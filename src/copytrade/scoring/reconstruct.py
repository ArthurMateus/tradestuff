"""Round-trip reconstruction (F5.AC2), edge-hypothesis 10.1.

A Decimal port of ``research/scripts/hl_sample.py::reconstruct``. Sizes and prices are exact decimals, so a position
is flat exactly when its size is zero (the reference needs a float epsilon; here none is needed).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from copytrade.scoring.models import Fill, FundingPayment, Reconstruction, RoundTrip, TripEvent

_ZERO = Decimal(0)


def is_core_perp(coin: str) -> bool:
    """Spot (``@n``, ``A/B``) and HIP-3 builder-dex perps (``dex:COIN``) are outside v1's universe."""
    return not (coin.startswith("@") or "/" in coin or ":" in coin)


def dedupe_fills(fills: Iterable[Fill]) -> list[Fill]:
    """Fills sorted by ``(time, tid)`` with repeats removed (same key as the reference: tid, time, coin, size)."""
    seen: set[tuple[int, int, str, Decimal]] = set()
    unique: list[Fill] = []
    for f in sorted(fills, key=lambda f: (f.time, f.tid)):
        key = (f.tid, f.time, f.coin, f.sz)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


@dataclass
class _Live:
    """A round trip while it is being built."""

    coin: str
    direction: int
    open_ms: int
    open_px: Decimal
    open_sz: Decimal
    avg_px: Decimal
    max_abs_sz: Decimal
    gross_pnl: Decimal = _ZERO
    net_pnl: Decimal = _ZERO
    adds: int = 0
    adds_while_losing: int = 0
    liquidated: bool = False
    reduces: list[Decimal] = field(default_factory=list)
    events: list[TripEvent] = field(default_factory=list)
    close_ms: int | None = None
    close_px: Decimal | None = None
    opened_by_flip: bool = False

    def freeze(self) -> RoundTrip:
        return RoundTrip(
            coin=self.coin,
            direction=self.direction,
            open_ms=self.open_ms,
            close_ms=self.close_ms,
            open_px=self.open_px,
            open_sz=self.open_sz,
            avg_px=self.avg_px,
            max_abs_sz=self.max_abs_sz,
            peak_notional=self.max_abs_sz * self.avg_px,
            events=tuple(self.events),
            adds=self.adds,
            adds_while_losing=self.adds_while_losing,
            reduces=tuple(self.reduces),
            gross_pnl=self.gross_pnl,
            net_pnl=self.net_pnl,
            liquidated=self.liquidated,
            close_px=self.close_px,
        )


def _fresh(coin: str, end: Decimal, t: int, px: Decimal, *, flip: bool) -> _Live:
    return _Live(
        coin=coin,
        direction=1 if end > 0 else -1,
        open_ms=t,
        open_px=px,
        open_sz=abs(end),
        avg_px=px,
        max_abs_sz=abs(end),
        opened_by_flip=flip,
    )


def reconstruct(fills: Sequence[Fill], funding: Sequence[FundingPayment]) -> Reconstruction:
    """Rebuild round trips exactly as ``research/scripts/hl_sample.py::reconstruct`` does, in Decimal.

    - Fills are processed in ``(time, tid)`` order whatever the input order; a repeated ``tid`` counts once.
    - A flip splits into a close (it takes the flip fill's closedPnl and fee) and a new open.
    - A position already open at the first fill of a coin is ignored until it is flat.
    - Spot (``@n``, ``A/B``) and ``dex:``-prefixed fills are skipped.
    - ``net_pnl`` = sum closedPnl - sum fee - funding paid on that coin between open and close (inclusive; a payment
      at the very millisecond of a flip belongs to the trip that closes).
    """
    closed: list[_Live] = []
    live: dict[str, _Live] = {}
    ignoring: dict[str, bool] = {}
    for f in dedupe_fills(f for f in fills if is_core_perp(f.coin)):
        coin, start = f.coin, f.start_position
        end = start + (f.sz if f.side == "B" else -f.sz)
        pnl = f.closed_pnl - f.fee
        if coin not in live and coin not in ignoring:
            ignoring[coin] = start != 0  # already open when our history starts: ignore until flat
        if ignoring.get(coin, False):
            if end == 0 or (start != 0 and (end > 0) != (start > 0)):
                ignoring[coin] = False
                if end != 0:  # flipped out of an ignored position: a fresh open
                    live[coin] = _fresh(coin, end, f.time, f.px, flip=True)
            continue
        rt = live.get(coin)
        if rt is None:
            if end == 0:
                continue
            rt = live[coin] = _fresh(coin, end, f.time, f.px, flip=False)
            rt.net_pnl, rt.gross_pnl, rt.liquidated = pnl, f.closed_pnl, f.liquidation
            continue
        rt.net_pnl += pnl
        rt.gross_pnl += f.closed_pnl
        rt.liquidated = rt.liquidated or f.liquidation
        same_side = end != 0 and (end > 0) == (rt.direction > 0)
        if same_side and abs(end) > abs(start):
            rt.adds += 1
            if (f.px - rt.avg_px) * rt.direction < 0:
                rt.adds_while_losing += 1
            rt.avg_px = (rt.avg_px * abs(start) + f.px * (abs(end) - abs(start))) / abs(end)
            rt.max_abs_sz = max(rt.max_abs_sz, abs(end))
            rt.events.append(TripEvent(f.time, "add", f.px, abs(start), abs(end)))
        elif same_side:
            rt.reduces.append((abs(start) - abs(end)) / abs(start))
            rt.events.append(TripEvent(f.time, "reduce", f.px, abs(start), abs(end)))
        else:
            rt.close_ms = f.time
            rt.close_px = f.px
            closed.append(rt)
            del live[coin]
            if end != 0:
                live[coin] = _fresh(coin, end, f.time, f.px, flip=True)
    _apply_funding([*closed, *live.values()], funding)
    return Reconstruction(
        closed=tuple(t.freeze() for t in closed),
        open=tuple(t.freeze() for t in live.values()),
    )


def _apply_funding(trips: Sequence[_Live], funding: Sequence[FundingPayment]) -> None:
    """Subtract funding paid from each trip's ``net_pnl``; a payment is attributed to at most one trip.

    Payments are indexed per coin with running totals, so each trip costs two binary searches.
    """
    by_coin: dict[str, list[FundingPayment]] = defaultdict(list)
    for p in funding:
        by_coin[p.coin].append(p)
    index: dict[str, tuple[list[int], list[Decimal]]] = {}
    for coin, payments in by_coin.items():
        payments.sort(key=lambda p: p.time)
        totals = [_ZERO]
        for p in payments:
            totals.append(totals[-1] + p.paid)
        index[coin] = ([p.time for p in payments], totals)
    for trip in trips:
        if trip.coin not in index:
            continue
        times, totals = index[trip.coin]
        lo = bisect_right(times, trip.open_ms) if trip.opened_by_flip else bisect_left(times, trip.open_ms)
        hi = len(times) if trip.close_ms is None else bisect_right(times, trip.close_ms)
        if hi > lo:
            trip.net_pnl -= totals[hi] - totals[lo]


__all__ = ["dedupe_fills", "is_core_perp", "reconstruct"]
