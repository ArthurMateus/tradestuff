"""Incremental candidate backfill under the rate budget (F6.AC4)."""

from __future__ import annotations

import logging
import math
import re
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import NamedTuple

from copytrade.core.clock import Clock
from copytrade.core.config import Config
from copytrade.hl import models as hl
from copytrade.hl.budget import Priority
from copytrade.hl.errors import HlBudgetError, HlError, HlRateLimitedError, HlSchemaError
from copytrade.hl.rest import HlRestClient
from copytrade.recorder.ports import CandleSource
from copytrade.scoring import models as sc
from copytrade.scoring.reconstruct import is_core_perp
from copytrade.selection.models import FILLS_PER_PAGE, HL_FILLS_LIMIT, CandidateList, ScreenRow
from copytrade.selection.prefilter import (
    EMPTY_COOLDOWN_H,
    KEEP_RANK_MULT,
    ROTATE_COOLDOWN_H,
    SCREEN_COOLDOWN_H,
    SCREEN_MAX_PER_CYCLE,
    TOO_ACTIVE_COOLDOWN_H,
)
from copytrade.selection.screen import ScreenThresholds, screen_page

_log = logging.getLogger(__name__)

_DAY_MS = 86_400_000
_HOUR_MS = 3_600_000
_CANDLE_INTERVAL = "1h"
_MAX_FILL_PAGES = 50  # 100 000 fills: a wallet with more in the window is too active to copy: dropped for a day
_FIRST_SLICE_PAGES = 2  # first slice of a wallet with others waiting: 240 of the 450 share, the light ones still fit
_MAX_PAGES_PER_STEP = 3  # 3 full pages (weight 120 each) fit one minute of the 450 scoring weight share
_MAX_BARS_PER_REQUEST = 4_800  # below the 5 000-candle cap of candleSnapshot
_BUDGET_KEY = ""  # the cooldown after a budget refusal belongs to no wallet
_WOULD_WAIT = re.compile(
    r"would wait (\d+(?:\.\d+)?) s"
)  # the fail-fast scoring sleeper's refusal text (runner.wiring)
_BUDGET_MARGIN_MS = 1_000  # added to the wait a budget refusal names
_PROGRESS_INTERVAL_MS = 60_000  # at most one progress line a minute while a pass is incomplete
_LIQUIDATION_MARK = "iquidat"  # "Liquidated Cross Long", "Liquidated Isolated Short", ...


def _figure(value: Decimal | None) -> str:
    return "unknown" if value is None else format(value, "f")


def _fill(raw: hl.Fill) -> sc.Fill:
    return sc.Fill(
        tid=raw.tid,
        time=raw.time_ms,
        coin=raw.coin,
        side=raw.side,
        sz=Decimal(raw.sz),
        px=Decimal(raw.px),
        start_position=Decimal(raw.start_position),
        closed_pnl=Decimal(raw.closed_pnl),
        fee=Decimal(raw.fee),
        crossed=raw.crossed,
        liquidation=raw.liquidation or _LIQUIDATION_MARK in raw.dir,
    )


def _candle(raw: hl.Candle) -> sc.Candle:
    return sc.Candle(
        open_ms=raw.open_ms,
        close_ms=raw.close_ms,
        o=Decimal(raw.open),
        hi=Decimal(raw.high),
        lo=Decimal(raw.low),
        c=Decimal(raw.close),
    )


def _portfolio(raw: dict[str, hl.PortfolioWindow], fetched_ms: int) -> sc.PortfolioSnapshot:
    return sc.PortfolioSnapshot(
        fetched_ms=fetched_ms,
        windows={
            name: sc.PortfolioWindow(
                account_value_history=tuple((ms, Decimal(v)) for ms, v in window.account_value_history),
                pnl_history=tuple((ms, Decimal(v)) for ms, v in window.pnl_history),
            )
            for name, window in raw.items()
        },
    )


def _clearinghouse(raw: hl.ClearinghouseState, fetched_ms: int) -> sc.ClearinghouseState:
    """``fetched_ms`` is our own clock (the scorer compares it with the cycle time). An open position whose
    unrealised P&L is not in the payload cannot feed the open-loss blow-up check, so the whole response is refused
    (fail closed)."""
    positions: list[sc.OpenPosition] = []
    for position in raw.positions:
        if position.unrealized_pnl is None:
            raise HlSchemaError(
                "an open position has no unrealizedPnl", endpoint="clearinghouseState", field="assetPositions"
            )
        positions.append(sc.OpenPosition(coin=position.coin, unrealized_pnl=Decimal(position.unrealized_pnl)))
    return sc.ClearinghouseState(
        fetched_ms=fetched_ms, account_value=Decimal(raw.account_value), positions=tuple(positions)
    )


class _FillsOutcome(Enum):
    DONE = "done"  # the present was reached
    DROPPED = "dropped"  # the first page showed an empty or too active wallet: dropped with its cooldown
    PAUSED = "paused"  # this step's page allowance is used up; the progress is kept
    STUCK = "stuck"  # a whole page inside one millisecond: the cursor cannot move
    CAPPED = "capped"  # ``_MAX_FILL_PAGES`` pages without reaching the present


@dataclass
class _Progress:
    """One wallet's unfinished fills fetch, kept across steps and failures: where to ask next, what was got."""

    cursor: int
    window_start: int  # the scoring window start when the fetch began: the truncation test must not drift with paging
    held: dict[int, sc.Fill]
    fetched: dict[int, hl.Fill] = field(default_factory=dict)
    pages: int = 0
    requests: int = 0  # every page asked for in this fetch, for the log (``pages`` restarts at the end of a fetch)
    last_page_ms: int = 0  # when the latest page came back: the fills are current as of then
    handoff: bool = False  # the first page is the candidate screen's page, absorbed without a second request
    page_done: _FillsOutcome | None = None  # how that page ended the fetch, if it did (a page that is not full)


@dataclass
class _Pass:
    """The counters of one pass over the candidates, from the first work to the last (for the progress line). Every
    counter only grows within a pass: a wallet that drops out stays counted as a candidate of the pass."""

    wallets: set[str]  # every wallet the pass had to backfill (kept ones and those screened OK)
    done: set[str]  # those whose backfill is complete
    screen_ok: int = 0
    screen_rejected: int = 0
    dropped: int = 0  # dropped by an early exit or as too active while being backfilled
    last_progress_ms: int | None = None


class _Scan(NamedTuple):
    """The state of the screening list: the next wallet that can be screened now, how many wallets wait out an error or
    rate limit cooldown, whether any wallet still has to be screened, and when the earliest of them can be tried."""

    ready: str | None
    cooling: int
    pending: bool
    wake_ms: int


class Backfiller:
    """Fetches scoring inputs for candidate wallets through the real REST client at SCORING priority (which paces
    itself on the rate budget). Satisfies ``copytrade.selection.models.InputsProvider``.

    Per wallet: fills (``userFillsByTime``; the first fetch starts ``scoring.window_days`` back, later ones after the
    last fill already held, de-duplicated by ``tid``), ``portfolio``, ``clearinghouseState``, ``userRole`` and, for each
    core perp coin seen in the fills, 1h candles through ``candles``. ``hl.Fill`` becomes ``scoring.Fill``; a fill
    whose ``dir`` contains ``iquidat`` has ``liquidation=True``.

    Decisions beyond that contract:
    - The other requests of a fetch are all or nothing: the wallet's held data is replaced only when every request of
      the fetch succeeded.
    - ``userFillsByTime`` is paged (2 000 fills a page) and resumable: one step or refresh requests at most
      ``_MAX_PAGES_PER_STEP`` pages of one wallet (``_FIRST_SLICE_PAGES`` on its first slice while others wait behind
      it, so a heavy wallet leaves room in the share for the light ones). The cursor and the fills got so far are kept
      across steps and failures, so a wallet of many pages finishes in about its own page count of requests and never
      restarts. An unfinished wallet goes behind the others in the queue and blocks ``complete`` until finished or
      dropped.
    - A fetch that reaches ``_MAX_FILL_PAGES`` pages without the present means the wallet is too active to copy: it is
      logged once (``backfill_too_active``), dropped from the candidates (the backfill can complete without it) and not
      fetched again for one day. A fetch whose cursor cannot move keeps what it got but does not advance
      ``fills_fetched_ms``, so the scorer sees the wallet as ``stale_input`` (fail closed) until a later refresh.
    - A fetch that ends cleanly with exactly ``HL_FILLS_LIMIT`` fills whose oldest is more than a day after the window
      start was cut by the API (only its 10 000 most recent fills are retrievable): the window is partial, so it is
      treated as too active (``reason`` ``too_active_truncated``), never scored.
    - Any other ``HlError`` starts a per-wallet cooldown of ``hl.backoff_base_s``, doubled for each consecutive failure
      up to ``hl.backoff_max_s`` (a budget refusal cools every wallet down); a skipped ``refresh`` is logged once per
      cooldown (``backfill_refresh_skipped``).
    - A wallet whose fetch ended in a persistent HTTP 429 is not asked again for ``hl.backoff_max_s`` seconds; the
      others go on meanwhile.
    - Candles are shared between wallets: a coin is fetched at most once per UTC hour, because a 1h bar that has closed
      never changes; ``candles_fetched_ms`` is the time the wallet's bars were last confirmed current.
    - ``userRole`` is requested once per wallet (again only after a failed attempt left it unknown).
    - Fills older than ``scoring.window_days`` are dropped (the scorer ignores them). ``funding`` and ``own_snapshots``
      stay empty (the REST client has no ``userFunding``; F5 falls back to ``perpMonth`` and to realised P&L).
    """

    def __init__(self, *, config: Config, clock: Clock, rest: HlRestClient, candles: CandleSource) -> None:
        self._window_ms: int = config["scoring.window_days"] * _DAY_MS
        self._rate_limit_cooldown_ms = math.ceil(config["hl.backoff_max_s"] * 1000)
        self._error_base_ms = math.ceil(config["hl.backoff_base_s"] * 1000)
        self._clock = clock
        self._rest = rest
        self._candle_source = candles
        self._held: dict[str, sc.WalletInputs] = {}
        self._undone: deque[str] = deque()
        self._progress: dict[str, _Progress] = {}
        self._rate_limited_until: dict[str, int] = {}
        self._too_active_until: dict[str, int] = {}
        self._empty_until: dict[str, int] = {}
        self._rejected_until: dict[str, int] = {}  # a screen rule S3-S9 failed
        self._rotated_until: dict[str, int] = {}  # RO1: ineligible in too many scored cycles
        self._error_until: dict[str, int] = {}
        self._error_streak: dict[str, int] = {}  # consecutive failed attempts (not 429) of a wallet
        self._skip_logged: dict[
            str, int
        ] = {}  # wallet -> ``until_ms`` of the cooldown whose skipped refresh was logged
        self._has_candidates = False
        self._complete = False
        self._thresholds = ScreenThresholds.from_config(config)
        self._k: int = config["scoring.candidates_k"]
        self._screening = (
            False  # a screen plan is set (``set_screen_plan``); else ``set_candidates`` wallets are not screened
        )
        self._rows: dict[str, ScreenRow] = {}
        self._ranked: tuple[str, ...] = ()
        self._ranked_count = 0
        self._keep: tuple[str, ...] = ()  # followed wallets: backfilled and scored whatever the screen says
        self._ok: dict[str, None] = {}  # screened OK, in the order they were admitted
        self._cycle_screens = 0
        self._pass: _Pass | None = None  # the pass in progress, if any
        self._bars: dict[str, tuple[sc.Candle, ...]] = {}
        self._bars_hour: dict[str, int] = {}

    @property
    def complete(self) -> bool:
        """True once every wallet of the candidate list has been fetched at least once (or dropped as too active), then
        latched. False before ``set_candidates`` has been called (fail closed)."""
        return self._complete

    def set_candidates(self, wallets: Sequence[str]) -> None:
        """Set the candidate list (lower-cased, de-duplicated, order kept) and stop screening: every listed wallet is
        backfilled in full (the first page still exits early for an empty or too active wallet). Data already fetched is
        kept, and so is the progress of a wallet still listed; a wallet dropped as too active returns one day after it
        was dropped."""
        self._screening = False
        self._ranked, self._rows, self._keep, self._ok = (), {}, (), {}
        self._rebuild(list(dict.fromkeys(wallet.lower() for wallet in wallets)))

    def set_screen_plan(self, plan: CandidateList, *, keep: Iterable[str]) -> None:
        """Start a cycle of the candidate screen (R3). ``plan`` is stage 1's list in screening order, ``keep`` the
        wallets that are always backfilled and scored (followed ones): never screened, never dropped by a screen.

        The wallets screened OK in earlier cycles keep their slot while they are ranked within the top
        ``KEEP_RANK_MULT`` x ``scoring.candidates_k`` and in no cooldown (L3); the other slots are filled by ``step``,
        screening the list in order until ``scoring.candidates_k`` wallets are OK or ``SCREEN_MAX_PER_CYCLE`` screens of
        this cycle are spent. A wallet in a cooldown is skipped."""
        self._screening = True
        self._rows = {row.address: row for row in plan.rows}
        self._ranked = tuple(row.address for row in plan.rows)
        self._ranked_count = plan.ranked_count
        self._keep = tuple(dict.fromkeys(wallet.lower() for wallet in keep))
        self._cycle_screens = 0
        now = self._clock.now_ms()
        rank = {address: i for i, address in enumerate(self._ranked[: plan.ranked_count])}
        within = min(KEEP_RANK_MULT * self._k, plan.ranked_count)
        self._ok = {
            wallet: None
            for wallet in self._ok
            if rank.get(wallet, within) < within and wallet not in self._keep and not self._screen_blocked(wallet, now)
        }
        self._rebuild(self.candidates())

    def candidates(self) -> list[str]:
        """The wallets to backfill, refresh and score: the kept (followed) ones, then those screened OK."""
        return list(dict.fromkeys((*self._keep, *self._ok)))

    def rotate(self, wallets: Iterable[str]) -> None:
        """RO1: cool the wallets down for ``ROTATE_COOLDOWN_H``. They are neither screened nor admitted from the next
        ``set_screen_plan`` on (until then they are refreshed as before)."""
        until = self._clock.now_ms() + ROTATE_COOLDOWN_H * _HOUR_MS
        for wallet in wallets:
            self._rotated_until[wallet.lower()] = until

    def _rebuild(self, wanted: list[str]) -> None:
        now = self._clock.now_ms()
        for table in (self._too_active_until, self._empty_until, self._rejected_until, self._rotated_until):
            for wallet in [w for w, until in table.items() if until <= now]:
                del table[wallet]
        self._progress = {w: progress for w, progress in self._progress.items() if w in wanted}
        self._undone = deque(
            wallet
            for wallet in wanted
            if (wallet not in self._held or self._handed_off(wallet))
            and wallet not in self._too_active_until
            and wallet not in self._empty_until
        )
        self._has_candidates = self._screening or bool(wanted)
        self._open_pass(wanted)
        self._latch()

    def _handed_off(self, wallet: str) -> bool:
        progress = self._progress.get(wallet)
        return progress is not None and progress.handoff

    def step(self) -> bool:
        """Fetch the next wallet that has never been fetched (blocking while the budget paces it), at most
        ``_MAX_PAGES_PER_STEP`` fill pages of it. A wallet whose fetch raises ``HlError`` (or ``OSError`` from the
        candle source), or that is not finished yet, is left undone and retried after the others; one rate limited
        (HTTP 429) waits out its cooldown. Returns False when no wallet can be fetched now."""
        self._report_progress()
        wallet = self._next_ready()
        if wallet is None:
            return self._screen_next()
        try:
            inputs = self._collect(wallet, _MAX_PAGES_PER_STEP)
        except (HlError, OSError) as exc:
            self._start_cooldown(wallet, exc)
            self._log_failure(wallet, exc)
            self._undone.append(wallet)
        else:
            self._reset_errors(wallet)
            if inputs is not None:
                self._held[wallet] = inputs
            elif not self._dropped(wallet):
                self._undone.append(wallet)  # unfinished: its progress is kept, it goes behind the others
        self._latch()
        return True

    def _screen_next(self) -> bool:
        """Screen the next wallet of the list, if one can be screened now. True when a request was made."""
        wallet = self._scan().ready
        if wallet is None:
            self._latch()
            return False
        self._screen(wallet)
        self._latch()
        return True

    def _screen(self, wallet: str) -> None:
        """Stage 2 for one wallet: ONE ``userFillsByTime`` page from the window start (exactly backfill page 1). A fetch
        or schema error is not a screen: the wallet's error cooldown starts and it is tried again."""
        now = self._clock.now_ms()
        try:
            page = self._rest.user_fills_by_time(wallet, now - self._window_ms, None, priority=Priority.SCORING)
        except (HlError, OSError) as exc:
            self._start_cooldown(wallet, exc)
            self._log_failure(wallet, exc)
            return
        self._reset_errors(wallet)
        result = screen_page(
            tuple(_fill(raw) for raw in page),
            full=len(page) >= FILLS_PER_PAGE,
            now_ms=now,
            account_value=self._rows[wallet].account_value,
            thresholds=self._thresholds,
        )
        self._cycle_screens += 1
        _log.info(
            "candidate screened: wallet=%s outcome=%s failed=%s not_evaluable=%s",
            wallet,
            "ok" if result.ok else "rejected",
            ",".join(result.failed) or "none",
            ",".join(result.not_evaluable) or "none",
            extra={
                "event": "candidate_screened",
                "wallet": wallet,
                "outcome": "ok" if result.ok else "rejected",
                "failed": list(result.failed),
                "not_evaluable": list(result.not_evaluable),
            },
        )
        if result.ok:
            self._admit(wallet, page, now)
            self._count(screen_ok=1)
            return
        self._count(screen_rejected=1)
        if "S1" in result.failed:
            self._drop_empty(wallet, screened=True)
        elif "S2" in result.failed:
            self._drop_too_active(wallet, 1, reason="too_active_first_page", screened=True)
        else:
            self._rejected_until[wallet] = now + SCREEN_COOLDOWN_H * _HOUR_MS

    def _admit(self, wallet: str, page: Sequence[hl.Fill], now_ms: int) -> None:
        """A wallet that passed the screen takes its slot. Its screen page IS its backfill page 1: it goes into the
        fetch progress, so the backfill continues after the page's last fill (a page that is not full is all of it)."""
        progress = self._start_progress(wallet, now_ms)
        progress.handoff = True
        progress.page_done = self._absorb(progress, page)
        self._ok[wallet] = None
        self._undone.append(wallet)

    def refresh(self, wallet: str) -> None:
        """Incremental fetch for one wallet (at most ``_MAX_PAGES_PER_STEP`` fill pages; the rest follows on the next
        call). Nothing is sent for a wallet in a cooldown (too active, rate limited or after an error); the first
        skipped refresh of a cooldown is logged. An ``HlError`` leaves the old data in place, starts the wallet's
        cooldown and propagates."""
        key = wallet.lower()
        cooldown = self._cooldown(key)
        if cooldown is not None:
            self._log_refresh_skipped(key, *cooldown)
            return
        try:
            inputs = self._collect(key, _MAX_PAGES_PER_STEP)
        except HlError as exc:
            self._start_cooldown(key, exc)
            raise
        self._reset_errors(key)
        if inputs is not None:
            self._held[key] = inputs
        if (inputs is not None or self._dropped(key)) and key in self._undone:
            self._undone.remove(key)
            self._latch()

    def inputs(self, wallet: str, t_ms: int) -> sc.WalletInputs | None:
        """The held inputs, or ``None`` when nothing has been fetched for ``wallet``. The scorer does the point-in-time
        filtering against the cycle time (10.1), so ``t_ms`` does not select anything here."""
        del t_ms
        return self._held.get(wallet.lower())

    # --- internals ---------------------------------------------------------------------------------------------

    def _latch(self) -> None:
        """Complete when every wallet to backfill is done and nothing is left to screen in this cycle: the list is
        exhausted, ``scoring.candidates_k`` wallets are OK or the cycle's screens are spent. It does not matter whether
        anybody passed: the manager must go on to score the followed wallets."""
        if self._has_candidates and not self._has_work():
            self._complete = True
            self._close_pass()

    def _has_work(self) -> bool:
        return bool(self._undone) or self._scan().pending

    def _open_pass(self, wanted: list[str]) -> None:
        """A pass starts with the first work after an idle time and grows with the wallets a new plan adds."""
        if self._pass is None:
            if not self._has_work():
                return
            self._pass = _Pass(
                wallets=set(wanted), done={w for w in wanted if w in self._held and w not in self._undone}
            )
        else:
            self._pass.wallets.update(wanted)

    def _close_pass(self) -> None:
        if self._pass is None:
            return
        done, total = len(self._pass.done), len(self._pass.wallets)
        _log.info(
            "backfill pass complete: done=%d of %d candidates, screen_ok=%d, screen_rejected=%d, dropped=%d",
            done,
            total,
            self._pass.screen_ok,
            self._pass.screen_rejected,
            self._pass.dropped,
            extra={"event": "backfill_pass_complete", "done": done, "candidates": total},
        )
        self._pass = None

    def _report_progress(self) -> None:
        """At most one INFO line a minute while a pass is incomplete: what is done, screened, dropped and waiting, and
        the seconds until the pass can try again (above 0 while it waits for the rate budget or a cooldown)."""
        if self._pass is None:
            return
        now = self._clock.now_ms()
        if self._pass.last_progress_ms is not None and now - self._pass.last_progress_ms < _PROGRESS_INTERVAL_MS:
            return
        self._pass.last_progress_ms = now
        scan = self._scan()
        budget_until = self._error_until.get(_BUDGET_KEY, 0)
        cooling, wakes = scan.cooling, [scan.wake_ms] if scan.pending else []
        for wallet in self._undone:
            until = max(self._rate_limited_until.get(wallet, 0), self._error_until.get(wallet, 0))
            cooling += until > now
            wakes.append(max(until, budget_until))
        retry_s = math.ceil(max(min(wakes, default=now) - now, 0) / 1000)
        screen_ok, screen_rejected = self._pass.screen_ok, self._pass.screen_rejected
        # the wallets of the pass so far plus the slots that may still be filled from the screening list
        total = len(self._pass.wallets) + max(min(self._k - len(self._ok), len(self._ranked)), 0)
        _log.info(
            "backfill progress: done=%d of %d candidates, screened=%d, screen_ok=%d, screen_rejected=%d, dropped=%d, "
            "cooling=%d, next retry in %d s",
            len(self._pass.done),
            total,
            screen_ok + screen_rejected,
            screen_ok,
            screen_rejected,
            self._pass.dropped,
            cooling,
            retry_s,
            extra={"event": "backfill_progress", "done": len(self._pass.done), "candidates": total},
        )

    def _screen_blocked(self, wallet: str, now: int) -> bool:
        """A decision about the wallet (screen outcome, early exit, rotation) keeps it out until its cooldown ends."""
        return any(
            table.get(wallet, 0) > now
            for table in (self._rejected_until, self._empty_until, self._too_active_until, self._rotated_until)
        )

    def _scan(self) -> _Scan:
        """Walk the screening list in order. A wallet that is OK, kept, or in a decision cooldown is passed over. While
        the budget refuses, every pending wallet waits: the walk stops at the first one."""
        if not self._screening or len(self._ok) >= self._k or self._cycle_screens >= SCREEN_MAX_PER_CYCLE:
            return _Scan(None, 0, False, 0)
        now = self._clock.now_ms()
        budget_until = self._error_until.get(_BUDGET_KEY, 0)
        cooling, wake = 0, None
        for wallet in self._ranked:
            if wallet in self._ok or wallet in self._keep or self._screen_blocked(wallet, now):
                continue
            own = max(self._rate_limited_until.get(wallet, 0), self._error_until.get(wallet, 0))
            if own > now:
                cooling += 1
                wake = min(wake or own, max(own, budget_until))
            elif budget_until > now:
                return _Scan(None, cooling, True, min(wake or budget_until, budget_until))
            else:
                return _Scan(wallet, cooling, True, now)
        return _Scan(None, cooling, wake is not None, wake or 0)

    def _cooldown(self, wallet: str) -> tuple[str, int] | None:
        """The cooldown the wallet is in now as ``(reason, until_ms)``, the one that lasts longest; None when free."""
        now = self._clock.now_ms()
        active = [
            (reason, until)
            for reason, table, key in (
                ("too_active", self._too_active_until, wallet),
                ("empty", self._empty_until, wallet),
                ("screen_rejected", self._rejected_until, wallet),
                ("rate_limited", self._rate_limited_until, wallet),
                ("error_cooldown", self._error_until, wallet),
                ("error_cooldown", self._error_until, _BUDGET_KEY),
            )
            if (until := table.get(key, 0)) > now
        ]
        return max(active, key=lambda item: item[1], default=None)

    def _dropped(self, wallet: str) -> bool:
        """The wallet was dropped by an early exit: not fetched again until its cooldown is over."""
        return wallet in self._too_active_until or wallet in self._empty_until

    def _cooling_down(self, wallet: str) -> bool:
        return self._cooldown(wallet) is not None

    def _start_cooldown(self, wallet: str, exc: Exception) -> None:
        """A 429 waits ``hl.backoff_max_s``; any other failure waits ``hl.backoff_base_s`` doubled for every consecutive
        failure of the wallet, up to ``hl.backoff_max_s``. A budget refusal is not about one wallet (the scoring
        share is shared): it cools every wallet down, so one refusal is one record, not one per candidate."""
        now = self._clock.now_ms()
        if isinstance(exc, HlRateLimitedError):
            self._rate_limited_until[wallet] = now + self._rate_limit_cooldown_ms
            return
        if isinstance(exc, HlBudgetError) and (said := _WOULD_WAIT.search(str(exc))) is not None:
            # the wait the refusal named (it prints tenths of a second, so it can be that much short) plus a second
            self._error_until[_BUDGET_KEY] = now + math.ceil(float(said.group(1)) * 1000) + _BUDGET_MARGIN_MS
            return
        key = _BUDGET_KEY if isinstance(exc, HlBudgetError) else wallet
        streak = self._error_streak.get(key, 0) + 1
        self._error_streak[key] = streak
        wait_ms = min(self._error_base_ms * 2 ** min(streak - 1, 62), self._rate_limit_cooldown_ms)
        self._error_until[key] = now + wait_ms

    def _reset_errors(self, wallet: str) -> None:
        """A request cycle that went through: the wallet's failure streak (and the shared budget one) starts over."""
        self._error_streak.pop(wallet, None)
        self._error_streak.pop(_BUDGET_KEY, None)

    def _log_refresh_skipped(self, wallet: str, reason: str, until_ms: int) -> None:
        if self._skip_logged.get(wallet) == until_ms:
            return
        self._skip_logged[wallet] = until_ms
        _log.info(
            "refresh of a candidate skipped, it is cooling down: wallet=%s reason=%s until_ms=%d",
            wallet,
            reason,
            until_ms,
            extra={"event": "backfill_refresh_skipped", "wallet": wallet, "reason": reason, "until_ms": until_ms},
        )

    def _next_ready(self) -> str | None:
        """Take the first undone wallet that is not cooling down (the others keep their order); None when none is."""
        for _ in range(len(self._undone)):
            wallet = self._undone.popleft()
            if not self._cooling_down(wallet):
                return wallet
            self._undone.append(wallet)
        return None

    def _log_failure(self, wallet: str, exc: Exception) -> None:
        """One record per failed attempt: the message of an HL error names the request type and status, never the URL
        or the response body."""
        _log.warning(
            "backfill of a candidate failed, it will be retried: wallet=%s status=%s error=%s (%s)",
            wallet,
            getattr(exc, "status", None),
            exc,
            type(exc).__name__,
            extra={
                "event": "backfill_failed",
                "wallet": wallet,
                "status": getattr(exc, "status", None),
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )

    def _collect(self, wallet: str, max_pages: int) -> sc.WalletInputs | None:
        """One fetch of one wallet, resuming its fills progress. ``None`` when the fills are not finished (progress
        kept) or the wallet was dropped as too active. Nothing is stored until every request has succeeded."""
        previous = self._held.get(wallet)
        progress = self._progress.get(wallet)
        if progress is None:
            progress = self._start_progress(wallet, self._clock.now_ms())
        judge_first_page = previous is None and progress.requests == 0 and wallet not in self._keep
        outcome = self._fetch_fills(wallet, progress, max_pages, judge_first_page=judge_first_page)
        if outcome is _FillsOutcome.PAUSED or outcome is _FillsOutcome.DROPPED:
            return None
        if outcome is _FillsOutcome.CAPPED:
            self._drop_too_active(wallet, progress.pages)
            return None
        if outcome is _FillsOutcome.DONE and self._truncated(progress):
            self._drop_too_active(wallet, progress.requests, reason="too_active_truncated")
            return None
        fetched_ms = progress.last_page_ms  # the fills are current as of the latest page, not of the requests after it
        fills_fetched_ms: int | None = fetched_ms
        window_start = fetched_ms - self._window_ms
        held_fills = dict(progress.held)
        for raw in progress.fetched.values():
            held_fills.setdefault(raw.tid, _fill(raw))
        fills = tuple(sorted((f for f in held_fills.values() if f.time >= window_start), key=lambda f: (f.time, f.tid)))

        portfolio = _portfolio(self._rest.portfolio(wallet, priority=Priority.SCORING), self._clock.now_ms())
        clearinghouse = _clearinghouse(
            self._rest.clearinghouse_state(wallet, priority=Priority.SCORING), self._clock.now_ms()
        )
        role = previous.role if previous is not None else None
        if role is None:
            role = self._rest.user_role(wallet, priority=Priority.SCORING)
        coins = sorted({f.coin for f in fills if is_core_perp(f.coin)})
        candles = {coin: self._bars_for(coin) for coin in coins}
        candles_fetched_ms = self._clock.now_ms()

        if outcome is _FillsOutcome.STUCK:
            _log.warning(
                "fills backfill did not reach the present, the wallet stays stale: wallet=%s pages=%d fills=%d",
                wallet,
                progress.pages,
                len(progress.fetched),
                extra={
                    "event": "backfill_incomplete",
                    "wallet": wallet,
                    "pages": progress.pages,
                    "fills": len(progress.fetched),
                },
            )
            fills_fetched_ms = previous.fills_fetched_ms if previous is not None else None
        if previous is None and outcome is not _FillsOutcome.STUCK:
            _log.info(
                "backfill of a candidate complete: wallet=%s fills=%d pages=%d",
                wallet,
                len(fills),
                progress.requests,
                extra={"event": "backfill_complete", "wallet": wallet, "fills": len(fills), "pages": progress.requests},
            )
        if self._pass is not None:
            self._pass.wallets.add(wallet)
            self._pass.done.add(wallet)
        del self._progress[wallet]
        return sc.WalletInputs(
            address=wallet,
            fills=fills,
            fills_fetched_ms=fills_fetched_ms,
            funding=(),
            portfolios=(portfolio,),
            clearinghouse=(clearinghouse,),
            own_snapshots=(),
            candles_1h=candles,
            candles_fetched_ms=candles_fetched_ms,
            role=role,
            leaderboard_row=None,
        )

    @staticmethod
    def _truncated(progress: _Progress) -> bool:
        """The API kept only its ``HL_FILLS_LIMIT`` most recent fills (exactly that many came back, never more) and the
        oldest of them starts well inside the window (more than a day after its start): the window is partial although
        the paging ended cleanly."""
        if len(progress.fetched) != HL_FILLS_LIMIT:  # more than the limit came back: nothing was cut off
            return False
        return min(raw.time_ms for raw in progress.fetched.values()) > progress.window_start + _DAY_MS

    def _count(self, *, screen_ok: int = 0, screen_rejected: int = 0, dropped: int = 0) -> None:
        if self._pass is not None:
            self._pass.screen_ok += screen_ok
            self._pass.screen_rejected += screen_rejected
            self._pass.dropped += dropped

    def _drop_too_active(self, wallet: str, pages: int, *, reason: str = "too_active", screened: bool = False) -> None:
        _log.warning(
            "wallet has more fills in the window than can be fetched, dropped for a day: wallet=%s reason=%s pages=%d",
            wallet,
            reason,
            pages,
            extra={"event": "backfill_too_active", "wallet": wallet, "reason": reason, "pages": pages},
        )
        self._too_active_until[wallet] = self._clock.now_ms() + TOO_ACTIVE_COOLDOWN_H * _HOUR_MS
        self._count(dropped=not screened)
        self._error_streak.pop(wallet, None)
        self._progress.pop(wallet, None)
        self._ok.pop(wallet, None)

    def _drop_empty(self, wallet: str, *, screened: bool = False) -> None:
        """A wallet with no fill in the window (EX2): dropped for ``EMPTY_COOLDOWN_H``. The leaderboard row's volumes
        are logged when the row is known: a wallet the row called active but whose fills are empty means the row's
        volume is not this address's fills."""
        row = self._rows.get(wallet)
        volumes = "" if row is None else f" vlm_week={_figure(row.vlm_week)} vlm_month={_figure(row.vlm_month)}"
        _log.info(
            "wallet has no fill in the window, dropped for a week: wallet=%s reason=backfill_empty%s",
            wallet,
            volumes,
            extra={"event": "backfill_empty", "wallet": wallet, "reason": "backfill_empty"},
        )
        self._empty_until[wallet] = self._clock.now_ms() + EMPTY_COOLDOWN_H * _HOUR_MS
        self._count(dropped=not screened)
        self._error_streak.pop(wallet, None)
        self._progress.pop(wallet, None)
        self._ok.pop(wallet, None)

    def _start_progress(self, wallet: str, now_ms: int) -> _Progress:
        """A new fills fetch of ``wallet`` whose window starts ``scoring.window_days`` before ``now_ms``: after the
        fills already held, if any."""
        previous = self._held.get(wallet)
        window_start = now_ms - self._window_ms
        held_fills = {} if previous is None else {f.tid: f for f in previous.fills if f.time >= window_start}
        progress = _Progress(
            cursor=max((f.time for f in held_fills.values()), default=window_start),
            window_start=window_start,
            held=held_fills,
        )
        self._progress[wallet] = progress
        return progress

    def _absorb(self, progress: _Progress, page: Sequence[hl.Fill]) -> _FillsOutcome | None:
        """Take one page of fills into ``progress``; the outcome when it ends the fetch, else ``None`` (ask again)."""
        progress.pages += 1
        progress.requests += 1
        progress.last_page_ms = self._clock.now_ms()
        for raw in page:
            progress.fetched.setdefault(raw.tid, raw)
        if len(page) < FILLS_PER_PAGE:
            progress.pages = 0  # the next fetch of this wallet (an incremental one) starts counting afresh
            return _FillsOutcome.DONE
        last = max(raw.time_ms for raw in page)
        if last <= progress.cursor:
            return _FillsOutcome.STUCK
        progress.cursor = last
        return None

    def _first_page_exit(self, wallet: str, page: Sequence[hl.Fill]) -> bool:
        """EX2 and EX1 on the first page of a wallet's window: drop it when empty, or when it is full inside one day
        (2 000 fills in under 24 h: far too active, five pages or fifty would only confirm it)."""
        if not page:
            self._drop_empty(wallet)
            return True
        times = [raw.time_ms for raw in page]
        if len(page) >= FILLS_PER_PAGE and max(times) - min(times) < _DAY_MS:
            self._drop_too_active(wallet, 1, reason="too_active_first_page")
            return True
        return False

    def _fetch_fills(
        self, wallet: str, progress: _Progress, max_pages: int, *, judge_first_page: bool
    ) -> _FillsOutcome:
        """Pages of fills from the progress cursor on, at most ``max_pages`` requests; every page is recorded in
        ``progress`` as it arrives, so a failure or a pause loses nothing. The first page of a fetch that
        ``judge_first_page`` may end it at once (``DROPPED``)."""
        if progress.page_done is not None:  # the candidate screen's page was the whole fetch (or cannot be followed)
            return progress.page_done
        requested = 0
        allowance = max_pages if progress.pages or not self._undone else min(max_pages, _FIRST_SLICE_PAGES)
        while progress.pages < _MAX_FILL_PAGES:
            if requested == allowance:
                return _FillsOutcome.PAUSED
            page = self._rest.user_fills_by_time(wallet, progress.cursor, None, priority=Priority.SCORING)
            requested += 1
            if judge_first_page and requested == 1 and self._first_page_exit(wallet, page):
                return _FillsOutcome.DROPPED
            outcome = self._absorb(progress, page)
            if outcome is not None:
                return outcome
        return _FillsOutcome.CAPPED

    def _bars_for(self, coin: str) -> tuple[sc.Candle, ...]:
        """The coin's 1h bars of the window, fetched when the coin has not been fetched in the current UTC hour."""
        now = self._clock.now_ms()
        if self._bars_hour.get(coin) != now // _HOUR_MS:
            window_start = now - self._window_ms
            held = {b.open_ms: b for b in self._bars.get(coin, ()) if b.open_ms >= window_start}
            start = max((b.open_ms for b in held.values()), default=window_start)  # the last bar may have been partial
            for chunk_start in range(start, now + 1, _MAX_BARS_PER_REQUEST * _HOUR_MS):
                chunk_end = min(chunk_start + _MAX_BARS_PER_REQUEST * _HOUR_MS - 1, now)
                for raw in self._candle_source.fetch(coin, _CANDLE_INTERVAL, chunk_start, chunk_end):
                    held[raw.open_ms] = _candle(raw)
            self._bars[coin] = tuple(sorted(held.values(), key=lambda b: b.open_ms))
            self._bars_hour[coin] = now // _HOUR_MS
        return self._bars[coin]
