"""Pure Decimal rules of the position manager (F12): ATR, the stop, the trail, the partial-reduce plan, open risk and
what a leader fill means for a share. No I/O, no clock, no config (every threshold is an argument)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_DOWN, Context, Decimal

from copytrade.core.atr import true_range_sum
from copytrade.hl.models import Candle, Fill

# Every product below is at most a few dozen digits; this context never rounds a realistic value.
_CTX = Context(prec=60)
_ZERO = Decimal(0)

REDUCE = "reduce"
PARTIAL_BELOW_MIN = "partial_below_min"
CLOSE_ALL_REMAINDER_BELOW_MIN = "close_all_remainder_below_min"


def atr(candles: Iterable[Candle], *, period: int, before_ms: int, max_age_ms: int | None = None) -> Decimal | None:
    """The mean true range of the last ``period`` bars closed at or before ``before_ms`` (no look-ahead).

    Needs ``period + 1`` such bars (the oldest only supplies a previous close). ``None`` when there are fewer, when the
    ATR is not positive, or when ``max_age_ms`` is given and the newest bar closed longer ago than that (a stale
    volatility would size a stop for a market that no longer exists). A bar seen twice is counted once.
    """
    closed = {c.open_ms: c for c in candles if c.close_ms <= before_ms}
    bars = [closed[key] for key in sorted(closed)]
    if len(bars) < period + 1:
        return None
    window = bars[-(period + 1) :]
    if max_age_ms is not None and before_ms - window[-1].close_ms > max_age_ms:
        return None
    mean = true_range_sum([(c.high, c.low, c.close) for c in window]) / period
    return mean if mean > 0 else None


def initial_stop(*, is_long: bool, entry_px: Decimal, atr: Decimal, stop_atr_mult: Decimal) -> Decimal:
    """``entry_px -/+ stop_atr_mult x atr`` (below a long, above a short). May be <= 0: the caller must check."""
    distance = _CTX.multiply(stop_atr_mult, atr)
    return _CTX.subtract(entry_px, distance) if is_long else _CTX.add(entry_px, distance)


def open_risk_usd(*, is_long: bool, qty: Decimal, entry_px: Decimal, stop_px: Decimal) -> Decimal:
    """What the share loses if its stop fills at the stop price: ``qty x (entry - stop)`` for a long, ``qty x
    (stop - entry)`` for a short, and 0 once the stop is past the entry (never negative)."""
    distance = _CTX.subtract(entry_px, stop_px) if is_long else _CTX.subtract(stop_px, entry_px)
    return _CTX.multiply(qty, distance) if distance > 0 else _ZERO


def trailed_stop(  # noqa: PLR0913 - the whole trailing rule is its arguments
    *,
    is_long: bool,
    current_stop_px: Decimal,
    entry_px: Decimal,
    initial_stop_px: Decimal,
    best_px: Decimal,
    atr: Decimal,
    trail_start_r: Decimal,
    trail_atr_mult: Decimal,
) -> Decimal:
    """The stop after trailing: once the best mark is at least ``trail_start_r`` R in profit (inclusive; R is the
    initial stop distance), ``best -/+ trail_atr_mult x atr``, but only if that is tighter than ``current_stop_px``.
    It never widens: a long's stop never falls, a short's never rises."""
    r_distance = abs(_CTX.subtract(entry_px, initial_stop_px))
    if r_distance <= 0:
        return current_stop_px
    start_distance = _CTX.multiply(trail_start_r, r_distance)
    profit = _CTX.subtract(best_px, entry_px) if is_long else _CTX.subtract(entry_px, best_px)
    if profit < start_distance:
        return current_stop_px
    trail_distance = _CTX.multiply(trail_atr_mult, atr)
    if is_long:
        return max(current_stop_px, _CTX.subtract(best_px, trail_distance))
    return min(current_stop_px, _CTX.add(best_px, trail_distance))


@dataclass(frozen=True)
class ReducePlan:
    """What to do with a leader's partial reduce: ``kind`` is ``reduce`` (send ``qty``), ``partial_below_min`` (skip,
    ``qty`` 0) or ``close_all_remainder_below_min`` (close the whole share, ``qty`` is its quantity)."""

    kind: str
    qty: Decimal


def reduce_plan(
    *, share_qty: Decimal, fraction: Decimal, px: Decimal, sz_decimals: int, min_order_usd: Decimal
) -> ReducePlan:
    """``fraction x share_qty`` rounded down to the lot, under the minimum-order rules: a reduce worth less than
    ``min_order_usd`` is skipped; one that would leave a remainder worth less than it closes everything. When both are
    below the minimum the reduce is skipped (a leader's dust partial never forces a full close)."""
    lot = Decimal(1).scaleb(-sz_decimals)
    qty = _CTX.multiply(share_qty, fraction).quantize(lot, rounding=ROUND_DOWN, context=_CTX)
    if _CTX.multiply(qty, px) < min_order_usd:
        return ReducePlan(PARTIAL_BELOW_MIN, _ZERO)
    if _CTX.multiply(_CTX.subtract(share_qty, qty), px) < min_order_usd:
        return ReducePlan(CLOSE_ALL_REMAINDER_BELOW_MIN, share_qty)
    return ReducePlan(REDUCE, qty)


def lot_decimals(qty: Decimal) -> int:
    """The number of decimals ``qty`` is quantised to. Every quantity the broker books went through the exchange's
    ``szDecimals`` rounding, so this is that lot (the broker exposes no lot size on a position)."""
    exponent = qty.as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


@dataclass(frozen=True)
class FillEffect:
    """What one leader fill does to a position of ours that follows direction ``is_long``.

    ``kind`` is ``close`` (flat or flipped), ``reduce`` (``fraction`` of the leader's size), ``add``, ``open`` (the
    leader had none in our direction and now has) or ``other``. ``post`` is the leader's signed size after the fill.
    """

    kind: str
    fraction: Decimal | None
    post: Decimal


def fill_effect(fill: Fill, *, is_long: bool) -> FillEffect:
    """Classify ``fill`` (``start_position`` is the leader's signed size before it) against direction ``is_long``."""
    direction = 1 if is_long else -1
    delta = fill.sz if fill.side == "B" else -fill.sz
    pre = Decimal(fill.start_position)
    post = _CTX.add(pre, delta)
    pre_d, post_d = _CTX.multiply(pre, direction), _CTX.multiply(post, direction)
    if pre_d <= 0:
        return FillEffect("open" if post_d > 0 else "other", None, post)
    if post_d > pre_d:
        return FillEffect("add", None, post)
    if post_d <= 0:
        return FillEffect("close", None, post)
    if post_d == pre_d:
        return FillEffect("other", None, post)
    return FillEffect("reduce", _CTX.divide(_CTX.subtract(pre_d, post_d), pre_d), post)
