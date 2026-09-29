"""INFO-ONLY Hyperliquid REST client (F3.AC1, F3.AC2, F3.AC5, F3.AC6)."""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from copytrade.core.clock import Clock
from copytrade.core.money import Price
from copytrade.hl.access import AccessMonitor
from copytrade.hl.budget import Priority, RateBudget, Sleeper
from copytrade.hl.models import Candle, ClearinghouseState, Fill, L2Book, PortfolioWindow
from copytrade.hl.schema import SchemaFailureMonitor

MAINNET_INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str


class HttpTransport(Protocol):
    """POSTs JSON text. An external boundary. Raises ``TimeoutError`` on timeout, ``OSError`` on connection failure."""

    def post(self, url: str, body: str, *, timeout_s: float) -> HttpResponse: ...


class StdlibHttpTransport:
    """Real transport over the standard library (loopback-testable)."""

    def post(self, url: str, body: str, *, timeout_s: float) -> HttpResponse:
        raise NotImplementedError


class HlRestClient:
    """POSTs ``{"type": ...}`` bodies to the info URL only.

    ``info_url`` must end in ``/info``; any URL whose path contains the exchange (order) endpoint segment is
    refused at construction (``HlRequestError``). Request types outside ``INFO_REQUEST_TYPES`` are refused
    locally, never sent.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        config: Mapping[str, Any],
        clock: Clock,
        transport: HttpTransport,
        sleeper: Sleeper,
        rng: random.Random,
        budget: RateBudget,
        access: AccessMonitor,
        schema_monitor: SchemaFailureMonitor,
        info_url: str = MAINNET_INFO_URL,
    ) -> None:
        raise NotImplementedError

    def info(self, request_type: str, params: Mapping[str, Any], *, priority: Priority) -> Any:
        """Send one info request and return the validated, typed response (see ``schema.parse_response``).

        Budget is reserved before sending (waiting via the sleeper when needed); 429 and timeouts back off and
        retry up to ``hl.retry_max`` times; every attempt uses ``hl.rest_timeout_s``; other non-2xx statuses raise
        ``HlHttpError`` at once; every outcome is reported to the access monitor; a schema failure is reported to
        the schema monitor and raises ``HlSchemaError``.

        Raises:
            HlRequestError, HlHttpError, HlRateLimitedError, HlTimeoutError, HlBudgetError, HlSchemaError.
        """
        raise NotImplementedError

    def all_mids(self, *, priority: Priority) -> dict[str, Price]:
        raise NotImplementedError

    def l2_book(self, coin: str, *, priority: Priority) -> L2Book:
        raise NotImplementedError

    def clearinghouse_state(self, user: str, *, priority: Priority) -> ClearinghouseState:
        raise NotImplementedError

    def user_fills_by_time(
        self, user: str, start_ms: int, end_ms: int | None, *, priority: Priority
    ) -> tuple[Fill, ...]:
        """Fills with ``startTime`` inclusive, ``aggregateByTime`` true."""
        raise NotImplementedError

    def candles(
        self, coin: str, interval: str, start_ms: int, end_ms: int, *, priority: Priority
    ) -> tuple[Candle, ...]:
        raise NotImplementedError

    def user_role(self, user: str, *, priority: Priority) -> str:
        raise NotImplementedError

    def portfolio(self, user: str, *, priority: Priority) -> dict[str, PortfolioWindow]:
        raise NotImplementedError
