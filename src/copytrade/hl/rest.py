"""INFO-ONLY Hyperliquid REST client (F3.AC1, F3.AC2, F3.AC5, F3.AC6).

The client can only POST ``{"type": ...}`` bodies to one info URL. There is no signing code and no way to
name another endpoint: the base URL is validated against an allow-list (path exactly ``/info``) at construction.
"""

from __future__ import annotations

import http.client
import json
import logging
import math
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from copytrade.core.clock import Clock
from copytrade.core.money import Price
from copytrade.hl.access import AccessMonitor
from copytrade.hl.backoff import backoff_delay_s
from copytrade.hl.budget import INFO_REQUEST_TYPES, Priority, RateBudget, Sleeper, request_weight
from copytrade.hl.errors import (
    HlBudgetError,
    HlConnectionError,
    HlHttpError,
    HlRateLimitedError,
    HlRequestError,
    HlSchemaError,
    HlTimeoutError,
)
from copytrade.hl.models import (
    Candle,
    ClearinghouseState,
    Fill,
    FundingRow,
    L2Book,
    MetaAndCtxs,
    PortfolioWindow,
)
from copytrade.hl.schema import SchemaFailureMonitor, parse_response
from copytrade.hl.wallet import normalize_wallet

MAINNET_INFO_URL = "https://api.hyperliquid.xyz/info"
INFO_PATH = "/info"

_MAX_RESPONSE_BYTES = 32 * 1024 * 1024  # a 5 000-candle or 2 000-fill response is about 1 MB
_READ_CHUNK_BYTES = 64 * 1024
_MAX_NAME_CHARS = 64
_RETRYABLE = (HlTimeoutError, HlConnectionError, HlRateLimitedError)
_log = logging.getLogger(__name__)


def _status_text(exc: Exception) -> str:
    """`` status=N`` for an HTTP failure, else empty (the error text never carries the URL or the body)."""
    status = getattr(exc, "status", None)
    return f" status={status}" if isinstance(status, int) else ""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str


class HttpTransport(Protocol):
    """POSTs JSON text. An external boundary. Raises ``TimeoutError`` on timeout, ``OSError`` on connection failure."""

    def post(self, url: str, body: str, *, timeout_s: float) -> HttpResponse: ...


class StdlibHttpTransport:
    """Real transport over the standard library (loopback-testable).

    One connection per request, no redirects followed, ``timeout_s`` is a deadline for the whole exchange
    (connect, send, and reading the complete body), and the body is size-capped.
    """

    def post(self, url: str, body: str, *, timeout_s: float) -> HttpResponse:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.hostname is None:
            raise ValueError("url must be an absolute http or https URL")
        connection_type = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        deadline = time.monotonic() + timeout_s
        connection = connection_type(parts.hostname, parts.port, timeout=timeout_s)
        try:
            connection.request(
                "POST", parts.path or "/", body=body.encode("utf-8"), headers={"Content-Type": "application/json"}
            )
            response = connection.getresponse()
            data = self._read_body(response, connection, deadline)
        except http.client.HTTPException as exc:  # malformed or truncated HTTP is a connection-level failure
            raise OSError(f"invalid HTTP exchange: {type(exc).__name__}") from exc
        finally:
            connection.close()
        return HttpResponse(status=response.status, body=data.decode("utf-8", errors="replace"))

    @staticmethod
    def _read_body(
        response: http.client.HTTPResponse, connection: http.client.HTTPConnection, deadline: float
    ) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("response not complete before the deadline")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read(_READ_CHUNK_BYTES)
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > _MAX_RESPONSE_BYTES:
                raise OSError("response body exceeds the size cap")
            chunks.append(chunk)


def _validate_info_url(url: str) -> str:
    parts = urlsplit(url)
    allowed = (
        parts.scheme in ("http", "https")
        and parts.hostname is not None
        and parts.path == INFO_PATH
        and not parts.query
        and not parts.fragment
        and parts.username is None
    )
    if not allowed:
        raise HlRequestError("info_url must be an http(s) URL whose path is exactly the info endpoint")
    return url


def _name(value: str, what: str) -> str:
    if type(value) is not str or not value or len(value) > _MAX_NAME_CHARS or not value.isprintable():
        raise HlRequestError(f"{what} must be a short printable non-empty string")
    return value


def _check_time_range(start_ms: int, end_ms: int | None) -> None:
    if (
        type(start_ms) is not int
        or start_ms < 0
        or (end_ms is not None and (type(end_ms) is not int or end_ms < start_ms))
    ):
        raise ValueError("start_ms and end_ms must be non-negative epoch milliseconds with start <= end")


class HlRestClient:
    """POSTs ``{"type": ...}`` bodies to the info URL only.

    ``info_url`` must be an http(s) URL whose path is exactly ``/info``; anything else, in particular any
    path that could reach the order-placing endpoint, is refused at construction (``HlRequestError``). Request
    types outside ``INFO_REQUEST_TYPES`` are refused locally, never sent.

    Synchronous and single-threaded: retries and budget waits block the caller through the injected sleeper.
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
        escalate_cooldown: bool = False,
    ) -> None:
        self._url = _validate_info_url(info_url)
        self._config = config
        self._timeout_s = float(config["hl.rest_timeout_s"])
        self._retry_max = int(config["hl.retry_max"])
        self._backoff_base_s = float(config["hl.backoff_base_s"])
        self._backoff_max_s = float(config["hl.backoff_max_s"])
        self._clock = clock
        self._transport = transport
        self._sleeper = sleeper
        self._rng = rng
        self._budget = budget
        self._access = access
        self._schema_monitor = schema_monitor
        self._cooldown_until_ms: dict[str, int] = {}
        self._rate_limited_in_a_row: dict[str, int] = {}
        self._escalate_cooldown = escalate_cooldown

    def info(self, request_type: str, params: Mapping[str, Any], *, priority: Priority) -> Any:
        """Send one info request and return the validated, typed response (see ``schema.parse_response``).

        Budget is reserved before sending (waiting via the sleeper when needed); 429 and timeouts back off and
        retry up to ``hl.retry_max`` times; every attempt uses ``hl.rest_timeout_s``; other non-2xx statuses raise
        ``HlHttpError`` at once; every outcome is reported to the access monitor; a schema failure is reported to
        the schema monitor and raises ``HlSchemaError``.

        Raises:
            HlRequestError, HlHttpError, HlRateLimitedError, HlTimeoutError, HlConnectionError, HlBudgetError,
            HlSchemaError.
        """
        if request_type not in INFO_REQUEST_TYPES:
            raise HlRequestError("request type is not an allowed info request")
        if "type" in params:
            raise HlRequestError("params must not set the request type")
        body = json.dumps({"type": request_type, **params})
        weight = request_weight(request_type, 0, self._config)
        attempt = 0
        while True:
            try:
                return self._attempt(request_type, body, weight, priority)
            except _RETRYABLE as exc:
                if attempt >= self._retry_max:
                    _log.warning(
                        "info request failed, giving up type=%s attempt=%d%s error=%s",
                        request_type,
                        attempt + 1,
                        _status_text(exc),
                        exc,
                        extra={"event": "hl_giveup"},
                    )
                    raise
                delay_s = backoff_delay_s(
                    attempt, base_s=self._backoff_base_s, max_s=self._backoff_max_s, rng=self._rng
                )
                _log.warning(
                    "info request failed, backing off type=%s attempt=%d delay=%.1fs%s error=%s",
                    request_type,
                    attempt + 1,
                    delay_s,
                    _status_text(exc),
                    exc,
                    extra={"event": "hl_retry"},
                )
                self._sleeper.sleep(delay_s)
                attempt += 1

    def all_mids(self, *, priority: Priority) -> dict[str, Price]:
        result: dict[str, Price] = self.info("allMids", {}, priority=priority)
        return result

    def l2_book(self, coin: str, *, priority: Priority) -> L2Book:
        result: L2Book = self.info("l2Book", {"coin": _name(coin, "coin")}, priority=priority)
        return result

    def clearinghouse_state(self, user: str, *, priority: Priority) -> ClearinghouseState:
        result: ClearinghouseState = self.info(
            "clearinghouseState", {"user": normalize_wallet(user)}, priority=priority
        )
        return result

    def user_fills_by_time(
        self, user: str, start_ms: int, end_ms: int | None, *, priority: Priority
    ) -> tuple[Fill, ...]:
        """Fills with ``startTime`` inclusive, ``aggregateByTime`` true."""
        _check_time_range(start_ms, end_ms)
        params: dict[str, Any] = {"user": normalize_wallet(user), "startTime": start_ms}
        if end_ms is not None:
            params["endTime"] = end_ms
        params["aggregateByTime"] = True
        result: tuple[Fill, ...] = self.info("userFillsByTime", params, priority=priority)
        return result

    def candles(
        self, coin: str, interval: str, start_ms: int, end_ms: int, *, priority: Priority
    ) -> tuple[Candle, ...]:
        _check_time_range(start_ms, end_ms)
        request = {
            "coin": _name(coin, "coin"),
            "interval": _name(interval, "interval"),
            "startTime": start_ms,
            "endTime": end_ms,
        }
        result: tuple[Candle, ...] = self.info("candleSnapshot", {"req": request}, priority=priority)
        return result

    def meta_and_asset_ctxs(self, *, priority: Priority) -> MetaAndCtxs:
        result: MetaAndCtxs = self.info("metaAndAssetCtxs", {}, priority=priority)
        return result

    def funding_history(self, coin: str, start_ms: int, *, priority: Priority) -> tuple[FundingRow, ...]:
        _check_time_range(start_ms, None)
        result: tuple[FundingRow, ...] = self.info(
            "fundingHistory", {"coin": _name(coin, "coin"), "startTime": start_ms}, priority=priority
        )
        return result

    def user_role(self, user: str, *, priority: Priority) -> str:
        result: str = self.info("userRole", {"user": normalize_wallet(user)}, priority=priority)
        return result

    def portfolio(self, user: str, *, priority: Priority) -> dict[str, PortfolioWindow]:
        result: dict[str, PortfolioWindow] = self.info("portfolio", {"user": normalize_wallet(user)}, priority=priority)
        return result

    def _attempt(self, request_type: str, body: str, weight: int, priority: Priority) -> Any:
        self._wait_for_cooldown(request_type)
        self._acquire(request_type, weight, priority)
        try:
            response = self._transport.post(self._url, body, timeout_s=self._timeout_s)
        except TimeoutError as exc:
            self._access.record_timeout()
            raise HlTimeoutError(f"{request_type}: no answer within {self._timeout_s:g} s") from exc
        except OSError as exc:
            self._access.record_timeout()
            raise HlConnectionError(f"{request_type}: connection failed ({type(exc).__name__})") from exc
        self._access.record_response(response.status, response.body)
        if 200 <= response.status < 300:
            self._rate_limited_in_a_row.pop(request_type, None)
            return self._decode(request_type, response.body, weight, priority)
        if response.status == 429:
            self._cooldown_until_ms[request_type] = self._clock.now_ms() + self._rate_limit_cooldown_ms(request_type)
            raise HlRateLimitedError(f"{request_type}: HTTP 429")
        raise HlHttpError(f"{request_type}: HTTP {response.status}", status=response.status)

    def _rate_limit_cooldown_ms(self, request_type: str) -> int:
        """One base backoff after a 429. With ``escalate_cooldown`` (a client whose sleeper never waits, so its callers
        fail and ask again later) it doubles for every further 429 in a row, up to ``hl.backoff_max_s``, so those
        callers never turn a 429 into a retry storm; a success resets it."""
        if not self._escalate_cooldown:
            return math.ceil(self._backoff_base_s * 1000)
        streak = self._rate_limited_in_a_row.get(request_type, 0) + 1
        self._rate_limited_in_a_row[request_type] = streak
        delay_s: float = min(self._backoff_base_s * 2 ** min(streak - 1, 62), self._backoff_max_s)
        return math.ceil(delay_s * 1000)

    def _wait_for_cooldown(self, request_type: str) -> None:
        """After a 429, nothing more goes to that endpoint for one base backoff (at least the 1 request/s rule)."""
        remaining_ms = self._cooldown_until_ms.get(request_type, 0) - self._clock.now_ms()
        if remaining_ms > 0:
            self._sleeper.sleep(remaining_ms / 1000)

    def _acquire(self, request_type: str, weight: int, priority: Priority) -> None:
        while not self._budget.try_acquire(weight, priority):
            wait_ms = self._budget.wait_ms(weight, priority)
            if wait_ms is None:
                raise HlBudgetError(f"{request_type}: weight {weight} can never fit the {priority.value} budget")
            self._sleeper.sleep(max(wait_ms, 1) / 1000)

    def _decode(self, request_type: str, text: str, weight: int, priority: Priority) -> Any:
        try:
            payload = json.loads(text)
        except (ValueError, RecursionError):
            self._schema_monitor.record_failure(request_type)
            raise HlSchemaError("response is not valid JSON", endpoint=request_type, field="") from None
        items = len(payload) if isinstance(payload, list) else 0
        late_weight = request_weight(request_type, items, self._config) - weight
        if late_weight > 0:
            self._budget.charge(late_weight, priority)
        try:
            return parse_response(request_type, payload)
        except HlSchemaError:
            self._schema_monitor.record_failure(request_type)
            raise
