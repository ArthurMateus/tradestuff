"""R2c.AC5 (R2-V2-3, advisory; pins the intended behaviour): after the per-iteration REST budget is spent

* an ENTRY signal's leader read fails closed: the entry is skipped and ledgered as ``signal_skip`` with reason
  ``no_leader_av`` (it is lost, never guessed, never sent without the leader's account value);
* an EXIT is NOT starved by the spent entry budget: a leader close, and a triggered stop, still close our copy at once.
  (Reading of the code: ``PositionManager`` reads REST only for opens (ATR candles, ``clearinghouse_state``), adds (ATR) and
  a wrong-direction reduce, whose failure is caught; a leader close and the broker's stop need no REST at all.)

The budget is spent by a hanging ``clearinghouseState``: the first entry's leader read takes the whole 2 s of the iteration,
the second one finds it spent. Two followed leaders, A (already copied) and B and C opening at once.
"""

from __future__ import annotations

from typing import Any

from tests.hl.support import T0
from tests.runner.fake_hl import fill_json
from tests.runner.r2_support import SleepLog, drive
from tests.runner.scenarios import set_mid_below_stop
from tests.runner.world import World

LOOP_BOUND_S = 3.0
HOUR_MS = 3_600_000
A, B, C = ("0x" + c * 40 for c in "abc")


def _world_with_a_copied(new_world: Any) -> tuple[World, Any, SleepLog]:
    world: World = new_world()
    wallets = [A, B, C]
    for wallet in wallets:
        world.hl.leader_av[wallet] = "1000.0"
        world.hl.leader_fills.setdefault(wallet, []).append(
            fill_json(
                8_000_000, coin="SOL", side="B", sz="1.0", px="100.0", direction="Open Long",
                time_ms=T0 - 2 * 86_400_000,
            )
        )
    world.seed_ledger(
        [("follow_started", {"wallet": w, "followed_at_ms": T0 - HOUR_MS, "held": []}) for w in wallets]
        + [
            (
                "select_cycle",
                {
                    "t_ms": T0 - HOUR_MS,
                    "status": "applied",
                    "eligible_count": 3,
                    "followed": wallets,
                    "decisions": [{"kind": "join", "wallet": w, "replaces": None, "reason": None} for w in wallets],
                },
            )
        ]
    )
    log = SleepLog(world.clock)
    runner, _ = world.start(sleeper=log)
    world.leader_open(runner, wallet=A, tid=1)
    world.run_until(runner, lambda: runner.broker.position("SOL") is not None and runner.broker.stops(), max_steps=40)
    world.step(runner, 3, ms=500)
    for wallet in (B, C):
        world.subscribe_ready(runner, wallet)
    return world, runner, log


def _open_fill(world: World, wallet: str, tid: int) -> None:
    world.hl.leader_positions[wallet] = [("SOL", "5.0", "100.0")]
    world.hl.push_user_fills(
        wallet,
        [fill_json(tid, coin="SOL", side="B", sz="5.0", px="100.0", direction="Open Long", time_ms=world.exchange_ms() - 200)],
    )


def _a_open(runner: Any) -> bool:
    """Our copy of leader A's SOL position is still open (B and C may hold the coin's position too)."""
    position = runner.broker.position("SOL")
    return position is not None and any(sid.startswith(f"share:{A}") for sid in position.share_ids)


ACK_ITERATIONS = 6  # x 500 ms: the paper broker's order ack delay (about 2 s) is the normal latency of any exit


def _skips(world: World, wallet: str) -> list[str]:
    return [r.payload["reason"] for r in world.records("signal_skip") if r.payload["leader"].lower() == wallet]


def test_R2c_AC5_an_entry_after_the_budget_is_spent_fails_closed_with_no_leader_av(new_world: Any) -> None:
    world, runner, log = _world_with_a_copied(new_world)
    shares_before = len(runner.broker.position("SOL").share_ids)
    world.hl.hang_types.add("clearinghouseState")
    try:
        _open_fill(world, B, 11)
        _open_fill(world, C, 12)
        worst = 0.0
        for i in range(6):
            beat = drive(world, runner, 500, log)
            worst = max(worst, beat.real_s)
            assert beat.real_s < LOOP_BOUND_S, f"iteration {i}: blocked for {beat.real_s:.1f} s"
    finally:
        world.hl.release()
    assert _skips(world, B) == ["no_leader_av"], f"leader B: {_skips(world, B)}"
    assert _skips(world, C) == ["no_leader_av"], f"leader C (read after the budget was spent): {_skips(world, C)}"
    assert len(runner.broker.position("SOL").share_ids) == shares_before, "an entry was opened without a leader read"


def test_R2c_AC5_a_leader_close_is_not_starved_by_a_spent_entry_budget(new_world: Any) -> None:
    world, runner, log = _world_with_a_copied(new_world)
    world.hl.hang_types.add("clearinghouseState")
    try:
        _open_fill(world, B, 21)  # spends the iteration's REST time first
        _open_fill(world, C, 22)
        world.leader_close(wallet=A, tid=23)  # the exit signal arrives in the same iteration, after the entries
        for i in range(ACK_ITERATIONS):
            beat = drive(world, runner, 500, log)
            assert beat.real_s < LOOP_BOUND_S, f"iteration {i}: blocked for {beat.real_s:.1f} s"
    finally:
        world.hl.release()
    assert "no_leader_av" in _skips(world, B) + _skips(world, C), "the scenario needs an entry that met the spent budget"
    assert not _a_open(runner), f"the leader's close was not followed within {ACK_ITERATIONS} iterations"


def test_R2c_AC5_a_triggered_stop_is_not_starved_by_a_spent_entry_budget(new_world: Any) -> None:
    world, runner, log = _world_with_a_copied(new_world)
    world.hl.hang_types.add("clearinghouseState")
    try:
        _open_fill(world, B, 31)
        _open_fill(world, C, 32)
        set_mid_below_stop(world, runner)
        for i in range(ACK_ITERATIONS):
            beat = drive(world, runner, 500, log)
            assert beat.real_s < LOOP_BOUND_S, f"iteration {i}: blocked for {beat.real_s:.1f} s"
    finally:
        world.hl.release()
    assert "no_leader_av" in _skips(world, B) + _skips(world, C), "the scenario needs an entry that met the spent budget"
    assert not _a_open(runner), f"the stop was not processed within {ACK_ITERATIONS} iterations"
