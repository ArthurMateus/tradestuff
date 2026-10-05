"""Support for the R1 backfill-fix tests: a fake Hyperliquid at the HTTP boundary and the real client, budget, backfiller
(and, for the manager tests, the real follow manager and ``PacedInputs``) around it.

Faked at the true boundary only: HTTP (``FakeHl``: serves ``userFillsByTime`` per wallet exactly like the exchange does,
at most 2 000 fills per request, earliest first, ``startTime`` inclusive), the clock, the sleeper, the candle source,
the clearinghouse-state source, the open-share source, the leaderboard source and the score store. Nothing here decides
an outcome of the code under test.

``fail_fast=True`` reproduces the PO's real wiring (``runner/wiring.py``): the scoring REST client never sleeps, a request
that does not fit the rate budget raises ``HlBudgetError`` at once and the caller tries again on a later slice.
"""

from __future__ import annotations

import bisect
import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copytrade.hl.access import AccessMonitor
from copytrade.hl.budget import RateBudget
from copytrade.hl.errors import HlBudgetError
from copytrade.hl.models import Candle
from copytrade.hl.rest import HlRestClient, HttpResponse
from copytrade.hl.schema import SchemaFailureMonitor
from copytrade.hl.ws import HlWsFeed
from copytrade.core.money import Price, Qty
from copytrade.runner.sources import PacedInputs
from copytrade.selection.backfill import Backfiller
from copytrade.selection.manager import FollowManager
from tests.hl.support import (
    T0,
    Call,
    FakeClock,
    FakeConnector,
    FakeHttp,
    FakeSleeper,
    RecordingAlerts,
    RecordingLedger,
    RecordingSink,
    fixture,
    make_config,
    ok,
)
from tests.scoring.helpers import PAPER_COSTS, MemoryStore
from tests.selection.helpers import FakeLeaderboard, FakeShares, FakeStates, w
from tests.signals.helpers import make_rig as make_detector_rig

DAY = 86_400_000
PAGE = 2_000
HL_FILLS_LIMIT = 10_000  # Hyperliquid fact: userFillsByTime only makes the 10 000 most recent fills of a wallet retrievable
FIXTURES_R1 = Path(__file__).resolve().parent.parent / "fixtures" / "hl"
EXTRAS_FIXTURE = "userFillsByTime_extras.synthetic-pending-recording.json"  # SYNTHETIC-PENDING-RECORDING


def r1_fixture(name: str = EXTRAS_FIXTURE) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((FIXTURES_R1 / name).read_text(encoding="utf-8"))
    return data


def synth_fills(n: int, *, start_ms: int = T0 - 2 * DAY, step_ms: int = 50, tid0: int = 1) -> list[dict[str, Any]]:
    """``n`` wire-format fills (recorded field set), strictly increasing in time and tid."""
    base = r1_fixture()[0]
    out: list[dict[str, Any]] = []
    for i in range(n):
        row = dict(base)
        row["tid"] = tid0 + i
        row["oid"] = 10_000_000 + tid0 + i
        row["time"] = start_ms + i * step_ms
        row["hash"] = "0x" + f"{tid0 + i:064x}"
        out.append(row)
    return out


def spread_fills(n: int, *, start_ms: int = T0 - 20 * DAY, step_ms: int = 60_000, tid0: int = 1) -> list[dict[str, Any]]:
    """``n`` fills one a minute (``synth_fills`` with a step that makes a full 2 000-fill page span 1.4 days). R3's first-page
    exit drops a wallet whose FIRST page is full inside one day, so a test about a later rule (the 50-page cap, the
    10 000-fill truncation) needs fills spread like this. 20 000 of them end about 6 days before ``T0``."""
    return synth_fills(n, start_ms=start_ms, step_ms=step_ms, tid0=tid0)


def stuck_fills() -> list[dict[str, Any]]:
    """A wallet whose cursor cannot move: one fill two days ago (so the full first page spans more than a day and R3's
    first-page exit does not fire), then 2 500 fills in ONE millisecond. Page 1 = the old fill + 1 999 of the pile; page 2
    (from that millisecond) = the first 2 000 of the pile, no progress: 2 001 distinct fills in 2 pages."""
    return [*synth_fills(1, start_ms=T0 - 2 * DAY), *synth_fills(2_500, start_ms=T0 - 3_600_000, step_ms=0, tid0=2)]


class FakeHl:
    """The info endpoint. ``fills`` per wallet (wire format); ``rules`` may answer a ``(wallet, request type)`` first
    (return ``None`` to fall through to the normal answer); everything but fills is served from the F3 fixtures."""

    def __init__(self, *, fills_limit: int | None = None) -> None:
        """``fills_limit`` (use ``HL_FILLS_LIMIT``) switches on the real API's retention: only the ``fills_limit`` most
        recent fills of a wallet exist for ``userFillsByTime``; a request that starts earlier gets the OLDEST retrievable
        fills (earliest first, 2 000 a page), with nothing to tell it that older ones were cut off."""
        self.fills_limit = fills_limit
        self._store: dict[str, tuple[list[int], list[dict[str, Any]]]] = {}
        self.rules: dict[tuple[str, str], Callable[[Call], HttpResponse | None]] = {}

    def set_fills(self, wallet: str, rows: Sequence[dict[str, Any]]) -> None:
        ordered = sorted(rows, key=lambda r: (r["time"], r.get("tid", 0)))
        self._store[wallet] = ([r["time"] for r in ordered], ordered)

    def handle(self, call: Call) -> HttpResponse:
        rtype, user = call.body["type"], call.body.get("user")
        rule = self.rules.get((str(user), rtype))
        if rule is not None:
            answer = rule(call)
            if answer is not None:
                return answer
        if rtype == "userFillsByTime":
            times, rows = self._store.get(str(user), ([], []))
            if self.fills_limit is not None:
                times, rows = times[-self.fills_limit:], rows[-self.fills_limit:]
            lo = bisect.bisect_left(times, call.body["startTime"])
            hi = len(times) if call.body.get("endTime") is None else bisect.bisect_right(times, call.body["endTime"])
            return ok(rows[lo:hi][:PAGE])
        return ok(fixture(rtype))


class FailFastSleeper:
    """The real runner's scoring sleeper: never sleeps, refuses at once."""

    def __init__(self) -> None:
        self.refusals = 0

    def sleep(self, seconds: float) -> None:
        self.refusals += 1
        raise HlBudgetError(f"the rate budget has no room for this request now (would wait {seconds:.1f} s)")


class FakeCandles:
    """CandleSource (F4 port): three 1h bars in the requested range; ``error`` makes it raise (a disk or store failure)."""

    def __init__(self) -> None:
        self.error: Exception | None = None

    def fetch(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Sequence[Candle]:
        if self.error is not None:
            raise self.error
        hour = 3_600_000
        first = start_ms - start_ms % hour
        return [
            Candle(first + k * hour, first + (k + 1) * hour - 1, coin, interval, Price("100"), Price("101"),
                   Price("99"), Price("100.5"), Qty("10"), 5)
            for k in range(3)
        ]


@dataclass
class World:
    cfg: Any
    clock: FakeClock
    sleeper: Any
    http: FakeHttp
    hl: FakeHl
    client: HlRestClient
    alerts: RecordingAlerts
    candles: FakeCandles
    backfiller: Backfiller
    schema_monitor: SchemaFailureMonitor = field(repr=False, default=None)  # type: ignore[assignment]

    def fills_calls(self, wallet: str | None = None) -> list[Call]:
        return [
            c for c in self.http.calls
            if c.body["type"] == "userFillsByTime" and (wallet is None or c.body["user"] == wallet)
        ]

    def tick(self, seconds: int = 10) -> None:
        self.clock.advance(seconds * 1000)


def make_world(*, fail_fast: bool = False, fills_limit: int | None = None, **overrides: Any) -> World:
    cfg = make_config(**overrides)
    clock = FakeClock()
    sleeper: Any = FailFastSleeper() if fail_fast else FakeSleeper(clock)
    hl = FakeHl(fills_limit=fills_limit)
    http = FakeHttp(clock, hl.handle)
    alerts, ledger = RecordingAlerts(), RecordingLedger()
    budget = RateBudget(
        budget_per_min=cfg["hl.rest_weight_budget_per_min"], scoring_share=cfg["hl.scoring_weight_share"], clock=clock
    )
    access = AccessMonitor(config=cfg, clock=clock, alerts=alerts, ledger=ledger)
    schema_monitor = SchemaFailureMonitor(clock=clock, alerts=alerts)
    client = HlRestClient(
        config=cfg, clock=clock, transport=http, sleeper=sleeper, rng=random.Random(7), budget=budget, access=access,
        schema_monitor=schema_monitor,
    )
    candles = FakeCandles()
    backfiller = Backfiller(config=cfg, clock=clock, rest=client, candles=candles)
    return World(cfg, clock, sleeper, http, hl, client, alerts, candles, backfiller, schema_monitor)


# --- leaderboard ---------------------------------------------------------------------------------------------------


def _passing_windows() -> list[list[Any]]:
    """windowPerformances that pass stage 1 (P1, P4-P8) for any account value from 10 000 to 200 000 USD and do not depend on
    it: the same figures on every row, so the K1 order of such rows is the lower-case address (R3)."""
    cells = {
        "day": ("100", "1000"),
        "week": ("1000", "200000"),
        "month": ("2000", "400000"),  # 50 bps a traded dollar
        "allTime": ("10000", "2000000"),
    }
    return [[name, {"pnl": pnl, "roi": "0.1", "vlm": vlm}] for name, (pnl, vlm) in cells.items()]


def board_body(
    rows: Sequence[tuple[str, str | None]],
    *,
    total: int = 1000,
    filler_value: str = "50000.0",
    filler_passes: bool = True,
) -> bytes:
    """A leaderboard JSON of the recorded shape: ``rows`` first (address, accountValue or ``None`` for a row without the
    field), then rich filler wallets up to ``total`` rows (``w(1_000_000 + i)``).

    Every row carries figures that pass the stage-1 rules P4-P8 (R3), except that ``filler_passes=False`` makes the
    FILLER fail P4 (template windows, month volume below 2 x account value), e.g. so a test about rows that cannot be
    ranked is not drowned by ``candidates_k`` ranked filler rows."""
    template = json.loads((Path(__file__).resolve().parent.parent / "fixtures/exchange/hl/leaderboard.json").read_text())
    base = template["leaderboardRows"][0]
    out: list[dict[str, Any]] = []
    for address, value in rows:
        row = {**base, "ethAddress": address, "windowPerformances": _passing_windows()}
        if value is None:
            row.pop("accountValue", None)
        else:
            row["accountValue"] = value
        out.append(row)
    i = 0
    while len(out) < total:
        filler = {**base, "ethAddress": w(1_000_000 + i), "accountValue": filler_value}
        if filler_passes:
            filler["windowPerformances"] = _passing_windows()
        out.append(filler)
        i += 1
    return json.dumps({"leaderboardRows": out}).encode()


@dataclass
class ManagerWorld:
    world: World
    manager: FollowManager
    inputs: PacedInputs
    board: FakeLeaderboard
    ledger: Any
    alerts: RecordingAlerts

    def records(self, kind: str) -> list[dict[str, Any]]:
        return [dict(r.payload) for r in self.ledger.records() if r.kind == kind]

    def work_until_complete(self, *, max_ticks: int = 400, tick_s: int = 10) -> int:
        """What the runner does: one paced slice every ``tick_s`` seconds. Returns the ticks used."""
        for n in range(1, max_ticks + 1):
            self.inputs.work()
            if self.inputs.complete:
                return n
            self.world.tick(tick_s)
        raise AssertionError(f"the backfill did not complete in {max_ticks} slices")


def make_manager_world(directory: Path, *, fail_fast: bool = True, **overrides: Any) -> ManagerWorld:
    """Real manager over real ``PacedInputs`` + ``Backfiller`` + REST client (the PO's wiring) and the fake HL."""
    world = make_world(fail_fast=fail_fast, **overrides)
    detector = make_detector_rig(directory, follow=(), clock=world.clock, **overrides)
    connector = FakeConnector(world.clock, auto_pong=True)
    feed = HlWsFeed(
        config=world.cfg, clock=world.clock, connector=connector, rest=world.client, rng=random.Random(3),
        sink=RecordingSink(), ledger=RecordingLedger(), alerts=world.alerts, schema_monitor=world.schema_monitor,
    )
    board = FakeLeaderboard(board_body([]))
    inputs = PacedInputs(world.backfiller)
    alerts = RecordingAlerts()
    manager = FollowManager(
        config=world.cfg, clock=world.clock, ledger=detector.ledger, alerts=alerts, feed=feed,
        registry=detector.detector, states=FakeStates(), shares=FakeShares(), leaderboard=board, inputs=inputs,
        scores=MemoryStore(), costs=PAPER_COSTS,
    )
    return ManagerWorld(world, manager, inputs, board, detector.ledger, alerts)
