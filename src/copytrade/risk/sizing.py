"""Pure sizing maths (F10.AC2). Decimal only.

Every quotient that feeds a size is computed at 60 digits and rounded DOWN, so a size is never rounded up across a
lot boundary by the arithmetic, and products are taken before quotients so an exact result stays exact
(``100 / 3000 x 300`` is exactly 10, not 9.99...9).
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Context, Decimal

from copytrade.core.money import Price, Qty, round_size

_FLOOR = Context(prec=60, rounding=ROUND_DOWN)


def mirror_notional_usd(
    *, leader_position_notional_usd: Decimal, leader_account_value_usd: Decimal, equity_usd: Decimal
) -> Decimal:
    """``(leader post-fill position notional / leader account value) x equity``.

    Raises:
        ValueError: the leader account value is not positive.
    """
    if leader_account_value_usd <= 0:
        raise ValueError("the leader account value must be positive")
    scaled = _FLOOR.multiply(leader_position_notional_usd, equity_usd)
    return _FLOOR.divide(scaled, leader_account_value_usd)


def stop_distance_fraction(*, decision_px: Price, stop_px: Price) -> Decimal:
    """``|decision_px - stop_px| / decision_px``.

    Raises:
        ValueError: ``decision_px`` is not positive.
    """
    if decision_px <= 0:
        raise ValueError("the decision price must be positive")
    return _FLOOR.divide(abs(_FLOOR.subtract(decision_px, stop_px)), decision_px)


def risk_notional_usd(
    *, equity_usd: Decimal, per_trade_fraction: Decimal, vol_mult: Decimal, stop_distance_fraction: Decimal
) -> Decimal:
    """``equity x per_trade_fraction x vol_mult / stop_distance_fraction``.

    Raises:
        ValueError: ``stop_distance_fraction`` is not positive.
    """
    if stop_distance_fraction <= 0:
        raise ValueError("the stop distance must be positive")
    budget_usd = _FLOOR.multiply(_FLOOR.multiply(equity_usd, per_trade_fraction), vol_mult)
    return _FLOOR.divide(budget_usd, stop_distance_fraction)


def lot_qty_down(*, notional_usd: Decimal, px: Price, sz_decimals: int) -> Qty:
    """``notional_usd / px`` rounded DOWN to ``sz_decimals`` decimals.

    Raises:
        ValueError: ``px`` is not positive, ``notional_usd`` is negative or ``sz_decimals`` is outside 0..6.
    """
    if px <= 0:
        raise ValueError("the price must be positive")
    if notional_usd < 0:
        raise ValueError("the notional must not be negative")
    return round_size(_FLOOR.divide(notional_usd, px), sz_decimals)


def add_qty(*, our_share_qty: Qty, leader_add_size: Qty, leader_pre_add_position: Qty) -> Decimal:
    """``our_share_qty x (leader_add_size / leader_pre_add_position)`` (F10.AC9), rounded down.

    Raises:
        ValueError: the leader's pre-add position is not positive.
    """
    if leader_pre_add_position <= 0:
        raise ValueError("the leader's pre-add position must be positive")
    return _FLOOR.divide(_FLOOR.multiply(our_share_qty, leader_add_size), leader_pre_add_position)
