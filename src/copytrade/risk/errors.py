"""Errors of the risk gate (F10)."""

from __future__ import annotations

from copytrade.core.errors import CopytradeError


class RiskStateError(CopytradeError):
    """The persisted risk state (pause flag, loss halts, drawdown) cannot be read, trusted or written.

    Entries are refused (``risk_state_unknown``) while it lasts; exits and stops are never affected.
    """
