"""F1.AC1 and F1.AC2 support: the compiled schema and the fixture tree describe the same §3 keys.

Added by the developer, not the test designer: these guard the loader's own tables against drift.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.ceilings import FIXED_VALUES, NUMERIC_KEYS, NumberKind, ceiling_for
from copytrade.core.config import load_config, schema_keys
from tests.core.helpers import ConfigTree, fixture_leaves

pytestmark = pytest.mark.unit

LEAVES = fixture_leaves()


def test_F1_AC1_schema_keys_are_exactly_the_keys_of_the_valid_fixture_tree() -> None:
    assert schema_keys() == set(LEAVES)


def test_F1_AC2_numeric_and_fixed_keys_do_not_overlap() -> None:
    assert not set(NUMERIC_KEYS) & set(FIXED_VALUES)


def test_F1_AC2_every_numeric_bound_has_the_type_of_its_kind_and_min_never_exceeds_max() -> None:
    for key, spec in NUMERIC_KEYS.items():
        bounds = ceiling_for(key)
        for bound in (bounds.min, bounds.max):
            if bound is not None:
                assert isinstance(bound, int if spec.kind is NumberKind.INT else Decimal), key
        if bounds.min is not None and bounds.max is not None:
            assert bounds.min <= bounds.max, key


def test_F1_AC2_the_fixture_value_of_every_numeric_key_has_its_kind_and_sits_within_its_bounds() -> None:
    for key, spec in NUMERIC_KEYS.items():
        value = LEAVES[key]
        if key in ("filter.trend.min_aligned_atr", "filter.funding.max_adverse_rate_per_h") or value == "unset":
            continue
        assert isinstance(value, int if spec.kind is NumberKind.INT else (int, Decimal)), key
        bounds = ceiling_for(key)
        if bounds.min is not None:
            assert value > bounds.min if bounds.min_exclusive else value >= bounds.min, key
        if bounds.max is not None:
            assert value <= bounds.max, key


def test_F1_AC5_only_five_schema_keys_match_the_secret_pattern_and_none_can_hold_text() -> None:
    pattern = re.compile(r"(?i)(token|secret|api_key|pin)")
    matching = {key for key in schema_keys() if pattern.search(key)}
    assert matching == {
        "telegram.pin_max_attempts",
        "telegram.pin_lockout_min",
        "hl.ws_ping_interval_s",
        "llm.price_usd_per_1k_tokens.input",
        "llm.price_usd_per_1k_tokens.output",
        "eval.run_worktree_pinned",
    }
    assert all(key in NUMERIC_KEYS or key in FIXED_VALUES for key in matching)


@pytest.mark.parametrize(
    "key",
    ["risk.per_trade_fraction_max", "okx.enabled", "risk.max.per_trade_fraction", "mode.extra"],
)
def test_F1_AC1_unknown_key_is_rejected_naming_it(tmp_path: Path, key: str) -> None:
    config_dir = ConfigTree().set(key, 1, file="extra.toml").write(tmp_path / "config")
    with pytest.raises(Exception) as info:
        load_config(config_dir)
    assert getattr(info.value, "key", None) == key


@pytest.mark.parametrize("mode", ["enforce"])
@pytest.mark.parametrize(
    ("mode_key", "threshold_key", "valid"),
    [
        ("filter.trend.mode", "filter.trend.min_aligned_atr", "1"),
        ("filter.funding.mode", "filter.funding.max_adverse_rate_per_h", "0.01"),
        ("filter.oi_drop.mode", "filter.oi_drop.max_drop_pct_24h", "10"),
        ("filter.premium.mode", "filter.premium.max_abs_pct", "1"),
    ],
)
def test_F1_AC1_enforce_needs_a_threshold_and_record_only_accepts_one(
    tmp_path: Path, mode: str, mode_key: str, threshold_key: str, valid: str
) -> None:
    from copytrade.core.errors import ConfigError

    tree = ConfigTree().set(mode_key, mode)
    with pytest.raises(ConfigError) as info:
        load_config(tree.write(tmp_path / "enforce_unset"))
    assert info.value.key == threshold_key

    threshold: Any = Decimal(valid)
    tree.set(threshold_key, threshold)
    assert load_config(tree.write(tmp_path / "enforce_set"))[threshold_key] == threshold
    assert load_config(ConfigTree().set(threshold_key, threshold).write(tmp_path / "record_only_set"))[mode_key] == "record_only"


def test_F1_AC1_error_messages_never_echo_a_text_value(tmp_path: Path) -> None:
    from copytrade.core.errors import ConfigError

    leaked = "hunter2-not-a-real-value"
    for key in ("filter.trend.mode", "llm.fallback", "storage.ledger_backup_time_utc", "cost.funding_accrual"):
        with pytest.raises(ConfigError) as info:
            load_config(ConfigTree().set(key, leaked).write(tmp_path / key))
        assert leaked not in str(info.value)
