"""R2.AC2 (RISK-67, blocking; CONFIRMED on the PO's PC: 'loop_stalled: trading loop has not completed an iteration for 30 s'
right after failed info requests): a REST call must never block the trading thread.

The clock resample (``ClockSync.tick`` every 600 s, and the forced resample every 30 s while the clock is in doubt) is a
retrying ``l2Book`` request (retry_max 5, back-off up to 60 s, a 10 s timeout per attempt) on the trading thread, and the
forced one runs inside ``gate_lock``. In doubt is exactly when Hyperliquid answers 429, so stops and liquidations were
processed about once per 90 s and ``/flatten`` waited on the lock. Pinned, with the fake HL answering 429 or hanging:

* every loop iteration is bounded (< 2 s of wall time AND < 2 s of back-off sleeping on the trading thread), including the
  iterations that start a resample, while stops are still processed on every loop;
* ``/flatten`` does not wait on ``gate_lock`` for a resample that hangs;
* the forced resample still happens (about every 30 s in doubt), only off the critical path;
* the other REST uses on the trading thread (mark/mid seed, candles, meta, funding, leader reconciliation, fills resync) do
  not sleep on it either (one test per request type; which of them fail today is listed in the test plan).

Real runner, gate, broker, ledger, manager over the loopback fakes. The sleeper is the fake one (it advances the fake clock)
and records which thread slept, so a back-off of 63 s is measured in microseconds of real time."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from tests.runner.r2_support import SleepLog, drive, rate_limit, wait_real
from tests.runner.scenarios import enter_unsynced, flatten_cmd, set_mid_below_stop
from tests.runner.world import World

LOOP_BOUND_S = 2.0


def opened(new_world: Any, **config: Any) -> tuple[World, Any, SleepLog]:
    """An open copy (SL 98.6) in a runner whose REST client sleeps through a ``SleepLog``."""
    world: World = new_world(**config)
    log = SleepLog(world.clock)
    world2, runner = _opened_in(world, log)
    return world2, runner, log


def _opened_in(world: World, log: SleepLog) -> tuple[World, Any]:
    from tests.runner.test_dev_e2e import small_leader

    small_leader(world)
    world.seed_follow()
    runner, _ = world.start(sleeper=log)
    world.leader_open(runner)
    world.run_until(runner, lambda: runner.broker.position("SOL") is not None and runner.broker.stops(), max_steps=40)
    world.step(runner, 3, ms=500)
    return world, runner


def assert_bounded(beat: Any, what: str) -> None:
    assert beat.slept_s < LOOP_BOUND_S, f"{what}: the trading thread slept {beat.slept_s:.0f} s (retry back-off / budget wait)"
    assert beat.real_s < LOOP_BOUND_S, f"{what}: one loop iteration blocked for {beat.real_s:.1f} s"


# ------------------------------------------------------------------------------------------------ 429 while in doubt


def test_R2_AC2_with_l2book_answering_429_every_iteration_is_bounded_and_the_stop_is_processed(new_world: Any) -> None:
    world, runner, log = opened(new_world)
    before = len(world.hl.requests_of("l2Book"))
    rate_limit(world, "l2Book")
    set_mid_below_stop(world, runner)
    closed_at: int | None = None
    for i, ms in enumerate([1_801_000] + [10_000] * 12):  # unsynced from the first step; 120 s in doubt
        beat = drive(world, runner, ms, log)
        assert_bounded(beat, f"iteration {i} (+{ms} ms)")
        assert beat.report.advanced_to_ms is not None, f"iteration {i}: broker time was not advanced"
        if runner.broker.position("SOL") is None and closed_at is None:
            closed_at = i
    assert closed_at is not None and closed_at <= 4, f"the stop was not processed promptly (closed at iteration {closed_at})"
    wait_real(lambda: len(world.hl.requests_of("l2Book")) >= before + 3, seconds=5, what="the forced resamples (30 s apart)")


def test_R2_AC2_a_resample_that_keeps_answering_429_never_stalls_the_loop_for_an_hour_of_doubt(new_world: Any) -> None:
    world, runner, log = opened(new_world)
    rate_limit(world, "l2Book")
    worst = 0.0
    for _ in range(30):  # 30 iterations of 2 minutes: the periodic estimate (600 s) and ~120 forced ones fall inside
        beat = drive(world, runner, 120_000, log)
        worst = max(worst, beat.slept_s, beat.real_s)
    assert worst < LOOP_BOUND_S, f"the slowest iteration took {worst:.0f} s"


# ------------------------------------------------------------------------------------------------ a hanging l2Book


def test_R2_AC2_with_l2book_hanging_the_iteration_returns_within_2_s(new_world: Any) -> None:
    world, runner, log = opened(new_world, hl__rest_timeout_s=4)  # the 10 s default x 6 attempts would be a minute
    world.hl.hang_types.add("l2Book")
    for i, ms in enumerate([1_801_000, 31_000, 31_000]):
        beat = drive(world, runner, ms, log)
        assert_bounded(beat, f"iteration {i} with a hanging l2Book")  # asserted at once: a failing run stops here
    world.hl.release()


def test_R2_AC2_flatten_does_not_wait_on_the_gate_lock_for_a_hanging_resample(new_world: Any) -> None:
    world, runner, log = opened(new_world, hl__rest_timeout_s=4)
    enter_unsynced(world, runner)  # the clock is in doubt: the next forced resample is due 30 s later
    world.hl.fail_types.discard("l2Book")
    world.hl.hang_types.add("l2Book")
    requests = len(world.hl.requests_of("l2Book"))
    world.clock.advance(31_000)
    world.pump_market()
    stepper = threading.Thread(target=runner.step, name="r2-trading-step")
    stepper.start()
    try:
        wait_real(
            lambda: len(world.hl.requests_of("l2Book")) > requests or not stepper.is_alive(),
            seconds=5,
            what="the forced resample to reach the exchange (or the iteration to finish)",
        )
        flatten_cmd(world, runner)  # waits 5 s for the bot to run flatten: it needs gate_lock
        assert runner.flatten_runs, "/flatten waited on gate_lock for a resample that hangs"
    finally:
        world.hl.release()
        stepper.join(timeout=60)


# ------------------------------------------------------------------------------------------------ the other REST uses

OTHER_REST = [
    "metaAndAssetCtxs",  # delisting check (hourly), the broker's rules refresh, funding at the hour boundary
    "fundingHistory",  # funding settlement at every UTC hour boundary
    "candleSnapshot",  # ATR / candles for open shares
    "clearinghouseState",  # leader reconciliation every 300 s, follow cycle
    "userFillsByTime",  # reconciliation, the daily fill audit, the feed's gap resync
    "allMids",
    "l2Book",  # the periodic ClockSync estimate every 600 s
]


@pytest.mark.parametrize("rtype", OTHER_REST)
def test_R2_AC2_no_rest_call_sleeps_on_the_trading_thread_for_an_hour_of_429(new_world: Any, rtype: str) -> None:
    world, runner, log = opened(new_world)
    rate_limit(world, rtype)
    worst, where = 0.0, ""
    for i in range(14):  # 14 x 5 minutes: reconciliation (300 s), hourly checks and a funding boundary all fall inside
        beat = drive(world, runner, 300_000, log)
        if max(beat.slept_s, beat.real_s) > worst:
            worst, where = max(beat.slept_s, beat.real_s), f"iteration {i}"
    assert worst < LOOP_BOUND_S, f"{rtype} answering 429: the trading thread blocked for {worst:.0f} s at {where}"
