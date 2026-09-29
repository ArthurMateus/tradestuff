"""REST weight budget with a 60 s sliding window and two priority classes (F3.AC1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

from copytrade.core.clock import Clock

INFO_REQUEST_TYPES: frozenset[str] = frozenset()  # filled by the developer: the info types this client may send


class Priority(Enum):
    """CRITICAL: reconciliation, exits, fill audit, candles for open shares. SCORING: leaderboard/scoring traffic."""

    CRITICAL = "critical"
    SCORING = "scoring"


def request_weight(request_type: str, items: int, config: Mapping[str, Any]) -> int:
    """Weight of one info request that returned ``items`` items.

    20 base; 2 for ``l2Book``, ``allMids``, ``clearinghouseState``; ``config['hl.weight_userRole']`` and
    ``config['hl.weight_portfolio']`` for those two; ``userFills``, ``userFillsByTime``, ``userFunding``,
    ``fundingHistory`` add ``items // 20``; ``candleSnapshot`` adds ``items // 60``.

    Raises:
        ValueError: ``items`` is negative.
    """
    raise NotImplementedError


@dataclass(frozen=True)
class QueuedRequest:
    """A request waiting for budget. ``tag`` is opaque to the budget."""

    tag: str
    weight: int
    priority: Priority


class RateBudget:
    """Sliding 60 s window: an entry counts against the window for exactly 60 000 ms after its timestamp.

    Never lets total weight in any window exceed ``budget_per_min``, nor SCORING weight exceed
    ``floor(budget_per_min * scoring_share)``.
    """

    def __init__(self, *, budget_per_min: int, scoring_share: Decimal, clock: Clock) -> None:
        raise NotImplementedError

    @property
    def scoring_cap(self) -> int:
        """``floor(budget_per_min * scoring_share)``."""
        raise NotImplementedError

    def used(self) -> int:
        """Total weight currently inside the window."""
        raise NotImplementedError

    def scoring_used(self) -> int:
        """SCORING weight currently inside the window."""
        raise NotImplementedError

    def try_acquire(self, weight: int, priority: Priority) -> bool:
        """Record ``weight`` now if it fits; return whether it did. A refusal records nothing."""
        raise NotImplementedError

    def charge(self, weight: int, priority: Priority) -> None:
        """Record extra weight known only after a response (items returned). Never raises."""
        raise NotImplementedError

    def wait_ms(self, weight: int, priority: Priority) -> int | None:
        """Milliseconds until ``try_acquire`` would succeed (0 = now); ``None`` if it can never succeed."""
        raise NotImplementedError

    def enqueue(self, request: QueuedRequest) -> None:
        """Queue a request for ``drain``."""
        raise NotImplementedError

    def drain(self) -> list[QueuedRequest]:
        """Acquire and return every queued request that fits now: CRITICAL before SCORING, FIFO within a
        class. While any CRITICAL request is still queued after the drain, no SCORING request is returned."""
        raise NotImplementedError

    def pending(self) -> int:
        """Number of queued requests."""
        raise NotImplementedError


class Sleeper(Protocol):
    """Blocks for a number of seconds. An external boundary; tests inject a fake that advances the fake clock."""

    def sleep(self, seconds: float) -> None: ...
