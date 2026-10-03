"""Value types, constants and ports of the selection package (F6). Plain data and Protocols, no logic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from copytrade.hl.models import ClearinghouseState
from copytrade.scoring.models import WalletInputs

# Refusal reasons (``FollowManager.refusal_reason``). The first two are spec names (F6.AC2, F6.AC6).
REASON_LEADER_PAUSED = "leader_paused"
REASON_NO_ELIGIBLE = "no_eligible_leaders"
REASON_NOT_FOLLOWED = "not_followed"  # decision D3 (the spec names no reason for a wallet we do not follow)
REASON_NO_WS_SLOT = "no_ws_slot"  # F6.AC3, logged as a deferral

# Decision kinds.
DECISION_JOIN = "join"
DECISION_RANK_DROP = "rank_drop"
DECISION_SAFETY_DROP = "safety_drop"
DECISION_SWAP = "swap"  # ``wallet`` comes in, ``replaces`` goes out
DECISION_DEFERRED = "deferred"  # a join or swap that could not be carried out; ``reason`` says why

# Cycle report statuses.
STATUS_APPLIED = "applied"
STATUS_BACKFILLING = "backfilling"
STATUS_LEADERBOARD_OUTAGE = "leaderboard_outage"
STATUS_OVERRUN = "cycle_overrun"

# Alert kinds.
ALERT_LEADERBOARD_OUTAGE = "leaderboard_outage"
ALERT_NO_ELIGIBLE = "no_eligible_leaders"

# Ledger record kinds written by the manager.
KIND_SELECT_CYCLE = "select_cycle"  # payload: t_ms, status, eligible_count, followed (sorted), decisions
KIND_FOLLOW_DEFERRED = "follow_deferred"  # payload: wallet, reason, t_ms
KIND_CYCLE_OVERRUN = "cycle_overrun"  # payload: started_ms, finished_ms

KIND_LEADER_PAUSED = "leader_paused"  # payload: wallet, t_ms (a copy-result trip outside a scoring cycle)

# Why a decision was taken (``Decision.reason``): audit text, never parsed.
REASON_SAFETY_PAUSED = "copy_pause"
REASON_SAFETY_BLOWUP = "blowup_flag"
REASON_SAFETY_DRAWDOWN = "g15"
REASON_DROP_RANK = "rank_above_drop_rank"
REASON_DROP_INELIGIBLE = "ineligible"
REASON_DROP_MISSING = "missing_from_cycle"
REASON_STATE_UNAVAILABLE = "state_unavailable"  # a join or swap whose ``clearinghouseState`` could not be fetched

GATE_CURRENT_DRAWDOWN = "G15"  # the F5 gate whose failure is a safety trigger (edge-hypothesis 10.6 step 2)
HOUR_MS = 3_600_000
MIN_LEADERBOARD_ROWS = 1000  # F6.AC5: fewer rows is an outage


@dataclass(frozen=True)
class ScreenRow:
    """What stage 2 and the logs keep of a leaderboard row: the lower-cased address, the self-reported ``accountValue``
    (``None`` when unreadable) and the week and month volume of the row (``None`` when unreadable)."""

    address: str
    account_value: Decimal | None
    vlm_week: Decimal | None
    vlm_month: Decimal | None


@dataclass(frozen=True)
class CandidateList:
    """Stage 1 of the candidate screen (``selection.prefilter``): the candidates in screening order, the K1-ranked rows
    first (``ranked_count`` of them) and then, when fewer than ``scoring.candidates_k`` rows are ranked, the rows that
    could not be ranked because a figure was unreadable, in the order served."""

    rows: tuple[ScreenRow, ...]
    ranked_count: int


@dataclass(frozen=True)
class Follow:
    """A followed wallet: when it was followed, and how many consecutive cycles it was past the drop line."""

    followed_at_ms: int
    drop_streak: int


@dataclass(frozen=True)
class SelectionState:
    """What the policy carries between cycles. ``join_streaks`` counts consecutive qualifying cycles of unfollowed
    wallets (absent = 0)."""

    followed: Mapping[str, Follow]
    join_streaks: Mapping[str, int]


@dataclass(frozen=True)
class Decision:
    """One change to the followed set, or a deferred one. ``replaces`` is set only for a swap."""

    kind: str
    wallet: str
    replaces: str | None
    reason: str | None


@dataclass(frozen=True)
class PolicyOutcome:
    """The next state and what changed. ``eligible_count`` counts eligible wallets in the result; ``few_eligible`` is
    ``eligible_count < select.min_followed`` (so it is also true for 0); ``no_eligible`` is ``eligible_count == 0``."""

    state: SelectionState
    decisions: tuple[Decision, ...]
    eligible_count: int
    few_eligible: bool
    no_eligible: bool


@dataclass(frozen=True)
class CycleReport:
    """What ``FollowManager`` did in one cycle. ``followed`` is sorted."""

    status: str
    decisions: tuple[Decision, ...]
    followed: tuple[str, ...]
    eligible_count: int


class WalletFeed(Protocol):
    """The user-fills feed (``copytrade.hl.ws.HlWsFeed`` satisfies it). ``subscribe_user`` may raise
    ``WsUserLimitError``."""

    def subscribe_user(self, wallet: str) -> None: ...

    def unsubscribe_user(self, wallet: str) -> None: ...


class FollowRegistry(Protocol):
    """The signal detector's follow API (``copytrade.signals.detector.SignalDetector`` satisfies it). F7 contract:
    ``begin_follow`` before the wallet is subscribed, ``end_follow`` after it is unsubscribed."""

    def begin_follow(self, wallet: str, state: ClearinghouseState, followed_at_ms: int) -> None: ...

    def end_follow(self, wallet: str) -> None: ...


class StateSource(Protocol):
    """A wallet's current ``clearinghouseState`` (a boundary over the REST client).

    May raise ``OSError`` or ``HlError``.
    """

    def clearinghouse_state(self, wallet: str) -> ClearinghouseState: ...


class OpenShareSource(Protocol):
    """Whether we still hold an open share (or shadow or mirror) copied from ``wallet`` (owned by F12)."""

    def has_open_shares(self, wallet: str) -> bool: ...


class InputsProvider(Protocol):
    """Point-in-time scoring inputs per wallet. ``copytrade.selection.backfill.Backfiller`` satisfies it."""

    @property
    def complete(self) -> bool:
        """The initial backfill of every candidate has finished (latched)."""
        ...

    def set_candidates(self, wallets: Sequence[str]) -> None: ...

    def refresh(self, wallet: str) -> None:
        """Fetch what is new for ``wallet`` (incremental)."""
        ...

    def inputs(self, wallet: str, t_ms: int) -> WalletInputs | None:
        """``None`` when nothing has been fetched for ``wallet``."""
        ...
