"""Walking a recorded L2 book (F11.AC1): the VWAP of the levels a market order consumes, inside the depth band."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from copytrade.core.money import round_size
from copytrade.hl.models import BookLevel, L2Book
from copytrade.paper.settings import MONEY_CONTEXT

# Depth beyond 5% of mid is not counted (F11.AC1). It is part of the fill model, not a tunable.
DEPTH_BAND = Decimal("0.05")
_TWO = Decimal(2)


@dataclass(frozen=True)
class BookWalk:
    """What a market order gets from one snapshot: ``qty`` (lot-rounded, never more than asked) at total ``cost``
    (USD, exactly the sum of level qty x level price)."""

    qty: Decimal
    cost: Decimal


def walk_book(book: L2Book, *, side: str, qty: Decimal, sz_decimals: int) -> BookWalk | None:
    """Fill ``qty`` of a market order (``side`` is ``"buy"`` or ``"sell"``) against ``book``.

    Buys consume asks upward, sells consume bids downward, only levels within ``DEPTH_BAND`` of mid. The result is
    rounded down to the lot, so it never exceeds ``qty`` and never overfills a level. ``None`` means no fill is
    possible: a one-sided or empty book (mid is undefined), a crossed book (garbage: fail closed), or no depth
    inside the band.
    """
    with localcontext(MONEY_CONTEXT):
        return _walk(book, side, qty, sz_decimals)


def _walk(book: L2Book, side: str, qty: Decimal, sz_decimals: int) -> BookWalk | None:
    bids = [level for level in book.bids if level.px > 0 and level.sz > 0]
    asks = [level for level in book.asks if level.px > 0 and level.sz > 0]
    if not bids or not asks:
        return None
    best_bid = max(level.px for level in bids)
    best_ask = min(level.px for level in asks)
    if best_bid > best_ask:
        return None
    mid = (best_bid + best_ask) / _TWO
    if side == "buy":
        ceiling = mid * (1 + DEPTH_BAND)
        levels = sorted((lv for lv in asks if lv.px <= ceiling), key=lambda lv: lv.px)
    else:
        floor = mid * (1 - DEPTH_BAND)
        levels = sorted((lv for lv in bids if lv.px >= floor), key=lambda lv: lv.px, reverse=True)
    target = min(qty, round_size(sum((lv.sz for lv in levels), Decimal(0)), sz_decimals))
    if target <= 0:
        return None
    return BookWalk(qty=target, cost=_cost_of(levels, target))


def _cost_of(levels: list[BookLevel], qty: Decimal) -> Decimal:
    remaining, cost = qty, Decimal(0)
    for level in levels:
        take = min(remaining, level.sz)
        cost += take * level.px
        remaining -= take
        if remaining <= 0:
            break
    return cost
