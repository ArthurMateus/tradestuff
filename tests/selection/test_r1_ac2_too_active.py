"""R1.AC2 [integration]: a wallet too active to copy is dropped, not retried forever, and never blocks the manager.

Pinned design (no new config key): "too active" = the 50-page x 2 000-fill cap is reached inside the scoring window
without reaching the present. The wallet is logged ONCE (event ``backfill_too_active``: ``wallet``, ``reason`` ==
``"too_active"``, ``pages``), removed from the candidates (the backfill completes without it), and neither
``set_candidates`` nor ``refresh`` fetches it again until one day (24 h of the injected clock, the day constant the
backfiller already has) after it was marked; then ONE new attempt, which marks it again if it is still too active.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from copytrade.selection.models import STATUS_APPLIED, STATUS_BACKFILLING
from tests.hl.support import T0
from tests.selection.helpers import w
from tests.selection.r1_logs import BACKFILL_LOGGER, attr, events
from tests.selection.r1_world import DAY, board_body, make_manager_world, make_world, synth_fills

HEAVY, B, C = w(1), w(2), w(3)
TOO_MANY = 101_000  # > 50 pages x 2 000
HOUR = 3_600_000


def setup_world(**kw: object):  # type: ignore[no-untyped-def]
    world = make_world(**kw)
    world.hl.set_fills(HEAVY, synth_fills(TOO_MANY))
    world.hl.set_fills(B, synth_fills(5, tid0=500_000))
    world.hl.set_fills(C, synth_fills(5, tid0=600_000))
    return world


def run_to_complete(world, limit: int = 30) -> None:  # type: ignore[no-untyped-def]
    for _ in range(limit):
        if world.backfiller.complete:
            return
        world.backfiller.step()
    raise AssertionError("the backfill did not complete")


def test_R1_AC2_a_wallet_over_the_page_cap_is_dropped_and_the_others_complete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = setup_world()
    world.backfiller.set_candidates([HEAVY, B, C])
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        run_to_complete(world)
    assert world.backfiller.complete is True  # not stuck waiting for the heavy wallet
    assert world.backfiller.inputs(HEAVY, T0) is None  # dropped, nothing stale kept for the scorer to rank
    assert world.backfiller.inputs(B, T0) is not None and world.backfiller.inputs(C, T0) is not None
    assert len(world.fills_calls(HEAVY)) <= 50  # the cap, once
    assert events(caplog, "backfill_failed") == []  # a decision, not a failure


def test_R1_AC2_it_is_logged_once_with_the_reason(caplog: pytest.LogCaptureFixture) -> None:
    world = setup_world()
    world.backfiller.set_candidates([HEAVY, B, C])
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        run_to_complete(world)
        for _ in range(5):
            world.backfiller.set_candidates([HEAVY, B, C])
            world.backfiller.step()
    (rec,) = events(caplog, "backfill_too_active")
    assert attr(rec, "wallet") == HEAVY
    assert attr(rec, "reason") == "too_active"
    assert attr(rec, "pages") == 50


def test_R1_AC2_it_is_not_retried_in_later_cycles(caplog: pytest.LogCaptureFixture) -> None:
    world = setup_world()
    world.backfiller.set_candidates([HEAVY, B, C])
    run_to_complete(world)
    seen = len(world.fills_calls(HEAVY))
    for _ in range(5):  # five more cycles of the manager
        world.tick(600)
        world.backfiller.set_candidates([HEAVY, B, C])
        assert world.backfiller.step() is False  # nothing left to fetch: the heavy wallet is not pending
        assert world.backfiller.complete is True
    assert len(world.fills_calls(HEAVY)) == seen


def test_R1_AC2_a_refresh_inside_the_cooldown_does_not_refetch_it() -> None:
    world = setup_world()
    world.backfiller.set_candidates([HEAVY, B, C])
    run_to_complete(world)
    seen = len(world.fills_calls(HEAVY))
    world.tick(HOUR // 1000)
    try:
        world.backfiller.refresh(HEAVY)
    except Exception:  # whether it raises or returns is not pinned, only that nothing is sent
        pass
    assert len(world.fills_calls(HEAVY)) == seen


def test_R1_AC2_the_cooldown_is_one_day_then_one_new_attempt(caplog: pytest.LogCaptureFixture) -> None:
    world = setup_world()
    world.backfiller.set_candidates([HEAVY, B, C])
    run_to_complete(world)
    first = len(world.fills_calls(HEAVY))
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        world.clock.advance(DAY - 60_000)  # 23 h 59 min after it was marked (marking happened before this)
        world.backfiller.set_candidates([HEAVY, B, C])
        while world.backfiller.step():
            pass
        assert len(world.fills_calls(HEAVY)) == first  # still cooling down
        world.clock.advance(DAY)  # now well past one day
        world.backfiller.set_candidates([HEAVY, B, C])
        for _ in range(30):
            if not world.backfiller.step():
                break
    second = len(world.fills_calls(HEAVY))
    assert 0 < second - first <= 50  # exactly one new bounded attempt
    assert len(events(caplog, "backfill_too_active")) == 1  # marked again, logged again
    world.clock.advance(HOUR)
    world.backfiller.set_candidates([HEAVY, B, C])
    assert world.backfiller.step() is False
    assert len(world.fills_calls(HEAVY)) == second  # and it cools down again


def test_R1_AC2_a_wallet_just_inside_the_cap_is_not_dropped(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.set_fills(HEAVY, synth_fills(99_000))  # 50 pages x 2 000 minus the repeated cursor fill, with margin
    world.backfiller.set_candidates([HEAVY])
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        run_to_complete(world, 10)
    got = world.backfiller.inputs(HEAVY, T0)
    assert got is not None and len(got.fills) == 99_000 and got.fills_fetched_ms is not None
    assert events(caplog, "backfill_too_active") == []


def test_R1_AC2_a_dropped_wallet_does_not_stop_the_manager_and_is_never_followed(tmp_path: Path) -> None:
    mw = make_manager_world(tmp_path)  # the PO's wiring: fail-fast scoring client, one 10 s slice at a time
    world = mw.world
    world.hl.set_fills(HEAVY, synth_fills(TOO_MANY))
    mw.board.outcome = board_body([(HEAVY, "50000.0"), (B, "50000.0"), (C, "50000.0")])
    first = mw.manager.run_cycle(p95_latency_s=None)
    assert first.status == STATUS_BACKFILLING
    mw.work_until_complete(max_ticks=600)  # completes without the heavy wallet (it cannot be finished)
    seen = len(world.fills_calls(HEAVY))
    assert seen <= 50
    for _ in range(3):
        report = mw.manager.run_cycle(p95_latency_s=None)
        assert report.status == STATUS_APPLIED  # the manager is not stuck in BACKFILLING
        assert HEAVY not in report.followed
        for _ in range(60):  # the paced refresh rotates through every candidate
            mw.inputs.work()
            world.tick(10)
        world.tick(600)
    assert len(world.fills_calls(HEAVY)) == seen  # not one more request for it
