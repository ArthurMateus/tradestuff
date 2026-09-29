"""Config loader (F1.AC1, F1.AC2, F1.AC5).

Contract:
- The config tree is every ``*.toml`` file directly under ``config_dir``, one file per area
  (§10 collision rule 1). Tables with the same name in different files merge; the same leaf key in
  two files is a ``ConfigError`` naming that key.
- TOML floats are parsed as ``Decimal``, so no loaded value is ever a binary ``float``. Lists load as tuples.
- Every §3 key must be present (no code defaults). A missing key, an unknown key, a wrong type or a value
  outside the compiled [Min, Max] (``copytrade.core.ceilings``) raises ``ConfigError`` naming the key.
  Whole-number keys refuse fractions (and ``2.0``); Decimal keys accept integer literals.
- A key whose name matches ``(?i)(token|secret|api_key|pin)`` with a non-empty value fails to load,
  unless it is a §3 key whose value cannot carry a secret: a number (``telegram.pin_*``,
  ``hl.ws_ping_interval_s``, ``llm.price_usd_per_1k_tokens.*``, Amendment 5) or a build-fixed constant
  (``eval.run_worktree_pinned``). The error never echoes the value; no error echoes a text value.
- ``mode`` other than ``"paper"`` raises ``ModeNotPermittedError`` ("mode not permitted in this build").
- Keys are addressed by their dotted path, e.g. ``config["risk.per_trade_fraction"]``.
- The four record-only filter thresholds are the string ``"unset"`` until calibrated; ``"unset"`` is
  refused while the rule's mode is ``enforce``.
- Keys are validated in a fixed order (the order of ``_RULES``), then the cross-key rules, and the first
  fault is reported.
"""

from __future__ import annotations

import operator
import re
import tomllib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from copytrade.core.ceilings import (
    FIXED_VALUES,
    HIGH_LEVERAGE_COIN_UNIVERSE,
    NUMERIC_KEYS,
    SCORE_COMPONENTS,
    Bounds,
    NumberKind,
)
from copytrade.core.errors import ConfigError, ModeNotPermittedError
from copytrade.core.manifest import PathGuard

PAPER_MODE = "paper"
UNSET = "unset"
RECORD_ONLY = "record_only"
ENFORCE = "enforce"

_SECRET_KEY_PATTERN = re.compile(r"(?i)(token|secret|api_key|pin)")
_HHMM = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
_TIME_OF_DAY = re.compile(_HHMM)
_WEEKLY_TIME = re.compile(rf"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) {_HHMM}")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
_TOML_POSITION = re.compile(r"\(at line (\d+), column (\d+)\)")
_SECRET_PATTERN_EXEMPT = frozenset(NUMERIC_KEYS) | frozenset(FIXED_VALUES)


class Config(Mapping[str, Any]):
    """Immutable, validated config. Maps dotted §3 keys to values (int, Decimal, str, bool, tuple).

    Build one with ``load_config``; the constructor trusts its argument.
    """

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any]) -> None:
        self._data: Mapping[str, Any] = MappingProxyType(dict(data))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"Config(<{len(self._data)} keys>)"


class _RejectError(Exception):
    """A value failed its rule. ``reason`` is safe to show: it never contains the offending value."""


Rule = Callable[[Any], Any]


# --- rules --------------------------------------------------------------------------------------------


def _show(number: int | Decimal) -> str:
    return str(number) if isinstance(number, int) else format(number, "f")


def _within(value: int | Decimal, bounds: Bounds) -> None:
    if bounds.min is not None:
        if bounds.min_exclusive and value <= bounds.min:
            raise _RejectError(f"{_show(value)} is not above {_show(bounds.min)}")
        if not bounds.min_exclusive and value < bounds.min:
            raise _RejectError(f"{_show(value)} is below the minimum {_show(bounds.min)}")
    if bounds.max is not None and value > bounds.max:
        raise _RejectError(f"{_show(value)} is above the maximum {_show(bounds.max)}")


def _to_decimal(value: Any) -> Decimal:
    """An int or Decimal (never a bool, str or float) as a finite Decimal."""
    if type(value) is int:
        return Decimal(value)
    if type(value) is Decimal and value.is_finite():
        return value
    raise _RejectError("expected a finite number")


def _int_rule(bounds: Bounds) -> Rule:
    def check(value: Any) -> int:
        if type(value) is not int:
            raise _RejectError("expected a whole number")
        _within(value, bounds)
        return value

    return check


def _decimal_rule(bounds: Bounds, *, allow_unset: bool) -> Rule:
    def check(value: Any) -> Decimal | str:
        if allow_unset and isinstance(value, str) and value == UNSET:
            return UNSET
        number = _to_decimal(value)
        _within(number, bounds)
        return number

    return check


def _bool_rule(value: Any) -> bool:
    if type(value) is not bool:
        raise _RejectError("expected true or false")
    return value


def _text_rule(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _RejectError("expected non-empty text")
    return value


def _path_rule(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise _RejectError("expected a non-empty path")
    return value


def _pattern_rule(pattern: re.Pattern[str], expected: str) -> Rule:
    def check(value: Any) -> str:
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise _RejectError(f"expected {expected}")
        return value

    return check


def _enum_rule(choices: tuple[str, ...]) -> Rule:
    def check(value: Any) -> str:
        if not isinstance(value, str) or value not in choices:
            raise _RejectError(f"expected one of {', '.join(choices)}")
        return value

    return check


def _fixed_rule(expected: str | bool | tuple[str, ...]) -> Rule:
    def check(value: Any) -> str | bool | tuple[str, ...]:
        if isinstance(expected, tuple):
            if not isinstance(value, list | tuple):
                raise _RejectError("expected a list")
            if tuple(value) != expected:
                raise _RejectError(f"fixed by the build: expected exactly {list(expected)}")
            return expected
        if type(value) is not type(expected):
            raise _RejectError("wrong type")
        if value != expected:
            raise _RejectError(f"fixed by the build: expected exactly {expected!r}")
        return value

    return check


def _string_list_rule(
    *,
    allow_empty: bool,
    item: Callable[[str], bool] = lambda text: bool(text.strip()),
    expected: str = "non-empty text",
) -> Rule:
    def check(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list | tuple):
            raise _RejectError("expected a list")
        if not value and not allow_empty:
            raise _RejectError("expected a non-empty list")
        if not all(isinstance(entry, str) and item(entry) for entry in value):
            raise _RejectError(f"every entry must be {expected}")
        if len(set(value)) != len(value):
            raise _RejectError("entries must not repeat")
        return tuple(value)

    return check


def _number_list_rule(value: Any) -> tuple[Decimal, ...]:
    if not isinstance(value, list | tuple) or not value:
        raise _RejectError("expected a non-empty list of numbers")
    return tuple(_to_decimal(entry) for entry in value)


# Threshold key -> the mode key that decides whether it may stay "unset".
_ENFORCE_THRESHOLDS: Mapping[str, str] = {
    "filter.trend.min_aligned_atr": "filter.trend.mode",
    "filter.funding.max_adverse_rate_per_h": "filter.funding.mode",
    "filter.oi_drop.max_drop_pct_24h": "filter.oi_drop.mode",
    "filter.premium.max_abs_pct": "filter.premium.mode",
}

_OTHER_RULES: Mapping[str, Rule] = {
    "storage.ledger_dir": _path_rule,
    "storage.recordings_dir": _path_rule,
    "storage.cache_dir": _path_rule,
    "storage.ledger_backup_time_utc": _pattern_rule(_TIME_OF_DAY, "a time of day HH:MM (00:00 to 23:59)"),
    "recording.markets": _string_list_rule(
        allow_empty=False, item=lambda text: text in ("core", "hip3"), expected="core or hip3"
    ),
    "gate.exclude_roles": _string_list_rule(allow_empty=True),
    "gate.exclude_addresses": _string_list_rule(
        allow_empty=True,
        item=lambda text: _ADDRESS.fullmatch(text) is not None,
        expected="a 0x-prefixed 40-digit hex address",
    ),
    "blowup.any_liquidation": _bool_rule,
    "filter.trend.mode": _enum_rule((RECORD_ONLY, ENFORCE)),
    "filter.funding.mode": _enum_rule((RECORD_ONLY, ENFORCE)),
    "filter.oi_drop.mode": _enum_rule((RECORD_ONLY, ENFORCE)),
    "filter.premium.mode": _enum_rule((RECORD_ONLY, ENFORCE)),
    "shadow.enabled": _bool_rule,
    "calendar.file": _path_rule,
    "calendar.blocking_classes": _string_list_rule(allow_empty=False),
    "risk.high_leverage_coins": _string_list_rule(
        allow_empty=True,
        item=lambda text: text in HIGH_LEVERAGE_COIN_UNIVERSE,
        expected="one of " + ", ".join(sorted(HIGH_LEVERAGE_COIN_UNIVERSE)),
    ),
    "exits.tp_enabled": _bool_rule,
    "exits.atr_candle_interval": _enum_rule(("1m", "1h")),
    "report.daily_time_utc": _pattern_rule(_TIME_OF_DAY, "a time of day HH:MM (00:00 to 23:59)"),
    "report.weekly_time_utc": _pattern_rule(_WEEKLY_TIME, "a weekday and time such as 'Mon 00:10'"),
    "report.disclaimer": _text_rule,
    "llm.enabled": _bool_rule,
    "llm.fallback": _enum_rule(("ollama",)),
    "replay.sensitivity_cost_mults": _number_list_rule,
    "replay.sensitivity_delays_s": _number_list_rule,
    "decay.deltas_s": _number_list_rule,
}


def _build_rules() -> dict[str, Rule]:
    rules: dict[str, Rule] = {}
    for key, spec in NUMERIC_KEYS.items():
        if spec.kind is NumberKind.INT:
            rules[key] = _int_rule(spec.bounds)
        else:
            rules[key] = _decimal_rule(spec.bounds, allow_unset=key in _ENFORCE_THRESHOLDS)
    for key, expected in FIXED_VALUES.items():
        rules[key] = _fixed_rule(expected)
    for key, rule in _OTHER_RULES.items():
        rules[key] = rule
    return rules


_RULES: Mapping[str, Rule] = _build_rules()
"""Every §3 key except ``mode`` (which has its own check), in validation order."""


def schema_keys() -> frozenset[str]:
    """Every dotted key the loader requires (``mode`` included)."""
    return frozenset(_RULES) | {"mode"}


# --- cross-key rules ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Ordering:
    """``key`` must compare ``relation`` to ``other``; a fault is reported on ``key``."""

    key: str
    relation: Callable[[Any, Any], bool]
    phrase: str
    other: str


_WEIGHT_SUM_TOLERANCE = Decimal("1e-9")  # F5.AC5: the six score weights sum to 1 within this

_ORDERINGS: tuple[_Ordering, ...] = (
    _Ordering("gate.min_positive_blocks", operator.le, "at most", "gate.n_blocks"),
    _Ordering("select.min_followed", operator.le, "at most", "select.max_followed"),
    _Ordering("select.max_cycle_duration_min", operator.le, "at most", "scoring.interval_min"),
    _Ordering("select.drop_rank", operator.gt, "above", "select.join_rank"),
    _Ordering("gate.dsr_n_trials", operator.ge, "at least", "scoring.candidates_k"),
    _Ordering("recording.disk_alert_free_gb", operator.gt, "above", "recording.disk_floor_free_gb"),
    _Ordering("tiers.tier1_min_depth_usd", operator.ge, "at least", "tiers.floor_min_depth_usd"),
    _Ordering("tiers.tier1_min_volume_usd", operator.ge, "at least", "tiers.floor_min_volume_usd"),
)


def _check_cross_keys(values: Mapping[str, Any], files: Mapping[str, str]) -> None:
    for rule in _ORDERINGS:
        if not rule.relation(values[rule.key], values[rule.other]):
            raise ConfigError(
                f"must be {rule.phrase} {rule.other} ({_show(values[rule.other])})", key=rule.key, file=files[rule.key]
            )
    for threshold, mode in _ENFORCE_THRESHOLDS.items():
        if values[mode] == ENFORCE and values[threshold] == UNSET:
            raise ConfigError(f"must be set while {mode} is {ENFORCE}", key=threshold, file=files[threshold])
    weights = [values[f"score.weights.{name}"] for name in SCORE_COMPONENTS]
    if abs(sum(weights) - 1) > _WEIGHT_SUM_TOLERANCE:
        raise ConfigError("the six weights must sum to 1", key="score.weights", file=files["score.weights.dsr_excess"])
    for name in SCORE_COMPONENTS:
        if values[f"score.anchors.{name}.lo"] == values[f"score.anchors.{name}.hi"]:
            raise ConfigError(
                "lo and hi must differ", key=f"score.anchors.{name}.hi", file=files[f"score.anchors.{name}.hi"]
            )


# --- reading files ------------------------------------------------------------------------------------


def _flatten(table: Mapping[str, Any], prefix: str) -> Iterator[tuple[str, Any]]:
    for name, value in table.items():
        dotted = f"{prefix}.{name}" if prefix else name
        if isinstance(value, dict):
            yield from _flatten(value, dotted)
        else:
            yield dotted, value


def _parse_file(path: Path, guard: PathGuard | None) -> dict[str, Any]:
    try:
        with guard.open_input(path) if guard is not None else path.open("rb") as handle:
            return tomllib.load(handle, parse_float=Decimal)
    except tomllib.TOMLDecodeError as exc:
        position = _TOML_POSITION.search(str(exc))
        where = f" at line {position.group(1)}, column {position.group(2)}" if position else ""
        raise ConfigError(f"malformed TOML{where}", file=path.name) from None
    except UnicodeDecodeError:
        raise ConfigError("config file is not valid UTF-8", file=path.name) from None
    except OSError as exc:
        raise ConfigError(f"config file unreadable ({type(exc).__name__})", file=path.name) from exc


def _config_files(config_dir: Path, guard: PathGuard | None) -> list[Path]:
    if not config_dir.is_dir():
        raise ConfigError("config directory not found", file=config_dir.name)
    paths = sorted(path for path in config_dir.glob("*.toml") if path.is_file())
    if guard is not None:
        for path in paths:
            guard.check(path)
    return paths


def _is_empty(value: Any) -> bool:
    return value == "" or (isinstance(value, list | tuple | dict) and not value)


@dataclass(frozen=True)
class _Leaves:
    """The flattened config files: dotted key -> value, and dotted key -> the file that set it."""

    values: dict[str, Any]
    files: dict[str, str]


def _collect_leaves(config_dir: Path, guard: PathGuard | None) -> _Leaves:
    leaves = _Leaves({}, {})
    for path in _config_files(config_dir, guard):
        for dotted, value in _flatten(_parse_file(path, guard), ""):
            if dotted in leaves.values:
                raise ConfigError(
                    f"key is set in more than one file (also in {leaves.files[dotted]})", key=dotted, file=path.name
                )
            leaves.values[dotted] = value
            leaves.files[dotted] = path.name
    return leaves


def _reject_secret_keys_and_unknown_keys(leaves: _Leaves) -> None:
    for dotted, value in leaves.values.items():
        if _SECRET_KEY_PATTERN.search(dotted) and dotted not in _SECRET_PATTERN_EXEMPT and not _is_empty(value):
            raise ConfigError(
                "key looks like a secret; secrets are read from environment variables only",
                key=dotted,
                file=leaves.files[dotted],
            )
    mode = leaves.values.get("mode")
    if "mode" in leaves.values:
        if not isinstance(mode, str):
            raise ConfigError("expected text", key="mode", file=leaves.files["mode"])
        if mode != PAPER_MODE:
            raise ModeNotPermittedError(file=leaves.files["mode"])
    for dotted in leaves.values:
        if dotted != "mode" and dotted not in _RULES:
            raise ConfigError("unknown config key", key=dotted, file=leaves.files[dotted])


def _validate(leaves: _Leaves) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for dotted, rule in {"mode": _fixed_rule(PAPER_MODE), **_RULES}.items():
        if dotted not in leaves.values:
            raise ConfigError("missing required key", key=dotted)
        try:
            values[dotted] = rule(leaves.values[dotted])
        except _RejectError as reject:
            raise ConfigError(f"invalid value: {reject}", key=dotted, file=leaves.files[dotted]) from None
    return values


def load_config(config_dir: Path, *, guard: PathGuard | None = None) -> Config:
    """Load and validate every ``*.toml`` file under ``config_dir``.

    With a ``guard``, every file is first checked against the engine path set and opened through it.

    Raises:
        ConfigError: missing, unknown, mistyped or out-of-range key; duplicate key; unreadable or
            malformed file; secret-looking key with a value.
        ModeNotPermittedError: ``mode`` is not ``paper``.
        EnginePathError: (with a ``guard``) a config file is outside the engine path set.
    """
    leaves = _collect_leaves(config_dir, guard)
    _reject_secret_keys_and_unknown_keys(leaves)
    values = _validate(leaves)
    _check_cross_keys(values, leaves.files)
    return Config(values)
