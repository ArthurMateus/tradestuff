"""Per-leader pause from our own copy results (F6.AC2)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from copytrade.core.config import Config

_ZERO = Decimal(0)


@dataclass
class _Record:
    """One leader's running copy results."""

    cumulative_usd: Decimal = _ZERO
    peak_usd: Decimal = _ZERO
    loss_run: int = 0


class LeaderPauseTracker:
    """Tracks, per leader, the P&L of our closed copies. A leader is paused (for good, in this process) when
    either trigger trips:

    - drawdown: the wallet's cumulative copy P&L (starting at 0) falls from its running peak (at least 0) by
      ``>= leader_pause.max_copy_dd * risk.leader_allocation_fraction * equity_usd``, with ``equity_usd`` as passed in
      the call that records the result;
    - ``leader_pause.max_consec_losses`` consecutive losing copies (a profit resets the run).

    A copy with P&L 0 neither extends nor resets the loss run. An equity of zero or less makes the threshold zero or
    negative, so the next result pauses the leader (fail closed: equity we cannot size against is not trusted).
    """

    def __init__(self, cfg: Config) -> None:
        self._max_dd_fraction: Decimal = cfg["leader_pause.max_copy_dd"] * cfg["risk.leader_allocation_fraction"]
        self._max_consecutive_losses: int = cfg["leader_pause.max_consec_losses"]
        self._records: dict[str, _Record] = {}
        self._paused: set[str] = set()

    def record_copy_result(self, wallet: str, *, pnl_usd: Decimal, equity_usd: Decimal) -> bool:
        """Record one closed copy (net of fees); return True when this call paused the wallet."""
        key = wallet.lower()
        if key in self._paused:
            return False
        record = self._records.setdefault(key, _Record())
        record.cumulative_usd += pnl_usd
        record.peak_usd = max(record.peak_usd, record.cumulative_usd)
        if pnl_usd < 0:
            record.loss_run += 1
        elif pnl_usd > 0:
            record.loss_run = 0
        drawdown_usd = record.peak_usd - record.cumulative_usd
        if drawdown_usd >= self._max_dd_fraction * equity_usd or record.loss_run >= self._max_consecutive_losses:
            self._paused.add(key)
            return True
        return False

    def restore_paused(self, wallet: str) -> None:
        """A wallet that an earlier run paused (the ledger's ``leader_paused`` record) stays paused."""
        self._paused.add(wallet.lower())

    def is_paused(self, wallet: str) -> bool:
        return wallet.lower() in self._paused

    def paused(self) -> frozenset[str]:
        """Every paused wallet, lower case."""
        return frozenset(self._paused)
