"""REST weight budget with a 60 s sliding window and two priority classes (F3.AC1)."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import Enum
from typing import Any, Protocol

from copytrade.core.clock import Clock
from copytrade.hl.errors import HlBudgetError

WINDOW_MS = 60_000
INFO_REQUEST_TYPES: frozenset[str] = frozenset(
    {
        "allMids",
        "l2Book",
        "clearinghouseState",
        "userFills",
        "userFillsByTime",
        "candleSnapshot",
        "userRole",
        "portfolio",
    }
)

_BASE_WEIGHT = 20
_LIGHT_WEIGHT = 2
_LIGHT_TYPES = frozenset({"l2Book", "allMids", "clearinghouseState"})
_ITEMS_PER_EXTRA_WEIGHT: Mapping[str, int] = {
    "userFills": 20,
    "userFillsByTime": 20,
    "userFunding": 20,
    "fundingHistory": 20,
    "candleSnapshot": 60,
}


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
    if items < 0:
        raise ValueError("items must not be negative")
    if request_type in _LIGHT_TYPES:
        return _LIGHT_WEIGHT
    if request_type == "userRole":
        return int(config["hl.weight_userRole"])
    if request_type == "portfolio":
        return int(config["hl.weight_portfolio"])
    items_per_extra = _ITEMS_PER_EXTRA_WEIGHT.get(request_type)
    return _BASE_WEIGHT + (0 if items_per_extra is None else items // items_per_extra)


@dataclass(frozen=True)
class QueuedRequest:
    """A request waiting for budget. ``tag`` is opaque to the budget."""

    tag: str
    weight: int
    priority: Priority


@dataclass(frozen=True)
class _Entry:
    at_ms: int
    weight: int
    priority: Priority


def _check_weight(weight: int) -> None:
    if type(weight) is not int or weight < 0:
        raise ValueError("weight must be a non-negative int")


class RateBudget:
    """Sliding 60 s window: an entry counts against the window for exactly 60 000 ms after its timestamp.

    Never lets total weight in any window exceed ``budget_per_min``, nor SCORING weight exceed
    ``floor(budget_per_min * scoring_share)``. The only way past a limit is ``charge``, which records weight
    that is known only after a response and therefore cannot be refused.

    Single-threaded: one caller drives it (the supervisor loop).
    """

    def __init__(self, *, budget_per_min: int, scoring_share: Decimal, clock: Clock) -> None:
        if type(budget_per_min) is not int or budget_per_min <= 0:
            raise ValueError("budget_per_min must be a positive int")
        if not Decimal(0) < scoring_share <= Decimal(1):
            raise ValueError("scoring_share must be in (0, 1]")
        self._budget = budget_per_min
        self._scoring_cap = int((budget_per_min * scoring_share).to_integral_value(rounding=ROUND_FLOOR))
        self._clock = clock
        self._window: deque[_Entry] = deque()
        self._total = 0
        self._scoring = 0
        self._critical_queue: deque[QueuedRequest] = deque()
        self._scoring_queue: deque[QueuedRequest] = deque()

    @property
    def scoring_cap(self) -> int:
        """``floor(budget_per_min * scoring_share)``."""
        return self._scoring_cap

    def used(self) -> int:
        """Total weight currently inside the window."""
        self._expire()
        return self._total

    def scoring_used(self) -> int:
        """SCORING weight currently inside the window."""
        self._expire()
        return self._scoring

    def try_acquire(self, weight: int, priority: Priority) -> bool:
        """Record ``weight`` now if it fits; return whether it did. A refusal records nothing."""
        _check_weight(weight)
        self._expire()
        if not self._fits(weight, priority, self._total, self._scoring):
            return False
        self._record(weight, priority)
        return True

    def charge(self, weight: int, priority: Priority) -> None:
        """Record extra weight known only after a response (items returned). Never refused, even over the limit."""
        _check_weight(weight)
        self._expire()
        if weight:
            self._record(weight, priority)

    def wait_ms(self, weight: int, priority: Priority) -> int | None:
        """Milliseconds until ``try_acquire`` would succeed (0 = now); ``None`` if it can never succeed."""
        _check_weight(weight)
        if weight > self._budget or (priority is Priority.SCORING and weight > self._scoring_cap):
            return None
        self._expire()
        now = self._clock.now_ms()
        total, scoring = self._total, self._scoring
        if self._fits(weight, priority, total, scoring):
            return 0
        for entry in self._window:
            total -= entry.weight
            if entry.priority is Priority.SCORING:
                scoring -= entry.weight
            if self._fits(weight, priority, total, scoring):
                return max(0, entry.at_ms + WINDOW_MS - now)
        return 0  # unreachable: an empty window always fits a weight that passed the checks above

    def enqueue(self, request: QueuedRequest) -> None:
        """Queue a request for ``drain``.

        Raises:
            HlBudgetError: the request can never fit its class (it would block the queue forever).
        """
        if self.wait_ms(request.weight, request.priority) is None:
            raise HlBudgetError(f"queued request {request.tag!r} can never fit the {request.priority.value} budget")
        queue = self._critical_queue if request.priority is Priority.CRITICAL else self._scoring_queue
        queue.append(request)

    def drain(self) -> list[QueuedRequest]:
        """Acquire and return every queued request that fits now: CRITICAL before SCORING, FIFO within a
        class. While any CRITICAL request is still queued after the drain, no SCORING request is returned."""
        served = self._drain_queue(self._critical_queue)
        if not self._critical_queue:
            served += self._drain_queue(self._scoring_queue)
        return served

    def pending(self) -> int:
        """Number of queued requests."""
        return len(self._critical_queue) + len(self._scoring_queue)

    def _drain_queue(self, queue: deque[QueuedRequest]) -> list[QueuedRequest]:
        served: list[QueuedRequest] = []
        while queue and self.try_acquire(queue[0].weight, queue[0].priority):
            served.append(queue.popleft())
        return served

    def _fits(self, weight: int, priority: Priority, total: int, scoring: int) -> bool:
        if total + weight > self._budget:
            return False
        return priority is Priority.CRITICAL or scoring + weight <= self._scoring_cap

    def _record(self, weight: int, priority: Priority) -> None:
        self._window.append(_Entry(self._clock.now_ms(), weight, priority))
        self._total += weight
        if priority is Priority.SCORING:
            self._scoring += weight

    def _expire(self) -> None:
        now = self._clock.now_ms()
        while self._window and now - self._window[0].at_ms >= WINDOW_MS:
            entry = self._window.popleft()
            self._total -= entry.weight
            if entry.priority is Priority.SCORING:
                self._scoring -= entry.weight


class Sleeper(Protocol):
    """Blocks for a number of seconds. An external boundary; tests inject a fake that advances the fake clock."""

    def sleep(self, seconds: float) -> None: ...
