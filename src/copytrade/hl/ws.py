"""Hyperliquid WebSocket feed: user-fill subscriptions, limits, heartbeat, staleness, gap resync (F3.AC3, F3.AC4)."""

from __future__ import annotations

import json
import logging
import math
import random
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from copytrade.core.clock import Clock
from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert, AlertSink
from copytrade.hl.backoff import backoff_delay_s
from copytrade.hl.budget import Priority
from copytrade.hl.errors import HlError, HlSchemaError, WsUserLimitError
from copytrade.hl.ledger_port import DowntimeRecord, DowntimeSink
from copytrade.hl.models import Fill
from copytrade.hl.rest import HlRestClient
from copytrade.hl.schema import SchemaFailureMonitor, parse_ws_fills
from copytrade.hl.wallet import normalize_wallet

FEED_STALE = "feed_stale"
DATA_GAP = "data_gap"
WS_FRAME_ENDPOINT = "ws:frame"
RECONNECT_BASE_S = 1.0  # spec F3.AC3: reconnect backoff runs from 1 s up to hl.ws_reconnect_backoff_max_s

_MINUTE_MS = 60_000
# The heartbeat is clamped to 3/4 of feed.stale_after_s: a healthy idle link must get its pong back before it is
# declared stale, whatever the two (independently validated) config values are.
_PING_WITHIN_STALE_NUM = 3
_PING_WITHIN_STALE_DEN = 4
_ENTRY_ACTIONS = frozenset({ActionKind.OPEN, ActionKind.ADD})
_PING = json.dumps({"method": "ping"})
_log = logging.getLogger(__name__)


class WsConnection(Protocol):
    """One open socket. An external boundary."""

    def send(self, message: str) -> None: ...

    def recv(self) -> str | None:
        """Next message already received, or ``None`` when none is waiting. Never blocks. Raises ``OSError`` when
        the connection is closed."""
        ...

    def close(self) -> None: ...


class WsConnector(Protocol):
    """Opens connections. An external boundary. ``connect`` raises ``OSError`` on failure."""

    def connect(self) -> WsConnection: ...


class FillSink(Protocol):
    """Receives de-duplicated leader fills in order. Downstream (F7) implements it."""

    def on_fills(self, wallet: str, fills: Sequence[Fill]) -> None: ...


def _subscription(method: str, wallet: str) -> str:
    return json.dumps({"method": method, "subscription": {"type": "userFills", "user": wallet}})


def _claimed_user(message: Mapping[str, Any]) -> str | None:
    """The wallet a rejected userFills message says it is for, if it says so as a string."""
    data = message.get("data")
    user = data.get("user") if isinstance(data, dict) else None
    return user if isinstance(user, str) else None


class _WalletState:
    """What the feed remembers about one subscribed wallet.

    ``gap_start_ms`` is not ``None`` while a gap is unresolved: fills from the new connection are held back in
    ``held`` and the wallet counts as stale until the REST resync succeeded.
    """

    __slots__ = ("failures", "gap_start_ms", "held", "last_fill_ms", "retry_at_ms", "seen_tids")

    def __init__(self) -> None:
        self.seen_tids: set[int] = set()
        self.last_fill_ms: int | None = None  # newest exchange timestamp among delivered fills
        self.gap_start_ms: int | None = None
        self.held: list[Fill] = []
        self.retry_at_ms = 0
        self.failures = 0

    def unseen(self, fills: Sequence[Fill]) -> list[Fill]:
        """The fills not delivered before, first occurrence only, in the given order."""
        fresh: dict[int, Fill] = {}
        for fill in fills:
            if fill.tid not in self.seen_tids and fill.tid not in fresh:
                fresh[fill.tid] = fill
        return list(fresh.values())

    def remember(self, fills: Sequence[Fill]) -> None:
        for fill in fills:
            self.seen_tids.add(fill.tid)
            if self.last_fill_ms is None or fill.time_ms > self.last_fill_ms:
                self.last_fill_ms = fill.time_ms


class HlWsFeed:
    """Drives everything from ``tick()`` (called by the scheduler at least once per second). ``tick`` never sleeps
    itself, but it blocks while a gap resync runs over the synchronous REST client (see below).

    ``tick`` connects when due (respecting ``hl.ws_max_new_conns_per_min`` and reconnect backoff), sends
    ``{"method": "ping"}`` every ``hl.ws_ping_interval_s`` (never slower than 3/4 of ``feed.stale_after_s``),
    drains messages, marks a connection stale when it has produced no message or pong for ``feed.stale_after_s``
    (stale at exactly that many seconds of silence), closes and reconnects it, and resyncs the gap over REST
    before releasing any new fill for an affected wallet. A malformed or unreadable userFills frame opens a gap too.

    Subscribe message: ``{"method":"subscribe","subscription":{"type":"userFills","user":<wallet>}}``.

    Fail closed: a wallet is stale (entries refused) whenever it is unknown, not yet subscribed on a live
    connection, waiting for its gap resync, or its connection has been silent too long. A resync runs inside
    ``tick`` over the synchronous REST client, so a long REST backoff blocks that tick (test-plan D8).
    Fills are de-duplicated by ``tid`` per wallet for the life of the process.

    Sink or ledger exceptions other than ``OSError`` are not caught: a downstream bug must not be hidden.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        config: Mapping[str, Any],
        clock: Clock,
        connector: WsConnector,
        rest: HlRestClient,
        rng: random.Random,
        sink: FillSink,
        ledger: DowntimeSink,
        alerts: AlertSink,
        schema_monitor: SchemaFailureMonitor,
    ) -> None:
        self._max_users = int(config["hl.ws_max_unique_users"])
        self._max_new_conns_per_min = int(config["hl.ws_max_new_conns_per_min"])
        self._stale_after_ms = int(config["feed.stale_after_s"]) * 1000
        self._ping_interval_ms = min(
            int(config["hl.ws_ping_interval_s"]) * 1000,
            self._stale_after_ms * _PING_WITHIN_STALE_NUM // _PING_WITHIN_STALE_DEN,
        )
        self._reconnect_max_s = float(config["hl.ws_reconnect_backoff_max_s"])
        self._resync_backoff_base_s = float(config["hl.backoff_base_s"])
        self._resync_backoff_max_s = float(config["hl.backoff_max_s"])
        self._clock = clock
        self._connector = connector
        self._rest = rest
        self._rng = rng
        self._sink = sink
        self._ledger = ledger
        self._alerts = alerts
        self._schema_monitor = schema_monitor
        self._wallets: dict[str, _WalletState] = {}
        self._conn: WsConnection | None = None
        self._subscribed: set[str] = set()  # wallets subscribed on the current connection
        self._last_activity_ms = 0
        self._last_ping_ms = 0
        self._confirmed = False  # the current connection has delivered at least one message
        self._reconnect_failures = 0
        self._next_connect_ms = 0
        self._connect_attempts: deque[int] = deque()
        self._alerted = False

    def subscribe_user(self, wallet: str) -> None:
        """Subscribe to a wallet's fills. Re-subscribing a known wallet is a no-op.

        Raises:
            WsUserLimitError: a new distinct wallet beyond ``hl.ws_max_unique_users``; nothing is sent.
            HlRequestError: ``wallet`` is not a valid address.
        """
        key = normalize_wallet(wallet)
        if key in self._wallets:
            return
        if len(self._wallets) >= self._max_users:
            raise WsUserLimitError(f"already {self._max_users} distinct users subscribed")
        self._wallets[key] = _WalletState()

    def open_gap(self, wallet: str, since_ms: int) -> None:
        """The wallet's fills were not watched since ``since_ms`` (a restart, R0): its first connection resyncs from
        there over REST before anything is acted on (B3), and until then the wallet counts as stale. Unknown wallets
        and wallets already in a gap are left alone."""
        state = self._wallets.get(wallet.lower())
        if state is not None and state.gap_start_ms is None:
            state.gap_start_ms = since_ms
            state.retry_at_ms = 0
            state.failures = 0

    def unsubscribe_user(self, wallet: str) -> None:
        """Forget a wallet (its unsubscribe message goes out on the next tick). Unknown wallets are ignored."""
        self._wallets.pop(wallet.lower(), None)

    def tick(self) -> None:
        now = self._clock.now_ms()
        if self._conn is not None:
            self._read_messages(now)
        if self._conn is not None and now - self._last_activity_ms >= self._stale_after_ms:
            self._lose_connection(now, "no message or pong for feed.stale_after_s")
        if self._conn is not None:
            self._ping_if_due(now)
        if self._conn is None:
            self._connect_if_due(now)
        if self._conn is not None:
            self._sync_subscriptions()
        if self._conn is not None:
            self._resync_gaps()
        self._alert_once_per_episode()

    def is_stale(self, wallet: str) -> bool:
        """True while the wallet's feed is stale, disconnected or resyncing."""
        key = wallet.lower()
        state = self._wallets.get(key)
        if state is None or self._conn is None or key not in self._subscribed or state.gap_start_ms is not None:
            return True
        return self._clock.now_ms() - self._last_activity_ms >= self._stale_after_ms

    def refusal_reason(self, wallet: str, action: ActionKind) -> str | None:
        """``"feed_stale"`` for OPEN/ADD while ``is_stale(wallet)``; ``None`` otherwise (exits are never refused)."""
        return FEED_STALE if action in _ENTRY_ACTIONS and self.is_stale(wallet) else None

    # --- connection lifecycle -------------------------------------------------------------------------------

    def _connect_if_due(self, now: int) -> None:
        if not self._wallets or now < self._next_connect_ms:
            return
        while self._connect_attempts and now - self._connect_attempts[0] >= _MINUTE_MS:
            self._connect_attempts.popleft()
        if len(self._connect_attempts) >= self._max_new_conns_per_min:
            return
        self._connect_attempts.append(now)
        try:
            connection = self._connector.connect()
        except OSError as exc:
            _log.warning(
                "websocket connect failed", extra={"event": "ws_connect_failed", "error_type": type(exc).__name__}
            )
            self._schedule_reconnect(now)
            return
        self._conn = connection
        self._subscribed = set()
        self._last_activity_ms = now
        self._last_ping_ms = now
        self._confirmed = False
        _log.info("websocket connected", extra={"event": "ws_connected", "wallets": len(self._wallets)})

    def _schedule_reconnect(self, now: int) -> None:
        delay_s = backoff_delay_s(
            self._reconnect_failures, base_s=RECONNECT_BASE_S, max_s=self._reconnect_max_s, rng=self._rng
        )
        self._reconnect_failures += 1
        self._next_connect_ms = now + math.ceil(delay_s * 1000)

    def _lose_connection(self, now: int, reason: str) -> None:
        """Drop the connection, open a gap for every wallet it served and schedule the jittered reconnect."""
        connection, self._conn = self._conn, None
        if connection is not None:
            try:
                connection.close()
            except OSError as exc:
                _log.debug(
                    "closing a lost websocket failed",
                    extra={"event": "ws_close_failed", "error_type": type(exc).__name__},
                )
        for wallet in self._subscribed:
            state = self._wallets.get(wallet)
            if state is not None and state.gap_start_ms is None:
                state.gap_start_ms = self._last_activity_ms
                state.retry_at_ms = 0
                state.failures = 0
        self._subscribed = set()
        self._schedule_reconnect(now)
        _log.warning("websocket lost", extra={"event": "ws_lost", "reason": reason})

    def _send(self, message: str) -> bool:
        """Send on the current connection; a failure loses the connection and returns False."""
        connection = self._conn
        if connection is None:
            return False
        try:
            connection.send(message)
        except OSError:
            self._lose_connection(self._clock.now_ms(), "send failed")
            return False
        return True

    def _ping_if_due(self, now: int) -> None:
        if now - self._last_ping_ms >= self._ping_interval_ms:
            self._last_ping_ms = now
            self._send(_PING)

    def _sync_subscriptions(self) -> None:
        for wallet in sorted(self._subscribed - self._wallets.keys()):
            if not self._send(_subscription("unsubscribe", wallet)):
                return
            self._subscribed.discard(wallet)
        for wallet in self._wallets:
            if wallet not in self._subscribed:
                if not self._send(_subscription("subscribe", wallet)):
                    return
                self._subscribed.add(wallet)

    # --- messages -------------------------------------------------------------------------------------------

    def _read_messages(self, now: int) -> None:
        connection = self._conn
        while connection is not None:
            try:
                raw = connection.recv()
            except OSError:
                self._lose_connection(now, "receive failed")
                return
            if raw is None:
                return
            previous_activity_ms, self._last_activity_ms = self._last_activity_ms, now
            if not self._confirmed:
                self._confirmed = True
                self._reconnect_failures = 0
            self._handle_message(raw, previous_activity_ms)

    def _handle_message(self, raw: str, previous_activity_ms: int) -> None:
        """Route one frame. A frame that may have carried fills but cannot be used opens a data gap (fills may be
        lost) for its wallet, or for every wallet on the connection when the wallet cannot be identified."""
        try:
            message = json.loads(raw)
        except (ValueError, RecursionError):
            message = None
        if type(message) is not dict or type(message.get("channel")) is not str:
            self._schema_monitor.record_failure(WS_FRAME_ENDPOINT)
            _log.warning("unreadable websocket frame dropped", extra={"event": "ws_bad_frame"})
            self._open_gaps(None, previous_activity_ms)
            return
        if message["channel"] != "userFills":  # pong, subscriptionResponse and channels we never subscribed to
            return
        try:
            user, _is_snapshot, fills = parse_ws_fills(message)
        except HlSchemaError as exc:
            self._schema_monitor.record_failure(exc.endpoint)
            _log.warning("websocket message rejected", extra={"event": "ws_schema_failure", "field": exc.field})
            self._open_gaps(_claimed_user(message), previous_activity_ms)
            return
        state = self._wallets.get(user.lower())
        if state is None:
            return
        if state.gap_start_ms is not None:
            state.held.extend(fills)
        else:
            self._deliver(user.lower(), state, fills)

    def _open_gaps(self, user: str | None, previous_activity_ms: int) -> None:
        """Open a gap from the last good message on for ``user`` if it is a subscribed wallet, else (fail closed)
        for every wallet on the connection. Wallets already in a gap keep their earlier start."""
        key = None if user is None else user.lower()
        targets = [key] if key in self._subscribed else sorted(self._subscribed)
        for wallet in targets:
            state = self._wallets.get(wallet)
            if state is not None and state.gap_start_ms is None:
                state.gap_start_ms = previous_activity_ms
                state.retry_at_ms = 0
                state.failures = 0

    def _deliver(self, wallet: str, state: _WalletState, fills: Sequence[Fill]) -> None:
        fresh = state.unseen(fills)
        if fresh:
            self._sink.on_fills(wallet, fresh)
            state.remember(fresh)

    # --- gap resync -----------------------------------------------------------------------------------------

    def _resync_gaps(self) -> None:
        for wallet, state in list(self._wallets.items()):
            if state.gap_start_ms is None or self._clock.now_ms() < state.retry_at_ms:
                continue
            self._resync(wallet, state, state.gap_start_ms)

    def _resync(self, wallet: str, state: _WalletState, gap_start_ms: int) -> None:
        """Fetch what was missed, ledger the gap, then release fetched fills before the fills held back."""
        start_ms = gap_start_ms if state.last_fill_ms is None else state.last_fill_ms
        try:
            fetched = self._rest.user_fills_by_time(wallet, start_ms, None, priority=Priority.CRITICAL)
            end_ms = max(self._clock.now_ms(), gap_start_ms + 1)
            self._ledger.record_downtime(
                DowntimeRecord(kind=DATA_GAP, start_ms=gap_start_ms, end_ms=end_ms, wallets=(wallet,))
            )
        except (HlError, OSError) as exc:
            delay_s = backoff_delay_s(
                state.failures, base_s=self._resync_backoff_base_s, max_s=self._resync_backoff_max_s, rng=self._rng
            )
            state.failures += 1
            state.retry_at_ms = self._clock.now_ms() + math.ceil(delay_s * 1000)
            _log.warning(
                "gap resync failed; the wallet stays stale",
                extra={
                    "event": "resync_failed",
                    "wallet": wallet,
                    "error_type": type(exc).__name__,
                    "retry_in_s": delay_s,
                },
            )
            return
        self._deliver(wallet, state, sorted(fetched, key=lambda fill: (fill.time_ms, fill.tid)))
        state.gap_start_ms = None
        state.failures = 0
        held, state.held = state.held, []
        self._deliver(wallet, state, held)
        _log.info("gap resynced", extra={"event": "resynced", "wallet": wallet, "fetched": len(fetched)})

    # --- alert ----------------------------------------------------------------------------------------------

    def _alert_once_per_episode(self) -> None:
        """One ``feed_stale`` alert per episode: from the feed going down or a gap left unresolved until the
        connection has delivered a message again with no gap outstanding."""
        down = self._conn is None or any(state.gap_start_ms is not None for state in self._wallets.values())
        if not down and self._confirmed:
            self._alerted = False
        if not down or self._alerted or not self._wallets:
            return
        wallets = ", ".join(self._wallets)
        message = (
            f"Hyperliquid fill feed is stale for {len(self._wallets)} wallet(s): {wallets}; opens and adds are refused"
        )
        try:
            self._alerts.send(Alert(kind=FEED_STALE, message=message))
        except OSError as exc:
            _log.warning(
                "feed alert delivery failed; retrying on the next tick",
                extra={"event": "feed_alert_failed", "error_type": type(exc).__name__},
            )
            return
        self._alerted = True
