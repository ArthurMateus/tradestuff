"""Concrete F3 WebSocket connector over the ``websockets`` library (W0). The only module allowed to import it."""

from __future__ import annotations

import logging
import math
from urllib.parse import urlsplit

from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.frames import CloseCode
from websockets.sync.client import ClientConnection, connect

from copytrade.hl.ws import WsConnection

__all__ = ["WebsocketsConnector"]

_log = logging.getLogger(__name__)
_SCHEMES = frozenset({"ws", "wss"})
_ORDER_PATH_MARKER = "exchange"  # F1.AC3: this connector is info-only and must never target the order endpoint


def _validate_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in _SCHEMES:
        raise ValueError("websocket url must use the ws or wss scheme")
    if not parts.hostname:
        raise ValueError("websocket url has no host")
    _ = parts.port  # raises ValueError for a malformed or out-of-range port
    if _ORDER_PATH_MARKER in parts.path.lower():
        raise ValueError("websocket url must not point at an exchange/order endpoint")


class _Connection:
    """One open socket behind the non-blocking ``WsConnection`` contract. Library errors become ``OSError``."""

    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws

    def send(self, message: str) -> None:
        try:
            self._ws.send(message)
        except ConnectionClosed as exc:
            raise OSError("websocket connection is closed") from exc

    def recv(self) -> str | None:
        try:
            # timeout=0 only inspects what the library's reader thread has already queued, in arrival order; frames
            # received before a close, failure or limit breach stay queued and are returned first.
            message = self._ws.recv(timeout=0)
        except TimeoutError:  # an OSError subclass: must be told apart from a real failure
            return None
        except ConnectionClosed as exc:  # peer close or drop, frame over max_size, invalid UTF-8
            raise OSError("websocket connection is closed") from exc
        if isinstance(message, str):
            return message
        self.close(CloseCode.UNSUPPORTED_DATA)
        raise OSError("websocket peer sent a binary frame; only text frames are accepted")

    def close(self, code: CloseCode = CloseCode.NORMAL_CLOSURE) -> None:
        """Idempotent. Waits at most the library ``close_timeout`` for the peer, then releases the socket."""
        try:
            self._ws.close(code)
        except OSError:
            _log.debug("websocket close failed on an already broken socket", exc_info=True)


class WebsocketsConnector:
    """Implements ``copytrade.hl.ws.WsConnector``: each ``connect`` opens one connection to the info WebSocket.

    Contract (W0 test plan):
    - ``url`` is ``ws://`` or ``wss://`` only, and must not point at an exchange/order endpoint (``ValueError``).
    - ``connect`` never blocks longer than ``connect_timeout_s`` and raises only ``OSError`` (refused, timeout,
      failed handshake, non-loopback block).
    - The returned connection is non-blocking: ``recv`` returns the next text frame already received or ``None``;
      after the peer closed or dropped (and buffered frames are drained) it raises ``OSError``, as it does for a
      binary frame, invalid UTF-8 or a frame above ``max_message_bytes``. ``send`` raises ``OSError`` when closed.
    - Heartbeat is F3's (application-level ``{"method":"ping"}``); the library's keepalive is off and protocol
      pings from the server are answered by the library and never surfaced. ``close`` is idempotent, waits at most
      ``connect_timeout_s`` for the peer's close frame and releases the socket.
    - No proxy is used (an ambient HTTPS_PROXY must not redirect the feed) and compression is off.
    """

    def __init__(self, url: str, *, connect_timeout_s: float, max_message_bytes: int) -> None:
        _validate_url(url)
        if not (math.isfinite(connect_timeout_s) and connect_timeout_s > 0):
            raise ValueError("connect_timeout_s must be a positive finite number")
        if max_message_bytes <= 0:
            raise ValueError("max_message_bytes must be positive")
        self._url = url
        self._timeout_s = connect_timeout_s
        self._max_bytes = max_message_bytes

    def connect(self) -> WsConnection:
        try:
            ws = connect(
                self._url,
                open_timeout=self._timeout_s,
                close_timeout=self._timeout_s,
                ping_interval=None,
                ping_timeout=None,
                max_size=self._max_bytes,
                compression=None,
                proxy=None,
                legacy=True,
            )
        except WebSocketException as exc:  # InvalidStatus, InvalidHandshake, InvalidMessage, ...
            raise OSError(f"websocket handshake failed: {type(exc).__name__}") from exc
        return _Connection(ws)
