"""R2b.AC7 (RISK-76): after a failed leader read the reconcile is retried soon, not 300 s later.

``reconcile()`` sets the next run to ``+reconcile_interval`` (300 s) before the leader is read. With the fail-fast
trading client a 429 cooldown or a budget refusal fails the read at once, so the backstop (C4: a leader close nobody saw)
would be missing for 300 to 600 s. Pinned: once a leader read failed, a new attempt reaches the exchange within
``max(wait_s, 30 s)`` (the cooldown after one 429 is a second; the bound used here is 90 s, far below 300 s).
Real runner, manager, gate, broker; loopback fake HL answering 429."""

from __future__ import annotations

from typing import Any

from tests.runner.r2_support import open_copy, rate_limit

READS = "clearinghouseState"


def test_R2b_AC7_a_failed_leader_read_is_retried_within_90_s_not_300(new_world: Any) -> None:
    world, runner = open_copy(new_world)
    original = world.hl._reply
    rate_limit(world, READS)  # every clearinghouseState answers 429 from now on
    baseline = len(world.hl.requests_of(READS))
    waited = 0
    while len(world.hl.requests_of(READS)) == baseline and waited < 400_000:
        world.step(runner, 1, ms=5_000)
        waited += 5_000
    assert len(world.hl.requests_of(READS)) > baseline, "precondition: the periodic reconcile never read the leader"
    world.hl.fail_types.discard(READS)  # the exchange answers again (the cooldown after one 429 is short)
    world.hl._reply = original  # type: ignore[method-assign]
    after_failure = len(world.hl.requests_of(READS))
    for _ in range(18):  # 90 s of loop time
        world.step(runner, 1, ms=5_000)
        if len(world.hl.requests_of(READS)) > after_failure:
            return
    raise AssertionError("the leader read was not retried within 90 s of a failed read (next reconcile is +300 s)")
