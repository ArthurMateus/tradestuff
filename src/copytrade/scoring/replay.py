"""Copy replay (edge-hypothesis 10.2 M14) and the ATR stop shared with the executable-share metric (M16).

Each closed round trip is re-traded as we would trade it: entry at the leader's open price plus half spread and copy
delay (adverse), our ATR stop and first take-profit (levels set from the leader's open price), the leader's close, and
our taker fee on every leg. Stops and targets are checked on the high and low of 1h bars; on an ambiguous bar the stop
is assumed first (conservative).

Not modelled (they depend on the F12 exit rules and are not pinned by the spec's fixtures): the trailing stop after
``exits.trail_start_r`` and mirrored adds and partial reduces. Each of them is a refinement, so R here is the
open-to-close, single-entry replay.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from itertools import pairwise

from copytrade.core.config import Config
from copytrade.scoring.models import Candle, CostModel, RoundTrip

_BPS = Decimal(10_000)
_ONE = Decimal(1)


class CandleBook:
    """1h candles per coin with close time at or before the cycle time, indexed for binary search."""

    def __init__(self, candles: Mapping[str, Sequence[Candle]], *, t_ms: int) -> None:
        self._bars: dict[str, list[Candle]] = {}
        self._closes: dict[str, list[int]] = {}
        for coin, bars in candles.items():
            known = sorted({b.open_ms: b for b in bars if b.close_ms <= t_ms}.values(), key=lambda b: b.open_ms)
            self._bars[coin] = known
            self._closes[coin] = [b.close_ms for b in known]

    def stop_distance(self, coin: str, before_ms: int, *, atr_period: int, atr_mult: Decimal) -> Decimal | None:
        """``atr_mult`` x ATR(``atr_period``) in price units, on the bars closed before ``before_ms`` (no look-ahead).

        ``None`` when fewer than ``atr_period + 1`` such bars exist or the ATR is not positive.
        """
        bars = self._bars.get(coin)
        if bars is None:
            return None
        end = bisect_left(self._closes[coin], before_ms)  # bars[:end] closed before the entry
        if end < atr_period + 1:
            return None
        window = bars[end - atr_period - 1 : end]
        true_ranges = [
            max(cur.hi - cur.lo, abs(cur.hi - prev.c), abs(cur.lo - prev.c)) for prev, cur in pairwise(window)
        ]
        distance = atr_mult * sum(true_ranges, Decimal(0)) / atr_period
        return distance if distance > 0 else None

    def bars_between(self, coin: str, start_ms: int, end_ms: int) -> Iterable[Candle]:
        """Bars that overlap ``[start_ms, end_ms)``: closing at or after ``start_ms`` and opening before ``end_ms``."""
        bars = self._bars.get(coin, [])
        for i in range(bisect_left(self._closes.get(coin, []), start_ms), len(bars)):
            if bars[i].open_ms >= end_ms:
                return
            yield bars[i]


def replay_r(trip: RoundTrip, *, book: CandleBook, cfg: Config, costs: CostModel) -> Decimal | None:
    """``R_copy`` of one closed round trip, or ``None`` if the ATR stop cannot be built or the trip has no close."""
    if trip.close_ms is None or trip.close_px is None:
        return None
    dist = book.stop_distance(
        trip.coin, trip.open_ms, atr_period=cfg["exits.atr_period"], atr_mult=cfg["exits.stop_atr_mult"]
    )
    if dist is None:
        return None
    d = trip.direction
    half_spread = costs.half_spread_bps(trip.coin, trip.open_ms)
    taker = costs.taker_fee_bps()
    entry = trip.open_px * (_ONE + d * (half_spread + costs.delay_bps(trip.coin, trip.open_ms)) / _BPS)
    stop = trip.open_px - d * dist  # levels sit on the leader's price; our worse entry is a cost, not a shift
    take_profit = trip.open_px + d * cfg["exits.tp1_r"] * dist if cfg["exits.tp_enabled"] else None
    tp_fraction: Decimal = cfg["exits.tp1_fraction"]

    def leg(exit_px: Decimal) -> Decimal:
        """R of one leg: the price move after the exit half spread and both taker fees, over the stop distance."""
        filled = exit_px * (_ONE - d * half_spread / _BPS)
        return (d * (filled - entry) - (entry + filled) * taker / _BPS) / dist

    total = Decimal(0)
    remaining = _ONE
    for bar in book.bars_between(trip.coin, trip.open_ms, trip.close_ms):
        stop_hit = bar.lo <= stop if d > 0 else bar.hi >= stop
        if stop_hit:  # checked first: an ambiguous bar is a stop
            return total + remaining * leg(stop)
        target_hit = take_profit is not None and (bar.hi >= take_profit if d > 0 else bar.lo <= take_profit)
        if target_hit and take_profit is not None and remaining == _ONE:
            total += tp_fraction * leg(take_profit)
            remaining -= tp_fraction
    return total + remaining * leg(trip.close_px)
