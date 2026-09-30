"""Concrete F3 WebSocket connector over the ``websockets`` library (W0). The only module allowed to import it."""

from __future__ import annotations

from copytrade.hl.ws import WsConnection

__all__ = ["WebsocketsConnector"]


class WebsocketsConnector:
    """Implements ``copytrade.hl.ws.WsConnector``: each ``connect`` opens one connection to the info WebSocket.

    Contract (W0 test plan):
    - ``url`` is ``ws://`` or ``wss://`` only, and must not point at an exchange/order endpoint (``ValueError``).
    - ``connect`` never blocks longer than ``connect_timeout_s`` and raises only ``OSError`` (refused, timeout,
      failed handshake, non-loopback block).
    - The returned connection is non-blocking: ``recv`` returns the next text frame already received or ``None``;
      after the peer closed or dropped (and buffered frames are drained) it raises ``OSError``, as it does for a
      binary frame, invalid UTF-8 or a frame above ``max_message_bytes``. ``send`` raises ``OSError`` when closed.
    - Heartbeat is F3's (application-level ``{"method":"ping"}``); protocol pings from the server are answered
      by the library and never surfaced. ``close`` is idempotent and releases the socket.
    """

    def __init__(self, url: str, *, connect_timeout_s: float, max_message_bytes: int) -> None:
        raise NotImplementedError

    def connect(self) -> WsConnection:
        raise NotImplementedError
