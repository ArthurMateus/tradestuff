"""Score S and ranking (F5.AC5), edge-hypothesis 10.4.

Each component uses fixed config anchors, never a cross-sectional statistic, so a wallet's S depends only on its own
data: it is independent of other wallets and of input order, and monotone in every component.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from copytrade.core.ceilings import SCORE_COMPONENTS
from copytrade.core.config import Config
from copytrade.scoring.models import Components, Metrics, RankEntry

_ZERO = Decimal(0)
_ONE = Decimal(1)


def shrink_toward_zero(x: Decimal, n: int, k: int) -> Decimal:
    """``x * n / (n + k)``: the same sign, a smaller or equal magnitude. No evidence at all (``n + k = 0``) gives 0."""
    return x * n / (n + k) if n + k > 0 else _ZERO


def _require(value: Decimal | None, name: str) -> Decimal:
    if value is None:
        raise ValueError(f"cannot score without {name}")
    return value


def score_components(m: Metrics, *, cfg: Config) -> Components:
    """``u_k = clip((x_k - lo_k) / (hi_k - lo_k), 0, 1)`` and ``S = sum w_k * u_k`` (10.4).

    ``x`` for ``copy_mean_r`` is shrunk: ``copy_mean_r * n_rt / (n_rt + score.shrink_k_trades)``; for ``pos_blocks``
    it is ``pos_blocks / gate.n_blocks``. Weights and anchors come from ``score.weights.*`` and ``score.anchors.*``.
    The weights sum to 1 only within 1e-9, so S is capped at 1.

    Raises:
        ValueError: a component input the score needs is None (only eligible wallets are scored).
    """
    x = {
        "dsr_excess": _require(m.dsr_excess, "dsr_excess"),
        "copy_mean_r": shrink_toward_zero(_require(m.copy_mean_r, "copy_mean_r"), m.n_rt, cfg["score.shrink_k_trades"]),
        "pos_blocks": Decimal(m.pos_blocks) / cfg["gate.n_blocks"],
        "max_dd": _require(m.max_dd, "max_dd"),
        "recent_sr": _require(m.recent_sr, "recent_sr"),
        "executable": _require(m.executable_share, "executable_share"),
    }
    u: dict[str, Decimal] = {}
    total = _ZERO
    for name in SCORE_COMPONENTS:
        lo: Decimal = cfg[f"score.anchors.{name}.lo"]
        hi: Decimal = cfg[f"score.anchors.{name}.hi"]
        u[name] = min(_ONE, max(_ZERO, (x[name] - lo) / (hi - lo)))
        total += cfg[f"score.weights.{name}"] * u[name]
    return Components(x=x, u=u, score=min(_ONE, total))


def rank_entries(entries: Sequence[RankEntry]) -> tuple[RankEntry, ...]:
    """Order by score descending, then ``n_rt`` descending, then lowercase address ascending. Deterministic."""
    return tuple(sorted(entries, key=lambda e: (-e.score, -e.n_rt, e.address.lower())))
