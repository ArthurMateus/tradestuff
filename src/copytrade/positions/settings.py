"""The position manager's config keys, validated at construction (A2, A3: tunables are config, never code)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from copytrade.core.ceilings import NUMERIC_KEYS
from copytrade.core.config import PAPER_MODE
from copytrade.core.errors import ConfigError, ModeNotPermittedError

MS_PER_SECOND = 1_000
MS_PER_MINUTE = 60_000
MS_PER_HOUR = 3_600_000
_INTERVAL_MS = {"1m": MS_PER_MINUTE, "1h": MS_PER_HOUR}


@dataclass(frozen=True)
class PositionSettings:
    """Every value the manager reads from config, in the units its name states."""

    stop_atr_mult: Decimal
    atr_period: int
    atr_interval: str
    atr_interval_ms: int
    tp_enabled: bool
    tp1_r: Decimal
    tp1_fraction: Decimal
    trail_start_r: Decimal
    trail_atr_mult: Decimal
    missed_exit_max_lag_ms: int
    missed_exit_max_count: int
    min_order_usd: Decimal
    reconcile_interval_ms: int
    fill_audit_interval_ms: int
    audit_retry_interval_ms: int
    audit_retry_max_ms: int

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> PositionSettings:
        """Read and validate the keys.

        Raises:
            ModeNotPermittedError: ``mode`` is anything but ``paper``.
            ConfigError: a key is missing, has the wrong type (a float included) or is outside its compiled range.
        """
        if "mode" not in config:
            raise ConfigError("missing config key", key="mode")
        if config["mode"] != PAPER_MODE:
            raise ModeNotPermittedError
        interval = _text(config, "exits.atr_candle_interval")
        if interval not in _INTERVAL_MS:
            raise ConfigError("expected one of 1m, 1h", key="exits.atr_candle_interval")
        return cls(
            stop_atr_mult=_decimal(config, "exits.stop_atr_mult"),
            atr_period=_whole(config, "exits.atr_period"),
            atr_interval=interval,
            atr_interval_ms=_INTERVAL_MS[interval],
            tp_enabled=_flag(config, "exits.tp_enabled"),
            tp1_r=_decimal(config, "exits.tp1_r"),
            tp1_fraction=_decimal(config, "exits.tp1_fraction"),
            trail_start_r=_decimal(config, "exits.trail_start_r"),
            trail_atr_mult=_decimal(config, "exits.trail_atr_mult"),
            missed_exit_max_lag_ms=_whole(config, "exits.missed_exit_max_lag_s") * MS_PER_SECOND,
            missed_exit_max_count=_whole(config, "eval.missed_exit_max_count"),
            min_order_usd=_decimal(config, "sizing.min_order_usd"),
            reconcile_interval_ms=_whole(config, "reconcile.interval_s") * MS_PER_SECOND,
            fill_audit_interval_ms=_whole(config, "eval.fill_audit_interval_h") * MS_PER_HOUR,
            audit_retry_interval_ms=_whole(config, "storage.retry_interval_min") * MS_PER_MINUTE,
            audit_retry_max_ms=_whole(config, "eval.missing_data_retry_max_h") * MS_PER_HOUR,
        )


def _get(config: Mapping[str, Any], key: str) -> Any:
    if key not in config:
        raise ConfigError("missing config key", key=key)
    return config[key]


def _within(key: str, value: int | Decimal) -> None:
    bounds = NUMERIC_KEYS[key].bounds
    below = bounds.min is not None and (value <= bounds.min if bounds.min_exclusive else value < bounds.min)
    if below or (bounds.max is not None and value > bounds.max):
        raise ConfigError("config value is outside its allowed range", key=key)


def _whole(config: Mapping[str, Any], key: str) -> int:
    value = _get(config, key)
    if type(value) is not int:
        raise ConfigError("expected a whole number", key=key)
    _within(key, value)
    return value


def _decimal(config: Mapping[str, Any], key: str) -> Decimal:
    raw = _get(config, key)
    if type(raw) is int:
        value = Decimal(raw)
    elif type(raw) is Decimal and raw.is_finite():
        value = raw
    else:
        raise ConfigError("expected a finite number that is not a float", key=key)
    _within(key, value)
    return value


def _flag(config: Mapping[str, Any], key: str) -> bool:
    value = _get(config, key)
    if type(value) is not bool:
        raise ConfigError("expected true or false", key=key)
    return value


def _text(config: Mapping[str, Any], key: str) -> str:
    value = _get(config, key)
    if type(value) is not str:
        raise ConfigError("expected text", key=key)
    return value
