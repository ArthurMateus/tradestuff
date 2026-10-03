"""F1.AC1: config validation at startup. No code defaults; missing, mistyped or out-of-range keys stop
the engine with an error naming the key, and no network connection is opened.

Spec: docs/sdlc/copytrade-v1/04-spec.md F1.AC1, §3 (every key), §5 "Invalid config at start".
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.config import load_config
from copytrade.core.errors import ConfigError
from copytrade.core.startup import startup
from tests.core.helpers import REPO_ROOT, ConfigTree, fixture_leaves, make_root, run_cli

pytestmark = pytest.mark.unit

LEAVES = fixture_leaves()
LEAF_KEYS = sorted(LEAVES)


def _wrong_type_for(value: Any) -> Any:
    if isinstance(value, bool):
        return "yes"
    if isinstance(value, (int, Decimal)):
        return "not-a-number"
    if isinstance(value, str):
        return 12345
    if isinstance(value, list):
        return "not-a-list"
    raise AssertionError(f"fixture has an unexpected value type: {value!r}")


def assert_rejected(config_dir: Path, *keys: str) -> ConfigError:
    """load_config must raise ConfigError naming one of ``keys`` (the first is the key under test)."""
    with pytest.raises(ConfigError) as info:
        load_config(config_dir)
    err = info.value
    assert err.key in keys, f"error names {err.key!r}, expected one of {keys}"
    assert err.key in str(err), f"message does not name the key: {err}"
    return err


# --- the valid tree ------------------------------------------------------------------------------

def test_F1_AC1_valid_fixture_tree_loads_every_key_with_its_value(tmp_path: Path) -> None:
    config = load_config(ConfigTree().write(tmp_path / "config"))
    for key, value in LEAVES.items():
        assert key in config, key
        loaded = config[key]
        if isinstance(value, list):
            assert list(loaded) == value, key
        else:
            assert loaded == value, key


def test_F1_AC1_tables_split_across_files_merge(tmp_path: Path) -> None:
    # [storage] is split between platform.toml (ledger/recordings dirs, F1) and storage.toml (F23): §10 rule 5.
    config = load_config(ConfigTree().write(tmp_path / "config"))
    assert config["storage.ledger_dir"] == "../copytrade-data/ledger"
    assert config["storage.cache_dir"] == "../copytrade-data/cache"


def test_F1_AC1_no_loaded_value_is_a_binary_float(tmp_path: Path) -> None:
    config = load_config(ConfigTree().write(tmp_path / "config"))

    def floats(v: Any) -> bool:
        if isinstance(v, float):
            return True
        if isinstance(v, (list, tuple)):
            return any(floats(x) for x in v)
        return False

    offenders = [k for k in config if floats(config[k])]
    assert offenders == []
    assert isinstance(config["risk.per_trade_fraction"], Decimal)
    assert config["risk.per_trade_fraction"] == Decimal("0.005")


def test_F1_AC1_loaded_config_is_immutable(tmp_path: Path) -> None:
    config = load_config(ConfigTree().write(tmp_path / "config"))
    with pytest.raises(TypeError):
        config["risk.per_trade_fraction"] = Decimal("0.01")  # type: ignore[index]


# --- no code defaults: every key is required -----------------------------------------------------

@pytest.mark.parametrize("key", LEAF_KEYS)
def test_F1_AC1_missing_key_is_rejected_naming_it(tmp_path: Path, key: str) -> None:
    config_dir = ConfigTree().delete(key).write(tmp_path / "config")
    assert_rejected(config_dir, key)


def test_F1_AC1_empty_config_dir_is_rejected_naming_a_missing_key(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    with pytest.raises(ConfigError) as info:
        load_config(config_dir)
    assert info.value.key in LEAVES


def test_F1_AC1_missing_config_dir_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does-not-exist")


# --- wrong types ---------------------------------------------------------------------------------

@pytest.mark.parametrize("key", LEAF_KEYS)
def test_F1_AC1_wrong_type_is_rejected_naming_it(tmp_path: Path, key: str) -> None:
    tree = ConfigTree()
    tree.set(key, _wrong_type_for(tree.get(key)))
    assert_rejected(tree.write(tmp_path / "config"), key)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("risk.per_trade_fraction", "0.005"),  # a numeric-looking string is still a string
        ("risk.max_open_positions", "10"),
        ("risk.max_open_positions", True),  # bool is an int subclass in Python
        ("telegram.allowed_user_id", True),
        ("risk.max_open_positions", Decimal("1.5")),  # fraction for an integer key
        ("filter.max_signal_age_ms", Decimal("4999.5")),
        ("risk.high_leverage_coins", "BTC"),  # a string is iterable but is not a list
        ("risk.high_leverage_coins", [1, 2]),  # list elements of the wrong type
        ("decay.deltas_s", ["a", "b"]),
        ("shadow.enabled", 1),
        ("mode", 0),
    ],
    ids=lambda v: repr(v),
)
def test_F1_AC1_nasty_wrong_types_are_rejected(tmp_path: Path, key: str, value: Any) -> None:
    tree = ConfigTree().set(key, value)
    assert_rejected(tree.write(tmp_path / "config"), key)


@pytest.mark.parametrize("key", ["risk.per_trade_fraction", "cost.taker_fee_bps", "paper.wallet_usd", "storage.monthly_budget_usd"])
@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")], ids=str)
def test_F1_AC1_nan_and_infinity_are_rejected(tmp_path: Path, key: str, bad: Decimal) -> None:
    tree = ConfigTree().set(key, bad)
    assert_rejected(tree.write(tmp_path / "config"), key)


def test_F1_AC1_integer_literal_for_a_decimal_key_loads_as_decimal(tmp_path: Path) -> None:
    tree = ConfigTree().set("risk.min_liq_distance_stop_mult", 3)
    config = load_config(tree.write(tmp_path / "config"))
    value = config["risk.min_liq_distance_stop_mult"]
    assert isinstance(value, Decimal) and value == Decimal(3)


@pytest.mark.parametrize("key", ["storage.ledger_dir", "storage.recordings_dir", "storage.cache_dir", "calendar.file"])
def test_F1_AC1_empty_required_path_is_rejected(tmp_path: Path, key: str) -> None:
    tree = ConfigTree().set(key, "")
    assert_rejected(tree.write(tmp_path / "config"), key)


@pytest.mark.parametrize(
    ("key", "value", "ok"),
    [
        ("storage.ledger_backup_time_utc", "23:59", True),
        ("storage.ledger_backup_time_utc", "00:00", True),
        ("storage.ledger_backup_time_utc", "24:00", False),
        ("storage.ledger_backup_time_utc", "12:60", False),
        ("storage.ledger_backup_time_utc", "noon", False),
        ("report.daily_time_utc", "25:05", False),
        ("report.weekly_time_utc", "Sun 23:59", True),
        ("report.weekly_time_utc", "Funday 00:10", False),
        ("report.weekly_time_utc", "Mon 24:10", False),
    ],
)
def test_F1_AC1_time_of_day_keys_validate_format(tmp_path: Path, key: str, value: str, ok: bool) -> None:
    config_dir = ConfigTree().set(key, value).write(tmp_path / "config")
    if ok:
        assert load_config(config_dir)[key] == value
    else:
        assert_rejected(config_dir, key)


@pytest.mark.parametrize("key", ["filter.trend.mode", "filter.funding.mode", "filter.oi_drop.mode", "filter.premium.mode"])
def test_F1_AC1_unknown_enum_value_is_rejected(tmp_path: Path, key: str) -> None:
    assert_rejected(ConfigTree().set(key, "bogus").write(tmp_path / "config"), key)


def test_F1_AC1_negative_telegram_group_chat_id_loads(tmp_path: Path) -> None:
    # Telegram group and channel IDs are negative 64-bit integers; they must not trip a range check.
    tree = ConfigTree().set("telegram.alerts_chat_id", -1009876543210).set("telegram.control_chat_id", -1001234567890)
    config = load_config(tree.write(tmp_path / "config"))
    assert config["telegram.alerts_chat_id"] == -1009876543210


def test_F1_AC1_unicode_text_value_round_trips(tmp_path: Path) -> None:
    text = "Negociação simulada (paper). Não é recomendação de investimento. ✓"
    config = load_config(ConfigTree().set("report.disclaimer", text).write(tmp_path / "config"))
    assert config["report.disclaimer"] == text


# --- structural faults ----------------------------------------------------------------------------

def test_F1_AC1_malformed_toml_is_rejected_naming_the_file(tmp_path: Path) -> None:
    config_dir = ConfigTree().write(tmp_path / "config")
    (config_dir / "risk.toml").write_text("[risk\nper_trade_fraction = 0.005\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_config(config_dir)
    assert "risk.toml" in str(info.value)


def test_F1_AC1_same_key_in_two_files_is_rejected_naming_the_key(tmp_path: Path) -> None:
    tree = ConfigTree().set("risk.per_trade_fraction", Decimal("0.005"), file="duplicate.toml")
    assert_rejected(tree.write(tmp_path / "config"), "risk.per_trade_fraction")


# --- at engine start: non-zero exit, key named, no network ------------------------------------

def test_F1_AC1_startup_with_invalid_config_names_the_key_and_opens_no_connection(
    tmp_path: Path, network_guard: Any, canary_secrets: dict[str, str]
) -> None:
    tree = ConfigTree().delete("risk.max_open_positions")
    fake = make_root(tmp_path, tree)
    connects_before = len(network_guard.all_connects)
    with pytest.raises(ConfigError) as info:
        startup(fake.root, canary_secrets, code_root=REPO_ROOT, engine_module_files=[])
    assert info.value.key == "risk.max_open_positions"
    assert network_guard.all_connects[connects_before:] == []


@pytest.mark.integration
@pytest.mark.parametrize(
    ("mutate", "key"),
    [
        (lambda t: t.delete("clock.max_estimate_age_s"), "clock.max_estimate_age_s"),
        (lambda t: t.set("hl.rest_timeout_s", "ten"), "hl.rest_timeout_s"),
        (lambda t: t.set("risk.per_trade_fraction", Decimal("0.0101")), "risk.per_trade_fraction"),
    ],
    ids=["missing", "wrong-type", "out-of-range"],
)
def test_F1_AC1_cli_start_exits_nonzero_naming_the_key_without_network(
    tmp_path: Path, network_guard: Any, mutate: Any, key: str
) -> None:
    tree = ConfigTree()
    mutate(tree)
    fake = make_root(tmp_path, tree)
    connects_before = len(network_guard.all_connects)
    result = run_cli(["start", "--root", str(fake.root)])
    assert result.code != 0
    assert key in result.stderr
    assert network_guard.all_connects[connects_before:] == []
