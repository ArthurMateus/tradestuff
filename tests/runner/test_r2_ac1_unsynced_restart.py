"""R2.AC1 (RISK-66, blocking): a restart with an UNSYNCED clock must not leave broker time behind the live exchange.

Broker time starts at the replayed ledger time and only moves by the monotonic projection, so after a downtime of D seconds
it lags the live books by D (plus the start-up time) while the hub keeps only 20 s of books and the broker fills only from
books with ``time <= broker time``: a triggered stop-loss / exit / flatten close stays pending, perhaps for ever when the
clock never becomes trusted (a Brazilian round trip over 100 ms of uncertainty). Pinned: while the baseline is unverified
broker time catches up to live exchange time (the newest exchange-stamped l2Book time in the hub, or the raw ClockSync
estimate even when too uncertain for entries); the close FILLS within 5 s of loop time although the clock never becomes
trusted; entries stay refused (``clock_unsynced``). Also: restored positions plus a clock that drops between the reload and
step 1 still advance broker time and mark.

Real runner, gate, broker, ledger, manager over the loopback fakes; the downtime is the fake local clock jumping while no
runner exists (the exchange moves with it)."""

from __future__ import annotations

from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from tests.runner.fake_hl import fill_json
from tests.runner.scenarios import opened_position, set_mid_below_stop
from tests.runner.world import LEADER, World

DOWNTIME_MS = 120_000  # well over the hub's 20 s book retention
BOUND_STEPS = 10  # x 500 ms = 5 s of loop time
STEP_MS = 500


def restart_after_downtime(new_world: Any, how: str, *, uncertain: bool = False) -> tuple[World, Any]:
    """An open copy, a stop (clean or kill -9), 120 s of downtime, then a start whose clock cannot be synced: the offset
    request fails (``unsynced``) or answers slower than ``clock.max_offset_uncertainty_ms`` (``uncertain``)."""
    world, run1 = opened_position(new_world)
    if how == "clean_stop":
        run1.stop()
    else:
        world.hard_kill(run1)
    world.clock.advance(DOWNTIME_MS)
    if uncertain:
        slow = {"first": True}

        def hook() -> None:
            if slow["first"]:  # the one estimate taken at start: a 600 ms round trip (uncertainty 301 ms > 100 ms)
                slow["first"] = False
                world.clock.advance(600)

        world.hl.hook = hook
    else:
        world.hl.fail_types.add("l2Book")
    run2, report = world.start()
    assert report.restored_positions == 1
    assert run2.sync.refusal_reason(ActionKind.OPEN) is not None, "precondition: the clock is not trusted for entries"
    return world, run2


def run_until_closed(world: World, runner: Any) -> list[int]:
    """Steps of 500 ms for at most 5 s of loop time; the broker times seen. The stop-loss price is crossed."""
    set_mid_below_stop(world, runner)
    seen: list[int] = []
    for _ in range(BOUND_STEPS):
        report = world.step(runner, 1, ms=STEP_MS)
        if report.advanced_to_ms is not None:
            seen.append(report.advanced_to_ms)
        if runner.broker.position("SOL") is None:
            break
    return seen


@pytest.mark.parametrize("how", ["clean_stop", "hard_kill"])
@pytest.mark.parametrize("variant", ["unsynced", "too_uncertain"])
def test_R2_AC1_after_a_long_downtime_and_an_unsynced_restart_a_triggered_stop_fills_within_5_s(
    new_world: Any, how: str, variant: str
) -> None:
    world, run2 = restart_after_downtime(new_world, how, uncertain=variant == "too_uncertain")
    seen = run_until_closed(world, run2)
    assert run2.broker.position("SOL") is None, (
        f"the stop-loss did not fill within 5 s of loop time; broker time lags exchange time by "
        f"{world.exchange_ms() - (run2.last_advanced_ms or 0)} ms"
    )
    assert [r for r in world.records("fill") if r.payload["exit_reason"] == "stop_loss"]
    assert run2.sync.refusal_reason(ActionKind.OPEN) is not None, "the clock never became trusted in this scenario"
    assert seen == sorted(seen), "broker time must never go backwards while catching up"


@pytest.mark.parametrize("variant", ["unsynced", "too_uncertain"])
def test_R2_AC1_broker_time_catches_up_to_live_exchange_time_while_the_clock_is_untrusted(
    new_world: Any, variant: str
) -> None:
    world, run2 = restart_after_downtime(new_world, "hard_kill", uncertain=variant == "too_uncertain")
    lag_at_start = world.exchange_ms() - (run2.last_advanced_ms or 0)
    world.step(run2, 8, ms=STEP_MS)  # 4 s: books of this run have reached the hub
    lag = world.exchange_ms() - (run2.last_advanced_ms or 0)
    assert lag_at_start >= DOWNTIME_MS - 5_000, "precondition: the replayed time is a downtime behind"
    assert -1_000 <= lag <= 3_000, f"broker time is still {lag} ms behind the live exchange time"


def test_R2_AC1_entries_stay_refused_while_broker_time_catches_up(new_world: Any) -> None:
    world, run2 = restart_after_downtime(new_world, "hard_kill")
    report = world.step(run2, 1, ms=STEP_MS)
    assert report.skipped == "clock_unsynced"
    world.hl.leader_positions[LEADER.lower()] = [("SOL", "5.0", "100.0"), ("ETH", "1.0", "3400.0")]
    world.hl.push_user_fills(
        LEADER,
        [fill_json(31, coin="ETH", side="B", sz="1.0", px="3400.0", direction="Open Long", time_ms=world.exchange_ms() - 100)],
    )
    for _ in range(BOUND_STEPS):
        report = world.step(run2, 1, ms=STEP_MS)
        assert report.skipped == "clock_unsynced"
    assert run2.broker.position("ETH") is None and not any(e.coin == "ETH" for e in run2.broker.pending_entries())
    assert not [r for r in world.records("paper_order") if r.payload.get("coin") == "ETH"]


def test_R2_AC1_a_flatten_close_fills_within_5_s_after_an_unsynced_restart(new_world: Any) -> None:
    from tests.runner.scenarios import flatten_cmd

    world, run2 = restart_after_downtime(new_world, "clean_stop")
    world.step(run2, 1, ms=STEP_MS)
    flatten_cmd(world, run2)
    for _ in range(BOUND_STEPS):
        world.step(run2, 1, ms=STEP_MS)
        if run2.broker.position("SOL") is None:
            break
    assert run2.broker.position("SOL") is None, "the /flatten close did not fill within 5 s of loop time"


def test_R2_AC1_a_pending_leader_close_requeued_at_the_restart_fills_within_5_s(new_world: Any) -> None:
    from tests.runner.test_reload import pending_close

    world, run1, _old = pending_close(new_world)
    world.hard_kill(run1)
    world.clock.advance(DOWNTIME_MS)
    world.hl.fail_types.add("l2Book")
    run2, report = world.start()
    assert report.requeued_exits, "precondition: the pending close was re-queued"
    for _ in range(BOUND_STEPS):
        world.step(run2, 1, ms=STEP_MS)
        if run2.broker.position("SOL") is None:
            break
    assert run2.broker.position("SOL") is None, "the re-queued exit did not fill within 5 s of loop time"


def test_R2_AC1_restored_positions_and_a_clock_that_drops_between_reload_and_step_1_still_advance_and_mark(
    new_world: Any,
) -> None:
    world, run1 = opened_position(new_world)
    run1.stop()
    run2, report = world.start()  # synced at the reload ...
    assert report.restored_positions == 1
    world.hl.fail_types.add("l2Book")  # ... and the offset can no longer be refreshed before the first step
    first = world.step(run2, 1, ms=1_801_000)  # the estimate is now older than clock.max_estimate_age_s
    assert first.skipped == "clock_unsynced"
    assert first.advanced_to_ms is not None, "no broker time was advanced: nothing is managed while the clock is in doubt"
    set_mid_below_stop(world, run2)
    for _ in range(BOUND_STEPS):
        world.step(run2, 1, ms=STEP_MS)
        if run2.broker.position("SOL") is None:
            break
    assert run2.broker.position("SOL") is None, "no mark reached the stop: nothing is managed while the clock is in doubt"
