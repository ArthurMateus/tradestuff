"""The outgoing queue (F14.AC3, AC8): strict FIFO, capped, aged out, rate limited per chat, with bounded backoff.

``put`` only enqueues (never blocks, never raises). ``flush`` does one delivery pass and stops at the first failure,
so a Telegram outage, a 429 or a slow reply can never hold up trading: nothing here sleeps and every request has
the API's timeout. A rejected message (4xx) is dropped, not retried forever.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from copytrade.core.clock import Clock
from copytrade.telegram.api import TelegramApi, TelegramError, TelegramRateLimited, TelegramRejected

_log = logging.getLogger(__name__)

BACKOFF_START_S = 1
BACKOFF_CAP_S = 60
RATE_WINDOW_MS = 60_000


@dataclass
class Outgoing:
    kind: Literal["send", "edit", "delete"]
    chat_id: int
    text: str = ""
    message_id: int | None = None
    enqueued_ms: int = 0
    on_sent: Callable[[int], None] | None = None
    on_dropped: Callable[[], None] | None = None


class Backoff:
    """1 s doubling to a 60 s cap; a ``retry_after`` from the server overrides one step."""

    def __init__(self) -> None:
        self._next_s = BACKOFF_START_S
        self.until_ms = 0

    def failed(self, now_ms: int, *, retry_after_s: int | None = None) -> None:
        wait_s = self._next_s if retry_after_s is None else retry_after_s
        self.until_ms = now_ms + wait_s * 1000
        self._next_s = min(self._next_s * 2, BACKOFF_CAP_S)

    def succeeded(self) -> None:
        self._next_s = BACKOFF_START_S
        self.until_ms = 0

    def waiting(self, now_ms: int) -> bool:
        return now_ms < self.until_ms


class Outbox:
    def __init__(
        self, api: TelegramApi, clock: Clock, *, max_messages: int, max_age_ms: int, per_chat_per_min: int
    ) -> None:
        self._api = api
        self._clock = clock
        self._max_messages = max_messages
        self._max_age_ms = max_age_ms
        self._per_chat_per_min = per_chat_per_min
        self._queue: deque[Outgoing] = deque()
        self._lock = threading.Lock()
        self._sent_at: dict[int, deque[int]] = {}
        self._backoff = Backoff()

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._queue)

    def put(self, item: Outgoing) -> None:
        item.enqueued_ms = self._clock.now_ms()
        with self._lock:
            self._queue.append(item)
            dropped = [self._queue.popleft() for _ in range(max(0, len(self._queue) - self._max_messages))]
        for old in dropped:
            self._drop(old, "queue_full")

    def flush(self) -> None:
        """One delivery pass: oldest first, until the queue is empty, a chat hits its cap or a call fails."""
        self._drop_aged()
        while not self._backoff.waiting(self._clock.now_ms()):
            with self._lock:
                head = self._queue[0] if self._queue else None
            if head is None or self._chat_capped(head.chat_id):
                return
            if not self._deliver(head):
                return

    # ------------------------------------------------------------------------------------------------ internals

    def _deliver(self, item: Outgoing) -> bool:
        try:
            message_id = self._call(item)
        except TelegramRateLimited as exc:
            self._backoff.failed(self._clock.now_ms(), retry_after_s=exc.retry_after_s)
            _log.warning("telegram rate limited", extra={"event": "telegram_rate_limited", "wait_s": exc.retry_after_s})
            return False
        except TelegramRejected as exc:
            _log.warning("telegram rejected a message", extra={"event": "telegram_rejected", "reason": str(exc)})
            self._pop(item)
            self._drop(item, "rejected")
            return True
        except TelegramError as exc:
            self._backoff.failed(self._clock.now_ms())
            _log.warning("telegram unavailable", extra={"event": "telegram_unavailable", "reason": str(exc)})
            return False
        self._backoff.succeeded()
        self._sent_at.setdefault(item.chat_id, deque()).append(self._clock.now_ms())
        self._pop(item)
        if item.on_sent is not None and message_id is not None:
            item.on_sent(message_id)
        return True

    def _call(self, item: Outgoing) -> int | None:
        if item.kind == "send":
            return self._api.send_message(item.chat_id, item.text)
        if item.message_id is None:
            raise TelegramRejected("an edit or delete needs a message id")
        if item.kind == "edit":
            self._api.edit_message_text(item.chat_id, item.message_id, item.text)
        else:
            self._api.delete_message(item.chat_id, item.message_id)
        return None

    def _chat_capped(self, chat_id: int) -> bool:
        sent = self._sent_at.get(chat_id)
        if sent is None:
            return False
        now = self._clock.now_ms()
        while sent and now - sent[0] >= RATE_WINDOW_MS:
            sent.popleft()
        return len(sent) >= self._per_chat_per_min

    def _pop(self, item: Outgoing) -> None:
        with self._lock:
            if self._queue and self._queue[0] is item:
                self._queue.popleft()

    def _drop_aged(self) -> None:
        now = self._clock.now_ms()
        with self._lock:
            aged = [i for i in self._queue if now - i.enqueued_ms > self._max_age_ms]
            if aged:
                self._queue = deque(i for i in self._queue if now - i.enqueued_ms <= self._max_age_ms)
        for item in aged:
            self._drop(item, "too_old")

    @staticmethod
    def _drop(item: Outgoing, reason: str) -> None:
        _log.warning(
            "telegram message dropped", extra={"event": "telegram_dropped", "reason": reason, "kind": item.kind}
        )
        if item.on_dropped is not None:
            item.on_dropped()
