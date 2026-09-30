"""Pearson correlation of return series (BTC bucket, F10.AC3). Decimal only."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from copytrade.paper.settings import MONEY_CONTEXT

_MIN_POINTS = 2


def _total(values: Sequence[Decimal]) -> Decimal:
    total = Decimal(0)
    for value in values:
        total = MONEY_CONTEXT.add(total, value)
    return total


def pearson(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    """Pearson correlation in [-1, 1], or ``None`` when either series has zero variance or fewer than 2 points.

    The result is clamped to [-1, 1]: the square root is rounded, so a perfectly correlated pair could otherwise come
    out a hair above 1.

    Raises:
        ValueError: the series have different lengths or a value is not finite.
    """
    if len(xs) != len(ys):
        raise ValueError("the series must have the same length")
    if not all(value.is_finite() for value in (*xs, *ys)):
        raise ValueError("every return must be finite")
    n = len(xs)
    if n < _MIN_POINTS:
        return None
    ctx = MONEY_CONTEXT
    mean_x, mean_y = ctx.divide(_total(xs), n), ctx.divide(_total(ys), n)
    cov = var_x = var_y = Decimal(0)
    for x, y in zip(xs, ys, strict=True):
        dx, dy = ctx.subtract(x, mean_x), ctx.subtract(y, mean_y)
        cov = ctx.add(cov, ctx.multiply(dx, dy))
        var_x = ctx.add(var_x, ctx.multiply(dx, dx))
        var_y = ctx.add(var_y, ctx.multiply(dy, dy))
    if var_x == 0 or var_y == 0:
        return None
    denominator = ctx.sqrt(ctx.multiply(var_x, var_y))
    return max(Decimal(-1), min(Decimal(1), ctx.divide(cov, denominator)))
