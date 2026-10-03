"""R3.AC4 [integration]: hand-off from the screen to the backfill and F5 (research/candidate-ranking.md section 9, V7).

- an OK wallet's screen page IS its backfill page 1: the window-start request is sent once; a non-full page is the whole
  backfill, a full page continues after its last fill (no refetch of page 1);
- only OK wallets receive the rest of the backfill (portfolio, clearinghouseState, userRole) and reach the scorer;
- followed wallets are never screened and never dropped by the screen.

Pinned decisions (the doc leaves them open):
- when every screen of the cycle is done (list exhausted, K OK wallets, or 100 screens) and every OK wallet is
  backfilled, ``PacedInputs.complete`` is True, also when nobody passed (otherwise the manager would stay in
  BACKFILLING and never re-score the followed wallets); the next ``run_cycle`` then applies (STATUS_APPLIED);
- a followed wallet (``manager.restore``) that appears in the leaderboard is backfilled and scored like any other
  candidate whatever its row or its first page say; it gets no ``candidate_screened`` line.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from copytrade.selection.models import STATUS_APPLIED, Follow
from tests.hl.support import T0
from tests.selection.helpers import w
from tests.selection.r3_world import (
    DAY,
    HOUR,
    WINDOW_DAYS,
    R3,
    fill,
    make_r3,
    ok_page,
    page_ok_full,
    page_s1,
    page_s2,
    page_s3,
    page_s4,
    page_s6,
    row,
    screen_lines,
    Tids,
    verdict,
)

OK1, OK2, BAD3, BAD1, BAD2 = w(1), w(2), w(3), w(4), w(5)


def held(r3: R3, wallet: str) -> Any:
    return r3.mw.inputs.inputs(wallet, r3.clock.now_ms())


def test_R3_AC4_a_non_full_screen_page_is_the_complete_backfill(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    page = ok_page(T0)
    r3.serve(OK1, page)
    r3.set_board([row(OK1)])
    r3.cycle()
    r3.drive_until_complete()
    assert len(r3.fills_calls(OK1)) == 1  # the screen was the only fills request
    assert r3.backfilled() == {OK1}  # and the rest of the backfill (portfolio, state, role) followed
    got = held(r3, OK1)
    assert got is not None and len(got.fills) == len(page) == 320
    assert got.fills_fetched_ms is not None


def test_R3_AC4_a_full_screen_page_is_page_1_and_the_backfill_resumes_after_its_last_fill(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    tids = Tids(1_000_000)
    page1 = page_ok_full(T0)  # 2 000 rows, the last one at T0 - 50 d
    last = max(r["time"] for r in page1)
    later = [fill("@107", "B", "0.000001", "2000", last + HOUR * (k + 1), "0.0", tids, direction="Buy") for k in range(300)]
    r3.serve(OK1, [*page1, *later])
    r3.set_board([row(OK1)])
    r3.cycle()
    r3.drive_until_complete()
    calls = r3.fills_calls(OK1)
    assert len(calls) == 2
    assert len(r3.screen_calls(OK1)) == 1  # page 1 was not fetched twice
    assert calls[1].body["startTime"] >= last  # the cursor resumes from the last fill of the screen page
    got = held(r3, OK1)
    assert got is not None and len(got.fills) == 2300 and len({f.tid for f in got.fills}) == 2300


def test_R3_AC4_a_full_page_that_failed_the_screen_gets_no_second_page(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    page = page_s6(T0)  # full, 12 000 fills per window at its rate
    r3.serve(BAD1, page)
    r3.set_board([row(BAD1)])
    r3.cycle(30)
    assert len(r3.fills_calls(BAD1)) == 1
    assert r3.backfilled() == set()


def test_R3_AC4_only_survivors_receive_the_rest_of_the_backfill_and_reach_the_scorer(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    good = ok_page(T0)
    r3.serve(OK1, good)
    r3.serve(OK2, good)
    r3.serve_at(BAD3, page_s3)  # S3
    r3.serve_at(BAD1, page_s1)  # S1: empty
    r3.serve_at(BAD2, lambda t: page_s2(t))  # S2: too active
    r3.set_board([row(w(i), bps_m=10 + i, bps_p=10 + i) for i in (1, 2, 3, 4, 5)])
    r3.cycle()
    r3.drive_until_complete()
    assert r3.backfilled() == {OK1, OK2}
    assert held(r3, OK1) is not None and held(r3, OK2) is not None
    for bad in (BAD1, BAD2, BAD3):
        assert held(r3, bad) is None  # nothing for the scorer to rank
    r3.advance_h(1)
    report = r3.mw.manager.run_cycle(p95_latency_s=None)
    assert report.status == STATUS_APPLIED  # scored the survivors only
    assert not ({BAD1, BAD2, BAD3} & set(report.followed))


def test_R3_AC4_the_pass_completes_when_nobody_passed_and_the_next_cycle_applies(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(BAD1, page_s1)
    r3.serve_at(BAD2, lambda t: page_s2(t))
    r3.set_board([row(BAD1, bps_m=20, bps_p=20), row(BAD2, bps_m=30, bps_p=30)])
    r3.cycle()
    r3.drive_until_complete(max_ticks=200)
    assert r3.backfilled() == set()  # nobody passed: nobody gets the rest of the backfill
    r3.advance_h(1)
    report = r3.mw.manager.run_cycle(p95_latency_s=None)
    assert report.status == STATUS_APPLIED  # not stuck in backfilling with nothing left to fetch


# --- followed wallets -----------------------------------------------------------------------------------------------


def follow(r3: R3, wallet: str) -> None:
    r3.mw.manager.restore(
        {wallet: Follow(followed_at_ms=r3.clock.now_ms(), drop_streak=0)}, subscribed=[wallet], paused=[]
    )
    assert wallet in r3.mw.manager.followed


def test_R3_AC4_a_followed_wallet_is_not_screened_and_not_dropped_by_a_screen_it_would_fail(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    followed, control = w(1), w(2)
    r3 = make_r3(tmp_path)
    for wallet in (followed, control):
        r3.serve_at(wallet, lambda t: page_s4(t, 225))  # a maker share of 0.703: S4 would reject it
    r3.set_board([row(followed, bps_m=40, bps_p=40), row(control, bps_m=30, bps_p=30)])
    follow(r3, followed)
    with caplog.at_level(logging.INFO):
        r3.cycle()
        r3.drive_until_complete()
    assert screen_lines(caplog, followed) == []  # never screened
    assert held(r3, followed) is not None and followed in r3.backfilled()  # fetched in full, scored like the rest
    assert verdict(caplog, control)["outcome"] == "rejected"  # the same page, not followed: rejected
    assert held(r3, control) is None and control not in r3.backfilled()
    r3.advance_h(1)
    r3.mw.manager.run_cycle(p95_latency_s=None)
    assert held(r3, followed) is not None


def test_R3_AC4_a_followed_wallet_whose_row_fails_stage_1_is_still_fetched_and_scored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    followed = w(1)
    r3 = make_r3(tmp_path)
    r3.serve(followed, ok_page(T0))
    other = w(3)
    r3.serve(other, ok_page(T0))
    # a losing month: stage 1 would not rank either row; only the followed one is fetched anyway
    r3.set_board([row(followed, pnl_month="-100"), row(other, pnl_month="-100"), row(w(2))])
    follow(r3, followed)
    with caplog.at_level(logging.INFO):
        r3.cycle()
        r3.drive_until_complete()
    assert r3.fills_calls(other) == []
    assert screen_lines(caplog, followed) == []
    assert held(r3, followed) is not None  # followed wallets are always re-scored whatever the prefilter says


def test_R3_AC4_a_followed_wallet_is_never_skipped_by_a_cooldown(tmp_path: Path) -> None:
    followed = w(1)
    control = w(2)
    r3 = make_r3(tmp_path)
    r3.serve(followed, [])  # an empty page would cool a screened wallet for 168 h
    r3.serve(control, [])
    r3.set_board([row(followed, bps_m=40, bps_p=40), row(control, bps_m=30, bps_p=30)])
    follow(r3, followed)
    r3.cycle()
    r3.drive_until_complete()
    r3.advance_h(1)
    r3.cycle(30)
    assert len(r3.fills_calls(control)) == 1  # screened once, cooling down for 168 h
    assert held(r3, followed) is not None  # still there, still refreshed
    assert len(r3.fills_calls(followed)) >= 2


def test_R3_AC4_the_screen_window_start_is_the_scoring_window(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    r3.serve(OK1, ok_page(T0))
    r3.set_board([row(OK1)])
    r3.cycle()
    r3.drive_until_complete()
    calls = r3.screen_calls(OK1)
    assert len(calls) == 1
    call = calls[0]
    assert call.body["startTime"] == call.t_ms - WINDOW_DAYS * DAY
