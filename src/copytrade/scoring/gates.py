"""Eligibility gates G1-G15 (F5.AC3), edge-hypothesis 10.3. Fail closed: a missing input fails its gate."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from copytrade.core.config import Config
from copytrade.scoring.models import Metrics
from copytrade.scoring.score import shrink_toward_zero

_SECONDS_PER_MINUTE = Decimal(60)


def _at_least(value: Decimal | int | None, floor: Decimal | int) -> bool:
    return value is not None and value >= floor


def _at_most(value: Decimal | int | None, ceiling: Decimal | int) -> bool:
    return value is not None and value <= ceiling


def _hold_gate(m: Metrics, cfg: Config, p95_latency_s: Decimal | None) -> bool:
    if m.median_hold_min is None or p95_latency_s is None:
        return False
    required = max(cfg["gate.min_median_hold_min"], cfg["gate.hold_latency_mult"] * p95_latency_s / _SECONDS_PER_MINUTE)
    return bool(m.median_hold_min >= required)


def _copy_gate(m: Metrics, cfg: Config) -> bool:
    if m.copy_edge_ratio is None or m.copy_mean_r is None:
        return False
    shrunk = shrink_toward_zero(m.copy_mean_r, m.n_rt, cfg["score.shrink_k_trades"])
    return m.copy_edge_ratio >= cfg["gate.min_copy_edge_ratio"] and shrunk > 0


def _role_gate(cfg: Config, address: str, role: str | None, maker_share: Decimal | None) -> bool:
    excluded_address = address.lower() in {a.lower() for a in cfg["gate.exclude_addresses"]}
    excluded_role = role is None or role in cfg["gate.exclude_roles"]
    return _at_most(maker_share, cfg["gate.max_maker_share"]) and not excluded_address and not excluded_role


def evaluate_gates(  # noqa: PLR0913
    m: Metrics,
    *,
    cfg: Config,
    address: str,
    role: str | None,
    p95_latency_s: Decimal | None,
    blowup_flags: Sequence[str],
) -> tuple[str, ...]:
    """Return the ids (``"G1"``..``"G15"``) of every failed gate in gate order; empty = eligible on the metrics.

    Fail closed: a ``None`` input to a gate fails that gate. G8 uses ``max(gate.min_median_hold_min,
    gate.hold_latency_mult * p95_latency_s / 60)`` and fails when ``p95_latency_s`` is None. G13 fails for the
    roles in ``gate.exclude_roles``, for a missing role (None) and for ``gate.exclude_addresses`` (case-insensitive).
    G14 fails when ``blowup_flags`` is non-empty.
    """
    passed = (
        ("G1", _at_least(m.account_age_days, cfg["gate.min_account_age_days"])),
        ("G2", m.n_rt >= cfg["gate.min_round_trips"]),
        ("G3", _at_least(m.fill_span_days, cfg["gate.min_fill_span_days"])),
        ("G4", m.pos_blocks >= cfg["gate.min_positive_blocks"]),
        ("G5", _at_most(m.max_dd, cfg["gate.max_drawdown"])),
        ("G6", _at_least(m.profit_factor, cfg["gate.min_profit_factor"])),
        (
            "G7",
            _at_least(m.dsr_prob, cfg["gate.min_dsr_prob"]) and m.t_days >= cfg["scoring.dsr_min_daily_days"],
        ),
        ("G8", _hold_gate(m, cfg, p95_latency_s)),
        (
            "G9",
            _at_most(m.top_trade_share, cfg["gate.max_top_trade_share"])
            and _at_most(m.top_asset_share, cfg["gate.max_top_asset_share"]),
        ),
        ("G10", _copy_gate(m, cfg)),
        ("G11", _at_least(m.account_value, cfg["gate.min_account_value_usd"])),
        ("G12", _at_least(m.executable_share, cfg["gate.min_executable_share"])),
        ("G13", _role_gate(cfg, address, role, m.maker_share)),
        ("G14", not blowup_flags),
        ("G15", _at_most(m.current_dd, cfg["gate.max_current_drawdown"])),
    )
    return tuple(gate for gate, ok in passed if not ok)
