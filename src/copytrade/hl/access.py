"""Access-degraded detection (F3.AC5, K10)."""

from __future__ import annotations

import logging
import re
from collections import deque
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert, AlertSink
from copytrade.hl.ledger_port import DowntimeRecord, DowntimeSink

ACCESS_DEGRADED = "access_degraded"
DOWNTIME_KIND = "access_degraded"
RECOVERY_MIN_SUCCESS_PERCENT = 95  # spec F3.AC5: the state clears on minutes with a success rate of at least 95%

_MINUTE_MS = 60_000
_ACCESS_STATUSES = frozenset({403, 451})
_ENTRY_ACTIONS = frozenset({ActionKind.OPEN, ActionKind.ADD})
_BODY_SCAN_CHARS = 4096
# Phrasing of a geo-block body. No recorded real sample exists yet (test-plan D4): two shapes, "<blocked> ... <place>"
# and "<place> ... <blocked>", plus the explicit "geo-block" spellings. Extend when a real body is captured.
_BLOCKED = r"(?:unavailable|not\s+available|blocked|restricted|prohibited|not\s+permitted|not\s+supported|forbidden)"
_PLACE = r"(?:region|jurisdiction|country|territory|location)"
_REGION_BLOCK = re.compile(
    rf"\bgeo-?\s?(?:block|restrict)|\b{_BLOCKED}\b[^.]{{0,60}}\b{_PLACE}\b|\b{_PLACE}\b[^.]{{0,60}}\b{_BLOCKED}\b",
    re.IGNORECASE,
)
_log = logging.getLogger(__name__)


def is_region_block_body(body: str) -> bool:
    """True when a response body says the service is blocked for the caller's region/jurisdiction."""
    return _REGION_BLOCK.search(body[:_BODY_SCAN_CHARS]) is not None


class AccessMonitor:
    """Tracks REST outcomes; enters ``access_degraded`` and leaves it per F3.AC5.

    Outcome classes: 403, 451 and region-block bodies are *access errors*; HTTP 2xx is a *success*; timeouts,
    5xx and other 4xx are failures; HTTP 429 is neither (rate limiting is not access denial) and is ignored.

    Entering the state is immediate (recorded outcomes are evaluated as they arrive) so that refusals never
    wait for the next ``tick``. ``tick`` sends the alert and evaluates recovery: the state clears after
    ``access.recover_min`` consecutive whole minutes (counted from the moment it tripped) that each had traffic
    and a success rate of at least 95%. A minute without traffic is not healthy, so silence never clears it.
    The success-rate trigger applies to any sample size (no minimum-sample rule exists in the spec).
    """

    def __init__(self, *, config: Mapping[str, Any], clock: Clock, alerts: AlertSink, ledger: DowntimeSink) -> None:
        self._error_count = int(config["access.degraded_error_count"])
        self._window_ms = int(config["access.degraded_window_min"]) * _MINUTE_MS
        self._min_success_rate = Decimal(str(config["access.degraded_min_success_rate"]))
        self._recover_min = int(config["access.recover_min"])
        self._clock = clock
        self._alerts = alerts
        self._ledger = ledger
        self._outcomes: deque[tuple[int, bool]] = deque()  # (time, success) of every counted request in the window
        self._successes = 0
        self._access_errors: deque[int] = deque()
        self._degraded = False
        self._degraded_since_ms = 0
        self._reason = ""
        self._alert_sent = False
        self._bucket_start_ms = 0
        self._bucket_successes = 0
        self._bucket_failures = 0
        self._healthy_minutes = 0

    def record_response(self, status: int, body: str = "") -> None:
        """Record one HTTP response."""
        if status == 429:
            return
        if 200 <= status < 300:
            self._observe(success=True, access_error=False)
            return
        access_error = status in _ACCESS_STATUSES or is_region_block_body(body)
        self._observe(success=False, access_error=access_error)

    def record_timeout(self) -> None:
        """Record one request that timed out or failed at the connection level."""
        self._observe(success=False, access_error=False)

    def tick(self) -> None:
        """Called at least once per second: re-evaluates recovery and sends the alert. Never raises."""
        if not self._degraded:
            return
        now = self._clock.now_ms()
        self._advance_bucket(now)
        if not self._alert_sent:
            self._send_alert()
        if self._healthy_minutes >= self._recover_min:
            self._clear(now)

    @property
    def degraded(self) -> bool:
        return self._degraded

    def refusal_reason(self, action: ActionKind) -> str | None:
        """``"access_degraded"`` for OPEN/ADD while degraded; ``None`` otherwise (exits are never refused)."""
        return ACCESS_DEGRADED if self._degraded and action in _ENTRY_ACTIONS else None

    def _observe(self, *, success: bool, access_error: bool) -> None:
        now = self._clock.now_ms()
        if self._degraded:
            self._advance_bucket(now)
            if success:
                self._bucket_successes += 1
            else:
                self._bucket_failures += 1
            return
        self._expire(now)
        self._outcomes.append((now, success))
        self._successes += success
        if access_error:
            self._access_errors.append(now)
        self._evaluate_trip(now)

    def _expire(self, now: int) -> None:
        while self._outcomes and now - self._outcomes[0][0] >= self._window_ms:
            _, success = self._outcomes.popleft()
            self._successes -= success
        while self._access_errors and now - self._access_errors[0] >= self._window_ms:
            self._access_errors.popleft()

    def _evaluate_trip(self, now: int) -> None:
        total = len(self._outcomes)
        if len(self._access_errors) >= self._error_count:
            self._trip(now, f"{len(self._access_errors)} access errors (403/451/region block) within the window")
        elif total and Decimal(self._successes) < self._min_success_rate * total:
            self._trip(now, f"REST success rate {self._successes}/{total} is below {self._min_success_rate}")

    def _trip(self, now: int, reason: str) -> None:
        self._degraded = True
        self._degraded_since_ms = now
        self._reason = reason
        self._alert_sent = False
        self._bucket_start_ms = now
        self._bucket_successes = 0
        self._bucket_failures = 0
        self._healthy_minutes = 0
        _log.warning("hyperliquid access degraded", extra={"event": "access_degraded", "reason": reason})

    def _advance_bucket(self, now: int) -> None:
        """Finalise the whole one-minute buckets that have elapsed since the state tripped."""
        elapsed = now - self._bucket_start_ms
        if elapsed < 0:  # the local clock stepped back: what was counted so far proves nothing
            self._bucket_start_ms = now
            self._bucket_successes = self._bucket_failures = self._healthy_minutes = 0
            return
        minutes = elapsed // _MINUTE_MS
        if minutes == 0:
            return
        healthy = self._bucket_is_healthy()
        self._healthy_minutes = self._healthy_minutes + 1 if healthy and minutes == 1 else 0
        self._bucket_successes = self._bucket_failures = 0
        self._bucket_start_ms += minutes * _MINUTE_MS

    def _bucket_is_healthy(self) -> bool:
        total = self._bucket_successes + self._bucket_failures
        return total > 0 and self._bucket_successes * 100 >= RECOVERY_MIN_SUCCESS_PERCENT * total

    def _send_alert(self) -> None:
        message = (
            f"Hyperliquid access degraded ({self._reason}): opens and adds are refused; exits, reconciliation "
            "and recording keep retrying"
        )
        try:
            self._alerts.send(Alert(kind=ACCESS_DEGRADED, message=message))
        except OSError as exc:
            _log.warning(
                "access alert delivery failed; retrying on the next tick",
                extra={"event": "access_alert_failed", "error_type": type(exc).__name__},
            )
            return
        self._alert_sent = True

    def _clear(self, now: int) -> None:
        record = DowntimeRecord(
            kind=DOWNTIME_KIND,
            start_ms=self._degraded_since_ms,
            end_ms=max(now, self._degraded_since_ms + 1),
            wallets=(),
        )
        try:
            self._ledger.record_downtime(record)
        except OSError as exc:  # stay degraded (fail closed) and retry the write on the next tick
            _log.warning(
                "access downtime could not be ledgered; staying degraded",
                extra={"event": "access_downtime_write_failed", "error_type": type(exc).__name__},
            )
            return
        self._degraded = False
        self._outcomes.clear()
        self._successes = 0
        self._access_errors.clear()
        _log.info("hyperliquid access restored", extra={"event": "access_restored"})
