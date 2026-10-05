"""R2b.AC8 (RISK-78): ``seed_unverified`` only when the start clock is untrusted.

The runner seeded the unverified baseline on EVERY restart with open positions, so even with a synced clock the first
synced candidate was accepted without the jump guard: a wall-clock step forward (Windows) between the start and the first
iteration moved broker time ahead by up to ``clock.max_estimate_age_s``. Pinned: a restart whose clock is synced keeps
the jump guard (the candidate is refused as ``clock_jump``, broker time stays on the exchange's timeline), Amendment 13.
(R2.AC1 pins the untrusted-start catch-up and is unchanged.)"""

from __future__ import annotations

from typing import Any

from tests.runner.scenarios import opened_position

WALL_STEP_MS = 300_000  # below clock.offset_interval_s (600 s): no fresh estimate repairs it before step 1


def test_R2b_AC8_a_synced_restart_refuses_a_wall_clock_step_before_the_first_iteration(new_world: Any) -> None:
    world, run1 = opened_position(new_world)
    run1.stop()
    run2, report = world.start()  # the clock is synced: the offset estimate succeeds at start
    assert report.restored_positions == 1
    world.step_wall(WALL_STEP_MS)  # Windows steps the wall clock forward; the exchange does not move
    step = world.step(run2, 1, ms=500)
    lead = (run2.last_advanced_ms or 0) - world.exchange_ms()
    assert lead < 5_000, f"broker time is {lead} ms ahead of the exchange: the wall-clock step was accepted"
    assert step.skipped == "clock_jump", step.skipped
