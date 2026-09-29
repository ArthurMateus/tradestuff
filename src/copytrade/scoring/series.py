"""Point-in-time series and the small Decimal statistics F5 needs (edge-hypothesis 10.1, 10.2).

Everything is exact ``Decimal`` arithmetic. ``None`` means "cannot be computed"; nothing here divides by zero.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

_ZERO = Decimal(0)
_TWO = Decimal(2)


class Series:
    """A time series of ``(ms, value)`` points, sorted by time; a later duplicate of a timestamp wins."""

    __slots__ = ("times", "values")

    def __init__(self, points: Iterable[tuple[int, Decimal]]) -> None:
        latest: dict[int, Decimal] = {}
        for ms, value in points:
            latest[ms] = value
        ordered = sorted(latest.items())
        self.times: list[int] = [ms for ms, _ in ordered]
        self.values: list[Decimal] = [v for _, v in ordered]

    def __len__(self) -> int:
        return len(self.times)

    def at(self, ms: int) -> Decimal | None:
        """The latest value at or before ``ms``; never a later one (BT-3). ``None`` if there is none."""
        i = bisect_right(self.times, ms)
        return self.values[i - 1] if i else None

    def index_at(self, ms: int) -> int:
        """Index of the latest point at or before ``ms``; ``-1`` if there is none."""
        return bisect_right(self.times, ms) - 1


def mean(xs: Sequence[Decimal]) -> Decimal | None:
    return sum(xs, _ZERO) / len(xs) if xs else None


def median(xs: Iterable[Decimal]) -> Decimal | None:
    """The middle value; the mean of the middle two for an even count."""
    ordered = sorted(xs)
    n = len(ordered)
    if n == 0:
        return None
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / _TWO


@dataclass(frozen=True)
class ReturnStats:
    """Sharpe ratio (sample sd, n - 1) and population skew and (non-excess) kurtosis of a return series."""

    sr: Decimal | None
    skew: Decimal | None
    kurt: Decimal | None


def return_stats(xs: Sequence[Decimal]) -> ReturnStats:
    """``sr = mean / sd`` with the sample sd; ``skew = m3 / m2^1.5`` and ``kurt = m4 / m2^2`` from population central
    moments (as in the DSR paper). Any of them is ``None`` when the series is too short or has no variance."""
    n = len(xs)
    if n < 2 or min(xs) == max(xs):
        return ReturnStats(None, None, None)
    mu = sum(xs, _ZERO) / n
    dev = [x - mu for x in xs]
    m2 = sum((d * d for d in dev), _ZERO) / n
    m3 = sum((d**3 for d in dev), _ZERO) / n
    m4 = sum((d**4 for d in dev), _ZERO) / n
    sd = (m2 * n / (n - 1)).sqrt()
    return ReturnStats(sr=mu / sd, skew=m3 / (m2 * m2.sqrt()), kurt=m4 / (m2 * m2))


def max_drawdown(equity: Iterable[Decimal]) -> Decimal | None:
    """Largest ``(peak - equity) / peak`` along the curve; ``None`` if it is empty or its peak is not positive."""
    peak: Decimal | None = None
    worst = _ZERO
    for e in equity:
        peak = e if peak is None or e > peak else peak
        if peak > 0:
            worst = max(worst, (peak - e) / peak)
    return worst if peak is not None and peak > 0 else None


def current_drawdown(equity: Sequence[Decimal]) -> Decimal | None:
    """``(peak - last) / peak`` of the curve; ``None`` if it is empty or its peak is not positive."""
    if not equity:
        return None
    peak = max(equity)
    return (peak - equity[-1]) / peak if peak > 0 else None
