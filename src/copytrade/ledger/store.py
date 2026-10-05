"""The append-only, hash-chained ledger (F2.AC1, AC3, AC6).

Storage: one file ``LEDGER_FILENAME`` inside the ledger directory, one record per line (ASCII JSON, ``\\n``
terminated). Each line is exactly the canonical stored form of one record (``records.encode_line``), and
verification re-derives that form, so altering any single byte of a line makes verification fail at that
line's sequence number (its 1-based position). The chain is ``h_n = sha256(h_{n-1} || canonical_bytes(n))``.

Durability: an append is one ``write`` of the whole line followed by ``fsync``; it returns only after that.
A crash can therefore leave at most one unterminated tail, which readers ignore and the next writer removes.
If a write fails, the ledger marks itself failed and refuses every later append (fail closed, A2).

Single writer: the directory holds ``LOCK_FILENAME``, an OS lock taken by ``Ledger.open`` and released by
``close`` or by the death of the process. Readers (``verify_ledger``, ``read_records`` and the export)
take no lock and work while the engine writes.
"""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import re
import sys
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from copytrade.core.clock import Clock, TimeSource, Timestamp
from copytrade.ledger.codec import decode_value, encode_value
from copytrade.ledger.errors import (
    DuplicateClientOrderIdError,
    LedgerCorruptError,
    LedgerLockedError,
    LedgerWriteError,
)
from copytrade.ledger.records import (
    GENESIS_HASH,
    KIND_DECISION,
    KIND_FILL,
    KIND_TRADE,
    RESERVED_KINDS,
    DecisionRecord,
    FillRecord,
    LedgerRecord,
    TradeRecord,
    canonical_bytes,
    decode_line,
    encode_line,
)

LEDGER_FILENAME = "ledger.jsonl"
LOCK_FILENAME = "ledger.lock"

_log = logging.getLogger("copytrade.ledger")
_KIND = re.compile(r"[a-z][a-z0-9_]*")
_O_BINARY = getattr(os, "O_BINARY", 0)

if sys.platform == "win32":  # pragma: no cover - exercised on the PO's Windows PC
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EDEADLOCK):  # the byte is locked by another process
                return False
            raise
        return True

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of walking the chain. ``failed_seq`` and ``reason`` are ``None`` when ``ok``."""

    ok: bool
    record_count: int
    failed_seq: int | None
    reason: str | None


def _next_hash(previous_hex: str, record: LedgerRecord) -> str:
    return hashlib.sha256(bytes.fromhex(previous_hex) + canonical_bytes(record)).hexdigest()


def _corrupt(seq: int, reason: str) -> LedgerCorruptError:
    return LedgerCorruptError(f"ledger corrupt at seq {seq}: {reason}", seq=seq, reason=reason)


def _check_line(line: bytes, seq: int, previous_hash: str) -> LedgerRecord:
    """Verify one stored line as record number ``seq``; return it or raise ``LedgerCorruptError``."""
    try:
        record = decode_line(line[:-1])
    except ValueError as exc:
        raise _corrupt(seq, "line is not a well-formed record") from exc
    if record.seq != seq:
        raise _corrupt(seq, f"sequence number is {record.seq}, expected {seq}")
    if record.hash != _next_hash(previous_hash, record):
        raise _corrupt(seq, "hash does not match the chain")
    if encode_line(record) != line:
        raise _corrupt(seq, "stored bytes are not the canonical form")
    return record


def _walk(directory: Path) -> Iterator[tuple[LedgerRecord, int]]:
    """Yield ``(record, end offset)`` for every complete record, verifying as it goes.

    An unterminated final line (a torn write) is not yielded and is not an error. A missing file is empty.
    """
    try:
        handle = (directory / LEDGER_FILENAME).open("rb")
    except FileNotFoundError:
        return
    previous_hash = GENESIS_HASH
    offset = 0
    seq = 0
    with handle:
        for line in handle:
            if not line.endswith(b"\n"):
                return
            seq += 1
            record = _check_line(line, seq, previous_hash)
            previous_hash = record.hash
            offset += len(line)
            yield record, offset


def verify_ledger(directory: Path) -> VerificationResult:
    """Read-only verification of the ledger in ``directory`` (never raises for corruption, never repairs).

    An unterminated final line (a torn write) is not counted and not an error. A missing or empty ledger
    is valid with 0 records.
    """
    count = 0
    try:
        for _ in _walk(directory):
            count += 1
    except LedgerCorruptError as error:
        return VerificationResult(ok=False, record_count=count, failed_seq=error.seq, reason=error.reason)
    return VerificationResult(ok=True, record_count=count, failed_seq=None, reason=None)


def read_records(directory: Path) -> Iterator[LedgerRecord]:
    """Read-only iteration in sequence order, verifying the chain while reading.

    Works while a writer holds the directory. Ignores (without touching) an unterminated final line.

    Raises:
        LedgerCorruptError: when the record at ``seq`` fails verification, raised before that record is yielded.
    """
    for record, _ in _walk(directory):
        yield record


def _fsync_directory(directory: Path) -> None:
    """Make a newly created file's directory entry durable (POSIX; Windows has no directory fsync)."""
    if sys.platform == "win32":  # pragma: no cover
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Ledger:
    """Single-writer handle. No update and no delete exist."""

    def __init__(  # noqa: PLR0913 - private constructor wiring the state ``open`` has just established
        self,
        *,
        directory: Path,
        clock: Clock,
        lock_fd: int,
        fd: int,
        last_seq: int,
        last_hash: str,
        size: int,
        client_order_ids: set[str],
    ) -> None:
        self._directory = directory
        self._clock = clock
        self._lock_fd = lock_fd
        self._fd = fd
        self._last_seq = last_seq
        self._last_hash = last_hash
        self._size = size
        self._client_order_ids = client_order_ids
        self._failed = False
        self._closed = False
        self._mutex = threading.Lock()

    @classmethod
    def open(cls, directory: Path, *, clock: Clock) -> Self:
        """Create the directory if needed, take the writer lock, verify the whole chain, and repair a torn tail.

        Raises:
            LedgerCorruptError: verification failed (``seq`` names the record). Also logs an ERROR on the
                ``copytrade.ledger`` logger naming the seq. Nothing is modified.
            LedgerLockedError: another live writer holds the directory.
        """
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_fd = os.open(directory / LOCK_FILENAME, os.O_RDWR | os.O_CREAT | _O_BINARY, 0o600)
        try:
            cls._take_lock(lock_fd)
            return cls._open_locked(directory, clock, lock_fd)
        except BaseException:
            os.close(lock_fd)  # closing the descriptor drops the lock
            raise

    @staticmethod
    def _take_lock(lock_fd: int) -> None:
        if not _try_lock(lock_fd):
            raise LedgerLockedError("another writer already holds this ledger")

    @classmethod
    def _open_locked(cls, directory: Path, clock: Clock, lock_fd: int) -> Self:
        last_seq = 0
        last_hash = GENESIS_HASH
        good_end = 0
        client_order_ids: set[str] = set()
        try:
            for record, end_offset in _walk(directory):
                last_seq, last_hash, good_end = record.seq, record.hash, end_offset
                if record.client_order_id is not None:
                    client_order_ids.add(record.client_order_id)
        except LedgerCorruptError as error:
            _log.error(
                "ledger verification failed at seq %d: %s; refusing to open",
                error.seq,
                error.reason,
                extra={"event": "ledger_corrupt", "seq": error.seq},
            )
            raise
        path = directory / LEDGER_FILENAME
        is_new = not path.exists()
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_BINARY, 0o600)
        try:
            size = os.fstat(fd).st_size
            if size > good_end:
                os.ftruncate(fd, good_end)
                os.fsync(fd)
                _log.warning(
                    "dropped an unterminated tail of %d bytes after seq %d",
                    size - good_end,
                    last_seq,
                    extra={"event": "ledger_torn_tail_dropped", "seq": last_seq},
                )
            elif is_new:
                _fsync_directory(directory)
        except BaseException:
            os.close(fd)
            raise
        return cls(
            directory=directory,
            clock=clock,
            lock_fd=lock_fd,
            fd=fd,
            last_seq=last_seq,
            last_hash=last_hash,
            size=good_end,
            client_order_ids=client_order_ids,
        )

    def append(self, kind: str, payload: Mapping[str, Any], *, client_order_id: str | None = None) -> LedgerRecord:
        """Durably append one record (written and fsynced before returning) and return it.

        The kinds ``decision``, ``fill`` and ``trade`` are reserved for the typed ``append_*`` methods, so
        every such record has been validated.

        Raises:
            TypeError, ValueError: bad ``kind`` (must match ``[a-z][a-z0-9_]*``) or payload; nothing is
                written, no sequence number is consumed and the ledger stays usable.
            DuplicateClientOrderIdError: ``client_order_id`` already present; nothing is written.
            LedgerWriteError: the write or fsync failed, or the ledger failed earlier. The ledger then
                refuses every later append.
        """
        if kind in RESERVED_KINDS:
            raise ValueError(f"kind {kind!r} is reserved for the typed append methods")
        return self._append(kind, payload, client_order_id)

    def append_decision(self, decision: DecisionRecord) -> LedgerRecord:
        """Append ``decision`` as a ``decision`` record."""
        return self._append(KIND_DECISION, decision.to_payload(), None)

    def append_fill(self, fill: FillRecord) -> LedgerRecord:
        """Append ``fill`` as a ``fill`` record (a client order ID may have several fills)."""
        return self._append(KIND_FILL, fill.to_payload(), None)

    def append_trade(self, trade: TradeRecord) -> LedgerRecord:
        """Append ``trade`` as a ``trade`` record."""
        return self._append(KIND_TRADE, trade.to_payload(), None)

    def _append(self, kind: str, payload: Mapping[str, Any], client_order_id: str | None) -> LedgerRecord:
        if type(kind) is not str or not _KIND.fullmatch(kind):
            raise ValueError("kind must match [a-z][a-z0-9_]*")
        if client_order_id is not None and (type(client_order_id) is not str or not client_order_id):
            raise ValueError("client_order_id must be a non-empty str")
        if not isinstance(payload, Mapping):
            raise TypeError("a record payload must be a mapping")
        with self._mutex:
            if self._closed:
                raise LedgerWriteError("the ledger is closed")
            if self._failed:
                raise LedgerWriteError("an earlier append failed; the ledger refuses to continue")
            if client_order_id is not None and client_order_id in self._client_order_ids:
                raise DuplicateClientOrderIdError("client order ID is already in the ledger")
            record = LedgerRecord(
                seq=self._last_seq + 1,
                ts=Timestamp(self._clock.now_ms(), TimeSource.LOCAL),
                kind=kind,
                payload=decode_value(encode_value(payload)),  # validated, and as it reads back from disk
                hash="",
                client_order_id=client_order_id,
            )
            record = replace(record, hash=_next_hash(self._last_hash, record))
            self._write_durably(encode_line(record))
            self._last_seq, self._last_hash = record.seq, record.hash
            if client_order_id is not None:
                self._client_order_ids.add(client_order_id)
            return record

    def _write_durably(self, line: bytes) -> None:
        """Write the whole line and fsync it. On any failure mark the ledger failed and try to undo the write."""
        try:
            self._write_all(line)
            os.fsync(self._fd)
        except OSError as exc:
            self._failed = True
            _log.error(
                "ledger append failed at seq %d (%s); the ledger now refuses every append",
                self._last_seq + 1,
                type(exc).__name__,
                extra={"event": "ledger_write_failed", "seq": self._last_seq + 1},
            )
            self._rollback()
            raise LedgerWriteError(f"append of seq {self._last_seq + 1} failed") from exc
        except BaseException:
            self._failed = True
            raise
        self._size += len(line)

    def _write_all(self, line: bytes) -> None:
        """``os.write`` until the whole line is out; a write that makes no progress is an ``OSError``."""
        view = memoryview(line)
        while view:
            written = os.write(self._fd, view)
            if written <= 0:
                raise OSError(errno.EIO, "the write made no progress")
            view = view[written:]

    def _rollback(self) -> None:
        """Best effort: cut the file back to the last acknowledged record. If this fails too, reopening the
        ledger drops the unterminated tail (or keeps the whole record, which then verifies)."""
        try:
            os.ftruncate(self._fd, self._size)
            os.fsync(self._fd)
        except OSError as exc:
            _log.error(
                "could not roll back the failed append (%s); reopening the ledger repairs it",
                type(exc).__name__,
                extra={"event": "ledger_rollback_failed"},
            )

    def has_client_order_id(self, client_order_id: str) -> bool:
        """Whether a record was appended with this ``client_order_id``."""
        return client_order_id in self._client_order_ids

    def records(self) -> Iterator[LedgerRecord]:
        """All records in sequence order."""
        return read_records(self._directory)

    def read_from(self, offset: int, *, kinds: frozenset[str] | None = None) -> tuple[list[LedgerRecord], int]:
        """The complete records stored at or after byte ``offset`` (only those of ``kinds`` when given; the other lines
        are not even parsed) and the offset after the last complete line (pass it to the next call). Read-only and NOT
        verified again: this process is the only writer and wrote them itself; an unterminated last line is left for
        the next call. A line that cannot be decoded is logged (its position only) and skipped: a reader of the facts
        must not stop for good at one bad line. Costs what was appended since, never the whole ledger."""
        try:
            with (self._directory / LEDGER_FILENAME).open("rb") as handle:
                handle.seek(offset)
                data = handle.read()
        except FileNotFoundError:
            return [], offset
        complete = data[: data.rfind(b"\n") + 1]
        markers = None if kinds is None else tuple(f'"kind":"{kind}"'.encode("ascii") for kind in sorted(kinds))
        wanted: list[LedgerRecord] = []
        position = offset
        for line in complete.splitlines(keepends=True):
            if markers is None or any(marker in line for marker in markers):
                try:
                    wanted.append(decode_line(line.rstrip(b"\r\n")))
                except ValueError:
                    _log.warning(
                        "an undecodable ledger line was skipped",
                        extra={"event": "ledger_line_skipped", "offset": position, "length": len(line)},
                    )
            position += len(line)
        return [r for r in wanted if kinds is None or r.kind in kinds], offset + len(complete)

    def verify(self) -> VerificationResult:
        """Verify the stored chain again."""
        return verify_ledger(self._directory)

    @property
    def last_seq(self) -> int:
        """Sequence number of the last record, 0 when empty."""
        return self._last_seq

    @property
    def failed(self) -> bool:
        """True once an append failed (F2.AC6). The engine reads this to enter its fail-closed state."""
        return self._failed

    def close(self) -> None:
        """Release the writer lock. Idempotent."""
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            try:
                os.close(self._fd)
            finally:
                os.close(self._lock_fd)  # closing the descriptor drops the lock

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
