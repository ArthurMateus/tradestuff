"""R2b.AC3 (RISK-75 + R2-SD3, blocking): with EVERY trading-thread REST endpoint hanging a loop iteration stays bounded.

R2.AC2 only pinned a hanging ``l2Book``. The trading client still waits a 10 s timeout per call inside ``gate_lock``:
leader reconciliation (``clearinghouseState`` and ``userFillsByTime`` per leader), the funding settlement
(``fundingHistory`` + ``metaAndAssetCtxs``, retried on every loop) and the hourly delisting check. With five followed
leaders that is about a minute and a half of loop without a single stop or liquidation processed, ``/flatten`` waiting for
the lock.

Mechanism-agnostic observable: the real duration of ``Runner.step`` (and the back-off the trading thread sleeps), with the
fake HL hanging all six endpoints and the config's default ``hl.rest_timeout_s`` (NO override: the developer picks a short
constant, a per-iteration cap with round-robin, or off-lock/worker execution). Five leaders are followed; the risk caps
(``max_symbol_open_risk_fraction``) let three of them hold an open SOL share, so three are reconciled (2 calls each).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from tests.hl.support import T0
from tests.runner.fake_hl import fill_json
from tests.runner.r2_support import SleepLog, drive, wait_real
from tests.runner.scenarios import PIN, set_mid_below_stop
from tests.runner.world import World

LOOP_BOUND_S = 3.0
HOUR_MS = 3_600_000
HANGING = ("clearinghouseState", "userFillsByTime", "metaAndAssetCtxs", "fundingHistory", "candleSnapshot", "l2Book")
WALLETS = ["0x" + c * 40 for c in "abcde"]


def five_leaders(new_world: Any) -> tuple[World, Any, SleepLog]:
    """Five followed leaders; the first three open SOL (our paper copy holds three shares, protected)."""
    world: World = new_world()
    for wallet in WALLETS:
        world.hl.leader_av[wallet] = "1000.0"
        world.hl.leader_fills.setdefault(wallet, []).append(
            fill_json(
                8_000_000,
                coin="SOL",
                side="B",
                sz="1.0",
                px="100.0",
                direction="Open Long",
                time_ms=T0 - 2 * 86_400_000,
            )
        )
    world.seed_ledger(
        [("follow_started", {"wallet": w, "followed_at_ms": T0 - HOUR_MS, "held": []}) for w in WALLETS]
        + [
            (
                "select_cycle",
                {
                    "t_ms": T0 - HOUR_MS,
                    "status": "applied",
                    "eligible_count": 5,
                    "followed": WALLETS,
                    "decisions": [{"kind": "join", "wallet": w, "replaces": None, "reason": None} for w in WALLETS],
                },
            )
        ]
    )
    log = SleepLog(world.clock)
    runner, _ = world.start(sleeper=log)
    for tid, wallet in enumerate(WALLETS[:3], start=1):
        world.subscribe_ready(runner, wallet)
        world.hl.leader_positions[wallet] = [("SOL", "5.0", "100.0")]
        world.hl.push_user_fills(
            wallet,
            [
                fill_json(
                    tid,
                    coin="SOL",
                    side="B",
                    sz="5.0",
                    px="100.0",
                    direction="Open Long",
                    time_ms=world.exchange_ms() - 200,
                )
            ],
        )
        world.run_until(
            runner,
            lambda t=tid: len(runner.broker.position("SOL").share_ids) >= t if runner.broker.position("SOL") else False,
            max_steps=60,
        )  # noqa: E501
    world.step(runner, 3, ms=500)
    assert len(runner.broker.position("SOL").share_ids) == 3, (
        "the scenario needs three open shares (three reconciled leaders)"
    )
    assert runner.broker.stops()
    return world, runner, log


def assert_bounded(beat: Any, what: str) -> None:
    assert beat.slept_s < LOOP_BOUND_S, (
        f"{what}: the trading thread slept {beat.slept_s:.0f} s (back-off / budget wait)"
    )
    assert beat.real_s < LOOP_BOUND_S, f"{what}: one loop iteration blocked for {beat.real_s:.1f} s"


def test_R2b_AC3_with_every_rest_endpoint_hanging_each_iteration_is_bounded_and_the_stop_is_processed(
    new_world: Any,
) -> None:
    world, runner, log = five_leaders(new_world)
    world.hl.hang_types.update(HANGING)
    set_mid_below_stop(world, runner)
    closed_at: int | None = None
    try:
        # 301 s apart: leader reconciliation (300 s), the funding boundary and the hourly delisting check all fall inside
        for i in range(14):
            beat = drive(world, runner, 301_000, log)
            assert_bounded(beat, f"iteration {i}")
            if runner.broker.position("SOL") is None and closed_at is None:
                closed_at = i
    finally:
        world.hl.release()
    assert closed_at is not None and closed_at <= 2, (
        f"the stop was not processed promptly (closed at iteration {closed_at})"
    )


def test_R2b_AC3_each_iteration_stays_bounded_when_the_endpoints_hang_from_the_first_loop_with_one_second_steps(
    new_world: Any,
) -> None:
    world, runner, log = five_leaders(new_world)
    world.hl.hang_types.update(HANGING)
    try:
        for i in range(6):
            beat = drive(world, runner, 1_000, log)
            assert_bounded(beat, f"iteration {i} (1 s steps)")
    finally:
        world.hl.release()


def test_R2b_AC3_flatten_waits_on_the_gate_lock_for_a_hanging_iteration_at_most_the_bound(new_world: Any) -> None:
    world, runner, _ = five_leaders(new_world)
    world.hl.hang_types.update(HANGING)
    seen = len(world.hl.requests_of("clearinghouseState"))
    world.clock.advance(301_000)  # reconciliation is due: the iteration reaches the hanging endpoint
    world.pump_market()
    stepper = threading.Thread(target=runner.step, name="r2b-trading-step")
    stepper.start()
    try:
        wait_real(
            lambda: len(world.hl.requests_of("clearinghouseState")) > seen or not stepper.is_alive(),
            seconds=5,
            what="the iteration to reach the exchange",
        )
        world.telegram_ready()
        world.tg.push_text(f"/flatten {PIN}")
        started = time.monotonic()
        try:
            wait_real(lambda: runner.flatten_runs, seconds=LOOP_BOUND_S + 0.5, what="the flatten run")
        except AssertionError:
            pytest.fail(
                f"/flatten waited {time.monotonic() - started:.1f} s (> {LOOP_BOUND_S} s) on gate_lock for a hanging iteration"
            )
    finally:
        world.hl.release()
        stepper.join(timeout=120)


def test_R2b_AC3_funding_settlement_retries_are_throttled_to_at_least_10_s(new_world: Any) -> None:
    """The rate of the funding hour is missing (``fundingHistory`` answers an error): the due funding stays owed and was
    retried on EVERY loop iteration. Thirty one-second iterations after the hour boundary: at most one retry per 10 s."""
    world, runner, log = five_leaders(new_world)
    to_boundary = HOUR_MS - world.clock.now % HOUR_MS
    world.clock.advance(to_boundary + 1_000)
    world.hl.fail_types.add("fundingHistory")
    world.step(runner, 2, ms=1_000)  # the boundary is crossed: the funding becomes due
    before = len(world.hl.requests_of("fundingHistory"))
    for _ in range(30):
        world.step(runner, 1, ms=1_000)
    retries = len(world.hl.requests_of("fundingHistory")) - before
    assert retries >= 1, "the scenario needs the funding to be retried at all (it is never skipped)"
    assert retries <= 5, f"{retries} fundingHistory requests in 30 s: the retry is not throttled to >= 10 s"


@pytest.mark.parametrize("rtype", HANGING)
def test_R2b_AC3_each_hanging_endpoint_alone_does_not_stall_an_iteration(new_world: Any, rtype: str) -> None:
    world, runner, log = five_leaders(new_world)
    world.hl.hang_types.add(rtype)
    try:
        for i in range(4):
            beat = drive(world, runner, 301_000, log)
            assert_bounded(beat, f"{rtype} hanging, iteration {i}")
    finally:
        world.hl.release()
