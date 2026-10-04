"""Support for the R5 tests (docs/sdlc/copytrade-v1/05-test-plan-R5.md): a wallet's backfill under the trading thread's
REST time limit.

Real components: the backfiller, F3's REST client and rate budget, ``RestCandles`` on the scoring client, the real
fail-fast scoring sleeper of ``runner.wiring`` and the real ``TradingSleeper`` as the client's ``call_limit`` (exactly the
PO's wiring: ``rest_scoring`` is built with ``call_limit=trading_sleeper``). The only doubles are the true boundaries: the
HTTP transport (``LatencyHttp``: every request takes a scripted time, a request slower than the timeout it was given
times out after that timeout, like the real socket), the clock and the monotonic time (one fake time, advanced by the
requests), and the fake Hyperliquid answers (``r1_world.FakeHl`` plus a candle server).

``LatencyHttp`` keeps the outcome of every request, so a test can count per request type what the server received and
what it answered.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from copytrade.hl.access import AccessMonitor
from copytrade.hl.budget import RateBudget
from copytrade.hl.rest import HlRestClient, HttpResponse
from copytrade.hl.schema import SchemaFailureMonitor
from copytrade.runner.failfast import TradingSleeper
from copytrade.runner.sources import RestCandles
from copytrade.runner.wiring import _FailFastSleeper
from copytrade.selection.backfill import Backfiller
from tests.hl.support import (
    T0,
    Call,
    FakeClock,
    FakeHttp,
    FakeSleeper,
    RecordingAlerts,
    RecordingLedger,
    make_config,
    ok,
)
from tests.selection.r1_world import DAY, FakeCandles, FakeHl, World
from tests.selection.r3_world import Tids, good_trips

HOUR = 3_600_000
WINDOW_DAYS = 180
LATENCY = Callable[[Call], float]


class Mono:
    """The monotonic clock of the ``TradingSleeper``: one fake time with the fake wall clock (see ``LatencyHttp``)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class LatencyHttp(FakeHttp):
    """HttpTransport double with a scripted response time. A request whose time exceeds the ``timeout_s`` it was given
    takes ``timeout_s`` and raises ``TimeoutError``; otherwise it takes its time and is answered by the handler."""

    def __init__(self, clock: FakeClock, handler: Callable[[Call], HttpResponse], mono: Mono, latency: LATENCY) -> None:
        super().__init__(clock, handler)
        self.mono = mono
        self.latency = latency
        self.outcomes: list[tuple[Call, str]] = []  # (request, "ok" | "timeout" | "error" | "status <code>")

    def pass_time(self, seconds: float) -> None:
        self.mono.now += seconds
        self.clock.advance(round(seconds * 1000))

    def post(self, url: str, body: str, *, timeout_s: float) -> HttpResponse:
        call = Call(self.clock.now_ms(), url, json.loads(body), timeout_s)
        self.calls.append(call)
        took = self.latency(call)
        if took > timeout_s:
            self.pass_time(timeout_s)
            self.outcomes.append((call, "timeout"))
            raise TimeoutError("no answer in time")
        self.pass_time(took)
        try:
            response = self.handler(call)
        except BaseException:
            self.outcomes.append((call, "error"))
            raise
        self.outcomes.append((call, "ok" if response.status == 200 else f"status {response.status}"))
        return response

    def of(self, rtype: str, wallet: str | None = None, *, outcome: str | None = None) -> list[Call]:
        return [
            c
            for c, result in self.outcomes
            if c.body["type"] == rtype
            and (wallet is None or c.body.get("user") == wallet)
            and (outcome is None or result == outcome)
        ]

    def candle_windows(self, coin: str | None = None, *, outcome: str | None = None) -> list[tuple[str, int, int]]:
        """(coin, startTime, endTime) of every ``candleSnapshot`` request, in order."""
        return [
            (c.body["req"]["coin"], c.body["req"]["startTime"], c.body["req"]["endTime"])
            for c in self.of("candleSnapshot", outcome=outcome)
            if coin is None or c.body["req"]["coin"] == coin
        ]

    def count_ok(self) -> Counter[str]:
        return Counter(c.body["type"] for c, result in self.outcomes if result == "ok")


def bar(open_ms: int, coin: str) -> dict[str, Any]:
    """One 1h candle of the recorded wire shape; the figures are the same for every bar (a flat market)."""
    return {
        "t": open_ms, "T": open_ms + HOUR - 1, "s": coin, "i": "1h",
        "o": "100.0", "c": "100.5", "h": "101.0", "l": "99.0", "v": "10.0", "n": 10,
    }  # fmt: skip


def candle_rule(clock: FakeClock) -> Callable[[Call], Any]:
    """The exchange's ``candleSnapshot``: every 1h bar whose OPEN lies in ``[startTime, endTime]`` and is not in the
    future (the bar of the current hour is returned part-formed, as the exchange does)."""

    def rule(call: Call) -> Any:
        req = call.body["req"]
        start, end = int(req["startTime"]), int(req["endTime"])
        first = -(-start // HOUR) * HOUR
        last = min(end, clock.now_ms())
        return ok([bar(t, req["coin"]) for t in range(first, last + 1, HOUR)])

    return rule


@dataclass
class R5World:
    world: World
    limit: TradingSleeper
    mono: Mono
    http: LatencyHttp

    @property
    def backfiller(self) -> Backfiller:
        return self.world.backfiller

    @property
    def clock(self) -> FakeClock:
        return self.world.clock

    def serve_wallet(self, wallet: str, coins: Sequence[str], *, trips: int = 20) -> None:
        """A wallet that traded each of ``coins`` in ``trips`` closed round trips over the last 100 days (one fills page)."""
        tids = Tids()
        rows: list[dict[str, Any]] = []
        for coin in coins:
            rows += good_trips(T0, trips, tids=tids, coin=coin)
        self.world.hl.set_fills(wallet, rows)

    def iteration(self, *, spent_s: float = 0.0) -> float:
        """One loop iteration of the runner: a fresh REST time budget, optionally ``spent_s`` of it already used by other
        work (a request that took that long), then one backfill step. Returns the REST time of the whole iteration."""
        started = self.mono.now
        self.limit.new_iteration()
        if spent_s:
            self.limit.timeout_s(10.0)
            self.mono.now += spent_s
            self.limit.finished()
        self.backfiller.step()
        return self.mono.now - started

    def run(
        self, wallets: Sequence[str], *, max_steps: int, tick_s: int = 10, spent_s: float = 0.0
    ) -> tuple[int, list[float]]:
        """Iterations (and fake ``tick_s`` seconds between them, the runner's work interval) until every wallet has its
        inputs. Returns the iterations used and the REST time of each; raises if ``max_steps`` was not enough."""
        times: list[float] = []
        for n in range(1, max_steps + 1):
            times.append(self.iteration(spent_s=spent_s))
            if all(self.backfiller.inputs(wallet, T0) is not None for wallet in wallets):
                return n, times
            self.world.tick(tick_s)
        done = [wallet for wallet in wallets if self.backfiller.inputs(wallet, T0) is not None]
        raise AssertionError(f"{len(done)} of {len(wallets)} wallets complete after {max_steps} iterations")


def make_r5(*, latency: LATENCY | float = 0.0, **overrides: Any) -> R5World:
    """The PO's wiring with a scripted response time. ``hl.scoring_weight_share`` is the largest the config allows (0.8:
    a whole backfill weighs about 500, over the default 450 a minute) so the rate budget never masks the REST time
    limit under test."""
    cfg_over = {"hl__scoring_weight_share": 0.8, **overrides}
    cfg = make_config(**cfg_over)
    clock = FakeClock()
    mono = Mono()
    hl = FakeHl()
    hl.rules[("None", "candleSnapshot")] = candle_rule(clock)
    script: LATENCY = (lambda _call: float(latency)) if isinstance(latency, int | float) else latency
    http = LatencyHttp(clock, hl.handle, mono, script)
    limit = TradingSleeper(FakeSleeper(clock), monotonic=mono)
    limit.fail_fast()
    alerts, ledger = RecordingAlerts(), RecordingLedger()
    budget = RateBudget(
        budget_per_min=cfg["hl.rest_weight_budget_per_min"], scoring_share=cfg["hl.scoring_weight_share"], clock=clock
    )
    access = AccessMonitor(config=cfg, clock=clock, alerts=alerts, ledger=ledger)
    schema_monitor = SchemaFailureMonitor(clock=clock, alerts=alerts)
    client = HlRestClient(
        config=cfg, clock=clock, transport=http, sleeper=_FailFastSleeper(), rng=random.Random(7), budget=budget,
        access=access, schema_monitor=schema_monitor, call_limit=limit,
    )  # fmt: skip
    candles = RestCandles(client)
    backfiller = Backfiller(config=cfg, clock=clock, rest=client, candles=candles)
    world = World(cfg, clock, _FailFastSleeper(), http, hl, client, alerts, FakeCandles(), backfiller, schema_monitor)
    return R5World(world, limit, mono, http)


def expected_opens(now_ms: int, window_days: int = WINDOW_DAYS) -> list[int]:
    """The open times of every 1h bar of the scoring window (the bar of the current hour included) at ``now_ms``."""
    first = -(-(now_ms - window_days * DAY) // HOUR) * HOUR
    return list(range(first, now_ms - now_ms % HOUR + 1, HOUR))


__all__ = ["DAY", "HOUR", "WINDOW_DAYS", "R5World", "expected_opens", "make_r5"]
