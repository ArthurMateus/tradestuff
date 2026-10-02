"""Timestamps and clock-offset guard (F1.AC6, invariants B1 and B2).

- Every timestamp is UTC epoch milliseconds (``int``) and carries a ``TimeSource`` tag.
- ``ClockSync`` re-estimates the local-to-exchange clock offset every ``clock.offset_interval_s``.
  While the latest estimate's uncertainty is above ``clock.max_offset_uncertainty_ms``, or no
  successful estimate exists or the last one is older than ``clock.max_estimate_age_s``, opens and
  adds are refused with reason ``"clock_unsynced"`` (fail closed, including before the first estimate),
  exactly one ``Alert(kind="clock_unsynced")`` is sent per unsynced episode, and exits continue.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Protocol

from copytrade.core.domain import ActionKind
from copytrade.core.errors import ClockUnsyncedError
from copytrade.core.events import Alert, AlertSink

CLOCK_UNSYNCED = "clock_unsynced"
_ENTRY_ACTIONS = frozenset({ActionKind.OPEN, ActionKind.ADD})
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLISECOND = timedelta(milliseconds=1)
_log = logging.getLogger(__name__)


class TimeSource(Enum):
    """Where a timestamp came from."""

    EXCHANGE = "exchange"
    LOCAL = "local"
    DERIVED = "derived"


@dataclass(frozen=True)
class Timestamp:
    """UTC epoch milliseconds with a source tag.

    Raises ``TypeError`` when ``ms`` is not an ``int`` (floats and bools are rejected) or ``source`` is
    not a ``TimeSource``.
    """

    ms: int
    source: TimeSource

    def __post_init__(self) -> None:
        if type(self.ms) is not int:
            raise TypeError(f"Timestamp.ms must be an int of epoch milliseconds, not {type(self.ms).__name__}")
        if not isinstance(self.source, TimeSource):
            raise TypeError("Timestamp.source must be a TimeSource")

    @classmethod
    def from_datetime(cls, dt: datetime, source: TimeSource) -> Timestamp:
        """Convert an aware datetime (any zone) to UTC epoch ms, truncating sub-millisecond digits.

        Raises:
            ValueError: ``dt`` is naive.
        """
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("a naive datetime has no defined UTC instant")
        return cls(ms=(dt.astimezone(UTC) - _EPOCH) // _MILLISECOND, source=source)

    def to_datetime(self) -> datetime:
        """Return the timestamp as an aware UTC datetime."""
        return _EPOCH + timedelta(milliseconds=self.ms)


class Clock(Protocol):
    """The local wall clock. An external boundary; tests inject a fake."""

    def now_ms(self) -> int: ...


class SystemClock:
    """The real local clock (UTC epoch ms)."""

    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


@dataclass(frozen=True)
class OffsetEstimate:
    """One clock-offset estimate. ``offset_ms`` = exchange time - local time."""

    offset_ms: int
    uncertainty_ms: int

    def __post_init__(self) -> None:
        for name in ("offset_ms", "uncertainty_ms"):
            if type(getattr(self, name)) is not int:
                raise TypeError(f"OffsetEstimate.{name} must be an int of milliseconds")
        if self.uncertainty_ms < 0:
            raise ValueError("OffsetEstimate.uncertainty_ms must not be negative")


class OffsetSource(Protocol):
    """Produces offset estimates (exchange server time or NTP). An external boundary; may raise ``OSError``."""

    def estimate(self) -> OffsetEstimate: ...


def _require_positive_int(name: str, value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive int")


class ClockSync:
    """Keeps the clock-offset estimate fresh and gates entries on it.

    Entries (OPEN, ADD) are refused with ``"clock_unsynced"`` while there is no estimate, the latest
    estimate is uncertain by more than ``max_offset_uncertainty_ms``, or it is older than
    ``max_estimate_age_s`` (or the local clock stepped backwards since it was taken). The refusal is a
    pure function of that state and the local clock, so it takes effect at once and does not depend on
    how often ``tick`` runs; ``tick`` only re-estimates and sends the once-per-episode alert.
    """

    def __init__(  # noqa: PLR0913 - keyword-only wiring of one object's collaborators and thresholds
        self,
        *,
        offset_interval_s: int,
        max_offset_uncertainty_ms: int,
        max_estimate_age_s: int,
        clock: Clock,
        source: OffsetSource,
        alerts: AlertSink,
    ) -> None:
        _require_positive_int("offset_interval_s", offset_interval_s)
        _require_positive_int("max_offset_uncertainty_ms", max_offset_uncertainty_ms)
        _require_positive_int("max_estimate_age_s", max_estimate_age_s)
        self._offset_interval_s = offset_interval_s
        self._max_offset_uncertainty_ms = max_offset_uncertainty_ms
        self._max_estimate_age_s = max_estimate_age_s
        self._clock = clock
        self._source = source
        self._alerts = alerts
        self._last_attempt_ms: int | None = None
        self._estimate: OffsetEstimate | None = None
        self._estimate_taken_ms = 0
        self._alert_sent = False

    @classmethod
    def from_config(cls, config: Any, *, clock: Clock, source: OffsetSource, alerts: AlertSink) -> ClockSync:
        """Build from the loaded config's ``clock.*`` keys."""
        return cls(
            offset_interval_s=config["clock.offset_interval_s"],
            max_offset_uncertainty_ms=config["clock.max_offset_uncertainty_ms"],
            max_estimate_age_s=config["clock.max_estimate_age_s"],
            clock=clock,
            source=source,
            alerts=alerts,
        )

    @property
    def offset_interval_s(self) -> int:
        return self._offset_interval_s

    @property
    def max_offset_uncertainty_ms(self) -> int:
        return self._max_offset_uncertainty_ms

    @property
    def max_estimate_age_s(self) -> int:
        return self._max_estimate_age_s

    def tick(self) -> None:
        """Called by the scheduler (at least once per second). Re-estimates when
        ``offset_interval_s`` has elapsed since the last attempt (or on the first call), updates
        the synced state and sends alerts. Never raises when the offset source fails."""
        now = self._clock.now_ms()
        if self._estimate_due(now):
            self._last_attempt_ms = now
            self._try_estimate(now)
        problem = self._problem(now)
        if problem is None:
            self._alert_sent = False
        elif not self._alert_sent:
            self._send_alert(problem)

    def resample(self) -> bool:
        """Force a fresh offset estimate now (the time base does this while the clock is in doubt). ``True`` when one
        was taken; ``False`` when the source failed and the previous estimate stands. Never raises for a source
        failure."""
        now = self._clock.now_ms()
        self._last_attempt_ms = now
        return self._try_estimate(now)

    def refusal_reason(self, action: ActionKind) -> str | None:
        """``"clock_unsynced"`` for OPEN/ADD while unsynced; ``None`` otherwise. Exits are never refused."""
        if action in _ENTRY_ACTIONS and self._problem(self._clock.now_ms()) is not None:
            return CLOCK_UNSYNCED
        return None

    def exchange_now(self) -> Timestamp:
        """Local now corrected by the latest offset, tagged ``TimeSource.DERIVED``.

        Raises:
            ClockUnsyncedError: no offset has been estimated yet.
        """
        if self._estimate is None:
            raise ClockUnsyncedError("no clock-offset estimate exists yet")
        return Timestamp(ms=self._clock.now_ms() + self._estimate.offset_ms, source=TimeSource.DERIVED)

    def _estimate_due(self, now: int) -> bool:
        if self._last_attempt_ms is None:
            return True
        elapsed = now - self._last_attempt_ms
        return elapsed < 0 or elapsed >= self._offset_interval_s * 1000

    def _try_estimate(self, now: int) -> bool:
        try:
            estimate = self._source.estimate()
        except (OSError, ValueError) as exc:
            _log.warning(
                "clock offset estimate failed",
                extra={"event": "clock_offset_failed", "error_type": type(exc).__name__},
            )
            return False
        self._estimate = estimate
        self._estimate_taken_ms = now
        return True

    def _problem(self, now: int) -> str | None:
        """Why entries must be refused, or ``None`` when the clock is synced."""
        estimate = self._estimate
        if estimate is None:
            return "no clock-offset estimate yet"
        age_ms = now - self._estimate_taken_ms
        if age_ms < 0:
            return "the local clock stepped backwards since the last estimate"
        if age_ms > self._max_estimate_age_s * 1000:
            return f"last estimate is {age_ms // 1000} s old (limit {self._max_estimate_age_s} s)"
        if estimate.uncertainty_ms > self._max_offset_uncertainty_ms:
            return f"offset uncertainty {estimate.uncertainty_ms} ms exceeds {self._max_offset_uncertainty_ms} ms"
        return None

    def _send_alert(self, problem: str) -> None:
        try:
            self._alerts.send(Alert(kind=CLOCK_UNSYNCED, message=f"Clock unsynced, entries refused: {problem}"))
        except OSError as exc:
            _log.warning(
                "clock alert delivery failed; retrying on the next tick",
                extra={"event": "clock_alert_failed", "error_type": type(exc).__name__},
            )
            return
        self._alert_sent = True
