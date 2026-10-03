"""Adapters from the feature ports (F3/F4/F6/F10/F12) to the real REST client, the WebSocket connector and live data.

Every adapter is READ-ONLY toward Hyperliquid (info endpoint and info WebSocket only)."""

from __future__ import annotations

import http.client
import json
import logging
import random
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from copytrade.core.clock import Clock, OffsetEstimate
from copytrade.core.money import Price
from copytrade.hl.backoff import backoff_delay_s
from copytrade.hl.budget import Priority, Sleeper
from copytrade.hl.errors import HlError, HlHttpError, HlSchemaError
from copytrade.hl.models import CoinSpec, L2Book
from copytrade.hl.rest import HlRestClient, Timed
from copytrade.hl.schema import parse_response
from copytrade.hl.ws import RECONNECT_BASE_S, WsConnection, WsConnector
from copytrade.paper.types import CoinMeta, FundingSnapshot
from copytrade.recorder.ports import AssetContext, FeedEvent, FundingPoint, MidsUpdate

_log = logging.getLogger(__name__)

MAX_BOOKS_PER_COIN = 64
SERVER_ERROR_STATUS = 500
FUNDING_RETRY_MS = 10_000  # a funding rate that is not there yet is asked for again after this long
ESTIMATE_SERVER_ERROR_RETRIES = 2  # extra clock-estimate attempts after an HTTP 5xx answer
ESTIMATE_RETRY_PAUSE_S = 0.5
CONFIRMING_BOOKS = 2  # distinct books that must be at least this recent before a catch-up trusts a book time
BOOK_RETENTION_FACTOR = 4
RECONNECT_MAX_S = 30.0
PING_INTERVAL_MS = 20_000
MAX_FRAMES_PER_POLL = 10_000
LEADERBOARD_MAX_BYTES = 64 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_HOUR_MS = 3_600_000
_MAJOR_COINS = frozenset({"BTC", "ETH"})
_CONTROL_CHANNELS = frozenset({"subscriptionResponse", "pong"})
_PING = json.dumps({"method": "ping"})


def _oserror(exc: HlError) -> OSError:
    return OSError(f"exchange request failed: {type(exc).__name__}")


class ExchangeOffsetSource:
    """``core.clock.OffsetSource``. One estimate = one ``l2Book`` info request for ``probe_coin`` at CRITICAL priority:
    ``offset_ms = book.time_ms - midpoint(local before, local after)`` and ``uncertainty_ms = max(1, ceil((after -
    before) / 2))`` plus 1 ms of exchange timestamp granularity, where before/after bracket the FINAL attempt only
    (never the retries or waits). ``OSError`` / ``HlError`` from the request propagate as ``OSError`` (ClockSync
    treats that as a failed estimate)."""

    def __init__(self, *, rest: HlRestClient, clock: Clock, probe_coin: str, sleeper: Sleeper | None = None) -> None:
        self._rest = rest
        self._clock = clock
        self._probe_coin = probe_coin
        self._sleeper = sleeper

    def estimate(self) -> OffsetEstimate:
        timed = self._fetch()
        book: L2Book = timed.value
        before, after = (
            timed.sent_ms,
            timed.received_ms,
        )  # the final attempt only: retries and waits are not the round trip
        round_trip = max(0, after - before)
        return OffsetEstimate(
            offset_ms=book.time_ms - (before + after) // 2,
            uncertainty_ms=max(1, (round_trip + 1) // 2) + 1,
        )

    def _fetch(self) -> Timed:
        """The REST client retries 429 and timeouts itself; a server error (5xx) is retried here, a few times and after
        a short pause (the clock decides whether entries run, so one bad answer must not leave it unsynced)."""
        attempt = 0
        while True:
            try:
                return self._rest.l2_book_timed(self._probe_coin, priority=Priority.CRITICAL)
            except HlHttpError as exc:
                if exc.status < SERVER_ERROR_STATUS or attempt >= ESTIMATE_SERVER_ERROR_RETRIES:
                    raise _oserror(exc) from exc
            except HlError as exc:
                raise _oserror(exc) from exc
            attempt += 1
            if self._sleeper is not None:
                self._sleeper.sleep(ESTIMATE_RETRY_PAUSE_S)


def _positive(value: Price) -> bool:
    return value.is_finite() and value > 0


HUB_TAP_MAX_EVENTS = 50_000  # what the recorder has not collected yet; the oldest events go first


class HubTap:
    """The recorder's ``MarketFeed``: the runner drains the ``MarketHub`` itself on every iteration (mids and books must
    not depend on the recorder, RISK-65) and hands the events over here; ``poll`` returns what ``drain`` collected."""

    def __init__(self, hub: MarketHub) -> None:
        self._hub = hub
        self._lock = threading.Lock()
        self._events: deque[FeedEvent] = deque(maxlen=HUB_TAP_MAX_EVENTS)

    def drain(self) -> None:
        """Poll the hub (never raises for a lost connection) and keep the events for the recorder."""
        events = self._hub.poll()
        with self._lock:
            self._events.extend(events)

    def subscribe(self, coins: Sequence[str]) -> None:
        self._hub.subscribe(coins)

    def poll(self) -> Sequence[FeedEvent]:
        with self._lock:
            events, self._events = tuple(self._events), deque(maxlen=HUB_TAP_MAX_EVENTS)
        return events


class MarketHub:
    """``recorder.ports.MarketFeed`` over the info WebSocket (``l2Book`` per coin and ``allMids``), and the live-data
    store behind it: it is the ONLY consumer of the socket, the recorder polls it, and it keeps (a) the recent L2
    books per coin (``paper.ports.BookSource``) and (b) the latest mids (marks).

    - ``subscribe(coins)`` replaces the subscription set (subscribes the new coins, unsubscribes the dropped ones,
      ``allMids`` once). ``poll()`` never raises: a lost connection is retried on a later poll (jittered backoff,
      resubscribing everything) and polls return ``()`` meanwhile. A connect attempt can take up to
      ``hl.ws_connect_timeout_s`` (the connector's bound), like F3's feed.
    - Frames: ``{"channel":"l2Book","data":{"coin","time","levels":[bids,asks]}}`` -> ``L2Book``;
      ``{"channel":"allMids","data":{"mids":{coin: px}}}`` -> ``MidsUpdate(time_ms=None, ...)``. Anything else
      (malformed, non-finite or non-positive prices, unknown channels) is dropped and counted, never raised;
      ``subscriptionResponse`` and ``pong`` are ignored.
    - ``first_book_at_or_after(coin, time_ms)``: the earliest kept book with ``time_ms >= time_ms``, else ``None``
      (the paper broker then treats the book as unavailable). Books more than ``paper.max_book_age_ms`` x 4 older
      than the newest book of the coin are pruned and at most 64 books per coin are kept.
    - ``mids()``: latest mid per coin as ``Price`` and ``mid_time_ms`` the local receive time of that update.

    Thread-safe: the recorder polls it on the trading thread while the gate (Telegram flatten) reads books.
    """

    def __init__(self, *, connector: WsConnector, clock: Clock, max_book_age_ms: int, seed: int) -> None:
        self._connector = connector
        self._clock = clock
        self._keep_ms = max_book_age_ms * BOOK_RETENTION_FACTOR
        self._rng = random.Random(seed)  # noqa: S311 - reconnect jitter, not security
        self._lock = threading.Lock()
        self._conn: WsConnection | None = None
        self._closed = False
        self._wanted: frozenset[str] = frozenset()
        self._subscribed: set[str] = set()
        self._mids_subscribed = False
        self._attempt = 0
        self._next_attempt_ms = 0
        self._last_ping_ms = 0
        self._books: dict[str, deque[L2Book]] = {}
        self._mids: dict[str, Price] = {}
        self._mid_time_ms: int | None = None
        self.dropped_frames = 0

    def subscribe(self, coins: Sequence[str]) -> None:
        with self._lock:
            self._wanted = frozenset(coins)

    def poll(self) -> Sequence[FeedEvent]:
        with self._lock:
            conn = None if self._closed else self._ensure_connected()
            if conn is None:
                return ()
            events: list[FeedEvent] = []
            try:
                self._sync_subscriptions(conn)
                self._ping_when_due(conn)
                self._drain(conn, events)
            except OSError as exc:
                self._lost(exc)
            return tuple(events)

    def first_book_at_or_after(self, coin: str, time_ms: int) -> L2Book | None:
        with self._lock:
            qualifying = [book for book in self._books.get(coin, ()) if book.time_ms >= time_ms]
        return min(qualifying, key=lambda book: book.time_ms, default=None)

    def confirmed_book_time_ms(self) -> int | None:
        """The exchange timestamp of the newest book that a SECOND book (another coin, or another snapshot of the same
        coin) does not contradict: the second-newest distinct book time across all coins, so one bogus frame stamped in
        the future is never taken. ``None`` until two distinct books have arrived."""
        with self._lock:
            times = {(coin, book.time_ms) for coin, books in self._books.items() for book in books}
        if len(times) < CONFIRMING_BOOKS:
            return None
        return sorted((t for _, t in times), reverse=True)[CONFIRMING_BOOKS - 1]

    def mids(self) -> Mapping[str, Price]:
        with self._lock:
            return dict(self._mids)

    def mid_time_ms(self) -> int | None:
        with self._lock:
            return self._mid_time_ms

    def seed_mids(self, mids: Mapping[str, Price]) -> None:
        """Start from a REST ``allMids`` snapshot so marks exist before the first WebSocket frame arrives. Only
        positive finite prices are taken; later frames overwrite them."""
        with self._lock:
            self._mids.update({coin: px for coin, px in mids.items() if _positive(px)})
            self._mid_time_ms = self._clock.now_ms()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            conn, self._conn = self._conn, None
        if conn is not None:
            conn.close()

    # ------------------------------------------------------------------------------------------ connection
    def _ensure_connected(self) -> WsConnection | None:
        if self._conn is not None:
            return self._conn
        now = self._clock.now_ms()
        if now < self._next_attempt_ms:
            return None
        try:
            self._conn = self._connector.connect()
        except OSError as exc:
            self._schedule_retry(exc)
            return None
        self._subscribed = set()
        self._mids_subscribed = False
        self._last_ping_ms = now
        return self._conn

    def _lost(self, error: OSError) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            conn.close()
        self._schedule_retry(error)

    def _schedule_retry(self, error: OSError) -> None:
        delay_s = backoff_delay_s(self._attempt, base_s=RECONNECT_BASE_S, max_s=RECONNECT_MAX_S, rng=self._rng)
        self._attempt += 1
        self._next_attempt_ms = self._clock.now_ms() + int(delay_s * 1000)
        _log.warning(
            "market websocket unavailable",
            extra={"event": "market_ws_down", "error_type": type(error).__name__, "retry_in_s": delay_s},
        )

    # ------------------------------------------------------------------------------------------ subscriptions
    @staticmethod
    def _send(conn: WsConnection, method: str, subscription: Mapping[str, str]) -> None:
        conn.send(json.dumps({"method": method, "subscription": dict(subscription)}))

    def _sync_subscriptions(self, conn: WsConnection) -> None:
        if not self._mids_subscribed:
            self._send(conn, "subscribe", {"type": "allMids"})
            self._mids_subscribed = True
        for coin in sorted(self._wanted - self._subscribed):
            self._send(conn, "subscribe", {"type": "l2Book", "coin": coin})
            self._subscribed.add(coin)
        for coin in sorted(self._subscribed - self._wanted):
            self._send(conn, "unsubscribe", {"type": "l2Book", "coin": coin})
            self._subscribed.discard(coin)
            self._books.pop(coin, None)

    def _ping_when_due(self, conn: WsConnection) -> None:
        now = self._clock.now_ms()
        if now - self._last_ping_ms >= PING_INTERVAL_MS:
            conn.send(_PING)
            self._last_ping_ms = now

    # ------------------------------------------------------------------------------------------ frames
    def _drain(self, conn: WsConnection, events: list[FeedEvent]) -> None:
        for _ in range(MAX_FRAMES_PER_POLL):
            text = conn.recv()
            if text is None:
                return
            self._attempt = 0
            event = self._decode(text)
            if isinstance(event, L2Book):
                self._keep_book(event)
            elif isinstance(event, MidsUpdate):
                self._mids.update(event.mids)
                self._mid_time_ms = self._clock.now_ms()
            else:
                continue
            events.append(event)

    def _decode(self, text: str) -> FeedEvent | None:
        try:
            message = json.loads(text)
            channel = message.get("channel") if isinstance(message, dict) else None
            if channel in _CONTROL_CHANNELS:
                return None
            if channel == "l2Book":
                return self._decode_book(message["data"])
            if channel == "allMids":
                return self._decode_mids(message["data"])
        except (ValueError, KeyError, TypeError, HlSchemaError):
            pass
        self.dropped_frames += 1
        return None

    @staticmethod
    def _decode_book(data: Any) -> L2Book:
        book: L2Book = parse_response("l2Book", data)
        if not all(_positive(level.px) for level in (*book.bids, *book.asks)):
            raise ValueError("non-positive price")
        return book

    @staticmethod
    def _decode_mids(data: Any) -> MidsUpdate:
        mids: dict[str, Price] = parse_response("allMids", data["mids"])
        if not all(_positive(px) for px in mids.values()):
            raise ValueError("non-positive mid")
        return MidsUpdate(time_ms=None, mids=mids)

    def _keep_book(self, book: L2Book) -> None:
        kept = self._books.setdefault(book.coin, deque(maxlen=MAX_BOOKS_PER_COIN))
        kept.append(book)
        while kept and kept[0].time_ms < book.time_ms - self._keep_ms:
            kept.popleft()


class RestMarketSource:
    """``recorder.ports.MarketSource`` over ``metaAndAssetCtxs`` and ``fundingHistory`` (CRITICAL priority), and
    ``paper.ports.FundingSource`` over the same two requests. The exchange timestamps come from the responses;
    ``clock`` (local time) only paces the retries of a funding rate that is not available: ``funding_at`` asks the
    exchange for one coin and hour at most once per ``FUNDING_RETRY_MS`` (it is two REST requests on the trading
    thread) and answers ``None`` (missing, retried later) in between."""

    def __init__(self, *, rest: HlRestClient, clock: Clock) -> None:
        self._rest = rest
        self._clock = clock
        self._funding_tried_ms: dict[tuple[str, int], int] = {}

    def asset_contexts(self) -> Sequence[AssetContext]:
        snapshot = self._rest.meta_and_asset_ctxs(priority=Priority.CRITICAL)
        return tuple(
            AssetContext(
                coin=row.coin,
                mark=row.mark_px,
                oracle=row.oracle_px,
                funding=row.funding,
                open_interest=row.open_interest,
                time_ms=None,
            )
            for row in snapshot.contexts
        )

    def all_mids(self) -> Mapping[str, Price]:
        """The mid of every coin (``allMids`` over REST, CRITICAL priority)."""
        return self._rest.all_mids(priority=Priority.CRITICAL)

    def funding_history(self, coin: str, start_ms: int) -> Sequence[FundingPoint]:
        rows = self._rest.funding_history(coin, start_ms, priority=Priority.CRITICAL)
        return tuple(
            FundingPoint(coin=row.coin, time_ms=row.time_ms, rate=row.rate, premium=row.premium)
            for row in sorted(rows, key=lambda r: r.time_ms)
            if row.coin == coin and row.time_ms >= start_ms
        )

    def funding_at(self, coin: str, hour_ms: int) -> FundingSnapshot | None:
        """The funding rate paid for the hour starting at ``hour_ms`` (the exchange stamps it inside that hour) and the
        CURRENT oracle price of the coin (the exchange does not serve the hour's own oracle). ``OSError`` on failure."""
        key, now = (coin, hour_ms), self._clock.now_ms()
        tried = self._funding_tried_ms.get(key)
        if tried is not None and 0 <= now - tried < FUNDING_RETRY_MS:
            return None
        self._funding_tried_ms[key] = now
        try:
            points = self.funding_history(coin, hour_ms)
            oracle = next((c.oracle for c in self.asset_contexts() if c.coin == coin), None)
        except HlError as exc:
            raise _oserror(exc) from exc
        point = next((p for p in points if p.time_ms < hour_ms + _HOUR_MS), None)
        if point is None or oracle is None:
            return None
        del self._funding_tried_ms[key]
        return FundingSnapshot(coin=coin, hour_ms=hour_ms, rate=point.rate, oracle_px=oracle)


class RestMetaSource:
    """``paper.ports.MetaSource`` over ``metaAndAssetCtxs``: ``fetch()`` -> ``{coin: CoinMeta(sz_decimals,
    max_leverage)}`` for every listed (not delisted) core perp; ``delisted()`` -> coins the exchange flags
    ``isDelisted``. A failed fetch raises ``OSError`` (the gate then refuses entries ``meta_unavailable``)."""

    def __init__(self, *, rest: HlRestClient) -> None:
        self._rest = rest

    def _coins(self) -> tuple[CoinSpec, ...]:
        try:
            return self._rest.meta_and_asset_ctxs(priority=Priority.CRITICAL).coins
        except HlError as exc:
            raise _oserror(exc) from exc

    def fetch(self) -> Mapping[str, CoinMeta]:
        return {
            spec.name: CoinMeta(sz_decimals=spec.sz_decimals, max_leverage=spec.max_leverage)
            for spec in self._coins()
            if not spec.is_delisted
        }

    def delisted(self) -> frozenset[str]:
        return frozenset(spec.name for spec in self._coins() if spec.is_delisted)


class HttpLeaderboardSource:
    """``recorder.ports.LeaderboardSource``: HTTP GET of ``url`` (the stats host) with a ``timeout_s`` deadline for
    the whole exchange; returns the body bytes exactly as received. Non-2xx, timeout, or a body above 64 MiB raises
    ``OSError`` / ``TimeoutError``. No redirects are followed."""

    def __init__(self, *, url: str, timeout_s: float) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.hostname is None:
            raise ValueError("url must be an absolute http or https URL")
        self._host: str = parts.hostname
        self._parts = parts
        self._timeout_s = timeout_s

    def fetch(self) -> bytes:
        parts = self._parts
        connection_type = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        deadline = time.monotonic() + self._timeout_s
        connection = connection_type(self._host, parts.port, timeout=self._timeout_s)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        try:
            connection.request("GET", target)
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise OSError(f"leaderboard answered HTTP {response.status}")
            return self._read_body(response, connection, deadline)
        except http.client.HTTPException as exc:
            raise OSError(f"invalid HTTP exchange: {type(exc).__name__}") from exc
        finally:
            connection.close()

    @staticmethod
    def _read_body(
        response: http.client.HTTPResponse, connection: http.client.HTTPConnection, deadline: float
    ) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("leaderboard not complete before the deadline")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read(_READ_CHUNK_BYTES)
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > LEADERBOARD_MAX_BYTES:
                raise OSError("leaderboard body exceeds the size cap")
            chunks.append(chunk)


class ConfigCostModel:
    """``scoring.models.CostModel`` from config only: ``taker_fee_bps`` = ``cost.taker_fee_bps``; ``half_spread_bps``
    and ``delay_bps`` = the ``cost.fallback_half_spread_bps.*`` / ``cost.fallback_delay_slippage_bps.*`` value of the
    coin's tier (``major`` for BTC and ETH, ``alt`` otherwise) times ``cost.fallback_half_spread_mult`` for the
    spread (the conservative fallback of the F11 cost model; recorded data is stage 2)."""

    def __init__(self, config: Mapping[str, object]) -> None:
        self._config = config

    def _tiered(self, key: str, coin: str) -> Decimal:
        tier = "major" if coin in _MAJOR_COINS else "alt"
        return Decimal(str(self._config[f"{key}.{tier}"]))

    def taker_fee_bps(self) -> Decimal:
        return Decimal(str(self._config["cost.taker_fee_bps"]))

    def half_spread_bps(self, coin: str, t_ms: int) -> Decimal:  # noqa: ARG002 - the fallback does not depend on time
        multiplier = Decimal(str(self._config["cost.fallback_half_spread_mult"]))
        return self._tiered("cost.fallback_half_spread_bps", coin) * multiplier

    def delay_bps(self, coin: str, t_ms: int) -> Decimal:  # noqa: ARG002 - the fallback does not depend on time
        return self._tiered("cost.fallback_delay_slippage_bps", coin)
