"""Replay of the paper broker's books from the ledger (R0 startup reload, A7: the ledger is the source of truth).

``replay_broker`` is a pure function over ledger records in sequence order. It applies the SAME share arithmetic the
broker used (``Share.extended`` / ``Share.reduced``), so cash, cost bases and positions come out as they were. The
quantity of a share is exact from the fill records; its cost is recovered from the fill's fee (exact whenever the fee
was exact, i.e. the original cost fits the 60-digit money context) and cross-checked against ``qty x price``.

The result describes what the broker held when the records stop: positions with their shares, the stops registered
and not triggered, the exit orders not yet filled, and the entries still pending (an entry is stale by definition once
the process is gone: the broker drops them, see ``PaperBroker.restore``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from decimal import Decimal, localcontext
from typing import Any

from copytrade.core.domain import ActionKind
from copytrade.ledger.records import LedgerRecord
from copytrade.paper.settings import BPS_DIVISOR, MONEY_CONTEXT, PaperSettings
from copytrade.paper.state import ENTRY_ACTIONS, ZERO, Share, sign_of_side

KIND_PAPER_ORDER = "paper_order"
KIND_FILL = "fill"
KIND_PAPER_STOP = "paper_stop"
KIND_PAPER_CANCEL = "paper_cancel"
KIND_PAPER_REJECT = "paper_reject"
KIND_PAPER_STOP_TRIGGER = "paper_stop_trigger"
KIND_PAPER_FUNDING = "paper_funding"
# Every ledger kind that changes what the broker holds (the reload compares the last checkpoint against these).
BROKER_STATE_KINDS = frozenset(
    {KIND_PAPER_ORDER, KIND_FILL, "trade", "partial_fill", KIND_PAPER_STOP, KIND_PAPER_CANCEL, KIND_PAPER_STOP_TRIGGER}
)
STOP_EXIT_REASONS = {"sl": "stop_loss", "tp": "take_profit"}
_COST_TOLERANCE = Decimal("1e-40")


@dataclass(frozen=True)
class StopSnap:
    """A registered stop that has not triggered."""

    client_order_id: str
    coin: str
    kind: str
    side: str
    qty: Decimal
    trigger_px: Decimal
    trade_id: str
    share_id: str


@dataclass(frozen=True)
class ExitSnap:
    """An accepted exit order (or a triggered stop) that has not filled; ``qty`` is what is still to fill."""

    client_order_id: str
    coin: str
    side: str
    qty: Decimal
    share_id: str
    trade_id: str
    exit_reason: str | None


@dataclass(frozen=True)
class PositionSnap:
    """One merged position: its first entry's leverage and its shares in the order they were opened."""

    coin: str
    leverage: int
    shares: tuple[Share, ...]


@dataclass(frozen=True)
class BrokerSnapshot:
    """What the ledger says the broker held. ``entries`` are the pending entries' client order ids; ``exits`` the
    exit orders that can be proven (their share is held on the opposite side); ``unproven_exits`` those that cannot."""

    cash: Decimal
    positions: tuple[PositionSnap, ...]
    stops: tuple[StopSnap, ...]
    exits: tuple[ExitSnap, ...]
    unproven_exits: tuple[ExitSnap, ...]
    entries: tuple[str, ...]
    retired: frozenset[tuple[str, str]]
    delisted: frozenset[str]
    last_time_ms: int
    last_funding_hour_ms: int | None


@dataclass(frozen=True)
class RestoredOrder:
    """A stop or exit order registered again under a new client order id."""

    old_client_order_id: str
    new_client_order_id: str
    share_id: str


@dataclass(frozen=True)
class RestoreResult:
    """What ``PaperBroker.restore`` did: the stops and exits re-registered (old and new ids), the coins whose rules the
    exchange no longer lists, and the client order ids of the dropped entries and unprovable exits."""

    stops: tuple[RestoredOrder, ...]
    exits: tuple[RestoredOrder, ...]
    unknown_coins: tuple[str, ...]
    dropped_entries: tuple[str, ...]
    dropped_exits: tuple[str, ...]


@dataclass
class _Pending:
    snap: ExitSnap
    action: ActionKind
    leverage: int


@dataclass
class _Book:
    """The mutable books while replaying."""

    settings: PaperSettings
    cash: Decimal
    leverage: dict[str, int] = field(default_factory=dict)
    positions: dict[str, dict[str, Share]] = field(default_factory=dict)
    pending: dict[str, _Pending] = field(default_factory=dict)
    stops: dict[str, StopSnap] = field(default_factory=dict)
    retired: set[tuple[str, str]] = field(default_factory=set)
    delisted: set[str] = field(default_factory=set)
    last_time_ms: int = 0
    last_funding_hour_ms: int | None = None

    # ------------------------------------------------------------------------------------------------ orders
    def order(self, cid: str, p: Any) -> None:
        action = ActionKind(p["action"])
        self.pending[cid] = _Pending(
            ExitSnap(cid, p["coin"], p["side"], Decimal(p["qty"]), p["share_id"], p["trade_id"], p["exit_reason"]),
            action,
            0 if p["leverage"] is None else int(p["leverage"]),
        )

    def stop(self, cid: str, p: Any) -> None:
        self.stops[cid] = StopSnap(
            cid,
            p["coin"],
            p["kind"],
            p["side"],
            Decimal(p["qty"]),
            Decimal(p["trigger_px"]),
            p["trade_id"],
            p["share_id"],
        )

    def cancel(self, p: Any) -> None:
        target = self.pending if p["target"] == "order" else self.stops
        target.pop(p["client_order_id"], None)

    def trigger(self, p: Any) -> None:
        """A stop became an exit order for the quantity the broker would have used: the stop's, capped by what its
        share still holds beyond the exits already pending."""
        stop = self.stops.pop(p["client_order_id"], None)
        share = self.positions.get(p["coin"], {}).get(stop.share_id) if stop is not None else None
        if stop is None or share is None:
            return
        reduction = sum(
            (
                o.snap.qty
                for o in self.pending.values()
                if o.action not in ENTRY_ACTIONS
                and o.snap.share_id == share.share_id
                and sign_of_side(o.snap.side) != share.sign
            ),
            ZERO,
        )
        qty = min(stop.qty, abs(share.qty) - reduction)
        if qty <= 0:
            return
        action = ActionKind.CLOSE if qty == abs(share.qty) else ActionKind.REDUCE
        snap = ExitSnap(
            stop.client_order_id,
            stop.coin,
            stop.side,
            qty,
            stop.share_id,
            stop.trade_id,
            STOP_EXIT_REASONS[stop.kind],
        )
        self.pending[stop.client_order_id] = _Pending(snap, action, 0)

    def funding(self, p: Any) -> None:
        amount = Decimal(p["amount"])
        self.cash += amount
        self.last_funding_hour_ms = max(self.last_funding_hour_ms or 0, int(p["hour_ms"]))
        shares = self.positions.get(p["coin"])
        if shares is not None and p["share_id"] in shares:
            shares[p["share_id"]] = shares[p["share_id"]].with_funding(amount)

    # ------------------------------------------------------------------------------------------------ fills
    def cost_of(self, p: Any, qty: Decimal, price: Decimal, fee: Decimal) -> Decimal:
        """The exact cost of a fill: recovered from its fee when it agrees with ``qty x price``, else that product."""
        approx = qty * price
        if p["exit_reason"] in ("liquidated", "delisted_force_settle") or self.settings.taker_fee_bps == 0:
            return approx
        recovered = fee * BPS_DIVISOR / self.settings.taker_fee_bps
        return recovered if abs(recovered - approx) <= approx * _COST_TOLERANCE else approx

    def fill(self, cid: str, p: Any) -> None:
        coin, share_id = p["coin"], p["share_id"]
        qty, fee = Decimal(p["qty"]), Decimal(p["fee"])
        cost = self.cost_of(p, qty, Decimal(p["price"]), fee)
        self.last_time_ms = max(self.last_time_ms, int(p["time"]["ms"]))
        order = self.pending.get(cid)
        shares = self.positions.get(coin)
        share = None if shares is None else shares.get(share_id)
        if order is not None and order.action in ENTRY_ACTIONS:
            self._entry_fill(order, p, share, (qty, cost, fee))
            del self.pending[cid]
            return
        if share is None:
            return  # an exit fill for a share not held: the ledger is inconsistent there, nothing to apply
        updated, gross = share.reduced(qty, cost, fee)
        self.cash += gross - fee
        closed = updated.qty == 0
        if closed:
            self._retire(coin, share_id)
        else:
            self.positions[coin][share_id] = updated
        if order is not None:
            order.snap = replace(order.snap, qty=order.snap.qty - qty)
            if closed or order.snap.qty <= 0:
                del self.pending[cid]

    def _entry_fill(
        self, order: _Pending, p: Any, share: Share | None, amounts: tuple[Decimal, Decimal, Decimal]
    ) -> None:
        qty, cost, fee = amounts
        coin = p["coin"]
        base = share if share is not None else Share(p["share_id"], p["trade_id"], coin, ZERO, ZERO)
        updated = base.extended(sign_of_side(p["side"]) * qty, cost, fee)
        self.cash -= fee
        if coin not in self.positions:
            self.positions[coin] = {}
            self.leverage[coin] = order.leverage
        self.positions[coin][p["share_id"]] = updated

    def _retire(self, coin: str, share_id: str) -> None:
        self.retired.add((share_id, coin))
        shares = self.positions[coin]
        del shares[share_id]
        if not shares:
            del self.positions[coin]
            del self.leverage[coin]

    def apply(self, record: LedgerRecord) -> None:
        kind, p = record.kind, record.payload
        cid = record.client_order_id
        if kind == KIND_PAPER_ORDER and cid is not None:
            self.order(cid, p)
        elif kind == KIND_FILL and cid is not None:
            if p["exit_reason"] == "delisted_force_settle":
                self.delisted.add(p["coin"])
            self.fill(cid, p)
        elif kind == KIND_PAPER_STOP and cid is not None:
            self.stop(cid, p)
        elif kind == KIND_PAPER_CANCEL:
            self.cancel(p)
        elif kind == KIND_PAPER_STOP_TRIGGER:
            self.trigger(p)
        elif kind == KIND_PAPER_REJECT:
            self.pending.pop(p["client_order_id"], None)
        elif kind == KIND_PAPER_FUNDING:
            self.funding(p)


def replay_broker(records: Iterable[LedgerRecord], settings: PaperSettings) -> BrokerSnapshot:
    """Rebuild the broker's books from ``records`` (every ledger record, in sequence order; unrelated kinds are
    ignored)."""
    book = _Book(settings=settings, cash=settings.wallet_usd)
    with localcontext(MONEY_CONTEXT):
        for record in records:
            book.apply(record)
    exits: list[ExitSnap] = []
    unproven: list[ExitSnap] = []
    for pending in book.pending.values():
        if pending.action in ENTRY_ACTIONS:
            continue
        share = book.positions.get(pending.snap.coin, {}).get(pending.snap.share_id)
        proven = share is not None and sign_of_side(pending.snap.side) != share.sign
        (exits if proven else unproven).append(pending.snap)
    return BrokerSnapshot(
        cash=book.cash,
        positions=tuple(
            PositionSnap(coin, book.leverage[coin], tuple(shares.values()))
            for coin, shares in sorted(book.positions.items())
        ),
        stops=tuple(book.stops.values()),
        exits=tuple(exits),
        unproven_exits=tuple(unproven),
        entries=tuple(cid for cid, o in book.pending.items() if o.action in ENTRY_ACTIONS),
        retired=frozenset(book.retired),
        delisted=frozenset(book.delisted),
        last_time_ms=book.last_time_ms,
        last_funding_hour_ms=book.last_funding_hour_ms,
    )
