"""Timestamps and clock-offset guard (F1.AC6, invariants B1 and B2).

- Every timestamp is UTC epoch milliseconds (``int``) and carries a ``TimeSource`` tag.
- ``ClockSync`` re-estimates the local-to-exchange clock offset every ``clock.offset_interval_s``.
  While the latest estimate's uncertainty is above ``clock.max_offset_uncertainty_ms``, or no
  successful estimate exists or the last one is older than ``clock.max_estimate_age_s``, opens and
  adds are refused with reason ``"clock_unsynced"`` (fail closed, including before the first estimate),
  exactly one ``Alert(kind="clock_unsynced")`` is sent per unsynced episode, and exits continue.

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from copytrade.core.domain import ActionKind
from copytrade.core.events import AlertSink


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
        raise NotImplementedError

    @classmethod
    def from_datetime(cls, dt: datetime, source: TimeSource) -> Timestamp:
        """Convert an aware datetime (any zone) to UTC epoch ms, truncating sub-millisecond digits.

        Raises:
            ValueError: ``dt`` is naive.
        """
        raise NotImplementedError

    def to_datetime(self) -> datetime:
        """Return the timestamp as an aware UTC datetime."""
        raise NotImplementedError


class Clock(Protocol):
    """The local wall clock. An external boundary; tests inject a fake."""

    def now_ms(self) -> int: ...


class SystemClock:
    """The real local clock (UTC epoch ms)."""

    def now_ms(self) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class OffsetEstimate:
    """One clock-offset estimate. ``offset_ms`` = exchange time - local time."""

    offset_ms: int
    uncertainty_ms: int


class OffsetSource(Protocol):
    """Produces offset estimates (exchange server time or NTP). An external boundary; may raise ``OSError``."""

    def estimate(self) -> OffsetEstimate: ...


class ClockSync:
    """Keeps the clock-offset estimate fresh and gates entries on it."""

    def __init__(
        self,
        *,
        offset_interval_s: int,
        max_offset_uncertainty_ms: int,
        max_estimate_age_s: int,
        clock: Clock,
        source: OffsetSource,
        alerts: AlertSink,
    ) -> None:
        raise NotImplementedError

    @classmethod
    def from_config(
        cls, config: Any, *, clock: Clock, source: OffsetSource, alerts: AlertSink
    ) -> ClockSync:
        """Build from the loaded config's ``clock.*`` keys."""
        raise NotImplementedError

    @property
    def offset_interval_s(self) -> int:
        raise NotImplementedError

    @property
    def max_offset_uncertainty_ms(self) -> int:
        raise NotImplementedError

    @property
    def max_estimate_age_s(self) -> int:
        raise NotImplementedError

    def tick(self) -> None:
        """Called by the scheduler (at least once per second). Re-estimates when
        ``offset_interval_s`` has elapsed since the last attempt (or on the first call), updates
        the synced state and sends alerts. Never raises when the offset source fails."""
        raise NotImplementedError

    def refusal_reason(self, action: ActionKind) -> str | None:
        """``"clock_unsynced"`` for OPEN/ADD while unsynced; ``None`` otherwise. Exits are never refused."""
        raise NotImplementedError

    def exchange_now(self) -> Timestamp:
        """Local now corrected by the latest offset, tagged ``TimeSource.DERIVED``."""
        raise NotImplementedError
