"""R0 developer tests (end to end over the loopback world): the order inside one loop iteration, what a restart does
about the time the process was down, the checkpoint check, and the copy results that pause a leader."""

from __future__ import annotations

from typing import Any

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.paper.types import OrderIntent
from copytrade.runner import reload as rl
from tests.runner.fake_hl import fill_json
from tests.runner.world import LEADER, T0, World

ACK_DELAY_MS = 1000  # paper.ack_delay_ms in the fixture config


def small_leader(world: World) -> None:
    """A leader account small enough that a mirrored entry clears the minimum order size."""
    world.hl.leader_av[LEADER.lower()] = "1000.0"


def opened(new_world: Any, **config: Any) -> tuple[World, Any]:
    world: World = new_world(**config)
    small_leader(world)
    world.seed_follow()
    runner, _ = world.start()
    world.leader_open(runner)
    world.step(runner, 3)
    assert runner.broker.position("SOL") is not None and runner.broker.stops()
    return world, runner


def test_a_stop_is_booked_at_this_iterations_time_so_its_exit_cannot_fill_earlier_than_one_ack_later(
    new_world: Any,
) -> None:
    world, runner = opened(new_world)
    trigger_px = min(s.trigger_px for s in runner.broker.stops() if s.kind == "sl")
    world.hl.mids["SOL"] = str(trigger_px - 1)
    n_before = len(world.records("paper_stop_trigger"))
    target = None
    for _ in range(400):
        report = world.step(runner, 1, ms=200)
        if len(world.records("paper_stop_trigger")) > n_before:
            target = report.advanced_to_ms
            break
    assert target is not None, "the stop never triggered within the step budget"
    world.run_until(runner, lambda: runner.broker.position("SOL") is None)
    exit_fill = [r for r in world.records("fill") if r.payload["exit_reason"] == "stop_loss"][-1]
    assert exit_fill.payload["time"]["ms"] >= target + ACK_DELAY_MS  # advance_to came before the mark


def test_the_checkpoint_is_flagged_behind_when_state_records_follow_it_and_not_after_a_clean_stop(
    new_world: Any,
) -> None:
    world, run1 = opened(new_world)
    run1.stop()
    run2, report = world.start()
    assert report.uncertain == ()  # a clean stop leaves nothing after the last checkpoint
    run2.stop()
    world.seed_ledger([("paper_cancel", {"client_order_id": "x", "target": "stop", "reason": "late"})])
    _run3, report = world.start()
    assert [u.code for u in report.uncertain] == [rl.CHECKPOINT_BEHIND_LEDGER] and report.entries_blocked


def test_what_a_leader_did_while_we_were_down_is_resynced_at_the_restart_and_mirrored(new_world: Any) -> None:
    world, run1 = opened(new_world)
    run1.stop()
    world.hl.leader_positions[LEADER.lower()] = []
    close = fill_json(
        9,
        coin="SOL",
        side="A",
        sz="5.0",
        px="100.0",
        direction="Close Long",
        time_ms=world.exchange_ms() + 500,
        start_position="5.0",
    )
    world.hl.leader_fills[LEADER.lower()].append(close)  # exchange history only: nothing is pushed live
    run2, _ = world.start()
    world.run_until(run2, lambda: run2.broker.position("SOL") is None)
    assert 9 in {r.payload["tid"] for r in world.records("signal")}  # the resync delivered the fill itself
    assert [r for r in world.records("fill") if r.payload["exit_reason"] == "leader_close"]


def test_a_losing_copy_pauses_its_leader_and_the_pause_is_ledgered(new_world: Any) -> None:
    world, runner = opened(new_world, leader_pause__max_copy_dd="0.02")
    trigger_px = min(s.trigger_px for s in runner.broker.stops() if s.kind == "sl")
    world.hl.mids["SOL"] = str(trigger_px - 1)
    world.run_until(runner, lambda: runner.broker.position("SOL") is None)
    world.step(runner, 3)
    assert [r.payload["wallet"] for r in world.records("leader_paused")] == [LEADER]
    assert LEADER not in runner.follow.followed
    assert T0 > 0


def test_every_process_gets_its_own_gate_key_so_a_token_from_a_previous_run_is_refused(new_world: Any) -> None:
    world: World = new_world()
    run1, _ = world.start()
    world.step(run1, 3)
    now = run1.last_advanced_ms
    assert now is not None
    intent = OrderIntent(
        client_order_id="replayed",
        coin="SOL",
        side="buy",
        qty=Qty("1"),
        action=ActionKind.OPEN,
        decided_at_ms=now,
        decision_px=Price("100"),
        trade_id="t-r",
        share_id="s-r",
        leverage=2,
        exit_reason=None,
    )
    old_token = run1.gate._authority.issue(intent)  # noqa: SLF001 - the previous process's only way to mint a token
    run1.stop()
    run2, _ = world.start()
    world.step(run2, 3)
    result = run2.broker.submit(intent, old_token)
    assert result.reason == "invalid_gate_token"
    assert run2.broker.position("SOL") is None
