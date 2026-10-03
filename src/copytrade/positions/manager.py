"""The position manager (F12): per-leader shares, stops, mirrored exits, reconciliation and the missed-exit detector.

Every order and every stop goes through the risk gate (A1): this module never calls the broker's ``submit`` or
``place_stop``. It reads every ``Outcome.broker_events`` (and every ``advance_to``, mark and delisting) and books the
fills into the share book BEFORE the next gate call (the F10/F11 contracts), in two phases: all queued events are
applied first, then one follow-up action (a stop to place, a flip's open leg, a deferred leader signal) runs, so no
gate call is ever made on a book that is missing a fill the broker already produced.

Exits and stops are never blocked by this module's own failures: no exit depends on candles, the leader's state, the
entry policy, the exchange meta or the alert sink. Entries fail closed. State is in memory only (a restart rebuilds it
from the ledger: F13/R0).
"""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from decimal import Decimal
from functools import partial
from typing import Any, TypeVar

from copytrade.core.config import Config
from copytrade.core.domain import ActionKind
from copytrade.core.errors import ClockUnsyncedError
from copytrade.core.events import Alert, AlertSink
from copytrade.core.money import Price, Qty
from copytrade.hl.models import Fill
from copytrade.ledger.records import FillRecord
from copytrade.ledger.store import Ledger
from copytrade.paper.broker import PaperBroker
from copytrade.paper.settings import MONEY_CONTEXT
from copytrade.paper.types import BrokerEvent, MarkUpdate
from copytrade.positions import rules
from copytrade.positions.book import PositionBook
from copytrade.positions.settings import PositionSettings
from copytrade.positions.types import (
    CLOSED,
    OPEN,
    PENDING_ENTRY,
    CandleReader,
    EntryPolicy,
    LeaderFills,
    LeaderState,
    ShareState,
)
from copytrade.risk.gate import RiskGate
from copytrade.risk.ports import ExchangeTime
from copytrade.risk.types import (
    AddRequest,
    ExitRequest,
    FlattenReport,
    OpenRequest,
    Outcome,
    StopRequest,
)
from copytrade.signals.detector import signal_id as detector_signal_id
from copytrade.signals.models import Signal

_log = logging.getLogger(__name__)
_K = TypeVar("_K")

# found_by / case values of a missed-exit record
FOUND_LIVE = "live"
FOUND_RECONCILIATION = "reconciliation"
FOUND_DAILY_AUDIT = "daily_audit"
CASE_LATE = "late"
CASE_ORPHAN = "orphan"

# exit reasons we send
REASON_LEADER_CLOSE = "leader_close"
REASON_DROPPED_LEADER = "dropped_leader"
REASON_LEADER_REDUCE = "leader_reduce"
REASON_RECONCILE_CLOSE = "reconcile_close"
REASON_AUDIT_CLOSE = "audit_close"
REASON_ORPHAN_CLOSE = "orphan_close"
REASON_STOP_FAILED = "stop_failed"
REASON_CLOSE_REMAINDER = "close_remainder"

# fills that close a share by our own rules (the leader's later events on that position are ignored: first exit wins)
_OUR_EXITS = frozenset({"stop_loss", "take_profit", "liquidated", "delisted_force_settle"})
_ORPHAN_LEADER = "orphan"
_RETRY_TID = 0  # appended to the tids of a retried close: real tids are positive, synthetic ones negative
_RETRIED_REFUSALS = frozenset({"share_closed", "exceeds_position"})  # a fill got in first: the close is re-sized
_MIN_WINDOW_MS = 3_600_000
RECONCILE_RETRY_MS = 30_000  # a failed leader read is tried again after max(its wait hint, this), not a full interval
SEEN_LIMIT = 20_000  # the oldest remembered signal id / broker event is forgotten beyond this
CHECKPOINT_SEEN_SIGNALS = 500  # how many of the newest signal ids a checkpoint carries
_SHARE_FIELDS = tuple(f.name for f in fields(ShareState))


@dataclass
class _Track:
    """What the manager knows about a share that ``ShareState`` does not carry."""

    open_ms: int  # exchange time of the opening signal: leader fills before it never concern this share
    evidence_ms: int  # the last time the leader was known to hold the position
    close_ms: int | None = None
    closing: bool = False  # a full close of ours has been accepted and has not filled yet
    closing_ms: int | None = None
    stop_seq: int = 0
    sl_cid: str | None = None
    sl_qty: Decimal = Decimal(0)
    stops: dict[str, tuple[str, Decimal, Decimal]] = field(
        default_factory=dict
    )  # registered: cid -> kind, qty, trigger
    deferred: list[Signal] = field(default_factory=list)  # leader exits and adds that arrived before the entry filled


@dataclass(frozen=True)
class _LeaderExit:
    """A leader exit (``close`` or ``reduce``) to mirror, wherever it was found: a live signal, a reconciliation pass
    or the daily fill audit."""

    leader: str
    coin: str
    kind: str
    fraction: Decimal | None
    event_ms: int
    event_key: int  # the leader fill's tid (negative and unique when there is no fill)
    signal_id: str
    px: Price
    found_by: str
    case: str
    tids: tuple[int, ...]
    close_reason: str
    dated: bool = True  # False when the exchange time of the event is unknown: nothing is classified as missed now


@dataclass
class _Stretch:
    """An audit interval that could not be retrieved yet."""

    first_attempt_ms: int
    start_ms: int
    breached: bool = False


class PositionManager:
    """Books shares, places their stops, mirrors the leaders' exits and reconciles against the leaders and the broker.

    Methods that take events from the outside (``on_signals``, ``advance_to``, ``on_mark``, ``on_delist``,
    ``on_broker_events``, ``flatten``) book what the broker returns before they return. ``on_signals`` never raises
    for a skipped or failed signal: it logs and alerts. Everything else lets system failures (a broker or ledger
    failure) propagate to the supervisor, except ``reconcile`` and ``run_fill_audit`` when run by ``advance_to``.
    """

    def __init__(  # noqa: PLR0913 - the boundaries are injected
        self,
        *,
        config: Config,
        gate: RiskGate,
        broker: PaperBroker,
        book: PositionBook,
        ledger: Ledger,
        alerts: AlertSink,
        exchange_time: ExchangeTime,
        candles: CandleReader,
        leader_state: LeaderState,
        leader_fills: LeaderFills,
        policy: EntryPolicy,
        run_id: str,
    ) -> None:
        if type(run_id) is not str or not run_id:
            raise ValueError("run_id must be a non-empty string")
        self._settings = PositionSettings.from_config(config)
        self._gate = gate
        # The risk gate is the one way to an order (A1). Its two order methods are bound once here because F10's
        # static chokepoint test rejects a call to a method of that name written anywhere outside gate.py.
        self._submit_through_gate = gate.submit
        self._place_stop_through_gate = gate.place_stop
        self._broker = broker
        self._book = book
        self._ledger = ledger
        self._alerts = alerts
        self._exchange_time = exchange_time
        self._candles = candles
        self._leader_state = leader_state
        self._leader_fills = leader_fills
        self._policy = policy
        self._run_id = run_id

        self._tracks: dict[str, _Track] = {}
        self._entry_orders: dict[str, str] = {}  # client order id of an accepted entry -> its share id
        self._seen_signals: dict[str, None] = {}  # insertion-ordered and bounded (``SEEN_LIMIT``)
        self._seen_events: dict[tuple[object, ...], None] = {}
        self._tids_done: dict[str, set[int]] = {}  # per leader: every fill tid the manager has been told about
        self._handled: dict[tuple[str, int], int] = {}  # (leader, tid) -> exchange ms our mirror/skip was recorded
        self._leader_pos: dict[tuple[str, str], Decimal] = {}  # the leader's signed size as the signals say
        self._ours_won: set[tuple[str, str]] = set()  # our SL/TP closed the share; ignore the leader until flat
        # the open leg of a flip and the share whose close fill it waits for
        self._flip_wait: dict[tuple[str, str], tuple[Signal, str]] = {}
        self._dropped: set[str] = set()
        self._orphans_closing: set[str] = set()
        self._missed_logged: set[tuple[str, int, str]] = set()
        self._missed_count = 0
        self._synthetic_tid = 0

        self._events: deque[BrokerEvent] = deque()
        self._actions: deque[Callable[[], None]] = deque()
        self._draining = False

        self._last_ms = 0
        self._unsynced_logged: str | None = None  # the reason of the clock line already shown, until the clock works
        now = self._read_clock()
        self._audit_anchor_ms: int | None = now
        self._next_audit_ms: int | None = None if now is None else now + self._settings.fill_audit_interval_ms
        self._next_reconcile_ms: int | None = None
        self._reconcile_since: dict[str, int] = {}
        self._leader_retry_ms: dict[str, int] = {}  # leader -> when its failed read is tried again
        self._audit_end: dict[str, int] = {}
        self._audit_leaders: set[str] = set()
        self._stretches: dict[str, _Stretch] = {}

    # ================================================================================ signals (the F7 sink)

    def on_signals(self, signals: Sequence[Signal]) -> None:
        """Act on leader signals in order. Never raises for a skipped or failed signal (it is logged and alerted)."""
        for signal in signals:
            try:
                self._on_signal(signal)
            except Exception as exc:
                _log.exception(
                    "a leader signal could not be processed",
                    extra={"event": "positions_signal_failed", "signal_id": signal.signal_id},
                )
                self._alert("signal_error", f"{signal.coin} signal {signal.signal_id} failed: {type(exc).__name__}")

    def _on_signal(self, sig: Signal) -> None:
        if sig.signal_id in self._seen_signals:
            return
        _remember(self._seen_signals, sig.signal_id)
        self._tids_done.setdefault(sig.wallet, set()).add(sig.tid)
        key = (sig.wallet, sig.coin)
        self._flip_wait.pop(key, None)  # any later signal of the leader on the coin outdates a waiting flip open leg
        if sig.outcome is not None or sig.action is None or sig.is_long is None or sig.post_position is None:
            self._leader_pos.pop(key, None)  # nothing is inferred for these: the leader's size is unknown
            return
        self._leader_pos[key] = Decimal(sig.post_position) * (1 if sig.is_long else -1)
        self._sync()
        active = self._book.active(*key)
        if active is not None:
            track = self._tracks[active.share_id]
            track.evidence_ms = max(track.evidence_ms, sig.exchange_ts.ms)
        self._handle(sig)

    def _handle(self, sig: Signal) -> None:
        key = (sig.wallet, sig.coin)
        if sig.action is ActionKind.OPEN:
            self._handle_open(sig)
            return
        if key in self._ours_won:
            self._skip(sig, "first_exit_won")
            if self._ends_flat(sig):
                self._ours_won.discard(key)
            return
        share = self._book.active(*key)
        if share is None:
            self._skip(sig, "no_share")
        elif share.status == PENDING_ENTRY:
            self._tracks[share.share_id].deferred.append(sig)
        elif sig.action is ActionKind.ADD:
            self._handle_add(share, sig)
        elif sig.action is ActionKind.REDUCE:
            self._handle_reduce(share, sig)
        else:
            self._mirror_exit(share.share_id, self._exit_of_signal(sig, "close", None))

    @staticmethod
    def _ends_flat(sig: Signal) -> bool:
        if sig.action is ActionKind.CLOSE:
            return True
        return sig.action is ActionKind.REDUCE and (
            sig.post_position == 0 or (sig.reduce_fraction is not None and sig.reduce_fraction >= 1)
        )

    # ------------------------------------------------------------------------------------------------ opens

    def _handle_open(self, sig: Signal) -> None:
        key = (sig.wallet, sig.coin)
        self._ours_won.discard(key)  # the leader's next open is a new signal
        refusal = sig.refusal_reason()
        if refusal is not None:
            self._skip(sig, refusal)
            return
        active = self._book.active(*key)
        if active is not None and sig.from_flip and sig.leg == 1:
            self._flip_wait[key] = (sig, active.share_id)  # the close leg is still working: the open waits for its fill
            return
        if active is not None:
            self._skip(sig, "invalid_signal")
            self._alert("bad_signal", f"{sig.coin}: the leader opened but we still hold its share {active.share_id}")
            return
        self._open_share(sig)

    def _is_stale(self, sig: Signal) -> bool:
        """An entry decided on a signal older than ``filter.max_signal_age_ms`` (exchange time) is never sent."""
        return self._now_or_last() - sig.exchange_ts.ms > self._settings.max_signal_age_ms

    def _clear_flip_leg(self, share: ShareState) -> None:
        """The share a flip's open leg waits for will never close by a fill of ours: the leg dies with it."""
        key = (share.leader, share.coin)
        waiting = self._flip_wait.get(key)
        if waiting is not None and waiting[1] == share.share_id:
            del self._flip_wait[key]

    def _open_share(self, sig: Signal) -> None:
        if self._is_stale(sig):
            self._skip(sig, "stale_signal")
            return
        try:
            mult = self._policy.vol_mult(sig)
        except Exception:
            _log.exception("the entry policy failed", extra={"event": "positions_policy_failed"})
            mult = None
        if mult is None:
            self._skip(sig, "policy_veto")
            return
        is_long = bool(sig.is_long)
        atr = self._atr(sig.coin, self._now_or_last())
        if atr is None:
            self._skip(sig, "no_atr")
            return
        stop = rules.initial_stop(is_long=is_long, entry_px=sig.px, atr=atr, stop_atr_mult=self._settings.stop_atr_mult)
        if stop <= 0:
            self._skip(sig, "invalid_stop")
            return
        try:
            leader = self._leader_state.clearinghouse_state(sig.wallet)
        except Exception:
            _log.warning("the leader's state is unavailable", extra={"event": "positions_leader_state"}, exc_info=True)
            self._skip(sig, "no_leader_av")
            return
        share_id, trade_id = f"share:{sig.signal_id}", f"trade:{sig.signal_id}"
        request = OpenRequest(
            run_id=self._run_id,
            signal_id=sig.signal_id,
            leader=sig.wallet,
            coin=sig.coin,
            is_long=is_long,
            tids=(sig.tid,),
            trade_id=trade_id,
            share_id=share_id,
            decision_px=sig.px,
            stop_px=Price(stop),
            vol_mult=mult,
            leader_position_notional_usd=MONEY_CONTEXT.multiply(Decimal(sig.post_position or 0), sig.px),
            leader_account_value_usd=Decimal(leader.account_value),
            leader_av_time_ms=leader.time_ms,
        )
        outcome = self._submit_through_gate(request)
        if outcome.result is None or not outcome.result.accepted:
            self._book_events(outcome.broker_events)
            return  # refused: the gate (or the broker) has logged it; there is no share
        zero = Decimal(0)
        self._book.add(
            ShareState(
                share_id=share_id,
                trade_id=trade_id,
                signal_id=sig.signal_id,
                leader=sig.wallet,
                coin=sig.coin,
                is_long=is_long,
                status=PENDING_ENTRY,
                qty=Qty(0),
                entry_px=sig.px,
                initial_stop_px=Price(stop),
                current_stop_px=Price(stop),
                initial_risk_usd=zero,
                open_risk_usd=zero,
                max_committed_risk_usd=zero,
                atr=atr,
                best_px=sig.px,
                tp_done=False,
            )
        )
        opened_ms = sig.exchange_ts.ms
        self._tracks[share_id] = _Track(open_ms=opened_ms, evidence_ms=opened_ms)
        if outcome.decision.client_order_id is not None:
            self._entry_orders[outcome.decision.client_order_id] = share_id
        self._audit_leaders.add(sig.wallet)
        self._book_events(outcome.broker_events)  # only now: the share is registered before any event can name it

    def _handle_add(self, share: ShareState, sig: Signal) -> None:
        if self._wrong_direction(share, sig):
            return
        if self._tracks[share.share_id].closing:
            refusal: str | None = "invalid_signal"  # a close of ours is on its way: nothing is added to the share
        else:
            refusal = sig.refusal_reason() or ("stale_signal" if self._is_stale(sig) else None)
        if refusal is not None:
            self._skip(sig, refusal, share)
            return
        pre = sig.pre_position
        if pre is None or pre <= 0 or sig.size <= 0:
            self._skip(sig, "invalid_signal", share)
            self._alert("bad_signal", f"{sig.coin}: an add with no usable leader size ({sig.signal_id})")
            return
        atr = self._atr(sig.coin, self._now_or_last())
        if atr is None:
            self._skip(sig, "no_atr", share)
            return
        stop = rules.initial_stop(
            is_long=share.is_long, entry_px=sig.px, atr=atr, stop_atr_mult=self._settings.stop_atr_mult
        )
        if stop <= 0:
            self._skip(sig, "invalid_stop", share)
            return
        outcome = self._submit_through_gate(
            AddRequest(
                run_id=self._run_id,
                signal_id=sig.signal_id,
                leader=share.leader,
                coin=share.coin,
                is_long=share.is_long,
                tids=(sig.tid,),
                trade_id=share.trade_id,
                share_id=share.share_id,
                decision_px=sig.px,
                stop_px=Price(stop),
                current_stop_px=share.current_stop_px,
                our_share_qty=share.qty,
                leader_add_size=sig.size,
                leader_pre_add_position=pre,
            )
        )
        self._book_events(outcome.broker_events)
        if outcome.result is not None and outcome.result.accepted and outcome.decision.client_order_id is not None:
            self._entry_orders[outcome.decision.client_order_id] = share.share_id

    # ----------------------------------------------------------------------------------------------- exits

    def _wrong_direction(self, share: ShareState, sig: Signal) -> bool:
        """An add or reduce on the other side than our share (the leader flipped and we missed or still work on it):
        it is skipped, alerted with what the leader holds, and a reconciliation is scheduled for the next loop."""
        if sig.is_long == share.is_long:
            return False
        self._skip(sig, "invalid_signal", share)
        try:
            held = next(
                (p.szi for p in self._leader_state.clearinghouse_state(share.leader).positions if p.coin == share.coin),
                "none",
            )
        except Exception:
            _log.warning("the leader's state is unavailable", extra={"event": "positions_leader_state"}, exc_info=True)
            held = "unknown"
        self._alert(
            "bad_signal",
            f"{sig.coin}: the leader's {sig.action} is on the other side than our share {share.share_id} "
            f"({sig.signal_id}; it holds {held}); reconciling",
        )
        self._next_reconcile_ms = self._now_or_last()
        return True

    def _handle_reduce(self, share: ShareState, sig: Signal) -> None:
        if self._wrong_direction(share, sig):
            return
        fraction = sig.reduce_fraction
        if fraction is None or not fraction.is_finite() or fraction <= 0 or fraction > 1:
            self._skip(sig, "invalid_signal", share)
            self._alert("bad_signal", f"{sig.coin}: a reduce with fraction {fraction} was not traded ({sig.signal_id})")
            return
        self._mirror_exit(share.share_id, self._exit_of_signal(sig, "close" if fraction == 1 else "reduce", fraction))

    def _exit_of_signal(self, sig: Signal, kind: str, fraction: Decimal | None) -> _LeaderExit:
        reason = REASON_DROPPED_LEADER if sig.wallet in self._dropped else REASON_LEADER_CLOSE
        return _LeaderExit(
            leader=sig.wallet,
            coin=sig.coin,
            kind=kind,
            fraction=fraction,
            event_ms=sig.exchange_ts.ms,
            event_key=sig.tid,
            signal_id=sig.signal_id,
            px=sig.px,
            found_by=FOUND_LIVE,
            case=CASE_LATE,
            tids=(sig.tid,),
            close_reason=reason,
        )

    def _mirror_exit(self, share_id: str, leader_exit: _LeaderExit) -> None:
        """Bring the share in line with a leader exit at once, through the gate, then run the missed-exit detector.

        A share that is already closing or closed is not touched: the exit counts as handled when that close
        happened. The order goes out BEFORE anything is recorded, so a recording failure never delays an exit."""
        share, track = self._share(share_id), self._tracks[share_id]
        if share.status != OPEN or track.closing:
            handled = track.closing_ms if track.closing else track.close_ms
            self._check_missed(share, leader_exit, self._now_or_last() if handled is None else handled)
            return
        close, qty, reason = True, share.qty, leader_exit.close_reason
        if leader_exit.kind == "reduce":
            assert leader_exit.fraction is not None  # noqa: S101 - a reduce always carries its fraction
            plan = rules.reduce_plan(
                share_qty=share.qty,
                fraction=leader_exit.fraction,
                px=leader_exit.px,
                sz_decimals=rules.lot_decimals(share.qty),
                min_order_usd=self._settings.min_order_usd,
            )
            if plan.kind == rules.PARTIAL_BELOW_MIN:
                now = self._now_or_last()
                self._handled[(share.leader, leader_exit.event_key)] = now
                self._append_skip(leader_exit.signal_id, share.leader, share.coin, "partial_below_min", share_id)
                self._check_missed(share, leader_exit, now)
                return
            if plan.kind == rules.REDUCE:
                close, qty, reason = False, Qty(plan.qty), REASON_LEADER_REDUCE
            else:
                reason = rules.CLOSE_ALL_REMAINDER_BELOW_MIN
        now = self._now_or_last()
        accepted = self._send_exit(
            share_id, qty=qty, close=close, reason=reason, tids=leader_exit.tids, signal_id=leader_exit.signal_id,
            px=leader_exit.px,
        )  # fmt: skip
        if accepted:
            self._handled[(share.leader, leader_exit.event_key)] = now
            if close:
                track.closing, track.closing_ms = True, now
        if leader_exit.kind == "close" and leader_exit.close_reason == REASON_RECONCILE_CLOSE:
            self._alert("reconcile_close", f"{share.coin}: the leader is flat or reversed; closing {share_id}")
        self._check_missed(share, leader_exit, now)

    def _send_exit(  # noqa: PLR0913 - one exit request
        self,
        share_id: str,
        *,
        qty: Decimal,
        close: bool,
        reason: str,
        tids: tuple[int, ...],
        signal_id: str,
        px: Price,
    ) -> bool:
        """Send a reduce-only exit through the gate, for no more than the share holds beyond the exits already on
        their way (a triggered stop, an earlier reduce): the broker refuses an exit larger than that. A close covers
        exactly that rest. ``True`` when the exit is on its way (accepted, or nothing is left to send).

        A close refused because a fill got in first (``share_closed``: the gate netted the fills of its own advance;
        ``exceeds_position``: the book was behind a fill, so the share is resynced from the broker first) is retried
        once, on the quantity the share holds by then, under a new deterministic id. A refused close is never left
        forgotten."""
        outcome = self._submit_exit(
            share_id, qty=qty, close=close, reason=reason, tids=tids, signal_id=signal_id, px=px
        )
        if outcome is None:
            return True
        result = outcome.result
        if result is not None and result.accepted:
            return True
        refused = outcome.decision.reason if result is None else result.reason
        resync_ok = True
        if result is not None and refused == "exceeds_position":
            resync_ok = self._resync_from_broker(share_id) is not None
        if close and resync_ok and refused in _RETRIED_REFUSALS and _RETRY_TID not in tids:
            retry = self._submit_exit(
                share_id, qty=qty, close=True, reason=reason, tids=(*tids, _RETRY_TID), signal_id=signal_id, px=px
            )
            if retry is None or (retry.result is not None and retry.result.accepted):
                return True
            refused = retry.decision.reason if retry.result is None else retry.result.reason
        if refused != "duplicate_order":
            self._alert("exit_refused", f"{self._share(share_id).coin}: an exit of {share_id} was refused ({refused})")
        return False

    def _submit_exit(  # noqa: PLR0913 - one exit request
        self,
        share_id: str,
        *,
        qty: Decimal,
        close: bool,
        reason: str,
        tids: tuple[int, ...],
        signal_id: str,
        px: Price,
    ) -> Outcome | None:
        """One gate submit; ``None`` when no exit needs sending because the exits on their way cover the share."""
        self._sync()  # the broker's own fills (a take-profit, a stop) are booked before the free quantity is computed
        share = self._share(share_id)
        free = MONEY_CONTEXT.subtract(share.qty, self._pending_exit_qty(share))
        send = free if close else min(qty, free)
        if send <= 0:
            return None
        outcome = self._submit_through_gate(
            ExitRequest(
                run_id=self._run_id,
                signal_id=signal_id,
                leader=share.leader,
                coin=share.coin,
                is_long=share.is_long,
                tids=tids,
                trade_id=share.trade_id,
                share_id=share_id,
                qty=Qty(send),
                close=close,
                decision_px=px,
                reason=reason,
            )
        )
        self._book_events(outcome.broker_events)
        return outcome

    def _pending_exit_qty(self, share: ShareState) -> Decimal:
        """What the exits already on their way (ours, and stops that have triggered) will take from the share."""
        return sum(
            (
                Decimal(p.qty)
                for p in self._broker.pending_exits()
                if p.share_id == share.share_id and p.coin == share.coin
            ),
            Decimal(0),
        )

    def _close_for_cause(self, share_id: str, reason: str) -> None:
        """Close a share the manager cannot protect (no stop could be placed) or that a close left open."""
        share, track = self._share(share_id), self._tracks[share_id]
        if share.status != OPEN:
            return
        now = self._now_or_last()
        if self._send_exit(
            share_id,
            qty=share.qty,
            close=True,
            reason=reason,
            tids=(self._next_synthetic_tid(),),
            signal_id=f"{reason}:{share_id}",
            px=self._book.mark_px(share.coin) or share.entry_px,
        ):
            track.closing, track.closing_ms = True, now

    # ================================================================================ broker events (booking)

    def on_broker_events(self, events: Iterable[BrokerEvent]) -> None:
        """Book events the caller obtained from the broker itself. Idempotent: an event already booked is ignored."""
        self._book_events(events)

    def _book_events(self, events: Iterable[BrokerEvent]) -> None:
        """Queue unseen events and, unless a drain is already running, apply them all, then run follow-up actions one
        at a time, re-applying any events a follow-up produced before the next one."""
        for event in events:
            key = _event_key(event)
            if key not in self._seen_events:
                _remember(self._seen_events, key)
                self._events.append(event)
        if self._draining:
            return
        self._draining = True
        try:
            while self._events or self._actions:
                while self._events:
                    self._apply_event(self._events.popleft())
                if self._actions:
                    self._actions.popleft()()
        finally:
            self._draining = False

    def _apply_event(self, event: BrokerEvent) -> None:
        if event.kind == "reject":
            self._on_reject(event)
            return
        fill = event.fill
        if fill is None:
            return  # an exit-unfilled alert: the broker has already alerted
        share = self._book.state(fill.share_id)
        if share is None or share.status == CLOSED:
            _log.warning("a fill for a share the book does not hold", extra={"event": "positions_unknown_fill"})
            return
        if fill.exit_reason is None:
            self._entry_filled(share, fill)
        else:
            self._exit_filled(share, fill, event)

    def _on_reject(self, event: BrokerEvent) -> None:
        share_id = self._entry_orders.pop(event.client_order_id or "", None)
        if share_id is None:
            return
        share, track = self._share(share_id), self._tracks[share_id]
        if share.status == PENDING_ENTRY:
            self._book.update(share_id, status=CLOSED)
            track.close_ms = event.time_ms
            track.deferred.clear()
            self._clear_flip_leg(share)
        self._append_share("entry_rejected", self._share(share_id), reason=event.reason)

    def _entry_filled(self, share: ShareState, fill: FillRecord) -> None:
        self._entry_orders.pop(fill.client_order_id, None)
        if share.status == PENDING_ENTRY:
            self._opened(share, fill.qty, Price(fill.price))
            return
        total = MONEY_CONTEXT.add(share.qty, fill.qty)
        entry = MONEY_CONTEXT.divide(
            MONEY_CONTEXT.add(
                MONEY_CONTEXT.multiply(share.qty, share.entry_px), MONEY_CONTEXT.multiply(fill.qty, fill.price)
            ),
            total,
        )
        updated = self._book.update(share.share_id, qty=Qty(total), entry_px=Price(entry))
        self._append_share("added", updated)
        self._actions.append(partial(self._replace_stop, share.share_id))

    def _opened(self, share: ShareState, qty: Decimal, entry: Price, mark: Decimal | None = None) -> None:
        stop = rules.initial_stop(
            is_long=share.is_long, entry_px=entry, atr=share.atr, stop_atr_mult=self._settings.stop_atr_mult
        )
        usable = stop > 0 and (mark is None or (stop < mark if share.is_long else stop > mark))
        stop_px = Price(stop if usable else 0)
        risk = rules.open_risk_usd(is_long=share.is_long, qty=qty, entry_px=entry, stop_px=stop_px)
        updated = self._book.update(
            share.share_id,
            status=OPEN,
            qty=Qty(qty),
            entry_px=entry,
            initial_stop_px=stop_px,
            current_stop_px=stop_px,
            initial_risk_usd=risk,
            best_px=entry,
        )
        self._append_share("opened", updated)
        track = self._tracks[share.share_id]
        if usable:
            self._actions.append(partial(self._place_protection, share.share_id))
        else:
            self._actions.append(partial(self._close_for_cause, share.share_id, "invalid_stop"))
        for signal in track.deferred:
            self._actions.append(partial(self._handle, signal))
        track.deferred = []

    def _exit_filled(self, share: ShareState, fill: FillRecord, event: BrokerEvent) -> None:
        track = self._tracks[share.share_id]
        remaining = MONEY_CONTEXT.subtract(share.qty, fill.qty)
        reason = fill.exit_reason
        if event.trade is not None or remaining <= 0:
            self._book.update(share.share_id, status=CLOSED, qty=Qty(0))
            track.close_ms = fill.time.ms
            track.deferred.clear()
            name = {"liquidated": "liquidated", "delisted_force_settle": "delisted"}.get(event.kind, "closed")
            self._append_share(name, self._share(share.share_id), reason=reason)
            key = (share.leader, share.coin)
            if reason in _OUR_EXITS:
                self._ours_won.add(key)
            waiting = self._flip_wait.get(key)
            if waiting is not None and waiting[1] == share.share_id:
                del self._flip_wait[key]
                self._ours_won.discard(key)  # the flip leg is a new signal
                self._actions.append(partial(self._open_share, waiting[0]))
            return
        take_profit = reason == "take_profit"
        updated = self._book.update(share.share_id, qty=Qty(remaining), tp_done=share.tp_done or take_profit)
        self._append_share("tp_filled" if take_profit else "reduced", updated, reason=reason)
        self._actions.append(partial(self._replace_stop, share.share_id))
        if track.closing and self._pending_exit_qty(updated) <= 0:
            # a close of ours left the share open and nothing is on its way out: close the rest
            track.closing = False
            self._actions.append(partial(self._close_for_cause, share.share_id, REASON_CLOSE_REMAINDER))

    # ================================================================================================= stops

    def _place_protection(self, share_id: str) -> None:
        """The initial stop (and the take-profit) of a share whose entry just filled. A share whose stop cannot be
        placed is closed at once: a position with no stop is never left open."""
        share = self._share(share_id)
        if share.status != OPEN:
            return
        track = self._tracks[share_id]
        held = [s for s in self._broker.stops() if s.share_id == share_id]
        standing = [s for s in held if s.kind == "sl" and s.qty == share.qty]
        cid: str | None
        if standing:  # a healed entry whose stop the broker already has (the kill came after it was recorded)
            cid = standing[0].client_order_id
            share = self._take_broker_stop(share, Decimal(standing[0].trigger_px))
        else:
            cid = self._place_stop(share, "sl", share.qty, share.current_stop_px)
        if cid is None:
            self._alert("stop_failed", f"{share.coin}: no stop could be placed for {share_id}; closing it")
            self._close_for_cause(share_id, REASON_STOP_FAILED)
            return
        track.sl_cid, track.sl_qty = cid, Decimal(share.qty)
        if self._settings.tp_enabled and not any(s.kind == "tp" for s in held):
            self._place_take_profit(share)

    def _place_take_profit(self, share: ShareState) -> None:
        settings = self._settings
        r_distance = abs(MONEY_CONTEXT.subtract(share.entry_px, share.initial_stop_px))
        reach = MONEY_CONTEXT.multiply(settings.tp1_r, r_distance)
        trigger = (
            MONEY_CONTEXT.add(share.entry_px, reach) if share.is_long else MONEY_CONTEXT.subtract(share.entry_px, reach)
        )
        qty: Decimal | None
        if settings.tp1_fraction >= 1:
            qty = Decimal(share.qty)
        else:
            plan = rules.reduce_plan(
                share_qty=share.qty,
                fraction=settings.tp1_fraction,
                px=share.entry_px,
                sz_decimals=rules.lot_decimals(share.qty),
                min_order_usd=settings.min_order_usd,
            )
            qty = plan.qty if plan.kind == rules.REDUCE else None
        if qty is None or trigger <= 0:
            self._append_share("tp_skipped", share, reason="below_min_order" if qty is None else "invalid_trigger")
            return
        if self._place_stop(share, "tp", qty, Price(trigger)) is None:
            self._alert("stop_failed", f"{share.coin}: no take-profit could be placed for {share.share_id}")

    def _place_stop(self, share: ShareState, kind: str, qty: Decimal, trigger_px: Decimal) -> str | None:
        """Register a stop through the gate under a fresh signal id; its client order id, or ``None`` if refused."""
        track = self._tracks[share.share_id]
        track.stop_seq += 1
        outcome = self._place_stop_through_gate(
            StopRequest(
                run_id=self._run_id,
                signal_id=f"{share.share_id}:{kind}:{track.stop_seq}",
                leader=share.leader,
                coin=share.coin,
                kind=kind,
                is_long=share.is_long,
                qty=Qty(qty),
                trigger_px=Price(trigger_px),
                trade_id=share.trade_id,
                share_id=share.share_id,
            )
        )
        cid = outcome.decision.client_order_id
        if outcome.result is None or not outcome.result.accepted or cid is None:
            _log.warning(
                "a stop was refused",
                extra={"event": "positions_stop_refused", "kind": kind, "share_id": share.share_id},
            )
            return None
        return cid

    def _replace_stop(self, share_id: str) -> None:
        """Re-place the share's stop-loss for its current quantity and stop (after a fill changed the quantity). The
        new stop is registered BEFORE the old one is cancelled, so the share is never unprotected."""
        share, track = self._share(share_id), self._tracks[share_id]
        if share.status != OPEN:
            return
        if track.sl_cid is not None and track.sl_qty == share.qty:
            return
        cid = self._place_stop(share, "sl", share.qty, share.current_stop_px)
        if cid is None:
            self._alert("stop_failed", f"{share.coin}: the stop of {share_id} could not be re-placed")
            return
        self._cancel_old_stop(track)
        track.sl_cid, track.sl_qty = cid, Decimal(share.qty)

    def _cancel_old_stop(self, track: _Track) -> None:
        """Cancel the stop-loss a new one has just replaced (a stop already triggered is an order in flight: the
        broker keeps it)."""
        if track.sl_cid is not None:
            self._broker.cancel_stop(track.sl_cid)

    def _trail(self, share_id: str) -> None:
        share, track = self._share(share_id), self._tracks[share_id]
        if share.status != OPEN or track.closing:
            return
        new_stop = rules.trailed_stop(
            is_long=share.is_long,
            current_stop_px=share.current_stop_px,
            entry_px=share.entry_px,
            initial_stop_px=share.initial_stop_px,
            best_px=share.best_px,
            atr=share.atr,
            trail_start_r=self._settings.trail_start_r,
            trail_atr_mult=self._settings.trail_atr_mult,
        )
        tighter = new_stop > share.current_stop_px if share.is_long else new_stop < share.current_stop_px
        if not tighter or new_stop <= 0:
            return
        cid = self._place_stop(share, "sl", share.qty, new_stop)
        if cid is None:
            self._alert("stop_failed", f"{share.coin}: the trailed stop of {share_id} could not be placed")
            return
        self._cancel_old_stop(track)
        track.sl_cid, track.sl_qty = cid, Decimal(share.qty)
        self._append_share("stop_moved", self._book.update(share_id, current_stop_px=Price(new_stop)))

    # ============================================================================= marks, time, delistings

    def advance_to(self, now_ms: int) -> tuple[BrokerEvent, ...]:
        """Move broker time (the supervisor's call, every loop, before marks), book what that produced, and run the
        leader reconciliation and the fill audit when they are due. Returns the broker's events."""
        events = tuple(self._broker.advance_to(now_ms))
        self._last_ms = max(self._last_ms, now_ms)
        self._book_events(events)
        if self._next_reconcile_ms is None:
            self._next_reconcile_ms = now_ms + self._settings.reconcile_interval_ms
        if self._audit_anchor_ms is None or self._next_audit_ms is None:
            self._audit_anchor_ms = now_ms
            self._next_audit_ms = now_ms + self._settings.fill_audit_interval_ms
        if now_ms >= self._next_reconcile_ms:
            self._run_guarded(self.reconcile, "reconcile_failed")
        elif self._leader_retry_ms and now_ms >= min(self._leader_retry_ms.values()):
            self._run_guarded(self._retry_failed_leaders, "reconcile_failed")
        if now_ms >= self._next_audit_ms:
            self._run_guarded(self.run_fill_audit, "audit_failed")
        return events

    def _run_guarded(self, job: Callable[[], None], alert_kind: str) -> None:
        """Run a background check; its failure is logged and alerted and never stops the loop or an exit."""
        try:
            job()
        except Exception as exc:
            _log.exception("a background check failed", extra={"event": "positions_check_failed", "job": alert_kind})
            self._alert(alert_kind, f"{alert_kind}: {type(exc).__name__}")

    def on_mark(self, update: MarkUpdate) -> tuple[BrokerEvent, ...]:
        """Give the mark to the broker (stops and liquidations), book the result, then move the trailing stops."""
        events = tuple(self._broker.on_mark(update))
        self._book_events(events)
        self._book.set_mark(update.coin, update.mark)
        for share in self._book.states():
            if share.coin != update.coin or share.status != OPEN:
                continue
            best = max(share.best_px, update.mark) if share.is_long else min(share.best_px, update.mark)
            if best != share.best_px:
                self._book.update(share.share_id, best_px=Price(best))
            self._trail(share.share_id)
        return events

    def on_delist(self, coin: str, settlement_px: Price, time_ms: int) -> tuple[BrokerEvent, ...]:
        """Settle every share on a delisted coin at ``settlement_px`` and book the result."""
        events = tuple(self._broker.on_delist(coin, settlement_px, time_ms))
        self._book_events(events)
        return events

    def leader_dropped(self, wallet: str) -> None:
        """The leader is no longer followed. Its open shares stay managed (our stops, its exits, reconciliation and the
        audit) until they close; its exits are mirrored under the exit reason ``dropped_leader``."""
        self._dropped.add(wallet)
        _log.info("leader dropped; its shares stay managed", extra={"event": "positions_leader_dropped"})

    def flatten(self, *, run_id: str) -> FlattenReport:
        """The kill switch's flatten through the gate; every pass's fills are booked. Re-run it with a new run id while
        the report's ``in_flight`` or ``still_open`` is not empty."""
        self._sync()
        report = self._gate.flatten(run_id=run_id)
        for outcome in report:
            self._book_events(outcome.broker_events)
        now = self._now_or_last()
        refused = {share_id for _coin, share_id, _qty in report.still_open}
        for share in self._book.states():
            track = self._tracks.get(share.share_id)
            if share.status == OPEN and track is not None and share.share_id not in refused and not track.closing:
                track.closing, track.closing_ms = True, now
        return report

    # ============================================================================== restart (R0 checkpoint)

    def export_state(self) -> dict[str, Any]:
        """What a restart needs, as a ledger-encodable tree: ``{"state": ..., "volatile": ...}``. ``state`` changes
        only when something structural does (a share, a stop, a pending close); ``volatile`` holds the cursors and the
        per-share best price that move all the time, so a caller that writes a checkpoint when ``state`` changed does
        not write one per mark. Only shares that are not closed are carried: closed ones live in the ledger.
        Not carried, by design: pending entries whose fill the broker does not hold (dropped at a restart), deferred
        leader signals of a pending entry, a flip's waiting open leg (the position is flat then; a missed re-entry is
        safe) and the entry-order map."""
        live = [state for state in self._book.states() if state.status != CLOSED]
        live_ids = {state.share_id for state in live}
        return {
            "state": {
                "shares": [_share_payload(state) for state in live],
                "tracks": {
                    sid: _track_payload(track) for sid, track in sorted(self._tracks.items()) if sid in live_ids
                },
                "leader_pos": [[leader, coin, size] for (leader, coin), size in sorted(self._leader_pos.items())],
                "ours_won": sorted([leader, coin] for leader, coin in self._ours_won),
                "dropped": sorted(self._dropped),
                "orphans_closing": sorted(self._orphans_closing & live_ids),
                "missed_count": self._missed_count,
                "synthetic_tid": self._synthetic_tid,
                "seen_signals": list(self._seen_signals)[-CHECKPOINT_SEEN_SIGNALS:],
            },
            "volatile": {
                "best_px": {state.share_id: state.best_px for state in live},
                "audit_end": dict(sorted(self._audit_end.items())),
                "reconcile_since": dict(sorted(self._reconcile_since.items())),
                "stretches": {
                    leader: [stretch.first_attempt_ms, stretch.start_ms, stretch.breached]
                    for leader, stretch in sorted(self._stretches.items())
                },
            },
        }

    def restore_state(
        self, exported: dict[str, Any], *, cid_map: Mapping[str, str], tids_done: Mapping[str, Iterable[int]]
    ) -> None:
        """Load what ``export_state`` wrote into a FRESH manager (call after the broker was restored).

        ``cid_map`` maps the client order ids of stops the broker registered again to their new ids (a share's stop
        bookkeeping follows them); ``tids_done`` is every leader fill tid already ledgered as a signal. A share that
        was a pending entry is booked as closed with nothing held (the broker dropped the order) and ledgered so,
        unless the broker holds its fill (the kill came before the checkpoint): it stays pending and
        ``heal_pending_entries`` books it open.
        A share is ``closing`` only while the broker really holds an exit for it. Time cursors are loaded last.

        Raises:
            ValueError: the manager is not fresh.
        """
        if self._book.states() or self._tracks:
            raise ValueError("restore_state needs a fresh manager")
        state, volatile = exported["state"], exported["volatile"]
        exiting = {order.share_id for order in self._broker.pending_exits()}
        held = {share_id for view in self._broker.positions() for share_id in view.share_ids}
        for payload in state["shares"]:
            share = _share_from_payload(
                payload, Price(volatile["best_px"].get(payload["share_id"], payload["entry_px"]))
            )
            if share.status == PENDING_ENTRY and share.share_id not in held:
                self._book.add(replace(share, status=CLOSED, qty=Qty(0), open_risk_usd=Decimal(0)))
                self._append_share("restart_dropped", self._share(share.share_id), reason="entry_pending_at_restart")
                continue
            self._book.add(share)
            self._tracks[share.share_id] = _track_from_payload(state["tracks"][share.share_id], cid_map)
            self._tracks[share.share_id].closing = share.share_id in exiting
        self._leader_pos = {(leader, coin): Decimal(size) for leader, coin, size in state["leader_pos"]}
        self._ours_won = {(leader, coin) for leader, coin in state["ours_won"]}
        self._dropped = set(state["dropped"])
        self._orphans_closing = set(state["orphans_closing"])
        self._missed_count = state["missed_count"]
        self._synthetic_tid = state["synthetic_tid"]
        self._seen_signals = dict.fromkeys(state["seen_signals"])
        self._tids_done = {leader: set(tids) for leader, tids in tids_done.items()}
        self._audit_end = dict(volatile["audit_end"])
        self._reconcile_since = dict(volatile["reconcile_since"])
        self._stretches = {leader: _Stretch(*values) for leader, values in volatile["stretches"].items()}
        self._audit_leaders = {s.leader for s in self._book.states() if s.status != CLOSED}

    def verify_protection(self) -> tuple[str, ...]:
        """After ``restore_state``: every open share held by the broker must have ONE live stop-loss on the opposite
        side for EXACTLY its quantity. The checkpoint can be older than the broker's ledger records (kill -9 between
        a fill and the next checkpoint), so the BROKER is the truth: the share's quantity is taken from the broker's
        share quantity and its current stop from the broker's tightest stop-loss. A stop-loss whose quantity equals
        the broker's is never cancelled; the others (stale sizes) are cancelled once a correct one stands. A missing
        or wrong stop is re-placed through the gate before anything is cancelled; when none can be placed the share
        is closed. Returns the share ids that needed repair."""
        return tuple(
            share_id
            for share_id in [s.share_id for s in self._book.states() if s.status == OPEN]
            if self._verify_share(share_id)
        )

    def _verify_share(self, share_id: str) -> bool:
        """``verify_protection`` for one share; ``True`` when its stop had to be re-placed."""
        share = self._share(share_id)
        view = self._broker.position(share.coin)
        if view is None or share_id not in view.share_ids:
            return False
        share = self._take_broker_quantity(share, Decimal(view.share_qtys[view.share_ids.index(share_id)]))
        track = self._tracks[share_id]
        side = "sell" if share.is_long else "buy"
        mine = [s for s in self._broker.stops() if s.share_id == share_id and s.kind == "sl" and s.side == side]
        tightest = max if share.is_long else min
        exact = [s for s in mine if s.qty == share.qty]
        if exact:
            keep = tightest(exact, key=lambda s: s.trigger_px)
            self._take_broker_stop(share, Decimal(keep.trigger_px))
            track.sl_cid, track.sl_qty = keep.client_order_id, Decimal(share.qty)
            for stale in mine:
                if stale.client_order_id != keep.client_order_id:
                    self._broker.cancel_stop(stale.client_order_id)
            return False
        if mine:
            share = self._take_broker_stop(share, Decimal(tightest(s.trigger_px for s in mine)))
        cid = self._place_stop(share, "sl", share.qty, share.current_stop_px)
        if cid is None:
            track.sl_cid = None
            self._alert("stop_failed", f"{share.coin}: no stop for {share_id} after the restart; closing it")
            self._close_for_cause(share_id, REASON_STOP_FAILED)
            return True
        for stale in mine:
            self._broker.cancel_stop(stale.client_order_id)
        track.sl_cid, track.sl_qty = cid, Decimal(share.qty)
        self._alert("stop_replaced", f"{share.coin}: the stop of {share_id} was missing or wrong after the restart")
        return True

    def _take_broker_quantity(self, share: ShareState, broker_qty: Decimal) -> ShareState:
        """The restored share's quantity is the broker's (the checkpoint may predate an add or a take-profit)."""
        if share.qty == broker_qty:
            return share
        updated = self._book.update(share.share_id, qty=Qty(broker_qty))
        self._append_share("reduced" if broker_qty < share.qty else "added", updated, reason="restart_broker_qty")
        return updated

    def _take_broker_stop(self, share: ShareState, trigger_px: Decimal) -> ShareState:
        """The restored share's current stop is the broker's stop-loss trigger (the checkpoint may predate a trail)."""
        if share.current_stop_px == trigger_px:
            return share
        return self._book.update(share.share_id, current_stop_px=Price(trigger_px))

    def heal_pending_entries(self) -> None:
        """The reload ends with it: a share the checkpoint has as pending whose fill the broker holds (the kill came
        before the next checkpoint) is booked open from the broker's quantity and price and protected at once, instead
        of up to ``reconcile_interval`` later. Nothing else is reconciled here (ghosts and orphans stay flagged by the
        reload and are handled by the periodic reconciliation)."""
        held = {
            (view.coin, share_id): (view, qty)
            for view in self._broker.positions()
            for share_id, qty in zip(view.share_ids, view.share_qtys, strict=True)
        }
        for share in [s for s in self._book.states() if s.status == PENDING_ENTRY]:
            found = held.get((share.coin, share.share_id))
            if found is not None:
                view, qty = found
                self._heal_entry(share, Decimal(qty), share.entry_px if len(view.share_ids) > 1 else view.avg_entry_px)

    # ======================================================================================== reconciliation

    def on_resync(self) -> None:
        """After a data gap and its resync (F3): reconcile now."""
        self.reconcile()

    def reconcile(self) -> None:
        """Compare the book with the broker (A7) and every leader we hold a share of with the exchange: a share the
        leader no longer holds closes with ``reconcile_close``, leader fills nobody processed are mirrored and run
        through the missed-exit detector, a size we cannot explain is alerted and never guessed at."""
        now = self._sync()
        self._next_reconcile_ms = now + self._settings.reconcile_interval_ms
        self._reconcile_broker()
        for leader in self._leaders_with_shares():
            self._reconcile_leader(leader, now)

    def _leaders_with_shares(self) -> list[str]:
        held = {s.leader for s in self._book.states() if s.status in (OPEN, PENDING_ENTRY)}
        self._leader_retry_ms = {leader: due for leader, due in self._leader_retry_ms.items() if leader in held}
        return sorted(held)

    def _retry_failed_leaders(self) -> None:
        """The leaders whose read failed and whose retry time has come, the longest-waiting first (the broker side is
        not compared again: the full reconciliation does that on its own schedule)."""
        now = self._sync()
        due = [(at, leader) for leader, at in self._leader_retry_ms.items() if at <= now]
        held = set(self._leaders_with_shares())
        for _at, leader in sorted(due):
            if leader in held:
                self._reconcile_leader(leader, now)

    def _reconcile_broker(self) -> None:
        held = {
            (view.coin, share_id): (view, qty)
            for view in self._broker.positions()
            for share_id, qty in zip(view.share_ids, view.share_qtys, strict=True)
        }
        pending_ids = {p.share_id for p in self._broker.pending_entries()}
        for (coin, share_id), (view, qty) in held.items():
            booked = self._book.state(share_id)
            if booked is None or booked.status == CLOSED:
                self._close_orphan(coin, share_id, view.qty > 0, qty, view.avg_entry_px)
        self._orphans_closing &= {share_id for _coin, share_id in held}
        for share in self._book.states():
            if share.status == PENDING_ENTRY and share.share_id not in pending_ids:
                if (share.coin, share.share_id) in held:
                    view, qty = held[(share.coin, share.share_id)]
                    entry_px = share.entry_px if len(view.share_ids) > 1 else view.avg_entry_px
                    self._heal_entry(share, Decimal(qty), entry_px)
                else:
                    self._drop_ghost(share, "the entry is neither pending nor held at the broker")
            elif share.status == OPEN:
                broker = held.get((share.coin, share.share_id))
                if broker is None:
                    self._drop_ghost(share, "the broker holds no such share")
                elif Decimal(broker[1]) != share.qty:
                    self._correct_quantity(share, Decimal(broker[1]))

    def _heal_entry(self, share: ShareState, qty: Decimal, entry_px: Price) -> None:
        """The broker holds a share the book still has as pending (the entry's fill event never reached us): book it as
        open from the broker's quantity and entry price, protect it, replay what arrived meanwhile (A7)."""
        self._alert(
            "position_mismatch", f"{share.coin}: {share.share_id} is held at the broker ({qty}) but pending in the book"
        )
        self._entry_orders = {cid: sid for cid, sid in self._entry_orders.items() if sid != share.share_id}
        self._opened(share, qty, entry_px, self._book.mark_px(share.coin))
        self._book_events(())

    def _close_orphan(self, coin: str, share_id: str, is_long: bool, qty: Decimal, avg_px: Price) -> None:
        """The broker holds a share the book does not know: alert and close it, never leave an orphaned copy."""
        if share_id in self._orphans_closing:
            return
        self._alert("position_mismatch", f"{coin}: the broker holds {share_id} ({qty}) that the book does not know")
        outcome = self._submit_through_gate(
            ExitRequest(
                run_id=self._run_id,
                signal_id=f"orphan:{share_id}",
                leader=_ORPHAN_LEADER,
                coin=coin,
                is_long=is_long,
                tids=(self._next_synthetic_tid(),),
                trade_id=share_id,
                share_id=share_id,
                qty=Qty(qty),
                close=True,
                decision_px=avg_px,
                reason=REASON_ORPHAN_CLOSE,
            )
        )
        self._book_events(outcome.broker_events)
        if outcome.result is not None and outcome.result.accepted:
            self._orphans_closing.add(share_id)
        else:
            self._alert("exit_refused", f"{coin}: the close of the orphaned {share_id} was refused")

    def _drop_ghost(self, share: ShareState, why: str) -> None:
        self._alert("position_mismatch", f"{share.coin}: {share.share_id} dropped from the book: {why}")
        self._book.update(share.share_id, status=CLOSED, qty=Qty(0))
        track = self._tracks[share.share_id]
        track.close_ms = self._now_or_last()
        track.deferred.clear()
        self._clear_flip_leg(share)
        self._append_share("ghost_share_dropped", self._share(share.share_id), reason=why)

    def _correct_quantity(self, share: ShareState, broker_qty: Decimal) -> None:
        """The broker's quantity is the truth (A7): correct the book, alert, and re-protect the new quantity."""
        self._alert(
            "position_mismatch",
            f"{share.coin}: {share.share_id} is {share.qty} in the book and {broker_qty} at the broker; corrected",
        )
        updated = self._book.update(share.share_id, qty=Qty(broker_qty))
        self._append_share("reduced" if broker_qty < share.qty else "added", updated, reason="broker_resync")
        self._actions.append(partial(self._replace_stop, share.share_id))
        self._book_events(())

    def _resync_from_broker(self, share_id: str) -> Decimal | None:
        """After an oversized exit: take the share's quantity from the broker (or drop the share if it holds none).
        Returns the broker's quantity, or ``None`` when there is none."""
        share = self._share(share_id)
        view = self._broker.position(share.coin)
        if view is not None and share_id in view.share_ids:
            qty = Decimal(view.share_qtys[view.share_ids.index(share_id)])
            if qty != share.qty:
                self._correct_quantity(share, qty)
            return qty
        self._drop_ghost(share, "an exit found no such share at the broker")
        return None

    def _reconcile_leader(self, leader: str, now: int) -> None:
        since = self._reconcile_since.get(leader, self._audit_anchor_ms if self._audit_anchor_ms is not None else now)
        try:
            state = self._leader_state.clearinghouse_state(leader)
            fills = tuple(self._leader_fills.user_fills_by_time(leader, since, now))
        except Exception as exc:
            _log.warning("leader reconciliation failed", extra={"event": "positions_reconcile_failed"}, exc_info=True)
            if leader not in self._leader_retry_ms:  # one alert per stretch of failures, not one per retry
                self._alert("reconcile_failed", f"could not read leader {leader}: no share was changed")
            wait_s = getattr(exc, "wait_s", None)  # a rate-budget refusal says how long until it fits
            wait_ms = math.ceil(wait_s * 1000) if isinstance(wait_s, int | float) else 0
            self._leader_retry_ms[leader] = now + max(wait_ms, RECONCILE_RETRY_MS)
            return
        self._leader_retry_ms.pop(leader, None)
        sizes = {p.coin: Decimal(p.szi) for p in state.positions}
        for share in [s for s in self._book.states() if s.leader == leader and s.status == OPEN]:
            self._reconcile_share(share.share_id, sizes.get(share.coin, Decimal(0)), fills, now)
        self._reconcile_since[leader] = max(since, now - self._settings.missed_exit_max_lag_ms)

    def _reconcile_share(self, share_id: str, size: Decimal, fills: Sequence[Fill], now: int) -> None:
        share, track = self._share(share_id), self._tracks[share_id]
        done = self._tids_done.setdefault(share.leader, set())
        unseen = sorted(
            (f for f in fills if f.coin == share.coin and f.tid not in done and f.time_ms > track.open_ms),
            key=lambda f: (f.time_ms, f.tid),
        )
        for fill in unseen:
            self._replay_fill(share_id, fill, found_by=FOUND_RECONCILIATION, close_reason=REASON_RECONCILE_CLOSE)
        share = self._share(share_id)
        if share.status != OPEN or track.closing:
            return
        direction = 1 if share.is_long else -1
        if size * direction <= 0:
            tid = self._next_synthetic_tid()
            self._mirror_exit(
                share_id,
                _LeaderExit(
                    leader=share.leader,
                    coin=share.coin,
                    kind="close",
                    fraction=None,
                    event_ms=track.evidence_ms,  # only the last time the leader was proven to hold the position
                    event_key=tid,
                    signal_id=f"reconcile:{share_id}",
                    px=self._book.mark_px(share.coin) or share.entry_px,
                    found_by=FOUND_RECONCILIATION,
                    case=CASE_ORPHAN,
                    tids=(tid,),
                    close_reason=REASON_RECONCILE_CLOSE,
                    dated=False,  # no fill explains it: the daily audit dates it later, from the leader's own fill
                ),
            )
            return
        expected = self._leader_pos.get((share.leader, share.coin))
        if expected is not None and expected != size:
            self._alert(
                "leader_mismatch",
                f"{share.coin}: leader {share.leader} holds {size}, the signals say {expected}; nothing was changed",
            )
        else:
            track.evidence_ms = now

    def _replay_fill(self, share_id: str, fill: Fill, *, found_by: str, close_reason: str) -> None:
        """A leader fill nobody told us about: record that it is known, and mirror it when it is an exit."""
        share = self._share(share_id)
        self._tids_done.setdefault(share.leader, set()).add(fill.tid)
        for leg in (0, 1):
            _remember(self._seen_signals, detector_signal_id(share.leader, fill.tid, leg))
        effect = rules.fill_effect(fill, is_long=share.is_long)
        self._leader_pos[(share.leader, share.coin)] = effect.post
        if effect.kind in ("close", "reduce"):
            self._mirror_exit(share_id, self._exit_of_fill(share.leader, fill, effect, found_by, close_reason))

    @staticmethod
    def _exit_of_fill(
        leader: str, fill: Fill, effect: rules.FillEffect, found_by: str, close_reason: str
    ) -> _LeaderExit:
        return _LeaderExit(
            leader=leader,
            coin=fill.coin,
            kind=effect.kind,
            fraction=effect.fraction,
            event_ms=fill.time_ms,
            event_key=fill.tid,
            signal_id=detector_signal_id(leader, fill.tid, 0),
            px=fill.px,
            found_by=found_by,
            case=CASE_ORPHAN,
            tids=(fill.tid,),
            close_reason=close_reason,
        )

    # ================================================================================= the leader-fill audit

    def run_fill_audit(self) -> None:
        """Fetch every leader's fills since the last complete audit (up to one missed-exit lag before now) for each
        leader that had a share since then, and classify each exit. An interval that cannot be retrieved is retried
        every ``storage.retry_interval_min`` for ``eval.missing_data_retry_max_h``; after that it is a breach."""
        now = self._sync()
        settings = self._settings
        anchor = self._audit_anchor_ms if self._audit_anchor_ms is not None else now - settings.fill_audit_interval_ms
        end = now - settings.missed_exit_max_lag_ms
        active = {s.leader for s in self._book.states() if s.status != CLOSED}
        retrying = False
        for leader in sorted(self._audit_leaders | active | set(self._stretches)):
            stretch = self._stretches.get(leader)
            start = stretch.start_ms if stretch is not None else self._audit_end.get(leader, anchor)
            if end < start:
                continue
            try:
                fills = tuple(self._leader_fills.user_fills_by_time(leader, start, end))
            except Exception:
                _log.warning("fill audit fetch failed", extra={"event": "positions_audit_failed"}, exc_info=True)
                retrying = True
                self._audit_unreachable(leader, start, end, now)
                continue
            for fill in sorted(fills, key=lambda f: (f.time_ms, f.tid)):
                self._audit_fill(leader, fill)
            self._append("fill_audit", {"leader": leader, "start_ms": start, "end_ms": end, "complete": True})
            self._audit_end[leader] = end
            self._stretches.pop(leader, None)
        self._audit_leaders = {s.leader for s in self._book.states() if s.status != CLOSED}
        interval = settings.audit_retry_interval_ms if retrying else settings.fill_audit_interval_ms
        self._next_audit_ms = now + interval

    def _audit_unreachable(self, leader: str, start: int, end: int, now: int) -> None:
        stretch = self._stretches.setdefault(leader, _Stretch(first_attempt_ms=now, start_ms=start))
        self._append("fill_audit", {"leader": leader, "start_ms": start, "end_ms": end, "complete": False})
        if stretch.first_attempt_ms == now:
            self._alert("audit_failed", f"the fill audit of leader {leader} could not be retrieved; retrying")
        if not stretch.breached and now - stretch.first_attempt_ms >= self._settings.audit_retry_max_ms:
            stretch.breached = True
            self._append("audit_breach", {"leader": leader, "stretch_start_ms": stretch.start_ms})
            self._alert("audit_breach", f"the fill audit of leader {leader} is still missing: P4 breach")

    def _audit_fill(self, leader: str, fill: Fill) -> None:
        """Classify one leader fill: only an exit on a coin where we held that leader's share at that moment counts."""
        held = [
            s
            for s in self._book.states()
            if s.leader == leader
            and s.coin == fill.coin
            and (track := self._tracks.get(s.share_id)) is not None
            and track.open_ms < fill.time_ms
            and (track.close_ms is None or fill.time_ms <= track.close_ms)
        ]
        if not held:
            return
        share = held[-1]
        effect = rules.fill_effect(fill, is_long=share.is_long)
        if effect.kind not in ("close", "reduce"):
            return
        handled = self._handled.get((leader, fill.tid))
        leader_exit = self._exit_of_fill(leader, fill, effect, FOUND_DAILY_AUDIT, REASON_AUDIT_CLOSE)
        if handled is not None:
            self._check_missed(share, leader_exit, handled)
        else:
            self._replay_fill(share.share_id, fill, found_by=FOUND_DAILY_AUDIT, close_reason=REASON_AUDIT_CLOSE)

    # ============================================================================== the missed-exit detector

    def _check_missed(self, share: ShareState, leader_exit: _LeaderExit, handled_ms: int) -> None:
        """An exit is handled if a mirror action, a skip record or the share's full close came within the lag limit of
        its exchange timestamp; otherwise it is ledgered as a missed exit, a go-live blocker is written and one alert
        goes out. Detection never pauses anything."""
        if not leader_exit.dated:
            return
        lag = handled_ms - leader_exit.event_ms
        key = (share.leader, leader_exit.event_key, share.share_id)
        if lag <= self._settings.missed_exit_max_lag_ms or key in self._missed_logged:
            return
        self._missed_logged.add(key)
        self._missed_count += 1
        missed_id = f"me:{share.share_id}:{leader_exit.event_key}"
        self._append(
            "missed_exit",
            {
                "missed_exit_id": missed_id,
                "leader": share.leader,
                "coin": share.coin,
                "share_id": share.share_id,
                "event_type": leader_exit.kind,
                "event_exchange_ms": leader_exit.event_ms,
                "detected_ms": self._now_or_last(),
                "lag_ms": lag,
                "case": leader_exit.case,
                "found_by": leader_exit.found_by,
            },
        )
        self._append("go_live_blocker", {"type": "ME", "missed_exit_id": missed_id})
        self._alert(
            "missed_exit",
            f"missed exit {self._missed_count}/{self._settings.missed_exit_max_count} since this run started "
            f"(run {self._run_id}): {share.coin} {leader_exit.kind} by {share.leader} mirrored {lag} ms late "
            f"({leader_exit.found_by}). Go-live blocker ME; its cost will follow.",
        )

    # ======================================================================================== small helpers

    def _atr(self, coin: str, before_ms: int) -> Decimal | None:
        """ATR on the candles closed before ``before_ms``, or ``None`` (a failing candle source gives no ATR)."""
        settings = self._settings
        allowance = max(2 * settings.atr_interval_ms, _MIN_WINDOW_MS)
        start = before_ms - (settings.atr_period + 1) * settings.atr_interval_ms - allowance
        try:
            bars = self._candles.get(coin, settings.atr_interval, start, before_ms)
        except Exception:
            _log.warning("candles unavailable for the ATR", extra={"event": "positions_candles_failed"}, exc_info=True)
            return None
        return rules.atr(bars, period=settings.atr_period, before_ms=before_ms, max_age_ms=allowance)

    def _read_clock(self) -> int | None:
        try:
            now = self._exchange_time.exchange_now().ms
        except ClockUnsyncedError as error:  # expected at start-up: one short line per reason, not a traceback per read
            if self._unsynced_logged != str(error):
                self._unsynced_logged = str(error)
                _log.warning(
                    "exchange time is not available yet (%s): entries refused until it is",
                    error,
                    extra={"event": "positions_clock_unsynced"},
                )
            return None
        except Exception:
            _log.warning("exchange time unavailable", extra={"event": "positions_clock_failed"}, exc_info=True)
            return None
        self._unsynced_logged = None
        self._last_ms = max(self._last_ms, now)
        return now

    def _now_or_last(self) -> int:
        now = self._read_clock()
        return self._last_ms if now is None else now

    def _sync(self) -> int:
        """Move the broker to exchange time and book what that produced, so every decision below sees the fills the
        broker already has. Returns exchange time (the last one seen while the clock is unsynced)."""
        now = self._read_clock()
        if now is None:
            return self._last_ms
        self._book_events(self._broker.advance_to(now))
        return now

    def _share(self, share_id: str) -> ShareState:
        share = self._book.state(share_id)
        if share is None:
            raise KeyError(share_id)
        return share

    def _next_synthetic_tid(self) -> int:
        self._synthetic_tid -= 1
        return self._synthetic_tid

    def _alert(self, kind: str, message: str) -> None:
        try:
            self._alerts.send(Alert(kind=kind, message=message))
        except Exception:
            _log.warning(
                "alert delivery failed", extra={"event": "positions_alert_failed", "kind": kind}, exc_info=True
            )

    def _skip(self, sig: Signal, reason: str, share: ShareState | None = None) -> None:
        self._append_skip(sig.signal_id, sig.wallet, sig.coin, reason, None if share is None else share.share_id)

    def _append_skip(self, signal_id: str, leader: str, coin: str, reason: str, share_id: str | None) -> None:
        payload: dict[str, object] = {"signal_id": signal_id, "leader": leader, "coin": coin, "reason": reason}
        if share_id is not None:
            payload["share_id"] = share_id
        self._append("signal_skip", payload)

    def _append_share(self, event: str, share: ShareState, *, reason: str | None = None) -> None:
        payload: dict[str, object] = {
            "event": event,
            "share_id": share.share_id,
            "leader": share.leader,
            "coin": share.coin,
            "qty": share.qty,
            "entry_px": share.entry_px,
            "stop_px": share.current_stop_px,
            "open_risk_usd": share.open_risk_usd,
        }
        if reason is not None:
            payload["reason"] = reason
        self._append("share_state", payload)

    def _append(self, kind: str, payload: dict[str, object]) -> None:
        self._ledger.append(kind, payload)  # a ledger failure is a system failure: it propagates (F2.AC6)


def _share_payload(share: ShareState) -> dict[str, Any]:
    payload = {name: getattr(share, name) for name in _SHARE_FIELDS}
    del payload["best_px"]  # volatile: carried separately
    return payload


def _share_from_payload(payload: dict[str, Any], best_px: Price) -> ShareState:
    decimals = {"initial_risk_usd", "open_risk_usd", "max_committed_risk_usd", "atr"}
    prices = {"entry_px", "initial_stop_px", "current_stop_px"}
    values: dict[str, Any] = {}
    for name, value in payload.items():
        if name in prices:
            values[name] = Price(value)
        elif name == "qty":
            values[name] = Qty(value)
        else:
            values[name] = Decimal(value) if name in decimals else value
    return ShareState(best_px=best_px, **values)


def _track_payload(track: _Track) -> dict[str, Any]:
    return {
        "open_ms": track.open_ms,
        "evidence_ms": track.evidence_ms,
        "close_ms": track.close_ms,
        "closing_ms": track.closing_ms,
        "stop_seq": track.stop_seq,
        "sl_cid": track.sl_cid,
        "sl_qty": track.sl_qty,
        "stops": {cid: list(values) for cid, values in sorted(track.stops.items())},
    }


def _track_from_payload(payload: dict[str, Any], cid_map: Mapping[str, str]) -> _Track:
    return _Track(
        open_ms=payload["open_ms"],
        evidence_ms=payload["evidence_ms"],
        close_ms=payload["close_ms"],
        closing_ms=payload["closing_ms"],
        stop_seq=payload["stop_seq"],
        sl_cid=None if payload["sl_cid"] is None else cid_map.get(payload["sl_cid"], payload["sl_cid"]),
        sl_qty=Decimal(payload["sl_qty"]),
        stops={
            cid_map.get(cid, cid): (kind, Decimal(qty), Decimal(trigger))
            for cid, (kind, qty, trigger) in payload["stops"].items()
        },
    )


def _remember(seen: dict[_K, None], key: _K) -> None:
    """Add ``key`` to a bounded, insertion-ordered set."""
    seen[key] = None
    if len(seen) > SEEN_LIMIT:
        del seen[next(iter(seen))]


def _event_key(event: BrokerEvent) -> tuple[object, ...]:
    """What makes a broker event the same event when it is handed over twice."""
    fill = event.fill
    return (
        event.kind,
        event.time_ms,
        event.coin,
        event.client_order_id,
        event.reason,
        None if fill is None else (fill.qty, fill.price, fill.share_id),
    )
