"""The F11 time-base contract for the loop (Amendment 13): advance on every iteration from a monotonic projection,
entries only with a trusted exchange clock, forced resamples and a two-estimate rebase while in doubt."""

from __future__ import annotations

import time
from collections.abc import Callable

from copytrade.core.clock import Clock, ClockSync, TimeSource, Timestamp
from copytrade.core.domain import ActionKind
from copytrade.core.errors import ClockUnsyncedError
from copytrade.risk.ports import ExchangeTime

DOUBT_RESAMPLE_S = 30  # while in doubt, force a fresh offset estimate this often
REBASE_FRESH_ESTIMATES = 2  # consecutive agreeing fresh estimates that rebase the projection
DOUBT_REALERT_S = 300  # while in doubt with positions open, remind the PO this often
MARKS_STALE_ALERT_N = 5  # consecutive iterations with positions open and no usable mark before an alert
SKIP_CLOCK_UNSYNCED = "clock_unsynced"
SKIP_CLOCK_JUMP = "clock_jump"
ALERT_CLOCK_JUMP = "clock_jump"
ALERT_CLOCK_UNSYNCED = "clock_unsynced"
ALERT_CLOCK_REBASED = "clock_rebased"
ALERT_CLOCK_IN_DOUBT = "clock_in_doubt"
ALERT_LOOP_STALLED = "loop_stalled"


def _real_monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _no_resample() -> bool:
    return False


def _no_live_time() -> int | None:
    return None


class TimeBase:
    """Turns ``ExchangeTime.exchange_now()`` into the broker time of one loop iteration (F11 Amendment 13).

    Broker time is a MONOTONIC PROJECTION: the last accepted exchange target plus the monotonic time elapsed since,
    never
    backwards, so exits, stops, liquidations and delistings are driven on every iteration whatever the exchange clock
    does. ENTRIES need a trusted exchange clock: the clock is IN DOUBT while it raises (unsynced, too uncertain, too
    old), or while a candidate is more than ``2 x max_offset_uncertainty_ms`` away from the projection (ahead or
    behind, RISK-29), or while a restart baseline is unverified and no synced candidate has arrived. While in doubt a
    fresh offset estimate is forced every ``DOUBT_RESAMPLE_S``; two consecutive fresh estimates that agree rebase the
    projection onto the exchange (one forward jump, or a hold of broker time while the exchange is behind it).
    The wall clock is only used by the offset estimate; a wall step never moves broker time."""

    def __init__(  # noqa: PLR0913 - the injected boundaries of one object
        self,
        *,
        exchange_time: ExchangeTime,
        clock: Clock,
        max_offset_uncertainty_ms: int,
        monotonic_ms: Callable[[], int] = _real_monotonic_ms,
        resample: Callable[[], bool] = _no_resample,
        live_time_ms: Callable[[], int | None] = _no_live_time,
    ) -> None:
        self._exchange_time = exchange_time
        self._clock = clock
        self._allowance_ms = 2 * max_offset_uncertainty_ms
        self._mono = monotonic_ms
        self._resample = resample
        self._live_time_ms = live_time_ms
        self._base_target_ms: int | None = None
        self._base_mono_ms = 0
        self._frozen = False  # broker time is held flat (the exchange is behind it after a backward rebase)
        self._unverified = False
        self._in_doubt = False
        self._reason: str | None = None
        self._next_resample_ms = 0
        self._fresh_offsets: list[int] = []
        self.rebase_count = 0

    @property
    def in_doubt(self) -> bool:
        return self._in_doubt

    @property
    def reason(self) -> str | None:
        """``SKIP_CLOCK_UNSYNCED`` / ``SKIP_CLOCK_JUMP`` while the clock is in doubt, else ``None``."""
        return self._reason

    def monotonic_ms(self) -> int:
        return self._mono()

    def seed_unverified(self, ms: int) -> None:
        """After a restart with positions and an unsynced clock: the replayed broker time, projected with monotonic
        time. The first synced candidate is accepted without the jump guard (a forward-only catch-up)."""
        self._set_base(ms)
        self._unverified = True

    def next_target_ms(self) -> tuple[int | None, str | None]:
        """``(broker_target, doubt_reason)``. The target is ``None`` only while no baseline exists at all; the reason is
        ``None`` when the exchange clock is trusted (entries allowed)."""
        candidate = self._candidate()
        if self._base_target_ms is None:
            if candidate is None:
                return None, SKIP_CLOCK_UNSYNCED
            self._set_base(candidate)
            return candidate, None
        projection = self._projection()
        if candidate is not None and self._trusts(candidate, projection):
            return self._accept(candidate, projection), None
        if not self._in_doubt:
            self._in_doubt = True
            self._fresh_offsets = []
            self._next_resample_ms = self._mono() + DOUBT_RESAMPLE_S * 1000
        if not self._frozen and self._mono() >= self._next_resample_ms:
            self._next_resample_ms = self._mono() + DOUBT_RESAMPLE_S * 1000
            if self._resample():
                candidate = self._candidate()
                if candidate is not None and self._trusts(candidate, projection):
                    return self._accept(candidate, projection), None
                rebased = self._take_fresh_estimate(candidate, projection)
                if rebased is not None:
                    return rebased, None
                projection = self._projection()
        self._reason = SKIP_CLOCK_UNSYNCED if candidate is None else SKIP_CLOCK_JUMP
        return self._caught_up(projection), self._reason

    def _caught_up(self, projection: int) -> int:
        """While the restart baseline is unverified the projection runs from the REPLAYED time, which lags the live
        exchange by the downtime, and the paper broker fills only from books at or before broker time (the hub keeps
        seconds of them): a triggered stop or exit would stay pending. So broker time catches up, forward only, to
        ``live_time_ms`` (the newest exchange-stamped book that a second book confirms; never the raw clock estimate:
        a retried request or a wall-clock step would put it ahead of the exchange for good). Entries stay refused:
        the clock is still in doubt."""
        if not self._unverified:
            return projection
        live = self._live_time_ms()
        if live is None or live <= projection:
            return projection
        self._set_base(live)
        return live

    def projected_ms(self) -> int | None:
        """The broker-time projection while the exchange clock is trusted, else ``None`` (the gate refuses entries and
        stamps exits with the last exchange time it saw). What the gate and the manager read between iterations."""
        if self._base_target_ms is None or self._in_doubt:
            return None
        return self._projection()

    # ----------------------------------------------------------------------------------------------- internals
    def _candidate(self) -> int | None:
        try:
            return self._exchange_time.exchange_now().ms
        except ClockUnsyncedError:
            return None

    def _projection(self) -> int:
        assert self._base_target_ms is not None  # noqa: S101 - callers check for a baseline
        if self._frozen:
            return self._base_target_ms
        return self._base_target_ms + max(0, self._mono() - self._base_mono_ms)

    def _set_base(self, target_ms: int) -> None:
        self._base_target_ms, self._base_mono_ms = target_ms, self._mono()
        self._frozen = False

    def _trusts(self, candidate: int, projection: int) -> bool:
        if self._unverified:
            return True
        if self._frozen:
            return candidate >= projection - self._allowance_ms
        return abs(candidate - projection) <= self._allowance_ms

    def _accept(self, candidate: int, projection: int) -> int:
        target = max(candidate, projection)
        self._set_base(target)
        self._unverified = False
        self._in_doubt = False
        self._reason = None
        self._fresh_offsets = []
        return target

    def _take_fresh_estimate(self, candidate: int | None, projection: int) -> int | None:
        """A forced estimate that is still outside the allowance. ``REBASE_FRESH_ESTIMATES`` consecutive ones whose
        implied offsets (candidate minus monotonic time) agree rebase: the target when the clock is trusted again (the
        exchange is ahead), else ``None`` (the exchange is behind: broker time is held flat until it catches up)."""
        if candidate is None:
            self._fresh_offsets = []
            return None
        offset = candidate - self._mono()
        agreeing = [o for o in self._fresh_offsets if abs(o - offset) <= self._allowance_ms]
        self._fresh_offsets = [*agreeing[-(REBASE_FRESH_ESTIMATES - 1) :], offset]
        if len(self._fresh_offsets) < REBASE_FRESH_ESTIMATES:
            return None
        self.rebase_count += 1
        self._fresh_offsets = []
        if candidate >= projection:
            return self._accept(candidate, projection)
        self._base_target_ms, self._base_mono_ms, self._frozen = projection, self._mono(), True
        return None


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
