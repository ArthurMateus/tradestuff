"""R2c.AC1 (R2-V2-1, money path): two or more AGREEING future-stamped books must not push broker time ahead.

The 2-book confirmation alone is not enough: two books stamped later than the local clock + the 30 s catch-up cap
(``wiring.CATCH_UP_MAX_AHEAD_MS``) confirm each other. Only the cap stops them. Observable: broker time vs the true
exchange time and the stop filling within 5 s of loop time. Kills the mutant that removes the
``confirmed > clock.now_ms() + CATCH_UP_MAX_AHEAD_MS`` guard in ``wiring._live_exchange_ms``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.runner.scenarios import set_mid_below_stop
from tests.runner.test_r2b_ac1_catch_up import AHEAD_LIMIT_MS, _restart_with_uncertain_clock


@pytest.mark.parametrize("ahead_ms", [60_000, 600_000])
def test_R2c_AC1_two_agreeing_future_stamped_books_do_not_push_broker_time_ahead(new_world: Any, ahead_ms: int) -> None:
    world, runner = _restart_with_uncertain_clock(new_world, first_estimate_ms=None)
    future = world.exchange_ms() + ahead_ms  # well beyond local clock + 30 s
    assert world.hl.push_l2("SOL", future) >= 1, "the market feed is not subscribed"
    assert world.hl.push_l2("SOL", future + 1_000) >= 1
    time.sleep(0.05)  # real sockets: let both frames reach the hub before the first iteration
    set_mid_below_stop(world, runner)
    # while the two future books are the newest in the hub, broker time is never taken ahead of the exchange
    for k in range(8):
        world.step(runner, 1, ms=500)
        ahead = (runner.last_advanced_ms or 0) - world.exchange_ms()
        assert ahead <= AHEAD_LIMIT_MS, f"step {k}: broker time is {ahead} ms ahead of the exchange (future books taken)"
        if k == 0:  # the bogus stamps then age out of the hub (it keeps 64 books per coin)
            now = world.exchange_ms()
            for i in range(70):
                world.hl.push_l2("SOL", now - 100 + i)
            time.sleep(0.2)
    # and once they are gone the loop still protects the position: the stop fills in bounded loop time (30 s), never ahead
    for _ in range(60):
        if runner.broker.position("SOL") is None:
            break
        world.step(runner, 1, ms=500)
        ahead = (runner.last_advanced_ms or 0) - world.exchange_ms()
        assert ahead <= AHEAD_LIMIT_MS, f"broker time is {ahead} ms ahead of the exchange"
    assert runner.broker.position("SOL") is None, "the stop never filled within 30 s of loop time"
