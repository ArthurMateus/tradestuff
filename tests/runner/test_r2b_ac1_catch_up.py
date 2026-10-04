"""R2b.AC1 (RISK-73, blocking): after a restart the catch-up of broker time must never run AHEAD of the exchange.

Broker time only moves forward and exits fill only from books stamped at or after the attempt time, which ``_probe_exit``
keeps within ``max_book_age`` (5 s) of broker time: once broker time leads the exchange by more than about 5 s no exit ever
fills (stop-loss, flatten, leader close) and the share runs to liquidation. The catch-up after a restart (clock not yet
trusted) therefore takes ONLY the newest hub book time, ignores a book time ahead of projection + downtime that no second
book confirms, never takes the raw clock estimate (a retried estimate is (after - before) / 2 ahead; a wall-clock step moves
it: Amendment 13) and the offset estimate times only its final attempt.

Observable (mechanism-agnostic): broker time vs the true exchange time, and the stop fills within 5 s of loop time.
Reproduces the reviewer's probe (first estimate 12 s / 30 s through retries, later ones 300 ms: too uncertain, never synced).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from tests.runner.scenarios import opened_position, set_mid_below_stop
from tests.runner.world import World

FILL_WITHIN_STEPS = 10  # x 500 ms = 5 s of loop time
AHEAD_LIMIT_MS = 1_500


def _restart_with_uncertain_clock(new_world: Any, *, first_estimate_ms: int | None) -> tuple[World, Any]:
    """A killed run with an open copy, 120 s of downtime, a restart whose clock estimates are all too uncertain (300 ms
    round trip) except that the very first one may take ``first_estimate_ms`` (retries and back-off)."""
    world, run1 = opened_position(new_world)
    world.hard_kill(run1)
    world.clock.advance(120_000)
    first = {"pending": first_estimate_ms is not None}

    def hook() -> None:
        if first["pending"]:
            first["pending"] = False
            world.clock.advance(first_estimate_ms or 0)
        else:
            world.clock.advance(300)

    world.hl.hook = hook
    run2, _ = world.start()
    assert run2.sync.refusal_reason(ActionKind.OPEN) is not None, "the scenario needs a clock that is not trusted"
    return world, run2


def _stop_fills_within_5_s(world: World, runner: Any, what: str) -> None:
    set_mid_below_stop(world, runner)
    for _ in range(FILL_WITHIN_STEPS):
        world.step(runner, 1, ms=500)
        if runner.broker.position("SOL") is None:
            break
    ahead = (runner.last_advanced_ms or 0) - world.exchange_ms()
    assert runner.broker.position("SOL") is None, (
        f"{what}: the stop never filled in 5 s; broker time ahead by {ahead} ms"
    )
    assert ahead <= AHEAD_LIMIT_MS, f"{what}: broker time is {ahead} ms ahead of the exchange"


@pytest.mark.parametrize("slow_ms", [12_000, 30_000])
def test_R2b_AC1_a_slow_first_estimate_does_not_push_broker_time_ahead_and_the_stop_fills(
    new_world: Any, slow_ms: int
) -> None:
    world, runner = _restart_with_uncertain_clock(new_world, first_estimate_ms=slow_ms)
    _stop_fills_within_5_s(world, runner, f"first estimate took {slow_ms} ms")


def test_R2b_AC1_a_bogus_future_book_time_does_not_push_broker_time_ahead(new_world: Any) -> None:
    world, runner = _restart_with_uncertain_clock(new_world, first_estimate_ms=None)
    runner_book_future = world.exchange_ms() + 60_000
    assert world.hl.push_l2("SOL", runner_book_future) >= 1, "the market feed is not subscribed"
    time.sleep(0.05)  # real sockets: let the one bogus frame reach the hub before the first iteration
    _stop_fills_within_5_s(world, runner, "one book stamped 60 s in the future")


def test_R2b_AC1_a_wall_clock_step_forward_does_not_move_broker_time_after_a_restart(new_world: Any) -> None:
    world, runner = _restart_with_uncertain_clock(new_world, first_estimate_ms=None)
    world.step(runner, 2, ms=500)
    world.step_wall(
        60_000
    )  # Windows steps the local wall clock forward one minute: the raw clock estimate moves with it
    world.step(runner, 1, ms=500)
    _stop_fills_within_5_s(world, runner, "after a wall-clock step forward of 60 s")


def test_R2b_AC1_the_offset_estimate_times_only_its_final_attempt(new_world: Any) -> None:
    """The first two l2Book answers are HTTP 500 and are retried with back-off (the fake sleeper advances the clock by
    seconds); the third succeeds after a 100 ms round trip. The estimate is then as exact as a 100 ms round trip allows
    (uncertainty about 50 ms, trusted), not (retry time) / 2 off with an uncertainty of seconds."""
    world: World = new_world()
    calls = {"n": 0}

    def hook() -> None:
        calls["n"] += 1
        if calls["n"] <= 2:
            world.hl.fail_types.add("l2Book")
        else:
            world.hl.fail_types.discard("l2Book")
        world.clock.advance(100)

    world.hl.hook = hook
    runner, _ = world.start()
    assert calls["n"] >= 3, "the scenario needs the first estimate to be retried"
    error = (
        abs(runner.sync.exchange_now().ms - world.exchange_ms())
        if runner.sync.refusal_reason(ActionKind.OPEN) is None
        else None
    )
    assert error is not None, (
        "a final attempt of 100 ms round trip must give a trusted estimate (the retries do not count)"
    )
    assert error <= 150, f"the estimate is {error} ms off: the retried attempts were counted in the round trip"
