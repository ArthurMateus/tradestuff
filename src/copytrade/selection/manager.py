"""The follow manager (F6.AC2-AC7): runs a cycle and drives the feed, the signal detector and the ledger."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.config import Config
from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert, AlertSink
from copytrade.hl.errors import HlError, WsUserLimitError
from copytrade.hl.wallet import normalize_wallet
from copytrade.ledger.store import Ledger
from copytrade.recorder.ports import SOURCE_FAILURES, LeaderboardSource
from copytrade.recorder.registry import LeaderboardRow, parse_leaderboard
from copytrade.scoring.cycle import run_cycle as score_and_persist
from copytrade.scoring.models import CostModel, CycleResult, ScoreStore, WalletInputs
from copytrade.selection.models import (
    ALERT_LEADERBOARD_OUTAGE,
    ALERT_NO_ELIGIBLE,
    DECISION_DEFERRED,
    DECISION_JOIN,
    DECISION_SAFETY_DROP,
    DECISION_SWAP,
    KIND_CYCLE_OVERRUN,
    KIND_FOLLOW_DEFERRED,
    KIND_LEADER_PAUSED,
    KIND_SELECT_CYCLE,
    MIN_LEADERBOARD_ROWS,
    REASON_LEADER_PAUSED,
    REASON_NO_ELIGIBLE,
    REASON_NO_WS_SLOT,
    REASON_NOT_FOLLOWED,
    REASON_SAFETY_PAUSED,
    REASON_STATE_UNAVAILABLE,
    STATUS_APPLIED,
    STATUS_BACKFILLING,
    STATUS_LEADERBOARD_OUTAGE,
    STATUS_OVERRUN,
    CandidateList,
    CycleReport,
    Decision,
    Follow,
    FollowRegistry,
    InputsProvider,
    OpenShareSource,
    PolicyOutcome,
    ScreeningInputs,
    SelectionState,
    StateSource,
    WalletFeed,
)
from copytrade.selection.pause import LeaderPauseTracker
from copytrade.selection.policy import apply_cycle as apply_policy
from copytrade.selection.policy import safety_reason
from copytrade.selection.prefilter import ROTATE_AFTER_CYCLES, candidate_list

_log = logging.getLogger(__name__)

_MINUTE_MS = 60_000
_ENTRY_ACTIONS = frozenset({ActionKind.OPEN, ActionKind.ADD})
_OUTAGE_ERRORS: tuple[type[Exception], ...] = (*SOURCE_FAILURES, ValueError)  # ValueError: an unreadable body


def _payload(decision: Decision) -> dict[str, Any]:
    return {"kind": decision.kind, "wallet": decision.wallet, "replaces": decision.replaces, "reason": decision.reason}


class FollowManager:
    """See ``docs/sdlc/copytrade-v1/05-test-plan-F6.md`` for the pinned decisions.

    Joining a wallet: fetch its ``clearinghouseState`` (a failure means it is not joined this cycle), then
    ``registry.begin_follow(wallet, state, now_ms)``, then ``feed.subscribe_user(wallet)``. Releasing: ``feed.
    unsubscribe_user`` then ``registry.end_follow``. Distinct subscribed users never exceed ``hl.ws_max_unique_users``;
    a join or swap without a free slot is deferred (ledger ``follow_deferred`` with reason ``no_ws_slot``).

    All state is in memory (restart reconstruction belongs to the runner). Single-threaded. A ledger write failure
    propagates: the ledger refuses every later append, so the process stops there.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        config: Config,
        clock: Clock,
        ledger: Ledger,
        alerts: AlertSink,
        feed: WalletFeed,
        registry: FollowRegistry,
        states: StateSource,
        shares: OpenShareSource,
        leaderboard: LeaderboardSource,
        inputs: InputsProvider,
        scores: ScoreStore,
        costs: CostModel,
    ) -> None:
        self._config = config
        self._clock = clock
        self._ledger = ledger
        self._alerts = alerts
        self._feed = feed
        self._registry = registry
        self._states = states
        self._shares = shares
        self._leaderboard = leaderboard
        self._inputs = inputs
        self._scores = scores
        self._costs = costs
        self._pause = LeaderPauseTracker(config)
        self._max_users: int = config["hl.ws_max_unique_users"]
        self._interval_ms: int = config["scoring.interval_min"] * _MINUTE_MS
        self._max_cycle_ms: int = config["select.max_cycle_duration_min"] * _MINUTE_MS
        self._candidates_k: int = config["scoring.candidates_k"]
        self._min_account_value = config["gate.min_account_value_usd"]
        self._excluded: frozenset[str] = frozenset(a.lower() for a in config["gate.exclude_addresses"])
        self._join_confirm: int = config["select.join_confirm_cycles"]
        self._state = SelectionState(followed={}, join_streaks={})
        self._subscribed: set[str] = set()  # followed wallets plus dropped wallets held for their open shares
        self._safety_dropped: set[str] = set()
        self._next_due_ms: int | None = None
        self._eligible_count = 0
        self._no_eligible = False
        self._no_eligible_alerted = False
        self._outage_alerted = False
        self._ineligible_streak: dict[str, int] = {}  # RO1: consecutive scored cycles a candidate was ineligible

    # --- views -----------------------------------------------------------------------------------------------

    @property
    def followed(self) -> frozenset[str]:
        """Wallets whose new opens we copy."""
        return frozenset(self._state.followed)

    @property
    def subscribed(self) -> frozenset[str]:
        """Followed wallets plus dropped wallets still held for their open shares."""
        return frozenset(self._subscribed)

    @property
    def next_due_ms(self) -> int | None:
        """When the next cycle should start (``None`` before the first cycle)."""
        return self._next_due_ms

    def due(self) -> bool:
        """True before the first cycle, then once the clock reaches ``next_due_ms``."""
        return self._next_due_ms is None or self._clock.now_ms() >= self._next_due_ms

    def restore(self, followed: Mapping[str, Follow], *, subscribed: Iterable[str], paused: Iterable[str]) -> None:
        """Load what an earlier run left (R0 startup reload, from the ledger) into a FRESH manager: the followed set,
        the wallets whose fills stay subscribed (followed ones plus dropped ones held for an open share) and the
        wallets the copy-result rule paused (never followed again, in this or any later process). The detector
        rebuilds its own follow state from the ledger, so it is not told again. The next cycle is due at once.

        Raises:
            ValueError: the manager is not fresh.
            WsUserLimitError: more wallets than ``hl.ws_max_unique_users`` (the limit was lowered since).
        """
        if self._state.followed or self._subscribed or self._next_due_ms is not None:
            raise ValueError("restore needs a fresh follow manager")
        for wallet in paused:
            self._pause.restore_paused(wallet)
            self._safety_dropped.add(wallet.lower())
        self._state = SelectionState(
            followed={w: f for w, f in followed.items() if not self._pause.is_paused(w)}, join_streaks={}
        )
        for wallet in sorted(set(subscribed)):
            self._feed.subscribe_user(normalize_wallet(wallet))
            self._subscribed.add(wallet)

    # --- cycles ----------------------------------------------------------------------------------------------

    def run_cycle(self, *, p95_latency_s: Decimal | None) -> CycleReport:
        """One full cycle at ``clock.now_ms()``: fetch the leaderboard, set the candidates, and (only when the
        inputs provider is ``complete``) refresh and score candidates plus followed wallets with F5's ``run_cycle``
        and apply the result. Always ledgers a ``select_cycle`` record."""
        started_ms = self._clock.now_ms()
        self._next_due_ms = started_ms + self._interval_ms  # anchored to this start, whatever happens below
        found = self._fetch_candidates()
        if found is None:
            return self._leaderboard_outage(started_ms, p95_latency_s)
        self._outage_alerted = False
        candidates = self._set_candidates(found)
        if not self._inputs.complete:
            return self._finish(STATUS_BACKFILLING, (), started_ms)
        result = self._score([*candidates, *sorted(self._subscribed - set(candidates))], p95_latency_s)
        finished_ms = self._clock.now_ms()
        if finished_ms - started_ms > self._max_cycle_ms:
            self._ledger.append(KIND_CYCLE_OVERRUN, {"started_ms": started_ms, "finished_ms": finished_ms})
            _log.warning(
                "selection cycle overran, the followed set is kept",
                extra={"event": "cycle_overrun", "started_ms": started_ms, "finished_ms": finished_ms},
            )
            return self._finish(STATUS_OVERRUN, (), started_ms)
        return self._apply(result, now_ms=self._clock.now_ms() if result is None else result.t_ms)

    def apply_cycle(self, result: CycleResult, *, now_ms: int) -> CycleReport:
        """Apply an already scored cycle (no leaderboard, no backfill gate, no overrun check)."""
        return self._apply(result, now_ms=now_ms)

    def _set_candidates(self, found: CandidateList) -> list[str]:
        """Hand stage 1's list to the inputs provider and return the wallets to score. A provider that runs the screen
        gets the whole list (it screens in order until ``scoring.candidates_k`` wallets are OK) and the followed wallets
        to keep; any other gets the first ``scoring.candidates_k`` rows."""
        if isinstance(self._inputs, ScreeningInputs):
            self._inputs.set_screen_plan(found, keep=sorted({*self._state.followed, *self._subscribed}))
            return self._inputs.candidates()
        candidates = [row.address for row in found.rows[: self._candidates_k]]
        self._inputs.set_candidates(candidates)
        return candidates

    def _fetch_candidates(self) -> CandidateList | None:
        """Stage 1 of the candidate screen over the leaderboard (no request besides the leaderboard itself), or ``None``
        on an outage. The row figures are self-reported: they only decide whom to look at, never who is followed."""
        try:
            board = parse_leaderboard(self._leaderboard.fetch())
        except _OUTAGE_ERRORS as exc:
            _log.warning(
                "leaderboard unavailable", extra={"event": "leaderboard_failed", "error_type": type(exc).__name__}
            )
            return None
        if board.row_count < MIN_LEADERBOARD_ROWS:
            _log.warning(
                "leaderboard has too few rows",
                extra={"event": "leaderboard_short", "rows": board.row_count, "minimum": MIN_LEADERBOARD_ROWS},
            )
            return None
        valid = [row for row in board.rows if _is_address(row.address)]
        first_of: dict[str, LeaderboardRow] = {}
        for row in valid:
            first_of.setdefault(row.address, row)  # the first row of an address wins, in served order
        found = candidate_list(
            list(first_of.values()),
            excluded=self._excluded,
            min_account_value=self._min_account_value,
            k=self._candidates_k,
        )
        _log.info(
            "candidate prefilter: rows=%d ranked=%d candidates=%d",
            board.row_count,
            found.ranked_count,
            len(found.rows),
            extra={
                "event": "candidate_prefilter",
                "rows": board.row_count,
                "ranked": found.ranked_count,
                "candidates": len(found.rows),
            },
        )
        return found

    def _score(self, wallets: Sequence[str], p95_latency_s: Decimal | None) -> CycleResult | None:
        """Refresh and score ``wallets`` at the time the data was gathered, persisting through F5 (once). A wallet
        that cannot be refreshed is scored on what is held (F5 marks it stale); one with nothing held is left out."""
        inputs: list[WalletInputs] = []
        for wallet in wallets:
            try:
                self._inputs.refresh(wallet)
            except (HlError, OSError) as exc:
                _log.warning(
                    "refresh failed, scoring on held data",
                    extra={"event": "refresh_failed", "wallet": wallet, "error_type": type(exc).__name__},
                )
            held = self._inputs.inputs(wallet, self._clock.now_ms())
            if held is not None:
                inputs.append(held)
        if not inputs:
            return None
        return score_and_persist(
            self._scores,
            inputs,
            cfg=self._config,
            t_ms=self._clock.now_ms(),
            costs=self._costs,
            p95_latency_s=p95_latency_s,
        )

    def _leaderboard_outage(self, started_ms: int, p95_latency_s: Decimal | None) -> CycleReport:
        """Keep the followed set, add nobody, alert once per outage, keep re-scoring the followed wallets from fills.
        A safety trigger (blow-up flag, G15) still drops a followed wallet; nothing else changes."""
        if not self._outage_alerted:
            self._outage_alerted = self._send(
                Alert(
                    kind=ALERT_LEADERBOARD_OUTAGE,
                    message="The leaderboard is unavailable: the followed set is kept and nobody is added.",
                )
            )
        result = self._score(sorted(self._subscribed), p95_latency_s)
        decisions: list[Decision] = []
        if result is not None:
            by_address = {s.address: s for s in result.scores}
            paused = self._pause.paused()
            for wallet in sorted(self._state.followed):
                reason = safety_reason(by_address.get(wallet), paused=wallet in paused)
                if reason is not None:
                    decisions.append(Decision(DECISION_SAFETY_DROP, wallet, None, reason))
            self._drop_followed([d.wallet for d in decisions], safety=True)
        return self._finish(STATUS_LEADERBOARD_OUTAGE, tuple(decisions), started_ms)

    def _apply(self, result: CycleResult | None, *, now_ms: int) -> CycleReport:
        if result is None:  # no wallet had any data at all: nothing to apply, nobody can be followed on no data
            result = CycleResult(t_ms=now_ms, scores=())
        outcome = apply_policy(self._config, self._state, result, now_ms=now_ms, paused=self._pause.paused())
        decisions = self._enact(outcome, now_ms)
        self._rotate_ineligible(result)
        self._eligible_count = outcome.eligible_count
        self._track_no_eligible(outcome.no_eligible)
        return self._finish(STATUS_APPLIED, decisions, now_ms)

    def _rotate_ineligible(self, result: CycleResult) -> None:
        """RO1: a candidate that is not followed and was ineligible in ``ROTATE_AFTER_CYCLES`` consecutive scored cycles
        is cooled down for ``ROTATE_COOLDOWN_H``, so the slots go on down the ranked list instead of staying on wallets
        that keep failing the gates. One eligible cycle starts the count over; a cycle that scored nobody counts for
        nobody. The cooldown applies from the next cycle's candidate list."""
        if not isinstance(self._inputs, ScreeningInputs):
            return
        scored = {score.address for score in result.scores}
        self._ineligible_streak = {w: n for w, n in self._ineligible_streak.items() if w in scored}  # not consecutive
        rotated: list[str] = []
        for score in result.scores:
            wallet = score.address
            if score.eligible or wallet in self._state.followed or wallet in self._subscribed:
                self._ineligible_streak.pop(wallet, None)
                continue
            streak = self._ineligible_streak.get(wallet, 0) + 1
            if streak >= ROTATE_AFTER_CYCLES:
                self._ineligible_streak.pop(wallet, None)
                rotated.append(wallet)
            else:
                self._ineligible_streak[wallet] = streak
        if rotated:
            self._inputs.rotate(rotated)
            _log.info(
                "candidates rotated out after %d ineligible cycles: %d",
                ROTATE_AFTER_CYCLES,
                len(rotated),
                extra={"event": "candidates_rotated", "wallets": len(rotated)},
            )

    # --- carrying out the policy's decisions ----------------------------------------------------------------

    def _enact(self, outcome: PolicyOutcome, now_ms: int) -> tuple[Decision, ...]:
        """Drops first (a dropped wallet with no open share frees its slot at once), then joins and swaps. A join or
        swap that cannot be carried out is reverted in the state (the candidate keeps its streak) and reported as a
        deferred decision."""
        followed = dict(outcome.state.followed)
        streaks = dict(outcome.state.join_streaks)
        reported: list[Decision] = []
        for decision in outcome.decisions:
            if decision.kind in (DECISION_JOIN, DECISION_SWAP):
                deferral = self._admit(decision.wallet, now_ms)
                if deferral is None:
                    if decision.replaces is not None:
                        self._release(decision.replaces)
                    self._safety_dropped.discard(decision.wallet)
                    reported.append(decision)
                    continue
                followed.pop(decision.wallet, None)
                streaks[decision.wallet] = self._join_confirm
                if decision.replaces is not None:
                    followed[decision.replaces] = self._state.followed[decision.replaces]
                deferred = Decision(DECISION_DEFERRED, decision.wallet, decision.replaces, deferral)
                self._ledger.append(
                    KIND_FOLLOW_DEFERRED, {"wallet": decision.wallet, "reason": deferral, "t_ms": now_ms}
                )
                reported.append(deferred)
                continue
            if decision.kind == DECISION_SAFETY_DROP:
                self._safety_dropped.add(decision.wallet)
            self._release(decision.wallet)
            reported.append(decision)
        self._state = SelectionState(followed=followed, join_streaks=streaks)
        return tuple(reported)

    def _admit(self, wallet: str, now_ms: int) -> str | None:
        """Start following ``wallet``: ``None`` when done, else the reason it was deferred. A wallet still held for its
        open shares is already subscribed and already known to the detector, so it only changes status."""
        if wallet in self._subscribed:
            return None
        if len(self._subscribed) >= self._max_users:
            return REASON_NO_WS_SLOT
        try:
            state = self._states.clearinghouse_state(wallet)
        except (HlError, OSError) as exc:
            _log.warning(
                "clearinghouseState unavailable, the wallet is not joined this cycle",
                extra={"event": "follow_state_failed", "wallet": wallet, "error_type": type(exc).__name__},
            )
            return REASON_STATE_UNAVAILABLE
        self._registry.begin_follow(wallet, state, now_ms)
        try:
            self._feed.subscribe_user(normalize_wallet(wallet))
        except WsUserLimitError:
            self._registry.end_follow(wallet)
            return REASON_NO_WS_SLOT
        self._subscribed.add(wallet)
        return None

    def _release(self, wallet: str) -> None:
        """``wallet`` is no longer followed: release its subscription, unless open shares still need its fills."""
        if not self._shares.has_open_shares(wallet):
            self._unsubscribe(wallet)

    def _unsubscribe(self, wallet: str) -> None:
        self._feed.unsubscribe_user(wallet)
        self._subscribed.discard(wallet)
        self._registry.end_follow(wallet)

    def _drop_followed(self, wallets: Sequence[str], *, safety: bool) -> None:
        followed = dict(self._state.followed)
        for wallet in wallets:
            del followed[wallet]
            if safety:
                self._safety_dropped.add(wallet)
            self._release(wallet)
        self._state = SelectionState(followed=followed, join_streaks=self._state.join_streaks)

    def tick(self) -> None:
        """Release dropped wallets whose last share has closed. Call at least once a second."""
        for wallet in sorted(self._subscribed - set(self._state.followed)):
            if not self._shares.has_open_shares(wallet):
                self._unsubscribe(wallet)

    # --- our own copy results ---------------------------------------------------------------------------------

    def on_copy_closed(self, wallet: str, *, pnl_usd: Decimal, equity_usd: Decimal) -> None:
        """Feed one closed copy to the leader pause; a trip drops the wallet at once (safety drop)."""
        key = wallet.lower()
        if not self._pause.record_copy_result(key, pnl_usd=pnl_usd, equity_usd=equity_usd):
            return
        self._safety_dropped.add(key)
        if key in self._state.followed:
            self._drop_followed([key], safety=True)
        self._ledger.append(KIND_LEADER_PAUSED, {"wallet": key, "t_ms": self._clock.now_ms()})
        _log.warning("leader paused", extra={"event": "leader_paused", "wallet": key, "reason": REASON_SAFETY_PAUSED})

    def refusal_reason(self, wallet: str, action: ActionKind) -> str | None:
        """For OPEN and ADD: ``leader_paused`` (safety dropped or paused), else ``no_eligible_leaders`` (last cycle had
        no eligible wallet), else ``not_followed``, else None. Reduces and closes are never refused."""
        if action not in _ENTRY_ACTIONS:
            return None
        key = wallet.lower()
        if key in self._safety_dropped or self._pause.is_paused(key):
            return REASON_LEADER_PAUSED
        if self._no_eligible:
            return REASON_NO_ELIGIBLE
        if key not in self._state.followed:
            return REASON_NOT_FOLLOWED
        return None

    # --- reporting --------------------------------------------------------------------------------------------

    def _finish(self, status: str, decisions: tuple[Decision, ...], t_ms: int) -> CycleReport:
        followed = tuple(sorted(self._state.followed))
        self._ledger.append(
            KIND_SELECT_CYCLE,
            {
                "t_ms": t_ms,
                "status": status,
                "eligible_count": self._eligible_count,
                "followed": list(followed),
                "decisions": [_payload(d) for d in decisions],
            },
        )
        _log.info(
            "selection cycle",
            extra={
                "event": "select_cycle",
                "status": status,
                "followed": len(followed),
                "decisions": len(decisions),
            },
        )
        return CycleReport(status=status, decisions=decisions, followed=followed, eligible_count=self._eligible_count)

    def _track_no_eligible(self, none_eligible: bool) -> None:
        """One alert per episode of a cycle with no eligible wallet; the flag drives ``refusal_reason``."""
        self._no_eligible = none_eligible
        if not none_eligible:
            self._no_eligible_alerted = False
        elif not self._no_eligible_alerted:
            self._no_eligible_alerted = self._send(
                Alert(
                    kind=ALERT_NO_ELIGIBLE,
                    message="No eligible leader: new opens and adds are refused until one qualifies.",
                )
            )

    def _send(self, alert: Alert) -> bool:
        """Deliver an alert; False (to be retried by the caller's next cycle) when the sink fails."""
        try:
            self._alerts.send(alert)
        except OSError as exc:
            _log.warning(
                "alert delivery failed, retrying next cycle",
                extra={"event": "alert_failed", "kind": alert.kind, "error_type": type(exc).__name__},
            )
            return False
        return True


def _is_address(value: str) -> bool:
    try:
        normalize_wallet(value)
    except HlError:
        return False
    return True
