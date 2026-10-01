"""The F11 time-base contract for the loop (advance on every iteration, never while unsynced, jump guard)."""

from __future__ import annotations

from copytrade.core.clock import Clock, ClockSync, TimeSource, Timestamp
from copytrade.core.domain import ActionKind
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
        self._accepting = False

    def next_target_ms(self) -> tuple[int | None, str | None]:
        """``(target_ms, None)`` to advance to, or ``(None, reason)`` with ``SKIP_CLOCK_UNSYNCED`` or
        ``SKIP_CLOCK_JUMP``."""
        try:
            candidate = self._exchange_time.exchange_now().ms
        except ClockUnsyncedError:
            self._accepting = False
            return None, SKIP_CLOCK_UNSYNCED
        local = self._clock.now_ms()
        last = self._last_target_ms
        if last is None:
            self._last_target_ms, self._last_local_ms = candidate, local
            self._accepting = True
            return candidate, None
        elapsed_ms = max(0, local - self._last_local_ms)
        if candidate - last > elapsed_ms + self._allowance_ms:
            self._accepting = False
            return None, SKIP_CLOCK_JUMP
        target = max(candidate, last)
        self._last_target_ms, self._last_local_ms = target, local
        self._accepting = True
        return target, None

    def projected_ms(self) -> int | None:
        """The last accepted target moved forward by the local time since it was accepted, or ``None`` while the latest
        sample was refused (unsynced or a jump) or none was taken yet. This is what the gate and the position manager
        read between loop iterations (Telegram commands, flatten), so no raw, unguarded clock reaches the broker."""
        if not self._accepting or self._last_target_ms is None:
            return None
        return self._last_target_ms + max(0, self._clock.now_ms() - self._last_local_ms)


class SyncedExchangeTime:
    """``ExchangeTime`` over ``ClockSync`` that raises ``ClockUnsyncedError`` whenever the sync says entries must be
    refused (no estimate, too uncertain, too old), not only before the first estimate."""

    def __init__(self, sync: ClockSync) -> None:
        self._sync = sync

    def exchange_now(self) -> Timestamp:
        if self._sync.refusal_reason(ActionKind.OPEN) is not None:
            raise ClockUnsyncedError("the exchange clock is unsynced")
        return self._sync.exchange_now()


class GuardedExchangeTime:
    """``ExchangeTime`` for the risk gate and the position manager: the time base's guarded clock. It raises
    ``ClockUnsyncedError`` while the time base refuses the clock (unsynced or a jump), so an entry is refused and an
    exit is stamped with the last exchange time the gate saw."""

    def __init__(self, timebase: TimeBase) -> None:
        self._timebase = timebase

    def exchange_now(self) -> Timestamp:
        ms = self._timebase.projected_ms()
        if ms is None:
            raise ClockUnsyncedError("the guarded exchange clock is not available")
        return Timestamp(ms=ms, source=TimeSource.DERIVED)
