"""R0 fix round 1, Amendment 13: an exchange clock in doubt (unsynced, or a candidate outside the allowance of the
monotonic projection) refuses ENTRIES only. Stops, trailing, liquidations, delistings, exits, flatten and marks go on from
the projection; the alerts have a cadence. Real runner, gate, broker, ledger, manager and bot over the loopback fakes.
Every scenario is bounded in (fake) time. Contract names are in 05-test-plan-R0.md, 'Fix-round addendum'."""

from __future__ import annotations

from typing import Any

import pytest

from tests.runner.fake_hl import fill_json
from tests.runner.scenarios import PHRASE, count, enter_jump, enter_unsynced, opened_position, set_mid_below_stop
from tests.runner.world import LEADER, World

DOUBT = ["unsynced", "jump"]


def enter(world: World, runner: Any, how: str) -> None:
    (enter_unsynced if how == "unsynced" else enter_jump)(world, runner)


def test_R0_AC4_stop_triggers_while_clock_unsynced(new_world: Any) -> None:
    world, runner = opened_position(new_world)
    report = enter_unsynced(world, runner)
    assert report.advanced_to_ms is not None  # broker time is driven by the monotonic projection
    set_mid_below_stop(world, runner)
    world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=120, ms=200)
    assert world.records("paper_stop_trigger")


def test_R0_AC4_stop_triggers_during_jump_doubt(new_world: Any) -> None:
    world, runner = opened_position(new_world)
    report = enter_jump(world, runner)
    assert report.advanced_to_ms is not None and abs(report.advanced_to_ms - world.exchange_ms()) <= 5_000
    set_mid_below_stop(world, runner)
    world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=120, ms=200)  # 24 s < the 30 s resample
    assert world.records("paper_stop_trigger")


@pytest.mark.parametrize("how", DOUBT)
def test_R0_AC4_trailing_stop_moves_while_in_doubt(new_world: Any, how: str) -> None:
    world, runner = opened_position(new_world)
    enter(world, runner, how)
    world.hl.mids["SOL"] = "120"
    world.run_until(
        runner,
        lambda: any(s.trigger_px > 100 for s in runner.broker.stops() if s.kind == "sl"),
        max_steps=40,
        ms=500,
    )
    sl = [s.trigger_px for s in runner.broker.stops() if s.kind == "sl"]
    assert sl and min(sl) > 100  # the stop trailed the price up (was 98.6)



@pytest.mark.parametrize("how", DOUBT)
def test_R0_AC4_a_gap_far_below_the_stop_closes_the_position_while_in_doubt(new_world: Any, how: str) -> None:
    world, runner = opened_position(new_world)
    enter(world, runner, how)
    world.hl.mids["SOL"] = "1.0"  # beyond the stop and the liquidation price
    world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=60, ms=200)
    assert (
        world.records("paper_stop_trigger")
        or any(r.payload.get("exit_reason") == "liquidated" for r in world.records("fill"))
        or world.records("paper_liquidation")
        or world.records("liquidation")
    )


@pytest.mark.parametrize("how", DOUBT)
def test_R0_AC4_delisting_closes_the_position_while_in_doubt(new_world: Any, how: str) -> None:
    world, runner = opened_position(new_world)
    enter(world, runner, how)
    sol_idx = next(i for i, u in enumerate(world.hl.universe) if u["name"] == "SOL")
    world.hl.universe[sol_idx] = {**world.hl.universe[sol_idx], "isDelisted": True}
    assert world.hl.universe[sol_idx]["name"] == "SOL"
    world.step(runner, 1, ms=3_600_001)  # the hourly delisting check (paper.meta_refresh_min = 60)
    world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=60, ms=200)


@pytest.mark.parametrize("how", DOUBT)
def test_R0_AC4_entry_refused_while_in_doubt_exit_filled(new_world: Any, how: str) -> None:
    world, runner = opened_position(new_world)
    enter(world, runner, how)
    world.hl.leader_positions[LEADER.lower()] = [("SOL", "5.0", "100.0"), ("ETH", "1.0", "3400.0")]
    world.hl.push_user_fills(
        LEADER,
        [fill_json(7, coin="ETH", side="B", sz="1.0", px="3400.0", direction="Open Long", time_ms=world.exchange_ms() - 100)],
    )
    world.leader_close(coin="SOL", tid=8)  # the leader closes SOL: our exit must still fill
    world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=60, ms=200)
    world.step(runner, 10, ms=200)
    assert runner.broker.position("ETH") is None and not any(e.coin == "ETH" for e in runner.broker.pending_entries())
    assert not [r for r in world.records("paper_order") if r.payload.get("coin") == "ETH"]


def test_R0_AC4_clock_alerts_names_cadence_and_rebased(new_world: Any) -> None:
    world, runner = opened_position(new_world)
    enter_unsynced(world, runner)
    world.wait_text("clock_unsynced")
    n0 = count(world, PHRASE)
    world.step(runner, 29, ms=10_000)  # 290 s in doubt with a position open
    assert count(world, PHRASE) == n0
    world.step(runner, 2, ms=10_000)  # 310 s: one reminder, 300 s after entering the doubt
    assert count(world, PHRASE) == n0 + 1
    world.step(runner, 28, ms=10_000)  # 590 s
    assert count(world, PHRASE) == n0 + 1
    world.step(runner, 2, ms=10_000)  # 610 s
    assert count(world, PHRASE) == n0 + 2
    text = next(t for t in world.tg.sent() if PHRASE in t)
    assert "1 open position" in text  # names the number of open positions
    # the estimates come back: one rebase notice, and the alert state is reset
    world.hl.fail_types.clear()
    world.step(runner, 8, ms=10_000)
    assert world.tg.sent() and count(world, "clock_rebased") <= 1
    before = count(world, PHRASE)
    world.step(runner, 40, ms=10_000)
    assert count(world, PHRASE) == before  # no reminders once the clock is trusted again


def test_R0_AC4_a_persistent_offset_step_sends_clock_jump_once_then_clock_rebased_once_and_resets(new_world: Any) -> None:
    world, runner = opened_position(new_world)
    enter_jump(world, runner)
    world.wait_text("clock_jump")
    assert count(world, "clock_jump") == 1
    world.step(runner, 70, ms=10_000)  # two fresh consistent estimates (30 s and 60 s) rebase it
    assert count(world, "clock_rebased") == 1 and count(world, "clock_jump") == 1
    report = world.step(runner, 1, ms=1_000)
    assert report.skipped is None and abs((report.advanced_to_ms or 0) - world.exchange_ms()) <= 200
    enter_jump(world, runner, step_ms=-7_000)  # a new episode alerts again (the alert state was reset)
    wait = count(world, "clock_jump")
    assert wait == 2


def test_R0_AC4_no_realert_without_positions(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    world.step(runner, 3)
    assert runner.broker.positions() == ()
    enter_unsynced(world, runner)
    world.step(runner, 70, ms=10_000)
    assert count(world, PHRASE) == 0
    assert count(world, "clock_unsynced") <= 2  # the entry alert only (ClockSync's and/or the runner's)
