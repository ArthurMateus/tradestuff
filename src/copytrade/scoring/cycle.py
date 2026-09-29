"""One scoring cycle: score every wallet, rank the eligible, persist (F5.AC3, AC5, AC6, AC7).

Interface stub; the developer owns the implementation.
"""


from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from copytrade.core.config import Config
from copytrade.scoring.models import CostModel, CycleResult, ScoreStore, WalletInputs, WalletScore


def input_hashes(inputs: WalletInputs, *, t_ms: int) -> Mapping[str, str]:
    """sha256 hex per input kind (``fills``, ``funding``, ``portfolio``, ``clearinghouse``, ``own_snapshots``,
    ``candles``) over the canonical bytes of the point-in-time inputs actually used (10.1). The leaderboard row is
    not hashed. Stable across processes and input order."""
    raise NotImplementedError


def score_wallet(
    inputs: WalletInputs, *, cfg: Config, t_ms: int, costs: CostModel, p95_latency_s: Decimal | None
) -> WalletScore:
    """Metrics, blow-up flags, gates and (if eligible) components and S for one wallet, with ``rank`` None.

    A missing input, or the latest input older than ``scoring.stale_input_mult * scoring.interval_min`` minutes,
    gives ``eligible=False`` with the reason ``stale_input`` and no score. Depends on this wallet's data only.
    """
    raise NotImplementedError


def score_cycle(
    wallets: Sequence[WalletInputs], *, cfg: Config, t_ms: int, costs: CostModel, p95_latency_s: Decimal | None
) -> CycleResult:
    """Score all wallets and rank the eligible ones (rank 1 = best) with the deterministic tie-break."""
    raise NotImplementedError


def run_cycle(  # noqa: PLR0913
    store: ScoreStore,
    wallets: Sequence[WalletInputs],
    *,
    cfg: Config,
    t_ms: int,
    costs: CostModel,
    p95_latency_s: Decimal | None,
) -> CycleResult:
    """``score_cycle`` then ``store.append_cycle`` exactly once. A store failure propagates (nothing is swallowed)."""
    raise NotImplementedError
