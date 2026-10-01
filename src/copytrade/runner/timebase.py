"""The F11 time-base contract for the loop (advance on every iteration, never while unsynced, jump guard)."""

from __future__ import annotations

from copytrade.core.clock import Clock
from copytrade.risk.ports import ExchangeTime

SKIP_CLOCK_UNSYNCED = "clock_unsynced"
SKIP_CLOCK_JUMP = "clock_jump"
ALERT_CLOCK_JUMP = "clock_jump"
ALERT_LOOP_STALLED = "loop_stalled"


class TimeBase:
    """Turns ``ExchangeTime.exchange_now()`` into the target for ``advance_to`` of one loop iteration.

    Pinned guard (RISK-29): a target is accepted when it is at most ``local elapsed since the last accepted target +
    2 x clock.max_offset_uncertainty_ms`` ahead of the last accepted target. A target behind the last one is never
    returned (broker time only moves forward). The first target after construction is accepted as it is."""

    def __init__(self, *, exchange_time: ExchangeTime, clock: Clock, max_offset_uncertainty_ms: int) -> None:
        raise NotImplementedError

    def next_target_ms(self) -> tuple[int | None, str | None]:
        """``(target_ms, None)`` to advance to, or ``(None, reason)`` with ``SKIP_CLOCK_UNSYNCED`` or
        ``SKIP_CLOCK_JUMP``."""
        raise NotImplementedError
