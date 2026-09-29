"""Round-trip reconstruction (F5.AC2). Interface stub; the developer owns the implementation."""


from __future__ import annotations

from collections.abc import Sequence

from copytrade.scoring.models import Fill, FundingPayment, Reconstruction


def reconstruct(fills: Sequence[Fill], funding: Sequence[FundingPayment]) -> Reconstruction:
    """Rebuild round trips exactly as ``research/scripts/hl_sample.py::reconstruct`` does, in Decimal.

    - Fills are processed in ``(time, tid)`` order whatever the input order; a repeated ``tid`` counts once.
    - A flip splits into a close (it takes the flip fill's closedPnl and fee) and a new open.
    - A position already open at the first fill of a coin is ignored until it is flat.
    - Spot (``@n``, ``A/B``) and ``dex:``-prefixed fills are skipped.
    - ``net_pnl`` = sum closedPnl - sum fee - funding paid on that coin between open and close (inclusive).
    """
    raise NotImplementedError
