"""F6.AC1 property tests (edge-hypothesis 10.7 tests 6-10) over random cycle sequences on the pure policy."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.scoring.models import CycleResult, WalletScore
from copytrade.selection.models import (
    DECISION_JOIN,
    DECISION_RANK_DROP,
    DECISION_SAFETY_DROP,
    DECISION_SWAP,
    SelectionState,
)
from copytrade.selection.policy import apply_cycle
from tests.selection.helpers import HOUR, NOW, cfg, w

VARIANTS = [
    {},
    {"select__join_confirm_cycles": 1, "select__drop_confirm_cycles": 1},
    {"select__join_rank": 12, "select__drop_rank": 14, "select__max_followed": 5, "select__min_followed": 3},
    {"select__max_swaps_per_cycle": 0},
    {"select__join_confirm_cycles": 3, "select__min_follow_hours": 1, "select__swap_margin": "0.02"},
]
N_WALLETS = 14
STATUSES = ["eligible", "eligible", "eligible", "gate", "blowup", "g15", "missing"]


@st.composite
def cycles(draw: st.DrawFn) -> list[tuple[int, list[WalletScore], frozenset[str]]]:
    out = []
    now = NOW
    for _ in range(draw(st.integers(1, 12))):
        now += draw(st.integers(0, 40 * HOUR))
        rows: list[tuple[int, str, Decimal]] = []
        scores: list[WalletScore] = []
        for i in range(1, N_WALLETS + 1):
            status = draw(st.sampled_from(STATUSES))
            value = Decimal(draw(st.integers(0, 99))) / 100
            if status == "missing":
                continue
            if status == "eligible":
                rows.append((i, status, value))
            else:
                scores.append(
                    WalletScore(
                        address=w(i), eligible=False,
                        reasons=("G15",) if status == "g15" else ("G6",),
                        blowup_flags=("BU4",) if status == "blowup" else (),
                        metrics=None, components=None, score=None, rank=None, input_hashes={}, dsr_resolution=None,
                    )
                )
        rows.sort(key=lambda r: (-r[2], w(r[0])))
        for rank, (i, _, value) in enumerate(rows, start=1):
            scores.append(
                WalletScore(
                    address=w(i), eligible=True, reasons=(), blowup_flags=(), metrics=None, components=None,
                    score=value, rank=rank, input_hashes={}, dsr_resolution=None,
                )
            )
        paused = frozenset(w(i) for i in range(1, N_WALLETS + 1) if draw(st.integers(0, 29)) == 0)
        out.append((now, scores, paused))
    return out


@settings(max_examples=150)
@given(variant=st.sampled_from(VARIANTS), seq=cycles())
def test_F6_AC1_property_invariants_hold_over_random_cycle_sequences(
    variant: dict[str, object], seq: list[tuple[int, list[WalletScore], frozenset[str]]]
) -> None:
    c = cfg(**variant)
    max_followed = c["select.max_followed"]
    min_follow_ms = c["select.min_follow_hours"] * HOUR
    margin = Decimal(str(c["select.swap_margin"]))
    state = SelectionState(followed={}, join_streaks={})
    for now, scores, paused in seq:
        result = CycleResult(t_ms=now, scores=tuple(scores))
        by_addr = {s.address: s for s in scores}
        out = apply_cycle(c, state, result, now_ms=now, paused=paused)
        assert out == apply_cycle(c, state, result, now_ms=now, paused=paused)  # determinism (10.7 test 4)
        before = set(state.followed)
        after = set(out.state.followed)

        assert len(after) <= max_followed  # 10.7 test 7
        assert not (after & paused)

        drops = {d.wallet for d in out.decisions if d.kind in (DECISION_RANK_DROP, DECISION_SAFETY_DROP)}
        joins = {d.wallet for d in out.decisions if d.kind == DECISION_JOIN}
        swaps = [d for d in out.decisions if d.kind == DECISION_SWAP]
        swapped_out = {d.replaces for d in swaps}
        swapped_in = {d.wallet for d in swaps}
        assert after == (before - drops - swapped_out) | joins | swapped_in  # the decisions explain the change
        assert len(swaps) <= c["select.max_swaps_per_cycle"]  # 10.7 test 10

        for wallet in joins | swapped_in:  # 10.7 test 6
            joined = by_addr[wallet]
            assert joined.eligible and joined.rank is not None and joined.rank <= c["select.join_rank"]
            assert wallet not in paused
        for d in swaps:
            assert d.replaces in before
            s_out = by_addr.get(d.replaces)
            s_in = by_addr[d.wallet]
            assert s_in.score is not None
            if s_out is not None and s_out.score is not None:
                assert s_in.score >= s_out.score + margin
            assert now - state.followed[d.replaces].followed_at_ms >= min_follow_ms

        for d in out.decisions:
            if d.kind == DECISION_RANK_DROP:  # 10.7 test 9: no rank drop before the minimum follow time
                assert now - state.followed[d.wallet].followed_at_ms >= min_follow_ms
                dropped = by_addr.get(d.wallet)
                assert dropped is None or not dropped.eligible or (dropped.rank or 0) > c["select.drop_rank"]
            if d.kind == DECISION_SAFETY_DROP:
                flagged = by_addr.get(d.wallet)
                assert d.wallet in paused or (flagged is not None and (flagged.blowup_flags or "G15" in flagged.reasons))

        for wallet in before:  # every followed wallet with a safety trigger is gone at once (10.7 test 9)
            unsafe = by_addr.get(wallet)
            if wallet in paused or (unsafe is not None and (unsafe.blowup_flags or "G15" in unsafe.reasons)):
                assert wallet not in after

        for wallet in before & after:  # 10.7 test 8: the band keeps its status
            assert wallet not in drops
        for wallet in before - after:
            band = by_addr.get(wallet)
            if (
                band is not None and band.eligible and band.rank is not None
                and c["select.join_rank"] < band.rank <= c["select.drop_rank"]
                and wallet not in paused
            ):
                assert wallet in swapped_out  # only a swap may remove a wallet in the band
        state = out.state
