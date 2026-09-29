"""Eligibility gates G1-G15 (F5.AC3). Interface stub; the developer owns the implementation."""


from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from copytrade.core.config import Config
from copytrade.scoring.models import Metrics


def evaluate_gates(  # noqa: PLR0913
    m: Metrics,
    *,
    cfg: Config,
    address: str,
    role: str | None,
    p95_latency_s: Decimal | None,
    blowup_flags: Sequence[str],
) -> tuple[str, ...]:
    """Return the sorted ids (``"G1"``..``"G15"``) of every failed gate; empty = eligible on the metrics.

    Fail closed: a ``None`` input to a gate fails that gate. G8 uses ``max(gate.min_median_hold_min,
    gate.hold_latency_mult * p95_latency_s / 60)`` and fails when ``p95_latency_s`` is None. G13 fails for the
    roles in ``gate.exclude_roles``, for a missing role (None) and for ``gate.exclude_addresses`` (case-insensitive).
    G14 fails when ``blowup_flags`` is non-empty.
    """
    raise NotImplementedError
