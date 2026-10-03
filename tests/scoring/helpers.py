"""Builders for the F5 tests. Test utilities only: they build inputs, they never compute a metric."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.config import Config, load_config
from copytrade.scoring.models import (
    Candle,
    ClearinghouseState,
    CycleResult,
    Fill,
    FundingPayment,
    Metrics,
    OpenPosition,
    OwnSnapshot,
    PortfolioSnapshot,
    PortfolioWindow,
    RoundTrip,
    TripRecord,
    WalletInputs,
)
from tests.core.helpers import ConfigTree, same_kind

D = Decimal
M = 60_000
H = 3_600_000
DAY = 86_400_000

# --------------------------------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------------------------------


def make_cfg(base: Path, **overrides: Any) -> Config:
    """The valid fixture config with dotted-key overrides (keys with dots are passed via ``**{"a.b": v}``)."""
    tree = ConfigTree()
    for key, value in overrides.items():
        tree.set(key, same_kind(tree.get(key), value))
    return load_config(tree.write(base / "config"))


# --------------------------------------------------------------------------------------------------
# fills
# --------------------------------------------------------------------------------------------------

_tids = itertools.count(1)


def fill(
    t: int,
    coin: str,
    side: str,
    sz: str | int,
    px: str | int,
    start: str | int,
    *,
    pnl: str | int = 0,
    fee: str | int = 0,
    crossed: bool = True,
    liq: bool = False,
    tid: int | None = None,
) -> Fill:
    """Mirror of ``hl_sample._fill`` with Decimal fields. ``tid`` defaults to a fresh increasing id."""
    if tid is None:
        tid = next(_tids)
    return Fill(
        tid=tid,
        time=t,
        coin=coin,
        side=side,
        sz=D(str(sz)),
        px=D(str(px)),
        start_position=D(str(start)),
        closed_pnl=D(str(pnl)),
        fee=D(str(fee)),
        crossed=crossed,
        liquidation=liq,
    )


def round_trip_fills(
    t0: int,
    hold_ms: int,
    *,
    coin: str = "BTC",
    sz: str | int = 1,
    px: str | int = 100,
    exit_px: str | int | None = None,
    fee: str | int = 0,
    direction: int = 1,
    crossed: bool = True,
) -> list[Fill]:
    """Open then close in one direction. closedPnl is set from the prices."""
    open_side, close_side = ("B", "A") if direction > 0 else ("A", "B")
    xpx = D(str(exit_px if exit_px is not None else px))
    size = D(str(sz))
    pnl = direction * size * (xpx - D(str(px)))
    start_close = size * direction
    return [
        fill(t0, coin, open_side, sz, px, 0, fee=fee, crossed=crossed),
        fill(t0 + hold_ms, coin, close_side, sz, xpx, start_close, pnl=pnl, fee=fee, crossed=crossed),
    ]


# --------------------------------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------------------------------


def window(
    av: Sequence[tuple[int, str | int]] = (), pnl: Sequence[tuple[int, str | int]] = ()
) -> PortfolioWindow:
    return PortfolioWindow(
        account_value_history=tuple((t, D(str(v))) for t, v in av),
        pnl_history=tuple((t, D(str(v))) for t, v in pnl),
    )


def portfolio(fetched_ms: int, **windows: PortfolioWindow) -> PortfolioSnapshot:
    return PortfolioSnapshot(fetched_ms=fetched_ms, windows=dict(windows))


def clearinghouse(fetched_ms: int, av: str | int, unrealized: Sequence[tuple[str, str | int]] = ()) -> ClearinghouseState:
    return ClearinghouseState(
        fetched_ms=fetched_ms,
        account_value=D(str(av)),
        positions=tuple(OpenPosition(coin=c, unrealized_pnl=D(str(u))) for c, u in unrealized),
    )


def flat_candles(coin: str, px: str | int, start_ms: int, end_ms: int, *, spread: str = "0.01") -> tuple[Candle, ...]:
    """Hourly bars from ``start_ms`` (an hour boundary) to before ``end_ms``: o = c = px, h/l = px x (1 +/- spread)."""
    p = D(str(px))
    s = D(spread)
    bars = []
    t = start_ms
    while t < end_ms:
        bars.append(Candle(open_ms=t, close_ms=t + H - 1, o=p, hi=p * (1 + s), lo=p * (1 - s), c=p))
        t += H
    return tuple(bars)


def with_bar(bars: tuple[Candle, ...], open_ms: int, *, hi: str | int, lo: str | int) -> tuple[Candle, ...]:
    """Replace the high and low of the bar that opens at ``open_ms``."""
    return tuple(replace(b, hi=D(str(hi)), lo=D(str(lo))) if b.open_ms == open_ms else b for b in bars)


def wallet(address: str = "0xaaa0000000000000000000000000000000000001", **kw: Any) -> WalletInputs:
    base: dict[str, Any] = {
        "address": address,
        "fills": (),
        "fills_fetched_ms": None,
        "funding": (),
        "portfolios": (),
        "clearinghouse": (),
        "own_snapshots": (),
        "candles_1h": {},
        "candles_fetched_ms": None,
        "role": "user",
        "leaderboard_row": None,
    }
    base.update(kw)
    for key in ("fills", "funding", "portfolios", "clearinghouse", "own_snapshots"):
        base[key] = tuple(base[key])
    return WalletInputs(**base)


@dataclass(frozen=True)
class FixedCosts:
    """A test double for the recorded-cost boundary (CostModel): fixed numbers per coin."""

    taker: Decimal = D(0)
    half_spread: dict[str, Decimal] = field(default_factory=dict)
    delay: dict[str, Decimal] = field(default_factory=dict)
    default_half_spread: Decimal = D(0)
    default_delay: Decimal = D(0)

    def taker_fee_bps(self) -> Decimal:
        return self.taker

    def half_spread_bps(self, coin: str, t_ms: int) -> Decimal:
        return self.half_spread.get(coin, self.default_half_spread)

    def delay_bps(self, coin: str, t_ms: int) -> Decimal:
        return self.delay.get(coin, self.default_delay)


ZERO_COSTS = FixedCosts()
PAPER_COSTS = FixedCosts(taker=D("4.5"), default_half_spread=D(2), default_delay=D(5), half_spread={"SOL": D(8)})


class MemoryStore:
    """A test double for the ScoreStore boundary (the ledger, F2): keeps what it is given."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.cycles: list[CycleResult] = []
        self.fail = fail

    def append_cycle(self, result: CycleResult) -> None:
        if self.fail is not None:
            raise self.fail
        self.cycles.append(result)


# --------------------------------------------------------------------------------------------------
# metrics and trips
# --------------------------------------------------------------------------------------------------


def passing_metrics(**overrides: Any) -> Metrics:
    """A Metrics that passes every gate at the fixture config (G8 at p95 latency <= 45 s), with round values."""
    base = Metrics(
        n_rt=300,
        fill_span_days=D(100),
        account_age_days=D(400),
        profit_factor=D("2.0"),
        sr_d=D("0.30"),
        skew=D(0),
        kurt=D(3),
        dsr_prob=D("0.99"),
        sr0=D("0.20"),
        dsr_excess=D("0.10"),
        t_days=120,
        pos_blocks=5,
        max_dd=D("0.10"),
        max_dd_realised=D("0.08"),
        max_dd_mtm=D("0.10"),
        median_hold_min=D(120),
        top_trade_share=D("0.10"),
        top_asset_share=D("0.30"),
        maker_share=D("0.20"),
        copy_mean_r=D("0.20"),
        copy_edge_ratio=D("4.0"),
        executable_share=D("0.80"),
        recent_sr=D("0.15"),
        current_dd=D("0.05"),
        eff_leverage_median=D(3),
        account_value=D(50_000),
        open_loss_fraction=D("0.01"),
    )
    return replace(base, **overrides)


def trip(
    net_pnl: str | int,
    *,
    open_ms: int = 0,
    adds: int = 0,
    adds_while_losing: int = 0,
    peak_notional: str | int = 1000,
    liquidated: bool = False,
    coin: str = "BTC",
) -> RoundTrip:
    return RoundTrip(
        coin=coin,
        direction=1,
        open_ms=open_ms,
        close_ms=open_ms + H,
        open_px=D(100),
        open_sz=D(10),
        avg_px=D(100),
        max_abs_sz=D(10),
        peak_notional=D(str(peak_notional)),
        events=(),
        adds=adds,
        adds_while_losing=adds_while_losing,
        reduces=(),
        gross_pnl=D(str(net_pnl)),
        net_pnl=D(str(net_pnl)),
        liquidated=liquidated,
    )


def record(t: RoundTrip, av: str | int | None = 10_000) -> TripRecord:
    return TripRecord(trip=t, av_at_open=None if av is None else D(str(av)))


def funding(t: int, coin: str, paid: str | int) -> FundingPayment:
    return FundingPayment(time=t, coin=coin, paid=D(str(paid)))


def own(ms: int, av: str | int, pnl: str | int) -> OwnSnapshot:
    return OwnSnapshot(ms=ms, account_value=D(str(av)), pnl=D(str(pnl)))
