"""R3.AC5 [integration]: early exits in the backfill (research/candidate-ranking.md section 2, EX1-EX3; section 9, V5).

The real ``Backfiller`` over the real REST client and rate budget, with a loopback fake Hyperliquid (``r1_world``):
- EX2: zero fills in the window = the wallet is dropped after ONE request with a 168 h cooldown, the row volume is logged
  (manager flow, where the leaderboard row is known);
- EX1: a FULL first page (2 000 rows) whose first and last fill are less than 86 400 000 ms apart = too active at once:
  one request (not five or fifty), the existing ``backfill_too_active`` record with reason ``too_active_first_page``
  and ``pages=1``, R1's 24 h cooldown.
EX3 (R1: more than 50 pages, or exactly 10 000 fills with the first one later than window start + 1 day) is unchanged.

Pinned decisions: the empty-wallet record is event ``backfill_empty`` (INFO or WARNING) with wallet, reason
``backfill_empty`` and, when the row is known, ``vlm_week`` and ``vlm_month`` as ``key=value`` text in the message.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.hl.support import T0
from tests.selection.helpers import w
from tests.selection.r1_logs import attr, events
from tests.selection.r1_world import DAY, HL_FILLS_LIMIT, make_world, synth_fills
from tests.selection.r3_world import full_short_page, make_r3, page_s1, page_s2, row, tokens

E, B, HEAVY = w(1), w(2), w(3)
HOUR = 3_600_000


def one(recs: list[Any]) -> Any:
    assert len(recs) == 1, f"expected exactly one record, got {len(recs)}"
    return recs[0]


def run_to_complete(world, limit: int = 30) -> None:  # type: ignore[no-untyped-def]
    for _ in range(limit):
        if world.backfiller.complete:
            return
        world.backfiller.step()
    raise AssertionError("the backfill did not complete")


def per_wallet_other_calls(world, wallet: str) -> list[Any]:  # type: ignore[no-untyped-def]
    return [c for c in world.http.calls if c.body.get("user") == wallet and c.body["type"] != "userFillsByTime"]


# --- EX2: zero fills --------------------------------------------------------------------------------------------------


def test_R3_AC5_a_wallet_with_no_fill_in_the_window_is_dropped_after_one_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make_world()
    world.hl.set_fills(B, synth_fills(5, tid0=500_000))  # E has nothing at all
    world.backfiller.set_candidates([E, B])
    with caplog.at_level(logging.INFO):
        run_to_complete(world)
    assert world.backfiller.complete is True  # the pass does not wait for it
    assert len(world.fills_calls(E)) == 1
    assert world.backfiller.inputs(E, T0) is None  # nothing for the scorer
    assert per_wallet_other_calls(world, E) == []  # no portfolio, state or role request for an empty wallet
    assert world.backfiller.inputs(B, T0) is not None


def test_R3_AC5_fills_older_than_the_window_count_as_no_fill(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.set_fills(E, synth_fills(5, start_ms=T0 - 200 * DAY))  # all before the 180 day window
    world.backfiller.set_candidates([E])
    run_to_complete(world)
    assert world.backfiller.inputs(E, T0) is None


def test_R3_AC5_one_fill_is_not_empty(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.set_fills(E, synth_fills(1))
    world.backfiller.set_candidates([E])
    run_to_complete(world)
    got = world.backfiller.inputs(E, T0)
    assert got is not None and len(got.fills) == 1


def test_R3_AC5_an_empty_wallet_is_logged_once_with_its_reason(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.backfiller.set_candidates([E])
    with caplog.at_level(logging.INFO):
        run_to_complete(world)
        for _ in range(5):
            world.backfiller.set_candidates([E])
            world.backfiller.step()
    recs = events(caplog, "backfill_empty")
    assert len(recs) == 1
    assert attr(recs[0], "wallet") == E and attr(recs[0], "reason") == "backfill_empty"
    assert tokens(recs[0])["wallet"] == E and tokens(recs[0])["reason"] == "backfill_empty"
    assert recs[0].levelno >= logging.INFO


def test_R3_AC5_the_empty_cooldown_is_168_hours(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.backfiller.set_candidates([E])
    run_to_complete(world)
    assert len(world.fills_calls(E)) == 1
    world.clock.advance(168 * HOUR - 60_000)  # 167 h 59 min after it was dropped
    world.backfiller.set_candidates([E])
    assert world.backfiller.step() is False
    assert len(world.fills_calls(E)) == 1
    world.clock.advance(2 * 60_000)  # now past 168 h: exactly one new attempt
    world.backfiller.set_candidates([E])
    while world.backfiller.step():
        pass
    assert len(world.fills_calls(E)) == 2


def test_R3_AC5_an_empty_wallet_that_the_row_called_active_logs_the_row_volume(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(E, page_s1)
    r3.set_board([row(E, vlm_week="123456", vlm_month="987654")])
    with caplog.at_level(logging.INFO):
        r3.cycle(20)
    rec = one(events(caplog, "backfill_empty"))
    toks = tokens(rec)
    assert Decimal(toks["vlm_week"]) == Decimal("123456")  # the row said it traded; its fills say it did not
    assert Decimal(toks["vlm_month"]) == Decimal("987654")
    assert len(r3.fills_calls(E)) == 1
    # a 168 h cooldown, in the manager flow too
    r3.advance_h(167)
    r3.cycle(20)
    assert len(r3.fills_calls(E)) == 1


# --- EX1: a full first page inside one day -----------------------------------------------------------------------------


def test_R3_AC5_a_full_first_page_inside_a_day_is_too_active_at_once_one_request_not_five(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make_world()
    world.hl.set_fills(HEAVY, synth_fills(12_000))  # 12 000 fills 50 ms apart: the first page spans 100 s
    world.hl.set_fills(B, synth_fills(5, tid0=500_000))
    world.backfiller.set_candidates([HEAVY, B])
    with caplog.at_level(logging.INFO):
        run_to_complete(world)
    assert len(world.fills_calls(HEAVY)) == 1  # not 5 pages (not 50)
    assert world.backfiller.inputs(HEAVY, T0) is None
    assert per_wallet_other_calls(world, HEAVY) == []
    assert world.backfiller.complete is True and world.backfiller.inputs(B, T0) is not None
    rec = one(events(caplog, "backfill_too_active"))  # the existing record, once
    assert attr(rec, "wallet") == HEAVY
    assert attr(rec, "reason") == "too_active_first_page"
    assert attr(rec, "pages") == 1
    assert tokens(rec)["reason"] == "too_active_first_page"


def test_R3_AC5_just_under_a_day_is_too_active_exactly_a_day_is_not() -> None:
    first = T0 - 3 * DAY
    world = make_world()
    world.hl.set_fills(HEAVY, full_short_page(first, DAY - 1))
    world.hl.set_fills(B, full_short_page(first, DAY))
    world.backfiller.set_candidates([HEAVY, B])
    run_to_complete(world)
    assert world.backfiller.inputs(HEAVY, T0) is None
    assert len(world.fills_calls(HEAVY)) == 1
    got = world.backfiller.inputs(B, T0)  # a page spanning a full day is not "at once": it continues as before
    assert got is not None and len(got.fills) == 2_000
    assert len(world.fills_calls(B)) >= 2


def test_R3_AC5_the_too_active_cooldown_is_one_day() -> None:
    world = make_world()
    world.hl.set_fills(HEAVY, synth_fills(12_000))
    world.backfiller.set_candidates([HEAVY])
    run_to_complete(world)
    assert len(world.fills_calls(HEAVY)) == 1
    world.clock.advance(DAY - 60_000)
    world.backfiller.set_candidates([HEAVY])
    assert world.backfiller.step() is False
    assert len(world.fills_calls(HEAVY)) == 1
    world.clock.advance(2 * 60_000)
    world.backfiller.set_candidates([HEAVY])
    while world.backfiller.step():
        pass
    assert len(world.fills_calls(HEAVY)) == 2  # one new attempt, and it costs one request again


def test_R3_AC5_a_first_page_that_is_not_full_is_never_too_active_at_once() -> None:
    world = make_world()
    world.hl.set_fills(HEAVY, synth_fills(1_999))  # 1 999 fills inside 100 s: busy, but the page is not full
    world.backfiller.set_candidates([HEAVY])
    run_to_complete(world)
    got = world.backfiller.inputs(HEAVY, T0)
    assert got is not None and len(got.fills) == 1_999


def test_R3_AC5_only_the_first_page_is_judged_a_later_full_page_inside_a_day_goes_on() -> None:
    world = make_world()
    page1 = synth_fills(2_000, start_ms=T0 - 170 * DAY, step_ms=HOUR)  # first page spans 83 days
    page2 = synth_fills(2_000, start_ms=T0 - 60 * DAY, step_ms=50, tid0=10_000)  # a full burst inside 100 s
    world.hl.set_fills(HEAVY, [*page1, *page2])
    world.backfiller.set_candidates([HEAVY])
    run_to_complete(world, 40)
    got = world.backfiller.inputs(HEAVY, T0)
    assert got is not None and len(got.fills) == 4_000


def test_R3_AC5_the_truncation_rule_of_R1_still_catches_a_wallet_whose_first_page_spans_more_than_a_day(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make_world(fills_limit=HL_FILLS_LIMIT)
    # 12 000 fills a minute apart: the API only keeps the latest 10 000, whose first page spans 33 hours
    world.hl.set_fills(HEAVY, synth_fills(12_000, start_ms=T0 - 9 * DAY, step_ms=60_000))
    world.backfiller.set_candidates([HEAVY])
    with caplog.at_level(logging.WARNING):
        run_to_complete(world)
    assert world.backfiller.inputs(HEAVY, T0) is None
    rec = one(events(caplog, "backfill_too_active"))
    assert attr(rec, "reason") == "too_active_truncated"
    assert 5 <= len(world.fills_calls(HEAVY)) <= 6  # the whole retrievable history was paged (no early exit)


# --- the same exits in the manager flow (stage 2 reports them as the screen's S1 / S2 outcomes) ---------------------


def test_R3_AC5_a_too_active_candidate_in_the_manager_flow_costs_one_request_and_one_record(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(HEAVY, lambda t: page_s2(t))
    r3.set_board([row(HEAVY)])
    with caplog.at_level(logging.INFO):
        r3.cycle(30)
    assert len(r3.fills_calls(HEAVY)) == 1
    rec = one(events(caplog, "backfill_too_active"))
    assert attr(rec, "reason") == "too_active_first_page" and attr(rec, "pages") == 1
    r3.advance_h(23)
    r3.cycle(20)
    assert len(r3.fills_calls(HEAVY)) == 1  # 24 h cooldown
    r3.advance_h(2)
    r3.cycle(20)
    assert len(r3.fills_calls(HEAVY)) == 2
