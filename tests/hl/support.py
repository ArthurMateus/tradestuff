"""Test doubles for the F3 tests. Only true external boundaries are faked: the local clock, sleeping, the
HTTP transport, the WebSocket connector, the alert sink and the ledger. Nothing here re-implements F3.

Fixture payloads live in tests/fixtures/exchange/hl/ (see the README there for their provenance).
"""

from __future__ import annotations

import json
import math
import tempfile
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.config import Config, load_config
from copytrade.core.events import Alert
from copytrade.hl.ledger_port import DowntimeRecord
from copytrade.hl.rest import HttpResponse
from tests.core.helpers import ConfigTree, same_kind

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "exchange" / "hl"
T0 = 1_790_000_000_000  # epoch ms
SECOND = 1_000
MINUTE = 60_000
WALLET_A = "0x1111111111111111111111111111111111111111"
WALLET_B = "0x2222222222222222222222222222222222222222"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


_CONFIG_CACHE: dict[tuple[tuple[str, Any], ...], Config] = {}


def make_config(**overrides: Any) -> Config:
    """The valid fixture config with ``overrides`` (dotted keys written with ``__`` for ``.``), really loaded by F1."""
    key = tuple(sorted(overrides.items()))
    if key not in _CONFIG_CACHE:
        tree = ConfigTree()
        for k, v in overrides.items():
            dotted = k.replace("__", ".")
            tree.set(dotted, same_kind(tree.get(dotted), v))
        root = Path(tempfile.mkdtemp(prefix="f3cfg"))
        _CONFIG_CACHE[key] = load_config(tree.write(root / "config"))
    return _CONFIG_CACHE[key]


class FakeClock:
    def __init__(self, now_ms: int = T0) -> None:
        self.now = now_ms

    def now_ms(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


class FakeSleeper:
    """Advances the fake clock instead of sleeping (rounded up to whole ms)."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock.advance(math.ceil(seconds * 1000))


@dataclass
class RecordingAlerts:
    sent: list[Alert] = field(default_factory=list)

    def send(self, alert: Alert) -> None:
        self.sent.append(alert)

    def of_kind(self, kind: str) -> list[Alert]:
        return [a for a in self.sent if a.kind == kind]


@dataclass
class RecordingLedger:
    records: list[DowntimeRecord] = field(default_factory=list)

    def record_downtime(self, record: DowntimeRecord) -> None:
        self.records.append(record)

    def of_kind(self, kind: str) -> list[DowntimeRecord]:
        return [r for r in self.records if r.kind == kind]


@dataclass
class RecordingSink:
    """Consumer of fills (stands in for F7). Keeps every delivery in order."""

    deliveries: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def on_fills(self, wallet: str, fills: Sequence[Any]) -> None:
        self.deliveries.append((wallet, tuple(fills)))

    def tids(self, wallet: str | None = None) -> list[int]:
        return [f.tid for w, fs in self.deliveries for f in fs if wallet is None or w == wallet]


# --------------------------------------------------------------------------------------------------
# HTTP boundary
# --------------------------------------------------------------------------------------------------

@dataclass
class Call:
    t_ms: int
    url: str
    body: dict[str, Any]
    timeout_s: float


Handler = Callable[[Call], HttpResponse]


class FakeHttp:
    """HttpTransport double. ``handler`` decides each response; it may raise TimeoutError or OSError."""

    def __init__(self, clock: FakeClock, handler: Handler | None = None) -> None:
        self.clock = clock
        self.handler: Handler = handler or self.serve_fixtures
        self.calls: list[Call] = []
        self.overrides: dict[str, Callable[[Call], Any]] = {}

    def post(self, url: str, body: str, *, timeout_s: float) -> HttpResponse:
        call = Call(self.clock.now_ms(), url, json.loads(body), timeout_s)
        self.calls.append(call)
        return self.handler(call)

    def serve_fixtures(self, call: Call) -> HttpResponse:
        rtype = call.body["type"]
        if rtype in self.overrides:
            return ok(self.overrides[rtype](call))
        return ok(fixture(rtype))

    def times(self, rtype: str | None = None) -> list[int]:
        return [c.t_ms for c in self.calls if rtype is None or c.body["type"] == rtype]


def ok(payload: Any) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload))


def status(code: int, body: str = "") -> HttpResponse:
    return HttpResponse(status=code, body=body)


def raising(exc: BaseException) -> Handler:
    def handler(call: Call) -> HttpResponse:
        raise exc

    return handler


def always(code: int, body: str = "") -> Handler:
    return lambda call: status(code, body)


def oracle_weight(rtype: str, items: int = 0, *, user_role: int = 60, portfolio: int = 20) -> int:
    """Independent statement of the F3.AC1 weight table (test oracle, not the code under test)."""
    if rtype in ("l2Book", "allMids", "clearinghouseState"):
        return 2
    if rtype == "userRole":
        return user_role
    if rtype == "portfolio":
        return portfolio
    if rtype in ("userFills", "userFillsByTime", "userFunding", "fundingHistory"):
        return 20 + items // 20
    if rtype == "candleSnapshot":
        return 20 + items // 60
    return 20


def max_window_sum(events: Sequence[tuple[int, int]], window_ms: int = MINUTE) -> int:
    """Largest total weight of ``(t_ms, weight)`` events inside any half-open window [t, t + window_ms)."""
    best = 0
    total = 0
    ev = sorted(events)
    j = 0
    for i, (t, _) in enumerate(ev):
        while j < len(ev) and ev[j][0] < t + window_ms:
            total += ev[j][1]
            j += 1
        best = max(best, total)
        total -= ev[i][1]
    return best


# --------------------------------------------------------------------------------------------------
# WebSocket boundary
# --------------------------------------------------------------------------------------------------

class FakeConnection:
    def __init__(self, clock: FakeClock, *, auto_pong: bool = False) -> None:
        self.clock = clock
        self.inbox: deque[str] = deque()
        self.sent: list[str] = []
        self.closed = False
        self.dead = False  # a dead connection raises OSError on recv
        self.auto_pong = auto_pong

    def push(self, message: Any) -> None:
        self.inbox.append(message if isinstance(message, str) else json.dumps(message))

    def send(self, message: str) -> None:
        if self.dead or self.closed:
            raise OSError("connection closed")
        self.sent.append(message)
        if self.auto_pong and json.loads(message) == {"method": "ping"}:
            self.push({"channel": "pong"})

    def recv(self) -> str | None:
        if self.dead:
            raise OSError("connection lost")
        return self.inbox.popleft() if self.inbox else None

    def close(self) -> None:
        self.closed = True

    def sent_json(self) -> list[dict[str, Any]]:
        return [json.loads(m) for m in self.sent]

    def subscribed_users(self) -> list[str]:
        return [
            m["subscription"]["user"]
            for m in self.sent_json()
            if m.get("method") == "subscribe" and m["subscription"].get("type") == "userFills"
        ]

    def pings(self) -> int:
        return sum(1 for m in self.sent_json() if m == {"method": "ping"})


class FakeConnector:
    """Opens FakeConnections; ``fail`` makes ``connect`` raise OSError; ``die_on_connect`` makes new connections dead."""

    def __init__(self, clock: FakeClock, *, auto_pong: bool = False) -> None:
        self.clock = clock
        self.auto_pong = auto_pong
        self.fail = False
        self.die_on_connect = False
        self.connect_times: list[int] = []
        self.attempt_times: list[int] = []
        self.connections: list[FakeConnection] = []
        self.on_connect: Callable[[FakeConnection], None] | None = None

    def connect(self) -> FakeConnection:
        self.attempt_times.append(self.clock.now_ms())
        if self.fail:
            raise OSError("connect failed")
        self.connect_times.append(self.clock.now_ms())
        conn = FakeConnection(self.clock, auto_pong=self.auto_pong)
        conn.dead = self.die_on_connect
        self.connections.append(conn)
        if self.on_connect is not None:
            self.on_connect(conn)
        return conn

    @property
    def current(self) -> FakeConnection:
        return self.connections[-1]


def fill_json(tid: int, *, time_ms: int | None = None, coin: str = "BTC", **over: Any) -> dict[str, Any]:
    """A wire-format fill shaped like the recorded sample, with a chosen tid and a time that grows with the tid (one hour
    before ``T0`` plus one second per tid; keep tids small)."""
    base = fixture("userFillsByTime")[0]
    out = dict(base)
    out.update(
        tid=tid,
        oid=tid + 1,
        time=T0 - 3_600_000 + tid * 1000 if time_ms is None else time_ms,
        hash="0x" + f"{tid:064x}",
        coin=coin,
    )
    out.update(over)
    return out


def ws_fills(wallet: str, tids: Sequence[int], *, snapshot: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {"user": wallet, "fills": [fill_json(t) for t in tids]}
    if snapshot:
        data["isSnapshot"] = True
    return {"channel": "userFills", "data": data}


def dec(x: str) -> Decimal:
    return Decimal(x)


# --------------------------------------------------------------------------------------------------
# Wiring of the real F3 objects around the fake boundaries
# --------------------------------------------------------------------------------------------------

@dataclass
class Rig:
    """A real HlRestClient with real budget, access monitor and schema monitor over fake boundaries."""

    cfg: Config
    clock: FakeClock
    sleeper: FakeSleeper
    http: FakeHttp
    alerts: RecordingAlerts
    ledger: RecordingLedger
    budget: Any
    access: Any
    schema_monitor: Any
    client: Any


def make_rig(*, seed: int = 1, handler: Handler | None = None, url: str | None = None, transport: Any = None, **overrides: Any) -> Rig:
    import random

    from copytrade.hl.access import AccessMonitor
    from copytrade.hl.budget import RateBudget
    from copytrade.hl.rest import MAINNET_INFO_URL, HlRestClient
    from copytrade.hl.schema import SchemaFailureMonitor

    cfg = make_config(**overrides)
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    http = FakeHttp(clock, handler)
    alerts, ledger = RecordingAlerts(), RecordingLedger()
    budget = RateBudget(
        budget_per_min=cfg["hl.rest_weight_budget_per_min"], scoring_share=cfg["hl.scoring_weight_share"], clock=clock
    )
    access = AccessMonitor(config=cfg, clock=clock, alerts=alerts, ledger=ledger)
    schema_monitor = SchemaFailureMonitor(clock=clock, alerts=alerts)
    client = HlRestClient(
        config=cfg,
        clock=clock,
        transport=transport or http,
        sleeper=sleeper,
        rng=random.Random(seed),
        budget=budget,
        access=access,
        schema_monitor=schema_monitor,
        info_url=url or MAINNET_INFO_URL,
    )
    return Rig(cfg, clock, sleeper, http, alerts, ledger, budget, access, schema_monitor, client)


@dataclass
class FeedRig:
    rig: Rig
    connector: FakeConnector
    sink: RecordingSink
    feed: Any
    server_fills: list[dict[str, Any]]  # what the fake REST server holds for every wallet (wire format)

    @property
    def clock(self) -> FakeClock:
        return self.rig.clock

    def run(self, seconds: int, *, each: Callable[[], None] | None = None) -> None:
        """Advance the fake clock one second at a time, ticking the feed (and the access monitor) each second."""
        for _ in range(seconds):
            self.clock.advance(SECOND)
            if each is not None:
                each()
            self.feed.tick()


def make_feed(*, seed: int = 1, auto_pong: bool = True, **overrides: Any) -> FeedRig:
    import random

    from copytrade.hl.ws import HlWsFeed

    rig = make_rig(seed=seed + 100, **overrides)
    connector = FakeConnector(rig.clock, auto_pong=auto_pong)
    sink = RecordingSink()
    feed = HlWsFeed(
        config=rig.cfg,
        clock=rig.clock,
        connector=connector,
        rest=rig.client,
        rng=random.Random(seed),
        sink=sink,
        ledger=rig.ledger,
        alerts=rig.alerts,
        schema_monitor=rig.schema_monitor,
    )
    server_fills: list[dict[str, Any]] = []

    def serve_fills(call: Call) -> list[dict[str, Any]]:
        lo, hi = call.body["startTime"], call.body.get("endTime")
        return sorted((f for f in server_fills if f["time"] >= lo and (hi is None or f["time"] <= hi)), key=lambda f: f["time"])

    rig.http.overrides["userFillsByTime"] = serve_fills
    return FeedRig(rig, connector, sink, feed, server_fills)
