"""Errors of the paper broker (F11)."""

from __future__ import annotations

from copytrade.ledger.errors import LedgerWriteError


class PaperBrokerFailedError(LedgerWriteError):
    """The broker failed closed (F2.AC6, A2): an earlier operation raised, so its in-memory state may disagree with
    the ledger, and every later mutating call refuses. It is a ``LedgerWriteError`` because a ledger append that
    cannot be written is the case it exists for; the original exception is ``__cause__`` of the first failure."""
