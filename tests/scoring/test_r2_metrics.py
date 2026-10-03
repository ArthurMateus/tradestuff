"""F5 round 2: metric edges that the first round left unpinned (F5.AC1).

Window edges, the oldest score block, drawdown maximum, executable share at its boundary and cap, the 30-day recent
window, non-positive account values, the source-selection gap edges and look-ahead guards. All wallets are built from
the fill, snapshot and candle records; the expected numbers are derived in the comments.
"""

from __future__ import annotations

import statistics
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from copytrade.core.config import Config
from copytrade.scoring.metrics import compute_metrics, daily_returns, trip_records
from copytrade.scoring.models import Fill, WalletInputs
from tests.scoring import wallets as W
from tests.scoring.helpers import (
    DAY,
    H,
    ZERO_COSTS,
    clearinghouse,
    fill,
    flat_candles,
    make_cfg,
    own,
    portfolio,
    round_trip_fills,
    wallet,
    window,
)

pytestmark = pytest.mark.unit
D = Decimal
T = W.T
START = T - 90 * DAY  # the 90-day window's first millisecond (config override scoring.window_days = 90)


def wallet_with(
    fills: list[Fill],
    *,
    av: int | str = 10_000,
    pnl: list[tuple[int, int]] | None = None,
    extra_windows: dict[str, object] | None = None,
    **kw: object,
) -> WalletInputs:
    windows = {"perpAllTime": window([(100 * DAY, av)], pnl if pnl is not None else [(100 * DAY, 0)])}
    windows.update(extra_windows or {})
    base: dict[str, object] = {
        "fills": fills,
        "fills_fetched_ms": W.FETCHED,
        "portfolios": [portfolio(W.FETCHED, **windows)],  # type: ignore[arg-type]
        "clearinghouse": [clearinghouse(W.FETCHED, 10_000)],
        "candles_1h": {"BTC": flat_candles("BTC", 100, T - 100 * DAY, T)},
        "candles_fetched_ms": W.FETCHED,
    }
    base.update(kw)
    return wallet(**base)  # type: ignore[arg-type]


# --- window edges: [t - window_days, t], both ends inclusive ---------------------------------------------------------
def test_F5_AC1_window_fills_at_exactly_start_and_exactly_t_are_in_and_one_ms_outside_are_out(cfg90: Config) -> None:
    fills = [
        fill(START - 1, "BTC", "B", 1, 100, 0),
        fill(START, "ETH", "B", 1, 100, 0),
        fill(T, "SOL", "B", 1, 100, 0),
        fill(T + 1, "XRP", "B", 1, 100, 0),
    ]
    m = compute_metrics(wallet_with(fills), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.fill_span_days == D(90)  # ETH at START ... SOL at T, exactly
    assert m.maker_share == D(0)  # (all crossed) and defined, so the two inside fills are counted


def test_F5_AC1_window_a_fill_at_start_is_counted_for_the_maker_share(cfg90: Config) -> None:
    fills = [fill(START, "ETH", "B", 1, 100, 0, crossed=False), fill(START + H, "SOL", "B", 3, 100, 0)]
    m = compute_metrics(wallet_with(fills), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.maker_share == D("0.25")


def test_F5_AC1_window_a_fill_at_t_is_counted_for_the_maker_share(cfg90: Config) -> None:
    fills = [fill(START + H, "ETH", "B", 3, 100, 0), fill(T, "SOL", "B", 1, 100, 0, crossed=False)]
    m = compute_metrics(wallet_with(fills), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.maker_share == D("0.25")


# --- M8: the oldest block counts ---------------------------------------------------------------------------------------
def test_F5_AC1_M8_the_oldest_block_is_counted_when_it_is_the_only_positive_one(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path, **{"scoring.window_days": 90, "gate.n_blocks": 3, "gate.min_positive_blocks": 2})
    # blocks of 30 days back from T: day 215 is in block 3 (days 210..239), the oldest of three
    fills = round_trip_fills(215 * DAY + H, 2 * H, sz=10, px=100, exit_px=102)
    m = compute_metrics(wallet_with(fills), cfg=cfg, t_ms=T, costs=ZERO_COSTS)
    assert m.pos_blocks == 1


def test_F5_AC1_M8_the_newest_block_is_counted_too(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path, **{"scoring.window_days": 90, "gate.n_blocks": 3, "gate.min_positive_blocks": 2})
    fills = round_trip_fills(295 * DAY + H, 2 * H, sz=10, px=100, exit_px=102)
    m = compute_metrics(wallet_with(fills), cfg=cfg, t_ms=T, costs=ZERO_COSTS)
    assert m.pos_blocks == 1


# --- M9: max drawdown is the larger of realised and mark-to-market ------------------------------------------------------
def test_F5_AC1_M9_max_dd_takes_the_realised_drawdown_when_it_is_the_larger(cfg90: Config) -> None:
    # one -1000 trip on AV 10000: realised curve 10000 -> 9000 = 0.1. The perpAllTime pnl line is flat: mtm 0.
    fills = [fill(250 * DAY + H, "BTC", "B", 10, 100, 0), fill(250 * DAY + 3 * H, "BTC", "A", 10, 0, 10, pnl=-1000)]
    m = compute_metrics(wallet_with(fills, pnl=[(100 * DAY, 0), (299 * DAY, 0)]), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.max_dd_realised == D("0.1") and m.max_dd_mtm == D(0)
    assert m.max_dd == D("0.1")


def test_F5_AC1_M9_max_dd_takes_the_mtm_drawdown_when_it_is_the_larger(cfg90: Config) -> None:
    fills = round_trip_fills(250 * DAY + H, 2 * H, sz=10, px=100, exit_px=101)  # +10, no realised drawdown
    m = compute_metrics(wallet_with(fills, pnl=[(100 * DAY, 0), (200 * DAY, 1000), (250 * DAY, 0)]), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.max_dd_realised == D(0) and m.max_dd_mtm == D(1000) / D(11_000)
    assert m.max_dd == m.max_dd_mtm


# --- M16: executable share at exactly the minimum order, and the risk cap ---------------------------------------------
def _m16(cfg: Config, *, av: int, spread: str = "0.01", sz: int = 10) -> Decimal | None:
    fills = round_trip_fills(250 * DAY + H, 2 * H, sz=sz, px=100, exit_px=100)
    bars = flat_candles("BTC", 100, T - 100 * DAY, T, spread=spread)
    w = wallet_with(fills, av=av, candles_1h={"BTC": bars})
    return compute_metrics(w, cfg=cfg, t_ms=T, costs=ZERO_COSTS).executable_share


def _min30(tmp_path: Path) -> Config:
    return make_cfg(tmp_path, **{"scoring.window_days": 90, "sizing.min_order_usd": 30})


def test_F5_AC1_M16_a_mirrored_order_of_exactly_the_minimum_is_executable(tmp_path: Path) -> None:
    # mirrored = 10 x 100 / 10000 x 300 = 30.00 = min_order_usd; the risk cap 1.5 x 100 / 4 = 37.5 does not bind
    assert _m16(_min30(tmp_path), av=10_000) == D(1)


def test_F5_AC1_M16_a_mirrored_order_just_below_the_minimum_is_not_executable(tmp_path: Path) -> None:
    assert _m16(_min30(tmp_path), av=10_001) == D(0)  # 29.997


def test_F5_AC1_M16_the_default_minimum_is_ten_dollars(cfg90: Config) -> None:
    assert cfg90["sizing.min_order_usd"] == D(10)
    assert _m16(cfg90, av=10_000, sz=3) == D(0)  # mirrored 3 x 100 / 10000 x 300 = $9.00
    assert _m16(cfg90, av=10_000, sz=4) == D(1)  # $12.00


def test_F5_AC1_M16_the_risk_cap_can_push_a_large_mirrored_order_below_the_minimum(cfg90: Config) -> None:
    # spread 0.05 -> ATR 10, stop distance 20; cap = 0.005 x 300 x 100 / 20 = 7.5 < 10 although the mirrored order is $300
    assert _m16(cfg90, av=1000, spread="0.05") == D(0)


def test_F5_AC1_M16_a_risk_cap_of_exactly_the_minimum_is_executable(cfg90: Config) -> None:
    # spread 0.0375 -> ATR 7.5, stop distance 15; cap = 1.5 x 100 / 15 = 10.00 exactly; mirrored $300
    assert _m16(cfg90, av=1000, spread="0.0375") == D(1)


def test_F5_AC1_M16_the_cap_leaves_a_small_mirrored_order_alone(cfg90: Config) -> None:
    assert _m16(cfg90, av=10_000) == D(1)  # mirrored $30, cap 37.5: $30 >= $10


# --- M17: the recent window is the last 30 whole days ----------------------------------------------------------------
def test_F5_AC1_M17_recent_window_starts_at_day_270_inclusive_and_excludes_day_269(cfg90: Config) -> None:
    fills: list[Fill] = []
    exits = {}
    for d in range(270, 300):
        exits[d] = 101 if d % 3 else D("99.5")  # +10 or -5 on AV 10000
        fills += round_trip_fills(d * DAY + H, 2 * H, sz=10, px=100, exit_px=exits[d])
    fills += round_trip_fills(269 * DAY + H, 2 * H, sz=10, px=100, exit_px=120)  # +200: only a wrong window sees it
    m = compute_metrics(wallet_with(fills), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    rets = [float((10 * (exits[d] - 100)) / 10_000) for d in range(270, 300)]
    expected = statistics.mean(rets) / statistics.stdev(rets) * 30 / (30 + 30)
    assert m.recent_sr is not None and abs(float(m.recent_sr) - expected) <= 1e-9


def test_F5_AC1_M17_a_day_270_return_is_used_and_a_day_269_return_is_not(cfg90: Config) -> None:
    def build(day: int) -> WalletInputs:  # a single outlier day in an otherwise 0/+10 recent window
        f: list[Fill] = []
        for d in range(271, 300):
            f += round_trip_fills(d * DAY + H, 2 * H, sz=10, px=100, exit_px=101 if d % 2 else 100)
        return wallet_with(f + round_trip_fills(day * DAY + H, 2 * H, sz=10, px=100, exit_px=150))

    on_270 = compute_metrics(build(270), cfg=cfg90, t_ms=T, costs=ZERO_COSTS).recent_sr
    on_269 = compute_metrics(build(269), cfg=cfg90, t_ms=T, costs=ZERO_COSTS).recent_sr
    assert on_270 is not None and on_269 is not None and on_270 != on_269
    # day 269 is outside the window: the recent series is then exactly the 29 alternating days plus a zero day 270
    rets = [0.0] + [float((10 * (1 if d % 2 else 0)) / 10_000) for d in range(271, 300)]
    assert abs(float(on_269) - statistics.mean(rets) / statistics.stdev(rets) * 30 / 60) <= 1e-9


# --- non-positive account values never divide -------------------------------------------------------------------------
@pytest.mark.parametrize("av", [0, -5])
def test_F5_AC1_daily_returns_skip_days_whose_previous_account_value_is_not_positive(cfg90: Config, av: int) -> None:
    fills = round_trip_fills(250 * DAY + H, 2 * H, sz=10, px=100, exit_px=101)
    rets, resolution = daily_returns(wallet_with(fills, av=av), cfg=cfg90, t_ms=T)
    assert rets == () and (resolution.own_hourly_days, resolution.perp_month_days, resolution.fill_days) == (0, 0, 0)


@pytest.mark.parametrize("av", [0, -5])
def test_F5_AC1_zero_or_negative_account_value_gives_undefined_metrics_not_a_crash(cfg90: Config, av: int) -> None:
    fills = round_trip_fills(250 * DAY + H, 2 * H, sz=10, px=100, exit_px=101)
    m = compute_metrics(wallet_with(fills, av=av), cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.t_days == 0 and m.sr_d is None and m.recent_sr is None and m.dsr_prob is None
    assert m.eff_leverage_median is None and m.executable_share is None


@pytest.mark.parametrize("av", [0, -5])
def test_F5_AC1_BU8_a_non_positive_clearinghouse_account_value_gives_no_open_loss_fraction(cfg90: Config, av: int) -> None:
    fills = round_trip_fills(250 * DAY + H, 2 * H, sz=10, px=100, exit_px=101)
    w = wallet_with(fills, clearinghouse=[clearinghouse(W.FETCHED, av, [("BTC", -50)])])
    m = compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.open_loss_fraction is None and m.account_value == D(av)


def test_F5_AC1_BU8_a_positive_clearinghouse_account_value_gives_the_loss_over_it(cfg90: Config) -> None:
    fills = round_trip_fills(250 * DAY + H, 2 * H, sz=10, px=100, exit_px=101)
    w = wallet_with(fills, clearinghouse=[clearinghouse(W.FETCHED, 1000, [("BTC", -50)])])
    assert compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS).open_loss_fraction == D("0.05")


# --- source selection: a boundary point at exactly the gap still stands for the boundary ------------------------------
DAY_D = 280  # the day under test


def _source_wallet(kind: str, *, start_gap: int, end_gap: int) -> WalletInputs:
    start, end = DAY_D * DAY, (DAY_D + 1) * DAY
    if kind == "own":
        return wallet_with([], own_snapshots=[own(start - start_gap, 10_000, 0), own(end - end_gap, 10_000, 50)])
    month = window([(100 * DAY, 10_000)], [(start - start_gap, 0), (end - end_gap, 50)])
    return wallet_with([], extra_windows={"perpMonth": month})


@pytest.mark.parametrize(
    ("kind", "gap"), [("own", H), ("month", 6 * H)]
)
def test_F5_AC1_gap_exactly_at_the_limit_at_the_start_boundary_still_uses_the_finer_source(cfg90: Config, kind: str, gap: int) -> None:
    rets, res = daily_returns(_source_wallet(kind, start_gap=gap, end_gap=0), cfg=cfg90, t_ms=T)
    assert dict(rets)[DAY_D] == D("0.005")  # 50 / AV 10000
    assert (res.own_hourly_days, res.perp_month_days) == ((1, 0) if kind == "own" else (0, 1))


@pytest.mark.parametrize(
    ("kind", "gap"), [("own", H), ("month", 6 * H)]
)
def test_F5_AC1_gap_exactly_at_the_limit_at_the_end_boundary_still_uses_the_finer_source(cfg90: Config, kind: str, gap: int) -> None:
    rets, res = daily_returns(_source_wallet(kind, start_gap=0, end_gap=gap), cfg=cfg90, t_ms=T)
    assert dict(rets)[DAY_D] == D("0.005")
    assert (res.own_hourly_days, res.perp_month_days) == ((1, 0) if kind == "own" else (0, 1))


@pytest.mark.parametrize(("kind", "gap"), [("own", H + 1), ("month", 6 * H + 1)])
@pytest.mark.parametrize("where", ["start", "end"])
def test_F5_AC1_gap_one_ms_over_the_limit_falls_back_to_the_next_source(cfg90: Config, kind: str, gap: int, where: str) -> None:
    w = _source_wallet(kind, start_gap=gap if where == "start" else 0, end_gap=gap if where == "end" else 0)
    rets, res = daily_returns(w, cfg=cfg90, t_ms=T)
    assert dict(rets)[DAY_D] == D(0)  # no fills that day: realised P&L is zero
    assert res.own_hourly_days == 0 and res.perp_month_days == 0


def test_F5_AC1_an_own_gap_over_an_hour_falls_back_to_the_month_source_when_it_covers_the_day(cfg90: Config) -> None:
    start, end = DAY_D * DAY, (DAY_D + 1) * DAY
    w = wallet_with(
        [],
        own_snapshots=[own(start - H - 1, 10_000, 0), own(end, 10_000, 500)],
        extra_windows={"perpMonth": window([(100 * DAY, 10_000)], [(start - 2 * H, 0), (end - 5 * H, 30)])},
    )
    rets, res = daily_returns(w, cfg=cfg90, t_ms=T)
    assert dict(rets)[DAY_D] == D("0.003") and (res.own_hourly_days, res.perp_month_days) == (0, 1)


# --- look-ahead guards ------------------------------------------------------------------------------------------------
def _lookahead_base() -> WalletInputs:
    fills = round_trip_fills(250 * DAY + H, 2 * H, sz=10, px=100, exit_px=101) + round_trip_fills(
        260 * DAY + H, 2 * H, sz=10, px=100, exit_px=99
    )
    return wallet_with(
        fills,
        pnl=[(100 * DAY, 0), (255 * DAY, 10), (299 * DAY, -20)],
        own_snapshots=[own(290 * DAY, 10_000, 0), own(299 * DAY, 10_000, 5)],
        extra_windows={"perpMonth": window([(270 * DAY, 10_000)], [(270 * DAY, 0), (289 * DAY, 4)])},
    )


def test_F5_AC1_own_snapshots_after_t_do_not_change_any_metric(cfg90: Config) -> None:
    base = _lookahead_base()
    future = replace(base, own_snapshots=(*base.own_snapshots, own(T + 1, 1, 10**9), own(T + DAY, 1, -(10**9))))
    assert compute_metrics(future, cfg=cfg90, t_ms=T, costs=ZERO_COSTS) == compute_metrics(base, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert daily_returns(future, cfg=cfg90, t_ms=T) == daily_returns(base, cfg=cfg90, t_ms=T)


def test_F5_AC1_portfolio_window_points_after_t_do_not_change_any_metric(cfg90: Config) -> None:
    base = _lookahead_base()
    snap = base.portfolios[0]
    windows = {
        name: replace(
            win,
            account_value_history=(*win.account_value_history, (T + 1, D(1)), (T + 2 * DAY, D(10**9))),
            pnl_history=(*win.pnl_history, (T + 1, D(-(10**9))), (T + 2 * DAY, D(10**9))),
        )
        for name, win in snap.windows.items()
    }
    future = replace(base, portfolios=(replace(snap, windows=windows),))
    assert compute_metrics(future, cfg=cfg90, t_ms=T, costs=ZERO_COSTS) == compute_metrics(base, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert daily_returns(future, cfg=cfg90, t_ms=T) == daily_returns(base, cfg=cfg90, t_ms=T)


def test_F5_AC1_a_portfolio_or_clearinghouse_snapshot_fetched_after_t_is_never_used(cfg90: Config) -> None:
    base = _lookahead_base()
    later = portfolio(T + 1, perpAllTime=window([(100 * DAY, 1)], [(100 * DAY, 10**6)]))
    future = replace(
        base,
        portfolios=(*base.portfolios, later),
        clearinghouse=(*base.clearinghouse, clearinghouse(T + 1, 1, [("BTC", -1)])),
    )
    assert compute_metrics(future, cfg=cfg90, t_ms=T, costs=ZERO_COSTS) == compute_metrics(base, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)


def test_F5_AC1_a_snapshot_fetched_exactly_at_t_is_used(cfg90: Config) -> None:
    base = _lookahead_base()
    at_t = replace(base, clearinghouse=(*base.clearinghouse, clearinghouse(T, 777, [])))
    assert compute_metrics(at_t, cfg=cfg90, t_ms=T, costs=ZERO_COSTS).account_value == D(777)


def test_F5_AC1_trip_records_ignore_account_value_points_after_t(cfg90: Config) -> None:
    base = _lookahead_base()
    snap = base.portfolios[0]
    win = snap.windows["perpAllTime"]
    future = replace(base, portfolios=(replace(snap, windows={"perpAllTime": replace(win, account_value_history=((100 * DAY, D(10_000)), (T + 1, D(1))))}),))
    assert trip_records(future, cfg=cfg90, t_ms=T) == trip_records(base, cfg=cfg90, t_ms=T)
