"""F5 round 2: copy replay M14 (feeds G10 and score component 2) at its exact fee, TP-once, stop-boundary and ATR edges.

Flat candles at 100 with a 1% spread give ATR 2, so at the default config the stop distance is 4 (stop 96 for a long,
104 for a short) and the first take-profit is 2R = 108. Costs are FixedCosts so every number is exact.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from copytrade.core.config import Config
from copytrade.scoring.metrics import compute_metrics, copy_replay_r
from copytrade.scoring.models import Candle, WalletInputs
from tests.scoring import wallets as W
from tests.scoring.helpers import (
    DAY,
    H,
    M,
    ZERO_COSTS,
    FixedCosts,
    clearinghouse,
    flat_candles,
    portfolio,
    round_trip_fills,
    wallet,
    window,
    with_bar,
)

pytestmark = pytest.mark.unit
D = Decimal
T = W.T
OPEN = 250 * DAY + 1 * H  # an hour boundary well inside the 90-day window


def replay_wallet(
    *, exit_px: int | str, direction: int = 1, hold_h: int = 2, bars: tuple[Candle, ...] | None = None
) -> WalletInputs:
    return wallet(
        fills=round_trip_fills(OPEN, hold_h * H, sz=10, px=100, exit_px=exit_px, direction=direction),
        fills_fetched_ms=W.FETCHED,
        candles_1h={"BTC": bars if bars is not None else flat_candles("BTC", 100, T - 100 * DAY, T)},
        candles_fetched_ms=W.FETCHED,
    )


def r_of(w: WalletInputs, cfg: Config, costs: FixedCosts = ZERO_COSTS) -> list[Decimal]:
    return list(copy_replay_r(w, cfg=cfg, t_ms=T, costs=costs))


# --- taker fee: exact amount on the entry and the exit leg -----------------------------------------------------------
def test_F5_AC1_M14_long_pays_the_taker_fee_on_the_entry_and_the_exit_notional(cfg90: Config) -> None:
    # entry 100, exit 102, taker 10 bps: (2 - (100 + 102) x 0.001) / 4
    assert r_of(replay_wallet(exit_px=102), cfg90, FixedCosts(taker=D(10))) == [D("0.4495")]


def test_F5_AC1_M14_short_pays_the_taker_fee_on_the_entry_and_the_exit_notional(cfg90: Config) -> None:
    # short 100 -> 98: (2 - (100 + 98) x 0.001) / 4
    assert r_of(replay_wallet(exit_px=98, direction=-1), cfg90, FixedCosts(taker=D(10))) == [D("0.4505")]


def test_F5_AC1_M14_a_flat_trade_costs_exactly_both_fees(cfg90: Config) -> None:
    assert r_of(replay_wallet(exit_px=100), cfg90, FixedCosts(taker=D(10))) == [D("-0.05")]  # -(200 x 0.001) / 4


# --- take-profit fires once ------------------------------------------------------------------------------------------
def test_F5_AC1_M14_a_target_touched_on_two_bars_is_taken_once(cfg90: Config) -> None:
    bars = flat_candles("BTC", 100, T - 100 * DAY, T)
    bars = with_bar(bars, OPEN, hi=108, lo=99)
    bars = with_bar(bars, OPEN + H, hi=110, lo=99)
    # half at 2R (+2), the other half at the leader's close (100, 0 R): 1.0. A second fill would give 2.0.
    assert r_of(replay_wallet(exit_px=100, hold_h=3, bars=bars), cfg90) == [D(1)]


def test_F5_AC1_M14_a_target_touched_on_three_bars_is_still_taken_once(cfg90: Config) -> None:
    bars = flat_candles("BTC", 100, T - 100 * DAY, T)
    for k in range(3):
        bars = with_bar(bars, OPEN + k * H, hi=108, lo=99)
    assert r_of(replay_wallet(exit_px=102, hold_h=4, bars=bars), cfg90) == [D("1.25")]  # 0.5 x 2 + 0.5 x 0.5


# --- stop touched exactly at the bar's boundary is a stop ------------------------------------------------------------
def test_F5_AC1_M14_a_long_low_exactly_at_the_stop_is_stopped(cfg90: Config) -> None:
    bars = with_bar(flat_candles("BTC", 100, T - 100 * DAY, T), OPEN, hi=101, lo=96)
    assert r_of(replay_wallet(exit_px=100, bars=bars), cfg90) == [D(-1)]


def test_F5_AC1_M14_a_long_low_one_tick_above_the_stop_is_not_stopped(cfg90: Config) -> None:
    bars = with_bar(flat_candles("BTC", 100, T - 100 * DAY, T), OPEN, hi=101, lo="96.01")
    assert r_of(replay_wallet(exit_px=100, bars=bars), cfg90) == [D(0)]


def test_F5_AC1_M14_a_short_high_exactly_at_the_stop_is_stopped(cfg90: Config) -> None:
    bars = with_bar(flat_candles("BTC", 100, T - 100 * DAY, T), OPEN, hi=104, lo=99)
    assert r_of(replay_wallet(exit_px=100, direction=-1, bars=bars), cfg90) == [D(-1)]


def test_F5_AC1_M14_a_short_high_one_tick_below_the_stop_is_not_stopped(cfg90: Config) -> None:
    bars = with_bar(flat_candles("BTC", 100, T - 100 * DAY, T), OPEN, hi="103.99", lo=99)
    assert r_of(replay_wallet(exit_px=100, direction=-1, bars=bars), cfg90) == [D(0)]


# --- the ATR needs atr_period + 1 closed bars ------------------------------------------------------------------------
@pytest.mark.parametrize(("n_bars", "buildable"), [(13, False), (14, False), (15, True), (16, True)])
def test_F5_AC1_M14_the_stop_needs_fifteen_closed_bars_at_atr_period_14(cfg90: Config, n_bars: int, buildable: bool) -> None:
    bars = flat_candles("BTC", 100, OPEN - n_bars * H, OPEN + 3 * H)  # n_bars close before the entry, then the trade
    got = r_of(replay_wallet(exit_px=102, bars=bars), cfg90)
    assert got == ([D("0.5")] if buildable else [])


def test_F5_AC1_M14_no_candles_for_the_coin_omits_the_trip(cfg90: Config) -> None:
    w = wallet(
        fills=round_trip_fills(OPEN, 2 * H, sz=10, px=100, exit_px=102),
        fills_fetched_ms=W.FETCHED,
        candles_1h={"ETH": flat_candles("ETH", 100, T - 100 * DAY, T)},
        candles_fetched_ms=W.FETCHED,
    )
    assert r_of(w, cfg90) == []


# --- a flat market has ATR 0: no stop, no crash ----------------------------------------------------------------------
def test_F5_AC1_M14_zero_atr_gives_no_replay_and_no_division_by_zero(cfg90: Config) -> None:
    bars = flat_candles("BTC", 100, T - 100 * DAY, T, spread="0")
    assert r_of(replay_wallet(exit_px=102, bars=bars), cfg90) == []


def test_F5_AC1_M14_zero_atr_leaves_copy_mean_r_and_executable_share_undefined_without_crashing(cfg90: Config) -> None:
    bars = flat_candles("BTC", 100, T - 100 * DAY, T, spread="0")
    w = wallet(
        fills=round_trip_fills(OPEN, 2 * H, sz=10, px=100, exit_px=102),
        fills_fetched_ms=W.FETCHED,
        portfolios=[portfolio(W.FETCHED, perpAllTime=window([(100 * DAY, 10_000)], [(100 * DAY, 0)]))],
        clearinghouse=[clearinghouse(W.FETCHED, 10_000)],
        candles_1h={"BTC": bars},
        candles_fetched_ms=W.FETCHED,
    )
    m = compute_metrics(w, cfg=cfg90, t_ms=T, costs=ZERO_COSTS)
    assert m.n_rt == 1 and m.copy_mean_r is None and m.executable_share is None


# --- point-in-time: a bar counts only once it has closed --------------------------------------------------------------------
def _bar(open_ms: int, close_ms: int, *, hi: int = 101, lo: int = 99) -> Candle:
    return Candle(open_ms=open_ms, close_ms=close_ms, o=D(100), hi=D(hi), lo=D(lo), c=D(100))


def test_F5_AC1_M14_a_bar_that_closes_exactly_at_the_entry_is_not_known_before_it(cfg90: Config) -> None:
    pre = flat_candles("BTC", 100, OPEN - 14 * H, OPEN)  # 14 bars closed before the entry
    trade = flat_candles("BTC", 100, OPEN, OPEN + 3 * H)
    assert r_of(replay_wallet(exit_px=102, bars=(*pre, *trade)), cfg90) == []  # 14 known bars: no ATR
    edge = _bar(OPEN - 1, OPEN)  # closes at the entry ms itself: still not before it
    assert r_of(replay_wallet(exit_px=102, bars=(*pre, edge, *trade)), cfg90) == []
    early = _bar(OPEN - 2, OPEN - 1)  # closes one ms before the entry: known
    assert r_of(replay_wallet(exit_px=102, bars=(*pre, early, *trade)), cfg90) == [D("0.5")]


def test_F5_AC1_M14_a_bar_that_closes_after_t_never_stops_a_trade(cfg90: Config) -> None:
    open_ms = T - 2 * H
    w = wallet(
        fills=round_trip_fills(open_ms, 2 * H - 10 * M, sz=10, px=100, exit_px=102),
        fills_fetched_ms=W.FETCHED,
        candles_1h={"BTC": (*flat_candles("BTC", 100, T - 100 * DAY, T), _bar(T - 30 * M, T + 30 * M, lo=90))},
        candles_fetched_ms=W.FETCHED,
    )
    assert r_of(w, cfg90) == [D("0.5")]  # the bar closes after t: it is not used, so the leader's close (+2) stands
