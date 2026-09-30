"""Compressed, day-partitioned, atomically written recordings with two hashes per file (F4.AC3, F4.AC7).

Layout: below ``recordings_dir``; the relative POSIX path of a file contains its stream name, its UTC day
(``YYYY-MM-DD``, by ``receive_ts_ms``) and, for per-coin streams, the coin (percent-encoded, so no character is illegal
on Windows and no name can climb out of the directory). The candle streams are also partitioned by the UTC hour of the
candle's open time (F4.AC9: one file per coin, interval and hour). A partition can have several files (a restart, a
disk-floor stop, a late candle); their names never collide and none is ever overwritten.

A file is a sequence of ``.xz`` streams, one per segment, so each sealed segment is a self-contained block whose bytes
never change. Records are serialised and held in memory until their segment is sealed (every
``recording.segment_hash_minutes``, and at close). Sealing appends the segment's block to ``<name>.part`` and fsyncs it
**before** the ledger record for the segment is written, so a ledgered segment is always fully on disk.

Ledger records written here (kind: payload keys):

- ``recording_segment``: ``stream``, ``coin``, ``day``, ``segment`` (0, 1, ... within the file), ``start_ms`` and
  ``end_ms`` (the earliest and latest receive time in the segment), ``record_count``, ``segment_hash``, ``prev_hash``
  (64 zeros for a stream's first segment) and, for the store's own reading, ``file``, ``hour_ms`` (candle streams,
  else ``None``), ``byte_start`` and ``byte_end`` (the block's place in the file).
  ``segment_hash = sha256(bytes.fromhex(prev_hash) + b"".join(serialize_record(r) + b"\\n" for r in segment))``. One is
  written for every open file that has new records; the chain runs per stream and coin, across files and days.
- ``recording_file_closed``: ``path``, ``stream``, ``coin``, ``day``, ``stream_sha256``, ``transport_sha256``,
  ``byte_count`` (stored bytes), ``record_count``, ``reason`` (``normal``, ``day_end``, ``disk_floor``, ``shutdown`` or
  ``recovered``). Exactly one per file, written before the file gets its final name.
- ``day_complete``: ``day`` and ``files`` (the closed relative paths), written by ``tick`` once
  ``storage.upload_delay_min`` minutes after 00:00 UTC have passed and every file of that day is closed.

Readers see only data covered by a ledgered hash: the blocks of sealed segments. Unhashed data (the records buffered
for the open segment, and after a crash everything after the last sealed segment) is a gap: never returned.

Construction recovers what a crash left behind: a ``.part`` file keeps its sealed segments and loses the rest, and is
closed with reason ``recovered``; one whose closing record was already written just gets its final name; one with no
sealed segment is removed.

Cost note: sealing compresses every open file in the tick that finds its segment due, so that tick is long (seconds for
250 coins). Records are stamped by the caller before it starts, so the stamps stay correct; F21 measures the real figure
in the 24 h dry run.
"""

from __future__ import annotations

import hashlib
import logging
import lzma
import os
import sys
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.errors import CopytradeError
from copytrade.ledger.records import LedgerRecord
from copytrade.ledger.store import Ledger, read_records
from copytrade.recorder.records import (
    STREAM_CANDLE_1H,
    STREAM_CANDLE_1M,
    Record,
    deserialize_record,
    serialize_record,
)

KIND_SEGMENT = "recording_segment"
KIND_FILE_CLOSED = "recording_file_closed"
KIND_DAY_COMPLETE = "day_complete"

GENESIS_HASH = "0" * 64
PART_SUFFIX = ".part"
FINAL_SUFFIX = ".xz"
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
CLOSE_REASONS = frozenset({"normal", "day_end", "disk_floor", "shutdown", "recovered"})
HOUR_PARTITIONED_STREAMS = frozenset({STREAM_CANDLE_1M, STREAM_CANDLE_1H})
# xz preset 1 compresses 5-minute blocks of (synthetic) order books to under a tenth of their JSON size at several
# times the speed of the default preset, which matters because sealing happens inside the recorder's tick.
DEFAULT_COMPRESSION_PRESET = 1
DECODED_BLOCK_CACHE_SIZE = 64

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NAME_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
_NAME_MAX_CHARS = 96
_NO_COIN_NAME = "_all"
_O_BINARY = getattr(os, "O_BINARY", 0)
_log = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class FileKey:
    """The partition a record is stored in: stream, coin, UTC day of its receive time and, for the candle streams,
    the UTC hour (epoch ms, on the hour) in which the candle opened."""

    stream: str
    coin: str | None
    day: str
    hour_ms: int | None


def file_key(record: Record) -> FileKey:
    """The partition of ``record``.

    Raises:
        ValueError: the receive time is outside the supported dates, or a candle record has no exchange time.
    """
    try:
        day = (_EPOCH + timedelta(milliseconds=record.receive_ts_ms)).date().isoformat()
    except OverflowError as exc:
        raise ValueError("receive_ts_ms is outside the supported dates") from exc
    hour_ms = None
    if record.stream in HOUR_PARTITIONED_STREAMS:
        if record.exchange_ts_ms is None:
            raise ValueError("a candle record needs its open time as exchange_ts_ms")
        hour_ms = record.exchange_ts_ms - record.exchange_ts_ms % HOUR_MS
    return FileKey(record.stream, record.coin, day, hour_ms)


def _day_deadline_ms(day: str, upload_delay_ms: int) -> int:
    """When a UTC day's files are due to be closed and marked complete: its end plus the upload delay."""
    start = (datetime.fromisoformat(day).replace(tzinfo=UTC) - _EPOCH) // timedelta(milliseconds=1)
    return start + DAY_MS + upload_delay_ms


def _encode_name(text: str) -> str:
    """Percent-encode everything but ASCII letters, digits and ``_``; very long names keep a hash of the whole."""
    encoded = "".join(c if c in _NAME_SAFE else "".join(f"%{b:02X}" for b in c.encode("utf-8")) for c in text)
    if len(encoded) > _NAME_MAX_CHARS:
        return f"{encoded[:64]}~{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
    return encoded


def _fsync_directory(directory: Path) -> None:
    """Make a rename durable (POSIX; Windows has no directory fsync)."""
    if sys.platform == "win32":  # pragma: no cover
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _hex_sha256(*chunks: bytes) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


# --- the index: what the ledger says about the files ------------------------------------------------------------------


@dataclass(frozen=True)
class _Block:
    """One sealed segment: its bytes ``[start, end)`` in the file and what the ledger recorded about it."""

    start: int
    end: int
    min_ts: int
    max_ts: int
    count: int
    seq: int  # ledger sequence number of the segment record: the order in which the blocks were sealed
    prev_hash: str
    segment_hash: str


@dataclass
class _FileInfo:
    path: str
    stream: str
    coin: str | None
    day: str
    hour_ms: int | None
    blocks: list[_Block] = field(default_factory=list)
    closed: ClosedFile | None = None


class _Series:
    """The blocks of one stream and coin in sealing order, with the running maximum of their latest receive times."""

    def __init__(self) -> None:
        self.entries: list[tuple[_FileInfo, _Block]] = []
        self.prefix_max_ts: list[int] = []

    def add(self, info: _FileInfo, block: _Block) -> None:
        self.entries.append((info, block))
        previous = self.prefix_max_ts[-1] if self.prefix_max_ts else block.max_ts
        self.prefix_max_ts.append(max(previous, block.max_ts))


class _Index:
    """Everything the readers and the writer need from the ledger's recording records."""

    def __init__(self) -> None:
        self.files: dict[str, _FileInfo] = {}
        self.closed_in_order: list[ClosedFile] = []
        self.closed_by_day: dict[str, list[str]] = {}
        self.completed_days: set[str] = set()
        self.series: dict[tuple[str, str | None], _Series] = {}
        self.hours: dict[tuple[str, str | None, int], list[_FileInfo]] = {}
        self.chain: dict[tuple[str, str | None], str] = {}
        self.lower_paths: set[str] = set()  # every recorded path, lower-cased (for the collision check on Windows)

    @classmethod
    def build(cls, records: Iterable[LedgerRecord]) -> _Index:
        index = cls()
        for record in records:
            index.apply(record)
        return index

    def apply(self, record: LedgerRecord) -> None:
        try:
            if record.kind == KIND_SEGMENT:
                self._apply_segment(record)
            elif record.kind == KIND_FILE_CLOSED:
                self._apply_closed(record)
            elif record.kind == KIND_DAY_COMPLETE:
                self.completed_days.add(record.payload["day"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecordingIntegrityError(f"malformed {record.kind} record at ledger seq {record.seq}") from exc

    def _apply_segment(self, record: LedgerRecord) -> None:
        p = record.payload
        info = self.files.get(p["file"])
        if info is None:
            info = self.files[p["file"]] = _FileInfo(p["file"], p["stream"], p["coin"], p["day"], p["hour_ms"])
            self.lower_paths.add(info.path.lower())
            if info.hour_ms is not None:
                self.hours.setdefault((info.stream, info.coin, info.hour_ms), []).append(info)
        block = _Block(
            start=p["byte_start"],
            end=p["byte_end"],
            min_ts=p["start_ms"],
            max_ts=p["end_ms"],
            count=p["record_count"],
            seq=record.seq,
            prev_hash=p["prev_hash"],
            segment_hash=p["segment_hash"],
        )
        info.blocks.append(block)
        self.series.setdefault((info.stream, info.coin), _Series()).add(info, block)
        self.chain[(info.stream, info.coin)] = block.segment_hash

    def _apply_closed(self, record: LedgerRecord) -> None:
        p = record.payload
        closed = ClosedFile(
            path=p["path"],
            stream=p["stream"],
            coin=p["coin"],
            day=p["day"],
            stream_sha256=p["stream_sha256"],
            transport_sha256=p["transport_sha256"],
            byte_count=p["byte_count"],
            record_count=p["record_count"],
            reason=p["reason"],
        )
        info = self.files.get(closed.path)
        if info is None:  # a closed file without any segment cannot be read, but it is still listed
            info = self.files[closed.path] = _FileInfo(closed.path, closed.stream, closed.coin, closed.day, None)
            self.lower_paths.add(closed.path.lower())
        info.closed = closed
        self.closed_in_order.append(closed)
        self.closed_by_day.setdefault(closed.day, []).append(closed.path)


# --- reading ---------------------------------------------------------------------------------------------------------


class RecordingReader:
    """Read-only local implementation of the store interface every reader depends on (§10 collision rule 6).

    Reads the ledger's recording records on every call (``ledger_records`` is called each time), so it always sees what
    the writer has hashed by then; ``pinned`` gives a view over one such reading for callers that make many calls.
    Every block it decodes is checked against its ledgered segment hash, and reading a closed file also checks both
    ledgered file hashes. The most recently used decoded blocks are kept, keyed by their segment hash, so a block that
    was verified once is not read from disk again while it stays cached.
    """

    def __init__(self, recordings_dir: Path, ledger_records: Callable[[], Iterable[LedgerRecord]]) -> None:
        self._dir = recordings_dir
        self._ledger_records = ledger_records
        self._pinned_index: _Index | None = None
        self._cache: OrderedDict[tuple[str, int, int, str], tuple[Record, ...]] = OrderedDict()

    @classmethod
    def from_ledger_dir(cls, recordings_dir: Path, ledger_dir: Path) -> RecordingReader:
        """Read the ledger with the lock-free reader (``copytrade.ledger.store.read_records``)."""
        return RecordingReader(recordings_dir, lambda: read_records(ledger_dir))

    def pinned(self) -> RecordingReader:
        """A view of this reader that reads the ledger once, now, instead of on every call."""
        view = RecordingReader(self._dir, self._ledger_records)
        view._pinned_index = self._snapshot()
        view._cache = self._cache
        return view

    def _snapshot(self) -> _Index:
        return self._pinned_index if self._pinned_index is not None else _Index.build(self._ledger_records())

    def files(self) -> tuple[ClosedFile, ...]:
        """Every closed file, in ledger order.

        The ledger is the truth: a file is listed as soon as its close is ledgered, even if the final name does not
        exist yet (the rename follows the ledger record); reading it then goes through the ``.part`` name."""
        return tuple(self._snapshot().closed_in_order)

    def read_file(self, path: str) -> tuple[Record, ...]:
        """All records of a closed file (relative path as ledgered), after checking both ledgered hashes.

        Raises:
            RecordingIntegrityError: unknown path, missing file, or either hash differs.
        """
        return tuple(deserialize_record(line) for line in self._closed_lines(path))

    def read_stream_bytes(self, path: str) -> bytes:
        """The decompressed stream of a closed file: ``b"".join(serialize_record(r) + b"\\n" for r in records)``."""
        return b"".join(line + b"\n" for line in self._closed_lines(path))

    def scan(self, stream: str, coin: str | None, from_ms: int, to_ms: int) -> Iterator[Record]:
        """Records of ``stream`` (and ``coin``) with ``from_ms <= receive_ts_ms < to_ms``, in receive order,
        hashed data only."""
        return self._scan(self._snapshot(), stream, coin, from_ms, to_ms)

    def as_of(self, stream: str, coin: str | None, t_ms: int) -> Record | None:
        """The latest hashed record with ``receive_ts_ms <= t_ms``; never a record received after ``t_ms``."""
        series = self._snapshot().series.get((stream, coin))
        if series is None:
            return None
        best: tuple[tuple[int, int, int], Record] | None = None
        for position in range(len(series.entries) - 1, -1, -1):
            if best is not None and series.prefix_max_ts[position] < best[0][0]:
                break  # no earlier block reaches as far as the best record found
            info, block = series.entries[position]
            if block.min_ts > t_ms or (best is not None and block.max_ts < best[0][0]):
                continue
            for _, records in self._decode(info, [block]):
                for offset, record in enumerate(records):
                    rank = (record.receive_ts_ms, block.seq, offset)
                    if record.receive_ts_ms <= t_ms and (best is None or rank > best[0]):
                        best = (rank, record)
        return None if best is None else best[1]

    def scan_hour(self, stream: str, coin: str | None, hour_ms: int) -> Iterator[Record]:
        """Every hashed record of an hour-partitioned stream (the candle streams) whose partition hour is ``hour_ms``,
        whenever it was received, in receive order."""
        infos = self._snapshot().hours.get((stream, coin, hour_ms), [])
        return iter(self._ordered([(info, list(info.blocks)) for info in infos], lambda _: True))

    def coins(self, stream: str, from_ms: int, to_ms: int) -> tuple[str, ...]:
        """The coins with at least one hashed record of ``stream`` with ``from_ms <= receive_ts_ms < to_ms``, sorted."""
        index = self._snapshot()
        return tuple(
            sorted(
                coin
                for series_stream, coin in index.series
                if series_stream == stream
                and coin is not None
                and next(self._scan(index, stream, coin, from_ms, to_ms), None) is not None
            )
        )

    # --- internals ---------------------------------------------------------------------------------------------------

    def _scan(self, index: _Index, stream: str, coin: str | None, from_ms: int, to_ms: int) -> Iterator[Record]:
        series = index.series.get((stream, coin))
        if series is None or to_ms <= from_ms:
            return iter(())
        wanted: dict[str, tuple[_FileInfo, list[_Block]]] = {}
        for info, block in series.entries:
            if block.max_ts >= from_ms and block.min_ts < to_ms:
                wanted.setdefault(info.path, (info, []))[1].append(block)
        return iter(self._ordered(wanted.values(), lambda ts: from_ms <= ts < to_ms))

    def _ordered(self, groups: Iterable[tuple[_FileInfo, list[_Block]]], keep: Callable[[int], bool]) -> list[Record]:
        """The records of the given blocks that pass ``keep`` (a test of the receive time), by receive time, then by
        the order in which they were sealed and written."""
        ranked: list[tuple[int, int, int, Record]] = []
        for info, blocks in groups:
            for block, records in self._decode(info, blocks):
                ranked.extend(
                    (record.receive_ts_ms, block.seq, offset, record)
                    for offset, record in enumerate(records)
                    if keep(record.receive_ts_ms)
                )
        ranked.sort(key=lambda item: item[:3])
        return [item[3] for item in ranked]

    def _decode(self, info: _FileInfo, blocks: Sequence[_Block]) -> list[tuple[_Block, tuple[Record, ...]]]:
        decoded: list[tuple[_Block, tuple[Record, ...]]] = []
        closed_bytes: bytes | None = None
        for block in blocks:
            key = (info.path, block.start, block.end, block.segment_hash)
            records = self._cache.get(key)
            if records is None:
                if info.closed is not None and closed_bytes is None:
                    closed_bytes = self._verified_closed_bytes(info.closed)
                packed = self._block_bytes(info, block, closed_bytes)
                try:
                    records = tuple(deserialize_record(line) for line in _unpack(packed, block, info.path))
                except ValueError as exc:
                    raise RecordingIntegrityError(f"{info.path}: a stored record is malformed") from exc
                self._cache[key] = records
                if len(self._cache) > DECODED_BLOCK_CACHE_SIZE:
                    self._cache.popitem(last=False)
            else:
                self._cache.move_to_end(key)
            decoded.append((block, records))
        return decoded

    def _verified_closed_bytes(self, closed: ClosedFile) -> bytes:
        """The transport bytes of a closed file, checked against the ledgered byte count and transport sha256.

        The writer ledgers ``recording_file_closed`` before it renames ``<name>.xz.part`` to ``<name>.xz`` (and a crash
        can leave the file under the ``.part`` name until the restart), so a reader that sees the closed record may
        find only the ``.part`` name. It is read with exactly the same checks as the final name."""
        data = self._read_either_name(closed.path)
        if len(data) != closed.byte_count or _hex_sha256(data) != closed.transport_sha256:
            raise RecordingIntegrityError(f"{closed.path} does not match its ledgered transport sha256")
        return data

    def _read_either_name(self, path: str) -> bytes:
        final = self._dir / path
        # final, then the part name, then final again: the writer may rename between the two attempts
        for candidate in (final, self._dir / (path + PART_SUFFIX), final):
            try:
                return candidate.read_bytes()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise RecordingIntegrityError(f"{path} cannot be read ({type(exc).__name__})") from exc
        raise RecordingIntegrityError(f"{path} is missing")

    def _block_bytes(self, info: _FileInfo, block: _Block, closed_bytes: bytes | None) -> bytes:
        if closed_bytes is not None:
            return closed_bytes[block.start : block.end]
        for path in (self._dir / (info.path + PART_SUFFIX), self._dir / info.path):  # the writer may rename meanwhile
            try:
                with path.open("rb") as handle:
                    handle.seek(block.start)
                    return handle.read(block.end - block.start)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise RecordingIntegrityError(f"{info.path} cannot be read ({type(exc).__name__})") from exc
        raise RecordingIntegrityError(f"{info.path} is missing")

    def _closed_lines(self, path: str) -> list[bytes]:
        """The serialised record lines of a closed file after both file hashes and every segment hash were checked."""
        info = self._snapshot().files.get(path)
        if info is None or info.closed is None:
            raise RecordingIntegrityError(f"{path} is not a closed recording file")
        data = self._verified_closed_bytes(info.closed)
        lines: list[bytes] = []
        for block in info.blocks:
            lines.extend(_unpack(data[block.start : block.end], block, path))
        if _hex_sha256(*(line + b"\n" for line in lines)) != info.closed.stream_sha256:
            raise RecordingIntegrityError(f"{path} does not match its ledgered stream sha256")
        if len(lines) != info.closed.record_count:
            raise RecordingIntegrityError(f"{path} does not hold its ledgered record count")
        return lines


def _unpack(packed: bytes, block: _Block, path: str) -> list[bytes]:
    """Decompress one block, check it against its ledgered segment hash and record count, and split it into lines."""
    try:
        raw = lzma.decompress(packed, format=lzma.FORMAT_XZ)
    except (lzma.LZMAError, EOFError) as exc:
        raise RecordingIntegrityError(f"{path}: a block does not decompress") from exc
    if _hex_sha256(bytes.fromhex(block.prev_hash), raw) != block.segment_hash:
        raise RecordingIntegrityError(f"{path}: a block does not match its ledgered segment hash")
    lines = raw.split(b"\n")
    if lines.pop() != b"" or len(lines) != block.count:
        raise RecordingIntegrityError(f"{path}: a block does not hold its ledgered record count")
    return lines


# --- writing ---------------------------------------------------------------------------------------------------------


class _OpenFile:
    """A file being written: its buffered (unsealed) lines and the running state of what is sealed."""

    def __init__(self, key: FileKey, path: str, part: Path, deadline_ms: int) -> None:
        self.key = key
        self.path = path
        self.part = part
        self.deadline_ms = deadline_ms  # from then on the file is due to be closed (day end plus upload delay)
        self.lines: list[bytes] = []
        self.min_ts = 0
        self.max_ts = 0
        self.sealed_bytes = 0
        self.sealed_records = 0
        self.segments = 0
        self.stream_hash = hashlib.sha256()
        self.transport_hash = hashlib.sha256()

    def buffer(self, line: bytes, receive_ts_ms: int) -> None:
        if not self.lines:
            self.min_ts = self.max_ts = receive_ts_ms
        else:
            self.min_ts = min(self.min_ts, receive_ts_ms)
            self.max_ts = max(self.max_ts, receive_ts_ms)
        self.lines.append(line)


class RecordingStore(RecordingReader):
    """The writer. Uses the injected clock for segment sealing and the day rollover. Single writer per directory.

    There is no way to delete, replace or prune a recording (F4.AC2; retention is F23.AC2's).
    """

    def __init__(
        self,
        *,
        config: Mapping[str, Any],
        clock: Clock,
        ledger: Ledger,
        recordings_dir: Path,
        compression_level: int | None = None,
    ) -> None:
        preset = DEFAULT_COMPRESSION_PRESET if compression_level is None else compression_level
        if type(preset) is not int or not 0 <= preset <= 9:
            raise ValueError("compression_level must be an int from 0 to 9")
        super().__init__(recordings_dir, ledger.records)
        self._preset = preset
        self._segment_ms = int(config["recording.segment_hash_minutes"]) * 60_000
        self._upload_delay_ms = int(config["storage.upload_delay_min"]) * 60_000
        self._clock = clock
        self._ledger = ledger
        self._live = _Index.build(ledger.records())
        self._open: dict[FileKey, _OpenFile] = {}
        self._next_seal_ms: int | None = None
        recordings_dir.mkdir(parents=True, exist_ok=True)
        self._recover()
        self._pending_days = {
            day: _day_deadline_ms(day, self._upload_delay_ms)
            for day in self._live.closed_by_day
            if day not in self._live.completed_days
        }

    def _snapshot(self) -> _Index:
        return self._live

    # --- writing ---------------------------------------------------------------------------------------------------

    def append(self, record: Record) -> FileKey:
        """Buffer a record into its stream/coin/day file (day of ``receive_ts_ms``) and return that file's partition.

        Raises:
            ValueError: see ``file_key``.
        """
        key = file_key(record)
        target = self._open.get(key) or self._open_file(key)
        target.buffer(serialize_record(record) + b"\n", record.receive_ts_ms)
        return key

    def tick(self) -> None:
        """Seal segments that are due and close and mark finished days. Call at least once per second."""
        now = self._clock.now_ms()
        if self._next_seal_ms is None:
            self._next_seal_ms = now + self._segment_ms
        elif now >= self._next_seal_ms:
            for target in list(self._open.values()):
                self._seal(target)
            while self._next_seal_ms <= now:
                self._next_seal_ms += self._segment_ms
        for target in list(self._open.values()):
            if now >= target.deadline_ms:
                self._close(target, "day_end")
        self._complete_days(now)

    def close_all(self, reason: str) -> None:
        """Seal what is open and close every open file atomically with the given close reason."""
        _check_reason(reason)
        for target in list(self._open.values()):
            self._close(target, reason)

    def close_files(self, keys: Iterable[FileKey], reason: str) -> None:
        """Close the open files of these partitions (partitions with nothing open are skipped)."""
        _check_reason(reason)
        for key in keys:
            target = self._open.get(key)
            if target is not None:
                self._close(target, reason)

    # --- files -----------------------------------------------------------------------------------------------------

    def _open_file(self, key: FileKey) -> _OpenFile:
        path = self._reserve_path(key)
        part = self._dir / (path + PART_SUFFIX)
        part.parent.mkdir(parents=True, exist_ok=True)
        os.close(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o600))
        target = _OpenFile(key, path, part, _day_deadline_ms(key.day, self._upload_delay_ms))
        self._open[key] = target
        return target

    def _reserve_path(self, key: FileKey) -> str:
        """A relative path no file, open file or ledger record uses (compared case-insensitively, for Windows)."""
        taken = self._live.lower_paths | {t.path.lower() for t in self._open.values()}
        name = _NO_COIN_NAME if key.coin is None else _encode_name(key.coin)
        if key.hour_ms is not None:
            name += "-" + (_EPOCH + timedelta(milliseconds=key.hour_ms)).strftime("%Y%m%d%H")
        number = 1
        while True:
            path = f"{key.stream}/{key.day}/{name}-{number:04d}{FINAL_SUFFIX}"
            if (
                path.lower() not in taken
                and not (self._dir / path).exists()
                and not (self._dir / (path + PART_SUFFIX)).exists()
            ):
                return path
            number += 1

    def _seal(self, target: _OpenFile) -> None:
        """Write the buffered records as one block, then ledger the segment (in that order)."""
        if not target.lines:
            return
        key = target.key
        raw = b"".join(target.lines)
        previous = self._live.chain.get((key.stream, key.coin), GENESIS_HASH)
        packed = lzma.compress(raw, format=lzma.FORMAT_XZ, preset=self._preset)
        start = target.sealed_bytes
        with target.part.open(
            "r+b"
        ) as handle:  # rewrites from the sealed end, so an earlier failed attempt is harmless
            handle.seek(start)
            handle.write(packed)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        record = self._ledger.append(
            KIND_SEGMENT,
            {
                "stream": key.stream,
                "coin": key.coin,
                "day": key.day,
                "segment": target.segments,
                "start_ms": target.min_ts,
                "end_ms": target.max_ts,
                "record_count": len(target.lines),
                "segment_hash": _hex_sha256(bytes.fromhex(previous), raw),
                "prev_hash": previous,
                "file": target.path,
                "hour_ms": key.hour_ms,
                "byte_start": start,
                "byte_end": start + len(packed),
            },
        )
        self._live.apply(record)
        target.stream_hash.update(raw)
        target.transport_hash.update(packed)
        target.sealed_bytes += len(packed)
        target.sealed_records += len(target.lines)
        target.segments += 1
        target.lines = []

    def _close(self, target: _OpenFile, reason: str) -> None:
        """Seal the tail, ledger the closing record, then give the file its final name."""
        self._seal(target)
        key = target.key
        record = self._ledger.append(
            KIND_FILE_CLOSED,
            {
                "path": target.path,
                "stream": key.stream,
                "coin": key.coin,
                "day": key.day,
                "stream_sha256": target.stream_hash.hexdigest(),
                "transport_sha256": target.transport_hash.hexdigest(),
                "byte_count": target.sealed_bytes,
                "record_count": target.sealed_records,
                "reason": reason,
            },
        )
        self._live.apply(record)
        del self._open[key]
        self._pending_days.setdefault(key.day, _day_deadline_ms(key.day, self._upload_delay_ms))
        self._publish(target.part, self._dir / target.path)

    @staticmethod
    def _publish(part: Path, final: Path) -> None:
        os.replace(part, final)
        _fsync_directory(final.parent)

    def _complete_days(self, now: int) -> None:
        for day, deadline in sorted(self._pending_days.items()):
            if now < deadline or any(t.key.day == day for t in self._open.values()):
                continue
            del self._pending_days[day]
            if day not in self._live.completed_days:
                record = self._ledger.append(
                    KIND_DAY_COMPLETE, {"day": day, "files": list(self._live.closed_by_day.get(day, ()))}
                )
                self._live.apply(record)

    # --- crash recovery --------------------------------------------------------------------------------------------

    def _recover(self) -> None:
        for part in sorted(self._dir.rglob("*" + PART_SUFFIX)):
            path = part.relative_to(self._dir).as_posix()[: -len(PART_SUFFIX)]
            info = self._live.files.get(path)
            if info is None or not info.blocks:
                part.unlink()  # nothing in it was ever hashed: it is a gap
                _log.warning("recording file with no sealed segment removed", extra={"event": "recording_empty_part"})
            elif info.closed is not None:
                data = part.read_bytes()
                if len(data) != info.closed.byte_count or _hex_sha256(data) != info.closed.transport_sha256:
                    raise RecordingIntegrityError(f"{path} was closed but its bytes do not match the ledger")
                self._publish(part, self._dir / path)
            else:
                self._recover_open(part, info)

    def _recover_open(self, part: Path, info: _FileInfo) -> None:
        """Keep the sealed segments of a file the crash left open, drop the unhashed tail and close it."""
        sealed_end = info.blocks[-1].end
        if part.stat().st_size < sealed_end:
            raise RecordingIntegrityError(f"{info.path} is shorter than its last sealed segment")
        with part.open("r+b") as handle:
            handle.truncate(sealed_end)
            handle.flush()
            os.fsync(handle.fileno())
        data = part.read_bytes()
        stream_hash = hashlib.sha256()
        records = 0
        for block in info.blocks:
            for line in _unpack(data[block.start : block.end], block, info.path):
                stream_hash.update(line + b"\n")
                records += 1
        record = self._ledger.append(
            KIND_FILE_CLOSED,
            {
                "path": info.path,
                "stream": info.stream,
                "coin": info.coin,
                "day": info.day,
                "stream_sha256": stream_hash.hexdigest(),
                "transport_sha256": _hex_sha256(data),
                "byte_count": len(data),
                "record_count": records,
                "reason": "recovered",
            },
        )
        self._live.apply(record)
        self._publish(part, self._dir / info.path)
        _log.warning(
            "recording file recovered after a crash",
            extra={"event": "recording_recovered", "records": records, "bytes": len(data)},
        )


def _check_reason(reason: str) -> None:
    if reason not in CLOSE_REASONS:
        raise ValueError(f"unknown close reason {reason!r}")
