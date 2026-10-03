"""The paper broker's config keys, validated at construction (A2, A3: the broker never trusts a hand-built Config)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Context, Decimal
from typing import Any

from copytrade.core.ceilings import NUMERIC_KEYS, Bounds
from copytrade.core.config import PAPER_MODE
from copytrade.core.errors import ConfigError, ModeNotPermittedError

MS_PER_SECOND = 1000
MS_PER_MINUTE = 60 * MS_PER_SECOND
BPS_DIVISOR = 10_000
# Every money computation of the package runs at this precision: enough for any price x size x rate product and
# any VWAP quotient without silent rounding at the 28 digits of the default context.
MONEY_CONTEXT = Context(prec=60)
# Hyperliquid caps the hourly funding rate at 4%; a rate beyond it is bad data, not a rate (fail closed: retried).
MAX_FUNDING_RATE_PER_HOUR = Decimal("0.04")


@dataclass(frozen=True)
class PaperSettings:
    """Every value the broker reads from config, in the units its name states. ``max_time_skew_ms`` is the F1 key
    ``filter.max_signal_age_ms`` reused as the tolerance for an external timestamp ahead of the broker's time:
    above it a timestamp is alerted as clamped and an entry decision is refused ``bad_decision_time``."""

    wallet_usd: Decimal
    ack_delay_ms: int
    max_book_age_ms: int
    meta_refresh_ms: int
    taker_fee_bps: Decimal
    min_order_usd: Decimal
    retry_interval_ms: int
    alert_after_ms: int
    max_time_skew_ms: int

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> PaperSettings:
        """Read and validate the keys.

        Raises:
            ModeNotPermittedError: ``mode`` is anything but ``paper`` (A10, F1.AC3).
            ConfigError: a key is missing, has the wrong type (a float included) or is outside its ceiling.
        """
        if "mode" not in config:
            raise ConfigError("missing config key", key="mode")
        if config["mode"] != PAPER_MODE:
            raise ModeNotPermittedError
        return cls(
            wallet_usd=_decimal(config, "paper.wallet_usd"),
            ack_delay_ms=_whole(config, "paper.ack_delay_ms"),
            max_book_age_ms=_whole(config, "paper.max_book_age_ms"),
            meta_refresh_ms=_whole(config, "paper.meta_refresh_min") * MS_PER_MINUTE,
            taker_fee_bps=_decimal(config, "cost.taker_fee_bps"),
            min_order_usd=_decimal(config, "sizing.min_order_usd"),
            retry_interval_ms=_whole(config, "exits.retry_interval_s") * MS_PER_SECOND,
            alert_after_ms=_whole(config, "exits.alert_after_s") * MS_PER_SECOND,
            max_time_skew_ms=_whole(config, "filter.max_signal_age_ms"),
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
