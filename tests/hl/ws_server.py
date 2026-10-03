"""Loopback fake WebSocket servers for the W0 connector tests. Real sockets on 127.0.0.1 only (the suite network guard
permits nothing else). ``FakeWsServer`` uses the ``websockets`` server API; ``RawWsServer`` speaks just enough RFC 6455
by hand to send things a well-behaved server library refuses to send (bad UTF-8, a non-101 handshake reply, a silent
peer). Nothing here is the unit under test.
"""

from __future__ import annotations

import base64
import hashlib
import json
import queue
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SECRET_BODY = b"SECRET-BODY-xyzzy"
SECRET_HEADER = b"SECRET-HEADER-plugh"
POLL_S = 0.002
WAIT_S = 5.0


def wait_for(condition: Callable[[], Any], *, timeout_s: float = WAIT_S, what: str = "condition") -> Any:
    """Poll a real-socket condition until true. Bounded: a missing event fails the test instead of hanging."""
    deadline = time.monotonic() + timeout_s
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout_s}s waiting for {what}")
        time.sleep(POLL_S)


class ServerSide:
    """One accepted connection, as the fake server sees it. Commands are queued; the handler thread executes them."""

    def __init__(self, auto_pong: bool) -> None:
        self.received: list[str] = []
        self.closed = threading.Event()  # the peer is gone or the handler finished
        self.auto_pong = auto_pong
        self._commands: queue.Queue[tuple[str, Any]] = queue.Queue()

    def send(self, message: str | bytes) -> None:
        self._commands.put(("send", message))

    def protocol_ping(self) -> None:
        self._commands.put(("ping", None))

    def close(self) -> None:
        """Clean close handshake (close frame, code 1000)."""
        self._commands.put(("close", None))

    def abort(self) -> None:
        """Abrupt drop: the TCP connection is torn down with no close frame."""
        self._commands.put(("abort", None))

    def run(self, ws: ServerConnection) -> None:
        try:
            while True:
                try:
                    cmd, arg = self._commands.get_nowait()
                except queue.Empty:
                    cmd, arg = "", None
                if cmd == "send":
                    ws.send(arg)
                elif cmd == "ping":
                    ws.ping()
                elif cmd == "close":
                    ws.close()
                    return
                elif cmd == "abort":
                    ws.socket.shutdown(socket.SHUT_RDWR)
                    return
                try:
                    message = ws.recv(timeout=0.005)
                except TimeoutError:
                    continue
                text = message if isinstance(message, str) else message.decode("utf-8", "replace")
                self.received.append(text)
                if self.auto_pong and text == json.dumps({"method": "ping"}):
                    ws.send(json.dumps({"channel": "pong"}))
        except (ConnectionClosed, OSError):
            pass
        finally:
            self.closed.set()


class FakeWsServer:
    """A ``websockets`` server on 127.0.0.1 with an ephemeral port, serving in a background thread."""

    def __init__(self, *, auto_pong: bool = True) -> None:
        self.auto_pong = auto_pong
        self.connections: list[ServerSide] = []
        self._lock = threading.Lock()
        self._server = serve(self._handle, "127.0.0.1", 0)
        self.port: int = self._server.socket.getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}/ws"
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            self._server.serve_forever()
        except OSError:  # stopped before the serve loop finished starting
            pass

    def _handle(self, ws: ServerConnection) -> None:
        side = ServerSide(self.auto_pong)
        with self._lock:
            self.connections.append(side)
        side.run(ws)

    def wait_connection(self, index: int = 0) -> ServerSide:
        return wait_for(lambda: self.connections[index] if len(self.connections) > index else None, what="a client")

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=WAIT_S)

    def __enter__(self) -> FakeWsServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


def _text_frame(payload: bytes) -> bytes:
    assert len(payload) < 126
    return bytes([0x81, len(payload)]) + payload


class RawWsServer:
    """Hand-rolled loopback peer. ``mode``: ``hold`` (accepts TCP, never answers the handshake), ``http403`` (answers the
    upgrade with 403), ``bad_utf8`` (valid handshake, then a text frame holding invalid UTF-8), ``server_ping``
    (valid handshake, a protocol ping frame, then the text frame ``hello``)."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self.port: int = self._listener.getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}/ws"
        self.accepted = 0
        self.pong_seen = threading.Event()
        self.handshake_request = b""  # the upgrade request as the peer saw it (``record``/``silent``/``binary`` modes)
        self.frames: list[tuple[int, bytes]] = []  # client frames seen as (opcode, unmasked payload)
        self.frames_lock = threading.Lock()
        self._peers: list[socket.socket] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                peer, _ = self._listener.accept()
            except OSError:
                return
            self.accepted += 1
            self._peers.append(peer)
            if self.mode != "hold":
                threading.Thread(target=self._talk, args=(peer,), daemon=True).start()

    def _talk(self, peer: socket.socket) -> None:
        try:
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = peer.recv(4096)
                if not chunk:
                    return
                request += chunk
            self.handshake_request = request
            if self.mode == "http403":
                peer.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            if self.mode.startswith("http:"):  # e.g. ``http:429``, with a body and header a leak would show
                code = int(self.mode.split(":", 1)[1])
                body = SECRET_BODY
                peer.sendall(
                    b"HTTP/1.1 %d Whatever\r\nX-Secret-Header: " % code
                    + SECRET_HEADER
                    + b"\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body)
                    + body
                )
                return
            key = next(
                line.split(b":", 1)[1].strip() for line in request.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key")
            )
            accept = base64.b64encode(hashlib.sha1(key + _GUID).digest())
            peer.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
            )
            if self.mode == "silent":  # valid handshake, then the peer never reads or answers anything again
                threading.Event().wait(WAIT_S * 2)
                return
            if self.mode in ("record", "binary"):
                if self.mode == "binary":
                    peer.sendall(bytes([0x82, 3]) + b"\x01\x02\x03")
                self._record_frames(peer)
                return
            if self.mode == "bad_utf8":
                peer.sendall(_text_frame(b"\xff\xfe\xfd"))
            elif self.mode == "server_ping":
                peer.sendall(bytes([0x89, 0x00]) + _text_frame(b"hello"))
                peer.settimeout(WAIT_S)
                if peer.recv(64)[:1] == b"\x8a":  # the client's pong
                    self.pong_seen.set()
        except OSError:
            return

    def _record_frames(self, peer: socket.socket) -> None:
        """Parse masked client frames (payloads under 126 bytes) into ``frames``; answer a close frame with a close."""
        peer.settimeout(WAIT_S * 2)
        buf = b""
        while True:
            while len(buf) < 2 or len(buf) < 6 + (buf[1] & 0x7F):
                chunk = peer.recv(4096)
                if not chunk:
                    return
                buf += chunk
            opcode, length = buf[0] & 0x0F, buf[1] & 0x7F
            assert length < 126 and buf[1] & 0x80, "test peer only parses small masked client frames"
            mask, payload = buf[2:6], buf[6 : 6 + length]
            buf = buf[6 + length :]
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            with self.frames_lock:
                self.frames.append((opcode, data))
            if opcode == 0x8:
                peer.sendall(bytes([0x88, len(data)]) + data)
                peer.close()
                return

    def frames_of(self, opcode: int) -> list[bytes]:
        with self.frames_lock:
            return [d for o, d in self.frames if o == opcode]

    def stop(self) -> None:
        self._listener.close()
        for peer in self._peers:
            peer.close()

    def __enter__(self) -> RawWsServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


def closed_port() -> int:
    """A loopback port nothing listens on (bound, read, released)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
