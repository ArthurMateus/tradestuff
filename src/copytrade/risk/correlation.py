"""Pearson correlation of return series (BTC bucket, F10.AC3). Decimal only."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def pearson(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    """Pearson correlation in [-1, 1], or ``None`` when either series has zero variance or fewer than 2 points.

    Raises:
        ValueError: the series have different lengths.
    """
    raise NotImplementedError
