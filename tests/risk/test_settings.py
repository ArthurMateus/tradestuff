"""F10 config keys (A2, A3: hard limits are config, fail closed on bad config; F1.AC4: no floats)."""

from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.config import Config
from copytrade.core.errors import ConfigError, ModeNotPermittedError
from copytrade.risk.settings import RiskSettings
from tests.paper.helpers import make_config
from tests.risk.helpers import build_risk_env

KEYS = (
    "risk.per_trade_fraction", "risk.max_share_risk_fraction", "risk.max_total_open_risk_fraction",
    "risk.max_symbol_open_risk_fraction", "risk.max_btc_bucket_open_risk_fraction", "risk.btc_bucket_corr_threshold",
    "risk.btc_bucket_corr_window_days", "risk.max_leader_open_risk_fraction", "risk.max_open_positions",
    "risk.max_position_notional_equity_mult", "risk.leverage_min", "risk.max_leverage_alt",
    "risk.max_leverage_high_tier", "risk.high_leverage_coins", "risk.min_liq_distance_stop_mult",
    "risk.daily_loss_limit", "risk.weekly_loss_limit", "risk.max_orders_per_min", "sizing.min_order_usd",
    "eval.max_dd", "eval.mark_interval_s", "follow.max_leader_av_age_s",
)


@pytest.mark.unit
def test_F10_AC3_the_fixture_config_loads_with_the_spec_values() -> None:
    s = RiskSettings.from_config(make_config())
    assert s.per_trade_fraction == D("0.005")
    assert s.max_share_risk_fraction == D("0.01")
    assert s.max_total_open_risk_fraction == D("0.05")
    assert s.max_symbol_open_risk_fraction == D("0.015")
    assert s.max_btc_bucket_open_risk_fraction == D("0.03")
    assert s.btc_bucket_corr_threshold == D("0.6")
    assert s.btc_bucket_corr_window_days == 30
    assert s.max_leader_open_risk_fraction == D("0.015")
    assert s.max_open_positions == 10
    assert s.max_position_notional_equity_mult == D("1.0")
    assert (s.leverage_min, s.max_leverage_alt, s.max_leverage_high_tier) == (1, 5, 10)
    assert s.high_leverage_coins == frozenset({"BTC", "ETH", "SOL"})
    assert s.min_liq_distance_stop_mult == D(3)
    assert (s.daily_loss_limit, s.weekly_loss_limit, s.max_orders_per_min) == (D("0.02"), D("0.05"), 30)
    assert s.min_order_usd == D(10)
    assert (s.max_drawdown, s.mark_interval_s, s.max_leader_av_age_s) == (D("0.15"), 60, 300)


@pytest.mark.unit
@pytest.mark.parametrize("key", KEYS)
def test_F10_AC7_a_missing_key_fails_closed_naming_the_key(key: str) -> None:
    data = dict(make_config())
    del data[key]
    with pytest.raises(ConfigError) as err:
        RiskSettings.from_config(Config(data))
    assert err.value.key == key


@pytest.mark.unit
@pytest.mark.parametrize(
    "key,bad",
    [
        ("risk.per_trade_fraction", D("0.011")),
        ("risk.per_trade_fraction", D("0.0009")),
        ("risk.max_leverage_alt", 6),
        ("risk.max_leverage_high_tier", 11),
        ("risk.leverage_min", 4),
        ("risk.max_open_positions", 11),
        ("risk.max_orders_per_min", 61),
        ("risk.min_liq_distance_stop_mult", D("2.9")),
        ("sizing.min_order_usd", D("9.99")),
        ("risk.daily_loss_limit", D("0.051")),
        ("risk.max_position_notional_equity_mult", D("3.1")),
    ],
)
def test_F10_AC7_a_value_beyond_its_compiled_ceiling_is_refused(key: str, bad: Any) -> None:
    with pytest.raises(ConfigError) as err:
        RiskSettings.from_config(make_config(**{key.replace(".", "__"): bad}))
    assert err.value.key == key


@pytest.mark.unit
@pytest.mark.parametrize(
    "key,good",
    [
        ("risk.per_trade_fraction", D("0.01")),
        ("risk.max_leverage_alt", 5),
        ("risk.max_leverage_high_tier", 10),
        ("risk.max_orders_per_min", 60),
        ("risk.min_liq_distance_stop_mult", D(3)),
    ],
)
def test_F10_AC3_the_ceiling_itself_loads(key: str, good: Any) -> None:
    RiskSettings.from_config(make_config(**{key.replace(".", "__"): good}))


@pytest.mark.unit
@pytest.mark.parametrize("coins", [("BTC", "DOGE"), ("XRP",), ("BTC", "ETH", "SOL", "HYPE")])
def test_F10_AC10_high_leverage_coins_must_be_a_subset_of_btc_eth_sol(coins: tuple[str, ...]) -> None:
    with pytest.raises(ConfigError) as err:
        RiskSettings.from_config(make_config(risk__high_leverage_coins=coins))
    assert err.value.key == "risk.high_leverage_coins"


@pytest.mark.unit
def test_F10_AC10_a_subset_of_the_high_leverage_list_is_accepted() -> None:
    s = RiskSettings.from_config(make_config(risk__high_leverage_coins=("BTC",)))
    assert s.high_leverage_coins == frozenset({"BTC"})


@pytest.mark.unit
def test_F1_AC4_a_float_config_value_is_refused() -> None:
    with pytest.raises((TypeError, ConfigError)):
        RiskSettings.from_config(make_config(risk__per_trade_fraction=0.005))


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["live", "testnet", "", "Paper"])
def test_F1_AC3_any_mode_but_paper_is_refused(mode: str) -> None:
    with pytest.raises(ModeNotPermittedError):
        RiskSettings.from_config(make_config(mode=mode))


@pytest.mark.unit
def test_F10_AC7_a_gate_cannot_be_built_from_a_config_that_failed_validation(tmp_path: Path) -> None:
    bad = dict(make_config())
    bad["risk.max_leverage_alt"] = 6
    with pytest.raises(ConfigError):
        build_risk_env(tmp_path, config=Config(bad))
