"""R0.AC9: the recording-retention cap. The recorder never deletes (F4.AC2); the runner prunes local copies of closed
days older than ``storage.local_retention_days`` and says so in the ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.ledger.errors import LedgerError
from copytrade.ledger.store import Ledger, read_records
from copytrade.recorder.records import Record
from copytrade.recorder.store import RecordingReader, RecordingStore
from copytrade.runner.retention import KIND_RECORDING_PRUNED, prune_recordings
from tests.hl.support import FakeClock
from tests.recorder.helpers import cfg
from tests.runner.world import World

DAY = 86_400_000
NOW = int(datetime(2026, 10, 1, 12, 0, tzinfo=UTC).timestamp() * 1000)  # 2026-10-01 12:00 UTC


def day_ms(days_ago: int) -> int:
    midnight = NOW - NOW % DAY
    return midnight - days_ago * DAY + 3_600_000  # 01:00 UTC of that day


def iso(days_ago: int) -> str:
    return (datetime.fromtimestamp(NOW / 1000, UTC) - timedelta(days=days_ago)).date().isoformat()


def write_days(ledger_dir: Path, recordings_dir: Path, days_ago: list[int], config: Any = None) -> list[str]:
    """Closed recording files for the given days (real F4 store). Returns the relative paths, in day order."""
    config = config or cfg()
    clock = FakeClock(NOW)
    ledger = Ledger.open(ledger_dir, clock=clock)
    store = RecordingStore(config=config, clock=clock, ledger=ledger, recordings_dir=recordings_dir)
    for d in days_ago:
        store.append(
            Record(stream="mids", coin=None, exchange_ts_ms=None, receive_ts_ms=day_ms(d), source="ws",
                   data={"mids": {"SOL": Decimal("100")}})
        )
    store.close_all("shutdown")
    ledger.close()
    return [f.path for f in RecordingReader.from_ledger_dir(recordings_dir, ledger_dir).files()]


def prune(base: Path, config: Any = None, *, now_ms: int = NOW) -> tuple[str, ...]:
    config = config or cfg()
    ledger = Ledger.open(base / "ledger", clock=FakeClock(now_ms))
    try:
        return prune_recordings(config, recordings_dir=base / "rec", ledger=ledger, now_ms=now_ms)
    finally:
        ledger.close()


def existing(base: Path) -> set[str]:
    return {p.relative_to(base / "rec").as_posix() for p in (base / "rec").rglob("*") if p.is_file()}


def test_R0_AC9_days_older_than_the_retention_are_deleted_newer_ones_kept(tmp_path: Path) -> None:
    paths = write_days(tmp_path / "ledger", tmp_path / "rec", [0, 1, 7, 8, 30])  # storage.local_retention_days = 7
    by_day = {iso(d): p for d, p in zip([0, 1, 7, 8, 30], paths, strict=True)}
    deleted = prune(tmp_path)
    assert set(deleted) == {by_day[iso(8)], by_day[iso(30)]}  # exactly retention days old is kept: T-7 stays, T-8 goes
    assert existing(tmp_path) >= {by_day[iso(0)], by_day[iso(1)], by_day[iso(7)]}
    assert not existing(tmp_path) & set(deleted)
    assert list(deleted) == sorted(deleted)


def test_R0_AC9_each_pruned_file_is_ledgered_with_its_hash_and_size(tmp_path: Path) -> None:
    write_days(tmp_path / "ledger", tmp_path / "rec", [9])
    reader = RecordingReader.from_ledger_dir(tmp_path / "rec", tmp_path / "ledger")
    closed = reader.files()[0]
    raw = (tmp_path / "rec" / closed.path).read_bytes()
    prune(tmp_path)
    pruned = [r for r in read_records(tmp_path / "ledger") if r.kind == KIND_RECORDING_PRUNED]
    assert len(pruned) == 1
    payload = pruned[0].payload
    assert payload["path"] == closed.path and payload["bytes"] == len(raw) == closed.byte_count
    assert payload["sha256"] == closed.transport_sha256


def test_R0_AC9_a_second_prune_deletes_nothing_more_and_writes_nothing(tmp_path: Path) -> None:
    write_days(tmp_path / "ledger", tmp_path / "rec", [9, 10])
    assert len(prune(tmp_path)) == 2
    n = len(list(read_records(tmp_path / "ledger")))
    assert prune(tmp_path) == ()
    assert len(list(read_records(tmp_path / "ledger"))) == n


def test_R0_AC9_only_closed_recording_files_are_touched(tmp_path: Path) -> None:
    write_days(tmp_path / "ledger", tmp_path / "rec", [9])
    (tmp_path / "rec" / "wallets.txt").write_text("0x" + "a" * 40, encoding="utf-8")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "keep.bin").write_bytes(b"x")
    prune(tmp_path)
    assert (tmp_path / "rec" / "wallets.txt").exists() and (tmp_path / "cache" / "keep.bin").exists()
    assert (tmp_path / "ledger" / "ledger.jsonl").exists()


def test_R0_AC9_a_ledger_failure_deletes_nothing(tmp_path: Path) -> None:
    paths = write_days(tmp_path / "ledger", tmp_path / "rec", [9, 10])
    ledger = Ledger.open(tmp_path / "ledger", clock=FakeClock(NOW))
    ledger.close()  # appends now fail
    with pytest.raises(LedgerError):  # whichever ledger error the closed ledger raises
        prune_recordings(cfg(), recordings_dir=tmp_path / "rec", ledger=ledger, now_ms=NOW)
    assert existing(tmp_path) == set(paths)  # the record comes BEFORE the delete, so no file is lost silently


@pytest.mark.parametrize("keep_days", [2, 3, 14])
def test_R0_AC9_the_retention_days_come_from_config(tmp_path: Path, keep_days: int) -> None:
    paths = write_days(tmp_path / "ledger", tmp_path / "rec", [0, 2, 4, 13, 15])
    config = cfg(storage__local_retention_days=keep_days)
    deleted = set(prune(tmp_path, config))
    expected = {p for d, p in zip([0, 2, 4, 13, 15], paths, strict=True) if d > keep_days}
    assert deleted == expected


def test_R0_AC9_the_runner_prunes_old_local_copies_at_start(new_world: Any) -> None:
    world: World = new_world()
    paths = write_days(world.ledger_dir, world.recordings_dir, [30, 20])
    # the world's clock is T0 (2026-09-21): files written for NOW-30d / NOW-20d are older than 7 days either way
    world.clock.now = NOW
    runner, _ = world.start()
    gone = [p for p in paths if not (world.recordings_dir / p).exists()]
    assert gone == paths
    assert len(world.records(KIND_RECORDING_PRUNED)) == 2
    assert runner.recorder.recording
