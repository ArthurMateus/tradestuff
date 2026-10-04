"""R2c.AC2 unit behaviour of the off-thread worker pattern (real threads, no mocks of our own code)."""

from __future__ import annotations

import threading
from typing import Any
import time

import pytest

from copytrade.hl.ws import ConnectPendingError
from copytrade.runner.offthread import BackgroundConnector, BackgroundLeaderboard, OffThread


class _Gate:
    """A call that blocks until released and counts how many threads entered it."""

    def __init__(self, value: bytes = b"[]") -> None:
        self.release = threading.Event()
        self.entered = 0
        self.value = value
        self._lock = threading.Lock()

    def __call__(self) -> bytes:
        with self._lock:
            self.entered += 1
        self.release.wait(10)
        return self.value


def _wait(predicate, seconds: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    end = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_R2c_AC2_a_hung_call_costs_one_bounded_wait_then_nothing_and_never_stacks_threads() -> None:
    gate = _Gate()
    call: OffThread[bytes] = OffThread(gate, name="t", start_wait_s=0.3)
    started = time.monotonic()
    assert call.poll() is None
    assert 0.25 <= time.monotonic() - started < 1.5  # the starting poll waits its bound
    for _ in range(50):
        began = time.monotonic()
        assert call.poll() is None
        assert time.monotonic() - began < 0.1  # later polls never wait
    assert gate.entered == 1  # one in flight
    gate.release.set()
    call.join(time.monotonic() + 5)


def test_R2c_AC2_an_outcome_waits_in_the_slot_once_and_a_new_call_follows() -> None:
    gate = _Gate(b"first")
    call: OffThread[bytes] = OffThread(gate, name="t", start_wait_s=0.01)
    assert call.poll() is None
    gate.release.set()
    _wait(lambda: gate.entered == 1 and call._slot is not None)  # noqa: SLF001
    settled = call.poll()
    assert settled is not None and settled.unwrap() == b"first"
    assert gate.entered == 1  # taking the outcome did not start a call
    again = call.poll()  # release is set: the new call returns within the starting wait
    assert gate.entered == 2
    assert again is None or again.unwrap() == b"first"
    call.join(time.monotonic() + 5)


def test_R2c_AC2_the_calls_exception_is_reraised_on_the_polling_thread() -> None:
    def boom() -> bytes:
        raise TimeoutError("deadline")

    call: OffThread[bytes] = OffThread(boom, name="t", start_wait_s=2.0)
    settled = call.poll()
    assert settled is not None
    with pytest.raises(TimeoutError, match="deadline"):
        settled.unwrap()


def test_R2c_AC2_close_discards_a_late_connection_and_join_waits_for_the_worker() -> None:
    closed: list[int] = []
    release = threading.Event()

    def work() -> int:
        release.wait(10)
        return 7

    call: OffThread[int] = OffThread(work, name="t", discard=closed.append, start_wait_s=0.01)
    assert call.poll() is None
    call.close()
    assert call.poll() is None  # no call starts after the close
    release.set()
    call.join(time.monotonic() + 5)
    assert closed == [7]


def test_R2c_AC2_join_is_bounded_by_its_deadline() -> None:
    gate = _Gate()
    call: OffThread[bytes] = OffThread(gate, name="t", start_wait_s=0.01)
    call.poll()
    began = time.monotonic()
    call.join(time.monotonic() + 0.2)
    assert time.monotonic() - began < 1.5
    gate.release.set()
    call.join(time.monotonic() + 5)


def test_R2c_AC2_leaderboard_fetch_raises_timeout_while_running_then_returns_the_bytes_once() -> None:
    gate = _Gate(b"body")
    board = BackgroundLeaderboard(gate, name="t")
    assert board.ready() is False
    with pytest.raises(TimeoutError):
        board.fetch()
    gate.release.set()
    _wait(board.ready)
    assert board.fetch() == b"body"
    assert gate.entered >= 1
    board.close()
    board.join(time.monotonic() + 5)


def test_R2c_AC2_connector_is_pending_while_connecting_then_hands_over_the_connection() -> None:
    release = threading.Event()

    class Conn:
        def send(self, message: str) -> None: ...
        def recv(self) -> str | None:
            return None

        def close(self) -> None: ...

    conn = Conn()

    class Slow:
        def connect(self) -> Conn:
            release.wait(10)
            return conn

    connector = BackgroundConnector(Slow(), name="t")  # type: ignore[arg-type]
    with pytest.raises(ConnectPendingError):
        connector.connect()
    release.set()
    deadline = time.monotonic() + 5
    while True:
        try:
            assert connector.connect() is conn
            break
        except ConnectPendingError:
            assert time.monotonic() < deadline
            time.sleep(0.01)
    connector.close()
    connector.join(time.monotonic() + 5)


def test_R2c_AC2_stop_returns_with_no_live_leaderboard_thread(new_world: Any) -> None:
    """``Runner.stop`` abandons and joins the off-thread workers: none is alive when it returns."""
    world = new_world()
    world.seed_follow()
    world.hl.leaderboard_delay_s = 1.0  # the GET answers 1 s (real time) after it starts: in flight when stop() runs
    runner, _ = world.start()
    runner.step()  # the follow cycle is due at once: the download starts on its worker
    names = ("r0-follow-leaderboard", "r0-recorder-leaderboard")

    def alive() -> list[threading.Thread]:
        return [t for t in threading.enumerate() if t.name in names and t.is_alive()]

    assert alive(), "the scenario needs a leaderboard download in flight when stop() is called"
    try:
        assert runner.stop() == 0
        assert alive() == [], "stop() returned while a leaderboard thread was still running (not joined)"
        assert runner._parts.follow_leaderboard.ready() is False, "the workers were not closed"  # noqa: SLF001
    finally:
        world.hl.release()


def test_R2c_AC2_a_download_still_running_defers_the_follow_cycle_without_an_outage_alert(new_world: Any) -> None:
    """The cycle waits for the download instead of reporting an outage; it runs when the download has finished."""
    world = new_world()
    world.seed_follow()
    world.hl.leaderboard_delay_s = 60.0
    runner, _ = world.start()
    try:
        for _ in range(6):
            world.step(runner, 1, ms=500)
        assert runner.follow.due(), "the follow cycle ran (or gave up) while the download was still running"
        assert not any("leaderboard" in text for text in world.tg.sent()), "an outage was reported for a slow download"
    finally:
        world.hl.release()
    deadline = time.monotonic() + 10
    while runner.follow.due() and time.monotonic() < deadline:
        world.step(runner, 1, ms=500)
        time.sleep(0.05)
    assert not runner.follow.due(), "the follow cycle never ran after the download finished"
    runner.stop()
