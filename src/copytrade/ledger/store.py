"""The append-only, hash-chained ledger (F2.AC1, AC3, AC6).

Interface stub written by the test designer. The developer owns the implementation.

Storage contract the tests rely on: one file ``LEDGER_FILENAME`` inside the ledger directory, one record
per line (UTF-8, ``\\n`` terminated), each line exactly the stored form of one record, so that altering
any single byte of a line makes verification fail at that line's sequence number (1-based position).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from copytrade.core.clock import Clock
from copytrade.ledger.records import DecisionRecord, FillRecord, LedgerRecord, TradeRecord

LEDGER_FILENAME = "ledger.jsonl"


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of walking the chain. ``failed_seq`` and ``reason`` are ``None`` when ``ok``."""

    ok: bool
    record_count: int
    failed_seq: int | None
    reason: str | None


def verify_ledger(directory: Path) -> VerificationResult:
    """Read-only verification of the ledger in ``directory`` (never raises for corruption, never repairs).

    An unterminated final line (a torn write) is not counted and not an error. A missing or empty ledger
    is valid with 0 records.
    """
    raise NotImplementedError


def read_records(directory: Path) -> Iterator[LedgerRecord]:
    """Read-only iteration in sequence order, verifying the chain while reading.

    Works while a writer holds the directory. Ignores (without touching) an unterminated final line.

    Raises:
        LedgerCorruptError: when the record at ``seq`` fails verification, raised before that record is yielded.
    """
    raise NotImplementedError


class Ledger:
    """Single-writer handle. No update and no delete exist."""

    @classmethod
    def open(cls, directory: Path, *, clock: Clock) -> Self:
        """Create the directory if needed, take the writer lock, verify the whole chain, and repair a torn tail.

        Raises:
            LedgerCorruptError: verification failed (``seq`` names the record). Also logs an ERROR on the
                ``copytrade.ledger`` logger naming the seq.
            LedgerLockedError: another live writer holds the directory.
        """
        raise NotImplementedError

    def append(self, kind: str, payload: Mapping[str, Any], *, client_order_id: str | None = None) -> LedgerRecord:
        """Durably append one record (written and fsynced before returning) and return it.

        Raises:
            TypeError, ValueError: bad ``kind`` (must match ``[a-z][a-z0-9_]*``) or payload; nothing is
                written, no sequence number is consumed and the ledger stays usable.
            DuplicateClientOrderIdError: ``client_order_id`` already present; nothing is written.
            LedgerWriteError: the write or fsync failed, or the ledger failed earlier. The ledger then
                refuses every later append.
        """
        raise NotImplementedError

    def append_decision(self, decision: DecisionRecord) -> LedgerRecord:
        """Append ``decision`` as a ``decision`` record."""
        raise NotImplementedError

    def append_fill(self, fill: FillRecord) -> LedgerRecord:
        """Append ``fill`` as a ``fill`` record (a client order ID may have several fills)."""
        raise NotImplementedError

    def append_trade(self, trade: TradeRecord) -> LedgerRecord:
        """Append ``trade`` as a ``trade`` record."""
        raise NotImplementedError

    def has_client_order_id(self, client_order_id: str) -> bool:
        """Whether a record was appended with this ``client_order_id``."""
        raise NotImplementedError

    def records(self) -> Iterator[LedgerRecord]:
        """All records in sequence order."""
        raise NotImplementedError

    def verify(self) -> VerificationResult:
        """Verify the stored chain again."""
        raise NotImplementedError

    @property
    def last_seq(self) -> int:
        """Sequence number of the last record, 0 when empty."""
        raise NotImplementedError

    @property
    def failed(self) -> bool:
        """True once an append failed (F2.AC6). The engine reads this to enter its fail-closed state."""
        raise NotImplementedError

    def close(self) -> None:
        """Release the writer lock. Idempotent."""
        raise NotImplementedError

    def __enter__(self) -> Self:
        raise NotImplementedError

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        raise NotImplementedError
