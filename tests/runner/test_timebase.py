"""R0.AC4: the F11 time-base contract in the loop. ``advance_to(exchange_now)`` on EVERY iteration, before marks,
delistings and submit; not while unsynced; a jump guard; a stall heartbeat; zero bad_timestamp alerts in normal running.

``TimeBase`` unit tests use the ExchangeTime/Clock ports (true boundaries); the loop tests run the real runner."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.runner.timebase import ALERT_CLOCK_JUMP, ALERT_LOOP_STALLED, SKIP_CLOCK_JUMP, SKIP_CLOCK_UNSYNCED, TimeBase
from tests.hl.support import FakeClock
from tests.hl.ws_server import wait_for
from tests.risk.helpers import FakeExchangeTime
from tests.runner.fake_hl import fill_json
from tests.runner.world import LEADER, T0, World

UNCERT = 100  # clock.max_offset_uncertainty_ms in the fixture config


def make(offset: int = 0) -> tuple[TimeBase, FakeClock, FakeExchangeTime]:
    clock, xt = FakeClock(T0), FakeExchangeTime(T0 + offset)
    return TimeBase(exchange_time=xt, clock=clock, max_offset_uncertainty_ms=UNCERT), clock, xt


def move(clock: FakeClock, xt: FakeExchangeTime, local_ms: int, exchange_ms: int) -> None:
    clock.advance(local_ms)
    xt.now += exchange_ms


# ---------------------------------------------------------------------------------------------- TimeBase


def test_R0_AC4_the_first_target_is_the_exchange_time_as_it_is() -> None:
    tb, _, xt = make(offset=7_000)
    assert tb.next_target_ms() == (xt.now, None)


def test_R0_AC4_unsynced_returns_no_target_and_the_unsynced_reason() -> None:
    tb, _, xt = make()
    xt.unsynced = True
    assert tb.next_target_ms() == (None, SKIP_CLOCK_UNSYNCED)


def test_R0_AC4_a_normal_step_is_accepted_and_each_target_follows_the_exchange_clock() -> None:
    tb, clock, xt = make()
    tb.next_target_ms()
    for _ in range(5):
        move(clock, xt, 1_000, 1_000)
        assert tb.next_target_ms() == (xt.now, None)


@pytest.mark.parametrize(("extra", "accepted"), [(UNCERT * 2 - 1, True), (UNCERT * 2, True), (UNCERT * 2 + 1, False)])
def test_R0_AC4_jump_guard_boundary_at_two_offset_uncertainties(extra: int, accepted: bool) -> None:
    tb, clock, xt = make()
    first, _ = tb.next_target_ms()
    move(clock, xt, 1_000, 1_000 + extra)
    target, reason = tb.next_target_ms()
    if accepted:
        assert (target, reason) == (xt.now, None)
    else:
        assert (target, reason) == (None, SKIP_CLOCK_JUMP)
    assert first == T0


def test_R0_AC4_one_plus_hour_sample_is_not_accepted_and_the_next_normal_sample_is() -> None:
    tb, clock, xt = make()
    tb.next_target_ms()
    move(clock, xt, 1_000, 3_600_000)  # RISK-29: one +1 h sample
    assert tb.next_target_ms() == (None, SKIP_CLOCK_JUMP)
    xt.now -= 3_600_000  # the offset estimate recovers
    move(clock, xt, 1_000, 1_000)
    assert tb.next_target_ms() == (xt.now, None)


def test_R0_AC4_a_sustained_jump_is_accepted_once_local_time_has_caught_up_with_it() -> None:
    tb, clock, xt = make()
    tb.next_target_ms()
    move(clock, xt, 1_000, 3_600_000)
    assert tb.next_target_ms()[0] is None
    move(clock, xt, 3_600_000, 0)  # an hour of local time later the exchange clock is where it said it was
    target, reason = tb.next_target_ms()
    assert reason is None and target == xt.now


def test_R0_AC4_a_target_behind_the_last_one_is_never_returned() -> None:
    tb, clock, xt = make()
    tb.next_target_ms()
    move(clock, xt, 1_000, 1_000)
    high, _ = tb.next_target_ms()
    move(clock, xt, 1_000, -5_000)  # the offset estimate moved backwards
    target, reason = tb.next_target_ms()
    assert reason is None and target is not None and high is not None and target >= high


@given(steps=st.lists(st.tuples(st.integers(0, 5_000), st.integers(-10_000, 4_000_000)), min_size=1, max_size=40))
def test_R0_AC4_property_targets_never_decrease_and_never_outrun_local_time_by_more_than_the_guard(
    steps: list[tuple[int, int]],
) -> None:
    tb, clock, xt = make()
    last_target, last_local = tb.next_target_ms()[0], clock.now
    assert last_target is not None
    for dlocal, dex in steps:
        move(clock, xt, dlocal, dex)
        target, reason = tb.next_target_ms()
        if target is None:
            assert reason == SKIP_CLOCK_JUMP
            continue
        assert target >= last_target
        assert target - last_target <= (clock.now - last_local) + 2 * UNCERT or target == last_target
        last_target, last_local = target, clock.now


# ---------------------------------------------------------------------------------------------- the loop


def test_R0_AC4_every_iteration_advances_broker_time_to_the_exchange_clock(new_world: Any) -> None:
    world: World = new_world()
    world.offset_ms = 5_000
    runner, _ = world.start()
    seen = []
    for _ in range(6):
        report = world.step(runner, 1)
        assert report.skipped is None and report.advanced_to_ms == world.exchange_ms()
        assert runner.last_advanced_ms == report.advanced_to_ms
        seen.append(report.advanced_to_ms)
    assert seen == sorted(set(seen)) and len(seen) == 6  # strictly increasing: an advance on EVERY iteration


def test_R0_AC4_nothing_is_advanced_while_the_clock_is_unsynced_and_the_alert_reaches_telegram(new_world: Any) -> None:
    world: World = new_world()
    world.hl.fail_types.add("l2Book")  # the exchange clock cannot be estimated
    runner, _ = world.start()
    report = world.step(runner, 3)
    assert report.advanced_to_ms is None and report.skipped == SKIP_CLOCK_UNSYNCED
    assert runner.last_advanced_ms is None
    world.wait_text("clock_unsynced")
    world.hl.fail_types.clear()
    report = world.step(runner, 1, ms=601_000)  # clock.offset_interval_s = 600: the next tick re-estimates
    assert report.skipped is None and runner.last_advanced_ms == report.advanced_to_ms


def test_R0_AC4_a_leader_open_while_unsynced_opens_nothing(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    world.hl.fail_types.add("l2Book")
    runner, _ = world.start()
    world.subscribe_ready(runner)
    world.hl.push_user_fills(
        LEADER,
        [fill_json(1, coin="SOL", side="B", sz="5.0", px="100.0", direction="Open Long", time_ms=world.exchange_ms() - 200)],
    )
    world.step(runner, 20, ms=200)
    assert runner.broker.positions() == () and runner.broker.pending_entries() == ()
    assert not [r for r in world.records("paper_order")]


def test_R0_AC4_a_one_hour_clock_jump_is_not_followed_alerts_once_and_is_not_advanced(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    world.step(runner, 3)
    before = runner.last_advanced_ms
    world.offset_ms += 3_600_000  # the next estimate is one hour ahead (RISK-29)
    report = world.step(runner, 1, ms=601_000)
    assert report.skipped == SKIP_CLOCK_JUMP and report.advanced_to_ms is None
    assert runner.last_advanced_ms == before
    world.wait_text(ALERT_CLOCK_JUMP)
    world.step(runner, 3)
    assert sum(ALERT_CLOCK_JUMP in t for t in world.tg.sent()) == 1  # alert once per episode


def test_R0_AC4_a_triggered_stop_is_booked_at_this_iterations_exchange_time_so_advance_came_before_marks(
    new_world: Any,
) -> None:
    world: World = new_world()
    world.seed_follow()
    world.offset_ms = 2_500
    runner, _ = world.start()
    world.leader_open(runner)
    assert runner.broker.stops(), "the share has a stop"
    trigger_px = min(s.trigger_px for s in runner.broker.stops() if s.kind == "sl")
    world.hl.mids["SOL"] = str(trigger_px - 1)
    n_before = len(world.records("paper_stop_trigger"))
    for _ in range(60):
        report = world.step(runner, 1, ms=200)
        triggers = world.records("paper_stop_trigger")
        if len(triggers) > n_before:
            assert triggers[-1].payload["time_ms"] == report.advanced_to_ms
            return
    pytest.fail("the stop never triggered")


@pytest.mark.parametrize("offset", [-10_000, 0, 10_000])
def test_R0_AC4_zero_bad_timestamp_alerts_and_entries_work_whatever_the_clock_offset(new_world: Any, offset: int) -> None:
    world: World = new_world()
    world.seed_follow()
    world.offset_ms = offset
    runner, _ = world.start()
    world.leader_open(runner)
    world.step(runner, 30)
    assert "bad_timestamp" not in world.alert_kinds_sent()
    assert not [r for r in world.records("risk_decision") if r.payload["reason"] in ("equity_mark_stale", "bad_decision_time", "stale_decision")]


def test_R0_AC4_a_stalled_loop_raises_a_telegram_heartbeat_alert_after_three_ledger_heartbeats(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    world.step(runner, 2)
    threshold_ms = 3 * 10 * 1000  # 3 x ledger.heartbeat_interval_s
    world.clock.advance(threshold_ms)  # exactly the threshold: not yet a stall
    stalled = threading.Event()
    assert not stalled.wait(0.3)
    assert not any(ALERT_LOOP_STALLED in t for t in world.tg.sent())
    world.clock.advance(1)
    wait_for(lambda: any(ALERT_LOOP_STALLED in t for t in world.tg.sent()), what="the stall heartbeat alert")
    world.step(runner, 1)  # the loop is alive again
    world.clock.advance(threshold_ms + 1)
    wait_for(lambda: sum(ALERT_LOOP_STALLED in t for t in world.tg.sent()) == 2, what="a second episode alert")
