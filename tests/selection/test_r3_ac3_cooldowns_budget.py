"""R3.AC3 [integration]: cooldowns and the screen budget (research/candidate-ranking.md section 9, V5 and V6).

Cooldown lengths are CODE CONSTANTS (PO decision 2026-10-03): S1 fail 168 h, S2 fail 24 h, any of S3-S9 72 h, keyed by
the lower-case wallet. Observed over HTTP: a cooled wallet gets no request of any kind until its time is up (checked one
hour before and one hour after), then is screened again and judged on its new page.

Budget: a cycle spends at most 100 screens (V6) and stops when ``scoring.candidates_k`` wallets screened OK; every screen
goes through the SCORING share of the REST budget (450 of 900 weight a minute) and waits out the wait that a
``HlBudgetError`` reports: after a refusal that says "would wait W s" nothing is sent before W s have passed, and a
refused screen is not a rejection (the wallet is not cooled, it is simply tried again).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.selection.helpers import w
from tests.selection.r3_world import (
    FAILING_PAGES,
    HOUR,
    K,
    R3,
    good_trips,
    make_r3,
    ok_page,
    page_s1,
    page_s2,
    page_s3,
    row,
    screen_lines,
    verdict,
)

COOLDOWNS: list[tuple[str, Callable[[int], list[dict[str, Any]]], int]] = [
    ("S1", page_s1, 168),
    ("S2", lambda t: page_s2(t), 24),
    *[(rule, page, 72) for rule, page in FAILING_PAGES.items()],
]


def set_clock(r3: R3, target_ms: int) -> None:
    assert target_ms >= r3.clock.now_ms()
    r3.clock.advance(target_ms - r3.clock.now_ms())


@pytest.mark.parametrize(("rule", "build", "hours"), COOLDOWNS, ids=[c[0] for c in COOLDOWNS])
def test_R3_AC3_a_rejected_wallet_is_not_asked_again_until_its_cooldown_is_over(
    tmp_path: Path, rule: str, build: Callable[[int], list[dict[str, Any]]], hours: int
) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(w(1), build)
    r3.set_board([row(w(1))])
    r3.cycle(15)
    calls = r3.fills_calls(w(1))
    assert len(calls) == 1  # one screen, and a rejected wallet gets nothing more
    assert r3.backfilled() == set()
    screened_ms = calls[0].t_ms

    set_clock(r3, screened_ms + (hours - 1) * HOUR)
    r3.cycle(15)
    assert len(r3.fills_calls(w(1))) == 1, f"{rule}: asked again before {hours} h were over"

    set_clock(r3, screened_ms + (hours + 1) * HOUR)
    r3.cycle(15)
    assert len(r3.fills_calls(w(1))) == 2, f"{rule}: not screened again after {hours} h"


def test_R3_AC3_cooldowns_are_per_wallet(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(w(1), page_s1)  # 168 h
    r3.serve_at(w(2), lambda t: page_s2(t))  # 24 h
    r3.serve_at(w(3), page_s3)  # 72 h
    r3.set_board([row(w(i), bps_m=10 + i, bps_p=10 + i) for i in (1, 2, 3)])
    r3.cycle(30)
    base = r3.clock.now_ms()
    set_clock(r3, base + 25 * HOUR)
    r3.cycle(30)
    counts = {wallet: len(r3.fills_calls(wallet)) for wallet in (w(1), w(2), w(3))}
    assert counts == {w(1): 1, w(2): 2, w(3): 1}
    set_clock(r3, base + 73 * HOUR)
    r3.cycle(30)
    counts = {wallet: len(r3.fills_calls(wallet)) for wallet in (w(1), w(2), w(3))}
    assert counts[w(1)] == 1 and counts[w(3)] == 2


def test_R3_AC3_the_cooldown_key_is_the_lower_case_address(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    lower = "0x" + "ab" * 20
    upper = "0x" + "AB" * 20
    r3 = make_r3(tmp_path)
    r3.serve_at(lower, page_s1)
    r3.set_board([row(upper)])
    with caplog.at_level(logging.INFO):
        r3.cycle(15)
        assert len(screen_lines(caplog, lower)) == 1
        set_clock(r3, r3.clock.now_ms() + 2 * HOUR)
        r3.set_board([row(lower)])  # the same wallet, served in lower case this time
        r3.cycle(15)
        assert len(screen_lines(caplog, lower)) == 1  # still cooling down: not screened again
        set_clock(r3, r3.clock.now_ms() + 170 * HOUR)
        r3.cycle(15)
        assert len(screen_lines(caplog, lower)) == 2  # and screened again once the 168 h are over


def test_R3_AC3_after_the_cooldown_the_wallet_is_judged_again_on_its_new_page(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(w(1), page_s3)
    r3.set_board([row(w(1))])
    with caplog.at_level(logging.INFO):
        r3.cycle(15)
        base = r3.clock.now_ms()
        r3.serve_at(w(1), lambda t: good_trips(t))  # it changed its ways
        set_clock(r3, base + 73 * HOUR)
        r3.cycle(30)
    lines = screen_lines(caplog, w(1))
    assert len(lines) == 2
    first, second = lines
    assert first["outcome"] == "rejected" and second["outcome"] == "ok"
    assert w(1) in r3.backfilled()


def test_R3_AC3_a_screen_that_could_not_be_fetched_starts_no_cooldown(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from tests.hl.support import status

    r3 = make_r3(tmp_path)
    r3.serve_at(w(1), page_s1)
    healthy = r3.world.hl.rules[(w(1), "userFillsByTime")]
    outage_until = r3.clock.now_ms() + 60_000
    r3.world.hl.rules[(w(1), "userFillsByTime")] = lambda call: status(503) if call.t_ms < outage_until else healthy(call)
    r3.set_board([row(w(1))])
    with caplog.at_level(logging.INFO):
        r3.cycle(12)  # 120 s: a minute of 503s, then the retry after the error cooldown goes through
    assert len(r3.fills_calls(w(1))) >= 2  # tried again within minutes, not after 24, 72 or 168 h
    v = verdict(caplog, w(1))  # judged once, on the good page, and not before
    assert v["outcome"] == "rejected" and "S1" in v["failed"]


# --- at most 100 screens per cycle ------------------------------------------------------------------------------


def ranked_rows(n: int) -> list[dict[str, Any]]:
    """``n`` rows with the same K1 (50) and a higher all-time pnl for a higher number: rank order is n, n-1, ..., 1."""
    return [row(w(i), vlm_prior=1_600_000 + i * 1_000) for i in range(1, n + 1)]


def test_R3_AC3_a_cycle_makes_at_most_100_screens_and_the_rest_wait_for_the_next_cycle(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    r3.set_board(ranked_rows(150))
    r3.cycle(250)  # nobody has a fill: every screen is a cheap rejection
    assert r3.screened_order() == [w(i) for i in range(150, 50, -1)]  # exactly the best 100, in rank order
    assert len(r3.fills_calls()) == 100

    r3.advance_h(1)  # the first 100 are cooled for 168 h: the next cycle goes on down the list
    r3.cycle(250)
    assert r3.screened_order() == [w(i) for i in range(150, 0, -1)]
    assert len(r3.fills_calls()) == 150

    r3.advance_h(1)  # all 150 are cooling down: nothing to screen
    r3.cycle(60)
    assert len(r3.fills_calls()) == 150


@pytest.mark.parametrize("rejects_first", [0, 5], ids=["all OK", "five rejected first"])
def test_R3_AC3_the_cycle_stops_screening_at_candidates_k_ok_wallets(tmp_path: Path, rejects_first: int) -> None:
    r3 = make_r3(tmp_path)
    page = ok_page()
    n = 60
    for i in range(1, n + 1):
        rank = n - i  # w(n) is ranked first
        r3.serve(w(i), [] if rank < rejects_first else page)
    r3.set_board(ranked_rows(n))
    r3.cycle()
    r3.drive_until_complete(max_ticks=1500)
    expected_last = n - K - rejects_first  # the screens that end with the K-th OK wallet
    assert r3.screened_order() == [w(i) for i in range(n, expected_last, -1)]
    assert len(r3.screened_order()) == K + rejects_first
    assert len(r3.backfilled()) == K  # only the OK wallets went on to the full backfill


# --- the scoring budget -----------------------------------------------------------------------------------------


def _heavy_world(tmp_path: Path, n: int = 24) -> R3:
    """``n`` candidates whose first page is full and far too active (S2): each screen weighs 120."""
    r3 = make_r3(tmp_path)
    for i in range(1, n + 1):
        r3.serve_at(w(i), lambda t: page_s2(t))
    r3.set_board(ranked_rows(n))
    return r3


def test_R3_AC3_screens_never_exceed_the_scoring_share_of_the_budget(tmp_path: Path) -> None:
    r3 = _heavy_world(tmp_path)
    r3.cycle(150)
    calls = r3.fills_calls()
    assert len(calls) == 24  # all screened (one request each), nobody backfilled
    assert r3.backfilled() == set()
    weighted = [(c.t_ms, r3.weight_of(c, rows)) for c, (_t, _w, rows) in zip(calls, r3.served, strict=True)]
    share = int(r3.world.cfg["hl.rest_weight_budget_per_min"] * r3.world.cfg["hl.scoring_weight_share"])
    assert share == 450
    for t, _weight in weighted:
        in_window = sum(weight for at, weight in weighted if t - 60_000 < at <= t)
        # the base weight is reserved first and the rows' extra weight is charged after the answer (at most 100 over)
        assert in_window <= share + 100, f"{in_window} weight in the minute ending at {t}"


def test_R3_AC3_a_refusal_that_says_would_wait_is_honoured(tmp_path: Path) -> None:
    r3 = _heavy_world(tmp_path)
    r3.cycle(150)
    assert r3.refusals, "the scenario must hit the budget"
    attempts = sorted([t for t, _wait in r3.refusals] + [c.t_ms for c in r3.world.http.calls])
    for t, wait_s in r3.refusals:
        later = [a for a in attempts if a > t]
        assert not later or min(later) >= t + round(wait_s * 1000), (
            f"a refusal at {t} said it would wait {wait_s} s but the next attempt came {min(later) - t} ms later"
        )


def test_R3_AC3_a_refused_screen_is_not_a_rejection_the_wallet_is_tried_again(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = _heavy_world(tmp_path)
    with caplog.at_level(logging.INFO):
        r3.cycle(150)
    assert r3.refusals
    lines = screen_lines(caplog)
    assert sorted(line["wallet"] for line in lines) == sorted(w(i) for i in range(1, 25))  # each judged once
    assert {line["outcome"] for line in lines} == {"rejected"}
    for i in range(1, 25):
        assert "S2" in verdict(caplog, w(i))["failed"]
