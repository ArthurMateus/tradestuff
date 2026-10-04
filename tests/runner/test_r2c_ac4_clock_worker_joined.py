"""R2c.AC4 (R2-V2-5, R2-SD4): ``Runner.stop`` joins the clock worker thread.

A clock estimate still in flight when the runner stops would touch the access monitor's ledger after it is closed.
``stop()`` must wait (bounded) for it, so that when it returns no ``r0-clock-estimate`` thread is alive. Kills the mutant
that removes ``self._parts.clock_worker.join(THREAD_JOIN_TIMEOUT_S)`` from ``Runner.stop``.
"""

from __future__ import annotations

import threading
from typing import Any

from tests.runner.world import World

WORKER = "r0-clock-estimate"
RELEASE_AFTER_S = 1.0  # the estimate's request is answered this long (real time) after stop() starts


def _workers() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == WORKER and t.is_alive()]


def test_R2c_AC4_stop_returns_with_no_live_clock_estimate_thread(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    world.step(runner, 2)
    world.hl.hang_types.add("l2Book")
    world.clock.advance(601_000)  # the periodic estimate (clock.offset_interval_s 600) is due: the worker is started
    world.pump_market()
    runner.step()  # waits a bounded time for the worker, which hangs on its l2Book request
    assert _workers(), "the scenario needs a clock estimate in flight when stop() is called"
    timer = threading.Timer(RELEASE_AFTER_S, world.hl.release)
    timer.start()
    try:
        assert runner.stop() == 0
        alive = _workers()
        assert alive == [], "stop() returned while a clock estimate thread was still running (not joined)"
    finally:
        timer.cancel()
        world.hl.release()
