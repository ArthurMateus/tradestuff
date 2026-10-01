"""The entry-policy stand-in (F9 is stage 2): allow every entry at volatility multiplier 1, but never against the
runner's own fail-closed refusals."""

from __future__ import annotations

from decimal import Decimal

from copytrade.signals.models import Signal


class RunnerEntryPolicy:
    """``positions.types.EntryPolicy``. ``vol_mult(signal)`` is ``None`` (veto) when ANY of these says no for an OPEN
    by ``signal.wallet``: the runner is stopping; ``FollowManager.refusal_reason``; ``HlWsFeed.refusal_reason`` (stale
    feed); ``Recorder.refusal_reason`` (recording stopped at the disk floor); ``AccessMonitor`` degraded. Otherwise
    ``Decimal(1)``. A refusal source that raises counts as a veto (A2)."""

    def vol_mult(self, signal: Signal) -> Decimal | None:
        raise NotImplementedError
