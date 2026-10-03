"""F6.AC1 [unit]: hysteresis (edge-hypothesis 10.6 steps 2-5 and 10.7 tests 6-10), on the pure policy.

The inputs are real F5 data types (``CycleResult`` / ``WalletScore``) built by hand. Ranks and scores are read from
them, never recomputed, so a result may be sparse (a wallet at rank 16 without fifteen wallets above it).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from copytrade.core.config import Config
from copytrade.scoring.models import WalletScore
from copytrade.selection.models import (
    DECISION_JOIN,
    DECISION_RANK_DROP,
    DECISION_SAFETY_DROP,
    DECISION_SWAP,
    PolicyOutcome,
    SelectionState,
)
from copytrade.selection.policy import apply_cycle
from tests.selection.helpers import D, HOUR, MINUTE, NOW, cfg, cycle, kinds, of_kind, score, state, w

NONE: frozenset[str] = frozenset()


def step(
    c: Config, st: SelectionState, scores: Sequence[WalletScore], now: int = NOW, paused: frozenset[str] = NONE
) -> PolicyOutcome:
    return apply_cycle(c, st, cycle(scores, now), now_ms=now, paused=paused)


def run(
    c: Config, st: SelectionState, per_cycle: Sequence[Sequence[WalletScore]], start: int = NOW, every: int = MINUTE
) -> tuple[PolicyOutcome, list[PolicyOutcome]]:
    """Apply a list of score lists, one per cycle; return (final outcome, all outcomes)."""
    outs = []
    now = start
    for scores in per_cycle:
        out = step(c, st, scores, now)
        outs.append(out)
        st = out.state
        now += every
    return outs[-1], outs


# --- join -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("confirm", [1, 2, 3])
def test_F6_AC1_joins_exactly_on_the_join_confirm_cycle(confirm: int) -> None:
    c = cfg(select__join_confirm_cycles=confirm)
    _, outs = run(c, state(), [[score(1, 1)]] * (confirm + 1))
    for i, out in enumerate(outs[: confirm - 1]):
        assert out.decisions == (), f"cycle {i + 1} is before the confirmation"
    joined = [i for i, o in enumerate(outs) if kinds(o.decisions) == [(DECISION_JOIN, w(1))]]
    assert joined == [confirm - 1]
    assert w(1) in outs[-1].state.followed


def test_F6_AC1_a_join_records_the_follow_time_of_the_confirming_cycle() -> None:
    _, outs = run(cfg(), state(), [[score(1, 1)], [score(1, 1)]], start=NOW, every=HOUR)
    assert outs[1].state.followed[w(1)].followed_at_ms == NOW + HOUR
    assert outs[1].state.followed[w(1)].drop_streak == 0


@pytest.mark.parametrize("rank", [1, 7, 8])
def test_F6_AC1_ranks_up_to_join_rank_join(rank: int) -> None:
    out, _ = run(cfg(), state(), [[score(1, rank)]] * 2)
    assert w(1) in out.state.followed


@pytest.mark.parametrize("rank", [9, 10, 15, 16, 40])
def test_F6_AC1_ranks_above_join_rank_never_join_however_long_they_persist(rank: int) -> None:
    out, _ = run(cfg(), state(), [[score(1, rank)]] * 6)
    assert out.state.followed == {}
    assert out.decisions == ()


@pytest.mark.parametrize(
    "ranks", [[8, 9, 8], [8, 16, 8], [1, 9, 1], [8, 15, 8]], ids=["8-9-8", "8-16-8", "1-9-1", "8-15-8"]
)
def test_F6_AC1_a_rank_outside_the_join_line_resets_the_join_streak(ranks: list[int]) -> None:
    out, outs = run(cfg(), state(), [[score(1, r)] for r in ranks])
    assert all(o.decisions == () for o in outs)
    assert w(1) not in out.state.followed
    assert out.state.join_streaks.get(w(1), 0) == 1


def test_F6_AC1_an_ineligible_cycle_resets_the_join_streak() -> None:
    bad = score(1, None, eligible=False, reasons=("G6",))
    out, outs = run(cfg(), state(), [[score(1, 1)], [bad], [score(1, 1)]])
    assert all(o.decisions == () for o in outs)
    assert out.state.join_streaks.get(w(1), 0) == 1


def test_F6_AC1_a_wallet_missing_from_the_cycle_resets_the_join_streak() -> None:
    out, outs = run(cfg(), state(), [[score(1, 1)], [score(2, 1)], [score(1, 1)]])
    assert all(o.decisions == () for o in outs)
    assert w(1) not in out.state.followed
    assert out.state.join_streaks.get(w(1), 0) == 1


def test_F6_AC1_an_already_followed_wallet_at_a_good_rank_gets_no_new_decision() -> None:
    out = step(cfg(), state({1: (NOW - 48 * HOUR, 0)}), [score(1, 1)])
    assert out.decisions == ()
    assert w(1) in out.state.followed


# --- rank drop and the hysteresis band --------------------------------------------------------------------------


@pytest.mark.parametrize("confirm", [1, 2, 3])
def test_F6_AC1_a_followed_wallet_is_dropped_on_the_drop_confirm_cycle(confirm: int) -> None:
    c = cfg(select__drop_confirm_cycles=confirm)
    _, outs = run(c, state({1: (NOW - 30 * HOUR, 0)}), [[score(1, 16)]] * (confirm + 1))
    dropped = [i for i, o in enumerate(outs) if kinds(o.decisions) == [(DECISION_RANK_DROP, w(1))]]
    assert dropped == [confirm - 1]
    assert w(1) not in outs[-1].state.followed


@pytest.mark.parametrize("rank", [9, 10, 15])
def test_F6_AC1_ranks_in_the_band_keep_a_followed_wallet(rank: int) -> None:
    out, outs = run(cfg(), state({1: (NOW - 48 * HOUR, 0)}), [[score(1, rank)]] * 6)
    assert all(o.decisions == () for o in outs)
    assert w(1) in out.state.followed


def test_F6_AC1_rank_one_above_drop_rank_drops_and_drop_rank_itself_does_not() -> None:
    kept, _ = run(cfg(), state({1: (NOW - 48 * HOUR, 0)}), [[score(1, 15)]] * 6)
    gone, _ = run(cfg(), state({1: (NOW - 48 * HOUR, 0)}), [[score(1, 16)]] * 2)
    assert w(1) in kept.state.followed
    assert w(1) not in gone.state.followed


@pytest.mark.parametrize("ranks", [[16, 15, 16], [16, 9, 16], [16, 1, 16]])
def test_F6_AC1_a_rank_back_inside_the_drop_line_resets_the_drop_streak(ranks: list[int]) -> None:
    out, outs = run(cfg(), state({1: (NOW - 48 * HOUR, 0)}), [[score(1, r)] for r in ranks])
    assert all(o.decisions == () for o in outs)
    assert w(1) in out.state.followed
    assert out.state.followed[w(1)].drop_streak == 1


@pytest.mark.parametrize(
    "reasons", [("G6",), ("stale_input",), ("G1", "G11")], ids=["G6", "stale_input", "two-gates"]
)
def test_F6_AC1_an_ineligible_followed_wallet_counts_as_past_the_drop_line(reasons: tuple[str, ...]) -> None:
    bad = score(1, None, eligible=False, reasons=reasons)
    out, outs = run(cfg(), state({1: (NOW - 48 * HOUR, 0)}), [[bad], [bad]])
    assert outs[0].decisions == ()
    assert kinds(outs[1].decisions) == [(DECISION_RANK_DROP, w(1))]
    assert w(1) not in out.state.followed


def test_F6_AC1_a_followed_wallet_missing_from_the_result_counts_as_past_the_drop_line() -> None:
    out, outs = run(cfg(), state({1: (NOW - 48 * HOUR, 0)}), [[score(2, 1)], [score(2, 1)]])
    assert kinds(of_kind(outs[1].decisions, DECISION_RANK_DROP)) == [(DECISION_RANK_DROP, w(1))]
    assert w(1) not in out.state.followed


# --- minimum follow time ----------------------------------------------------------------------------------------


def test_F6_AC1_min_follow_hours_boundary_exactly_at_is_dropped_one_ms_short_is_not() -> None:
    c = cfg()
    at = step(c, state({1: (NOW - 24 * HOUR, 1)}), [score(1, 16)])
    short = step(c, state({1: (NOW - 24 * HOUR + 1, 1)}), [score(1, 16)])
    assert kinds(at.decisions) == [(DECISION_RANK_DROP, w(1))]
    assert short.decisions == ()
    assert w(1) in short.state.followed
    assert short.state.followed[w(1)].drop_streak >= 2  # the streak keeps counting while the wallet is protected
    later = step(c, short.state, [score(1, 16)], now=NOW + 1)
    assert kinds(later.decisions) == [(DECISION_RANK_DROP, w(1))]


def test_F6_AC1_no_rank_drop_before_min_follow_hours_however_many_cycles() -> None:
    every = HOUR + 10 * MINUTE
    _, outs = run(cfg(), state({1: (NOW, 0)}), [[score(1, 40)]] * 25, start=NOW, every=every)
    early = [o for i, o in enumerate(outs) if i * every < 24 * HOUR]
    assert len(early) == 21 and all(o.decisions == () for o in early)
    assert all(w(1) in o.state.followed for o in early)
    assert kinds(outs[21].decisions) == [(DECISION_RANK_DROP, w(1))]  # the first cycle past the 24 h mark


@pytest.mark.parametrize("hours", [1, 24, 48])
def test_F6_AC1_min_follow_hours_is_read_from_config(hours: int) -> None:
    c = cfg(select__min_follow_hours=hours)
    ok = step(c, state({1: (NOW - hours * HOUR, 5)}), [score(1, 16)])
    early = step(c, state({1: (NOW - hours * HOUR + 1, 5)}), [score(1, 16)])
    assert kinds(ok.decisions) == [(DECISION_RANK_DROP, w(1))]
    assert early.decisions == ()


# --- swap -------------------------------------------------------------------------------------------------------

OLD = NOW - 48 * HOUR


def full_house(
    weakest_score: str, *, cand_score: str = "0.90", weakest_at: int = OLD, cand_streak: int = 1
) -> tuple[SelectionState, list[WalletScore]]:
    """Nine followed wallets w1..w9 (w9 the weakest, score ``weakest_score`` <= 0.80) and a candidate w20 at rank 1.
    w1..w8 score 0.88 down to 0.81. Returns (state, scores)."""
    followed = {i: (OLD, 0) for i in range(1, 9)}
    followed[9] = (weakest_at, 0)
    scores = [score(20, 1, cand_score)]
    for i in range(1, 9):
        scores.append(score(i, i + 1, str(D("0.89") - D("0.01") * i)))
    scores.append(score(9, 10, weakest_score))
    return state(followed, {20: cand_streak}), scores


def test_F6_AC1_swap_margin_boundary_exactly_at_the_margin_swaps() -> None:
    st, scores = full_house("0.80")
    out = step(cfg(), st, scores)
    assert kinds(out.decisions) == [(DECISION_SWAP, w(20))]
    assert out.decisions[0].replaces == w(9)
    assert w(20) in out.state.followed and w(9) not in out.state.followed
    assert len(out.state.followed) == 9
    assert out.state.followed[w(20)].followed_at_ms == NOW


def test_F6_AC1_swap_margin_boundary_just_below_the_margin_does_not_swap() -> None:
    st, scores = full_house("0.801")
    out = step(cfg(), st, scores)
    assert out.decisions == ()
    assert len(out.state.followed) == 9 and w(9) in out.state.followed and w(20) not in out.state.followed


@pytest.mark.parametrize("margin,weakest,swaps", [("0.20", "0.70", True), ("0.20", "0.701", False), ("0", "0.80", True)])
def test_F6_AC1_swap_margin_is_read_from_config(margin: str, weakest: str, swaps: bool) -> None:
    st, scores = full_house(weakest)
    out = step(cfg(select__swap_margin=margin), st, scores)
    assert bool(of_kind(out.decisions, DECISION_SWAP)) is swaps


def test_F6_AC1_the_weakest_must_have_been_followed_min_follow_hours_before_a_swap() -> None:
    st_ok, scores = full_house("0.60", weakest_at=NOW - 24 * HOUR)
    st_young, _ = full_house("0.60", weakest_at=NOW - 24 * HOUR + 1)
    assert kinds(step(cfg(), st_ok, scores).decisions) == [(DECISION_SWAP, w(20))]
    young = step(cfg(), st_young, scores)
    assert young.decisions == ()
    assert w(9) in young.state.followed and w(20) not in young.state.followed


def test_F6_AC1_a_young_weakest_blocks_the_swap_even_if_an_older_wallet_would_do() -> None:
    # w9 (score 0.60) is 1 h old; w8 (0.72, the next weakest) is old and the candidate beats it by 0.08 only, so the
    # only margin-clearing target is the young one.
    st, scores = full_house("0.60", weakest_at=NOW - HOUR)
    out = step(cfg(), st, scores)
    assert out.decisions == ()


def test_F6_AC1_no_swap_while_there_is_room() -> None:
    st, scores = full_house("0.60")
    followed = {k: v for k, v in st.followed.items() if k != w(9)}
    out = step(cfg(), SelectionState(followed=followed, join_streaks=st.join_streaks), [s for s in scores if s.address != w(9)])
    assert kinds(out.decisions) == [(DECISION_JOIN, w(20))]  # a plain join into the free seat, not a swap


def test_F6_AC1_at_most_one_swap_per_cycle_and_the_best_ranked_candidate_wins() -> None:
    st, scores = full_house("0.50")
    st = SelectionState(followed=st.followed, join_streaks={w(20): 1, w(21): 1})
    scores = [
        score(20, 1, "0.95"),
        score(21, 2, "0.94"),
        *[score(i, i + 2, str(D("0.89") - D("0.01") * i)) for i in range(1, 9)],
        score(9, 11, "0.50"),
    ]
    out = step(cfg(), st, scores)
    swaps = of_kind(out.decisions, DECISION_SWAP)
    assert [(d.wallet, d.replaces) for d in swaps] == [(w(20), w(9))]
    assert len(out.state.followed) == 9 and w(21) not in out.state.followed


def test_F6_AC1_max_swaps_per_cycle_zero_means_no_swaps() -> None:
    st, scores = full_house("0.50")
    out = step(cfg(select__max_swaps_per_cycle=0), st, scores)
    assert out.decisions == ()
    assert w(9) in out.state.followed


def test_F6_AC1_a_swap_candidate_must_have_confirmed_its_join() -> None:
    st, scores = full_house("0.50", cand_streak=0)  # this is the candidate's first qualifying cycle
    out = step(cfg(), st, scores)
    assert out.decisions == ()


# --- the followed count -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("max_followed", [1, 5, 9])
def test_F6_AC1_the_followed_count_never_exceeds_max_followed(max_followed: int) -> None:
    c = cfg(select__join_rank=12, select__drop_rank=20, select__max_followed=max_followed,
            select__min_followed=min(5, max_followed))
    scores = [score(i, i) for i in range(1, 13)]
    st = state(joins={i: 1 for i in range(1, 13)})
    out = step(c, st, scores)
    assert len(out.state.followed) == max_followed
    assert set(out.state.followed) == {w(i) for i in range(1, max_followed + 1)}  # best ranks first
    assert [d.wallet for d in of_kind(out.decisions, DECISION_JOIN)] == [w(i) for i in range(1, max_followed + 1)]
    assert of_kind(out.decisions, DECISION_SWAP) == []


# --- safety drop ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flags,reasons",
    [(("BU1",), ("BU1",)), (("BU6",), ()), (("BU8", "BU3"), ("G6",)), ((), ("G15",)), ((), ("G1", "G15"))],
    ids=["BU1", "BU6-only-flag", "two-BU", "G15", "G15-and-G1"],
)
def test_F6_AC1_a_blowup_flag_or_a_G15_failure_drops_immediately_whatever_the_follow_time(
    flags: tuple[str, ...], reasons: tuple[str, ...]
) -> None:
    bad = score(1, None, eligible=False, reasons=reasons, flags=flags)
    out = step(cfg(), state({1: (NOW - HOUR, 0)}), [bad])
    assert kinds(out.decisions) == [(DECISION_SAFETY_DROP, w(1))]
    assert w(1) not in out.state.followed


def test_F6_AC1_a_paused_wallet_is_dropped_immediately() -> None:
    out = step(cfg(), state({1: (NOW - 60_000, 0)}), [score(1, 1)], paused=frozenset({w(1)}))
    assert kinds(out.decisions) == [(DECISION_SAFETY_DROP, w(1))]
    assert w(1) not in out.state.followed


def test_F6_AC1_a_non_safety_gate_failure_is_not_an_immediate_drop() -> None:
    bad = score(1, None, eligible=False, reasons=("G6",))
    out = step(cfg(), state({1: (NOW - HOUR, 0)}), [bad])
    assert out.decisions == ()
    assert w(1) in out.state.followed


def test_F6_AC1_a_safety_drop_frees_a_seat_for_a_join_in_the_same_cycle() -> None:
    followed = {i: (OLD, 0) for i in range(1, 10)}
    scores = [score(20, 1, "0.90"), score(1, None, eligible=False, flags=("BU2",))]
    scores += [score(i, i, str(D("0.89") - D("0.01") * i)) for i in range(2, 10)]
    out = step(cfg(), state(followed, {20: 1}), scores)
    assert kinds(of_kind(out.decisions, DECISION_SAFETY_DROP)) == [(DECISION_SAFETY_DROP, w(1))]
    assert kinds(of_kind(out.decisions, DECISION_JOIN)) == [(DECISION_JOIN, w(20))]
    assert of_kind(out.decisions, DECISION_SWAP) == []
    assert len(out.state.followed) == 9


# --- never follow the ineligible --------------------------------------------------------------------------------


def test_F6_AC1_an_ineligible_wallet_never_joins_whatever_its_streak() -> None:
    bad = score(1, None, eligible=False, reasons=("G6",))
    out = step(cfg(), state(joins={1: 9}), [bad])
    assert out.state.followed == {} and out.decisions == ()


def test_F6_AC1_a_paused_wallet_never_joins_even_at_rank_one() -> None:
    out = step(cfg(), state(joins={1: 9}), [score(1, 1)], paused=frozenset({w(1)}))
    assert out.state.followed == {} and out.decisions == ()


# --- purity -----------------------------------------------------------------------------------------------------


def test_F6_AC1_the_policy_is_deterministic_and_leaves_its_input_state_alone() -> None:
    st = state({1: (OLD, 1), 2: (OLD, 0)}, {3: 1})
    before = (dict(st.followed), dict(st.join_streaks))
    scores = [score(3, 1), score(1, 16), score(2, 2)]
    a = step(cfg(), st, scores)
    b = step(cfg(), st, scores)
    assert a == b
    assert (dict(st.followed), dict(st.join_streaks)) == before


def test_F6_AC1_eligible_count_counts_eligible_wallets_only() -> None:
    scores = [score(1, 1), score(2, 2), score(3, None, eligible=False, reasons=("G6",))]
    assert step(cfg(), state(), scores).eligible_count == 2
