"""R3.AC6 [integration]: rotation of ineligible candidates and a stable list (research/candidate-ranking.md RO1, L3).

- RO1: a candidate that is fully backfilled, not followed and INELIGIBLE in 3 consecutive scored cycles gets a 72 h
  cooldown, so the ``scoring.candidates_k`` slots go on down the ranked list instead of staying on wallets that keep
  failing the gates (the K1 order barely moves and G7 is strict);
- L3 stickiness: last cycle's candidates that still pass P1-P8 and rank within the top 2 x K keep their slot and are not
  screened again; free slots go to the best-ranked others. A better-ranked newcomer does not push anybody out (no thrash).

Pinned decisions (the doc leaves them open):
- only SCORED cycles count (``run_cycle`` that reached the scorer, or ``apply_cycle``): a cycle that ended in
  BACKFILLING scored nobody and counts for nobody; one eligible cycle resets the streak;
- a cooldown that starts in a cycle takes effect for the candidate list of the NEXT ``run_cycle``;
- a rotated wallet is neither refreshed nor screened until its 72 h are over, then it competes again.
In these scenarios the real F5 scorer finds every crafted wallet ineligible (young, few trades).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from copytrade.selection.models import STATUS_APPLIED, Follow
from tests.hl.support import T0
from tests.selection.helpers import cycle as scored_cycle
from tests.selection.helpers import score, w
from tests.selection.r3_world import K, R3, make_r3, ok_page, ranked_rows, row

N = 55  # five more ranked wallets than slots


def many_ok(tmp_path: Path, n: int = N) -> R3:
    r3 = make_r3(tmp_path)
    page = ok_page(T0)
    for i in range(1, n + 1):
        r3.serve(w(i), page)
    r3.set_board(ranked_rows(n))
    return r3


def hourly_cycle(r3: R3, ticks: int = 20) -> Any:
    r3.advance_h(1)
    return r3.cycle(ticks)


def test_R3_AC6_three_ineligible_cycles_in_a_row_free_the_slots_for_the_wallets_below(tmp_path: Path) -> None:
    r3 = many_ok(tmp_path)
    r3.cycle()
    r3.drive_until_complete(max_ticks=1500)  # cycle 1: the top 50 are screened OK and backfilled (it scores nobody)
    top, below = [w(i) for i in range(N, N - K, -1)], [w(i) for i in range(1, 6)]
    assert r3.screened_order() == top

    for _ in range(2):  # scored cycles 1 and 2: ineligible, nothing rotates yet
        report = hourly_cycle(r3)
        assert report.status == STATUS_APPLIED
    assert not set(below) & set(r3.screened_order()), "rotated after only two ineligible cycles"

    hourly_cycle(r3)  # scored cycle 3: the third in a row
    hourly_cycle(r3, 300)  # the next cycle's list skips the rotated wallets: the five below get the freed slots
    assert set(below) <= set(r3.screened_order())
    assert r3.screened_order()[:K] == top  # and the order of what was screened before did not change
    for wallet in top:
        assert len(r3.screen_calls(wallet)) == 1  # nobody was re-screened

    rotated = len(r3.fills_calls(top[0]))
    r3.advance_h(1)
    r3.cycle(100)
    assert len(r3.fills_calls(top[0])) == rotated  # a rotated wallet is not refreshed during its cooldown

    r3.advance_h(75)  # past 72 h from the cooldown start
    r3.cycle(400)
    assert len(r3.fills_calls(top[0])) > rotated  # it competes again


def apply_scored(r3: R3, *, eligible: tuple[int, ...] = ()) -> None:
    """One hand-built scored cycle over the three wallets: ``eligible`` ids are ranked (1..), the rest ineligible."""
    now = r3.clock.now_ms()
    scores = [
        score(i, eligible.index(i) + 1) if i in eligible else score(i, None, eligible=False, reasons=("G2",))
        for i in (1, 2, 3)
    ]
    r3.mw.manager.apply_cycle(scored_cycle(scores, t_ms=now), now_ms=now)
    r3.advance_h(1)


def three_wallets(tmp_path: Path) -> R3:
    r3 = make_r3(tmp_path)
    for i in (1, 2, 3):
        r3.serve(w(i), ok_page(T0))
    r3.set_board(ranked_rows(3))
    r3.cycle()
    r3.drive_until_complete()
    return r3


def refreshed_after_next_cycle(r3: R3) -> set[str]:
    """Wallets (of the three) that were refreshed or fetched again after the next ``run_cycle`` (cycle B)."""
    r3.advance_h(1)
    r3.cycle()  # cycle B: its candidate list is built from the cooldowns known by now
    before = {w(i): len(r3.fills_calls(w(i))) for i in (1, 2, 3)}
    r3.drive(40)
    return {wallet for wallet, n in before.items() if len(r3.fills_calls(wallet)) > n}


def test_R3_AC6_one_eligible_cycle_resets_the_streak(tmp_path: Path) -> None:
    r3 = three_wallets(tmp_path)
    # wallet 1: ineligible, ineligible, ELIGIBLE, ineligible, then the real cycle A (ineligible): two in a row only.
    # Wallets 2 and 3 are ineligible every time: rotated.
    apply_scored(r3)
    apply_scored(r3)
    apply_scored(r3, eligible=(1,))
    apply_scored(r3)
    hourly_cycle(r3)  # cycle A, scored by F5: ineligible
    assert refreshed_after_next_cycle(r3) == {w(1)}


def test_R3_AC6_without_the_reset_the_third_ineligible_cycle_rotates_it(tmp_path: Path) -> None:
    r3 = three_wallets(tmp_path)
    apply_scored(r3)  # ineligible, ineligible, then the real cycle A (ineligible): three in a row
    apply_scored(r3)
    hourly_cycle(r3)
    assert refreshed_after_next_cycle(r3) == set()  # all three are cooling down for 72 h


# --- a stable list ------------------------------------------------------------------------------------------------


def screened_after(r3: R3, before: list[str]) -> list[str]:
    return [x for x in r3.screened_order() if x not in before]


def test_R3_AC6_a_better_ranked_newcomer_does_not_push_a_slot_holder_out(tmp_path: Path) -> None:
    r3 = many_ok(tmp_path)
    r3.cycle()
    r3.drive_until_complete(max_ticks=1500)
    first = r3.screened_order()
    star = w(1)  # not a slot holder (rank 55), and now the best row of the board
    rows = ranked_rows(N)
    rows[0] = row(star, bps_m=50, bps_p=50, vlm_prior=900_000_000)
    r3.set_board(list(reversed(rows)))  # served in the opposite order too
    r3.advance_h(1)
    r3.cycle(300)
    assert screened_after(r3, first) == []  # the 50 holders keep their slots: no screen at all
    for wallet in first:
        assert len(r3.screen_calls(wallet)) == 1


def test_R3_AC6_a_slot_holder_that_stops_passing_stage_1_frees_exactly_one_slot(tmp_path: Path) -> None:
    r3 = many_ok(tmp_path)
    r3.cycle()
    r3.drive_until_complete(max_ticks=1500)
    first = r3.screened_order()
    rows = ranked_rows(N)
    rows[N - 1] = row(w(N), pnl_month="0")  # the best holder lost its month: P6 fails
    r3.set_board(rows)
    r3.advance_h(1)
    r3.cycle(300)
    assert screened_after(r3, first) == [w(5)]  # the best-ranked wallet outside the list takes the free slot


@pytest.mark.parametrize(("newcomers", "screened"), [(99, 49), (100, 50)], ids=["old rank 100 keeps its slot", "old rank 101"])
def test_R3_AC6_a_holder_keeps_its_slot_only_within_the_top_two_times_k(
    tmp_path: Path, newcomers: int, screened: int
) -> None:
    r3 = make_r3(tmp_path)
    page = ok_page(T0)
    old = [row(w(i), bps_m=20, bps_p=20, vlm_prior=1_600_000 + i * 1_000) for i in range(1, K + 1)]
    for i in range(1, K + 1):
        r3.serve(w(i), page)
    r3.set_board(old)
    r3.cycle()
    r3.drive_until_complete(max_ticks=1500)
    first = r3.screened_order()
    assert len(first) == K

    new = [row(w(1000 + j), vlm_prior=1_600_000 + j * 1_000) for j in range(1, newcomers + 1)]  # K1 50: all above the old
    for j in range(1, newcomers + 1):
        r3.serve(w(1000 + j), page)
    r3.set_board([*old, *new])
    r3.advance_h(1)
    r3.cycle(600)
    fresh = screened_after(r3, first)
    assert fresh == [w(1000 + j) for j in range(newcomers, newcomers - screened, -1)]  # best newcomers first
    for wallet in first:
        assert len(r3.screen_calls(wallet)) == 1  # a holder is never screened a second time


def test_R3_AC6_a_followed_wallet_is_never_rotated_and_counts_from_zero_once_unfollowed(tmp_path: Path) -> None:
    # R3-SD4: ineligible while FOLLOWED never counts (the followed are never rotated); the 72 h cooldown must not be
    # waiting for the wallet at the moment it is unfollowed. drop_confirm_cycles 6 keeps it followed through five
    # ineligible cycles (3 would rotate a wallet that counted), the sixth drops it (followed for over 24 h).
    # refreshed_in_next_cycle(): the wallet got a fills request while that cycle's work ran.
    r3 = make_r3(tmp_path, select__drop_confirm_cycles=6)
    target = w(1)
    for i in (1, 2):
        r3.serve(w(i), ok_page(T0))
    r3.set_board(ranked_rows(2))
    r3.mw.manager.restore(
        {target: Follow(followed_at_ms=r3.clock.now_ms() - 30 * 3_600_000, drop_streak=0)}, subscribed=[target], paused=[]
    )
    r3.cycle()
    r3.drive_until_complete()
    assert target in r3.mw.manager.followed

    def refreshed_in_next_cycle() -> bool:
        before = len(r3.fills_calls(target))
        hourly_cycle(r3, 40)
        return len(r3.fills_calls(target)) > before

    for n in range(1, 6):  # scored cycles 1-5 while followed: no streak, nothing rotates
        hourly_cycle(r3)
        assert target in r3.mw.manager.followed, n
    assert refreshed_in_next_cycle()  # cycle 6: a cooldown from cycle 3 would not hold a followed wallet back either
    r3.mw.manager.tick()  # dropped by the sixth ineligible cycle, no open share: released now
    assert target not in r3.mw.manager.followed
    # unfollowed, the wallet counts from zero: the cycles right after are not enough to rotate it (a wallet that had
    # counted its followed cycles would be cooling down from the first of them) ...
    for n in (7, 8, 9):
        assert refreshed_in_next_cycle(), n
    # ... and it IS rotated once three counted cycles have passed
    assert not all(refreshed_in_next_cycle() for _ in range(4))
