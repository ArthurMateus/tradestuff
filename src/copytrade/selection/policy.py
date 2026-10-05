"""The selection policy (F6.AC1, AC6; edge-hypothesis 10.6): a pure function from a scored cycle to the next state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from copytrade.core.config import Config
from copytrade.scoring.models import CycleResult, WalletScore
from copytrade.selection.models import (
    DECISION_JOIN,
    DECISION_RANK_DROP,
    DECISION_SAFETY_DROP,
    DECISION_SWAP,
    GATE_CURRENT_DRAWDOWN,
    HOUR_MS,
    REASON_DROP_INELIGIBLE,
    REASON_DROP_MISSING,
    REASON_DROP_RANK,
    REASON_SAFETY_BLOWUP,
    REASON_SAFETY_DRAWDOWN,
    REASON_SAFETY_PAUSED,
    Decision,
    Follow,
    PolicyOutcome,
    SelectionState,
)

_ZERO = Decimal(0)


def safety_reason(score: WalletScore | None, *, paused: bool) -> str | None:
    """Why a followed wallet must be dropped at once (edge-hypothesis 10.6 step 2), or ``None``.

    Any blow-up flag, a failed ``G15`` (which F5 also reports when the drawdown cannot be computed at all, so missing
    data fails closed) or the copy pause. ``score`` is ``None`` for a wallet missing from the result: that is a
    hysteresis matter, not a safety one.
    """
    if paused:
        return REASON_SAFETY_PAUSED
    if score is None:
        return None
    if score.blowup_flags:
        return REASON_SAFETY_BLOWUP
    if GATE_CURRENT_DRAWDOWN in score.reasons:
        return REASON_SAFETY_DRAWDOWN
    return None


def _past_drop_line(score: WalletScore | None, drop_rank: int) -> str | None:
    """Why a followed wallet counts towards a rank drop this cycle, or ``None`` when it is in good standing."""
    if score is None:
        return REASON_DROP_MISSING
    if not score.eligible or score.rank is None:
        return REASON_DROP_INELIGIBLE
    return REASON_DROP_RANK if score.rank > drop_rank else None


def _strength(wallet: str, score: WalletScore | None) -> tuple[bool, Decimal, str]:
    """Ordering key of a followed wallet, weakest first: no score is the lowest, ties go to the lower address."""
    if score is None or score.score is None:
        return (False, _ZERO, wallet)
    return (True, score.score, wallet)


def _review_followed(
    cfg: Config,
    state: SelectionState,
    by_address: Mapping[str, WalletScore],
    now_ms: int,
    paused: frozenset[str],
) -> tuple[dict[str, Follow], list[Decision], list[Decision]]:
    """Safety drops, then rank drops; returns (the followed wallets that stay, safety decisions, rank decisions)."""
    drop_rank: int = cfg["select.drop_rank"]
    drop_confirm: int = cfg["select.drop_confirm_cycles"]
    min_follow_ms: int = cfg["select.min_follow_hours"] * HOUR_MS
    staying: dict[str, Follow] = {}
    safety: list[Decision] = []
    rank_drops: list[Decision] = []
    for wallet in sorted(state.followed):
        follow = state.followed[wallet]
        score = by_address.get(wallet)
        reason = safety_reason(score, paused=wallet in paused)
        if reason is not None:
            safety.append(Decision(DECISION_SAFETY_DROP, wallet, None, reason))
            continue
        past = _past_drop_line(score, drop_rank)
        streak = follow.drop_streak + 1 if past is not None else 0
        if past is not None and streak >= drop_confirm and now_ms - follow.followed_at_ms >= min_follow_ms:
            rank_drops.append(Decision(DECISION_RANK_DROP, wallet, None, past))
            continue
        staying[wallet] = Follow(follow.followed_at_ms, streak)
    return staying, safety, rank_drops


def _qualify(
    cfg: Config,
    state: SelectionState,
    by_address: Mapping[str, WalletScore],
    paused: frozenset[str],
) -> tuple[dict[str, int], list[WalletScore]]:
    """Join streaks of the unfollowed wallets, and those whose streak has reached the confirmation, best rank first."""
    join_rank: int = cfg["select.join_rank"]
    join_confirm: int = cfg["select.join_confirm_cycles"]
    streaks: dict[str, int] = {}
    qualified: list[WalletScore] = []
    for score in by_address.values():
        if (
            score.address in state.followed
            or score.address in paused
            or not score.eligible
            or score.rank is None
            or score.score is None
            or score.rank > join_rank
        ):
            continue
        streaks[score.address] = state.join_streaks.get(score.address, 0) + 1
        if streaks[score.address] >= join_confirm:
            qualified.append(score)
    qualified.sort(key=lambda s: (s.rank or 0, s.address))
    return streaks, qualified


def _swap(
    cfg: Config,
    followed: dict[str, Follow],
    candidates: Sequence[WalletScore],
    by_address: Mapping[str, WalletScore],
    now_ms: int,
) -> list[Decision]:
    """Swaps of the candidates for the weakest followed wallet, in place, at most ``select.max_swaps_per_cycle``."""
    max_followed: int = cfg["select.max_followed"]
    max_swaps: int = cfg["select.max_swaps_per_cycle"]
    min_follow_ms: int = cfg["select.min_follow_hours"] * HOUR_MS
    margin: Decimal = cfg["select.swap_margin"]
    swaps: list[Decision] = []
    for candidate in candidates:
        if len(swaps) >= max_swaps or len(followed) < max_followed:
            break
        weakest = min(followed, key=lambda a: _strength(a, by_address.get(a)))
        if now_ms - followed[weakest].followed_at_ms < min_follow_ms:
            break  # the weakest is protected, and an older but stronger wallet is never swapped in its place
        weakest_score = by_address[weakest].score if weakest in by_address else None
        if weakest_score is not None and (candidate.score or _ZERO) < weakest_score + margin:
            continue
        del followed[weakest]
        followed[candidate.address] = Follow(now_ms, 0)
        swaps.append(Decision(DECISION_SWAP, candidate.address, weakest, None))
    return swaps


def apply_cycle(
    cfg: Config,
    state: SelectionState,
    result: CycleResult,
    *,
    now_ms: int,
    paused: frozenset[str],
) -> PolicyOutcome:
    """Apply one scored cycle to ``state`` (which is never modified).

    Order: safety drops, rank drops, joins, then at most ``select.max_swaps_per_cycle`` swaps. Wallet addresses are
    lower case. ``paused`` are wallets whose own copy results tripped the leader pause.

    Rules (``select.*`` keys):
    - Unfollowed wallet: its join streak grows by one in each cycle where it is eligible, not paused and has
      ``rank <= join_rank``, and is reset otherwise. It joins, best rank first, once the streak reaches
      ``join_confirm_cycles`` and there is room (followed < ``max_followed``). ``followed_at_ms`` is ``now_ms``.
    - Followed wallet: its ``drop_streak`` grows by one when it is ineligible (or missing from the result) or has
      ``rank > drop_rank``, and is reset otherwise (rank in the band ``(join_rank, drop_rank]`` keeps its status).
      It is rank-dropped when the streak reaches ``drop_confirm_cycles`` and ``now_ms - followed_at_ms >=
      min_follow_hours``; before that it stays followed and the streak keeps counting.
    - Safety drop, immediate and whatever the follow time: a followed wallet with any blow-up flag, with ``G15`` among
      its reasons, or in ``paused``.
    - Swap: followed == ``max_followed``, a join-qualified candidate (best rank first) has ``score >= weakest score +
      select.swap_margin``, and the weakest followed wallet (lowest score; no score is the lowest) has been followed
      ``>= min_follow_hours``. The candidate replaces it.
    - Ineligible and paused wallets never join.
    - ``rank`` and ``score`` are read from each ``WalletScore`` (F5's output); ranks are never recomputed here, and a
      result may be sparse.
    """
    max_followed: int = cfg["select.max_followed"]
    min_followed: int = cfg["select.min_followed"]
    by_address: Mapping[str, WalletScore] = {s.address: s for s in result.scores}

    followed, safety, rank_drops = _review_followed(cfg, state, by_address, now_ms, paused)
    streaks, qualified = _qualify(cfg, state, by_address, paused)

    joins: list[Decision] = []
    room = max(max_followed - len(followed), 0)
    for score in qualified[:room]:
        followed[score.address] = Follow(now_ms, 0)
        del streaks[score.address]
        joins.append(Decision(DECISION_JOIN, score.address, None, None))
    swaps = _swap(cfg, followed, qualified[room:], by_address, now_ms)
    for swap in swaps:
        del streaks[swap.wallet]

    eligible_count = sum(1 for s in by_address.values() if s.eligible)
    return PolicyOutcome(
        state=SelectionState(followed=followed, join_streaks=streaks),
        decisions=(*safety, *rank_drops, *joins, *swaps),
        eligible_count=eligible_count,
        few_eligible=eligible_count < min_followed,
        no_eligible=eligible_count == 0,
    )
