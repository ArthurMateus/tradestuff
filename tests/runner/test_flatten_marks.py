"""R0 fix round 1: /flatten is UNFINISHED while positions or pending exits remain (not only in_flight/still_open), it is
re-run, it alerts ``flatten_incomplete`` at the limit and then every 300 s, a raise in ``manager.flatten`` still leaves a
re-run scheduled, it works with the clock in doubt; and stale or unknown marks with positions open raise ``marks_stalled``
(RISK-57). Real runner/gate/broker/manager/bot; the only fault seam is ``manager.flatten`` raising (named below)."""

from __future__ import annotations

import time
from typing import Any

from copytrade.runner.flatten import FLATTEN_RERUN_INTERVAL_S, FLATTEN_RERUN_MAX
from tests.hl.ws_server import wait_for
from tests.runner.scenarios import count, enter_jump, enter_unsynced, flatten_cmd, opened_position

INCOMPLETE = "flatten_incomplete"
STALE_STEP_MS = 40_000  # feed.stale_after_s = 30


def test_R0_AC4_flatten_in_doubt_closes_positions(new_world: Any) -> None:
    for how in (enter_unsynced, enter_jump):
        world, runner = opened_position(new_world)
        try:
            how(world, runner)
            flatten_cmd(world, runner)
            world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=80, ms=200)
            assert not runner.broker.pending_exits()
        finally:
            runner.stop()


def test_R0_AC4_flatten_unfinished_while_positions_or_pending_exits_remain(new_world: Any) -> None:
    world, runner = opened_position(new_world)
    flatten_cmd(world, runner)
    world.step(runner, 4, ms=FLATTEN_RERUN_INTERVAL_S * 1000, pump=False)  # no fresh books: the exit cannot fill
    assert runner.broker.position("SOL") is not None  # still open: the old supervisor called this finished
    runs = len(runner.flatten_runs)
    assert runs >= 3  # the loop kept re-running it every interval (the bot's call + at least two re-runs)
    world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=80, ms=1_000)
    world.step(runner, 2, ms=FLATTEN_RERUN_INTERVAL_S * 1000)
    done = len(runner.flatten_runs)
    world.step(runner, 4, ms=FLATTEN_RERUN_INTERVAL_S * 1000)
    assert len(runner.flatten_runs) == done  # done only when everything is empty; then no more runs


def test_R0_AC4_flatten_incomplete_alert_repeats(new_world: Any) -> None:
    world, runner = opened_position(new_world)
    flatten_cmd(world, runner)
    world.step(runner, FLATTEN_RERUN_MAX + 2, ms=FLATTEN_RERUN_INTERVAL_S * 1000, pump=False)
    world.wait_text(INCOMPLETE)
    assert count(world, INCOMPLETE) == 1  # at the existing limit, once
    world.step(runner, 29, ms=10_000, pump=False)  # < 300 s later
    assert count(world, INCOMPLETE) == 1
    world.step(runner, 2, ms=10_000, pump=False)  # >= 300 s after the first one
    assert count(world, INCOMPLETE) == 2
    world.step(runner, 30, ms=10_000, pump=False)
    world.step(runner, 2, ms=10_000, pump=False)
    assert count(world, INCOMPLETE) == 3  # and every 300 s while unfinished
    world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=40, ms=1_000)  # books are back
    n = count(world, INCOMPLETE)
    world.step(runner, 40, ms=10_000)
    assert count(world, INCOMPLETE) == n  # finished: no more alerts


def test_R0_AC4_flatten_raises_still_reruns(new_world: Any, monkeypatch: Any) -> None:
    world, runner = opened_position(new_world)
    real = runner.manager.flatten
    failures = [2]

    def flaky(*, run_id: str) -> Any:  # fault seam: the manager's flatten raises twice, then works
        if failures[0] > 0:
            failures[0] -= 1
            raise RuntimeError("injected flatten failure")
        return real(run_id=run_id)

    monkeypatch.setattr(runner.manager, "flatten", flaky)
    flatten_cmd(world, runner)
    for _ in range(40):
        if runner.broker.position("SOL") is None:
            break
        world.step(runner, 1, ms=1_000)
    assert runner.broker.position("SOL") is None
    assert failures[0] == 0  # the loop survived both raises and the supervisor re-ran until it worked


def drain_market(world: Any, runner: Any) -> None:
    for conn in world.hl.connections():
        while not conn._commands.empty():
            time.sleep(0.005)
    time.sleep(0.02)
    runner.hub.poll()


def test_R0_AC13_marks_stalled_alert_after_5_and_repeats(new_world: Any) -> None:
    world, runner = opened_position(new_world)
    drain_market(world, runner)
    world.step(runner, 4, ms=STALE_STEP_MS, pump=False)  # 4 iterations with a position open and stale mids
    assert count(world, "marks_stalled") == 0
    world.step(runner, 1, ms=STALE_STEP_MS, pump=False)
    world.wait_text("marks_stalled")
    assert count(world, "marks_stalled") == 1  # at the 5th
    world.step(runner, 7, ms=STALE_STEP_MS, pump=False)  # 280 s later
    assert count(world, "marks_stalled") == 1
    world.step(runner, 1, ms=STALE_STEP_MS, pump=False)  # 320 s later
    wait_for(lambda: count(world, "marks_stalled") >= 2, what="the 2nd marks_stalled alert")
    assert count(world, "marks_stalled") == 2
    world.pump_market()
    drain_market(world, runner)
    world.step(runner, 1, ms=1_000, pump=False)  # a good mark resets the counter and the throttle
    world.step(runner, 4, ms=STALE_STEP_MS, pump=False)
    assert count(world, "marks_stalled") == 2
    world.step(runner, 1, ms=STALE_STEP_MS, pump=False)
    wait_for(lambda: count(world, "marks_stalled") >= 3, what="the 3rd marks_stalled alert")
    assert count(world, "marks_stalled") == 3  # a new episode alerts at its 5th iteration, not 300 s after the last one


def test_R0_AC13_no_marks_stalled_alert_without_positions(new_world: Any) -> None:
    world = new_world()
    runner, _ = world.start()
    world.step(runner, 10, ms=STALE_STEP_MS, pump=False)
    assert count(world, "marks_stalled") == 0
