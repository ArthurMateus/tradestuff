"""Hand-built fixture wallets for F5.AC1 / AC3 / AC5 / AC6 / AC7.

Every number is chosen so that the expected metric can be computed by hand; the derivations are in the comments
and in docs/sdlc/copytrade-v1/05-test-plan-F5.md. Cycle time is T = day 300; the window is 90 days (config override).
"""

from __future__ import annotations

from decimal import Decimal

from copytrade.scoring.models import Candle, Fill, PortfolioSnapshot, WalletInputs
from tests.scoring.helpers import (
    DAY,
    H,
    M,
    clearinghouse,
    fill,
    flat_candles,
    own,
    portfolio,
    round_trip_fills,
    wallet,
    window,
    with_bar,
)

D = Decimal
T = 300 * DAY
WINDOW_DAYS = 90
FETCHED = T - 10 * M  # every input fetched 10 minutes before the cycle
HIGH_WALLET = "0xaaa0000000000000000000000000000000000001"


def _d(day: float, extra_ms: int = 0) -> int:
    return int(day * DAY) + extra_ms


def h1_fills() -> list[Fill]:
    """Wallet H1. Seven closed round trips (BTC, ETH), one open SOL trip, and four fills that must be ignored.

    Account value points (perpAllTime): (day 100, 10000) and (day 230.5, 20000).
    """
    f: list[Fill] = []
    # ignored: a pre-existing ETH long (start 1, +1, then sold flat) at day 211; no P&L, no fee
    f.append(fill(_d(211), "ETH", "B", 1, 50, 1))
    f.append(fill(_d(211, M), "ETH", "A", 2, 50, 2))
    # T1 BTC long day 220 +1h, 100 -> 102, size 10, fees 0.4 each leg, hold 120 min. L = 20 - 0.8 = 19.2
    f.append(fill(_d(220, 1 * H), "BTC", "B", 10, 100, 0, fee="0.4"))
    f.append(fill(_d(220, 3 * H), "BTC", "A", 10, 102, 10, pnl=20, fee="0.4"))
    # T2 BTC long day 225: open 10 @100, add 10 @98 (while losing), reduce 8 @101 (40%), close 12 @103.
    #    avg after the add = 99, peak notional 20 x 99 = 1980, closedPnl 16 + 48 = 64, 4 fees of 0.5. L = 62
    f.append(fill(_d(225), "BTC", "B", 10, 100, 0, fee="0.5"))
    f.append(fill(_d(225, 10 * M), "BTC", "B", 10, 98, 10, fee="0.5"))
    f.append(fill(_d(225, 20 * M), "BTC", "A", 8, 101, 20, pnl=16, fee="0.5"))
    f.append(fill(_d(225, 2 * H), "BTC", "A", 12, 103, 12, pnl=48, fee="0.5"))
    # ignored: HIP-3 and spot fills
    f.append(fill(_d(226), "xyz:TSLA", "B", 1, 300, 0, fee="0.1"))
    f.append(fill(_d(227), "@107", "B", 1, 30, 0, fee="0.1"))
    # T3 ETH short day 235, both fills maker. 40 @50 -> 49, closedPnl 40, fees 0.8 each. L = 38.4. hold 360 min
    f.append(fill(_d(235), "ETH", "A", 40, 50, 0, fee="0.8", crossed=False))
    f.append(fill(_d(235, 6 * H), "ETH", "B", 40, 49, -40, pnl=40, fee="0.8", crossed=False))
    # T4 ETH long day 250: 10 @50 -> 48, closedPnl -20, fees 0.2 each. L = -20.4. hold 30 min
    f.append(fill(_d(250), "ETH", "B", 10, 50, 0, fee="0.2"))
    f.append(fill(_d(250, 30 * M), "ETH", "A", 10, 48, 10, pnl=-20, fee="0.2"))
    # T5 BTC long day 260 -> day 262: 30 @100 -> 97, closedPnl -90, fees 1.2 each. L = -92.4. hold 2880 min
    f.append(fill(_d(260), "BTC", "B", 30, 100, 0, fee="1.2"))
    f.append(fill(_d(262), "BTC", "A", 30, 97, 30, pnl=-90, fee="1.2"))
    # T6 BTC day 270: long 10 @100 (fee 0.4); flip at +1h: sell 25 @102 (closes 10, closedPnl 20, opens short 15,
    #    fee 1.0); short closed at +3h: buy 15 @101 (closedPnl 15, fee 0.5). L6a = 20-0.4-1.0 = 18.6, L6b = 15-0.5 = 14.5
    f.append(fill(_d(270), "BTC", "B", 10, 100, 0, fee="0.4"))
    f.append(fill(_d(270, 1 * H), "BTC", "A", 25, 102, 10, pnl=20, fee="1.0"))
    f.append(fill(_d(270, 3 * H), "BTC", "B", 15, 101, -15, pnl=15, fee="0.5"))
    # open SOL short (not a closed trip), fee 0.2
    f.append(fill(_d(290), "SOL", "A", 100, 20, 0, fee="0.2"))
    return f


def h1_portfolio() -> PortfolioSnapshot:
    av = [(_d(100), 10_000), (_d(230.5), 20_000)]
    pnl = [
        (_d(100), 0),
        (_d(220), 19),
        (_d(225), 60),
        (_d(240), 100),
        (_d(255), -200),
        (_d(262), -150),
        (_d(280), -100),
        (_d(299), -60),
    ]
    return portfolio(FETCHED, perpAllTime=window(av, pnl))


def h1_candles() -> dict[str, tuple[Candle, ...]]:
    return {
        "BTC": flat_candles("BTC", 100, T - 100 * DAY, T),
        "ETH": flat_candles("ETH", 50, T - 100 * DAY, T),
        "SOL": flat_candles("SOL", 20, T - 100 * DAY, T),
    }


def h1() -> WalletInputs:
    return wallet(
        HIGH_WALLET,
        fills=h1_fills(),
        fills_fetched_ms=FETCHED,
        portfolios=[h1_portfolio()],
        clearinghouse=[clearinghouse(FETCHED, 20_000, [("SOL", -500)])],
        candles_1h=h1_candles(),
        candles_fetched_ms=FETCHED,
        role="user",
    )


# --- W_R: copy replay vectors (open/close only, flat candles, zero cost) -------------------------------------------
R_DAY = 250 * DAY  # trips at hour boundaries on this day


def wr_fills() -> list[Fill]:
    f: list[Fill] = []
    f += round_trip_fills(R_DAY + 1 * H, 2 * H, sz=10, px=100, exit_px=102)  # a) +2% -> +0.5R
    f += round_trip_fills(R_DAY + 4 * H, 2 * H, sz=10, px=100, exit_px=98)  # b) -2% -> -0.5R
    f += round_trip_fills(R_DAY + 7 * H, 2 * H, sz=10, px=100, exit_px=99, direction=-1)  # c) short +1% -> +0.25R
    f += round_trip_fills(R_DAY + 10 * H, 3 * H, sz=10, px=100, exit_px=90)  # d) leader -10%, our stop hit first
    return f


def wr_candles() -> dict[str, tuple[Candle, ...]]:
    bars = flat_candles("BTC", 100, T - 100 * DAY, T)
    # d) the bar after entry trades down to 95 (stop at 96) and also up to 108.5 (2R take-profit): stop first
    bars = with_bar(bars, R_DAY + 10 * H, hi=D("108.5"), lo=95)
    return {"BTC": bars}


def wr() -> WalletInputs:
    return wallet(
        "0xbbb0000000000000000000000000000000000002",
        fills=wr_fills(),
        fills_fetched_ms=FETCHED,
        portfolios=[portfolio(FETCHED, perpAllTime=window([(_d(100), 10_000)], [(_d(100), 0)]))],
        clearinghouse=[clearinghouse(FETCHED, 10_000)],
        candles_1h=wr_candles(),
        candles_fetched_ms=FETCHED,
    )


# --- W_M: daily-return sources --------------------------------------------------------------------------------------
def wm(extra_alltime_pnl: tuple[tuple[int, int], ...] = ()) -> WalletInputs:
    """90 window days (210..299). Own hourly snapshots cover days 290..299 (+10 per even day, -4 per odd day),
    perpMonth covers days 270..289 (+3 on days divisible by 3, else -1), fills cover everything else with one
    +20 realised day at day 230 and one -30 day at day 240. AV is 10000 throughout."""
    own_pts = []
    cum = 0
    for d_ in range(290, 300):
        own_pts.append(own(_d(d_), 10_000, cum))
        cum += 10 if d_ % 2 == 0 else -4
    own_pts.append(own(_d(300), 10_000, cum))
    month_pnl: list[tuple[int, int]] = []
    cum = 0
    for d_ in range(270, 290):
        month_pnl.append((_d(d_), cum))
        cum += 3 if d_ % 3 == 0 else -1
    month_pnl.append((_d(290), cum))
    fills = round_trip_fills(_d(230, 1 * H), 2 * H, sz=10, px=100, exit_px=102) + round_trip_fills(
        _d(240, 1 * H), 2 * H, sz=10, px=100, exit_px=97
    )
    all_time = [(_d(100), 0), (_d(230, 4 * H), 20), (_d(240, 4 * H), -10), *extra_alltime_pnl]
    all_time.sort()
    return wallet(
        "0xccc0000000000000000000000000000000000003",
        fills=fills,
        fills_fetched_ms=FETCHED,
        portfolios=[
            portfolio(
                FETCHED,
                perpAllTime=window([(_d(100), 10_000)], all_time),
                perpMonth=window([(_d(270), 10_000)], month_pnl),
            )
        ],
        own_snapshots=own_pts,
        clearinghouse=[clearinghouse(FETCHED, 10_000)],
        candles_1h={"BTC": flat_candles("BTC", 100, T - 100 * DAY, T)},
        candles_fetched_ms=FETCHED,
    )


# --- healthy wallets: eligible under PERMISSIVE_CFG, used by the pipeline tests -------------------------------------
PERMISSIVE_CFG = {
    "scoring.window_days": 90,
    "gate.min_round_trips": 50,
    "gate.min_positive_blocks": 1,
    "gate.max_top_asset_share": "0.6",
}
P95_LATENCY_S = D(3)


def healthy(address: str, pnls: tuple[int, ...] = (12, 10, -4, 14, 8)) -> WalletInputs:
    """80 round trips, one per day on days 215..294, alternating BTC and ETH by day parity; 10 units of size at 100
    with fees 0.2 per leg. The exit moves by pnls[day % 5] / 10. Account value 10000 from day 100."""
    fills: list[Fill] = []
    total = D(0)
    for day in range(215, 295):
        coin = "BTC" if day % 2 == 0 else "ETH"
        pnl = pnls[day % 5]
        total += D(pnl) - D("0.4")
        fills += round_trip_fills(_d(day, 1 * H), 2 * H, coin=coin, sz=10, px=100, exit_px=D(100) + D(pnl) / 10, fee="0.2")
    pnl_pts = [(_d(100), 0), (_d(299), int(total))]
    return wallet(
        address,
        fills=fills,
        fills_fetched_ms=FETCHED,
        portfolios=[portfolio(FETCHED, perpAllTime=window([(_d(100), 10_000)], pnl_pts))],
        clearinghouse=[clearinghouse(FETCHED, 20_000)],
        candles_1h={
            "BTC": flat_candles("BTC", 100, T - 100 * DAY, T),
            "ETH": flat_candles("ETH", 100, T - 100 * DAY, T),
        },
        candles_fetched_ms=FETCHED,
    )
