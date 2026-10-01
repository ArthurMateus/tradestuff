"""R0 fix round 1: pins for the mutation survivors of the senior-dev run on the money path (runner, paper restore). Each
test names the mutant it kills (``name`` in scratchpad r0m/muts.json) and passes on the code as written; they are
guards of behaviour that exists. Run the mutation harness with this file added to every mutant's test list."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from copytrade.runner import reload as rl
from copytrade.runner.timebase import ALERT_LOOP_STALLED
from tests.hl.ws_server import wait_for
from tests.runner.scenarios import opened_position, set_mid_below_stop
from tests.runner.test_reload import pending_close
from tests.runner.world import T0, World


def test_pin_br_funding_boundary_a_restart_after_a_funding_record_does_not_charge_that_hour_again(new_world: Any) -> None:
    """Kills br_funding_boundary: the next funding boundary after a restart is computed from the later of the last
    broker time and the last funding hour (a funding record with no fill after it must not be charged twice)."""
    world, run1 = opened_position(new_world)
    world.step(run1, 2, ms=3_000_000)  # the position is held across a UTC hour boundary
    charged = [r.payload["hour_ms"] for r in world.records("paper_funding")]
    assert charged and len(charged) == len(set(charged))
    run1.stop()
    run2, _ = world.start()
    world.step(run2, 3, ms=1_000)
    hours = [r.payload["hour_ms"] for r in world.records("paper_funding")]
    assert hours == charged, "the hour that was already charged was charged again after the restart"
    run2.stop()


def test_pin_rp_trigger_cap_a_triggered_stop_is_capped_by_the_exits_already_pending(new_world: Any) -> None:
    """Kills rp_trigger_cap: the take-profit triggered and its exit is pending (no fresh books), then the stop-loss
    triggers too. The restart must rebuild the same pending exits, not a full-size exit for the stop."""
    world, run1 = opened_position(new_world)
    world.hl.mids["SOL"] = "110"
    for _ in range(4):
        world.clock.advance(300)
        runner_step_no_books(world, run1)
    assert len(world.records("paper_stop_trigger")) == 1 and run1.broker.pending_exits()
    world.hl.mids["SOL"] = "90"
    for _ in range(6):
        world.clock.advance(300)
        runner_step_no_books(world, run1)
    assert len(world.records("paper_stop_trigger")) == 2, "the stop-loss must trigger while the take-profit exit is pending"
    before = sorted(e.qty for e in run1.broker.pending_exits())
    assert len(before) == 2 and sum(before) <= Decimal("1.00"), before
    run1.stop()
    run2, _ = world.start()
    assert sorted(e.qty for e in run2.broker.pending_exits()) == before


def runner_step_no_books(world: World, runner: Any) -> None:
    import time

    world.hl.push_mids()
    runner.step()
    time.sleep(0.012)


def test_pin_br_exit_action_a_pending_full_close_is_requeued_as_a_close_not_a_reduce(new_world: Any) -> None:
    """Kills br_exit_action: an exit whose quantity equals the share's quantity is a CLOSE."""
    world, run1, _old = pending_close(new_world)
    run1.stop()
    run2, report = world.start()
    new = {r.new_client_order_id for r in report.requeued_exits}
    assert new
    orders = [r for r in world.records("paper_order") if r.client_order_id in new]
    assert orders and all(r.payload["action"] == "close" for r in orders)
    run2.stop()


def test_pin_rl_time_floor_the_restored_time_never_goes_back_below_the_ledgers_last_time(new_world: Any) -> None:
    """Kills rl_time_floor: restart with the exchange clock unsynced (the reload's own time is then 0)."""
    world, run1, _old = pending_close(new_world)
    last_ms = world.records()[-1].ts.ms
    run1.stop()
    world.hl.fail_types.add("l2Book")
    _run2, report = world.start()
    assert report.requeued_exits
    new = {r.new_client_order_id for r in report.requeued_exits}
    decided = [r.payload["decided_at_ms"] for r in world.records("paper_order") if r.client_order_id in new]
    assert decided and all(ms >= last_ms for ms in decided), (decided, last_ms)


def test_pin_rl_no_behind_flag_state_records_after_the_last_checkpoint_are_flagged_and_block_entries(new_world: Any) -> None:
    """Kills rl_no_behind_flag (explicit pin; the same rule is exercised in test_dev_e2e)."""
    world, run1 = opened_position(new_world)
    run1.stop()
    world.seed_ledger([("paper_cancel", {"client_order_id": "late-x", "target": "stop", "reason": "late"})])
    _run2, report = world.start()
    assert rl.CHECKPOINT_BEHIND_LEDGER in [u.code for u in report.uncertain] and report.entries_blocked


def test_pin_rl_no_unproven_flag_an_exit_without_a_share_is_flagged_not_silently_dropped(new_world: Any) -> None:
    """Kills rl_no_unproven_flag (explicit pin, no Telegram involved: the old test could only fail through a flake)."""
    world: World = new_world()
    world.seed_ledger(
        [
            (
                "paper_order",
                {
                    "coin": "SOL", "side": "sell", "action": "close", "requested_qty": Decimal("1"), "qty": Decimal("1"),
                    "decision_px": Decimal("100"), "decided_at_ms": T0, "trade_id": "tX", "share_id": "ghost-share",
                    "leverage": None, "exit_reason": "leader_close",
                },
                "ghost-exit-pin",
            )
        ]
    )
    _run, report = world.start()
    assert rl.EXIT_STATE_UNPROVEN in [u.code for u in report.uncertain] and report.entries_blocked


def test_pin_rn_stall_the_heartbeat_fires_after_three_ledger_heartbeats_not_thirty(new_world: Any) -> None:
    """Kills rn_stall (the stall threshold is 3 x ledger.heartbeat_interval_s = 30 s of local time)."""
    world: World = new_world()
    runner, _ = world.start()
    world.step(runner, 2)
    world.clock.advance(30_001)
    wait_for(lambda: any(ALERT_LOOP_STALLED in t for t in world.tg.sent()), what="the stall alert at 30 s")


def test_pin_rn_mark_stale_a_stale_mid_is_never_used_as_a_mark(new_world: Any) -> None:
    """Kills rn_mark_stale: the hub's last mid is older than feed.stale_after_s (30 s) when the position opens; it must
    not be marked against the new position's stop (the books are fresh, the mids are not)."""
    world: World = new_world()
    world.hl.leader_av["0x" + "a" * 40] = "1000.0"
    world.seed_follow()
    runner, _ = world.start()
    world.subscribe_ready(runner)
    world.hl.mids["SOL"] = "95"
    world.hl.push_mids()  # the last allMids message the hub will see for a while: SOL at 95
    world.step(runner, 2, ms=200, pump=False)
    world.hl.mids["SOL"] = "100"  # the books (fresh) are at 100; the mids are not pushed again
    from tests.runner.fake_hl import fill_json

    world.hl.leader_positions["0x" + "a" * 40] = [("SOL", "5.0", "100.0")]
    world.hl.push_user_fills(
        "0x" + "a" * 40,
        [fill_json(1, coin="SOL", side="B", sz="5.0", px="100.0", direction="Open Long", time_ms=world.exchange_ms() - 200)],
    )
    for _ in range(80):
        world.clock.advance(1_000)
        world.hl.push_l2("SOL", world.exchange_ms())
        runner.step()
        import time

        time.sleep(0.012)
        if runner.broker.position("SOL") is not None:
            break
    position = runner.broker.position("SOL")
    assert position is not None, "the entry did not fill on fresh books"
    stop = min(s.trigger_px for s in runner.broker.stops() if s.kind == "sl")
    assert stop > Decimal("95"), "the stale 95 would be below the new stop"
    for _ in range(5):
        world.clock.advance(1_000)
        world.hl.push_l2("SOL", world.exchange_ms())
        runner.step()
        time.sleep(0.012)
    assert runner.broker.position("SOL") is not None and not world.records("paper_stop_trigger")
