"""R0.AC10: clean stop. Stop taking entries, leave exits and stops as they are, flush the ledger, the recorder files and
the Telegram queue, join the threads, exit 0. A system failure exits 1 with one line, never a traceback."""

from __future__ import annotations

import io
import signal
import threading
import time
from typing import Any

from copytrade.core.events import Alert
from copytrade.ledger.store import Ledger
from tests.hl.ws_server import wait_for
from tests.runner.fake_hl import fill_json
from tests.runner.world import LEADER, World

R0_THREAD_PREFIX = "r0-"


def r0_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith(R0_THREAD_PREFIX) and t.is_alive()]


def test_R0_AC10_stop_returns_zero_is_idempotent_and_releases_ledger_and_threads(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    world.step(runner, 3)
    assert r0_threads(), "the dedicated threads run while the runner runs"
    assert runner.stop() == 0
    assert runner.stop() == 0
    assert not any(t.is_alive() for t in runner.threads) and r0_threads() == []
    Ledger.open(world.ledger_dir, clock=world.clock).close()  # the writer lock was released
    assert world.records("runner_stop")[-1].payload["run_id"] == runner.run_id


def test_R0_AC10_recording_files_are_closed_and_flushed_on_stop(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.step(runner, 10)
    assert world.recordings_dir.exists()
    runner.stop()
    assert not [p for p in world.recordings_dir.rglob("*.part")], "no half-written file is left behind"
    closed = world.records("recording_file_closed")
    assert closed and "shutdown" in {r.payload.get("reason") for r in closed}


def test_R0_AC10_queued_telegram_alerts_are_delivered_before_exit(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    runner.bot.send(Alert("stop_probe", "last words"))
    runner.stop()
    assert any("stop_probe: last words" in t for t in world.tg.sent())


def test_R0_AC10_a_hanging_telegram_cannot_block_the_stop(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    world.tg.mode = "hang"
    runner.bot.send(Alert("stop_probe", "never delivered"))
    done: list[int] = []
    t = threading.Thread(target=lambda: done.append(runner.stop()))
    started = time.monotonic()
    t.start()
    t.join(timeout=30)
    assert done == [0] and time.monotonic() - started < 30


def test_R0_AC10_after_request_stop_new_entries_are_refused_but_exits_and_stops_keep_working(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.leader_open(runner)
    stops_before = len(runner.broker.stops())
    runner.request_stop("test")
    runner.request_stop("again")  # idempotent
    assert runner.stopping and runner.entries_blocked
    assert not runner.gate.paused  # a stop is not the persisted kill switch: the next start is not paused
    world.hl.leader_positions[LEADER.lower()] = [("SOL", "5.0", "100.0"), ("ETH", "1.0", "3400.0")]
    world.hl.push_user_fills(
        LEADER,
        [fill_json(80, coin="ETH", side="B", sz="1.0", px="3400.0", direction="Open Long", time_ms=world.exchange_ms() - 100)],
    )
    world.run_until(
        runner,
        lambda: any(r.payload.get("reason") == "policy_veto" for r in world.records("signal_skip")),
        max_steps=60,
        ms=200,
    )
    assert runner.broker.position("ETH") is None
    assert "policy_veto" in [r.payload["reason"] for r in world.records("signal_skip")]
    assert len(runner.broker.stops()) == stops_before  # the stops are left as they are
    world.leader_close()
    world.run_until(runner, lambda: runner.broker.position("SOL") is None)  # the mirrored exit still goes out
    assert runner.stop() == 0


def test_R0_AC10_stop_does_not_flatten_and_the_next_start_is_not_paused(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.leader_open(runner)
    fills_before = len(world.records("fill"))
    runner.stop()
    assert len(world.records("fill")) == fills_before  # nothing was closed by the stop
    run2, report = world.start()
    assert not run2.gate.paused and not report.entries_blocked and run2.broker.position("SOL") is not None


def test_R0_AC10_run_returns_zero_when_the_stop_event_is_set(new_world: Any) -> None:
    world: World = new_world()
    runner = world.build()
    stop = threading.Event()
    codes: list[int] = []
    t = threading.Thread(target=lambda: codes.append(runner.run(stop)))
    t.start()
    world.telegram_ready()
    stop.set()
    t.join(timeout=20)
    assert codes == [0] and not t.is_alive()


def test_R0_AC10_run_returns_zero_after_request_stop(new_world: Any) -> None:
    world: World = new_world()
    runner = world.build()
    codes: list[int] = []
    t = threading.Thread(target=lambda: codes.append(runner.run(threading.Event())))
    t.start()
    world.telegram_ready()
    runner.request_stop("kill switch")
    t.join(timeout=20)
    assert codes == [0]


def test_R0_AC10_ctrl_c_stops_run_app_cleanly_with_exit_code_zero_and_restores_the_handler(new_world: Any) -> None:
    from copytrade.runner.app import run_app

    world: World = new_world()
    root = world.write_config()
    before = signal.getsignal(signal.SIGINT)
    out, err = io.StringIO(), io.StringIO()

    def interrupt() -> None:
        wait_for(lambda: world.tg.calls("getUpdates"), what="the runner to be running")
        signal.raise_signal(signal.SIGINT)

    helper = threading.Thread(target=interrupt)
    helper.start()
    code = run_app(root, world.env, deps=world.deps(), stop=None, out=out, err=err)
    helper.join(timeout=5)
    assert code == 0 and err.getvalue() == ""
    assert signal.getsignal(signal.SIGINT) is before
    assert r0_threads() == []


def test_R0_AC10_a_system_failure_stops_the_runner_cleanly_and_is_reraised_for_the_app_to_report(new_world: Any) -> None:
    from copytrade.ledger.errors import LedgerWriteError

    world: World = new_world()
    world.seed_follow()
    runner = world.build()
    errors: list[BaseException] = []

    def target() -> None:
        try:
            runner.run(threading.Event())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=target)
    t.start()
    world.telegram_ready()
    runner.ledger.close()  # the disk "fails": the next ledger append raises
    world.hl.push_user_fills(
        LEADER,
        [fill_json(99, coin="SOL", side="B", sz="1.0", px="100.0", direction="Open Long", time_ms=world.exchange_ms())],
    )
    t.join(timeout=30)
    assert not t.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], LedgerWriteError)
    assert r0_threads() == [] and not any(th.is_alive() for th in runner.threads)
