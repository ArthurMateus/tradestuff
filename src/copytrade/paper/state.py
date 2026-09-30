"""The broker's mutable bookkeeping: shares, pending orders, stops, and the share arithmetic (F11).

Money here is exact ``Decimal`` at ``MONEY_CONTEXT`` precision. A share keeps its cost basis (USD paid for the open
quantity) rather than an average price, so partial closes stay exact: the last close of a share takes whatever basis
is left, so the bases of all its closes sum to exactly what was paid, however the earlier ones were divided.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.paper.liquidation import exact_liquidation_price, liquidation_price
from copytrade.paper.settings import MONEY_CONTEXT
from copytrade.paper.types import PositionView

ENTRY_ACTIONS = frozenset({ActionKind.OPEN, ActionKind.ADD})
ZERO = Decimal(0)


def sign_of_side(side: str) -> int:
    """+1 for ``buy``, -1 for ``sell``."""
    return 1 if side == "buy" else -1


@dataclass(frozen=True)
class Share:
    """One share of a position: signed ``qty`` (long > 0), the USD ``cost`` basis of that quantity, and what it has
    realised so far: gross P&L, fees paid (positive) and funding received (signed, to us)."""

    share_id: str
    trade_id: str
    coin: str
    qty: Decimal
    cost: Decimal
    realized: Decimal = ZERO
    fees: Decimal = ZERO
    funding: Decimal = ZERO

    @property
    def sign(self) -> int:
        return 1 if self.qty > 0 else -1

    def extended(self, signed_qty: Decimal, cost: Decimal, fee: Decimal) -> Share:
        """This share after a fill of ``signed_qty`` (same direction, or opening it) costing ``cost``."""
        with localcontext(MONEY_CONTEXT):
            return Share(
                self.share_id,
                self.trade_id,
                self.coin,
                self.qty + signed_qty,
                self.cost + cost,
                self.realized,
                self.fees + fee,
                self.funding,
            )

    def reduced(self, closed_qty: Decimal, fill_cost: Decimal, fee: Decimal) -> tuple[Share, Decimal]:
        """This share after closing ``closed_qty`` (> 0, at most ``abs(qty)``) for ``fill_cost``.

        Returns the new share and the gross P&L realised by this close."""
        with localcontext(MONEY_CONTEXT):
            held = abs(self.qty)
            basis = self.cost if closed_qty == held else self.cost * closed_qty / held
            gross = fill_cost - basis if self.qty > 0 else basis - fill_cost
            remaining = self.qty - self.sign * closed_qty
            share = Share(
                self.share_id,
                self.trade_id,
                self.coin,
                remaining,
                self.cost - basis,
                self.realized + gross,
                self.fees + fee,
                self.funding,
            )
            return share, gross

    def with_funding(self, amount: Decimal) -> Share:
        with localcontext(MONEY_CONTEXT):
            return Share(
                self.share_id,
                self.trade_id,
                self.coin,
                self.qty,
                self.cost,
                self.realized,
                self.fees,
                self.funding + amount,
            )

    @property
    def net_pnl(self) -> Decimal:
        """Gross P&L minus fees plus funding: the trade P&L once the share is closed."""
        with localcontext(MONEY_CONTEXT):
            return self.realized - self.fees + self.funding


@dataclass
class Position:
    """The merged isolated position on one coin: its shares in the order they were opened, and the
    leverage of its first entry (a later entry never changes it) and the latest exchange rules."""

    coin: str
    leverage: int
    max_leverage: int
    sz_decimals: int
    shares: dict[str, Share] = field(default_factory=dict)

    @property
    def sign(self) -> int:
        return next(iter(self.shares.values())).sign

    def view(self) -> PositionView:
        """The merged view. Never raises for an off-grid liquidation price (see ``merged_view``)."""
        return merged_view(
            self.coin,
            self.shares.values(),
            leverage=self.leverage,
            max_leverage=self.max_leverage,
            sz_decimals=self.sz_decimals,
        )


def merged_average_entry(shares: Iterable[Share]) -> Price:
    """The quantity-weighted entry price of ``shares`` (all the same direction, at least one)."""
    held = tuple(shares)
    with localcontext(MONEY_CONTEXT):
        return Price(sum((s.cost for s in held), ZERO) / abs(sum((s.qty for s in held), ZERO)))


def merged_view(
    coin: str, shares: Iterable[Share], *, leverage: int, max_leverage: int, sz_decimals: int
) -> PositionView:
    """Merge ``shares`` (all the same direction, at least one) into one isolated position.

    When the liquidation price is not on the exchange grid (a merged average entry that no tick fits), the view
    carries the exact, unrounded liquidation price instead of raising: it keeps the position's leverage, is finite
    and positive, and is what ``on_mark`` compares against, so the position can still liquidate."""
    held = tuple(shares)
    with localcontext(MONEY_CONTEXT):
        signed_qty = sum((s.qty for s in held), ZERO)
        total_cost = sum((s.cost for s in held), ZERO)
        avg_entry = Price(total_cost / abs(signed_qty))
        margin = total_cost / leverage
    side = "long" if signed_qty > 0 else "short"
    try:
        liquidation_px = liquidation_price(
            side=side, avg_entry_px=avg_entry, leverage=leverage, max_leverage=max_leverage, sz_decimals=sz_decimals
        )
    except ValueError:
        liquidation_px = exact_liquidation_price(
            side=side, avg_entry_px=avg_entry, leverage=leverage, max_leverage=max_leverage
        )
    return PositionView(
        coin=coin,
        qty=Qty(signed_qty),
        avg_entry_px=avg_entry,
        leverage=leverage,
        margin_usd=margin,
        liquidation_px=liquidation_px,
        share_ids=tuple(s.share_id for s in held),
        share_qtys=tuple(Qty(abs(s.qty)) for s in held),
    )


@dataclass
class PendingOrder:
    """An accepted market order (or a triggered stop) waiting for its fill.

    ``leverage`` is 0 for an exit. ``remaining`` is what is still to fill. An entry is tried once, inside the
        book-age window that starts at ``fill_at_ms``. An exit is retried every retry interval from ``next_attempt_ms``
        until it fills or its share is closed, and raises one alert at ``alert_due_ms``.
    """

    client_order_id: str
    coin: str
    side: str
    requested_qty: Decimal
    remaining: Decimal
    action: ActionKind
    decided_at_ms: int
    fill_at_ms: int
    share_id: str
    trade_id: str
    leverage: int
    exit_reason: str | None
    sz_decimals: int
    max_leverage: int
    next_attempt_ms: int
    alert_due_ms: int
    alerted: bool = False
    decision_px: Decimal = ZERO

    @property
    def is_entry(self) -> bool:
        return self.action in ENTRY_ACTIONS


@dataclass(frozen=True)
class RegisteredStop:
    """A stop-loss or take-profit waiting for its trigger on the mark."""

    client_order_id: str
    coin: str
    kind: str
    side: str
    qty: Decimal
    trigger_px: Decimal
    trade_id: str
    share_id: str
    sz_decimals: int
    max_leverage: int

    def triggered_by(self, mark: Decimal) -> bool:
        """SL sells a long when the mark falls to the trigger (buys a short when it rises to it); TP is the
        reverse. Equality triggers."""
        closing_long = self.side == "sell"
        falls = closing_long == (self.kind == "sl")
        return mark <= self.trigger_px if falls else mark >= self.trigger_px


@dataclass(frozen=True)
class FundingDue:
    """Funding owed for one share at one UTC hour boundary, waiting for that hour's actual rate."""

    coin: str
    share_id: str
    hour_ms: int
    signed_qty: Decimal
