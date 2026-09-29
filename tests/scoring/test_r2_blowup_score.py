"""F5 round 2: tests that kill surviving hand-made mutants in the blow-up detectors and the score (F5.AC4, F5.AC5).

Each test names the behaviour it pins; see the round-2 section of docs/sdlc/copytrade-v1/05-test-plan-F5.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from copytrade.core.config import Config, load_config
from copytrade.scoring.blowup import detect_blowups
from copytrade.scoring.metrics import compute_metrics
from copytrade.scoring.models import RankEntry, TripRecord
from copytrade.scoring.score import rank_entries, score_components
from tests.core.helpers import ConfigTree
from tests.scoring import wallets as W
from tests.scoring.helpers import DAY, H, ZERO_COSTS, D, fill, make_cfg, passing_metrics, record, trip, wallet

pytestmark = pytest.mark.unit


def flags(cfg: Config, records: list[TripRecord] | None = None, **m: object) -> tuple[str, ...]:
    return detect_blowups(records or [], passing_metrics(**m), cfg=cfg)


# --- BU6: any liquidation, exactly one fill is enough ----------------------------------------------------------------
def test_F5_AC4_BU6_a_single_liquidation_fill_with_no_liquidated_trip_fires(cfg_default: Config) -> None:
    # e.g. the liquidated position is still open, so no closed trip carries the flag
    assert "BU6" in flags(cfg_default, [record(trip("5"))], liquidation_fills=1)


def test_F5_AC4_BU6_no_liquidation_fill_and_no_liquidated_trip_does_not_fire(cfg_default: Config) -> None:
    assert "BU6" not in flags(cfg_default, [record(trip("5"))], liquidation_fills=0)


def test_F5_AC4_BU6_switched_off_by_config_even_with_fills_and_liquidated_trips(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path, **{"blowup.any_liquidation": False})
    assert "BU6" not in flags(cfg, [record(trip("-5", liquidated=True))], liquidation_fills=3)
    assert "BU6" not in flags(cfg, [record(trip("5"))], liquidation_fills=1)


def test_F5_AC4_BU6_switched_on_by_config_fires_on_a_liquidated_trip(cfg_default: Config) -> None:
    assert "BU6" in flags(cfg_default, [record(trip("-5", liquidated=True))], liquidation_fills=0)


def test_F5_AC4_BU6_metrics_count_a_single_liquidation_fill_on_a_position_that_is_still_open(tmp_path: Path) -> None:
    # opened, then liquidated down to a smaller size: the trip is not closed, so only the fill count carries it
    fills = [
        fill(W.T - 5 * DAY, "BTC", "B", 10, 100, 0),
        fill(W.T - 4 * DAY, "BTC", "A", 4, 60, 10, pnl=-160, liq=True),
    ]
    cfg = make_cfg(tmp_path, **{"scoring.window_days": 90})
    m = compute_metrics(wallet(fills=fills, fills_fetched_ms=W.FETCHED), cfg=cfg, t_ms=W.T, costs=ZERO_COSTS)
    assert m.n_rt == 0 and m.liquidation_fills == 1
    assert "BU6" in detect_blowups([], m, cfg=cfg)


# --- BU2: a previous trip with zero P&L is neither a win nor a loss --------------------------------------------------
def _zero_pnl_tail(n: int, size: int, start_index: int) -> list[TripRecord]:
    return [record(trip("0", open_ms=(start_index + i) * H, peak_notional=size), av=1000) for i in range(n)]


def _alternating(n: int, after_loss: int, after_win: int) -> list[TripRecord]:
    out = []
    for i in range(n):
        wins = i % 2 == 0
        size = after_loss if i % 2 == 0 else after_win
        out.append(record(trip("10" if wins else "-10", open_ms=i * H, peak_notional=size), av=1000))
    return out


def test_F5_AC4_BU2_trips_that_follow_a_zero_pnl_trip_are_left_out_of_both_groups(cfg_default: Config) -> None:
    base = _alternating(41, 200, 100)  # 20 after a loss at 200, 20 after a win at 100: fires
    assert "BU2" in flags(cfg_default, base)
    # 60 huge break-even trips: were they counted as "after a win" the win median would jump and BU2 would go quiet
    assert "BU2" in flags(cfg_default, base + _zero_pnl_tail(60, 100_000, 41))


def test_F5_AC4_BU2_break_even_trips_are_not_counted_as_after_a_loss_either(cfg_default: Config) -> None:
    base = _alternating(41, 100, 100)  # equal sizes: does not fire
    assert "BU2" not in flags(cfg_default, base)
    assert "BU2" not in flags(cfg_default, base + _zero_pnl_tail(60, 100_000, 41))


def test_F5_AC4_BU2_a_zero_pnl_run_alone_never_fires(cfg_default: Config) -> None:
    assert "BU2" not in flags(cfg_default, _zero_pnl_tail(80, 100_000, 0))


# --- score: capped at 1 when the weights sum to slightly more than 1 ------------------------------------------------
BEST = dict(
    dsr_excess=D("0.5"), copy_mean_r=D(5), n_rt=100_000, pos_blocks=6, max_dd=D(0), recent_sr=D(5), executable_share=D(1)
)


def test_F5_AC5_score_is_capped_at_one_when_the_weights_sum_to_one_plus_5e_10(tmp_path: Path) -> None:
    tree = ConfigTree()
    tree.set("score.weights.dsr_excess", D("0.3") + D("0.0000000005"))
    cfg = load_config(tree.write(tmp_path / "config"))
    c = score_components(passing_metrics(**BEST), cfg=cfg)
    assert all(v == D(1) for v in c.u.values())
    assert D(0) <= c.score <= D(1)
    assert c.score == D(1)


def test_F5_AC5_score_stays_within_zero_and_one_when_the_weights_sum_to_one_minus_5e_10(tmp_path: Path) -> None:
    tree = ConfigTree()
    tree.set("score.weights.dsr_excess", D("0.3") - D("0.0000000005"))
    cfg = load_config(tree.write(tmp_path / "config"))
    c = score_components(passing_metrics(**BEST), cfg=cfg)
    assert D("0.999999999") <= c.score <= D(1)


# --- ranking: the tie-break is on the lowercase address, whatever the case it arrives in -----------------------------
def test_F5_AC5_rank_tie_break_lowercases_a_mixed_case_address() -> None:
    upper_first = RankEntry("0xB000000000000000000000000000000000000001", D("0.5"), 100)
    lower_second = RankEntry("0xa000000000000000000000000000000000000002", D("0.5"), 100)
    # byte order would put "0xB" before "0xa"; the lowercase order puts 0xa... first
    assert [e.address for e in rank_entries([upper_first, lower_second])] == [lower_second.address, upper_first.address]
    assert [e.address for e in rank_entries([lower_second, upper_first])] == [lower_second.address, upper_first.address]


def test_F5_AC5_rank_tie_break_lowercases_the_same_address_in_different_cases() -> None:
    a = RankEntry("0xAb00000000000000000000000000000000000001", D("0.5"), 7)
    b = RankEntry("0xaC00000000000000000000000000000000000002", D("0.5"), 7)
    assert [e.address for e in rank_entries([b, a])] == [a.address, b.address]  # "ab" < "ac"; raw: "aC" < "ab"
