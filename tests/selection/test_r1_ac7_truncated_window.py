"""R1.AC7 [integration]: Hyperliquid only makes the 10 000 most recent fills of a wallet retrievable.

A fact of the API, so a code constant (no config key). A wallet with more fills than that in the scoring window is
paged to a clean DONE (a short last page) yet the window is incomplete: the oldest part is silently missing. Pinned:

- truncated = fills fetched reach 10 000 (the constant) AND the earliest fetched fill is later than
  ``window_start + one day`` (``_DAY_MS``, the day constant the backfiller already has; no new key). One day absorbs a
  wallet whose first fill is a little after the window start; a wallet that started trading inside the window and has
  exactly 10 000 fills is indistinguishable from a cut one, and dropping it is the fail-closed side.
- a truncated wallet is logged ONCE as ``backfill_too_active`` (the ``reason`` contains ``too_active`` and
  ``truncat``), dropped (``inputs`` is None: never scored on a partial window), cooled down for 24 h, then one new
  attempt.
- not truncated: 9 999 fills, or 10 000 fills whose earliest is at or before ``window_start + one day``.
"""

from __future__ import annotations

import logging

import pytest

from copytrade.hl.budget import Priority
from tests.hl.support import T0
from tests.selection.helpers import w
from tests.selection.r1_logs import BACKFILL_LOGGER, attr, events
from tests.selection.r1_world import DAY, HL_FILLS_LIMIT, World, make_world, synth_fills

BIG, B = w(1), w(2)
WINDOW_START = T0 - 180 * DAY  # scoring.window_days = 180, the fake clock does not move while the tests fetch


def make(wallet_fills: list[dict[str, object]]) -> World:
    world = make_world(fills_limit=HL_FILLS_LIMIT)
    world.hl.set_fills(BIG, wallet_fills)  # type: ignore[arg-type]
    world.hl.set_fills(B, synth_fills(5, tid0=500_000))
    world.backfiller.set_candidates([BIG, B])
    return world


def run_to_complete(world: World, limit: int = 30) -> None:
    for _ in range(limit):
        if world.backfiller.complete:
            return
        world.backfiller.step()
    raise AssertionError("the backfill did not complete")


MINUTE = 60_000


def recent(n: int) -> list[dict[str, object]]:
    # one fill a minute, the last one about 6 days (n = 20 000: 13.9 days of fills) before now: far after window_start + 1 day,
    # and the first 2 000-fill page spans 1.4 days, so R3's first-page exit (a full page inside a day) does not fire
    return synth_fills(n, start_ms=T0 - 20 * DAY, step_ms=MINUTE)  # type: ignore[return-value]


def starting_at(first_ms: int, n: int = HL_FILLS_LIMIT) -> list[dict[str, object]]:
    # one fill a minute (was a second): a 2 000-fill page spans 1.4 days, so R3's first-page exit does not fire and the
    # R1 truncation rule is what these tests are about
    return synth_fills(n, start_ms=first_ms, step_ms=MINUTE)  # type: ignore[return-value]


def test_R1_AC7_the_fake_serves_oldest_retrievable_first_and_nothing_older() -> None:
    world = make(recent(20_000))
    rows = world.client.user_fills_by_time(BIG, WINDOW_START, None, priority=Priority.SCORING)
    assert len(rows) == 2_000
    assert rows[0].tid == 10_001 and rows[-1].tid == 12_000  # the 10 000 oldest are gone; oldest retrievable first


def test_R1_AC7_a_wallet_with_20000_fills_is_paged_to_done_but_dropped_as_truncated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make(recent(20_000))
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        run_to_complete(world)
    assert world.backfiller.complete is True  # the others are not held up
    assert world.backfiller.inputs(BIG, T0) is None  # never scored on a partial window as fresh
    assert world.backfiller.inputs(B, T0) is not None
    assert len(world.fills_calls(BIG)) <= 7  # ~5 full pages and a short one, not the 50-page cap
    (rec,) = events(caplog, "backfill_too_active")
    assert attr(rec, "wallet") == BIG
    assert "too_active" in str(attr(rec, "reason")) and "truncat" in str(attr(rec, "reason")).lower()
    assert events(caplog, "backfill_failed") == []


def test_R1_AC7_logged_once_and_not_retried_for_24_hours(caplog: pytest.LogCaptureFixture) -> None:
    world = make(recent(20_000))
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        run_to_complete(world)
        seen = len(world.fills_calls(BIG))
        for _ in range(5):
            world.tick(600)
            world.backfiller.set_candidates([BIG, B])
            assert world.backfiller.step() is False
        world.backfiller.refresh(BIG)
        assert len(world.fills_calls(BIG)) == seen
        world.clock.advance(DAY)  # past the 24 h cooldown
        world.backfiller.set_candidates([BIG, B])
        run_to_complete(world)
        for _ in range(6):
            world.backfiller.step()
    assert len(world.fills_calls(BIG)) > seen  # one new bounded attempt
    assert world.backfiller.inputs(BIG, T0) is None
    assert len(events(caplog, "backfill_too_active")) == 2  # one per drop, not per step


def test_R1_AC7_a_wallet_with_exactly_10000_fills_covering_the_window_start_is_not_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make(starting_at(WINDOW_START))  # complete window: the earliest fill is at window_start
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        run_to_complete(world)
    got = world.backfiller.inputs(BIG, T0)
    # (the fake rate budget lets the clock run on a minute while paging, so the sliding window sheds the first fills)
    assert got is not None and len(got.fills) > HL_FILLS_LIMIT - 200 and got.fills_fetched_ms is not None
    assert events(caplog, "backfill_too_active") == []


def test_R1_AC7_9999_fills_are_not_dropped(caplog: pytest.LogCaptureFixture) -> None:
    world = make(recent(HL_FILLS_LIMIT - 1))
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        run_to_complete(world)
    got = world.backfiller.inputs(BIG, T0)
    assert got is not None and len(got.fills) == HL_FILLS_LIMIT - 1 and got.fills_fetched_ms is not None
    assert events(caplog, "backfill_too_active") == []


def test_R1_AC7_tolerance_boundary_exactly_one_day_after_window_start_is_kept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make(starting_at(WINDOW_START + DAY))
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        run_to_complete(world)
    assert world.backfiller.inputs(BIG, T0) is not None
    assert events(caplog, "backfill_too_active") == []


def test_R1_AC7_tolerance_boundary_one_millisecond_later_is_dropped(caplog: pytest.LogCaptureFixture) -> None:
    world = make(starting_at(WINDOW_START + DAY + 1))
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        run_to_complete(world)
    assert world.backfiller.inputs(BIG, T0) is None
    assert len(events(caplog, "backfill_too_active")) == 1


def test_R1_AC7_tolerance_boundary_one_day_before_with_9999_fills_is_kept() -> None:
    world = make(starting_at(WINDOW_START + 5 * DAY, HL_FILLS_LIMIT - 1))  # late start but under the limit: complete
    run_to_complete(world)
    assert world.backfiller.inputs(BIG, T0) is not None
