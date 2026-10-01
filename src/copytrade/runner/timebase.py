"""The F11 time-base contract for the loop (advance on every iteration, never while unsynced, jump guard)."""

from __future__ import annotations

from copytrade.core.clock import Clock
from copytrade.core.errors import ClockUnsyncedError
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
        self._exchange_time = exchange_time
        self._clock = clock
        self._allowance_ms = 2 * max_offset_uncertainty_ms
        self._last_target_ms: int | None = None
        self._last_local_ms = 0

    def next_target_ms(self) -> tuple[int | None, str | None]:
        """``(target_ms, None)`` to advance to, or ``(None, reason)`` with ``SKIP_CLOCK_UNSYNCED`` or
        ``SKIP_CLOCK_JUMP``."""
        try:
            candidate = self._exchange_time.exchange_now().ms
        except ClockUnsyncedError:
            return None, SKIP_CLOCK_UNSYNCED
        local = self._clock.now_ms()
        last = self._last_target_ms
        if last is None:
            self._last_target_ms, self._last_local_ms = candidate, local
            return candidate, None
        elapsed_ms = max(0, local - self._last_local_ms)
        if candidate - last > elapsed_ms + self._allowance_ms:
            return None, SKIP_CLOCK_JUMP
        target = max(candidate, last)
        self._last_target_ms, self._last_local_ms = target, local
        return target, None
