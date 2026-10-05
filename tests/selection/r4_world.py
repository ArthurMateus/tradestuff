"""Support for the R4 tests (docs/sdlc/copytrade-v1/05-test-plan-R4.md): pseudo-coins ``#N`` and failing candles.

Real components (backfiller, REST client, rate budget, ``RestCandles``, manager, scorer); the only double is the
loopback fake Hyperliquid at the HTTP boundary. Unlike ``r1_world`` the backfiller's candles go over that fake HTTP
(``RestCandles`` on the scoring client, exactly the PO's wiring), so ``candleSnapshot`` requests are counted by coin.
"""

from __future__ import annotations

import re
from typing import Any

from copytrade.runner.sources import RestCandles
from tests.hl.support import Call, status
from tests.selection.r1_world import World
from tests.selection.r3_world import R3, Tids, fill, good_trips

HASH_COINS = ("#0", "#10", "#140", "#1020", "#7521")
WINDOW = re.compile(r"coin=(\S+) window=(\d+)\.\.(\d+) status=(\d+)")


class CandleServer:
    """Answers ``candleSnapshot`` like the exchange: HTTP 500 for every ``#N`` name, ``fail[coin]`` for coins a test
    breaks (a status code), the recorded fixture otherwise."""

    def __init__(self, fail: dict[str, int] | None = None) -> None:
        self.fail: dict[str, int] = dict(fail or {})

    def rule(self, call: Call) -> Any:
        coin = call.body["req"]["coin"]
        if coin.startswith("#"):
            return status(500)
        if coin in self.fail:
            return status(self.fail[coin])
        return None


def install(world: World, fail: dict[str, int] | None = None) -> CandleServer:
    """Route the backfiller's candles through the fake HL's HTTP endpoint (the production wiring)."""
    server = CandleServer(fail)
    world.hl.rules[("None", "candleSnapshot")] = server.rule
    world.candles.fetch = RestCandles(world.client).fetch  # type: ignore[method-assign]
    return server


def candle_calls(world: World, coin: str | None = None) -> list[Call]:
    return [
        c for c in world.http.calls
        if c.body["type"] == "candleSnapshot" and (coin is None or c.body["req"]["coin"] == coin)
    ]


def candle_coins(world: World) -> set[str]:
    return {c.body["req"]["coin"] for c in candle_calls(world)}


def trips_of(coins: list[str], t: int, *, n: int = 10, tids: Tids | None = None) -> list[dict[str, Any]]:
    """``n`` closed 2 000 USD taker trips of each coin, in the recorded wire shape."""
    tids = tids or Tids()
    rows: list[dict[str, Any]] = []
    for coin in coins:
        rows += good_trips(t, n, tids=tids, coin=coin)
    return rows


def hash_fill(tids: Tids, time_ms: int, usd: int, *, coin: str = "#140", crossed: bool = True) -> dict[str, Any]:
    return fill(coin, "B", format(usd / 2000, "f"), "2000", time_ms, "0.0", tids, crossed=crossed, direction="Buy")


def drive(world: World, max_steps: int = 60, tick_s: int = 10) -> int:
    """What the runner does: one backfill step, then ``tick_s`` seconds of fake time; until the pass is complete."""
    for n in range(1, max_steps + 1):
        world.backfiller.step()
        if world.backfiller.complete:
            return n
        world.tick(tick_s)
    raise AssertionError(f"the backfill did not complete in {max_steps} steps")


def r3_install(r3: R3, fail: dict[str, int] | None = None) -> CandleServer:
    return install(r3.world, fail)
