"""R1.AC6 [integration]: HTTP 429 that persists on one wallet.

After the client's own retries are exhausted the step fails; the wallet is retried LATER (after a cooldown), other
wallets progress meanwhile, and nothing hammers the endpoint while it cools down. Cooldown derived from existing
config: ``hl.backoff_max_s`` seconds of the injected clock after the failure.
"""

from __future__ import annotations

import logging

import pytest

from tests.hl.support import T0, status
from tests.selection.helpers import w
from tests.selection.r1_logs import BACKFILL_LOGGER, attr, events
from tests.selection.r1_world import World, make_world, synth_fills

BAD, B, C = w(1), w(2), w(3)


def build() -> tuple[World, dict[str, bool]]:
    world = make_world()
    for wallet, tid0 in ((BAD, 1), (B, 500_000), (C, 600_000)):
        world.hl.set_fills(wallet, synth_fills(5, tid0=tid0))
    state = {"limited": True}
    world.hl.rules[(BAD, "userFillsByTime")] = lambda call: status(429) if state["limited"] else None
    world.backfiller.set_candidates([BAD, B, C])
    return world, state


def test_R1_AC6_other_wallets_progress_while_one_is_rate_limited(caplog: pytest.LogCaptureFixture) -> None:
    world, _ = build()
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        for _ in range(3):
            world.backfiller.step()
    assert world.backfiller.inputs(B, T0) is not None and world.backfiller.inputs(C, T0) is not None
    assert world.backfiller.inputs(BAD, T0) is None
    assert world.backfiller.complete is False
    (rec,) = events(caplog, "backfill_failed")
    assert attr(rec, "wallet") == BAD and attr(rec, "status") == 429


def test_R1_AC6_the_limited_wallet_is_not_hammered_during_the_cooldown() -> None:
    world, _ = build()
    for _ in range(3):
        world.backfiller.step()
    seen = len(world.fills_calls(BAD))
    for _ in range(5):  # nobody else is left; the clock has not moved
        world.backfiller.step()
    assert len(world.fills_calls(BAD)) == seen
    world.clock.advance(int(world.cfg["hl.backoff_max_s"] * 1000) - 5_000)  # still inside the cooldown
    world.backfiller.step()
    assert len(world.fills_calls(BAD)) == seen


def test_R1_AC6_it_is_retried_after_the_cooldown_and_completes_once_the_limit_lifts() -> None:
    world, state = build()
    for _ in range(3):
        world.backfiller.step()
    state["limited"] = False
    world.clock.advance(int(world.cfg["hl.backoff_max_s"] * 1000) + 1_000)
    world.backfiller.step()
    assert world.backfiller.inputs(BAD, T0) is not None
    assert world.backfiller.complete is True
