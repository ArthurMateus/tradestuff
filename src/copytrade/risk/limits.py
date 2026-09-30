"""Loss limits and drawdown on an equity mark (F10.AC5). Pure: a state and a mark in, a state and the new halts out.

Opening equity of a UTC day (week) is the first known mark at or after its 00:00 UTC (Monday 00:00 UTC). A limit is
hit when the loss reaches it exactly (``>=``), so -2.00 % halts and -1.99 % does not. Daily and weekly halts last until
the next boundary and expire by time, not by a recovery; the drawdown pause lasts until ``/resume``. Every comparison
is exact Decimal arithmetic (a product, never a rounded quotient).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from copytrade.paper.settings import MONEY_CONTEXT
from copytrade.risk.settings import RiskSettings
from copytrade.risk.state import DAYS_PER_WEEK, MS_PER_DAY, RiskState, utc_day_start_ms, utc_week_start_ms

DAILY_LOSS = "daily_loss"
WEEKLY_LOSS = "weekly_loss"
DRAWDOWN = "drawdown"


@dataclass(frozen=True)
class Halt:
    """A limit that was hit by this mark. ``reference_equity_usd`` is the day's or week's opening equity, or the
    peak for a drawdown; ``until_ms`` is when a daily or weekly halt ends (``None``: until ``/resume``)."""

    reason: str
    equity_usd: Decimal
    reference_equity_usd: Decimal
    limit: Decimal
    until_ms: int | None


def apply_mark(
    state: RiskState,
    *,
    now_ms: int,
    equity_usd: Decimal,
    settings: RiskSettings,
) -> tuple[RiskState, tuple[Halt, ...]]:
    """Fold one known, positive equity mark taken at ``now_ms`` into ``state``.

    A mark stamped before the current day or week (a clock that stepped back) never rolls the period backwards, so
    a halt can not be cleared by a bad timestamp."""
    daily_limit, weekly_limit, max_drawdown = (
        settings.daily_loss_limit,
        settings.weekly_loss_limit,
        settings.max_drawdown,
    )
    halts: list[Halt] = []
    day_start = utc_day_start_ms(now_ms)
    if state.day_start_ms is not None:
        day_start = max(day_start, state.day_start_ms)
    if day_start != state.day_start_ms:
        state = replace(state, day_start_ms=day_start, day_open_equity_usd=equity_usd, daily_halt_until_ms=None)
    week_start = utc_week_start_ms(now_ms)
    if state.week_start_ms is not None:
        week_start = max(week_start, state.week_start_ms)
    if week_start != state.week_start_ms:
        state = replace(state, week_start_ms=week_start, week_open_equity_usd=equity_usd, weekly_halt_until_ms=None)
    peak = equity_usd if state.peak_equity_usd is None else max(state.peak_equity_usd, equity_usd)
    state = replace(state, peak_equity_usd=peak)

    day_open, week_open = state.day_open_equity_usd, state.week_open_equity_usd
    if state.daily_halt_until_ms is None and day_open is not None and _lost(day_open, equity_usd, daily_limit):
        until = day_start + MS_PER_DAY
        state = replace(state, daily_halt_until_ms=until)
        halts.append(Halt(DAILY_LOSS, equity_usd, day_open, daily_limit, until))
    if state.weekly_halt_until_ms is None and week_open is not None and _lost(week_open, equity_usd, weekly_limit):
        until = week_start + DAYS_PER_WEEK * MS_PER_DAY
        state = replace(state, weekly_halt_until_ms=until)
        halts.append(Halt(WEEKLY_LOSS, equity_usd, week_open, weekly_limit, until))
    if not state.drawdown_pause and _lost(peak, equity_usd, max_drawdown):
        state = replace(state, drawdown_pause=True)
        halts.append(Halt(DRAWDOWN, equity_usd, peak, max_drawdown, None))
    return state, tuple(halts)


def _lost(reference_usd: Decimal, equity_usd: Decimal, limit: Decimal) -> bool:
    """Whether ``reference - equity >= limit x reference``."""
    loss_usd = MONEY_CONTEXT.subtract(reference_usd, equity_usd)
    return loss_usd >= MONEY_CONTEXT.multiply(limit, reference_usd)
