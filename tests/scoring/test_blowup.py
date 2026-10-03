"""F5.AC4: blow-up detectors BU1-BU8 fire exactly at their section 10.5 thresholds and never below their minimum sample.

Spec: 04-spec.md F5.AC4, §3.4 ``blowup.*``; edge-hypothesis 10.5 and 10.7 test 11. Trip records are built directly.
Inclusive/exclusive: every rule is a strict ">" or "<" as written in 10.5, so the threshold itself does not fire.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from copytrade.core.config import Config
from copytrade.scoring.blowup import detect_blowups
from copytrade.scoring.models import TripRecord
from tests.scoring.helpers import D, H, make_cfg, passing_metrics, record, trip

pytestmark = pytest.mark.unit


def flags(cfg: Config, records: list[TripRecord] | None = None, **m: object) -> tuple[str, ...]:
    return detect_blowups(records or [], passing_metrics(**m), cfg=cfg)


def adds_records(total_adds: int, losing: int) -> list[TripRecord]:
    """One winning trip carrying the adds (BU1 sums adds over trips)."""
    return [record(trip("10", adds=total_adds, adds_while_losing=losing))]


# --- BU1 martingale adds -----------------------------------------------------------------------------------------------
def test_F5_AC4_BU1_below_the_minimum_of_ten_adds_never_fires(cfg_default: Config) -> None:
    assert "BU1" not in flags(cfg_default, adds_records(9, 9))  # every add a loser, but only 9 adds


def test_F5_AC4_BU1_at_ten_adds_share_0_20_does_not_fire_and_0_30_fires(cfg_default: Config) -> None:
    assert "BU1" not in flags(cfg_default, adds_records(10, 2))  # 0.20, not above
    assert "BU1" in flags(cfg_default, adds_records(10, 3))  # 0.30


def test_F5_AC4_BU1_spec_example_share_0_21_fires_and_0_20_does_not(cfg_default: Config) -> None:
    # The spec quotes 0.21 "at 10 adds"; a share of 0.21 needs at least 100 adds, so it is tested at 100.
    assert "BU1" in flags(cfg_default, adds_records(100, 21))
    assert "BU1" not in flags(cfg_default, adds_records(100, 20))


def test_F5_AC4_BU1_sums_adds_across_trips(cfg_default: Config) -> None:
    recs = [record(trip("5", adds=5, adds_while_losing=2, open_ms=i * H)) for i in range(2)]  # 10 adds, 4 losing = 0.4
    assert "BU1" in flags(cfg_default, recs)
    recs = [record(trip("5", adds=5, adds_while_losing=1, open_ms=i * H)) for i in range(2)]  # 10 adds, 2 losing = 0.2
    assert "BU1" not in flags(cfg_default, recs)


def test_F5_AC4_BU1_thresholds_follow_config(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path, **{"blowup.max_adds_while_losing_share": "0.5", "blowup.min_adds": 4})
    assert "BU1" not in flags(cfg, adds_records(3, 3))
    assert "BU1" not in flags(cfg, adds_records(4, 2))
    assert "BU1" in flags(cfg, adds_records(4, 3))


# --- BU2 size up after losses ------------------------------------------------------------------------------------------
def alternating(n: int, after_loss_notional: int, after_win_notional: int) -> list[TripRecord]:
    """W, L, W, L, ...: trip i (i >= 1) follows trip i-1. Odd i follow a win, even i >= 2 follow a loss."""
    out = []
    for i in range(n):
        wins = i % 2 == 0
        size = after_loss_notional if i % 2 == 0 else after_win_notional
        out.append(record(trip("10" if wins else "-10", open_ms=i * H, peak_notional=size), av=1000))
    return out


def test_F5_AC4_BU2_fires_above_1_5_and_not_at_1_5(cfg_default: Config) -> None:
    # 41 trips: 20 follow a win, 20 follow a loss
    assert "BU2" in flags(cfg_default, alternating(41, 151, 100))  # 1.51
    assert "BU2" not in flags(cfg_default, alternating(41, 150, 100))  # exactly 1.5
    assert "BU2" not in flags(cfg_default, alternating(41, 100, 100))


def test_F5_AC4_BU2_needs_twenty_of_each(cfg_default: Config) -> None:
    assert "BU2" not in flags(cfg_default, alternating(40, 900, 100))  # 20 after a win, 19 after a loss
    assert "BU2" in flags(cfg_default, alternating(41, 900, 100))


def test_F5_AC4_BU2_ignores_trips_with_no_account_value_at_open(cfg_default: Config) -> None:
    recs = alternating(41, 900, 100)
    recs = [r if i % 2 == 1 else TripRecord(trip=r.trip, av_at_open=None) for i, r in enumerate(recs)]
    assert "BU2" not in flags(cfg_default, recs)  # the after-loss trips are excluded: 0 samples


# --- BU3 short-volatility profile --------------------------------------------------------------------------------------
def skew_records(wins: int, losses: int, win_pnl: str, loss_pnl: str) -> list[TripRecord]:
    return [record(trip(win_pnl, open_ms=i * H)) for i in range(wins)] + [
        record(trip(loss_pnl, open_ms=(wins + i) * H)) for i in range(losses)
    ]


def test_F5_AC4_BU3_needs_win_rate_above_0_85_and_mean_loss_above_three_times_mean_win(cfg_default: Config) -> None:
    assert "BU3" in flags(cfg_default, skew_records(86, 14, "1", "-3.01"))
    assert "BU3" not in flags(cfg_default, skew_records(85, 15, "1", "-9"))  # win rate exactly 0.85
    assert "BU3" not in flags(cfg_default, skew_records(86, 14, "1", "-3"))  # mean loss exactly 3 x mean win
    assert "BU3" not in flags(cfg_default, skew_records(60, 40, "1", "-9"))  # low win rate


def test_F5_AC4_BU3_all_winners_is_not_a_short_vol_profile(cfg_default: Config) -> None:
    assert "BU3" not in flags(cfg_default, skew_records(100, 0, "1", "-1"))  # no losses: nothing to compare


# --- BU4 tail loss -----------------------------------------------------------------------------------------------------
def tail_records(n_losses: int, worst: str) -> list[TripRecord]:
    losses = [record(trip("-1", open_ms=i * H)) for i in range(n_losses - 1)]
    return [record(trip("100", open_ms=999 * H)), *losses, record(trip(worst, open_ms=1000 * H))]


def test_F5_AC4_BU4_fires_when_the_worst_loss_is_beyond_ten_times_the_median_loss(cfg_default: Config) -> None:
    assert "BU4" in flags(cfg_default, tail_records(10, "-10.01"))
    assert "BU4" not in flags(cfg_default, tail_records(10, "-10"))  # exactly 10 x the median


def test_F5_AC4_BU4_never_fires_below_ten_losses(cfg_default: Config) -> None:
    assert "BU4" not in flags(cfg_default, tail_records(9, "-1000"))
    assert "BU4" in flags(cfg_default, tail_records(10, "-1000"))


# --- BU5 hidden drawdown -----------------------------------------------------------------------------------------------
def test_F5_AC4_BU5_needs_mtm_above_twice_realised_and_above_0_15(cfg_default: Config) -> None:
    def f(mtm: str, real: str) -> tuple[str, ...]:
        return flags(cfg_default, max_dd_mtm=D(mtm), max_dd_realised=D(real))

    assert "BU5" in f("0.1501", "0.05")
    assert "BU5" not in f("0.15", "0.05")  # not above the floor
    assert "BU5" not in f("0.30", "0.15")  # exactly twice
    assert "BU5" in f("0.3001", "0.15")
    assert "BU5" not in f("0.14", "0.01")  # far above twice, below the floor
    assert "BU5" in f("0.20", "0")


# --- BU6 liquidation ---------------------------------------------------------------------------------------------------
def test_F5_AC4_BU6_any_liquidated_trip_fires(cfg_default: Config) -> None:
    assert "BU6" in flags(cfg_default, [record(trip("-5", liquidated=True)), record(trip("5", open_ms=H))])
    assert "BU6" not in flags(cfg_default, [record(trip("-5")), record(trip("5", open_ms=H))])


# --- BU7 leverage ------------------------------------------------------------------------------------------------------
def test_F5_AC4_BU7_median_effective_leverage_above_ten(cfg_default: Config) -> None:
    assert "BU7" in flags(cfg_default, eff_leverage_median=D("10.01"))
    assert "BU7" not in flags(cfg_default, eff_leverage_median=D("10"))


# --- BU8 bag holding now -----------------------------------------------------------------------------------------------
def test_F5_AC4_BU8_open_unrealised_loss_above_ten_percent_of_account_value(cfg_default: Config) -> None:
    assert "BU8" in flags(cfg_default, open_loss_fraction=D("0.1001"))
    assert "BU8" not in flags(cfg_default, open_loss_fraction=D("0.10"))


def test_F5_AC4_BU8_and_BU7_follow_config(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path, **{"blowup.max_open_unrealized_loss": "0.05", "blowup.max_median_eff_leverage": 5})
    assert "BU8" in flags(cfg, open_loss_fraction=D("0.06")) and "BU8" not in flags(cfg, open_loss_fraction=D("0.05"))
    assert "BU7" in flags(cfg, eff_leverage_median=D("5.01")) and "BU7" not in flags(cfg, eff_leverage_median=D(5))


# --- all together ------------------------------------------------------------------------------------------------------
def test_F5_AC4_no_detector_fires_on_a_clean_wallet(cfg_default: Config) -> None:
    assert flags(cfg_default, [record(trip("10", open_ms=i * H)) for i in range(30)]) == ()


def test_F5_AC4_missing_inputs_do_not_fire_and_do_not_raise(cfg_default: Config) -> None:
    assert flags(cfg_default, [], max_dd_mtm=None, max_dd_realised=None, eff_leverage_median=None, open_loss_fraction=None) == ()


def test_F5_AC4_flags_are_sorted_and_multiple_can_fire(cfg_default: Config) -> None:
    got = flags(cfg_default, [record(trip("-5", liquidated=True))], eff_leverage_median=D(20), open_loss_fraction=D("0.5"))
    assert got == ("BU6", "BU7", "BU8")


def test_F5_AC4_a_liquidation_fill_makes_a_wallet_ineligible_through_the_pipeline(cfg90: Config) -> None:
    from dataclasses import replace

    from copytrade.scoring.cycle import score_wallet
    from tests.scoring import wallets as W
    from tests.scoring.helpers import PAPER_COSTS, fill

    w = W.healthy("0xaaa0000000000000000000000000000000000009")
    liq = [fill(280 * 86_400_000, "ETH", "B", 1, 100, 0), fill(280 * 86_400_000 + H, "ETH", "A", 1, 60, 1, pnl=-40, liq=True)]
    s = score_wallet(replace(w, fills=(*w.fills, *liq)), cfg=cfg90, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert "BU6" in s.blowup_flags and "G14" in s.reasons and s.eligible is False and s.score is None
