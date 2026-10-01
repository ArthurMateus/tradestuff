"""R0 fix round 1, batch B: the stop-loss survives a torn restore and consecutive restarts (RISK-54); a missing SL at the
reload is flagged or replaced; a dead loop is not silent (RISK-55: fsync failure -> ``runner_crashed`` alert naming the open
positions); a non-money exception does not kill the loop; the market hub is polled independently of the recorder
(RISK-65). Real runner/gate/broker/ledger/manager/bot; faults are injected at the OS boundary (``os.fsync``) or at the
disk-probe port."""

from __future__ import annotations

import errno
import os
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.ledger.store import Ledger
from tests.hl.ws_server import wait_for
from tests.recorder.helpers import FakeDisk
from tests.runner.scenarios import count, opened_position, set_mid_below_stop
from tests.runner.test_reload import assert_no_duplicates
from tests.runner.world import World


def stop_shape(runner: Any) -> list[tuple[Any, ...]]:
    return sorted((s.coin, s.kind, s.side, s.qty, s.trigger_px, s.share_id) for s in runner.broker.stops())


def protected(runner: Any) -> bool:
    """The open SOL position is covered by a live stop-loss for its quantity, or is being / has been closed."""
    position = runner.broker.position("SOL")
    if position is None or runner.broker.pending_exits():
        return True
    cover = sum((s.qty for s in runner.broker.stops() if s.kind == "sl" and s.coin == "SOL"), Decimal(0))
    return cover >= position.qty


def ledger_lines(world: World) -> list[str]:
    return (world.ledger_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)


def keep_first(world: World, lines: list[str], keep: int) -> None:
    """The ledger exactly as a kill -9 left it after record ``keep`` (a suffix of the append-only file is gone)."""
    (world.ledger_dir / "ledger.jsonl").write_text("".join(lines[:keep]), encoding="utf-8")


def test_R0_AC5_torn_restore_ledger_truncated_after_cancel_still_has_live_sl(new_world: Any) -> None:
    world, run1 = opened_position(new_world)
    run1.stop()
    n1 = len(world.records())
    run2, _ = world.start()
    run2.stop()
    full, lines = world.records(), ledger_lines(world)
    assert any(r.kind == "paper_cancel" for r in full[n1:]), "the restore re-registers the stops through the ledger"
    for cut in range(n1, len(full) + 1):  # a kill -9 after every record the restart wrote
        keep_first(world, lines, cut)
        run3, _ = world.start()
        world.step(run3, 3, ms=500)
        assert protected(run3), f"no live stop-loss after a restart on a ledger torn after record {cut - n1} of the restore"
        if run3.broker.position("SOL") is not None and not run3.broker.pending_exits():
            set_mid_below_stop(world, run3)
            world.run_until(run3, lambda: run3.broker.position("SOL") is None, max_steps=60, ms=200)
        run3.stop()


def test_R0_AC5_two_consecutive_restarts_no_duplicate_or_resurrected_stops(new_world: Any) -> None:
    world, run1 = opened_position(new_world)
    world.hl.mids["SOL"] = "110"  # the take-profit fills; the first stop-loss (98.6) is cancelled and replaced
    world.step(run1, 12, ms=500)
    shape = stop_shape(run1)
    assert shape and all(s[4] > Decimal("100") for s in shape), shape
    run1.stop()
    for _ in range(2):  # two restarts in a row, no step in between the second and the first
        runner, _ = world.start()
        assert stop_shape(runner) == shape  # same stops: not duplicated, the cancelled 98.6 stop not resurrected
        runner.stop()
    runner, _ = world.start()
    world.hl.mids["SOL"] = "90"
    world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=60, ms=200)
    assert runner.broker.stops() == () and not runner.broker.pending_exits()  # nothing left to fire later
    runner.stop()
    again, _ = world.start()
    assert again.broker.position("SOL") is None and again.broker.stops() == () and not again.broker.pending_exits()
    assert_no_duplicates(world)


def test_R0_AC6_reload_flags_or_replaces_missing_sl(new_world: Any) -> None:
    world, run1 = opened_position(new_world)
    sl_cid = next(s.client_order_id for s in run1.broker.stops() if s.kind == "sl")
    run1.stop()
    ledger = Ledger.open(world.ledger_dir, clock=world.clock)
    try:  # the stop-loss was cancelled after the last checkpoint (the checkpoint still lists it, the broker does not)
        ledger.append("paper_cancel", {"client_order_id": sl_cid, "target": "stop", "reason": "restart"})
    finally:
        ledger.close()
    run2, report = world.start()
    world.step(run2, 5, ms=500)
    flagged = bool(report.uncertain)
    covered = run2.broker.position("SOL") is not None and protected(run2) and not run2.broker.pending_exits()
    closing = run2.broker.position("SOL") is None or bool(run2.broker.pending_exits())
    assert covered or (flagged and closing), "an open position without a stop-loss was neither covered nor flagged and closed"


# ------------------------------------------------------------------------------------------- the fail-safe (RISK-55)


def drive_until(world: World, done: Any, *, seconds: float = 20.0) -> None:
    """Move the fake clock and the fake market while a ``run()`` thread loops, until ``done()`` (bounded in real time)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and not done():
        world.clock.advance(200)
        world.pump_market()
        time.sleep(0.02)
    assert done(), "the condition did not become true in time"


def test_R0_AC10_fsync_failure_enqueues_runner_crashed_alert_naming_positions(new_world: Any, monkeypatch: Any) -> None:
    world, run1 = opened_position(new_world)
    run1.stop()
    run2 = world.build()
    failing = threading.Event()
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        if failing.is_set():
            raise OSError(errno.EIO, "injected: input/output error")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    errors: list[BaseException] = []

    def target() -> None:
        try:
            run2.run(threading.Event())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    try:
        world.telegram_ready()
        wait_for(lambda: run2.broker.position("SOL") is not None, what="the restored position")
        set_mid_below_stop(world, run2)
        failing.set()  # the disk fails: the stop's ledger record cannot be made durable
        drive_until(world, lambda: not thread.is_alive())
    finally:
        failing.clear()
        thread.join(timeout=30)
    assert errors, "the loop ended on a failing ledger"
    wait_for(lambda: any("runner_crashed" in t for t in world.tg.sent()), what="the runner_crashed alert")
    text = next(t for t in world.tg.sent() if "runner_crashed" in t)
    assert "SOL" in text  # it names the open positions


class FlakyDisk(FakeDisk):
    """The disk probe port failing the way a real one can: an OSError or any other exception."""

    def __init__(self) -> None:
        super().__init__("500")
        self.fault: Exception | None = None

    def free_gb(self, path: Path) -> Decimal:
        if self.fault is not None:
            raise self.fault
        return super().free_gb(path)


def test_R0_AC10_non_money_exception_does_not_kill_loop(new_world: Any) -> None:
    world: World = new_world()
    world.disk = FlakyDisk()
    world.seed_follow()
    world.hl.leader_av["0x" + "a" * 40] = "1000.0"
    runner, _ = world.start()
    world.leader_open(runner)
    world.step(runner, 3)
    world.disk.fault = ValueError("injected: the free-space probe returned garbage")  # type: ignore[attr-defined]
    try:
        world.step(runner, 3, ms=70_000)  # the recorder probes the disk every 60 s
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"a non-money exception killed the loop: {type(exc).__name__}")
    set_mid_below_stop(world, runner)
    world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=20, ms=70_000)  # exits go on
    wait_for(lambda: count(world, "runner_section_failed") >= 1, what="a throttled alert for the failing section")
    assert count(world, "runner_section_failed") <= 2  # throttled, not one per iteration


def test_R0_AC13_hub_polled_independently_of_recorder_fault(new_world: Any) -> None:
    world, runner = opened_position(new_world)
    flaky = FlakyDisk()
    world.disk = flaky
    runner.stop()  # the position stays in the ledger; the restart uses the flaky probe
    run2, _ = world.start()
    world.step(run2, 3, ms=500)
    flaky.fault = OSError(errno.EIO, "injected: the recorder's disk probe fails on every iteration")
    set_mid_below_stop(world, run2)
    world.run_until(run2, lambda: run2.broker.position("SOL") is None, max_steps=20, ms=70_000)  # marks still arrive
    assert world.records("paper_stop_trigger")


def test_R0_AC13_mid_marks_reach_the_stops_even_when_the_recorder_raises_a_non_os_error(new_world: Any) -> None:
    world, runner = opened_position(new_world)
    flaky = FlakyDisk()
    world.disk = flaky
    runner.stop()
    run2, _ = world.start()
    world.step(run2, 3, ms=500)
    flaky.fault = ValueError("injected")
    set_mid_below_stop(world, run2)
    try:
        world.run_until(run2, lambda: run2.broker.position("SOL") is None, max_steps=20, ms=70_000)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"the loop died or the stop never fired: {type(exc).__name__}: {exc}")

