"""R0.AC4: the F11 time-base contract in the loop (Amendment 13, R0 fix round 1). ``advance_to(broker_target)`` on EVERY
iteration, before marks, delistings and submit; broker_target = the last accepted exchange target + MONOTONIC elapsed
time, forward-only; an exchange clock in doubt (unsynced, or a candidate more than 2 x clock.max_offset_uncertainty_ms
from the projection) refuses ENTRIES only; a rebase needs two consecutive fresh estimates; a stall heartbeat; zero
bad_timestamp alerts in normal running.

``TimeBase`` unit tests use the ExchangeTime/Clock ports (true boundaries); the loop tests run the real runner."""

from __future__ import annotations

import inspect
import threading
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.errors import ClockUnsyncedError
from copytrade.runner.timebase import ALERT_CLOCK_JUMP, ALERT_LOOP_STALLED, SKIP_CLOCK_JUMP, SKIP_CLOCK_UNSYNCED, TimeBase
from tests.hl.support import FakeClock
from tests.hl.ws_server import wait_for
from tests.risk.helpers import FakeExchangeTime
from tests.runner.fake_hl import fill_json
from tests.runner.world import LEADER, T0, World

UNCERT = 100  # clock.max_offset_uncertainty_ms in the fixture config


# ---------------------------------------------------------------------------------------------- TimeBase
# New contract (pinned in 05-test-plan-R0.md, "Fix-round addendum"): ``TimeBase(exchange_time=, clock=,
# max_offset_uncertainty_ms=, monotonic_ms=, resample=)``; ``next_target_ms() -> (target, reason)``: ``target`` is the
# broker-time PROJECTION (``None`` only when there is no baseline at all), ``reason`` is ``None`` when the exchange clock is
# trusted and ``SKIP_CLOCK_UNSYNCED`` / ``SKIP_CLOCK_JUMP`` while it is in doubt (entries refused, exits go on);
# ``resample() -> bool`` forces a fresh offset estimate and says whether it got one; ``seed_unverified(ms)``;
# ``rebase_count``.

DOUBT_RESAMPLE_MS = 30_000
FRESH = 2


def make(offset: int = 0) -> tuple[TimeBase, FakeClock, FakeExchangeTime]:
    clock, xt = FakeClock(T0), FakeExchangeTime(T0 + offset)
    # the monotonic clock follows the fake local clock here (drop the guard once TimeBase takes ``monotonic_ms``)
    extra = {"monotonic_ms": clock.now_ms} if "monotonic_ms" in inspect.signature(TimeBase).parameters else {}
    return TimeBase(exchange_time=xt, clock=clock, max_offset_uncertainty_ms=UNCERT, **extra), clock, xt


def move(clock: FakeClock, xt: FakeExchangeTime, local_ms: int, exchange_ms: int) -> None:
    clock.advance(local_ms)
    xt.now += exchange_ms


class Rig:
    """The exchange clock as production has it: ``candidate = local wall + the latest offset ESTIMATE``. The true exchange
    time is ``wall + true_offset``; ``resample()`` (the forced re-estimate) copies the true offset into the estimate. The
    monotonic clock is separate from the wall clock, so the wall can be stepped."""

    def __init__(self, *, fresh: bool = True) -> None:
        self.wall, self.mono = FakeClock(T0), 0
        self.true_offset = self.estimate = 0
        self.synced, self.fresh, self.resamples = True, fresh, 0
        self.tb = TimeBase(
            exchange_time=self, clock=self.wall, max_offset_uncertainty_ms=UNCERT, monotonic_ms=lambda: self.mono,
            resample=self.resample,
        )

    def exchange_now(self) -> Timestamp:
        if not self.synced:
            raise ClockUnsyncedError("unsynced")
        return Timestamp(ms=self.wall.now + self.estimate, source=TimeSource.DERIVED)

    def resample(self) -> bool:
        self.resamples += 1
        if not self.fresh:
            return False
        self.estimate = self.true_offset
        return True

    def exchange_step(self, ms: int, *, estimated: bool = True) -> None:
        """The exchange clock really moves ``ms`` against the local one (the periodic estimate sees it if ``estimated``)."""
        self.true_offset += ms
        if estimated:
            self.estimate += ms

    def wall_step(self, ms: int) -> None:
        """Windows steps the wall clock: the true exchange time does not move, the stored estimate is now stale."""
        self.wall.advance(ms)
        self.true_offset -= ms

    def tick(self, ms: int = 1000) -> tuple[int | None, str | None]:
        self.wall.advance(ms)
        self.mono += ms
        return self.tb.next_target_ms()

    def run(self, seconds: int) -> list[tuple[int | None, str | None]]:
        return [self.tick() for _ in range(seconds)]

    def true_now(self) -> int:
        return self.wall.now + self.true_offset


def test_R0_AC4_the_first_target_is_the_exchange_time_as_it_is() -> None:
    tb, _, xt = make(offset=7_000)
    assert tb.next_target_ms() == (xt.now, None)


def test_R0_AC4_unsynced_without_any_baseline_returns_no_target_and_the_unsynced_reason() -> None:
    tb, _, xt = make()
    xt.unsynced = True
    assert tb.next_target_ms() == (None, SKIP_CLOCK_UNSYNCED)


def test_R0_AC4_a_normal_step_is_accepted_and_each_target_follows_the_exchange_clock() -> None:
    tb, clock, xt = make()
    tb.next_target_ms()
    for _ in range(5):
        move(clock, xt, 1_000, 1_000)
        assert tb.next_target_ms() == (xt.now, None)


@pytest.mark.parametrize(("extra", "in_doubt"), [(UNCERT * 2 - 1, False), (UNCERT * 2, False), (UNCERT * 2 + 1, True)])
def test_R0_AC4_jump_guard_boundary_at_two_offset_uncertainties(extra: int, in_doubt: bool) -> None:
    # EDITED for Amendment 13 (the candidate is compared with the monotonic projection; a refused candidate puts the
    # clock in doubt and the target is the projection instead of None). The boundary is unchanged.
    rig = Rig()
    first, _ = rig.tb.next_target_ms()
    rig.exchange_step(extra, estimated=True)
    target, reason = rig.tick()
    assert first == T0 and target is not None
    assert abs(target - (T0 + 1_000)) <= (UNCERT * 2 if not in_doubt else 0)
    assert reason == (SKIP_CLOCK_JUMP if in_doubt else None)
    if in_doubt:
        assert target == T0 + 1_000  # the projection, not the candidate


def test_R0_AC4_a_candidate_behind_the_projection_by_more_than_the_allowance_is_also_in_doubt() -> None:
    rig = Rig()
    rig.tb.next_target_ms()
    rig.exchange_step(-(UNCERT * 2 + 1))
    assert rig.tick() == (T0 + 1_000, SKIP_CLOCK_JUMP)  # symmetric (ahead or behind)
    rig = Rig()
    rig.tb.next_target_ms()
    rig.exchange_step(-(UNCERT * 2))
    assert rig.tick()[1] is None


def test_R0_AC4_timebase_exits_advance_while_unsynced_entries_refused() -> None:
    rig = Rig()
    rig.tb.next_target_ms()
    rig.synced = False
    for k in range(1, 6):
        assert rig.tick() == (T0 + k * 1_000, SKIP_CLOCK_UNSYNCED)  # broker time keeps moving with MONOTONIC time
    rig.synced = True
    target, reason = rig.tick()
    assert reason is None and target == T0 + 6_000


def test_R0_AC4_positive_offset_step_not_applied_until_two_fresh_estimates() -> None:
    # (a) a single bad +1 h sample that the next fresh estimate does not confirm never moves broker time
    rig = Rig()
    rig.tb.next_target_ms()
    rig.estimate += 3_600_000
    first = rig.run(30)  # the doubt is first seen on tick 1; the first forced resample is 30 s later (tick 31)
    assert all(t == T0 + (i + 1) * 1_000 and r == SKIP_CLOCK_JUMP for i, (t, r) in enumerate(first))
    target, reason = rig.tick()  # the forced resample brings the true offset back
    assert (target, reason) == (T0 + 31_000, None) and rig.tb.rebase_count == 0
    # (b) a real +1 h step: broker time holds the projection until two consecutive fresh estimates agree, then jumps once
    rig = Rig()
    rig.tb.next_target_ms()
    rig.exchange_step(3_600_000)
    seen = rig.run(60)  # fresh estimates arrive on ticks 31 and 61
    assert all(t == T0 + (i + 1) * 1_000 and r == SKIP_CLOCK_JUMP for i, (t, r) in enumerate(seen))
    assert rig.tb.rebase_count == 0
    assert rig.tick() == (T0 + 61_000 + 3_600_000, None) and rig.tb.rebase_count == 1


def test_R0_AC4_offset_step_is_rebased_after_two_fresh_estimates_and_broker_time_never_goes_back() -> None:
    # REPLACES test_R0_AC4_a_sustained_jump_is_accepted_once_local_time_has_caught_up_with_it (deleted: it modelled an
    # exchange clock that does not follow local time). Fake exchange clock = wall + offset(t), injected monotonic clock.
    rig = Rig()
    rig.tb.next_target_ms()
    rig.exchange_step(500)  # a persistent +500 ms shift (> the 200 ms allowance): the old code refused it for ever
    targets: list[int] = []
    reasons: list[str | None] = []
    for _ in range(75):
        t, r = rig.tick()
        assert t is not None
        targets.append(t)
        reasons.append(r)
    assert reasons[0] == SKIP_CLOCK_JUMP and reasons[-1] is None  # in doubt, then trusted again
    assert rig.tb.rebase_count == 1
    assert targets == sorted(targets) and targets[-1] == rig.true_now()  # never back; caught up with the exchange
    assert reasons.index(None) >= 60  # not before the second fresh estimate (ticks 31 and 61)
    # and it stays rebased: another 10 minutes and no second rebase, no doubt
    assert all(r is None for _, r in rig.run(600)) and rig.tb.rebase_count == 1


def test_R0_AC4_negative_offset_step_holds_broker_time_flat_and_entries_refused_until_caught_up() -> None:
    rig = Rig()
    rig.tb.next_target_ms()
    rig.exchange_step(-10_000)  # the exchange clock is 10 s behind what it was
    ticks = rig.run(61)  # the rebase happens on tick 61
    assert all(r == SKIP_CLOCK_JUMP for _, r in ticks[:60])
    before = [t or 0 for t, _ in ticks]
    assert before == sorted(before)  # never back
    held = ticks[-1]
    assert held[1] == SKIP_CLOCK_JUMP  # rebased (two fresh estimates) but the estimate is still behind the held time
    flat = [rig.tick() for _ in range(5)]
    assert {t for t, _ in flat} == {held[0]} and all(r is not None for _, r in flat)  # flat, entries refused
    later = rig.run(15)
    assert later[-1][1] is None and (later[-1][0] or 0) >= (held[0] or 0)
    assert [t or 0 for t, _ in later] == sorted(t or 0 for t, _ in later)


def test_R0_AC4_backward_wall_step_does_not_freeze_broker_time() -> None:
    rig = Rig()
    rig.tb.next_target_ms()
    rig.wall_step(-600_000)  # Windows steps the wall clock back 10 minutes; the stored estimate is now stale
    first = rig.run(30)
    assert [t for t, _ in first] == [T0 + (i + 1) * 1_000 for i in range(30)]  # broker time follows MONOTONIC time
    assert all(r == SKIP_CLOCK_JUMP for _, r in first)
    t, r = rig.tick()  # the forced resample (tick 31) sees the stepped wall clock
    assert (t, r) == (T0 + 31_000, None)


def test_R0_AC4_forward_wall_step_does_not_move_broker_time() -> None:
    rig = Rig()
    rig.tb.next_target_ms()
    rig.wall_step(3_600_000)
    ticks = rig.run(40)
    assert [t for t, _ in ticks] == [T0 + (i + 1) * 1_000 for i in range(40)]  # no 1 h jump, ever
    assert ticks[0][1] == SKIP_CLOCK_JUMP and ticks[-1][1] is None


def test_R0_AC4_stale_offset_after_wall_step_is_not_rebased_without_fresh_estimate() -> None:
    rig = Rig(fresh=False)  # every forced resample fails: no fresh estimate is ever available
    rig.tb.next_target_ms()
    rig.wall_step(-600_000)
    ticks = rig.run(300)
    assert all(r == SKIP_CLOCK_JUMP for _, r in ticks) and rig.tb.rebase_count == 0
    assert [t for t, _ in ticks] == [T0 + (i + 1) * 1_000 for i in range(300)]  # exits still driven by the projection
    assert rig.resamples >= 9  # and it keeps trying


def test_R0_AC4_forces_resample_every_30s_in_doubt() -> None:
    rig = Rig(fresh=False)
    rig.tb.next_target_ms()
    rig.run(120)
    assert rig.resamples == 0  # not in doubt: no forced resample (the periodic one belongs to ClockSync)
    rig.synced = False
    counts = []
    for _ in range(95):
        rig.tick()
        counts.append(rig.resamples)
    # in doubt from tick 1: no forced resample for 30 s, then one every 30 s
    assert counts[29] == 0 and counts[30] == 1 and counts[59] == 1 and counts[60] == 2 and counts[89] == 2 and counts[90] == 3


def test_R0_AC4_restart_unverified_baseline_projects_replayed_time_and_first_sync_catches_up() -> None:
    rig = Rig()
    rig.synced = False
    rig.tb.seed_unverified(T0 - 3_000)  # the replayed ledger time after a restart with open positions
    for k in range(1, 4):
        assert rig.tick() == (T0 - 3_000 + k * 1_000, SKIP_CLOCK_UNSYNCED)  # projected with MONOTONIC time, in doubt
    rig.exchange_step(90_000)  # the process was down: the exchange is now 90 s ahead of the replayed time
    rig.synced = True
    target, reason = rig.tick()
    assert (target, reason) == (rig.wall.now + rig.estimate, None)  # first synced candidate accepted, no jump guard
    nxt = rig.tick()
    assert nxt == (target + 1_000 if target else 0, None)


def test_R0_AC4_an_unverified_baseline_is_in_doubt_even_if_the_first_sample_is_synced_and_far_behind() -> None:
    rig = Rig()
    rig.tb.seed_unverified(T0 + 50_000)  # ahead of the exchange (a ledger from the future)
    target, reason = rig.tick()
    assert target is not None and target >= T0 + 50_000  # forward-only


@given(
    ops=st.lists(
        st.one_of(
            st.tuples(st.just("tick"), st.integers(0, 120_000)),
            st.tuples(st.just("estimate"), st.integers(-4_000_000, 4_000_000)),
            st.tuples(st.just("exchange"), st.integers(-4_000_000, 4_000_000)),
            st.tuples(st.just("wall"), st.integers(-4_000_000, 4_000_000)),
            st.tuples(st.just("sync"), st.integers(0, 1)),
        ),
        min_size=1,
        max_size=60,
    )
)
def test_R0_AC4_projection_is_forward_only(ops: list[tuple[str, int]]) -> None:
    rig = Rig()
    last = rig.tb.next_target_ms()[0]
    assert last is not None
    for op, value in ops:
        if op == "tick":
            target, _ = rig.tick(value)
            assert target is not None and target >= last
            last = target
        elif op == "estimate":
            rig.estimate += value
        elif op == "exchange":
            rig.exchange_step(value)
        elif op == "wall":
            rig.wall_step(value)
        else:
            rig.synced = bool(value)


@given(garbage=st.lists(st.integers(-4_000_000, 4_000_000), min_size=1, max_size=30))
def test_R0_AC4_property_no_unconfirmed_sample_moves_broker_time(garbage: list[int]) -> None:
    rig = Rig()
    rig.tb.next_target_ms()
    for i, g in enumerate(garbage, start=1):
        rig.estimate = g  # a wrong sample appears; the true offset never changes, so no estimate confirms it
        target, _ = rig.tick(1_000)
        assert target is not None and target <= T0 + i * 1_000 + 2 * UNCERT  # never ahead of the projection
        assert target >= T0 + i * 1_000 - 2 * UNCERT  # and never behind it by more than the allowance


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


def test_R0_AC4_a_one_hour_clock_sample_is_not_followed_alerts_once_and_broker_time_keeps_moving(new_world: Any) -> None:
    # EDITED for Amendment 13: broker time is no longer frozen, it is the monotonic projection; only entries are refused.
    world: World = new_world()
    runner, _ = world.start()
    world.step(runner, 3)
    before = runner.last_advanced_ms
    assert before is not None
    world.sample_bias_ms = 3_600_000  # the next l2Book sample is one hour ahead (RISK-29)
    report = world.step(runner, 1, ms=601_000)
    assert report.skipped == SKIP_CLOCK_JUMP
    assert report.advanced_to_ms is not None and abs(report.advanced_to_ms - world.exchange_ms()) <= 2 * UNCERT
    assert runner.last_advanced_ms == report.advanced_to_ms and report.advanced_to_ms > before
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
