"""True-range arithmetic shared by the copy replay (F5, M14/M16) and the position manager's stops (F12.AC2).

One implementation, so the stop distance the scorer assumes and the stop the bot places cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

Bar = tuple[Decimal, Decimal, Decimal]
"""``(high, low, close)`` of one candle."""

_ZERO = Decimal(0)


def true_range_sum(window: Sequence[Bar]) -> Decimal:
    """The sum of the true ranges of ``window[1:]``, oldest bar first.

    The true range of a bar is ``max(high - low, |high - previous close|, |low - previous close|)``, so the first bar
    only supplies the previous close: ``len(window) - 1`` ranges are summed. ``Decimal(0)`` for fewer than two bars.
    """
    total = _ZERO
    for index in range(1, len(window)):
        high, low, _close = window[index]
        previous_close = window[index - 1][2]
        total += max(high - low, abs(high - previous_close), abs(low - previous_close))
    return total
