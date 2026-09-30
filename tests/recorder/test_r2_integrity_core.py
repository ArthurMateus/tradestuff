"""F4 round 2 (senior-dev review, integrity core): seal-crash truncation, the reader race on the ``.part`` name, and
the fsync-before-ledger order.

Real F2 ledger and real store on tmp directories; only the clock is fake. The crash states are built on disk exactly
as a crash leaves them (extra bytes after the last ledgered block; a ledgered close whose rename never happened).

The reader-race tests (``test_F4_R2_a_closed_file_that_only_exists_as_part_...``) are EXPECTED TO FAIL until the
developer fixes ``RecordingReader._verified_closed_bytes`` to fall back to ``<name>.part``.
"""

from __future__ import annotations

import hashlib
import lzma
import os
from pathlib import Path
from typing import Any

import pytest

from copytrade.ledger.store import Ledger
from copytrade.recorder.records import STREAM_L2, Record, serialize_record
from copytrade.recorder.store import RecordingIntegrityError, RecordingReader, RecordingStore
from tests.recorder.helpers import (
    DAY,
    DAY0,
    MINUTE,
    SECOND,
    FakeClock,
    StoreRig,
    l2_record,
    make_store,
    open_files,
)

pytestmark = pytest.mark.integration


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def lines_of(records: list[Record]) -> bytes:
    return b"".join(serialize_record(r) + b"\n" for r in records)


def segment_payloads(rig: StoreRig) -> list[Any]:
    return [r.payload for r in rig.of_kind("recording_segment")]


def restart(rig: StoreRig) -> StoreRig:
    """Simulate a process crash and restart: drop the writer without closing anything, reopen ledger and store."""
    rig.ledger.close()
    clock = FakeClock(rig.clock.now_ms())
    ledger = Ledger.open(rig.ledger_dir, clock=clock)
    store = RecordingStore(config=rig.cfg, clock=clock, ledger=ledger, recordings_dir=rig.recordings_dir)
    return StoreRig(rig.cfg, clock, ledger, store, rig.recordings_dir, rig.ledger_dir)


def one_sealed_block_plus_buffer(tmp_path: Path) -> tuple[StoreRig, list[Record]]:
    """300 records sealed as one block (ledgered), 10 more only buffered in memory."""
    rig = make_store(tmp_path)
    records = [l2_record("BTC", DAY0 + i * SECOND, mid=100 + i) for i in range(310)]
    rig.put(records)
    assert len(segment_payloads(rig)) == 1
    return rig, records


# --- 1. seal crash: a fsynced block with no ledger segment record -----------------------------------------------------


@pytest.mark.parametrize("extra_kind", ["valid_xz_block", "garbage"])
def test_F4_R2_seal_crash_extra_unledgered_block_is_truncated_and_the_closed_record_covers_only_ledgered_blocks(
    tmp_path: Path, extra_kind: str
) -> None:
    rig, records = one_sealed_block_plus_buffer(tmp_path)
    (segment,) = segment_payloads(rig)
    end = segment["byte_end"]
    (part,) = open_files(rig.recordings_dir)
    ledgered_bytes = part.read_bytes()[:end]
    assert part.stat().st_size == end  # sanity: nothing extra yet
    if extra_kind == "valid_xz_block":  # what a crash between the block fsync and the ledger append leaves behind
        extra = lzma.compress(lines_of(records[300:]), format=lzma.FORMAT_XZ)
    else:
        extra = b"\x00\xffnot a block\x01" * 7
    with part.open("ab") as handle:
        handle.write(extra)
        handle.flush()
        os.fsync(handle.fileno())
    assert part.stat().st_size == end + len(extra)

    restarted = restart(rig)
    try:
        assert open_files(restarted.recordings_dir) == []
        (closed,) = restarted.closed()
        assert closed["reason"] == "recovered"
        final = restarted.recordings_dir / closed["path"]
        assert final.stat().st_size == end  # truncated to the last ledgered block
        assert final.read_bytes() == ledgered_bytes
        assert closed["byte_count"] == end
        assert closed["transport_sha256"] == sha(ledgered_bytes)
        assert closed["record_count"] == 300
        assert closed["stream_sha256"] == sha(lines_of(records[:300]))
        assert list(restarted.store.read_file(closed["path"])) == records[:300]
        cross = RecordingReader.from_ledger_dir(restarted.recordings_dir, restarted.ledger_dir)
        assert list(cross.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY)) == records[:300]
    finally:
        restarted.ledger.close()


# --- 2. reader race: closed in the ledger, only the .part name on disk ------------------------------------------------


def closed_file_left_as_part(tmp_path: Path) -> tuple[StoreRig, list[Record], Path, Path, dict[str, Any]]:
    """The window between the ledgered close and the rename (also: a crash in that window, before the restart)."""
    rig = make_store(tmp_path)
    records = [l2_record("BTC", DAY0 + i * SECOND, mid=100 + i) for i in range(40)]
    rig.put(records)
    rig.store.close_all("shutdown")
    (closed,) = rig.closed()
    final = rig.recordings_dir / closed["path"]
    part = final.with_name(final.name + ".part")
    os.replace(final, part)
    assert not final.exists() and part.exists()
    return rig, records, final, part, dict(closed)


def test_F4_R2_a_closed_file_that_only_exists_as_part_is_read_and_verified_by_a_cross_process_reader(
    tmp_path: Path,
) -> None:
    """MUST FAIL until the developer fixes ``_verified_closed_bytes`` (falls back to ``.part``)."""
    rig, records, _, _, closed = closed_file_left_as_part(tmp_path)
    try:
        reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
        assert list(reader.read_file(closed["path"])) == records
        assert reader.read_stream_bytes(closed["path"]) == lines_of(records)
        assert list(reader.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY)) == records
        assert reader.as_of(STREAM_L2, "BTC", DAY0 + DAY) == records[-1]
    finally:
        rig.ledger.close()


def test_F4_R2_a_closed_file_that_only_exists_as_part_is_read_by_a_reader_built_with_the_ledger_records(
    tmp_path: Path,
) -> None:
    """MUST FAIL until the developer fixes ``_verified_closed_bytes`` (falls back to ``.part``)."""
    rig, records, _, _, closed = closed_file_left_as_part(tmp_path)
    try:
        ledgered = list(rig.ledger.records())
        reader = RecordingReader(rig.recordings_dir, lambda: ledgered)
        assert list(reader.read_file(closed["path"])) == records
        assert list(reader.pinned().scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY)) == records
    finally:
        rig.ledger.close()


def test_F4_R2_the_part_fallback_still_checks_both_hashes(tmp_path: Path) -> None:
    """A tampered ``.part`` of a closed file is refused, never returned as data (also true before the fix)."""
    rig, _, _, part, closed = closed_file_left_as_part(tmp_path)
    try:
        raw = bytearray(part.read_bytes())
        raw[len(raw) // 2] ^= 0x01
        part.write_bytes(bytes(raw))
        reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
        with pytest.raises(RecordingIntegrityError):
            reader.read_file(closed["path"])
        with pytest.raises(RecordingIntegrityError):
            list(reader.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))
    finally:
        rig.ledger.close()


def test_F4_R2_a_truncated_part_of_a_closed_file_is_refused(tmp_path: Path) -> None:
    rig, _, _, part, closed = closed_file_left_as_part(tmp_path)
    try:
        part.write_bytes(part.read_bytes()[:-1])
        reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
        with pytest.raises(RecordingIntegrityError):
            reader.read_file(closed["path"])
    finally:
        rig.ledger.close()


def test_F4_R2_a_part_of_a_closed_file_with_extra_trailing_bytes_is_refused(tmp_path: Path) -> None:
    """Only the ledgered transport hash and byte count can catch bytes past the last ledgered block."""
    rig, _, _, part, closed = closed_file_left_as_part(tmp_path)
    try:
        with part.open("ab") as handle:
            handle.write(b"\x00")
        reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
        with pytest.raises(RecordingIntegrityError):
            reader.read_file(closed["path"])
    finally:
        rig.ledger.close()


def test_F4_R2_files_lists_a_closed_file_whose_final_name_does_not_exist_yet_and_it_reads_through_the_part_name(
    tmp_path: Path,
) -> None:
    """Expected behaviour: still listed (the ledger says it is closed) and readable through the ``.part`` fallback.
    The read half MUST FAIL until the developer fixes ``_verified_closed_bytes``."""
    rig, records, _, _, closed = closed_file_left_as_part(tmp_path)
    try:
        reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
        listed = reader.files()
        assert [f.path for f in listed] == [closed["path"]]
        assert listed[0].transport_sha256 == closed["transport_sha256"]
        assert list(reader.read_file(listed[0].path)) == records
    finally:
        rig.ledger.close()


def test_F4_R2_a_closed_file_missing_under_both_names_is_listed_but_reading_it_is_an_integrity_error(
    tmp_path: Path,
) -> None:
    rig, _, _, part, closed = closed_file_left_as_part(tmp_path)
    try:
        part.unlink()
        reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
        assert [f.path for f in reader.files()] == [closed["path"]]
        with pytest.raises(RecordingIntegrityError):
            reader.read_file(closed["path"])
        with pytest.raises(RecordingIntegrityError):
            list(reader.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))
    finally:
        rig.ledger.close()


# --- 3. the block is fsynced before its ledger segment record ---------------------------------------------------------


def test_F4_R2_the_block_is_fsynced_before_the_ledger_segment_record_is_appended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(10)])
    (part,) = open_files(rig.recordings_dir)
    part_id = (part.stat().st_dev, part.stat().st_ino)
    ledger_ids = {(p.stat().st_dev, p.stat().st_ino) for p in rig.ledger_dir.rglob("*") if p.is_file()}
    real_fsync = os.fsync
    events: list[tuple[str, int, int]] = []  # (what, part size at that moment, segment records in the ledger)

    def spy(fd: int) -> None:
        st = os.fstat(fd)
        ident = (st.st_dev, st.st_ino)
        what = "part" if ident == part_id else "ledger" if ident in ledger_ids else "other"
        events.append((what, part.stat().st_size, len(segment_payloads(rig))))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    rig.clock.now = DAY0 + 5 * MINUTE
    rig.store.tick()
    monkeypatch.undo()

    assert len(segment_payloads(rig)) == 1
    kinds = [e[0] for e in events]
    assert "part" in kinds and "ledger" in kinds
    first_part, first_ledger = kinds.index("part"), kinds.index("ledger")
    assert first_part < first_ledger  # the block was made durable first
    assert events[first_part][1] == segment_payloads(rig)[0]["byte_end"]  # the whole block was already written
    assert events[first_part][2] == 0  # and no segment record existed yet
