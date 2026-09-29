"""F5.AC3: gates G1-G15 at their boundaries, fail closed on missing inputs and on stale inputs.

Spec: 04-spec.md F5.AC3, §3.4 config keys; edge-hypothesis 10.3. Metrics are built directly (a plain data type)
so each gate is tested alone; stale inputs go through the wallet entry point.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from copytrade.core.config import Config
from copytrade.scoring.cycle import score_wallet
from copytrade.scoring.gates import evaluate_gates
from tests.scoring import wallets as W
from tests.scoring.helpers import D, M, PAPER_COSTS, passing_metrics

pytestmark = pytest.mark.unit
ADDR = "0x1111111111111111111111111111111111111111"
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"


def gates(cfg: Config, *, role: str | None = "user", latency: str | None = "3", flags: tuple[str, ...] = (), address: str = ADDR, **m: object) -> tuple[str, ...]:
    return evaluate_gates(
        passing_metrics(**m),
        cfg=cfg,
        address=address,
        role=role,
        p95_latency_s=None if latency is None else D(latency),
        blowup_flags=flags,
    )


def test_F5_AC3_a_wallet_that_passes_everything_has_no_failed_gate(cfg_default: Config) -> None:
    assert gates(cfg_default) == ()


# (gate id, metric field, value that passes, value that fails). Defaults: config §3.4.
BOUNDARIES = [
    ("G1", "account_age_days", D(180), D("179.99")),
    ("G2", "n_rt", 150, 149),
    ("G3", "fill_span_days", D(60), D("59.99")),
    ("G4", "pos_blocks", 4, 3),
    ("G5", "max_dd", D("0.3500"), D("0.3501")),
    ("G6", "profit_factor", D("1.3"), D("1.29")),
    ("G7", "dsr_prob", D("0.95"), D("0.9499")),
    ("G7", "t_days", 60, 59),
    ("G8", "median_hold_min", D(15), D("14.99")),
    ("G9", "top_trade_share", D("0.25"), D("0.2501")),
    ("G9", "top_asset_share", D("0.50"), D("0.5001")),
    ("G10", "copy_edge_ratio", D("3.0"), D("2.99")),
    ("G10", "copy_mean_r", D("0.0001"), D(0)),
    ("G11", "account_value", D(10_000), D("9999.99")),
    ("G12", "executable_share", D("0.50"), D("0.4999")),
    ("G13", "maker_share", D("0.70"), D("0.7001")),
    ("G15", "current_dd", D("0.20"), D("0.2001")),
]


@pytest.mark.parametrize(("gate", "field", "ok", "bad"), BOUNDARIES, ids=[f"{g}-{f}" for g, f, _, _ in BOUNDARIES])
def test_F5_AC3_boundary_exactly_at_the_threshold_passes_and_just_beyond_fails(
    cfg_default: Config, gate: str, field: str, ok: object, bad: object
) -> None:
    assert gate not in gates(cfg_default, **{field: ok})
    assert gates(cfg_default, **{field: bad}) == (gate,)


def test_F5_AC3_required_example_n_rt_149_ineligible_150_eligible(cfg_default: Config) -> None:
    assert gates(cfg_default, n_rt=149) == ("G2",)
    assert gates(cfg_default, n_rt=150) == ()


def test_F5_AC3_required_example_max_dd_0_3500_eligible_0_3501_ineligible(cfg_default: Config) -> None:
    assert gates(cfg_default, max_dd=D("0.3500")) == ()
    assert gates(cfg_default, max_dd=D("0.3501")) == ("G5",)


def test_F5_AC3_required_example_median_hold_14_99_ineligible_at_p95_latency_45s(cfg_default: Config) -> None:
    assert gates(cfg_default, latency="45", median_hold_min=D("14.99")) == ("G8",)
    assert gates(cfg_default, latency="45", median_hold_min=D("15")) == ()  # 20 x 0.75 min = 15 = the floor


@pytest.mark.parametrize(("latency", "ok", "bad"), [("90", "30", "29.99"), ("300", "100", "99.99"), ("0", "15", "14.99")])
def test_F5_AC3_G8_hold_must_exceed_twenty_times_p95_latency(cfg_default: Config, latency: str, ok: str, bad: str) -> None:
    assert "G8" not in gates(cfg_default, latency=latency, median_hold_min=D(ok))
    assert gates(cfg_default, latency=latency, median_hold_min=D(bad)) == ("G8",)


def test_F5_AC3_G8_fails_closed_when_the_latency_is_unknown(cfg_default: Config) -> None:
    assert gates(cfg_default, latency=None) == ("G8",)


@pytest.mark.parametrize(
    "field",
    [
        "account_age_days", "fill_span_days", "profit_factor", "dsr_prob", "median_hold_min", "top_trade_share",
        "top_asset_share", "copy_edge_ratio", "copy_mean_r", "account_value", "executable_share", "maker_share",
        "max_dd", "current_dd",
    ],
)
def test_F5_AC3_a_missing_metric_fails_its_gate_closed(cfg_default: Config, field: str) -> None:
    got = gates(cfg_default, **{field: None})
    assert len(got) == 1 and got[0].startswith("G")


def test_F5_AC3_G13_excluded_roles_missing_role_and_hlp(cfg_default: Config) -> None:
    for role in ("vault", "agent", "missing", None):
        assert gates(cfg_default, role=role) == ("G13",), role
    for role in ("user", "subAccount"):
        assert gates(cfg_default, role=role) == ()
    assert gates(cfg_default, address=HLP) == ("G13",)
    assert gates(cfg_default, address=HLP.upper().replace("0X", "0x")) == ("G13",)  # case-insensitive


def test_F5_AC3_G14_any_blowup_flag_fails_and_none_passes(cfg_default: Config) -> None:
    assert gates(cfg_default, flags=("BU6",)) == ("G14",)
    assert gates(cfg_default, flags=("BU1", "BU7")) == ("G14",)
    assert gates(cfg_default, flags=()) == ()


def test_F5_AC3_every_failed_gate_is_reported_sorted_by_gate_number(cfg_default: Config) -> None:
    got = gates(cfg_default, n_rt=1, max_dd=D("0.9"), current_dd=D("0.9"), account_age_days=D(1))
    assert got == ("G1", "G2", "G5", "G15")


def test_F5_AC3_thresholds_come_from_config_not_from_code(tmp_path: Path) -> None:
    from tests.scoring.helpers import make_cfg

    strict = make_cfg(tmp_path, **{"gate.min_round_trips": 300, "gate.max_drawdown": "0.05", "gate.min_profit_factor": "2.5"})
    assert gates(strict, n_rt=299) == ("G2",) and gates(strict, n_rt=300) == ()
    assert gates(strict, max_dd=D("0.0501")) == ("G5",) and gates(strict, max_dd=D("0.05")) == ()
    assert gates(strict, profit_factor=D("2.49")) == ("G6",) and gates(strict, profit_factor=D("2.5")) == ()


def test_F5_AC3_G4_uses_the_configured_block_requirement(tmp_path: Path) -> None:
    from tests.scoring.helpers import make_cfg

    cfg = make_cfg(tmp_path, **{"gate.min_positive_blocks": 2})
    assert gates(cfg, pos_blocks=1) == ("G4",) and gates(cfg, pos_blocks=2) == ()


def test_F5_AC3_G7_needs_the_configured_minimum_daily_days(tmp_path: Path) -> None:
    from tests.scoring.helpers import make_cfg

    cfg = make_cfg(tmp_path, **{"scoring.dsr_min_daily_days": 30})
    assert gates(cfg, t_days=29) == ("G7",) and gates(cfg, t_days=30) == ()


def test_F5_AC3_G10_shrinkage_never_flips_the_sign(cfg_default: Config) -> None:
    assert gates(cfg_default, copy_mean_r=D("-0.0001")) == ("G10",)
    assert gates(cfg_default, n_rt=150, copy_mean_r=D("0.00001")) == ()


# --- stale and missing inputs (through the wallet entry point) -------------------------------------------------------
INTERVAL_MIN = 60
STALE_MS = 2 * INTERVAL_MIN * M  # stale_input_mult (2) x interval_min (60), in ms


def test_F5_AC3_fresh_inputs_are_not_stale(cfg90: Config) -> None:
    s = score_wallet(W.h1(), cfg=cfg90, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert "stale_input" not in s.reasons


def _stale_variants() -> list[tuple[str, dict[str, object]]]:
    t = W.T
    h = W.h1()
    return [
        ("fills", {"fills_fetched_ms": t - STALE_MS - 1}),
        ("portfolio", {"portfolios": (replace(h.portfolios[0], fetched_ms=t - STALE_MS - 1),)}),
        ("clearinghouse", {"clearinghouse": (replace(h.clearinghouse[0], fetched_ms=t - STALE_MS - 1),)}),
        ("candles", {"candles_fetched_ms": t - STALE_MS - 1}),
    ]


@pytest.mark.parametrize(("name", "change"), _stale_variants(), ids=[n for n, _ in _stale_variants()])
def test_F5_AC3_an_input_older_than_mult_times_interval_is_stale(cfg90: Config, name: str, change: dict[str, object]) -> None:
    s = score_wallet(replace(W.h1(), **change), cfg=cfg90, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)  # type: ignore[arg-type]
    assert s.eligible is False and "stale_input" in s.reasons
    assert s.score is None and s.rank is None


def test_F5_AC3_an_input_exactly_mult_times_interval_old_is_still_fresh(cfg90: Config) -> None:
    h = W.h1()
    at_limit = replace(
        h,
        fills_fetched_ms=W.T - STALE_MS,
        portfolios=(replace(h.portfolios[0], fetched_ms=W.T - STALE_MS),),
        clearinghouse=(replace(h.clearinghouse[0], fetched_ms=W.T - STALE_MS),),
        candles_fetched_ms=W.T - STALE_MS,
    )
    s = score_wallet(at_limit, cfg=cfg90, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert "stale_input" not in s.reasons


@pytest.mark.parametrize("name", ["fills", "portfolio", "clearinghouse", "candles"])
def test_F5_AC3_a_missing_input_is_stale_input_fail_closed(cfg90: Config, name: str) -> None:
    h = W.h1()
    changes: dict[str, dict[str, object]] = {
        "fills": {"fills_fetched_ms": None},
        "portfolio": {"portfolios": ()},
        "clearinghouse": {"clearinghouse": ()},
        "candles": {"candles_fetched_ms": None},
    }
    change = changes[name]
    s = score_wallet(replace(h, **change), cfg=cfg90, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)  # type: ignore[arg-type]
    assert s.eligible is False and "stale_input" in s.reasons


def test_F5_AC3_a_snapshot_fetched_after_the_cycle_time_does_not_count_as_input(cfg90: Config) -> None:
    h = W.h1()
    only_future = replace(h, portfolios=(replace(h.portfolios[0], fetched_ms=W.T + 1),))
    s = score_wallet(only_future, cfg=cfg90, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert "stale_input" in s.reasons  # nothing fetched at or before t


def test_F5_AC3_staleness_limit_follows_config(tmp_path: Path) -> None:
    from tests.scoring.helpers import make_cfg

    tight = make_cfg(tmp_path, **{"scoring.window_days": 90, "scoring.stale_input_mult": 1})
    h = replace(W.h1(), fills_fetched_ms=W.T - 61 * M)  # 61 min old: fine at 2 x 60, stale at 1 x 60
    s = score_wallet(h, cfg=tight, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert "stale_input" in s.reasons
    ok = replace(W.h1(), fills_fetched_ms=W.T - 60 * M)
    assert "stale_input" not in score_wallet(ok, cfg=tight, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S).reasons


def test_F5_AC3_an_empty_wallet_is_ineligible_stale_input_and_does_not_raise(cfg90: Config) -> None:
    from tests.scoring.helpers import wallet

    s = score_wallet(wallet(), cfg=cfg90, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert s.eligible is False and "stale_input" in s.reasons
    assert s.score is None and s.rank is None


def test_F5_AC3_H1_fails_the_sample_size_and_edge_gates_it_should(cfg90: Config) -> None:
    s = score_wallet(W.h1(), cfg=cfg90, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert s.eligible is False
    # 7 round trips (G2), 79-day span passes G3, 2 positive blocks (G4), PF 1.35 passes G6, DSR ~0 (G7), edge ratio 2.55 (G10)
    for g in ("G2", "G4", "G7", "G10"):
        assert g in s.reasons, g
    for g in ("G3", "G5", "G6", "G11", "G13", "G15"):
        assert g not in s.reasons, g
