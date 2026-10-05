"""F5.AC5: score properties (edge-hypothesis 10.4, 10.7 tests 1-4 and 13).

Spec: 04-spec.md F5.AC5, §3.4 ``score.*``. Components are computed from a Metrics value directly.
Vector V1 (hand computed, default config, n_blocks 6, shrink_k_trades 100):
  dsr_excess 0.075 -> u 0.5;  copy_mean_r 0.24 x 300/400 = 0.18 -> u 0.6;  pos_blocks 5/6 -> u 2/3;
  max_dd 0.20 -> u 0.5;  recent_sr 0.6 -> clipped to 1;  executable 0.75 -> u 0.5
  S = .30*.5 + .25*.6 + .15*(2/3) + .15*.5 + .10*1 + .05*.5 = 0.60
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.config import Config, load_config
from copytrade.core.errors import ConfigError
from copytrade.scoring.models import Metrics, RankEntry
from copytrade.scoring.score import rank_entries, score_components
from tests.core.helpers import ConfigTree
from tests.scoring.helpers import D, make_cfg, passing_metrics

pytestmark = pytest.mark.unit

V1 = dict(
    dsr_excess=D("0.075"),
    copy_mean_r=D("0.24"),
    n_rt=300,
    pos_blocks=5,
    max_dd=D("0.20"),
    recent_sr=D("0.6"),
    executable_share=D("0.75"),
)
NAMES = ("dsr_excess", "copy_mean_r", "pos_blocks", "max_dd", "recent_sr", "executable")


def close(a: Decimal, b: float, tol: float = 1e-9) -> bool:
    return abs(float(a) - b) <= tol


def test_F5_AC5_vector_V1_components_and_score(cfg_default: Config) -> None:
    c = score_components(passing_metrics(**V1), cfg=cfg_default)
    expected_u = {"dsr_excess": 0.5, "copy_mean_r": 0.6, "pos_blocks": 2 / 3, "max_dd": 0.5, "recent_sr": 1.0, "executable": 0.5}
    assert set(c.u) == set(NAMES)
    for name, want in expected_u.items():
        assert close(c.u[name], want), name
    assert close(c.score, 0.60)


def test_F5_AC5_raw_components_x_are_reported(cfg_default: Config) -> None:
    c = score_components(passing_metrics(**V1), cfg=cfg_default)
    assert close(c.x["copy_mean_r"], 0.18)  # shrunk by n / (n + 100)
    assert close(c.x["pos_blocks"], 5 / 6)
    assert close(c.x["recent_sr"], 0.6)  # not clipped in x


@pytest.mark.parametrize(
    ("name", "field", "lo_value", "hi_value"),
    [
        ("dsr_excess", "dsr_excess", D("-0.5"), D("0.5")),
        ("copy_mean_r", "copy_mean_r", D("-0.5"), D("2")),
        ("pos_blocks", "pos_blocks", 0, 6),
        ("max_dd", "max_dd", D("0.9"), D("0")),  # lower is better: 0.9 is worse than the 0.35 anchor
        ("recent_sr", "recent_sr", D("-1"), D("1")),
        ("executable", "executable_share", D("0.1"), D("1")),
    ],
)
def test_F5_AC5_each_component_clips_to_zero_and_one_at_the_anchors(cfg_default: Config, name: str, field: str, lo_value: object, hi_value: object) -> None:
    worst = score_components(passing_metrics(**{field: lo_value}), cfg=cfg_default)
    best = score_components(passing_metrics(**{field: hi_value}), cfg=cfg_default)
    assert worst.u[name] == D(0) and best.u[name] == D(1)


def test_F5_AC5_anchors_are_hit_exactly(cfg_default: Config) -> None:
    at_lo = score_components(passing_metrics(dsr_excess=D(0), max_dd=D("0.35"), executable_share=D("0.5")), cfg=cfg_default)
    at_hi = score_components(passing_metrics(dsr_excess=D("0.15"), max_dd=D("0.05"), executable_share=D(1)), cfg=cfg_default)
    for name in ("dsr_excess", "max_dd", "executable"):
        assert at_lo.u[name] == D(0) and at_hi.u[name] == D(1)


def test_F5_AC5_all_components_at_best_gives_one_and_at_worst_gives_zero(cfg_default: Config) -> None:
    best = passing_metrics(dsr_excess=D(1), copy_mean_r=D(10), pos_blocks=6, max_dd=D(0), recent_sr=D(1), executable_share=D(1))
    worst = passing_metrics(dsr_excess=D(-1), copy_mean_r=D(-10), pos_blocks=0, max_dd=D(1), recent_sr=D(-1), executable_share=D(0))
    assert close(score_components(best, cfg=cfg_default).score, 1.0)
    assert score_components(worst, cfg=cfg_default).score == D(0)


def test_F5_AC5_weights_and_anchors_come_from_config(tmp_path: Path) -> None:
    cfg = make_cfg(
        tmp_path,
        **{
            "score.weights.dsr_excess": "0.5", "score.weights.copy_mean_r": "0.5", "score.weights.pos_blocks": "0",
            "score.weights.max_dd": "0", "score.weights.recent_sr": "0", "score.weights.executable": "0",
            "score.anchors.dsr_excess.hi": "0.30",
        },
    )
    c = score_components(passing_metrics(**{**V1, "dsr_excess": D("0.15")}), cfg=cfg)  # u1 = 0.15 / 0.30 = 0.5
    assert close(c.u["dsr_excess"], 0.5) and close(c.score, 0.5 * 0.5 + 0.5 * 0.6)


def test_F5_AC5_shrinkage_constant_comes_from_config(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path, **{"score.shrink_k_trades": 0})
    assert close(score_components(passing_metrics(**V1), cfg=cfg).x["copy_mean_r"], 0.24)


@pytest.mark.parametrize("field", ["dsr_excess", "copy_mean_r", "max_dd", "recent_sr", "executable_share"])
def test_F5_AC5_a_missing_component_input_raises_rather_than_scoring(cfg_default: Config, field: str) -> None:
    with pytest.raises(ValueError):
        score_components(passing_metrics(**{field: None}), cfg=cfg_default)


# --- config: weights must sum to 1 (already enforced by F1's loader; kept here as the F5 contract) -------------------
@pytest.mark.parametrize("delta", ["0.000000002", "-0.000000002", "0.0001", "-0.0001", "0.5", "-0.3"])
def test_F5_AC5_weights_that_do_not_sum_to_one_fail_config_load(tmp_path: Path, delta: str) -> None:
    tree = ConfigTree()
    tree.set("score.weights.dsr_excess", D(str(tree.get("score.weights.dsr_excess"))) + D(delta))
    with pytest.raises(ConfigError) as info:
        load_config(tree.write(tmp_path / "config"))
    assert info.value.key is not None and info.value.key.startswith("score.weights")


def test_F5_AC5_weights_within_1e_9_of_one_load(tmp_path: Path) -> None:
    tree = ConfigTree()
    tree.set("score.weights.dsr_excess", D("0.3") + D("0.0000000005"))
    load_config(tree.write(tmp_path / "config"))


# --- properties --------------------------------------------------------------------------------------------------------
dec = st.decimals(min_value="-2", max_value="2", places=4)
share = st.decimals(min_value="0", max_value="1", places=4)


@st.composite
def metrics_st(draw: st.DrawFn) -> Metrics:
    return passing_metrics(
        dsr_excess=draw(dec), copy_mean_r=draw(dec), n_rt=draw(st.integers(1, 2000)), pos_blocks=draw(st.integers(0, 6)),
        max_dd=draw(share), recent_sr=draw(dec), executable_share=draw(share),
    )


@given(metrics_st())
@settings(max_examples=200)
def test_F5_AC5_property_score_is_between_zero_and_one_and_each_u_too(m: Metrics) -> None:
    c = score_components(m, cfg=_DEFAULT[0])
    assert D(0) <= c.score <= D(1)
    assert all(D(0) <= u <= D(1) for u in c.u.values())


_DEFAULT: list[Config] = []


@pytest.fixture(autouse=True, scope="module")
def _load_default(cfg_default: Config) -> None:
    _DEFAULT[:] = [cfg_default]


@given(metrics_st(), st.decimals(min_value="0", max_value="1", places=3))
@settings(max_examples=150)
def test_F5_AC5_property_better_never_scores_lower(m: Metrics, bump: Decimal) -> None:
    cfg = _DEFAULT[0]
    base = score_components(m, cfg=cfg).score
    better = [
        replace(m, dsr_excess=m.dsr_excess + bump),  # type: ignore[operator]
        replace(m, copy_mean_r=m.copy_mean_r + bump),  # type: ignore[operator]
        replace(m, pos_blocks=min(6, m.pos_blocks + 1)),
        replace(m, max_dd=max(D(0), m.max_dd - bump)),  # type: ignore[operator]
        replace(m, recent_sr=m.recent_sr + bump),  # type: ignore[operator]
        replace(m, executable_share=min(D(1), m.executable_share + bump)),  # type: ignore[operator]
    ]
    for b in better:
        assert score_components(b, cfg=cfg).score >= base - D("1e-12")


@given(metrics_st())
@settings(max_examples=100)
def test_F5_AC5_property_shrinkage_keeps_the_sign_and_never_grows_the_magnitude(m: Metrics) -> None:
    x = score_components(m, cfg=_DEFAULT[0]).x["copy_mean_r"]
    raw = m.copy_mean_r
    assert raw is not None
    assert abs(x) <= abs(raw)
    assert x == 0 or (x > 0) == (raw > 0)
    assert (raw == 0) == (x == 0)


@given(metrics_st())
@settings(max_examples=50)
def test_F5_AC5_property_score_is_deterministic_and_independent_of_other_wallets(m: Metrics) -> None:
    cfg = _DEFAULT[0]
    once = score_components(m, cfg=cfg)
    score_components(passing_metrics(dsr_excess=D("0.9")), cfg=cfg)  # another wallet scored in between
    assert score_components(m, cfg=cfg) == once


def test_F5_AC5_score_ignores_fields_that_are_not_components(cfg_default: Config) -> None:
    a = score_components(passing_metrics(**V1), cfg=cfg_default)
    b = score_components(passing_metrics(**V1, profit_factor=D(9), maker_share=D("0.1"), account_value=D(9), sr_d=D("0.9")), cfg=cfg_default)
    assert a == b


# --- ranking and tie-break ---------------------------------------------------------------------------------------------
def test_F5_AC5_rank_orders_by_score_then_n_rt_then_lowercase_address(cfg_default: Config) -> None:
    entries = [
        RankEntry("0xbb", D("0.5"), 200),
        RankEntry("0xaa", D("0.5"), 200),  # same score and n_rt: address ascending
        RankEntry("0xcc", D("0.5"), 300),  # same score, more round trips: first
        RankEntry("0xdd", D("0.6"), 150),  # best score
        RankEntry("0xee", D("0.4"), 900),
    ]
    got = [e.address for e in rank_entries(entries)]
    assert got == ["0xdd", "0xcc", "0xaa", "0xbb", "0xee"]


def test_F5_AC5_rank_tie_break_uses_the_lowercase_address() -> None:
    a = RankEntry("0xABCD", D("0.5"), 10)
    b = RankEntry("0xabce", D("0.5"), 10)
    assert [e.address.lower() for e in rank_entries([b, a])] == ["0xabcd", "0xabce"]


@given(st.lists(st.tuples(st.integers(0, 5), st.integers(1, 3), st.integers(0, 9)), min_size=0, max_size=12, unique_by=lambda t: t[2]), st.randoms(use_true_random=False))
def test_F5_AC5_property_ranking_is_deterministic_under_input_order(rows: list[tuple[int, int, int]], rnd: object) -> None:
    entries = [RankEntry(f"0x{a:040x}", D(s) / 5, n) for s, n, a in rows]
    expected = rank_entries(entries)
    shuffled = entries[:]
    rnd.shuffle(shuffled)  # type: ignore[attr-defined]
    assert rank_entries(shuffled) == expected
    keys = [(-e.score, -e.n_rt, e.address) for e in expected]
    assert keys == sorted(keys)


def test_F5_AC5_rank_of_nothing_is_empty() -> None:
    assert rank_entries([]) == ()
