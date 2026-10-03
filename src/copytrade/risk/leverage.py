"""Automatic isolated leverage and the liquidation-distance rule (F10.AC4, AC10). Pure: no I/O."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal

from copytrade.core.money import Price, Qty
from copytrade.paper.liquidation import liquidation_price
from copytrade.paper.settings import MONEY_CONTEXT

_SIDES = ("long", "short")
INSUFFICIENT_MARGIN = "insufficient_margin"
LIQ_TOO_CLOSE = "liq_too_close"


@dataclass(frozen=True)
class LeveragePlan:
    """The automatic choice. ``reason`` is ``None`` when ``accepted``, else ``insufficient_margin`` or
    ``liq_too_close``. ``leverage`` is the lowest integer that fits the margin (``None`` when none does);
    ``liquidation_px`` is the F11.AC5 liquidation price of the merged position at that leverage (``None`` when
    ``leverage`` is ``None``); ``required_margin_usd`` is post-order notional / leverage (same rule)."""

    accepted: bool
    reason: str | None
    leverage: int | None
    ceiling: int
    required_margin_usd: Decimal | None
    posted_margin_usd: Decimal
    liquidation_px: Price | None


def leverage_ceiling(
    *,
    coin: str,
    high_leverage_coins: Collection[str],
    max_leverage_high_tier: int,
    max_leverage_alt: int,
    exchange_max_leverage: int,
) -> int:
    """``min(high tier if coin in high_leverage_coins else alt, exchange max leverage)``."""
    tier = max_leverage_high_tier if coin in high_leverage_coins else max_leverage_alt
    return min(tier, exchange_max_leverage)


def merged_average_entry(
    *, existing_qty: Qty, existing_avg_entry_px: Price | None, order_qty: Qty, decision_px: Price
) -> Price:
    """Quantity-weighted average entry of the existing position and an order filled at ``decision_px``.

    Raises:
        ValueError: there is an existing quantity but no average entry.
    """
    if existing_qty == 0:
        return decision_px
    if existing_avg_entry_px is None:
        raise ValueError("an existing position needs its average entry price")
    ctx = MONEY_CONTEXT
    cost = ctx.add(ctx.multiply(existing_qty, existing_avg_entry_px), ctx.multiply(order_qty, decision_px))
    return Price(ctx.divide(cost, ctx.add(existing_qty, order_qty)))


def plan_leverage(  # noqa: PLR0913
    *,
    side: str,
    coin_ceiling: int,
    leverage_min: int,
    exchange_max_leverage: int,
    sz_decimals: int,
    decision_px: Price,
    order_qty: Qty,
    existing_qty: Qty,
    existing_avg_entry_px: Price | None,
    posted_margin_usd: Decimal,
    free_equity_usd: Decimal,
    share_stop_pxs: Sequence[Price],
    min_liq_distance_stop_mult: Decimal,
) -> LeveragePlan:
    """Choose L, the lowest integer in ``[leverage_min, coin_ceiling]`` with
    ``(existing_qty + order_qty) x decision_px / L <= posted_margin_usd + free_equity_usd`` (``side`` is ``"long"`` or
    ``"short"``; quantities are absolute). Then require, for EVERY stop in ``share_stop_pxs`` (one per share of the
    resulting merged position, the new or added share included), ``|decision_px - liq| >= mult x |decision_px -
    stop|`` where ``liq`` is ``paper.liquidation.liquidation_price`` of the merged position (quantity-weighted
    average entry of the existing position and the order at ``decision_px``) at L. No higher L is tried.

    The margin test multiplies instead of dividing (``notional <= L x available``), so it is exact. An empty range
    (``leverage_min`` above ``coin_ceiling``) fits nothing and is ``insufficient_margin``.

    Raises:
        ValueError: ``side`` is not ``long``/``short``, a quantity or the price is not positive, there is an existing
            quantity without its average entry, or the liquidation price is not representable (``round_price``).
    """
    if side not in _SIDES:
        raise ValueError("side must be 'long' or 'short'")
    if order_qty <= 0 or existing_qty < 0 or decision_px <= 0:
        raise ValueError("the order quantity and the price must be positive and the existing quantity not negative")
    ctx = MONEY_CONTEXT
    notional = ctx.multiply(ctx.add(existing_qty, order_qty), decision_px)
    available = ctx.add(posted_margin_usd, free_equity_usd)
    leverage = next(
        (level for level in range(leverage_min, coin_ceiling + 1) if notional <= ctx.multiply(level, available)),
        None,
    )
    if leverage is None:
        return LeveragePlan(False, INSUFFICIENT_MARGIN, None, coin_ceiling, None, posted_margin_usd, None)
    avg_entry = merged_average_entry(
        existing_qty=existing_qty,
        existing_avg_entry_px=existing_avg_entry_px,
        order_qty=order_qty,
        decision_px=decision_px,
    )
    liquidation_px = liquidation_price(
        side=side,
        avg_entry_px=avg_entry,
        leverage=leverage,
        max_leverage=exchange_max_leverage,
        sz_decimals=sz_decimals,
    )
    liquidation_distance = abs(ctx.subtract(decision_px, liquidation_px))
    safe = all(
        liquidation_distance >= ctx.multiply(min_liq_distance_stop_mult, abs(ctx.subtract(decision_px, stop)))
        for stop in share_stop_pxs
    )
    return LeveragePlan(
        accepted=safe,
        reason=None if safe else LIQ_TOO_CLOSE,
        leverage=leverage,
        ceiling=coin_ceiling,
        required_margin_usd=ctx.divide(notional, leverage),
        posted_margin_usd=posted_margin_usd,
        liquidation_px=liquidation_px,
    )
