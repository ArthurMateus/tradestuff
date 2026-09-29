"""Access-degraded detection (F3.AC5, K10)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.domain import ActionKind
from copytrade.core.events import AlertSink
from copytrade.hl.ledger_port import DowntimeSink

ACCESS_DEGRADED = "access_degraded"


def is_region_block_body(body: str) -> bool:
    """True when a response body says the service is blocked for the caller's region/jurisdiction."""
    raise NotImplementedError


class AccessMonitor:
    """Tracks REST outcomes; enters ``access_degraded`` and leaves it per F3.AC5.

    Outcome classes: 403, 451 and region-block bodies are *access errors*; HTTP 2xx is a *success*; timeouts,
    5xx and other 4xx are failures; HTTP 429 is neither (rate limiting is not access denial) and is ignored.
    """

    def __init__(self, *, config: Mapping[str, Any], clock: Clock, alerts: AlertSink, ledger: DowntimeSink) -> None:
        raise NotImplementedError

    def record_response(self, status: int, body: str = "") -> None:
        """Record one HTTP response."""
        raise NotImplementedError

    def record_timeout(self) -> None:
        """Record one request that timed out or failed at the connection level."""
        raise NotImplementedError

    def tick(self) -> None:
        """Called at least once per second: re-evaluates recovery and sends the alert. Never raises."""
        raise NotImplementedError

    @property
    def degraded(self) -> bool:
        raise NotImplementedError

    def refusal_reason(self, action: ActionKind) -> str | None:
        """``"access_degraded"`` for OPEN/ADD while degraded; ``None`` otherwise (exits are never refused)."""
        raise NotImplementedError
