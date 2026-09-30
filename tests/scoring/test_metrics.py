"""F5.AC1: metrics M1-M19 against hand-computed fixture wallets (H1, W_R, W_M and four edge wallets).

Spec: 04-spec.md F5.AC1; edge-hypothesis 10.1, 10.2. Money and day counts compare exactly; ratios to 1e-9.
The derivations are in tests/scoring/wallets.py comments and 05-test-plan-F5.md.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.config import Config
from copytrade.scoring.metrics import compute_metrics, copy_replay_r, daily_returns, trip_records
from copytrade.scoring.models import DsrResolution, Metrics
from tests.scoring import wallets as W
from tests.scoring.helpers import (
    DAY,
    H,
    M,
    PAPER_COSTS,
    ZERO_COSTS,
    FixedCosts,
    clearinghouse,
    fill,
    flat_candles,
    portfolio,
    round_trip_fills,
    wallet,
    window,
)

pytestmark = pytest.mark.unit
D = Decimal
T = W.T


def close(actual: Decimal | None, expected: float, tol: float = 1e-9) -> bool:
    return actual is not None and abs(float(actual) - expected) <= tol


def h1m(cfg: Config) -> Metrics:
    return compute_metrics(W.h1(), cfg=cfg, t_ms=T, costs=PAPER_COSTS)


# --- H1: exact (money, counts, days) ---------------------------------------------------------------------------------
def test_F5_AC1_H1_counts_days_and_money_are_exact(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    m = h1_metrics
    assert m.n_rt == 7  # M1: the open SOL trip, the HIP-3 fill, the spot fill and the pre-existing ETH are not counted
    assert m.fill_span_days == D(79)  # M2: first core-perp fill day 211 -> last day 290
    assert m.account_age_days == D(200)  # M3: t - first perpAllTime point (day 100)
    assert m.median_hold_min == D(120)  # M10: holds 30,60,120,120,120,360,2880
    assert m.account_value == D(20_000)  # G11 input, clearinghouseState
    assert m.pos_blocks == 2  # M8: blocks (270,300] +32.9 and (210,240] +119.6 positive; 240-270 negative; 3 blocks have no data
    assert m.t_days == 90


def test_F5_AC1_H1_M4_profit_factor(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    assert close(h1_metrics.profit_factor, 152.7 / 112.8)  # wins 19.2+62+38.4+18.6+14.5, losses 20.4+92.4


def test_F5_AC1_H1_M11_M12_concentration(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    assert close(h1_metrics.top_trade_share, 62 / 39.9)  # sum L = 39.9
    assert close(h1_metrics.top_asset_share, 21.9 / 39.9)  # BTC 21.9, ETH 18.0


def test_F5_AC1_H1_M13_maker_share(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    assert close(h1_metrics.maker_share, 3960 / 24109)  # core-perp fill notional in the window; HIP-3 and spot excluded


def test_F5_AC1_H1_M9_M18_drawdowns(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    m = h1_metrics
    assert close(m.max_dd_realised, 0.011146685639748606)  # peak 10099.4 -> trough 9966.2 on AV_0 + cumulative L_j
    assert close(m.max_dd_mtm, 300 / 10100)  # 10000 + pnlHistory: peak 10100, trough 9800
    assert close(m.max_dd, 300 / 10100)  # the larger of the two
    assert close(m.current_dd, 160 / 10100)  # (10100 - 9940) / 10100


def test_F5_AC1_H1_M5_M6_M7_return_statistics(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    m = h1_metrics
    assert close(m.sr_d, 0.07574447540131825)
    assert close(m.skew, 2.3821425745735567)
    assert close(m.kurt, 34.99488248574413)
    assert close(m.sr0, 0.41728164658492317)  # Emax(15000) / sqrt(90)
    assert close(m.dsr_prob, 0.00027236735413432855)
    assert close(m.dsr_excess, -0.34153717118360494)


def test_F5_AC1_H1_M17_recent_sr_is_shrunk(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    assert close(h1_metrics.recent_sr, 0.09071495471379967)  # sr of days 270..299 x 30 / (30 + 30)


def test_F5_AC1_H1_M15_copy_edge_ratio(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    # mean gross bps 45.8959341... over mean cost bps 2*4.5 + 2*2 + 5 = 18 (BTC and ETH are majors in PAPER_COSTS)
    assert close(h1_metrics.copy_edge_ratio, 2.549774118401569)


def test_F5_AC1_H1_M16_executable_share(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    # mirrored = open notional / AV at open x $300: 30, 30, 30, 7.5 (below $10), 45 -> cap 37.5, 15, 22.95 -> 6 of 7
    assert close(h1_metrics.executable_share, 6 / 7)


def test_F5_AC1_H1_M19_effective_leverage(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    assert close(h1_metrics.eff_leverage_median, 0.1)  # N_j / AV: .1 .198 .1 .025 .15 .05 .0765 -> median .1


def test_F5_AC1_H1_BU8_input_open_loss_fraction(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    assert close(h1_metrics.open_loss_fraction, 500 / 20_000)


def test_F5_AC1_H1_M14_is_computed_and_finite(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    assert h1_metrics.copy_mean_r is not None
    assert -3 < float(h1_metrics.copy_mean_r) < 3


def test_F5_AC1_H1_trip_records_carry_the_account_value_at_open(cfg90: Config) -> None:
    recs = trip_records(W.h1(), cfg=cfg90, t_ms=T)
    assert [r.trip.net_pnl for r in recs] == [D("19.2"), D("62"), D("38.4"), D("-20.4"), D("-92.4"), D("18.6"), D("14.5")]
    assert [r.av_at_open for r in recs] == [D(10_000), D(10_000), D(20_000), D(20_000), D(20_000), D(20_000), D(20_000)]


# --- W_R: M14 vectors (zero cost, so the arithmetic is the spec's) ---------------------------------------------------
def test_F5_AC1_WR_M14_per_trip_R_at_zero_cost(cfg90: Config) -> None:
    rs = [float(x) for x in copy_replay_r(W.wr(), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)]
    # a) +2% / 4% stop = +0.5; b) -2% -> -0.5; c) short, +1% -> +0.25; d) stop 96 hit first (bar also reaches 108.5): -1
    assert len(rs) == 4
    for got, want in zip(rs, [0.5, -0.5, 0.25, -1.0], strict=True):
        assert abs(got - want) < 1e-9


def test_F5_AC1_WR_M14_mean_and_metrics(cfg90: Config) -> None:
    m = compute_metrics(W.wr(), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.n_rt == 4
    assert close(m.copy_mean_r, -0.1875)


def test_F5_AC1_WR_M14_costs_only_ever_lower_R(cfg90: Config) -> None:
    zero = [float(x) for x in copy_replay_r(W.wr(), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)]
    paid = [float(x) for x in copy_replay_r(W.wr(), cfg=cfg90, t_ms=T, costs=PAPER_COSTS)]
    assert len(paid) == 4
    assert all(p < z for p, z in zip(paid, zero, strict=True))
    # cost 2*4.5 + 2*2 + 5 = 18 bps of a 4% stop is about 0.045 R per trade; allow for the second-order terms
    assert all(0.03 < z - p < 0.06 for p, z in zip(paid, zero, strict=True))


@pytest.mark.parametrize(
    "costs",
    [FixedCosts(taker=D(10)), FixedCosts(default_half_spread=D(10)), FixedCosts(default_delay=D(10))],
    ids=["taker", "half_spread", "delay"],
)
def test_F5_AC1_WR_M14_each_cost_component_lowers_R(cfg90: Config, costs: FixedCosts) -> None:
    zero = [float(x) for x in copy_replay_r(W.wr(), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)]
    paid = [float(x) for x in copy_replay_r(W.wr(), cfg=cfg90, t_ms=T, costs=costs)]
    assert all(p < z for p, z in zip(paid, zero, strict=True))


def test_F5_AC1_WR_M14_bars_after_the_cycle_time_change_nothing(cfg90: Config) -> None:
    w = W.wr()
    base = [float(x) for x in copy_replay_r(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)]
    future = flat_candles("BTC", 100, T, T + 5 * H, spread="0.5")  # bars that close after the cycle time
    later = replace(w, candles_1h={"BTC": (*w.candles_1h["BTC"], *future)})
    assert [float(x) for x in copy_replay_r(later, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)] == base


def test_F5_AC1_M14_without_candles_the_stop_cannot_be_built(cfg90: Config) -> None:
    w = replace(W.wr(), candles_1h={})
    m = compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.copy_mean_r is None  # fail closed: G10 will fail
    assert m.executable_share is None  # no stop -> no risk cap -> cannot say


# --- W_M: daily-return sources ---------------------------------------------------------------------------------------
def test_F5_AC1_WM_sources_own_hourly_then_perpMonth_then_fills(cfg90: Config) -> None:
    rets, res = daily_returns(W.wm(), cfg=cfg90, t_ms=T)
    assert res == DsrResolution(own_hourly_days=10, perp_month_days=20, fill_days=60)
    r = dict(rets)
    assert len(r) == 90 and sorted(r) == list(range(210, 300))
    assert r[230] == D("0.002") and r[240] == D("-0.003") and r[215] == D(0)  # fills: realised, zeros included
    assert r[270] == D("0.0003") and r[271] == D("-0.0001")  # perpMonth: +3 on days divisible by 3, else -1
    assert r[290] == D("0.001") and r[291] == D("-0.0004")  # own hourly: +10 even days, -4 odd days


def test_F5_AC1_WM_metrics_use_all_ninety_days(cfg90: Config) -> None:
    m = compute_metrics(W.wm(), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.t_days == 90
    assert close(m.sr_d, 0.06651128405473967)
    assert close(m.skew, -1.7624722395942853)
    assert close(m.kurt, 24.69809166903904)
    assert close(m.dsr_prob, 0.0009852023540162236)
    assert close(m.recent_sr, 0.13833344124464705)


def test_F5_AC1_WM_all_time_points_are_never_interpolated_into_returns(cfg90: Config) -> None:
    base = compute_metrics(W.wm(), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    base_days, base_res = daily_returns(W.wm(), cfg=cfg90, t_ms=T)
    extra = ((215 * DAY + 5 * H, 1234), (222 * DAY + 3 * H, -777), (260 * DAY + 1, 5))
    more = W.wm(extra_alltime_pnl=extra)
    m = compute_metrics(more, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    days, res = daily_returns(more, cfg=cfg90, t_ms=T)
    assert (m.sr_d, m.t_days) == (base.sr_d, base.t_days)
    assert days == base_days and res == base_res


def test_F5_AC1_daily_return_uses_the_account_value_at_or_before_the_previous_day_end(cfg90: Config) -> None:
    # AV 10000 from day 100 and 20000 from day 230.5. Day 230 still divides by 10000, day 231 by 20000.
    fills = round_trip_fills(230 * DAY + H, H, sz=10, px=100, exit_px=101) + round_trip_fills(
        231 * DAY + H, H, sz=10, px=100, exit_px=101
    )
    w = wallet(
        fills=fills,
        portfolios=[portfolio(W.FETCHED, perpAllTime=window([(100 * DAY, 10_000), (int(230.5 * DAY), 20_000)]))],
    )
    r = dict(daily_returns(w, cfg=cfg90, t_ms=T)[0])
    assert r[230] == D("0.001") and r[231] == D("0.0005")


def test_F5_AC1_a_later_account_value_is_never_used_for_an_earlier_event(cfg90: Config) -> None:
    fills = round_trip_fills(220 * DAY + H, H, sz=10, px=100, exit_px=101)
    w = wallet(
        fills=fills,
        portfolios=[portfolio(W.FETCHED, perpAllTime=window([(100 * DAY, 10_000), (290 * DAY, 10_000_000)]))],
        clearinghouse=[clearinghouse(W.FETCHED, 10_000_000)],
        candles_1h={"BTC": flat_candles("BTC", 100, T - 100 * DAY, T)},
    )
    m = compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert close(m.eff_leverage_median, 1000 / 10_000)  # not 1000 / 10,000,000
    assert dict(daily_returns(w, cfg=cfg90, t_ms=T)[0])[220] == D("0.001")


def test_F5_AC1_events_with_no_prior_account_value_are_excluded_not_valued_later(cfg90: Config) -> None:
    early = round_trip_fills(220 * DAY + H, H, sz=10, px=100, exit_px=101)  # before the first AV point
    late = round_trip_fills(260 * DAY + H, H, sz=10, px=100, exit_px=101)
    w = wallet(
        fills=early + late,
        portfolios=[portfolio(W.FETCHED, perpAllTime=window([(int(250.5 * DAY), 10_000)]))],
        clearinghouse=[clearinghouse(W.FETCHED, 10_000)],
        candles_1h={"BTC": flat_candles("BTC", 100, T - 100 * DAY, T)},
    )
    recs = trip_records(w, cfg=cfg90, t_ms=T)
    assert [r.av_at_open for r in recs] == [None, D(10_000)]
    m = compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert close(m.executable_share, 1.0)  # 30 of 30: the excluded open is out of numerator and denominator
    rets, res = daily_returns(w, cfg=cfg90, t_ms=T)
    assert [d for d, _ in rets] == list(range(251, 300))  # days whose previous day-end has an AV point
    assert res.fill_days == 49


# --- edge wallets ----------------------------------------------------------------------------------------------------
def test_F5_AC1_no_fills_no_inputs_gives_a_safe_empty_metric_set(cfg90: Config) -> None:
    m = compute_metrics(wallet(), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.n_rt == 0 and m.t_days == 0 and m.pos_blocks == 0
    for name in ("sr_d", "dsr_prob", "profit_factor", "median_hold_min", "top_trade_share", "maker_share", "copy_mean_r"):
        assert getattr(m, name) is None, name


def test_F5_AC1_constant_zero_returns_have_no_sharpe(cfg90: Config) -> None:
    w = wallet(portfolios=[portfolio(W.FETCHED, perpAllTime=window([(100 * DAY, 10_000)]))], fills_fetched_ms=W.FETCHED)
    m = compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.t_days == 90 and m.sr_d is None and m.dsr_prob is None  # sd = 0: never a division by zero


def test_F5_AC1_M4_profit_factor_is_capped_at_ten(cfg90: Config) -> None:
    w = wallet(fills=round_trip_fills(220 * DAY, H, sz=10, px=100, exit_px=150))  # a single winner, no losses
    assert compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS).profit_factor == D(10)
    huge = wallet(fills=round_trip_fills(220 * DAY, H, sz=10, px=100, exit_px=150) + round_trip_fills(221 * DAY, H, sz=1, px=100, exit_px="99.99"))
    assert compute_metrics(huge, cfg=cfg90, t_ms=T, costs=ZERO_COSTS).profit_factor == D(10)


def test_F5_AC1_M11_M12_are_undefined_when_total_pnl_is_not_positive(cfg90: Config) -> None:
    w = wallet(fills=round_trip_fills(220 * DAY, H, sz=10, px=100, exit_px=90))
    m = compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.top_trade_share is None and m.top_asset_share is None  # G9 fails closed on None


def test_F5_AC1_M13_all_maker_wallet_has_maker_share_one(cfg90: Config) -> None:
    w = wallet(fills=round_trip_fills(220 * DAY, H, sz=10, px=100, exit_px=101, crossed=False))
    assert compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS).maker_share == D(1)


def test_F5_AC1_fills_older_than_the_window_are_not_counted(cfg90: Config) -> None:
    old = round_trip_fills(150 * DAY, H, sz=10, px=100, exit_px=101)
    new = round_trip_fills(250 * DAY, H, sz=10, px=100, exit_px=101)
    assert compute_metrics(wallet(fills=old + new), cfg=cfg90, t_ms=T, costs=ZERO_COSTS).n_rt == 1


def test_F5_AC1_window_days_comes_from_config(cfg90: Config, cfg_default: Config) -> None:
    old = round_trip_fills(150 * DAY, H, sz=10, px=100, exit_px=101)
    w = wallet(fills=old)
    assert compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS).n_rt == 0
    assert compute_metrics(w, cfg=cfg_default, t_ms=T, costs=ZERO_COSTS).n_rt == 1  # 180-day window reaches day 120


def test_F5_AC1_M10_median_hold_of_an_even_count_is_the_mean_of_the_middle_two(cfg90: Config) -> None:
    fills = []
    for i, hold in enumerate([10, 20, 30, 50]):
        fills += round_trip_fills(220 * DAY + i * H * 3, hold * M, sz=1, px=100, exit_px=101)
    assert compute_metrics(wallet(fills=fills), cfg=cfg90, t_ms=T, costs=ZERO_COSTS).median_hold_min == D(25)


def test_F5_AC1_money_fields_are_decimal_never_float(cfg90: Config) -> None:
    h1_metrics = h1m(cfg90)
    for name in ("median_hold_min", "account_value", "profit_factor", "sr_d", "max_dd", "maker_share", "copy_mean_r"):
        assert isinstance(getattr(h1_metrics, name), Decimal), name


def test_F5_AC1_a_repeated_fill_does_not_double_count(cfg90: Config) -> None:
    fills = W.h1_fills()
    base = compute_metrics(W.h1(), cfg=cfg90, t_ms=T, costs=PAPER_COSTS)
    dup = replace(W.h1(), fills=(*fills, *fills[2:6]))
    assert compute_metrics(dup, cfg=cfg90, t_ms=T, costs=PAPER_COSTS) == base


def test_F5_AC1_a_single_fill_with_time_zero_and_unicode_coin_does_not_crash(cfg90: Config) -> None:
    w = wallet(fills=[fill(0, "日本", "B", 1, 100, 0), fill(1, "\u0000", "A", 1, 100, 0)])
    assert compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS).n_rt == 0


@given(
    st.lists(
        st.tuples(st.integers(210 * DAY + 1, 269 * DAY + 3 * H).filter(lambda t: t % DAY != 0), st.integers(-10_000, 10_000)),
        max_size=25,
        unique_by=lambda p: p[0],
    )
)
@settings(max_examples=60)
def test_F5_AC5_property_all_time_pnl_points_never_move_sr_or_T(points: list[tuple[int, int]]) -> None:
    """Edge-hypothesis 10.7 test 14: adding or removing perpAllTime points between daily-resolution days changes nothing."""
    cfg = _CFG[0]
    base = compute_metrics(W.wm(), cfg=cfg, t_ms=T, costs=ZERO_COSTS)
    more = compute_metrics(W.wm(extra_alltime_pnl=tuple(points)), cfg=cfg, t_ms=T, costs=ZERO_COSTS)
    assert (more.sr_d, more.t_days, more.skew, more.kurt) == (base.sr_d, base.t_days, base.skew, base.kurt)


_CFG: list[Config] = []


@pytest.fixture(autouse=True, scope="module")
def _keep_cfg(cfg90: Config) -> None:
    _CFG[:] = [cfg90]
