"""The selection policy (F6.AC1, AC6; edge-hypothesis 10.6): a pure function from a scored cycle to the next state."""

from __future__ import annotations

from copytrade.core.config import Config
from copytrade.scoring.models import CycleResult
from copytrade.selection.models import PolicyOutcome, SelectionState


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
    raise NotImplementedError
