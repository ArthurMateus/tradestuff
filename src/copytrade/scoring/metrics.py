"""Metrics M1-M19 (F5.AC1). Interface stub; the developer owns the implementation."""


from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from copytrade.core.config import Config
from copytrade.scoring.models import CostModel, DsrResolution, Metrics, TripRecord, WalletInputs


def daily_returns(
    inputs: WalletInputs, *, cfg: Config, t_ms: int
) -> tuple[tuple[tuple[int, Decimal], ...], DsrResolution]:
    """Daily returns ``r_d = dPnL_d / AV_{d-1}`` for the complete UTC days in ``[t - window_days, t)``.

    Returns ``((day_index, r_d), ...)`` in day order plus the per-source day counts. See the test plan for the
    source order (own hourly, perpMonth, fills), the AV rule and the exclusion of days with no prior AV.
    ``perpAllTime`` P&L points are never used for a daily return.
    """
    raise NotImplementedError


def trip_records(inputs: WalletInputs, *, cfg: Config, t_ms: int) -> tuple[TripRecord, ...]:
    """Closed round trips inside the window (point-in-time), each with the AV at its open."""
    raise NotImplementedError


def compute_metrics(inputs: WalletInputs, *, cfg: Config, t_ms: int, costs: CostModel) -> Metrics:
    """M1-M19 for one wallet at cycle time ``t_ms``, using only inputs at or before ``t_ms`` (10.1, 10.2)."""
    raise NotImplementedError


def copy_replay_r(inputs: WalletInputs, *, cfg: Config, t_ms: int, costs: CostModel) -> Sequence[Decimal]:
    """Per closed round trip ``R_copy_j`` (M14). Trips whose ATR stop cannot be built are omitted."""
    raise NotImplementedError
