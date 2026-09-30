"""The paper broker (F11). Paper only: it never touches a network, an exchange endpoint or a signing client."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Concatenate, ParamSpec, TypeVar, cast

from copytrade.core.clock import Clock, TimeSource, Timestamp
from copytrade.core.config import Config
from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert, AlertSink
from copytrade.core.money import MAX_SZ_DECIMALS, Fee, Funding, Pnl, Price, Qty, round_size
from copytrade.hl.models import L2Book
from copytrade.ledger.records import FillRecord, TradeRecord
from copytrade.ledger.store import Ledger
from copytrade.paper.book import BookWalk, walk_book
from copytrade.paper.errors import PaperBrokerFailedError
from copytrade.paper.gate import GateAuthority
from copytrade.paper.liquidation import bankruptcy_price
from copytrade.paper.ports import BookSource, FundingSource, MetaSource
from copytrade.paper.settings import BPS_DIVISOR, MAX_FUNDING_RATE_PER_HOUR, MONEY_CONTEXT, PaperSettings
from copytrade.paper.state import (
    ENTRY_ACTIONS,
    ZERO,
    FundingDue,
    PendingOrder,
    Position,
    RegisteredStop,
    Share,
    merged_view,
    sign_of_side,
)
from copytrade.paper.types import (
    BrokerEvent,
    CoinMeta,
    FundingSnapshot,
    GateToken,
    MarkUpdate,
    OrderIntent,
    PositionView,
    StopIntent,
    SubmitResult,
)

_log = logging.getLogger(__name__)

HOUR_MS = 3_600_000
_SIDES = ("buy", "sell")
_STOP_REASONS = {"sl": "stop_loss", "tp": "take_profit"}
# The order in which things that happen at the same millisecond are applied: an exit fill comes before the funding
# boundary (a share closed at the boundary did not hold the position over it), which comes before an entry fill
# (a share opened at the boundary was not held over it); a late alert never beats a fill at the same time.
_RANK_EXIT_FILL = 0
_RANK_BOUNDARY = 1
_RANK_ENTRY = 2
_RANK_ALERT = 3

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _fail_closed(method: Callable[Concatenate[PaperBroker, _P], _R]) -> Callable[Concatenate[PaperBroker, _P], _R]:
    """Run a state-changing method at money precision, and latch the broker as failed if it raises for any reason.

    A ledger append that fails (F2.AC6) or any other unexpected error can leave the in-memory books disagreeing with
    the ledger, so from then on every state-changing call refuses (A2). Queries stay available."""

    @functools.wraps(method)
    def wrapper(self: PaperBroker, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        if self._failed:
            raise PaperBrokerFailedError(
                "the paper broker failed closed after an earlier error and refuses to continue"
            )
        try:
            with localcontext(MONEY_CONTEXT):
                return method(self, *args, **kwargs)
        except BaseException:
            self._failed = True
            raise

    return cast("Callable[Concatenate[PaperBroker, _P], _R]", wrapper)


@dataclass(frozen=True)
class _Admitted:
    """An order or stop that passed every exchange rule: its lot-rounded size and the coin's rules."""

    qty: Decimal
    meta: CoinMeta
    full_close: bool = False


@dataclass(frozen=True)
class _Probe:
    """What the next attempt of a pending order will use: the book (``None``: an entry's window ran out with no
    usable book) and the time it happens at."""

    time_ms: int
    book: L2Book | None


class PaperBroker:
    """Simulated account (``paper.wallet_usd``), isolated margin, one merged position per coin, shares tracked by ID.

    Time is explicit: ``submit`` and ``place_stop`` answer at once; everything that needs a book, a mark or the
    clock happens in ``advance_to``, ``on_mark`` and ``on_delist``, each returning the events it caused (also
    appended to the ledger). ``on_mark`` and ``on_delist`` first bring the broker up to their own time, so the
    events of anything that fell due on the way are part of what they return. Ledger append errors propagate to
    the caller (F2.AC6) and the broker then refuses every further state-changing call.

    Raises ``ConfigError`` at construction for a missing or out-of-range key, ``mode`` other than ``paper``.
    """

    def __init__(  # noqa: PLR0913 - the boundaries are injected
        self,
        *,
        config: Config,
        books: BookSource,
        meta: MetaSource,
        funding: FundingSource,
        ledger: Ledger,
        clock: Clock,
        alerts: AlertSink,
        authority: GateAuthority,
    ) -> None:
        self._settings = PaperSettings.from_config(config)
        self._books = books
        self._meta_source = meta
        self._funding = funding
        self._ledger = ledger
        self._clock = clock
        self._alerts = alerts
        self._authority = authority

        self._cash: Decimal = self._settings.wallet_usd
        self._positions: dict[str, Position] = {}
        self._pending: dict[str, PendingOrder] = {}
        self._stops: dict[str, RegisteredStop] = {}
        self._delisted: set[str] = set()
        self._used_tokens: set[str] = set()
        self._meta: Mapping[str, CoinMeta] | None = None
        self._meta_fetched_ms = 0
        self._dues: list[FundingDue] = []
        self._missing_alerted: dict[str, int] = {}
        self._retired: set[tuple[str, str]] = set()
        self._next_boundary_ms: int | None = None
        self._now_ms = 0
        self._failed = False

    # ------------------------------------------------------------------------------------------ queries

    def position(self, coin: str) -> PositionView | None:
        position = self._positions.get(coin)
        return None if position is None else position.view()

    def cash_usd(self) -> Decimal:
        """Wallet cash (a ``Decimal``): ``paper.wallet_usd`` plus realised P&L, minus fees, plus funding."""
        return Decimal(self._cash)

    # ------------------------------------------------------------------------------------- orders in

    @_fail_closed
    def submit(self, intent: OrderIntent, token: GateToken) -> SubmitResult:
        """Accept a gate-approved market order. See ``SubmitResult`` for the refusal reasons."""
        cid = intent.client_order_id
        refusal = self._token_refusal(intent, token)
        if refusal is None and self._ledger.has_client_order_id(cid):
            refusal = "duplicate_client_order_id"
        admitted: _Admitted | str = refusal if refusal is not None else self._admit_order(intent)
        if isinstance(admitted, str):
            return self._refuse(cid, intent.coin, admitted)
        self._ledger.append(
            "paper_order",
            {
                "coin": intent.coin,
                "side": intent.side,
                "action": intent.action.value,
                "requested_qty": intent.qty,
                "qty": admitted.qty,
                "decision_px": intent.decision_px,
                "decided_at_ms": intent.decided_at_ms,
                "trade_id": intent.trade_id,
                "share_id": intent.share_id,
                "leverage": intent.leverage,
                "exit_reason": intent.exit_reason,
            },
            client_order_id=cid,
        )
        decided_at_ms = (
            intent.decided_at_ms if intent.action in ENTRY_ACTIONS else max(intent.decided_at_ms, self._now_ms)
        )
        fill_at_ms = decided_at_ms + self._settings.ack_delay_ms
        self._pending[cid] = PendingOrder(
            client_order_id=cid,
            coin=intent.coin,
            side=intent.side,
            requested_qty=admitted.qty,
            remaining=admitted.qty,
            action=intent.action,
            decided_at_ms=decided_at_ms,
            fill_at_ms=fill_at_ms,
            share_id=intent.share_id,
            trade_id=intent.trade_id,
            leverage=intent.leverage if intent.leverage is not None else 0,
            exit_reason=intent.exit_reason,
            sz_decimals=admitted.meta.sz_decimals,
            max_leverage=admitted.meta.max_leverage,
            next_attempt_ms=fill_at_ms,
            alert_due_ms=decided_at_ms + self._settings.alert_after_ms,
        )
        return SubmitResult(client_order_id=cid, accepted=True, reason=None)

    @_fail_closed
    def place_stop(self, intent: StopIntent, token: GateToken) -> SubmitResult:
        """Register a gate-approved SL or TP."""
        cid = intent.client_order_id
        refusal = self._token_refusal(intent, token)
        if refusal is None and self._ledger.has_client_order_id(cid):
            refusal = "duplicate_client_order_id"
        admitted: _Admitted | str = refusal if refusal is not None else self._admit_stop(intent)
        if isinstance(admitted, str):
            return self._refuse(cid, intent.coin, admitted)
        self._ledger.append(
            "paper_stop",
            {
                "coin": intent.coin,
                "kind": intent.kind,
                "side": intent.side,
                "qty": admitted.qty,
                "trigger_px": intent.trigger_px,
                "trade_id": intent.trade_id,
                "share_id": intent.share_id,
            },
            client_order_id=cid,
        )
        self._stops[cid] = RegisteredStop(
            client_order_id=cid,
            coin=intent.coin,
            kind=intent.kind,
            side=intent.side,
            qty=admitted.qty,
            trigger_px=intent.trigger_px,
            trade_id=intent.trade_id,
            share_id=intent.share_id,
            sz_decimals=admitted.meta.sz_decimals,
            max_leverage=admitted.meta.max_leverage,
        )
        return SubmitResult(client_order_id=cid, accepted=True, reason=None)

    @_fail_closed
    def cancel_stop(self, client_order_id: str) -> bool:
        """Cancel a registered stop; ``True`` if one was removed. A stop that already triggered is an order in
        flight, not a stop, and is not cancelled here."""
        stop = self._stops.get(client_order_id)
        if stop is None:
            return False
        self._drop_stop(stop, "cancelled")
        return True

    # ---------------------------------------------------------------------------------- time and marks

    @_fail_closed
    def advance_to(self, now_ms: int) -> Sequence[BrokerEvent]:
        """Resolve pending orders whose fill time has come, and accrue funding for every UTC hour boundary passed."""
        events: list[BrokerEvent] = []
        self._run_until(now_ms, events)
        return tuple(events)

    @_fail_closed
    def on_mark(self, update: MarkUpdate) -> Sequence[BrokerEvent]:
        """Trigger stops and liquidate positions whose liquidation price the mark reached."""
        events: list[BrokerEvent] = []
        time_ms = max(update.time_ms, self._now_ms)
        self._run_until(time_ms, events)
        position = self._positions.get(update.coin)
        if position is None:
            return tuple(events)
        if update.mark <= 0:
            _log.warning("ignoring a non-positive mark", extra={"event": "paper_bad_mark", "coin": update.coin})
            return tuple(events)
        view = self._guarded_view(position)
        reached = view is not None and (
            update.mark <= view.liquidation_px if position.sign > 0 else update.mark >= view.liquidation_px
        )
        if view is not None and reached:
            price = bankruptcy_price(
                side="long" if position.sign > 0 else "short",
                avg_entry_px=view.avg_entry_px,
                leverage=position.leverage,
            )
            self._force_close(position, price, time_ms, "liquidated", events)
            self._send_alert(
                "liquidated",
                f"{update.coin} position liquidated at {price} (mark {update.mark}, trigger {view.liquidation_px})",
            )
        else:
            self._trigger_stops(update.coin, update.mark, time_ms)
        return tuple(events)

    @staticmethod
    def _guarded_view(position: Position) -> PositionView | None:
        """The merged view, or ``None`` (logged) if its liquidation price is not representable: the mark then cannot
        liquidate, but stops still work."""
        try:
            return position.view()
        except ValueError:
            _log.error(
                "paper position has no representable liquidation price",
                extra={"event": "paper_bad_view", "coin": position.coin},
            )
            return None

    def on_delist(self, coin: str, settlement_px: Price, time_ms: int) -> Sequence[BrokerEvent]:
        """Force-settle every share on ``coin`` at ``settlement_px``.

        Raises:
            ValueError: ``settlement_px`` is not a positive finite price. Nothing changes and the broker is not
                latched: the caller passed bad data, and a delisting settled at nothing would be a made-up loss.
        """
        if not settlement_px.is_finite() or settlement_px <= 0:
            raise ValueError("settlement_px must be a positive finite price")
        return self._settle_delisting(coin, settlement_px, time_ms)

    @_fail_closed
    def _settle_delisting(self, coin: str, settlement_px: Price, time_ms: int) -> Sequence[BrokerEvent]:
        events: list[BrokerEvent] = []
        time_ms = max(time_ms, self._now_ms)
        self._run_until(time_ms, events)
        self._delisted.add(coin)
        for order in [o for o in self._pending.values() if o.coin == coin]:
            self._reject_order(order, "delisted", time_ms, events)
        for stop in [s for s in self._stops.values() if s.coin == coin]:
            self._drop_stop(stop, "delisted")
        position = self._positions.get(coin)
        if position is not None:
            self._force_close(position, settlement_px, time_ms, "delisted_force_settle", events)
            self._send_alert("delisted_force_settle", f"{coin} delisted: positions settled at {settlement_px}")
        return tuple(events)

    # ------------------------------------------------------------------------------------ admission

    def _token_refusal(self, intent: OrderIntent | StopIntent, token: GateToken) -> str | None:
        """Verify the token and consume it. A token that verifies is consumed even if the order is then refused."""
        if not self._authority.verify(token, intent):
            return "invalid_gate_token"
        if token.token_id in self._used_tokens:
            return "gate_token_reused"
        self._used_tokens.add(token.token_id)
        return None

    def _refuse(self, client_order_id: str, coin: str, reason: str) -> SubmitResult:
        self._ledger.append("paper_reject", {"client_order_id": client_order_id, "coin": coin, "reason": reason})
        _log.info("paper order refused", extra={"event": "paper_refused", "reason": reason, "coin": coin})
        return SubmitResult(client_order_id=client_order_id, accepted=False, reason=reason)

    def _admit_order(self, intent: OrderIntent) -> _Admitted | str:
        """Apply the exchange rules to a market order: a refusal reason, or the admitted size."""
        is_entry = intent.action in ENTRY_ACTIONS
        coin_meta = self._rules_for(intent.coin, intent.side, is_entry=is_entry)
        if isinstance(coin_meta, str):
            return coin_meta
        if is_entry and intent.decided_at_ms < self._now_ms:
            return "stale_decision"
        qty = self._lot_size(intent.qty, coin_meta)
        if isinstance(qty, str):
            return qty
        refusal = self._leverage_refusal(intent.leverage, coin_meta.max_leverage) if is_entry else None
        full_close = False
        if refusal is None:
            refusal, full_close = self._reduction_refusal(intent, qty, is_entry=is_entry)
        if refusal is None and not full_close and qty * intent.decision_px < self._settings.min_order_usd:
            refusal = "below_min_notional"
        return refusal if refusal is not None else _Admitted(qty, coin_meta, full_close)

    @staticmethod
    def _lot_size(requested: Decimal, coin_meta: CoinMeta) -> Decimal | str:
        """``requested`` rounded down to the lot (never up: exposure never grows), or the reason it is unusable."""
        if requested <= 0:
            return "invalid_qty"
        qty = Decimal(round_size(requested, coin_meta.sz_decimals))
        return qty if qty > 0 else "below_min_notional"

    def _admit_stop(self, intent: StopIntent) -> _Admitted | str:
        if intent.kind not in _STOP_REASONS:
            return "invalid_stop_kind"
        coin_meta = self._rules_for(intent.coin, intent.side, is_entry=False)
        if isinstance(coin_meta, str):
            return coin_meta
        if intent.qty <= 0:
            return "invalid_qty"
        if intent.trigger_px <= 0:
            return "invalid_trigger"
        qty = Decimal(round_size(intent.qty, coin_meta.sz_decimals))
        position = self._positions.get(intent.coin)
        share = None if position is None else position.shares.get(intent.share_id)
        if share is None or share.sign == sign_of_side(intent.side) or qty <= 0 or qty > abs(share.qty):
            return "exceeds_position"
        return _Admitted(qty, coin_meta)

    def _rules_for(self, coin: str, side: str, *, is_entry: bool) -> CoinMeta | str:
        """The rules an order on ``coin`` is admitted under. An exit or stop on a coin we hold uses the rules stored
        on the position, so a ``meta`` refresh that dropped or broke the coin can never block it (F10.AC7); every
        other order needs the exchange's current ``meta``."""
        position = self._positions.get(coin)
        if not is_entry and position is not None and side in _SIDES:
            return CoinMeta(position.sz_decimals, position.max_leverage)
        return self._coin_meta(coin, side)

    def _coin_meta(self, coin: str, side: str) -> CoinMeta | str:
        """The coin's exchange rules, or the reason the order cannot be placed on it."""
        if side not in _SIDES:
            return "invalid_side"
        if coin in self._delisted:
            return "delisted"
        self._refresh_meta(self._clock.now_ms())
        if self._meta is None:
            return "meta_unavailable"
        return self._meta.get(coin, "unknown_coin")

    def _refresh_meta(self, now_ms: int) -> None:
        """Fetch ``meta`` on first use and again once ``paper.meta_refresh_min`` has passed. A failed refresh keeps
        the last known meta and is retried on the next call."""
        if self._meta is not None and 0 <= now_ms - self._meta_fetched_ms < self._settings.meta_refresh_ms:
            return
        try:
            fetched = self._meta_source.fetch()
            usable = {coin: rules for coin, rules in fetched.items() if _valid_rules(rules)}
        except Exception as exc:  # meta is read-only and non-money: any failure is "no data", retried
            _log.warning(
                "paper meta refresh failed", extra={"event": "paper_meta_failed", "error_type": type(exc).__name__}
            )
            return
        self._meta = usable
        self._meta_fetched_ms = now_ms

    @staticmethod
    def _leverage_refusal(leverage: int | None, max_leverage: int) -> str | None:
        if leverage is None:
            return "leverage_missing"
        if type(leverage) is not int or leverage < 1:
            return "leverage_invalid"
        return "leverage_exceeds_max" if leverage > max_leverage else None

    def _reduction_refusal(self, intent: OrderIntent, qty: Decimal, *, is_entry: bool) -> tuple[str | None, bool]:
        """Whether the order is allowed against the position on its coin. Returns ``(refusal, full_close)``.

        An entry never reduces a position: on the opposite side of one it is refused (a flip is a CLOSE, then an
        OPEN once the close has filled). An exit must reduce a share of ours and fit inside what no accepted exit is
        already going to close."""
        sign = sign_of_side(intent.side)
        position = self._positions.get(intent.coin)
        if is_entry:
            return ("opposite_side_entry" if position is not None and position.sign != sign else None), False
        share = None if position is None else position.shares.get(intent.share_id)
        if share is None or share.sign == sign:
            return "exceeds_position", False
        available = abs(share.qty) - self._pending_reduction(share)
        if qty > available:
            return "exceeds_position", False
        return None, qty == available

    def _pending_reduction(self, share: Share) -> Decimal:
        """Quantity of ``share`` that accepted exits are already going to close (a pending entry reduces nothing)."""
        return sum(
            (
                order.remaining
                for order in self._pending.values()
                if not order.is_entry
                and order.coin == share.coin
                and order.share_id == share.share_id
                and sign_of_side(order.side) != share.sign
            ),
            ZERO,
        )

    # ------------------------------------------------------------------------------- the event loop

    def _run_until(self, now_ms: int, events: list[BrokerEvent]) -> None:
        """Apply everything due at or before ``now_ms`` in time order: fills, funding boundaries, exit alerts."""
        while True:
            due = self._next_due(now_ms, events)
            if due is None:
                break
            due()
        self._settle_funding()
        self._now_ms = max(self._now_ms, now_ms)

    def _next_due(self, now_ms: int, events: list[BrokerEvent]) -> Callable[[], None] | None:
        candidates: list[tuple[int, int, int, Callable[[], None]]] = []
        if self._next_boundary_ms is not None and self._next_boundary_ms <= now_ms:
            candidates.append((self._next_boundary_ms, _RANK_BOUNDARY, 0, self._boundary_step))
        for seq, order in enumerate(self._pending.values()):
            probe = self._probe(order, now_ms)
            if probe is not None:
                rank = _RANK_ENTRY if order.is_entry else _RANK_EXIT_FILL
                candidates.append((probe.time_ms, rank, seq, functools.partial(self._resolve, order, probe, events)))
            if not order.is_entry and not order.alerted and order.alert_due_ms <= now_ms:
                candidates.append(
                    (order.alert_due_ms, _RANK_ALERT, seq, functools.partial(self._exit_alert, order, events))
                )
        if not candidates:
            return None
        return min(candidates, key=lambda candidate: candidate[:3])[3]

    def _probe(self, order: PendingOrder, now_ms: int) -> _Probe | None:
        return self._probe_entry(order, now_ms) if order.is_entry else self._probe_exit(order, now_ms)

    def _probe_entry(self, order: PendingOrder, now_ms: int) -> _Probe | None:
        """An entry is tried once: at the first snapshot at or after its fill time, if that is within
        ``paper.max_book_age_ms`` of it. Once that window has passed without one, it is refused ``no_book``."""
        window_end_ms = order.fill_at_ms + self._settings.max_book_age_ms
        book = self._book_from(order.coin, order.fill_at_ms, now_ms)
        if book is not None and book.time_ms <= window_end_ms:
            return _Probe(book.time_ms, book)
        if now_ms > window_end_ms:
            return _Probe(window_end_ms + 1, None)
        return None

    def _probe_exit(self, order: PendingOrder, now_ms: int) -> _Probe | None:
        """An exit is retried every ``exits.retry_interval_s`` from its fill time. An attempt at ``a`` may use the
        first snapshot at or after ``a`` if it is within ``paper.max_book_age_ms`` of ``a``. An attempt whose window
        has not closed and whose snapshot is not visible yet stays alive (so the events do not depend on how often
        ``advance_to`` is called); only attempts that provably cannot succeed by ``now_ms`` are skipped, in one step,
        so a long gap costs one book lookup, not one per second."""
        retry_ms = self._settings.retry_interval_ms
        max_age_ms = self._settings.max_book_age_ms
        attempt_ms = order.next_attempt_ms
        while attempt_ms <= now_ms:
            book = self._book_from(order.coin, attempt_ms, now_ms)
            if book is None:
                closed_ms = now_ms - max_age_ms - attempt_ms
                if closed_ms > 0:
                    attempt_ms += retry_ms * -(-closed_ms // retry_ms)
                break
            if book.time_ms <= attempt_ms + max_age_ms:
                order.next_attempt_ms = attempt_ms
                return _Probe(book.time_ms, book)
            behind_ms = book.time_ms - max_age_ms - attempt_ms
            attempt_ms += retry_ms * -(-behind_ms // retry_ms)
        order.next_attempt_ms = attempt_ms
        return None

    def _book_from(self, coin: str, from_ms: int, now_ms: int) -> L2Book | None:
        """The first recorded snapshot at or after ``from_ms`` that exists at ``now_ms`` (D1: a recorded book from
        the future is never used), or ``None``."""
        try:
            book = self._books.first_book_at_or_after(coin, from_ms)
            if book is None or book.coin != coin or book.time_ms < from_ms or book.time_ms > now_ms:
                return None
        except Exception as exc:  # a read-only, non-money port: any failure is "no book yet"
            _log.warning(
                "paper book source failed", extra={"event": "paper_book_failed", "error_type": type(exc).__name__}
            )
            return None
        return book

    # ------------------------------------------------------------------------------------------ fills

    def _resolve(self, order: PendingOrder, probe: _Probe, events: list[BrokerEvent]) -> None:
        if probe.book is None:
            self._reject_order(order, "no_book", probe.time_ms, events)
        else:
            self._fill_from_book(order, probe.book, events)

    def _fill_from_book(self, order: PendingOrder, book: L2Book, events: list[BrokerEvent]) -> None:
        time_ms = book.time_ms
        position = self._positions.get(order.coin)
        share = None if position is None else position.shares.get(order.share_id)
        target = order.remaining
        if order.is_entry:
            # Re-checked at fill time: what was true when the order was accepted may not be any more.
            if (order.share_id, order.coin) in self._retired:
                self._reject_order(order, "share_closed", time_ms, events)
                return
            if position is not None and position.sign != sign_of_side(order.side):
                self._reject_order(order, "opposite_side_entry", time_ms, events)
                return
        else:
            if share is None or share.sign == sign_of_side(order.side):
                self._cancel_order(order, "share_closed")
                return
            target = min(order.remaining, abs(share.qty))
        walk = walk_book(book, side=order.side, qty=target, sz_decimals=order.sz_decimals)
        if walk is None:
            if order.is_entry:
                self._reject_order(order, "no_depth", time_ms, events)
            else:
                order.next_attempt_ms = time_ms + self._settings.retry_interval_ms
            return
        self._commit_fill(order, position=position, share=share, walk=walk, time_ms=time_ms, events=events)

    def _commit_fill(  # noqa: PLR0913 - one fill's context
        self,
        order: PendingOrder,
        *,
        position: Position | None,
        share: Share | None,
        walk: BookWalk,
        time_ms: int,
        events: list[BrokerEvent],
    ) -> None:
        """Book one fill: build every record, append them to the ledger, and only then change the in-memory state."""
        fee = self._fee(walk.cost)
        gross = ZERO
        closed = False
        if not order.is_entry:
            assert share is not None  # noqa: S101 - _fill_from_book only commits an exit against its share
            updated, gross = share.reduced(walk.qty, walk.cost, fee)
            closed = updated.qty == 0
        else:
            base = share if share is not None else Share(order.share_id, order.trade_id, order.coin, ZERO, ZERO)
            updated = base.extended(sign_of_side(order.side) * walk.qty, walk.cost, fee)
            if not self._liquidation_representable(order, position, updated):
                self._reject_order(order, "liquidation_unrepresentable", time_ms, events)
                return
        remaining_after = order.remaining - walk.qty
        done = order.is_entry or closed or remaining_after <= 0
        partial = remaining_after > 0 and (order.is_entry or not closed)
        fill = FillRecord(
            time=Timestamp(time_ms, TimeSource.EXCHANGE),
            coin=order.coin,
            side=order.side,
            qty=Qty(walk.qty),
            price=Price(walk.cost / walk.qty),
            fee=Fee(fee),
            funding=Funding(updated.funding if closed else ZERO),
            client_order_id=order.client_order_id,
            trade_id=updated.trade_id,
            share_id=updated.share_id,
            exit_reason=None if order.is_entry else (order.exit_reason or order.action.value),
        )
        trade = self._trade_of(updated, time_ms, frozenset()) if closed else None
        self._ledger.append_fill(fill)
        if trade is not None:
            self._ledger.append_trade(trade)
        if partial:
            self._ledger.append(
                "partial_fill",
                {
                    "client_order_id": order.client_order_id,
                    "requested_qty": order.requested_qty,
                    "filled_qty": walk.qty,
                    "cancelled_qty": remaining_after if order.is_entry else ZERO,
                    "requeued_qty": ZERO if order.is_entry else remaining_after,
                },
            )
        self._cash += gross - fee
        self._store_share(order, position, updated, time_ms)
        if done:
            del self._pending[order.client_order_id]
        else:
            order.remaining = remaining_after
            order.next_attempt_ms = time_ms + self._settings.retry_interval_ms
        if closed:
            self._retire_share(updated)
        kind = "partial_fill" if partial else "fill"
        events.append(BrokerEvent(kind, time_ms, order.coin, order.client_order_id, None, fill, trade))

    def _liquidation_representable(self, order: PendingOrder, position: Position | None, updated: Share) -> bool:
        """Whether the position after this entry has a liquidation price on the exchange grid (fail closed)."""
        shares = dict(position.shares) if position is not None else {}
        shares[updated.share_id] = updated
        try:
            merged_view(
                order.coin,
                shares.values(),
                leverage=position.leverage if position is not None else order.leverage,
                max_leverage=order.max_leverage,
                sz_decimals=order.sz_decimals,
            )
        except ValueError:
            return False
        return True

    def _store_share(self, order: PendingOrder, position: Position | None, updated: Share, time_ms: int) -> None:
        """Put the share's new state into its position, creating the position (and starting the funding clock)
        for the first share on a coin."""
        if updated.qty == 0:
            if position is not None:
                del position.shares[updated.share_id]
            return
        if position is None:
            position = Position(order.coin, order.leverage, order.max_leverage, order.sz_decimals)
            self._positions[order.coin] = position
        if order.is_entry:  # the leverage stays the first entry's; the exchange's rules are the latest known
            position.max_leverage = order.max_leverage
            position.sz_decimals = order.sz_decimals
        position.shares[updated.share_id] = updated
        if self._next_boundary_ms is None:
            self._next_boundary_ms = self._boundary_after(time_ms)

    def _fee(self, notional_usd: Decimal) -> Decimal:
        """The taker fee: ``cost.taker_fee_bps`` of ``notional_usd``, unrounded (D3). Every fill pays it."""
        return notional_usd * self._settings.taker_fee_bps / BPS_DIVISOR

    @staticmethod
    def _trade_of(share: Share, time_ms: int, flags: frozenset[str]) -> TradeRecord:
        return TradeRecord(
            trade_id=share.trade_id,
            share_id=share.share_id,
            coin=share.coin,
            closed_at=Timestamp(time_ms, TimeSource.EXCHANGE),
            pnl_usd=Pnl(share.net_pnl),
            flags=flags,
        )

    # ------------------------------------------------------------------- liquidation and delisting

    def _force_close(
        self, position: Position, price: Price, time_ms: int, reason: str, events: list[BrokerEvent]
    ) -> None:
        """Close every share of ``position`` at ``price`` (the bankruptcy price of a liquidation, or the settlement
        price on delisting). The fill pays the taker fee like any other; the trade carries ``reason`` as its flag."""
        for share in list(position.shares.values()):
            qty = abs(share.qty)
            cost = qty * price
            fee = self._fee(cost)
            updated, gross = share.reduced(qty, cost, fee)
            client_order_id = f"{reason}:{share.share_id}"
            fill = FillRecord(
                time=Timestamp(time_ms, TimeSource.EXCHANGE),
                coin=share.coin,
                side="sell" if share.sign > 0 else "buy",
                qty=Qty(qty),
                price=price,
                fee=Fee(fee),
                funding=Funding(updated.funding),
                client_order_id=client_order_id,
                trade_id=share.trade_id,
                share_id=share.share_id,
                exit_reason=reason,
            )
            trade = self._trade_of(updated, time_ms, frozenset({reason}))
            self._ledger.append_fill(fill)
            self._ledger.append_trade(trade)
            self._cash += gross - fee
            del position.shares[share.share_id]
            self._retire_share(updated)
            events.append(BrokerEvent(reason, time_ms, share.coin, client_order_id, None, fill, trade))

    def _retire_share(self, share: Share) -> None:
        """A share closed: its exit orders and stops are moot, its ID is never opened again by a pending entry, and
        a coin with no share has no position."""
        self._retired.add((share.share_id, share.coin))
        for order in [o for o in self._pending.values() if o.share_id == share.share_id and not o.is_entry]:
            self._cancel_order(order, "share_closed")
        for stop in [s for s in self._stops.values() if s.share_id == share.share_id]:
            self._drop_stop(stop, "share_closed")
        position = self._positions.get(share.coin)
        if position is not None and not position.shares:
            del self._positions[share.coin]
        if not self._positions:
            self._next_boundary_ms = None

    # ------------------------------------------------------------------------------- stops, cancels

    def _trigger_stops(self, coin: str, mark: Price, time_ms: int) -> None:
        """Turn every stop the mark has reached into an exit order decided now, to fill at the book
        ``paper.ack_delay_ms`` later. The stop is spent: it cannot fire twice."""
        position = self._positions.get(coin)
        for stop in [s for s in self._stops.values() if s.coin == coin and s.triggered_by(mark)]:
            share = None if position is None else position.shares.get(stop.share_id)
            if share is None:
                self._drop_stop(stop, "share_closed")
                continue
            qty = min(stop.qty, abs(share.qty) - self._pending_reduction(share))
            if qty <= 0:
                continue
            self._ledger.append(
                "paper_stop_trigger",
                {"client_order_id": stop.client_order_id, "coin": coin, "mark": mark, "time_ms": time_ms},
            )
            del self._stops[stop.client_order_id]
            fill_at_ms = time_ms + self._settings.ack_delay_ms
            self._pending[stop.client_order_id] = PendingOrder(
                client_order_id=stop.client_order_id,
                coin=coin,
                side=stop.side,
                requested_qty=qty,
                remaining=qty,
                action=ActionKind.CLOSE if qty == abs(share.qty) else ActionKind.REDUCE,
                decided_at_ms=time_ms,
                fill_at_ms=fill_at_ms,
                share_id=stop.share_id,
                trade_id=stop.trade_id,
                leverage=0,
                exit_reason=_STOP_REASONS[stop.kind],
                sz_decimals=stop.sz_decimals,
                max_leverage=stop.max_leverage,
                next_attempt_ms=fill_at_ms,
                alert_due_ms=time_ms + self._settings.alert_after_ms,
            )

    def _drop_stop(self, stop: RegisteredStop, reason: str) -> None:
        self._ledger.append(
            "paper_cancel", {"client_order_id": stop.client_order_id, "target": "stop", "reason": reason}
        )
        del self._stops[stop.client_order_id]

    def _cancel_order(self, order: PendingOrder, reason: str) -> None:
        self._ledger.append(
            "paper_cancel", {"client_order_id": order.client_order_id, "target": "order", "reason": reason}
        )
        del self._pending[order.client_order_id]

    def _reject_order(self, order: PendingOrder, reason: str, time_ms: int, events: list[BrokerEvent]) -> None:
        self._ledger.append(
            "paper_reject", {"client_order_id": order.client_order_id, "coin": order.coin, "reason": reason}
        )
        del self._pending[order.client_order_id]
        _log.info("paper order rejected", extra={"event": "paper_rejected", "reason": reason, "coin": order.coin})
        events.append(BrokerEvent("reject", time_ms, order.coin, order.client_order_id, reason, None, None))

    # ---------------------------------------------------------------------------------- exit alerts

    def _exit_alert(self, order: PendingOrder, events: list[BrokerEvent]) -> None:
        """One alert for an exit still unfilled ``exits.alert_after_s`` after its decision (A8)."""
        self._ledger.append(
            "paper_alert",
            {
                "kind": "exit_unfilled",
                "client_order_id": order.client_order_id,
                "coin": order.coin,
                "share_id": order.share_id,
            },
        )
        order.alerted = True
        self._send_alert("exit_unfilled", f"{order.coin} exit {order.client_order_id} is still unfilled")
        events.append(
            BrokerEvent("exit_unfilled_alert", order.alert_due_ms, order.coin, order.client_order_id, None, None, None)
        )

    def _send_alert(self, kind: str, message: str) -> None:
        try:
            self._alerts.send(Alert(kind=kind, message=message))
        except Exception as exc:  # a non-money sink: a failed alert must never stop the books
            _log.warning(
                "paper alert delivery failed", extra={"event": "paper_alert_failed", "error_type": type(exc).__name__}
            )

    # --------------------------------------------------------------------------------------- funding

    @staticmethod
    def _boundary_after(time_ms: int) -> int:
        """The first UTC hour boundary strictly after ``time_ms``."""
        return (time_ms // HOUR_MS + 1) * HOUR_MS

    def _boundary_step(self) -> None:
        """An hour boundary: every share held over it owes that hour's funding. Shares opened at the boundary or
        later are not in ``_positions`` yet (entry fills at the same millisecond come after it)."""
        boundary_ms = self._next_boundary_ms
        if boundary_ms is None:
            return
        for position in self._positions.values():
            self._dues.extend(
                FundingDue(position.coin, share.share_id, boundary_ms, share.qty) for share in position.shares.values()
            )
        self._next_boundary_ms = boundary_ms + HOUR_MS
        self._settle_funding()

    def _settle_funding(self) -> None:
        """Post every owed funding whose hour's actual rate is known, oldest first. Each hour settles on its own: a
        missing rate is retried on every call (never skipped, D3) and alerted once per coin per stretch, and it does
        not hold back the later hours."""
        waiting: list[FundingDue] = []
        for due in self._dues:
            snapshot = self._funding_snapshot(due)
            if snapshot is None:
                waiting.append(due)
                self._alert_funding_missing(due)
            else:
                self._post_funding(due, snapshot)
        self._dues = waiting

    def _funding_snapshot(self, due: FundingDue) -> FundingSnapshot | None:
        try:
            snapshot = self._funding.funding_at(due.coin, due.hour_ms)
            usable = (
                snapshot is not None
                and snapshot.coin == due.coin
                and snapshot.hour_ms == due.hour_ms
                and snapshot.rate.is_finite()
                and abs(snapshot.rate) <= MAX_FUNDING_RATE_PER_HOUR
                and snapshot.oracle_px.is_finite()
                and snapshot.oracle_px > 0
            )
        except Exception as exc:  # a read-only, non-money port: any failure is "no data", retried
            _log.warning(
                "paper funding source failed",
                extra={"event": "paper_funding_failed", "error_type": type(exc).__name__},
            )
            return None
        return snapshot if usable else None

    def _post_funding(self, due: FundingDue, snapshot: FundingSnapshot) -> None:
        """``qty x oracle_px x rate``, paid by longs when the rate is positive; the amount is a cash flow to us."""
        amount = ZERO - due.signed_qty * snapshot.oracle_px * snapshot.rate
        self._ledger.append(
            "paper_funding",
            {
                "coin": due.coin,
                "share_id": due.share_id,
                "hour_ms": due.hour_ms,
                "rate": snapshot.rate,
                "oracle_px": snapshot.oracle_px,
                "amount": amount,
            },
        )
        self._cash += amount
        if self._missing_alerted.get(due.coin) == due.hour_ms:
            del self._missing_alerted[due.coin]
        position = self._positions.get(due.coin)
        share = None if position is None else position.shares.get(due.share_id)
        if position is not None and share is not None:
            position.shares[due.share_id] = share.with_funding(amount)

    def _alert_funding_missing(self, due: FundingDue) -> None:
        """One alert per coin per stretch of missing data: the hour alerted about is remembered, and the coin alerts
        again only after that hour's rate has arrived and a later hour goes missing."""
        if due.coin in self._missing_alerted:
            return
        self._ledger.append("paper_alert", {"kind": "funding_missing", "coin": due.coin, "hour_ms": due.hour_ms})
        self._missing_alerted[due.coin] = due.hour_ms
        self._send_alert("funding_missing", f"no funding rate for {due.coin} at hour {due.hour_ms}; retrying")


def _valid_rules(rules: object) -> bool:
    """Whether a coin's fetched rules are usable; a coin with unusable rules is treated as not listed."""
    return (
        isinstance(rules, CoinMeta)
        and type(rules.sz_decimals) is int
        and 0 <= rules.sz_decimals <= MAX_SZ_DECIMALS
        and type(rules.max_leverage) is int
        and rules.max_leverage >= 1
    )
