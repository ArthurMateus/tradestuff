"""Score S and ranking (F5.AC5). Interface stub; the developer owns the implementation."""


from __future__ import annotations

from collections.abc import Sequence

from copytrade.core.config import Config
from copytrade.scoring.models import Components, Metrics, RankEntry


def score_components(m: Metrics, *, cfg: Config) -> Components:
    """``u_k = clip((x_k - lo_k) / (hi_k - lo_k), 0, 1)`` and ``S = sum w_k * u_k`` (10.4).

    ``x`` for ``copy_mean_r`` is shrunk: ``copy_mean_r * n_rt / (n_rt + score.shrink_k_trades)``; for ``pos_blocks``
    it is ``pos_blocks / gate.n_blocks``. Weights and anchors come from ``score.weights.*`` and ``score.anchors.*``.

    Raises:
        ValueError: a component input the score needs is None (only eligible wallets are scored).
    """
    raise NotImplementedError


def rank_entries(entries: Sequence[RankEntry]) -> tuple[RankEntry, ...]:
    """Order by score descending, then ``n_rt`` descending, then lowercase address ascending. Deterministic."""
    raise NotImplementedError
