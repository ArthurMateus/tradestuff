"""Pure sizing maths (F10.AC2). Decimal only."""

from __future__ import annotations

from decimal import Decimal

from copytrade.core.money import Price, Qty


def mirror_notional_usd(
    *, leader_position_notional_usd: Decimal, leader_account_value_usd: Decimal, equity_usd: Decimal
) -> Decimal:
    """``(leader post-fill position notional / leader account value) x equity``."""
    raise NotImplementedError


def stop_distance_fraction(*, decision_px: Price, stop_px: Price) -> Decimal:
    """``|decision_px - stop_px| / decision_px``."""
    raise NotImplementedError


def risk_notional_usd(
    *, equity_usd: Decimal, per_trade_fraction: Decimal, vol_mult: Decimal, stop_distance_fraction: Decimal
) -> Decimal:
    """``equity x per_trade_fraction x vol_mult / stop_distance_fraction``.

    Raises:
        ValueError: ``stop_distance_fraction`` is not positive.
    """
    raise NotImplementedError


def lot_qty_down(*, notional_usd: Decimal, px: Price, sz_decimals: int) -> Qty:
    """``notional_usd / px`` rounded DOWN to ``sz_decimals`` decimals."""
    raise NotImplementedError
