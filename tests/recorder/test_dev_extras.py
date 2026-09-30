"""Developer additions for F4: behaviour the designer's tests do not reach (crash recovery corners, hostile coin names,
forming candles, abandoned candle jobs, a failing disk probe, a leaderboard that never parses)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from copytrade.core.domain import ActionKind
from copytrade.recorder.records import STREAM_CANDLE_1H, STREAM_L2, STREAM_LEADERBOARD
from copytrade.recorder.service import ALERT_LEADERBOARD_MISSING, DISK_LOW
from copytrade.recorder.store import RecordingStore
from tests.recorder.helpers import DAY, DAY0, HOUR, MINUTE, SECOND, Rig, l2_record, make_store
from tests.recorder.test_ac9_candles import H10, H11, X, scenario, step

pytestmark = pytest.mark.integration


def test_F4_AC7_a_file_closed_in_the_ledger_but_not_yet_renamed_gets_its_final_name_on_restart(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(10)])
    rig.store.close_all("shutdown")
    (closed,) = rig.closed()
    final = rig.recordings_dir / closed["path"]
    os.replace(final, str(final) + ".part")  # the crash fell between the ledger record and the rename
    again = RecordingStore(config=rig.cfg, clock=rig.clock, ledger=rig.ledger, recordings_dir=rig.recordings_dir)
    assert final.is_file() and len(rig.closed()) == 1
    assert len(again.read_file(closed["path"])) == 10


def test_F4_AC7_a_restart_closes_an_open_file_keeping_only_its_sealed_segments(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(400)])  # 300 sealed, 100 still in memory
    again = RecordingStore(config=rig.cfg, clock=rig.clock, ledger=rig.ledger, recordings_dir=rig.recordings_dir)
    (closed,) = rig.closed()
    assert closed["reason"] == "recovered" and closed["record_count"] == 300
    assert [r.receive_ts_ms for r in again.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY)] == [
        DAY0 + i * SECOND for i in range(300)
    ]


def test_F4_AC7_an_open_file_with_no_sealed_segment_is_removed_on_restart_and_leaves_no_closed_record(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(10)])
    RecordingStore(config=rig.cfg, clock=rig.clock, ledger=rig.ledger, recordings_dir=rig.recordings_dir)
    assert rig.closed() == []
    assert not [p for p in rig.recordings_dir.rglob("*") if p.is_file()]


def test_F4_AC7_a_corrupted_sealed_block_stops_the_restart_instead_of_being_closed_as_good(tmp_path: Path) -> None:
    from copytrade.recorder.store import RecordingIntegrityError

    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(400)])
    (part,) = rig.recordings_dir.rglob("*.part")
    raw = bytearray(part.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    part.write_bytes(bytes(raw))
    with pytest.raises(RecordingIntegrityError):
        RecordingStore(config=rig.cfg, clock=rig.clock, ledger=rig.ledger, recordings_dir=rig.recordings_dir)


def test_F4_AC1_very_long_and_case_colliding_coin_names_get_short_distinct_safe_paths(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    names = ["kPEPE", "KPEPE", "k" * 500, "coin with spaces", "CON", "é/ü:*?"]
    rig.put([l2_record(name, DAY0 + i) for i, name in enumerate(names)])
    rig.store.close_all("shutdown")
    paths = [c["path"] for c in rig.closed()]
    assert len({p.lower() for p in paths}) == len(names)
    assert all(len(p) < 160 and not any(ch in p for ch in '<>:"|?*\\ ') for p in paths)
    for name in names:
        assert len(list(rig.store.scan(STREAM_L2, name, DAY0, DAY0 + DAY))) == 1


def test_F4_AC9_a_candle_that_has_not_closed_yet_is_returned_to_a_reader_but_never_stored(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)  # the fake clock is at 10:00, so every candle of the hour is still forming
    got = rig.candles.get(X, "1h", H10, H11)
    assert [c.open_ms for c in got] == [H10]
    assert list(rig.store.scan_hour(STREAM_CANDLE_1H, X, H10)) == []
    assert [r for r in rig.ledger.records() if r.kind == "recording_file_closed"] == []


def test_F4_AC9_a_job_still_incomplete_after_the_retry_window_is_ledgered_as_abandoned_with_what_is_missing(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = scenario(rig_factory)
    rig.open_coins.intervals = [(X, H10 + 20 * MINUTE, H10 + 40 * MINUTE)]
    rig.candle_source.down = True
    step(rig, H11 + 72 * HOUR + 10 * MINUTE, by_ms=5 * MINUTE)
    abandoned = [dict(r.payload) for r in rig.ledger.records() if r.kind == "candles_abandoned"]
    assert sorted((a["interval"], len(a["missing"])) for a in abandoned) == [("1h", 1), ("1m", 60)]
    assert all(a["coin"] == X and a["hour_ms"] == H10 for a in abandoned)


def test_F4_AC5_a_disk_probe_that_fails_is_treated_as_no_free_space_and_recording_stops(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()

    def broken(path: Path) -> object:
        raise OSError("volume not readable")

    rig.disk.free_gb = broken  # type: ignore[method-assign,assignment]
    rig.run(120)
    assert rig.recorder.recording is False and rig.recorder.refusal_reason(ActionKind.OPEN) == DISK_LOW


def test_F4_AC2_a_leaderboard_that_never_parses_is_retried_then_recorded_missing_and_never_stored(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.leaderboard.invalid_body = b"<html>502</html>"
    rig.run(HOUR // SECOND - 1)
    rig.recorder.shutdown()
    (snap,) = rig.store.scan(STREAM_LEADERBOARD, None, DAY0, DAY0 + DAY)
    assert snap.data == {"status": "missing"}
    assert len(rig.leaderboard.calls) == 4 and len(rig.alerts.of_kind(ALERT_LEADERBOARD_MISSING)) == 1
    assert rig.registry.wallets() == frozenset()


def test_F4_AC7_a_lock_free_reader_sees_only_the_hashed_data_while_the_writer_holds_more_in_memory(tmp_path: Path) -> None:
    from copytrade.recorder.store import RecordingReader

    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(400)])  # the writer is still holding 100 unhashed records
    reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
    assert len(list(reader.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))) == 300
    assert reader.pinned().as_of(STREAM_L2, "BTC", DAY0 + DAY) == list(reader.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))[-1]
