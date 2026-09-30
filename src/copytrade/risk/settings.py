"""The risk gate's config keys, validated at construction (A2, A3: hard limits are config, never code)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from copytrade.core.ceilings import HIGH_LEVERAGE_COIN_UNIVERSE, NUMERIC_KEYS, Bounds
from copytrade.core.config import PAPER_MODE
from copytrade.core.errors import ConfigError, ModeNotPermittedError

_HIGH_LEVERAGE_COINS_KEY = "risk.high_leverage_coins"


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
        if "mode" not in config:
            raise ConfigError("missing config key", key="mode")
        if config["mode"] != PAPER_MODE:
            raise ModeNotPermittedError
        return cls(
            per_trade_fraction=_decimal(config, "risk.per_trade_fraction"),
            max_share_risk_fraction=_decimal(config, "risk.max_share_risk_fraction"),
            max_total_open_risk_fraction=_decimal(config, "risk.max_total_open_risk_fraction"),
            max_symbol_open_risk_fraction=_decimal(config, "risk.max_symbol_open_risk_fraction"),
            max_btc_bucket_open_risk_fraction=_decimal(config, "risk.max_btc_bucket_open_risk_fraction"),
            btc_bucket_corr_threshold=_decimal(config, "risk.btc_bucket_corr_threshold"),
            btc_bucket_corr_window_days=_whole(config, "risk.btc_bucket_corr_window_days"),
            max_leader_open_risk_fraction=_decimal(config, "risk.max_leader_open_risk_fraction"),
            max_open_positions=_whole(config, "risk.max_open_positions"),
            max_position_notional_equity_mult=_decimal(config, "risk.max_position_notional_equity_mult"),
            leverage_min=_whole(config, "risk.leverage_min"),
            max_leverage_alt=_whole(config, "risk.max_leverage_alt"),
            max_leverage_high_tier=_whole(config, "risk.max_leverage_high_tier"),
            high_leverage_coins=_coins(config),
            min_liq_distance_stop_mult=_decimal(config, "risk.min_liq_distance_stop_mult"),
            daily_loss_limit=_decimal(config, "risk.daily_loss_limit"),
            weekly_loss_limit=_decimal(config, "risk.weekly_loss_limit"),
            max_orders_per_min=_whole(config, "risk.max_orders_per_min"),
            min_order_usd=_decimal(config, "sizing.min_order_usd"),
            max_drawdown=_decimal(config, "eval.max_dd"),
            mark_interval_s=_whole(config, "eval.mark_interval_s"),
            max_leader_av_age_s=_whole(config, "follow.max_leader_av_age_s"),
        )


def _within(key: str, value: int | Decimal, bounds: Bounds) -> None:
    below = bounds.min is not None and (value <= bounds.min if bounds.min_exclusive else value < bounds.min)
    if below or (bounds.max is not None and value > bounds.max):
        raise ConfigError("config value is outside its allowed range", key=key)


def _whole(config: Mapping[str, Any], key: str) -> int:
    if key not in config:
        raise ConfigError("missing config key", key=key)
    value = config[key]
    if type(value) is not int:
        raise ConfigError("expected a whole number", key=key)
    _within(key, value, NUMERIC_KEYS[key].bounds)
    return value


def _decimal(config: Mapping[str, Any], key: str) -> Decimal:
    if key not in config:
        raise ConfigError("missing config key", key=key)
    raw = config[key]
    if type(raw) is int:
        value = Decimal(raw)
    elif type(raw) is Decimal and raw.is_finite():
        value = raw
    else:
        raise ConfigError("expected a finite number that is not a float", key=key)
    _within(key, value, NUMERIC_KEYS[key].bounds)
    return value


def _coins(config: Mapping[str, Any]) -> frozenset[str]:
    if _HIGH_LEVERAGE_COINS_KEY not in config:
        raise ConfigError("missing config key", key=_HIGH_LEVERAGE_COINS_KEY)
    raw = config[_HIGH_LEVERAGE_COINS_KEY]
    if not isinstance(raw, (tuple, list)) or not all(type(coin) is str for coin in raw):
        raise ConfigError("expected a list of coin names", key=_HIGH_LEVERAGE_COINS_KEY)
    coins = frozenset(raw)
    if not coins <= HIGH_LEVERAGE_COIN_UNIVERSE:
        raise ConfigError("coins outside the compiled high-leverage universe", key=_HIGH_LEVERAGE_COINS_KEY)
    return coins
