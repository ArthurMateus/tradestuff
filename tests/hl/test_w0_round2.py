"""W0 round 2: tests that kill the hand mutants the senior-dev review found alive (see 05-test-plan-W0.md, round 2).
Real loopback sockets only (``tests/hl/ws_server.py``); the only polling is the bounded ``wait_for``.
"""

from __future__ import annotations

import json
import struct
import time
from collections.abc import Iterator

import pytest

from copytrade.hl.connector import WebsocketsConnector
from copytrade.hl.ws import WsConnection
from tests.hl.ws_server import SECRET_BODY, SECRET_HEADER, FakeWsServer, RawWsServer, wait_for

pytestmark = pytest.mark.integration

CLOSE_TIMEOUT_CAP_S = 1.0  # agreed: close waits min(connect_timeout_s, 1.0) for the peer's close frame


def make(url: str, *, timeout_s: float = 2.0, max_bytes: int = 1024 * 1024) -> WebsocketsConnector:
    return WebsocketsConnector(url, connect_timeout_s=timeout_s, max_message_bytes=max_bytes)


@pytest.fixture
def server() -> Iterator[FakeWsServer]:
    with FakeWsServer() as s:
        yield s


def _timed_close(conn: WsConnection) -> float:
    start = time.monotonic()
    conn.close()
    return time.monotonic() - start


# (a) close is bounded against a peer that never answers the close handshake -------------------------------------------


def test_W0_r2_close_is_capped_at_one_second_against_a_silent_peer_even_with_a_large_connect_timeout() -> None:
    with RawWsServer("silent") as srv:
        conn = make(srv.url, timeout_s=5.0).connect()
        wait_for(lambda: srv.handshake_request, what="the handshake")
        elapsed = _timed_close(conn)
    assert elapsed <= 2 * CLOSE_TIMEOUT_CAP_S, f"close took {elapsed:.2f}s against a peer that never answers"


def test_W0_r2_close_with_a_small_connect_timeout_is_bounded_by_that_timeout_against_a_silent_peer() -> None:
    with RawWsServer("silent") as srv:
        conn = make(srv.url, timeout_s=0.3).connect()
        wait_for(lambda: srv.handshake_request, what="the handshake")
        elapsed = _timed_close(conn)
    assert elapsed <= 2 * 0.3 + 0.1, f"close took {elapsed:.2f}s with connect_timeout_s=0.3"


def test_W0_r2_close_is_idempotent_and_still_bounded_on_the_second_call_against_a_silent_peer() -> None:
    with RawWsServer("silent") as srv:
        conn = make(srv.url, timeout_s=5.0).connect()
        wait_for(lambda: srv.handshake_request, what="the handshake")
        first = _timed_close(conn)
        second = _timed_close(conn)
    assert first <= 2 * CLOSE_TIMEOUT_CAP_S
    assert second <= 0.5


# (b) a binary frame makes the client send close code 1003 -------------------------------------------------------------


def test_W0_r2_binary_frame_makes_the_client_send_close_code_1003_unsupported_data() -> None:
    with RawWsServer("binary") as srv:
        conn = make(srv.url).connect()
        try:
            with pytest.raises(OSError):
                wait_for(lambda: conn.recv(), what="the binary frame to be rejected")
            closes = wait_for(lambda: srv.frames_of(0x8), what="the client close frame")
        finally:
            conn.close()
    assert struct.unpack("!H", closes[0][:2])[0] == 1003


def test_W0_r2_normal_close_sends_code_1000() -> None:
    with RawWsServer("record") as srv:
        conn = make(srv.url).connect()
        wait_for(lambda: srv.handshake_request, what="the handshake")
        conn.close()
        closes = wait_for(lambda: srv.frames_of(0x8), what="the client close frame")
    assert struct.unpack("!H", closes[0][:2])[0] == 1000


# (c) keepalive stays off, compression is not negotiated ---------------------------------------------------------------


def test_W0_r2_client_sends_no_protocol_ping_over_an_idle_period_and_no_frame_at_all() -> None:
    with RawWsServer("record") as srv:
        conn = make(srv.url, timeout_s=0.2).connect()
        try:
            wait_for(lambda: srv.handshake_request, what="the handshake")
            deadline = (
                time.monotonic() + 0.5
            )  # real idle time; any keepalive ping_interval worth having fires well inside it
            while time.monotonic() < deadline:
                assert conn.recv() is None
                time.sleep(0.01)
            assert srv.frames_of(0x9) == []
            assert srv.frames == []
        finally:
            conn.close()


def test_W0_r2_permessage_deflate_is_not_negotiated() -> None:
    with RawWsServer("record") as srv:
        conn = make(srv.url).connect()
        try:
            request = wait_for(lambda: srv.handshake_request, what="the handshake")
        finally:
            conn.close()
    assert b"permessage-deflate" not in request.lower()
    assert b"sec-websocket-extensions" not in request.lower()


# (d) handshake errors name the status code and leak nothing else ------------------------------------------------------


@pytest.mark.parametrize("code", [403, 429])
def test_W0_r2_invalid_status_error_message_carries_the_http_status_code_only(code: int) -> None:
    with RawWsServer(f"http:{code}") as srv:
        with pytest.raises(OSError) as info:
            make(srv.url).connect()
    text = str(info.value)
    assert str(code) in text
    assert srv.url not in text and f"127.0.0.1:{srv.port}" not in text and "/ws" not in text
    assert SECRET_BODY.decode() not in text and SECRET_HEADER.decode() not in text
    assert "sec-websocket" not in text.lower()


# (e) burst: 300 back-to-back text frames, all delivered in order ------------------------------------------------------


def test_W0_r2_a_burst_of_300_text_frames_is_delivered_complete_and_in_order_by_non_blocking_recv(
    server: FakeWsServer,
) -> None:
    conn = make(server.url).connect()
    try:
        side = server.wait_connection()
        sent = [json.dumps({"n": i}) for i in range(300)]
        for m in sent:
            side.send(m)
        got: list[str] = []

        def drained() -> bool:
            while (m := conn.recv()) is not None:
                got.append(m)
            return len(got) >= 300

        wait_for(drained, what="300 frames")
        assert got == sent
        assert conn.recv() is None
    finally:
        conn.close()
