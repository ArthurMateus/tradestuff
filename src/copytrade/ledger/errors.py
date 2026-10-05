"""Errors raised by the ledger (F2).

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from copytrade.core.errors import CopytradeError


class LedgerError(CopytradeError):
    """Base class for ledger errors."""


class LedgerCorruptError(LedgerError):
    """The stored ledger fails verification (F2.AC1).

    Attributes:
        seq: the sequence number (1-based position of the record) at which verification failed.
        reason: short human-readable reason. Never contains payload content.

    ``str(error)`` names ``seq``.
    """

    def __init__(self, message: str, *, seq: int, reason: str) -> None:
        super().__init__(message)
        self.seq = seq
        self.reason = reason


class LedgerWriteError(LedgerError):
    """An append failed (I/O error, disk full) or the ledger already failed earlier (F2.AC6).

    ``__cause__`` is the underlying ``OSError`` when there is one. After this error the ``Ledger``
    object refuses every further append; reopening it verifies and repairs a torn tail.
    """


class LedgerLockedError(LedgerError):
    """Another live writer already holds this ledger directory (single writer)."""


class DuplicateClientOrderIdError(LedgerError):
    """A client order ID is already in the ledger (A5). Nothing was appended."""
