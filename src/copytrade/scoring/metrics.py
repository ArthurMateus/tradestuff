"""Metrics M1-M19 (F5.AC1), edge-hypothesis 10.1 and 10.2, from point-in-time inputs only.

The window is ``[t - scoring.window_days, t]`` for fills and funding. The latest ``portfolio`` and
``clearinghouseState`` snapshot fetched at or before ``t`` is used. An account value is always the latest point at or
before the event it belongs to (BT-3); an event with none is excluded, never valued with a later point. The coarse
``perpAllTime`` series is used for the mark-to-market curve and the account age, and never for a daily return (BT-17).

Ratios and money are ``Decimal``. ``None`` means "cannot be computed" and fails a gate closed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar

from copytrade.core.config import Config
from copytrade.scoring.dsr import dsr_prob, sr0, variance_term
from copytrade.scoring.models import (
    DAY_MS,
    HOUR_MS,
    ClearinghouseState,
    CostModel,
    DsrResolution,
    Fill,
    Metrics,
    OwnSnapshot,
    PortfolioSnapshot,
    RoundTrip,
    TripRecord,
    WalletInputs,
)
from copytrade.scoring.reconstruct import dedupe_fills, is_core_perp, reconstruct
from copytrade.scoring.replay import CandleBook, replay_r
from copytrade.scoring.series import ReturnStats, Series, current_drawdown, max_drawdown, mean, median, return_stats

_ZERO = Decimal(0)
_BPS = Decimal(10_000)
_PROFIT_FACTOR_CAP = Decimal(10)
_MINUTE_MS = Decimal(60_000)
_RECENT_DAYS = 30  # M17: the recent window, and the n in n / (n + shrink_k_days_recent)
# Longest distance between a day boundary and the nearest sub-daily point for that point to stand for the boundary.
_OWN_MAX_GAP_MS = HOUR_MS  # our own hourly snapshots
_MONTH_MAX_GAP_MS = 6 * HOUR_MS  # perpMonth: "sub-daily points"
_PERP_WINDOWS = ("perpAllTime", "perpMonth", "perpWeek", "perpDay")


_Snapshot = TypeVar("_Snapshot", PortfolioSnapshot, ClearinghouseState)


def latest_snapshot(snapshots: Sequence[_Snapshot], t_ms: int) -> _Snapshot | None:
    """The snapshot fetched at or before ``t_ms`` with the latest fetch time."""
    known = [s for s in snapshots if s.fetched_ms <= t_ms]
    return max(known, key=lambda s: s.fetched_ms, default=None)


@dataclass(frozen=True)
class _Day:
    index: int  # UTC day number (ms // DAY_MS)
    pnl: Decimal  # deposit-neutral P&L of the day, USD
    source: str  # "own" | "month" | "fills"


class _Prepared:
    """The point-in-time view of one wallet at ``t``: windowed fills, trips, snapshots and account-value series."""

    def __init__(self, inputs: WalletInputs, cfg: Config, t_ms: int) -> None:
        self.cfg = cfg
        self.t_ms = t_ms
        self.start_ms = t_ms - cfg["scoring.window_days"] * DAY_MS
        self.fills: list[Fill] = dedupe_fills(
            f for f in inputs.fills if is_core_perp(f.coin) and self.start_ms <= f.time <= t_ms
        )
        self.funding = [p for p in inputs.funding if is_core_perp(p.coin) and self.start_ms <= p.time <= t_ms]
        recon = reconstruct(self.fills, self.funding)
        self.closed: list[RoundTrip] = sorted(recon.closed, key=lambda r: (r.open_ms, r.close_ms or 0, r.coin))
        self.portfolio: PortfolioSnapshot | None = latest_snapshot(inputs.portfolios, t_ms)
        self.clearinghouse: ClearinghouseState | None = latest_snapshot(inputs.clearinghouse, t_ms)
        self.own: list[OwnSnapshot] = sorted((o for o in inputs.own_snapshots if o.ms <= t_ms), key=lambda o: o.ms)
        self.av = Series(self._account_value_points())
        self.book = CandleBook(inputs.candles_1h, t_ms=t_ms)

    def _account_value_points(self) -> list[tuple[int, Decimal]]:
        points: list[tuple[int, Decimal]] = []
        if self.portfolio is not None:
            for name in _PERP_WINDOWS:
                win = self.portfolio.windows.get(name)
                if win is not None:
                    points += [(ms, v) for ms, v in win.account_value_history if ms <= self.t_ms]
        return points + [(o.ms, o.account_value) for o in self.own]

    def pnl_series(self, window: str) -> Series | None:
        if self.portfolio is None or window not in self.portfolio.windows:
            return None
        return Series((ms, v) for ms, v in self.portfolio.windows[window].pnl_history if ms <= self.t_ms)

    # --- daily P&L and returns -------------------------------------------------------------------------------------

    def days(self) -> list[_Day]:
        """Every complete UTC day in the window, from the finest source that covers it (10.1): our own hourly
        snapshots, then ``perpMonth``, then realised P&L from fills (zero on a day without fills)."""
        first = -(-self.start_ms // DAY_MS)
        last = self.t_ms // DAY_MS - 1
        own = Series((o.ms, o.pnl) for o in self.own)
        month = self.pnl_series("perpMonth")
        realised: dict[int, Decimal] = defaultdict(lambda: _ZERO)
        for f in self.fills:
            realised[f.time // DAY_MS] += f.closed_pnl - f.fee
        for p in self.funding:
            realised[p.time // DAY_MS] -= p.paid
        out: list[_Day] = []
        for d in range(first, last + 1):
            delta = _delta(own, d, _OWN_MAX_GAP_MS)
            if delta is not None:
                out.append(_Day(d, delta, "own"))
                continue
            delta = None if month is None else _delta(month, d, _MONTH_MAX_GAP_MS)
            out.append(_Day(d, delta, "month") if delta is not None else _Day(d, realised[d], "fills"))
        return out

    def returns(self) -> tuple[list[tuple[int, Decimal]], DsrResolution]:
        """``r_d = dPnL_d / AV_{d-1}``; a day with no account value at or before its start is excluded."""
        rets: list[tuple[int, Decimal]] = []
        counts = {"own": 0, "month": 0, "fills": 0}
        for day in self.days():
            av_prev = self.av.at(day.index * DAY_MS)
            if av_prev is None or av_prev <= 0:
                continue
            rets.append((day.index, day.pnl / av_prev))
            counts[day.source] += 1
        return rets, DsrResolution(counts["own"], counts["month"], counts["fills"])

    def records(self) -> list[TripRecord]:
        return [TripRecord(trip=r, av_at_open=self.av.at(r.open_ms)) for r in self.closed]


def _delta(series: Series, day: int, max_gap_ms: int) -> Decimal | None:
    """Change of a cumulative series over UTC ``day``, or ``None`` if a boundary has no point close enough."""
    start, end = day * DAY_MS, (day + 1) * DAY_MS
    i, j = series.index_at(start), series.index_at(end)
    if i < 0 or j < 0 or start - series.times[i] > max_gap_ms or end - series.times[j] > max_gap_ms:
        return None
    return series.values[j] - series.values[i]


# --- public building blocks -------------------------------------------------------------------------------------


def daily_returns(
    inputs: WalletInputs, *, cfg: Config, t_ms: int
) -> tuple[tuple[tuple[int, Decimal], ...], DsrResolution]:
    """Daily returns ``r_d = dPnL_d / AV_{d-1}`` for the complete UTC days in ``[t - window_days, t)``.

    Returns ``((day_index, r_d), ...)`` in day order plus the per-source day counts. A day whose previous day-end
    has no account value is excluded. ``perpAllTime`` P&L points are never used for a daily return.
    """
    rets, resolution = _Prepared(inputs, cfg, t_ms).returns()
    return tuple(rets), resolution


def trip_records(inputs: WalletInputs, *, cfg: Config, t_ms: int) -> tuple[TripRecord, ...]:
    """Closed round trips inside the window (point-in-time), each with the AV at its open."""
    return tuple(_Prepared(inputs, cfg, t_ms).records())


def copy_replay_r(inputs: WalletInputs, *, cfg: Config, t_ms: int, costs: CostModel) -> Sequence[Decimal]:
    """Per closed round trip ``R_copy_j`` (M14). Trips whose ATR stop cannot be built are omitted."""
    return _replay(_Prepared(inputs, cfg, t_ms), costs)


def _replay(p: _Prepared, costs: CostModel) -> list[Decimal]:
    rs = (replay_r(t, book=p.book, cfg=p.cfg, costs=costs) for t in p.closed)
    return [r for r in rs if r is not None]


# --- the metrics ------------------------------------------------------------------------------------------------


def _profit_factor(pnls: Sequence[Decimal]) -> Decimal | None:
    wins = sum((x for x in pnls if x > 0), _ZERO)
    losses = -sum((x for x in pnls if x < 0), _ZERO)
    if losses == 0:
        return _PROFIT_FACTOR_CAP if wins > 0 else None
    return min(wins / losses, _PROFIT_FACTOR_CAP)


def _concentration(trips: Sequence[RoundTrip]) -> tuple[Decimal | None, Decimal | None]:
    """M11 and M12: the best trade's and the best coin's share of total net P&L; undefined unless it is positive."""
    total = sum((t.net_pnl for t in trips), _ZERO)
    if total <= 0:
        return None, None
    by_coin: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    for t in trips:
        by_coin[t.coin] += t.net_pnl
    return max(t.net_pnl for t in trips) / total, max(by_coin.values()) / total


def maker_share(fills: Sequence[Fill]) -> Decimal | None:
    """M13: the maker (not crossed) share of the traded notional of ``fills``; ``None`` when there is no notional."""
    total = sum((f.sz * f.px for f in fills), _ZERO)
    if total <= 0:
        return None
    return sum((f.sz * f.px for f in fills if not f.crossed), _ZERO) / total


def _positive_blocks(days: Sequence[_Day], *, t_ms: int, n_blocks: int, block_days: int) -> int:
    """M8: blocks ``[t - i*block, t - (i-1)*block)`` whose summed daily P&L is positive; a block with no day is not."""
    sums: dict[int, Decimal] = defaultdict(lambda: _ZERO)
    block_ms = block_days * DAY_MS
    for day in days:
        i = (t_ms - day.index * DAY_MS - 1) // block_ms + 1  # 1 = the most recent block
        if 1 <= i <= n_blocks:
            sums[i] += day.pnl
    return sum(1 for total in sums.values() if total > 0)


def _realised_drawdown(p: _Prepared) -> Decimal | None:
    """M9 (realised): drawdown of ``AV_0 + cumulative L_j`` over the closed trips in close order, AV_0 being the
    account value at or before the first open (or the window start when there is no trip)."""
    anchor = p.closed[0].open_ms if p.closed else p.start_ms
    base = p.av.at(anchor)
    if base is None:
        return None
    equity = [base]
    for trip in sorted(p.closed, key=lambda r: (r.close_ms or 0, r.open_ms)):
        equity.append(equity[-1] + trip.net_pnl)
    return max_drawdown(equity)


def _mtm_curve(p: _Prepared) -> list[Decimal] | None:
    """``AV_0 + pnlHistory`` of ``perpAllTime``; AV_0 is the account value at or before its first point."""
    pnl = p.pnl_series("perpAllTime")
    if pnl is None or not len(pnl):
        return None
    base = p.av.at(pnl.times[0])
    return None if base is None else [base + v for v in pnl.values]


def _account_age_days(p: _Prepared) -> Decimal | None:
    if p.portfolio is None or "perpAllTime" not in p.portfolio.windows:
        return None
    win = p.portfolio.windows["perpAllTime"]
    stamps = [ms for ms, _ in (*win.account_value_history, *win.pnl_history) if ms <= p.t_ms]
    return Decimal(p.t_ms - min(stamps)) / DAY_MS if stamps else None


def _executable_share(p: _Prepared, records: Sequence[TripRecord]) -> Decimal | None:
    """M16: share of opens whose mirrored notional, after the risk cap with our stop, reaches the minimum order.

    Opens with no account value at or before them, or with no buildable stop, are out of numerator and denominator.
    """
    cfg = p.cfg
    wallet: Decimal = cfg["paper.wallet_usd"]
    risk_usd = cfg["risk.per_trade_fraction"] * wallet
    counted = executable = 0
    for rec in records:
        trip = rec.trip
        dist = p.book.stop_distance(
            trip.coin, trip.open_ms, atr_period=cfg["exits.atr_period"], atr_mult=cfg["exits.stop_atr_mult"]
        )
        if rec.av_at_open is None or rec.av_at_open <= 0 or dist is None:
            continue
        mirrored = trip.open_sz * trip.open_px / rec.av_at_open * wallet
        capped = min(mirrored, risk_usd * trip.open_px / dist)  # risk cap: risk budget / stop fraction
        counted += 1
        executable += capped >= cfg["sizing.min_order_usd"]
    return Decimal(executable) / counted if counted else None


def _copy_edge_ratio(p: _Prepared, costs: CostModel) -> Decimal | None:
    """M15: mean gross bps of a trip (closedPnl / peak notional) over mean cost bps (two taker fees, two half spreads,
    the copy delay)."""
    if not p.closed:
        return None
    gross = [t.gross_pnl / t.peak_notional * _BPS for t in p.closed]
    taker = costs.taker_fee_bps()
    cost = [
        2 * taker + 2 * costs.half_spread_bps(t.coin, t.open_ms) + costs.delay_bps(t.coin, t.open_ms) for t in p.closed
    ]
    mean_cost = mean(cost)
    mean_gross = mean(gross)
    if mean_cost is None or mean_gross is None or mean_cost <= 0:
        return None
    return mean_gross / mean_cost


def _deflated_sharpe(stats: ReturnStats, *, t_days: int, n_trials: int) -> tuple[Decimal | None, Decimal | None]:
    """M7: ``(SR0, DSR probability)``. SR0 needs two days; the probability also needs a defined Sharpe, skew and
    kurtosis and a positive variance term (otherwise it is ``None``: cannot be computed, so G7 fails closed)."""
    if t_days < 2:
        return None, None
    benchmark = sr0(t_days, n_trials)
    if stats.sr is None or stats.skew is None or stats.kurt is None:
        return benchmark, None
    if variance_term(sr_d=stats.sr, skew=stats.skew, kurt=stats.kurt) <= 0:
        return benchmark, None
    return benchmark, dsr_prob(sr_d=stats.sr, skew=stats.skew, kurt=stats.kurt, t_days=t_days, n_trials=n_trials)


def _open_loss_fraction(state: ClearinghouseState | None) -> Decimal | None:
    """BU8 input: net unrealised loss of the open positions over the account value (zero when they are in profit)."""
    if state is None or state.account_value <= 0:
        return None
    net = sum((pos.unrealized_pnl for pos in state.positions), _ZERO)
    return max(_ZERO, -net) / state.account_value


def compute_metrics(inputs: WalletInputs, *, cfg: Config, t_ms: int, costs: CostModel) -> Metrics:
    """M1-M19 for one wallet at cycle time ``t_ms``, using only inputs at or before ``t_ms`` (10.1, 10.2)."""
    p = _Prepared(inputs, cfg, t_ms)
    records = p.records()
    days = p.days()
    rets, _ = p.returns()
    values = [r for _, r in rets]
    stats = return_stats(values)
    t_days = len(values)
    recent = return_stats([r for d, r in rets if d * DAY_MS >= t_ms - _RECENT_DAYS * DAY_MS])
    recent_sr = None
    if recent.sr is not None:
        recent_sr = recent.sr * _RECENT_DAYS / (_RECENT_DAYS + cfg["score.shrink_k_days_recent"])

    benchmark, dsr = _deflated_sharpe(stats, t_days=t_days, n_trials=cfg["gate.dsr_n_trials"])

    top_trade, top_asset = _concentration(p.closed)
    holds = [Decimal((t.close_ms or 0) - t.open_ms) / _MINUTE_MS for t in p.closed]
    replayed = _replay(p, costs)
    realised_dd = _realised_drawdown(p)
    curve = _mtm_curve(p)
    mtm_dd = None if curve is None else max_drawdown(curve)
    leverage = [r.trip.peak_notional / r.av_at_open for r in records if r.av_at_open is not None and r.av_at_open > 0]
    times = [f.time for f in p.fills]
    return Metrics(
        n_rt=len(p.closed),
        fill_span_days=Decimal(max(times) - min(times)) / DAY_MS if times else None,
        account_age_days=_account_age_days(p),
        profit_factor=_profit_factor([t.net_pnl for t in p.closed]),
        sr_d=stats.sr,
        skew=stats.skew,
        kurt=stats.kurt,
        dsr_prob=dsr,
        sr0=benchmark,
        dsr_excess=None if stats.sr is None or benchmark is None else stats.sr - benchmark,
        t_days=t_days,
        pos_blocks=_positive_blocks(days, t_ms=t_ms, n_blocks=cfg["gate.n_blocks"], block_days=cfg["gate.block_days"]),
        max_dd=None if realised_dd is None or mtm_dd is None else max(realised_dd, mtm_dd),
        max_dd_realised=realised_dd,
        max_dd_mtm=mtm_dd,
        median_hold_min=median(holds),
        top_trade_share=top_trade,
        top_asset_share=top_asset,
        maker_share=maker_share(p.fills),
        copy_mean_r=mean(replayed),
        copy_edge_ratio=_copy_edge_ratio(p, costs),
        executable_share=_executable_share(p, records),
        recent_sr=recent_sr,
        current_dd=None if curve is None else current_drawdown(curve),
        eff_leverage_median=median(leverage),
        account_value=None if p.clearinghouse is None else p.clearinghouse.account_value,
        open_loss_fraction=_open_loss_fraction(p.clearinghouse),
        liquidation_fills=sum(1 for f in p.fills if f.liquidation),
    )
