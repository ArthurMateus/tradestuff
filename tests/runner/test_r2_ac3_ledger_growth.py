"""R2.AC3 (RISK-59, blocking before the 2-4 week paper run): the ledger must not grow without bound and nothing may walk
the whole ledger on the trading thread.

* an unchanged ``runner_checkpoint`` is written only after a long force interval (600 s), and the 500 seen-signal ids are
  not rewritten in full by every checkpoint (a delta, or only when they change); a restart still knows every id;
* an idle runner (no trades) writes a small, bounded amount in a simulated hour; the heartbeat (one record per 10 s by
  design, about 180 KB/h) is accounted separately;
* with a ~50 MB ledger a trading-loop iteration that has retention pruning due stays fast and starts no ledger walk, and the
  Telegram post facts of an opened and a closed position (poll thread) are read from memory / the tail, not by a scan.

Real runner over the loopback fakes; the only instrumentation is a counter around the ledger's own walk."""

from __future__ import annotations

import collections
import time
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from copytrade.ledger.records import encode_line
from tests.hl.ws_server import wait_for
from tests.positions.helpers import make_signal
from tests.runner.r2_support import WalkLog, fill_ledger, open_copy
from tests.runner.world import LEADER, World

STEP_BOUND_S = 0.25  # a normal iteration takes milliseconds; one walk of 50 MB takes 0.37 s (two of them: >0.7 s)


@pytest.fixture
def walks(monkeypatch: pytest.MonkeyPatch) -> WalkLog:
    import threading

    from copytrade.ledger import store

    log = WalkLog()
    original = store._walk

    def counting(directory: Any) -> Any:
        log.threads.append(threading.current_thread())
        yield from original(directory)

    monkeypatch.setattr(store, "_walk", counting)
    return log


def out_of_scope(i: int, ms: int) -> Any:
    sig = make_signal(900_000 + i, ActionKind.OPEN, wallet=LEADER, coin="SOL", ts=ms)
    return type(sig)(**{**sig.__dict__, "signal_id": f"seen:{i}", "outcome": "out_of_scope"})


def idle_hour(new_world: Any, *, seen: int = 500) -> tuple[World, Any, list[Any]]:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    with runner.gate_lock:
        runner.manager.on_signals([out_of_scope(i, world.exchange_ms()) for i in range(seen)])
    world.step(runner, 3, ms=1000)
    n0 = len(world.records())
    world.step(runner, 360, ms=10_000)  # one simulated hour, nothing happens
    return world, runner, world.records()[n0:]


# ------------------------------------------------------------------------------------------ checkpoints and growth


def test_R2_AC3_an_idle_runner_writes_a_checkpoint_only_after_the_force_interval(new_world: Any) -> None:
    _, _, grown = idle_hour(new_world)
    checkpoints = [r for r in grown if r.kind == "runner_checkpoint"]
    assert len(checkpoints) <= 8, f"{len(checkpoints)} checkpoints in an idle hour (one per 600 s is 6)"


def test_R2_AC3_the_seen_signal_ids_are_not_rewritten_in_full_by_every_checkpoint(new_world: Any) -> None:
    world, _, grown = idle_hour(new_world)
    checkpoints = [r for r in grown if r.kind == "runner_checkpoint"]
    assert checkpoints
    sizes = [len(encode_line(r)) for r in checkpoints]
    # without the 500 ids a checkpoint is about 0.5 KB; with them about 6 KB: after the ids were written once, the
    # unchanged state costs a small delta or nothing
    assert max(sizes[1:] or [0]) <= 2_000, f"idle checkpoints of {sizes} bytes still carry the seen ids"


def test_R2_AC3_idle_growth_in_a_simulated_hour_is_small_and_bounded(new_world: Any) -> None:
    _, _, grown = idle_hour(new_world)
    by_kind: collections.Counter[str] = collections.Counter()
    for record in grown:
        by_kind[record.kind] += len(encode_line(record))
    heartbeat = by_kind.pop("component_heartbeat", 0)  # 360 x ~500 B: by design, one per 10 s (F4), not RISK-59
    assert by_kind["runner_checkpoint"] <= 25_000, dict(by_kind)
    assert sum(by_kind.values()) <= 100_000, dict(by_kind)
    assert sum(by_kind.values()) + heartbeat <= 300_000


@pytest.mark.parametrize("how", ["clean_stop", "hard_kill"])
def test_R2_AC3_a_restart_after_an_idle_hour_still_knows_every_seen_signal(new_world: Any, how: str) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    now = world.exchange_ms()
    first = [make_signal(7_000 + i, ActionKind.CLOSE, wallet=LEADER, coin="ETH", ts=now) for i in range(3)]
    with runner.gate_lock:
        runner.manager.on_signals([out_of_scope(i, now) for i in range(497)])
        runner.manager.on_signals(first)  # no share on ETH: each one is booked as a skip once, then remembered
    world.step(runner, 363, ms=10_000)  # an idle hour of forced and unforced checkpoints
    if how == "clean_stop":
        runner.stop()
    else:
        world.hard_kill(runner)
    run2, _ = world.start()
    n0 = len(world.records("signal_skip"))
    with run2.gate_lock:
        run2.manager.on_signals(first)  # the same ids again: remembered, nothing is booked
    assert len(world.records("signal_skip")) == n0, "a seen signal id was forgotten across the restart"
    fresh = make_signal(7_100, ActionKind.CLOSE, wallet=LEADER, coin="ETH", ts=world.exchange_ms())
    with run2.gate_lock:
        run2.manager.on_signals([fresh])
    assert len(world.records("signal_skip")) == n0 + 1  # and a new id is still processed


def test_R2_AC3_a_changed_state_is_still_checkpointed_promptly(new_world: Any) -> None:
    """Guard against over-correcting: a structural change (an opened copy) is checkpointed within a couple of seconds."""
    world, _runner = open_copy(new_world)
    checkpoints = world.records("runner_checkpoint")
    shares = checkpoints[-1].payload["manager"]["state"]["shares"]
    assert [s["status"] for s in shares] == ["open"], shares


# ------------------------------------------------------------------------------------------ whole-ledger scans


def timed_step(world: World, runner: Any, ms: int) -> float:
    world.clock.advance(ms)
    world.pump_market()
    started = time.perf_counter()
    runner.step()
    elapsed = time.perf_counter() - started
    time.sleep(0.012)
    return elapsed


def big_ledger_runner(new_world: Any, walks: WalkLog) -> tuple[World, Any]:
    world: World = new_world()
    world.seed_follow()
    fill_ledger(world, 50)
    assert (world.ledger_dir / "ledger.jsonl").stat().st_size > 45_000_000
    from tests.runner.test_dev_e2e import small_leader

    small_leader(world)
    runner, _ = world.start()
    world.step(runner, 2, ms=1000)
    walks.reset()  # the start-up reads are not what is pinned here
    return world, runner


def test_R2_AC3_a_loop_iteration_with_pruning_due_over_a_50_mb_ledger_stays_fast_and_walks_nothing(
    new_world: Any, walks: WalkLog
) -> None:
    world, runner = big_ledger_runner(new_world, walks)
    slowest = 0.0
    for _ in range(3):  # three hourly prunes
        slowest = max(slowest, timed_step(world, runner, 3_600_001))
        slowest = max(slowest, timed_step(world, runner, 1000))
    assert walks.on_trading_thread == 0, f"{walks.on_trading_thread} whole-ledger walks on the trading thread"
    assert slowest < STEP_BOUND_S, f"an iteration took {slowest:.2f} s with a 50 MB ledger"


def test_R2_AC3_the_post_facts_of_an_opened_and_a_closed_position_do_not_scan_the_ledger(
    new_world: Any, walks: WalkLog
) -> None:
    world, runner = big_ledger_runner(new_world, walks)
    world.leader_open(runner)
    world.step(runner, 3, ms=500)
    wait_for(lambda: "PAPER LONG SOL" in world.tg.all_outgoing_text(), what="the post of the opened position")
    world.leader_close()
    slowest = 0.0
    for _ in range(40):
        slowest = max(slowest, timed_step(world, runner, 500))
        if runner.broker.position("SOL") is None:
            break
    assert runner.broker.position("SOL") is None
    world.step(runner, 8, ms=1000)  # past telegram.min_edit_interval_s: the closing post is an edit
    wait_for(lambda: "CLOSED" in world.tg.all_outgoing_text(), what="the closing post (realised P&L and exit reason)")
    assert walks.total == 0, f"{walks.total} whole-ledger walks while posting one position's open and close"
    assert slowest < STEP_BOUND_S, f"an iteration took {slowest:.2f} s while the post facts were read"
