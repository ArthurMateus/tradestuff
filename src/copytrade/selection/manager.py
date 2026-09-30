"""The follow manager (F6.AC2-AC7): runs a cycle and drives the feed, the signal detector and the ledger."""

from __future__ import annotations

from decimal import Decimal

from copytrade.core.clock import Clock
from copytrade.core.config import Config
from copytrade.core.domain import ActionKind
from copytrade.core.events import AlertSink
from copytrade.ledger.store import Ledger
from copytrade.recorder.ports import LeaderboardSource
from copytrade.scoring.models import CostModel, CycleResult, ScoreStore
from copytrade.selection.models import (
    CycleReport,
    FollowRegistry,
    InputsProvider,
    OpenShareSource,
    StateSource,
    WalletFeed,
)


class FollowManager:
    """See ``docs/sdlc/copytrade-v1/05-test-plan-F6.md`` for the pinned decisions.

    Joining a wallet: fetch its ``clearinghouseState`` (a failure means it is not joined this cycle), then
    ``registry.begin_follow(wallet, state, now_ms)``, then ``feed.subscribe_user(wallet)``. Releasing: ``feed.
    unsubscribe_user`` then ``registry.end_follow``. Distinct subscribed users never exceed ``hl.ws_max_unique_users``;
    a join or swap without a free slot is deferred (ledger ``follow_deferred`` with reason ``no_ws_slot``).
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        config: Config,
        clock: Clock,
        ledger: Ledger,
        alerts: AlertSink,
        feed: WalletFeed,
        registry: FollowRegistry,
        states: StateSource,
        shares: OpenShareSource,
        leaderboard: LeaderboardSource,
        inputs: InputsProvider,
        scores: ScoreStore,
        costs: CostModel,
    ) -> None:
        raise NotImplementedError

    @property
    def followed(self) -> frozenset[str]:
        """Wallets whose new opens we copy."""
        raise NotImplementedError

    @property
    def subscribed(self) -> frozenset[str]:
        """Followed wallets plus dropped wallets still held for their open shares."""
        raise NotImplementedError

    @property
    def next_due_ms(self) -> int | None:
        """When the next cycle should start (``None`` before the first cycle)."""
        raise NotImplementedError

    def due(self) -> bool:
        """True before the first cycle, then once the clock reaches ``next_due_ms``."""
        raise NotImplementedError

    def run_cycle(self, *, p95_latency_s: Decimal | None) -> CycleReport:
        """One full cycle at ``clock.now_ms()``: fetch the leaderboard, set the candidates, and (only when the
        inputs provider is ``complete``) refresh and score candidates plus followed wallets with F5's ``run_cycle``
        and apply the result. Always ledgers a ``select_cycle`` record."""
        raise NotImplementedError

    def apply_cycle(self, result: CycleResult, *, now_ms: int) -> CycleReport:
        """Apply an already scored cycle (no leaderboard, no backfill gate, no overrun check)."""
        raise NotImplementedError

    def tick(self) -> None:
        """Release dropped wallets whose last share has closed. Call at least once a second."""
        raise NotImplementedError

    def on_copy_closed(self, wallet: str, *, pnl_usd: Decimal, equity_usd: Decimal) -> None:
        """Feed one closed copy to the leader pause; a trip drops the wallet at once (safety drop)."""
        raise NotImplementedError

    def refusal_reason(self, wallet: str, action: ActionKind) -> str | None:
        """For OPEN and ADD: ``leader_paused`` (safety dropped or paused), else ``no_eligible_leaders`` (last cycle had
        no eligible wallet), else ``not_followed``, else None. Reduces and closes are never refused."""
        raise NotImplementedError
