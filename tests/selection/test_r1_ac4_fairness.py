"""R1.AC4 [integration]: one heavy wallet cannot starve the others.

The PO's wiring (``runner/wiring.py``) gives the scoring REST client a sleeper that never sleeps: a request that does not
fit the rate budget raises ``HlBudgetError`` at once, and the paced backfill (one ``step`` every 10 s) tries again later.
The scoring share is 450 weight a minute; a full 2 000-fill page weighs 120. Today a wallet of more than about three
pages fails halfway on the budget every time and its pages are thrown away (all or nothing), so it restarts from page 1
for ever and keeps eating the budget the light wallets need.

Pinned: (a) one ``step`` fetches at most 3 fill pages of one wallet (what fits in one minute of the share); (b) the
heavy wallet's progress is kept across steps (resumable: it completes, with every fill and no duplicate, in about its own
page count of requests, never restarting from the window start); (c) light wallets complete in the first steps whichever
order they were queued in; (d) the same bound holds with the blocking (sleeping) client.
"""

from __future__ import annotations

import pytest

from tests.hl.support import T0, status
from tests.selection.helpers import w
from tests.selection.r1_world import DAY, World, make_world, synth_fills

HEAVY, B, C = w(1), w(2), w(3)
HEAVY_FILLS = 24_000  # 12 full pages, under the 50-page cap
MAX_PAGES_PER_STEP = 3


def setup(*, fail_fast: bool) -> World:
    world = make_world(fail_fast=fail_fast)
    world.hl.set_fills(HEAVY, synth_fills(HEAVY_FILLS))
    world.hl.set_fills(B, synth_fills(5, tid0=500_000))
    world.hl.set_fills(C, synth_fills(5, tid0=600_000))
    world.backfiller.set_candidates([HEAVY, B, C])  # the heavy wallet is first in the queue
    return world


def tick(world: World) -> int:
    """One paced slice: a step, then 10 s. Returns the fill pages of the HEAVY wallet requested during the step."""
    before = len(world.fills_calls(HEAVY))
    world.backfiller.step()
    pages = len(world.fills_calls(HEAVY)) - before
    world.tick(10)
    return pages


@pytest.mark.parametrize("fail_fast", [True, False])
def test_R1_AC4_one_step_requests_a_bounded_number_of_pages_of_one_wallet(fail_fast: bool) -> None:
    world = setup(fail_fast=fail_fast)
    pages = [tick(world) for _ in range(40)]
    assert max(pages) <= MAX_PAGES_PER_STEP


def test_R1_AC4_the_light_wallets_complete_in_the_first_steps_behind_a_heavy_one() -> None:
    world = setup(fail_fast=True)
    for _ in range(3):  # three steps: the heavy wallet's share, then B, then C
        tick(world)
    assert world.backfiller.inputs(B, T0) is not None
    assert world.backfiller.inputs(C, T0) is not None
    assert world.backfiller.complete is False  # the heavy wallet is not done yet, so the backfill is not either


def test_R1_AC4_the_heavy_wallet_completes_across_steps_with_every_fill_and_no_duplicate() -> None:
    world = setup(fail_fast=True)
    for _ in range(400):
        tick(world)
        if world.backfiller.complete:
            break
    assert world.backfiller.complete is True
    got = world.backfiller.inputs(HEAVY, T0)
    assert got is not None and got.fills_fetched_ms is not None
    tids = [f.tid for f in got.fills]
    assert len(tids) == len(set(tids)) == HEAVY_FILLS


def test_R1_AC4_progress_is_kept_the_heavy_wallet_never_restarts_from_the_window_start() -> None:
    world = setup(fail_fast=True)
    for _ in range(400):
        tick(world)
        if world.backfiller.complete:
            break
    calls = world.fills_calls(HEAVY)
    assert len(calls) <= 12 + 4  # its 12 pages, plus a little slack for the repeated cursor fill and a final empty page
    assert sum(1 for c in calls if c.body["startTime"] < T0 - 100 * DAY) == 1  # one start at the window, never again


def test_R1_AC4_a_server_error_in_the_middle_resumes_where_it_stopped() -> None:
    world = setup(fail_fast=False)
    state = {"n": 0}

    def flaky(call):  # type: ignore[no-untyped-def]
        state["n"] += 1
        return status(500) if state["n"] == 6 else None  # one transient 500 on the sixth fills request

    world.hl.rules[(HEAVY, "userFillsByTime")] = flaky
    for _ in range(60):
        tick(world)
        world.tick(60)
        if world.backfiller.complete:
            break
    assert world.backfiller.complete is True
    calls = world.fills_calls(HEAVY)
    assert sum(1 for c in calls if c.body["startTime"] < T0 - 100 * DAY) == 1  # not restarted from the window start
    assert len(calls) <= 12 + 4 + 1
    got = world.backfiller.inputs(HEAVY, T0)
    assert got is not None and len({f.tid for f in got.fills}) == HEAVY_FILLS
