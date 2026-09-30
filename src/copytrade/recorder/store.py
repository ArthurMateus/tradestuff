"""Compressed, day-partitioned, atomically written recordings with two hashes per file (F4.AC3, F4.AC7).

Interface stub written by the test designer. The developer owns the implementation.

Contract (behaviour the tests pin):
- Layout: below ``recordings_dir``; the relative POSIX path of a file contains its stream name, its UTC day
  (``YYYY-MM-DD``, by ``receive_ts_ms``) and, for per-coin streams, the coin. A stream/coin/day can have several
  files (a restart, a disk-floor stop, a late candle); their names never collide and none is ever overwritten.
- Open files carry a temporary suffix (``.part`` or ``.tmp``); a final name appears only by atomic rename, after
  the ``recording_file_closed`` ledger record exists. Nothing with a final name is ever partial.
- Ledger records written here (kind: payload keys):
  - ``recording_segment``: ``stream``, ``coin``, ``day``, ``segment`` (0, 1, ...), ``start_ms``, ``end_ms``,
    ``record_count``, ``segment_hash``, ``prev_hash`` (64 zeros for a stream's first segment).
    ``segment_hash = sha256(bytes.fromhex(prev_hash) + b"".join(serialize_record(r) + b"\\n" for r in segment))``.
    One is written for every open stream that has new records, every ``recording.segment_hash_minutes`` (5).
  - ``recording_file_closed``: ``path``, ``stream``, ``coin``, ``day``, ``stream_sha256``, ``transport_sha256``,
    ``byte_count`` (stored bytes), ``record_count``, ``reason`` (``normal``, ``day_end``, ``disk_floor``,
    ``shutdown`` or ``recovered``). Exactly one per file.
  - ``day_complete``: ``day`` and ``files`` (the closed relative paths), written by ``tick`` once
    ``storage.upload_delay_min`` minutes after 00:00 UTC have passed and every file of that day is closed.
- Readers see only data covered by a ledgered hash: the records of closed files and of sealed segments. Unhashed data
  (the open tail of a file, and after a crash everything after the last sealed segment) is a gap: never returned.
- Construction recovers files a crash left open: sealed segments are kept and verified, the unhashed tail is dropped,
  the file is closed with reason ``recovered``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.errors import CopytradeError
from copytrade.ledger.records import LedgerRecord
from copytrade.ledger.store import Ledger
from copytrade.recorder.records import Record

KIND_SEGMENT = "recording_segment"
KIND_FILE_CLOSED = "recording_file_closed"
KIND_DAY_COMPLETE = "day_complete"


class RecordingIntegrityError(CopytradeError):
    """A stored file does not match its ledgered stream sha256 or transport sha256 (or is not readable)."""


@dataclass(frozen=True)
class ClosedFile:
    """A ``recording_file_closed`` ledger record."""

    path: str
    stream: str
    coin: str | None
    day: str
    stream_sha256: str
    transport_sha256: str
    byte_count: int
    record_count: int
    reason: str


class RecordingReader:
    """Read-only local implementation of the store interface every reader depends on (§10 collision rule 6)."""

    def __init__(self, recordings_dir: Path, ledger_records: Callable[[], Iterable[LedgerRecord]]) -> None:
        raise NotImplementedError

    @classmethod
    def from_ledger_dir(cls, recordings_dir: Path, ledger_dir: Path) -> RecordingReader:
        """Read the ledger with the lock-free reader (``copytrade.ledger.store.read_records``)."""
        raise NotImplementedError

    def files(self) -> tuple[ClosedFile, ...]:
        """Every closed file, in ledger order."""
        raise NotImplementedError

    def read_file(self, path: str) -> tuple[Record, ...]:
        """All records of a closed file (relative path as ledgered), after checking both ledgered hashes.

        Raises:
            RecordingIntegrityError: unknown path, missing file, or either hash differs.
        """
        raise NotImplementedError

    def read_stream_bytes(self, path: str) -> bytes:
        """The decompressed stream of a closed file: ``b"".join(serialize_record(r) + b"\\n" for r in records)``."""
        raise NotImplementedError

    def scan(self, stream: str, coin: str | None, from_ms: int, to_ms: int) -> Iterator[Record]:
        """Records of ``stream`` (and ``coin``) with ``from_ms <= receive_ts_ms < to_ms``, in receive order,
        hashed data only."""
        raise NotImplementedError

    def as_of(self, stream: str, coin: str | None, t_ms: int) -> Record | None:
        """The latest hashed record with ``receive_ts_ms <= t_ms``; never a record received after ``t_ms``."""
        raise NotImplementedError


class RecordingStore(RecordingReader):
    """The writer. Uses the injected clock for segment sealing and the day rollover. Single writer per directory."""

    def __init__(
        self,
        *,
        config: Mapping[str, Any],
        clock: Clock,
        ledger: Ledger,
        recordings_dir: Path,
        compression_level: int | None = None,
    ) -> None:
        raise NotImplementedError

    def append(self, record: Record) -> None:
        """Buffer a record into its stream/coin/day file (day of ``receive_ts_ms``)."""
        raise NotImplementedError

    def tick(self) -> None:
        """Seal segments that are due and close and mark finished days. Call at least once per second."""
        raise NotImplementedError

    def close_all(self, reason: str) -> None:
        """Seal what is open and close every open file atomically with the given close reason."""
        raise NotImplementedError
