"""R2b.AC9 (RISK-79a): the forced resample of a clock in doubt does not hold ``gate_lock`` while it waits.

Every 30 s in doubt the time base asks for a fresh offset estimate and waits a bounded time (0.25 s) for the clock
worker; ``Runner.step`` does that inside ``gate_lock``, so the Telegram thread (``/flatten``, ``/status``) and the audits
queue behind it. Pinned: while the resample request is on its way to the exchange (the fake HL hangs it), the lock can be
taken by another thread at once."""

from __future__ import annotations

import threading
from typing import Any

from tests.runner.r2_support import wait_real
from tests.runner.scenarios import enter_unsynced
from tests.runner.test_r2_ac2_nonblocking_rest import opened


def test_R2b_AC9_the_forced_resample_wait_does_not_hold_the_gate_lock(new_world: Any) -> None:
    world, runner, _log = opened(new_world, hl__rest_timeout_s=4)
    enter_unsynced(world, runner)  # in doubt: the next forced resample is due 30 s later
    world.hl.fail_types.discard("l2Book")
    world.hl.hang_types.add("l2Book")
    requests = len(world.hl.requests_of("l2Book"))
    world.clock.advance(31_000)
    world.pump_market()
    stepper = threading.Thread(target=runner.step, name="r2b-trading-step")
    stepper.start()
    try:
        wait_real(
            lambda: len(world.hl.requests_of("l2Book")) > requests, seconds=5, what="the forced resample to be sent"
        )
        got = runner.gate_lock.acquire(timeout=0.1)
        if got:
            runner.gate_lock.release()
        assert got, "gate_lock is held while the loop waits for the forced resample"
    finally:
        world.hl.release()
        stepper.join(timeout=60)
