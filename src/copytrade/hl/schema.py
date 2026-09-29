"""Whole-response validation of Hyperliquid payloads (F3.AC6)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.events import AlertSink

SCHEMA_FAILURE_ALERT = "schema_failure"


def parse_response(request_type: str, payload: Any) -> Any:
    """Validate and convert the decoded JSON ``payload`` of info request ``request_type``.

    Returns: ``allMids`` -> ``dict[str, Price]``; ``l2Book`` -> ``L2Book``; ``clearinghouseState`` ->
    ``ClearinghouseState``; ``userFills`` / ``userFillsByTime`` -> ``tuple[Fill, ...]``; ``candleSnapshot`` ->
    ``tuple[Candle, ...]``; ``userRole`` -> ``str``; ``portfolio`` -> ``dict[str, PortfolioWindow]``.

    Raises:
        HlSchemaError: any missing field, wrong type (numbers must be JSON strings, ids and times JSON ints,
            JSON floats are wrong), non-finite or negative price, or unknown request type. Nothing is returned
            partially.
    """
    raise NotImplementedError


def parse_ws_fills(message: Any) -> tuple[str, bool, tuple[Any, ...]]:
    """Validate a WS ``userFills`` channel message; return ``(user, is_snapshot, fills)``.

    Raises:
        HlSchemaError: endpoint ``"ws:userFills"``; the whole message is rejected.
    """
    raise NotImplementedError


class SchemaFailureMonitor:
    """Counts schema failures per endpoint; the 3rd within 10 minutes on one endpoint sends one alert
    (kind ``schema_failure``, message naming the endpoint). Further failures in the same episode send none."""

    def __init__(self, *, clock: Clock, alerts: AlertSink) -> None:
        raise NotImplementedError

    def record_failure(self, endpoint: str) -> None:
        raise NotImplementedError


ParseFn = Callable[[str, Any], Any]
