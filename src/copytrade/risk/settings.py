"""The risk gate's config keys, validated at construction (A2, A3: hard limits are config, never code)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RiskSettings:
    """Every value the gate reads from config, in the units its name states."""

    per_trade_fraction: Decimal
    max_share_risk_fraction: Decimal
    max_total_open_risk_fraction: Decimal
    max_symbol_open_risk_fraction: Decimal
    max_btc_bucket_open_risk_fraction: Decimal
    btc_bucket_corr_threshold: Decimal
    btc_bucket_corr_window_days: int
    max_leader_open_risk_fraction: Decimal
    max_open_positions: int
    max_position_notional_equity_mult: Decimal
    leverage_min: int
    max_leverage_alt: int
    max_leverage_high_tier: int
    high_leverage_coins: frozenset[str]
    min_liq_distance_stop_mult: Decimal
    daily_loss_limit: Decimal
    weekly_loss_limit: Decimal
    max_orders_per_min: int
    min_order_usd: Decimal
    max_drawdown: Decimal
    mark_interval_s: int
    max_leader_av_age_s: int

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> RiskSettings:
        """Read and validate the keys.

        Raises:
            ModeNotPermittedError: ``mode`` is anything but ``paper``.
            ConfigError: a key is missing, has the wrong type (a float included), is outside its compiled range,
                or ``risk.high_leverage_coins`` is not a subset of {BTC, ETH, SOL}.
        """
        raise NotImplementedError
