"""Automatic isolated leverage and the liquidation-distance rule (F10.AC4, AC10). Pure: no I/O."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal

from copytrade.core.money import Price, Qty


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
    raise NotImplementedError


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
    """
    raise NotImplementedError
