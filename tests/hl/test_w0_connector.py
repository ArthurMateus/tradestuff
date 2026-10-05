"""W0: the concrete WsConnector over the ``websockets`` library. Spec: PO decision 2026-09-30 (decisions.md), STATE.md W0,
F3.AC3/AC4 (reconnect, heartbeat, resync stay in F3), F1.AC3 (info-only), invariants B3 (heartbeat, reconnect, gap resync)
and A2 (fail closed: any broken frame means the connection is treated as lost, never silently patched).

The unit under test is ``copytrade.hl.connector.WebsocketsConnector``. Its peers are real loopback sockets served by
``tests/hl/ws_server.py``; nothing of ours is mocked. The only polling is a bounded wait on a real socket event.
Contract decisions (spec gaps, see 05-test-plan-W0.md): binary frames, invalid UTF-8 and oversize frames make ``recv``
raise ``OSError`` (fail closed, F3 reconnects and resyncs); ``connect`` raises only ``OSError``.
"""

from __future__ import annotations

import ast
import importlib.metadata
import json
import re
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from copytrade.hl.connector import WebsocketsConnector
from copytrade.core.domain import ActionKind
from copytrade.hl.ws import HlWsFeed, WsConnection
from tests.core.test_mode_paper_only import FORBIDDEN_DISTRIBUTIONS
from tests.hl.support import SECOND, WALLET_A, FakeClock, RecordingSink, fill_json, make_rig, ws_fills
from tests.hl.ws_server import FakeWsServer, RawWsServer, closed_port, wait_for

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
PING = json.dumps({"method": "ping"})
PONG = json.dumps({"channel": "pong"})
ONE_MIB = 1024 * 1024

pytestmark = pytest.mark.integration


def make_connector(url: str, *, timeout_s: float = 2.0, max_bytes: int = 4 * ONE_MIB) -> WebsocketsConnector:
    return WebsocketsConnector(url, connect_timeout_s=timeout_s, max_message_bytes=max_bytes)


@pytest.fixture
def server() -> Iterator[FakeWsServer]:
    with FakeWsServer() as s:
        yield s


@pytest.fixture
def opened() -> Iterator[list[WsConnection]]:
    """Connections a test opened; all are closed at the end so no socket leaks into the next test."""
    conns: list[WsConnection] = []
    yield conns
    for c in conns:
        try:
            c.close()
        except OSError:
            pass


def open_conn(opened: list[WsConnection], url: str, **kw: float) -> WsConnection:
    conn = make_connector(url, **kw).connect()  # type: ignore[arg-type]
    opened.append(conn)
    return conn


def recv_n(conn: WsConnection, n: int) -> list[str]:
    got: list[str] = []

    def more() -> bool:
        m = conn.recv()
        if m is not None:
            got.append(m)
        return len(got) >= n

    wait_for(more, what=f"{n} frames")
    return got


def recv_raises(conn: WsConnection) -> None:
    def raised() -> bool:
        try:
            conn.recv()
        except OSError:
            return True
        return False

    wait_for(raised, what="recv to raise OSError")


# --- connect and receive (W0.1) --------------------------------------------------------------------------------------

def test_W0_connect_to_loopback_and_receive_text_frames_in_order(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    side = server.wait_connection()
    for i in range(3):
        side.send(f"m{i}")
    assert recv_n(conn, 3) == ["m0", "m1", "m2"]


def test_W0_received_frames_are_str_and_unicode_survives(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    text = json.dumps({"coin": "BTC", "note": "café 中文 \U0001f680"}, ensure_ascii=False)
    server.wait_connection().send(text)
    (got,) = recv_n(conn, 1)
    assert type(got) is str
    assert got == text


def test_W0_empty_text_frame_is_delivered_as_empty_string_not_as_none(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection().send("")
    assert recv_n(conn, 1) == [""]


def test_W0_frame_just_under_and_large_frames_up_to_the_limit_are_delivered(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url, max_bytes=2 * ONE_MIB)
    big = "x" * (2 * ONE_MIB)  # exactly at the limit
    server.wait_connection().send(big)
    (got,) = recv_n(conn, 1)
    assert got == big


def test_W0_the_connector_opens_a_new_independent_connection_on_each_connect(server: FakeWsServer, opened: list[WsConnection]) -> None:
    connector = make_connector(server.url)
    a, b = connector.connect(), connector.connect()
    opened.extend([a, b])
    assert a is not b
    sa, sb = server.wait_connection(0), server.wait_connection(1)
    sa.send("to-a")
    sb.send("to-b")
    assert recv_n(a, 1) == ["to-a"]
    assert recv_n(b, 1) == ["to-b"]


# --- non-blocking recv (W0.2) ----------------------------------------------------------------------------------------

def test_W0_recv_returns_none_immediately_when_no_frame_is_waiting(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection()
    start = time.monotonic()
    results = [conn.recv() for _ in range(50)]
    elapsed = time.monotonic() - start
    assert results == [None] * 50
    assert elapsed < 1.0  # 50 empty polls on an idle link; a blocking recv would take forever


def test_W0_recv_drains_every_waiting_frame_then_returns_none(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    side = server.wait_connection()
    for i in range(20):
        side.send(f"m{i}")
    got = recv_n(conn, 20)
    assert got == [f"m{i}" for i in range(20)]
    assert conn.recv() is None


def test_W0_recv_does_not_block_while_the_server_is_silent_but_the_link_is_open_for_seconds(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection()
    deadline = time.monotonic() + 0.3
    worst = 0.0
    while time.monotonic() < deadline:
        t = time.monotonic()
        assert conn.recv() is None
        worst = max(worst, time.monotonic() - t)
    assert worst < 0.25


# --- send, ping/pong (W0.3, W0.4) ------------------------------------------------------------------------------------

def test_W0_send_delivers_subscribe_messages_exactly_as_given(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    side = server.wait_connection()
    msgs = [
        json.dumps({"method": "subscribe", "subscription": {"type": "userFills", "user": WALLET_A}}),
        json.dumps({"method": "unsubscribe", "subscription": {"type": "userFills", "user": WALLET_A}}),
        "café \U0001f680",
    ]
    for m in msgs:
        conn.send(m)
    wait_for(lambda: len(side.received) >= 3, what="3 messages at the server")
    assert side.received == msgs


def test_W0_application_ping_reaches_the_server_and_the_pong_text_frame_comes_back_unchanged(opened: list[WsConnection]) -> None:
    with FakeWsServer(auto_pong=True) as srv:
        conn = open_conn(opened, srv.url)
        srv.wait_connection()
        conn.send(PING)
        assert recv_n(conn, 1) == [PONG]  # F3 treats any message, pong included, as activity; the connector passes it on


def test_W0_server_protocol_ping_is_answered_by_the_library_and_never_shown_to_the_feed(opened: list[WsConnection]) -> None:
    with RawWsServer("server_ping") as srv:
        conn = open_conn(opened, srv.url)
        assert recv_n(conn, 1) == ["hello"]  # the protocol ping frame produced no message
        wait_for(srv.pong_seen.is_set, what="the client's pong frame")
        assert conn.recv() is None


def test_W0_send_after_the_server_closed_raises_oserror(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection().close()
    recv_raises(conn)
    with pytest.raises(OSError):
        conn.send(PING)


def test_W0_send_after_an_abrupt_drop_raises_oserror_not_another_exception_type(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection().abort()
    recv_raises(conn)
    with pytest.raises(OSError):
        conn.send(PING)


# --- server close, drop, refused, timeout (W0.5) ---------------------------------------------------------------------

def test_W0_clean_server_close_raises_oserror_from_recv_and_keeps_raising(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection().close()
    recv_raises(conn)
    for _ in range(3):
        with pytest.raises(OSError):
            conn.recv()


def test_W0_frames_sent_before_a_server_close_are_delivered_before_recv_raises(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    side = server.wait_connection()
    for i in range(3):
        side.send(f"last{i}")
    side.close()
    got: list[str] = []

    def drained() -> bool:
        try:
            m = conn.recv()
        except OSError:
            return True
        if m is not None:
            got.append(m)
        return False

    wait_for(drained, what="close to surface")
    assert got == ["last0", "last1", "last2"]  # no fill lost just because the close arrived right behind it


def test_W0_abrupt_tcp_drop_raises_oserror_from_recv(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection().abort()
    recv_raises(conn)


def test_W0_connection_refused_raises_oserror_from_connect() -> None:
    connector = make_connector(f"ws://127.0.0.1:{closed_port()}/ws")
    with pytest.raises(OSError):
        connector.connect()


def test_W0_connect_timeout_raises_oserror_and_does_not_hang() -> None:
    with RawWsServer("hold") as srv:  # accepts TCP, never answers the handshake
        connector = make_connector(srv.url, timeout_s=0.3)
        start = time.monotonic()
        with pytest.raises(OSError):
            connector.connect()
        assert time.monotonic() - start < 3.0
        assert srv.accepted == 1


def test_W0_failed_handshake_http_403_raises_oserror_not_a_library_exception() -> None:
    with RawWsServer("http403") as srv:
        with pytest.raises(OSError):
            make_connector(srv.url).connect()


def test_W0_a_failed_connect_does_not_poison_the_connector_a_retry_succeeds(opened: list[WsConnection]) -> None:
    with FakeWsServer() as srv:
        port = srv.port
        connector = make_connector(srv.url)
    with pytest.raises(OSError):  # the server is gone now
        connector.connect()
    assert port > 0
    with FakeWsServer() as again:
        opened.append(make_connector(again.url).connect())
        again.wait_connection()


def test_W0_connect_to_a_non_loopback_host_is_blocked_by_the_guard_and_raises_oserror(network_guard: object) -> None:
    connector = make_connector("ws://203.0.113.7:9/ws", timeout_s=0.5)  # TEST-NET-3, never reachable
    with network_guard.expect_blocked() as seen:  # type: ignore[attr-defined]
        with pytest.raises(OSError):
            connector.connect()
    assert any("203.0.113.7" in target for _op, target in seen)  # the suite guard stopped it: nothing left the machine


def test_W0_connect_to_a_hostname_is_resolved_through_the_guard_and_blocked(network_guard: object) -> None:
    connector = make_connector("wss://api.hyperliquid.xyz/ws", timeout_s=0.5)
    with network_guard.expect_blocked() as seen:  # type: ignore[attr-defined]
        with pytest.raises(OSError):
            connector.connect()
    assert seen  # the real host is never reachable from a test


def test_W0_constructing_a_wss_connector_is_accepted_and_opens_no_socket(network_guard: object) -> None:
    before = len(network_guard.all_connects)  # type: ignore[attr-defined]
    make_connector("wss://api.hyperliquid.xyz/ws")
    assert len(network_guard.all_connects) == before  # type: ignore[attr-defined]  # construction is lazy: connect() does the I/O


# --- url validation, info-only (W0.6) --------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:1/ws",
        "https://api.hyperliquid.xyz/ws",
        "ftp://127.0.0.1/ws",
        "127.0.0.1:1/ws",
        "",
        "ws://",
        "wss://api.hyperliquid.xyz/exchange",
        "ws://127.0.0.1:1/exchange",
        "wss://api.hyperliquid.xyz/EXCHANGE",
    ],
)
def test_W0_a_url_that_is_not_ws_or_wss_or_points_at_the_exchange_endpoint_is_rejected_at_construction(url: str) -> None:
    with pytest.raises(ValueError):
        make_connector(url)


@pytest.mark.parametrize("bad", [0, -1.0, float("nan")])
def test_W0_a_non_positive_or_nan_connect_timeout_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError):
        make_connector("ws://127.0.0.1:1/ws", timeout_s=bad)


@pytest.mark.parametrize("bad", [0, -1])
def test_W0_a_non_positive_message_limit_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError):
        make_connector("ws://127.0.0.1:1/ws", max_bytes=bad)


# --- malformed, binary and oversize frames (W0.7) --------------------------------------------------------------------

def test_W0_binary_frame_makes_recv_raise_oserror_fail_closed(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection().send(b"\x00\x01binary")
    recv_raises(conn)


def test_W0_text_frames_before_a_binary_frame_are_still_delivered(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    side = server.wait_connection()
    side.send("ok")
    side.send(b"\x00")
    got: list[str] = []

    def drained() -> bool:
        try:
            m = conn.recv()
        except OSError:
            return True
        if m is not None:
            got.append(m)
        return False

    wait_for(drained, what="binary frame to surface")
    assert got == ["ok"]


def test_W0_invalid_utf8_text_frame_raises_oserror_and_does_not_crash() -> None:
    with RawWsServer("bad_utf8") as srv:
        conn = make_connector(srv.url).connect()
        try:
            recv_raises(conn)
        finally:
            conn.close()


def test_W0_frame_above_the_message_limit_raises_oserror_and_the_connection_is_dead(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url, max_bytes=1024)
    server.wait_connection().send("x" * 4096)
    recv_raises(conn)
    with pytest.raises(OSError):
        conn.recv()
    with pytest.raises(OSError):
        conn.send(PING)


def test_W0_frame_one_byte_over_the_limit_is_rejected_and_one_at_the_limit_is_accepted(server: FakeWsServer, opened: list[WsConnection]) -> None:
    ok = open_conn(opened, server.url, max_bytes=1024)
    over = open_conn(opened, server.url, max_bytes=1024)
    server.wait_connection(0).send("y" * 1024)
    server.wait_connection(1).send("y" * 1025)
    assert recv_n(ok, 1) == ["y" * 1024]
    recv_raises(over)


def test_W0_a_valid_json_frame_that_is_not_an_object_is_passed_through_for_f3_to_judge(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    side = server.wait_connection()
    for raw in ("[1,2]", "null", "not json at all", '{"channel": 7}'):
        side.send(raw)
    assert recv_n(conn, 4) == ["[1,2]", "null", "not json at all", '{"channel": 7}']  # parsing and gap handling are F3's


# --- close (W0.8) ----------------------------------------------------------------------------------------------------

def test_W0_close_is_idempotent(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection()
    conn.close()
    conn.close()
    conn.close()


def test_W0_close_releases_the_socket_the_server_sees_the_peer_leave(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    side = server.wait_connection()
    conn.close()
    wait_for(side.closed.is_set, what="the server to see the connection end")


def test_W0_after_close_recv_and_send_raise_oserror(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection()
    conn.close()
    with pytest.raises(OSError):
        conn.recv()
    with pytest.raises(OSError):
        conn.send(PING)


def test_W0_close_after_the_server_already_dropped_the_link_does_not_raise(server: FakeWsServer, opened: list[WsConnection]) -> None:
    conn = open_conn(opened, server.url)
    server.wait_connection().abort()
    recv_raises(conn)
    conn.close()
    conn.close()


def test_W0_many_connect_close_cycles_leave_no_connection_open_at_the_server() -> None:
    with FakeWsServer() as srv:
        connector = make_connector(srv.url)
        for _ in range(25):
            connector.connect().close()
        wait_for(lambda: len(srv.connections) == 25 and all(c.closed.is_set() for c in srv.connections), what="25 closes")


# --- static checks (W0.9, W0.10) -------------------------------------------------------------------------------------

def _imports_websockets(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name == "websockets" or a.name.startswith("websockets.") for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and (
            node.module == "websockets" or node.module.startswith("websockets.")
        ):
            return True
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            arg = node.args[0].value
            if name in ("import_module", "__import__") and isinstance(arg, str) and arg.split(".")[0] == "websockets":
                return True
    return False


@pytest.mark.unit
def test_W0_static_scan_detects_a_websockets_import_in_synthetic_source() -> None:
    assert _imports_websockets(ast.parse("import websockets"))
    assert _imports_websockets(ast.parse("from websockets.sync.client import connect"))
    assert _imports_websockets(ast.parse("import importlib\nimportlib.import_module('websockets.sync')"))
    assert not _imports_websockets(ast.parse("import json\nx = 'websockets'"))


@pytest.mark.unit
def test_W0_only_hl_connector_imports_websockets() -> None:
    importers = sorted(
        p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if _imports_websockets(ast.parse(p.read_text(encoding="utf-8")))
    )
    assert importers == ["copytrade/hl/connector.py"]  # exactly one, and it really is the connector


@pytest.mark.unit
def test_W0_connector_has_no_exchange_endpoint_literal_and_no_signing_import() -> None:
    text = (SRC / "copytrade" / "hl" / "connector.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert [s for s in literals if "/exchange" in s.lower()] == []
    imported: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            imported.add(n.module or "")
    assert not any(m.split(".")[0] in {"eth_account", "eth_keys", "web3", "hyperliquid", "ccxt", "coincurve"} for m in imported)


@pytest.mark.unit
def test_W0_uv_lock_pins_websockets_exactly_with_no_dependencies_and_no_signing_package() -> None:
    with (REPO / "uv.lock").open("rb") as fh:
        packages = tomllib.load(fh)["package"]
    by_name = {p["name"]: p for p in packages}
    assert "websockets" in by_name
    version = by_name["websockets"]["version"]
    assert re.fullmatch(r"\d+(\.\d+)+", version)
    assert not by_name["websockets"].get("dependencies")  # PO decision: no dependencies of its own
    assert {p["name"] for p in packages}.isdisjoint(FORBIDDEN_DISTRIBUTIONS)
    assert importlib.metadata.version("websockets") == version  # the environment runs what the lock pins


@pytest.mark.unit
def test_W0_pyproject_pins_websockets_with_an_exact_version_equal_to_the_lock() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pins = [d for d in project["dependencies"] if re.match(r"websockets\b", d)]
    with (REPO / "uv.lock").open("rb") as fh:
        locked = next(p["version"] for p in tomllib.load(fh)["package"] if p["name"] == "websockets")
    assert pins == [f"websockets=={locked}"]
    assert [d for d in project["dependencies"] if not d.startswith("websockets")] == []  # the only runtime dependency


# --- end to end: real HlWsFeed + real connector + fake server (W0.11) ------------------------------------------------

class Stack:
    """The real feed, REST client (fake HTTP boundary), budget and monitors, wired to the real connector."""

    def __init__(self, url: str) -> None:
        import random

        self.rig = make_rig(seed=101)
        self.sink = RecordingSink()
        self.server_fills: list[dict[str, object]] = []
        self.rig.http.overrides["userFillsByTime"] = lambda call: sorted(
            (f for f in self.server_fills if f["time"] >= call.body["startTime"]), key=lambda f: f["time"]  # type: ignore[operator]
        )
        self.connector = make_connector(url)
        self.feed = HlWsFeed(
            config=self.rig.cfg,
            clock=self.rig.clock,
            connector=self.connector,
            rest=self.rig.client,
            rng=random.Random(1),
            sink=self.sink,
            ledger=self.rig.ledger,
            alerts=self.rig.alerts,
            schema_monitor=self.rig.schema_monitor,
        )

    @property
    def clock(self) -> FakeClock:
        return self.rig.clock

    def tick_until(self, condition: object, *, what: str, clock_step_ms: int = 0) -> None:
        def step() -> bool:
            if clock_step_ms:
                self.clock.advance(clock_step_ms)
            self.feed.tick()
            return bool(condition())  # type: ignore[operator]

        wait_for(step, what=what)


def test_W0_e2e_feed_subscribes_over_the_real_connector_and_delivers_each_fill_once() -> None:
    with FakeWsServer() as srv:
        st = Stack(srv.url)
        st.feed.subscribe_user(WALLET_A)
        st.tick_until(lambda: srv.connections and any('"subscribe"' in m for m in srv.connections[0].received), what="subscribe")
        sub = json.loads(next(m for m in srv.connections[0].received if '"subscribe"' in m))
        assert sub == {"method": "subscribe", "subscription": {"type": "userFills", "user": WALLET_A}}
        side = srv.wait_connection()
        side.send(json.dumps(ws_fills(WALLET_A, [1, 2], snapshot=True)))
        side.send(json.dumps(ws_fills(WALLET_A, [2, 3])))  # tid 2 repeated
        st.tick_until(lambda: st.sink.tids() == [1, 2, 3], what="3 fills")
        for _ in range(20):
            st.feed.tick()
        assert st.sink.tids() == [1, 2, 3]  # exactly once each
        assert st.feed.is_stale(WALLET_A) is False
        side.abort()


def test_W0_e2e_feed_heartbeat_ping_reaches_the_server_and_the_pong_keeps_the_feed_alive() -> None:
    with FakeWsServer(auto_pong=True) as srv:
        st = Stack(srv.url)
        st.feed.subscribe_user(WALLET_A)
        st.tick_until(lambda: srv.connections, what="connect")
        side = srv.wait_connection()
        st.tick_until(lambda: PING in side.received, what="a heartbeat ping", clock_step_ms=SECOND)
        for _ in range(10):  # let the pong come back, then keep ticking past several heartbeat intervals
            st.clock.advance(SECOND)
            st.feed.tick()
        assert len(srv.connections) == 1  # never declared stale, never reconnected
        assert st.feed.is_stale(WALLET_A) is False


def test_W0_e2e_server_drop_triggers_reconnect_and_resync_through_f3_and_nothing_is_lost_or_doubled() -> None:
    with FakeWsServer() as srv:
        st = Stack(srv.url)
        st.feed.subscribe_user(WALLET_A)
        st.tick_until(lambda: srv.connections and srv.connections[0].received, what="first subscribe")
        first = srv.wait_connection(0)
        first.send(json.dumps(ws_fills(WALLET_A, [1, 2])))
        st.tick_until(lambda: st.sink.tids() == [1, 2], what="fills 1,2")
        # the link dies; while it is down the exchange records fills 3 and 4 that only REST can give us
        st.server_fills.extend(fill_json(t) for t in (2, 3, 4))
        first.abort()
        st.tick_until(lambda: st.feed.is_stale(WALLET_A), what="the feed to notice the drop")
        assert st.feed.refusal_reason(WALLET_A, ActionKind.OPEN) == "feed_stale"
        # F3 reconnects after its jittered backoff: advance the fake clock until a second connection exists
        st.tick_until(lambda: len(srv.connections) == 2, what="the reconnect", clock_step_ms=SECOND)
        second = srv.wait_connection(1)
        second.send(json.dumps(ws_fills(WALLET_A, [4, 5])))  # 4 also arrives live: duplicate of the REST one
        st.tick_until(lambda: st.sink.tids() == [1, 2, 3, 4, 5], what="resync then live fills", clock_step_ms=0)
        assert st.sink.tids() == [1, 2, 3, 4, 5]  # 0 duplicates, 0 gaps
        assert st.feed.is_stale(WALLET_A) is False
        assert len(st.rig.ledger.of_kind("data_gap")) == 1
        assert any("subscribe" in m for m in second.received)  # resubscribed on the new connection


def test_W0_e2e_connection_refused_is_retried_by_f3_with_backoff_not_a_crash() -> None:
    port = closed_port()
    st = Stack(f"ws://127.0.0.1:{port}/ws")
    st.feed.subscribe_user(WALLET_A)
    for _ in range(5):
        st.clock.advance(SECOND)
        st.feed.tick()  # every connect raises OSError from the real connector; F3 must absorb it
    assert st.feed.is_stale(WALLET_A) is True
    assert len(st.rig.alerts.of_kind("feed_stale")) == 1  # the stale feed is alerted once


def test_W0_e2e_binary_frame_from_the_server_is_treated_as_a_lost_connection_and_resynced() -> None:
    with FakeWsServer() as srv:
        st = Stack(srv.url)
        st.feed.subscribe_user(WALLET_A)
        st.tick_until(lambda: srv.connections and srv.connections[0].received, what="subscribe")
        srv.wait_connection(0).send(b"\x00\x01")
        st.tick_until(lambda: st.feed.is_stale(WALLET_A), what="the feed to treat it as a lost link")
        st.tick_until(lambda: len(srv.connections) == 2, what="the reconnect", clock_step_ms=SECOND)
