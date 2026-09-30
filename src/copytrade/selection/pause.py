"""Per-leader pause from our own copy results (F6.AC2)."""

from __future__ import annotations

from decimal import Decimal

from copytrade.core.config import Config


class LeaderPauseTracker:
    """Tracks, per leader, the P&L of our closed copies. A leader is paused (for good, in this process) when
    either trigger trips:

    - drawdown: the wallet's cumulative copy P&L (starting at 0) falls from its running peak (at least 0) by
      ``>= leader_pause.max_copy_dd * risk.leader_allocation_fraction * equity_usd``, with ``equity_usd`` as passed in
      the call that records the result;
    - ``leader_pause.max_consec_losses`` consecutive losing copies (a profit resets the run).
    """

    def __init__(self, cfg: Config) -> None:
        raise NotImplementedError

    def record_copy_result(self, wallet: str, *, pnl_usd: Decimal, equity_usd: Decimal) -> bool:
        """Record one closed copy (net of fees); return True when this call paused the wallet."""
        raise NotImplementedError

    def is_paused(self, wallet: str) -> bool:
        raise NotImplementedError

    def paused(self) -> frozenset[str]:
        """Every paused wallet, lower case."""
        raise NotImplementedError
