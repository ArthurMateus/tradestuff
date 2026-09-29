"""Hyperliquid WebSocket feed: user-fill subscriptions, limits, heartbeat, staleness, gap resync (F3.AC3, F3.AC4)."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from copytrade.core.clock import Clock
from copytrade.core.domain import ActionKind
from copytrade.core.events import AlertSink
from copytrade.hl.ledger_port import DowntimeSink
from copytrade.hl.models import Fill
from copytrade.hl.rest import HlRestClient
from copytrade.hl.schema import SchemaFailureMonitor

FEED_STALE = "feed_stale"


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


class HlWsFeed:
    """Drives everything from ``tick()`` (called by the scheduler at least once per second); it never sleeps.

    ``tick`` connects when due (respecting ``hl.ws_max_new_conns_per_min`` and reconnect backoff), sends
    ``{"method": "ping"}`` every ``hl.ws_ping_interval_s``, drains messages, marks a connection stale when it
    has produced no message or pong for more than ``feed.stale_after_s``, closes and reconnects it, and resyncs
    the gap over REST before releasing any new fill for an affected wallet.

    Subscribe message: ``{"method":"subscribe","subscription":{"type":"userFills","user":<wallet>}}``.
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
        raise NotImplementedError

    def subscribe_user(self, wallet: str) -> None:
        """Subscribe to a wallet's fills. Re-subscribing a known wallet is a no-op.

        Raises:
            WsUserLimitError: a new distinct wallet beyond ``hl.ws_max_unique_users``; nothing is sent.
        """
        raise NotImplementedError

    def unsubscribe_user(self, wallet: str) -> None:
        raise NotImplementedError

    def tick(self) -> None:
        raise NotImplementedError

    def is_stale(self, wallet: str) -> bool:
        """True while the wallet's feed is stale, disconnected or resyncing."""
        raise NotImplementedError

    def refusal_reason(self, wallet: str, action: ActionKind) -> str | None:
        """``"feed_stale"`` for OPEN/ADD while ``is_stale(wallet)``; ``None`` otherwise (exits are never refused)."""
        raise NotImplementedError
