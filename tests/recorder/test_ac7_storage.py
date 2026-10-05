"""F4.AC7: compressed, day-partitioned, atomic, lossless recordings with a stream hash and a transport hash per file,
segment records every 5 minutes, hash-at-close ledger records and ``day_complete``.

Spec: 04-spec.md F4.AC7 (A3.4, A4.8 a and b, test 24), §3.3 ``recording.segment_hash_minutes``, ``storage.upload_delay_min``.
Real F2 ledger and real store on tmp directories; only the clock is fake.
"""

from __future__ import annotations

import hashlib
import random
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.recorder.records import (
    STREAM_ASSET_CTX,
    STREAM_L2,
    STREAM_MIDS,
    Record,
    deserialize_record,
    serialize_record,
    stream_sha256,
)
from copytrade.ledger.records import LedgerRecord
from copytrade.ledger.store import Ledger
from copytrade.recorder.store import RecordingIntegrityError, RecordingReader, RecordingStore
from tests.recorder.helpers import (
    DAY,
    DAY0,
    DAY0_ISO,
    DAY1_ISO,
    HOUR,
    MINUTE,
    SECOND,
    FakeClock,
    StoreRig,
    cfg,
    final_files,
    l2_record,
    make_store,
    open_files,
    spawn_worker,
    stream_records,
)

pytestmark = pytest.mark.integration

GENESIS = "0" * 64


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def stream_bytes(records: list[Record]) -> bytes:
    return b"".join(serialize_record(r) + b"\n" for r in records)


def hour_fixture() -> list[Record]:
    """1 hour, 3 coins: L2 every 2 s, mids every second, asset_ctx every minute. Exact Decimal strings, both timestamps."""
    out: list[Record] = []
    for coin in ("BTC", "ETH", "SOL"):
        out += [l2_record(coin, DAY0 + t, mid=100 + i) for i, t in enumerate(range(0, HOUR, 2 * SECOND))]
        out += stream_records(
            STREAM_ASSET_CTX,
            coin,
            range(DAY0, DAY0 + HOUR, MINUTE),
            source="rest",
            data={"mark": Decimal("100.50"), "oracle": Decimal("100.250"), "funding": Decimal("0.0000125")},
        )
    out += [
        Record(STREAM_MIDS, None, None, DAY0 + t, "ws", {"mids": {"BTC": Decimal("67123.5"), "ETH": Decimal("3412.25")}})
        for t in range(0, HOUR, SECOND)
    ]
    return sorted(out, key=lambda r: r.receive_ts_ms)


def written_hour(rig: StoreRig) -> list[Record]:
    records = hour_fixture()
    rig.put(records)
    rig.advance_to(DAY0 + HOUR + 6 * MINUTE)
    rig.store.close_all("shutdown")
    return records


# --- serialisation ------------------------------------------------------------------------------------------------


def test_F4_AC7_serialisation_is_deterministic_and_independent_of_data_key_order() -> None:
    a = Record(STREAM_L2, "BTC", 5, 9, "ws", {"x": 1, "y": Decimal("1.10"), "z": [1, {"k": "v"}]})
    b = Record(STREAM_L2, "BTC", 5, 9, "ws", {"z": [1, {"k": "v"}], "y": Decimal("1.10"), "x": 1})
    assert serialize_record(a) == serialize_record(b)
    assert serialize_record(a) == serialize_record(a)
    assert b"\n" not in serialize_record(a)


def test_F4_AC7_serialisation_keeps_decimal_scale_and_text_exactly() -> None:
    hostile = 'line1\nline2  \x00 "quoted" \\ back \U0001f600 é'
    rec = Record(STREAM_L2, "BTC", None, 9, "ws", {"d": Decimal("1.10"), "e": Decimal("1E+3"), "t": hostile})
    back = deserialize_record(serialize_record(rec))
    assert back == rec
    assert str(back.data["d"]) == "1.10"
    assert str(back.data["e"]) == "1E+3"
    assert back.data["t"] == hostile
    assert b"\n" not in serialize_record(rec)


def test_F4_AC7_a_record_with_a_float_or_a_non_finite_number_is_refused() -> None:
    with pytest.raises((TypeError, ValueError)):
        Record(STREAM_L2, "BTC", None, 9, "ws", {"px": 1.5})
    with pytest.raises((TypeError, ValueError)):
        Record(STREAM_L2, "BTC", None, 9, "ws", {"px": Decimal("NaN")})


def test_F4_AC7_a_record_with_an_unknown_stream_or_a_float_timestamp_is_refused() -> None:
    with pytest.raises((TypeError, ValueError)):
        Record("not_a_stream", "BTC", None, 9, "ws", {})
    with pytest.raises((TypeError, ValueError)):
        Record(STREAM_L2, "BTC", None, 9.5, "ws", {})  # type: ignore[arg-type]


def test_F4_AC7_deserialising_garbage_raises_value_error() -> None:
    for raw in (b"", b"not json", b'{"stream":"l2"}', b"[1,2]"):
        with pytest.raises(ValueError):
            deserialize_record(raw)


@given(
    text=st.text(max_size=40),
    dec=st.decimals(allow_nan=False, allow_infinity=False, min_value=Decimal("-1e12"), max_value=Decimal("1e12"), places=8),
    ints=st.lists(st.integers(min_value=-(10**15), max_value=10**15), max_size=5),
    ex=st.one_of(st.none(), st.integers(min_value=0, max_value=2 * 10**12)),
    rx=st.integers(min_value=0, max_value=2 * 10**12),
)
def test_F4_AC7_property_serialise_then_deserialise_is_the_identity(
    text: str, dec: Decimal, ints: list[int], ex: int | None, rx: int
) -> None:
    rec = Record(STREAM_L2, "BTC", ex, rx, "ws", {"t": text, "d": dec, "i": ints, "n": None, "b": True})
    back = deserialize_record(serialize_record(rec))
    assert back == rec
    assert serialize_record(back) == serialize_record(rec)
    assert str(back.data["d"]) == str(dec)


# --- lossless one-hour fixture ------------------------------------------------------------------------------------


def test_F4_AC7_a_one_hour_fixture_reads_back_exactly_equal_to_what_was_written(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    written = written_hour(rig)
    for stream, coin in ((STREAM_L2, "BTC"), (STREAM_L2, "SOL"), (STREAM_ASSET_CTX, "ETH"), (STREAM_MIDS, None)):
        expect = [r for r in written if r.stream == stream and r.coin == coin]
        got = list(rig.store.scan(stream, coin, DAY0, DAY0 + DAY))
        assert got == expect
        assert stream_bytes(got) == stream_bytes(expect)  # Decimal strings, both timestamps and the source tag


def test_F4_AC7_decompressing_a_file_yields_the_bytes_the_recorder_serialised(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    written = written_hour(rig)
    btc_l2 = [r for r in written if r.stream == STREAM_L2 and r.coin == "BTC"]
    files = [c for c in rig.closed() if c["stream"] == STREAM_L2 and c["coin"] == "BTC"]
    assert len(files) == 1
    assert rig.store.read_stream_bytes(files[0]["path"]) == stream_bytes(btc_l2)
    assert list(rig.store.read_file(files[0]["path"])) == btc_l2


def test_F4_AC7_unicode_and_hostile_text_survive_the_file_round_trip(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    recs = stream_records(STREAM_MIDS, None, [DAY0 + 1, DAY0 + 2], data={"note": "a\nb c\x00d\U0001f600"})
    rig.put(recs)
    rig.store.close_all("shutdown")
    assert list(rig.store.scan(STREAM_MIDS, None, DAY0, DAY0 + DAY)) == recs


# --- layout, atomicity ----------------------------------------------------------------------------------------------


def test_F4_AC7_files_are_partitioned_by_stream_utc_day_and_coin(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + 5), l2_record("ETH", DAY0 + 6), l2_record("BTC", DAY0 + DAY + 5)])
    rig.store.close_all("shutdown")
    paths = [c["path"] for c in rig.closed()]
    assert len(paths) == 3
    btc_d0 = [p for p in paths if "BTC" in p and DAY0_ISO in p]
    btc_d1 = [p for p in paths if "BTC" in p and DAY1_ISO in p]
    eth_d0 = [p for p in paths if "ETH" in p and DAY0_ISO in p]
    assert len(btc_d0) == len(btc_d1) == len(eth_d0) == 1
    assert all("l2" in p for p in paths)
    assert all((rig.recordings_dir / p).is_file() for p in paths)


def test_F4_AC7_the_utc_day_is_taken_from_the_receive_time_at_the_exact_midnight_boundary(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + DAY - 1), l2_record("BTC", DAY0 + DAY)])
    rig.store.close_all("shutdown")
    by_day = {c["day"]: c["record_count"] for c in rig.closed()}
    assert by_day == {DAY0_ISO: 1, DAY1_ISO: 1}


def test_F4_AC7_nothing_with_a_final_name_is_partial_and_open_files_are_marked_temporary(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(30)])
    assert final_files(rig.recordings_dir) == []  # nothing closed yet: only temporary files exist
    assert open_files(rig.recordings_dir) != []
    rig.store.close_all("shutdown")
    assert open_files(rig.recordings_dir) == []
    assert len(final_files(rig.recordings_dir)) == 1


def test_F4_AC7_close_all_twice_writes_no_second_closed_record(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + 1)])
    rig.store.close_all("shutdown")
    rig.store.close_all("shutdown")
    assert len(rig.closed()) == 1


def test_F4_AC7_close_all_with_nothing_open_writes_nothing(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    before = rig.ledger.last_seq
    rig.store.close_all("shutdown")
    assert rig.ledger.last_seq == before
    assert final_files(rig.recordings_dir) == []


def test_F4_AC7_a_second_file_for_the_same_stream_and_day_never_overwrites_the_first(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    first = [l2_record("BTC", DAY0 + i * SECOND) for i in range(5)]
    second = [l2_record("BTC", DAY0 + HOUR + i * SECOND) for i in range(5)]
    rig.put(first)
    rig.store.close_all("shutdown")
    before = {p: p.read_bytes() for p in final_files(rig.recordings_dir)}
    rig.put(second)
    rig.store.close_all("shutdown")
    closed = rig.closed()
    assert len(closed) == 2 and len({c["path"] for c in closed}) == 2
    for p, data in before.items():
        assert p.read_bytes() == data
    assert list(rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY)) == first + second


def test_F4_AC7_a_late_record_stamped_before_midnight_lands_in_its_own_day_file(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + DAY - 2 * SECOND)])
    rig.advance_to(DAY0 + DAY + 5 * SECOND)
    rig.store.append(l2_record("BTC", DAY0 + DAY - 1))  # out of order: stamped in the previous day
    rig.store.close_all("shutdown")
    by_day = {c["day"]: c["record_count"] for c in rig.closed()}
    assert by_day == {DAY0_ISO: 2}


# --- two hashes, hash at close ---------------------------------------------------------------------------------------


def test_F4_AC7_every_closed_file_is_ledgered_once_with_both_hashes_matching_its_bytes(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    written = written_hour(rig)
    closed = rig.closed()
    files = final_files(rig.recordings_dir)
    assert len(closed) == len(files) == 7  # 3 coins x (l2, asset_ctx) + mids
    assert sorted((rig.recordings_dir / c["path"]) for c in closed) == files
    for c in closed:
        raw = (rig.recordings_dir / c["path"]).read_bytes()
        assert c["transport_sha256"] == sha(raw)
        assert c["byte_count"] == len(raw)
        recs = [r for r in written if r.stream == c["stream"] and r.coin == c["coin"]]
        assert c["record_count"] == len(recs)
        assert c["stream_sha256"] == sha(stream_bytes(recs))
        assert c["stream_sha256"] == stream_sha256(recs)
        assert c["reason"] == "shutdown"
        assert len(c["stream_sha256"]) == len(c["transport_sha256"]) == 64


def test_F4_AC7_stream_hash_ignores_compression_and_transport_hash_follows_it(tmp_path: Path) -> None:
    records = [l2_record("BTC", DAY0 + i * 500, mid=100 + (i % 17)) for i in range(800)]
    hashes = {}
    for level in (1, 9):
        rig = make_store(tmp_path / f"level{level}", compression_level=level)
        rig.put(records)
        rig.store.close_all("shutdown")
        (closed,) = rig.closed()
        hashes[level] = (closed["stream_sha256"], closed["transport_sha256"])
        assert list(rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY)) == records
    assert hashes[1][0] == hashes[9][0]
    assert hashes[1][1] != hashes[9][1]


def test_F4_AC7_the_closed_record_exists_in_the_ledger_before_a_reader_can_list_the_file(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + 1)])
    rig.store.close_all("shutdown")
    reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
    listed = reader.files()
    assert [f.path for f in listed] == [c["path"] for c in rig.closed()]
    assert all(f.reason == "shutdown" and f.record_count == 1 for f in listed)
    assert len(reader.read_file(listed[0].path)) == 1


def test_F4_AC7_a_reader_refuses_a_file_whose_bytes_changed(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(20)])
    rig.store.close_all("shutdown")
    (closed,) = rig.closed()
    target = rig.recordings_dir / closed["path"]
    raw = bytearray(target.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    target.write_bytes(bytes(raw))
    with pytest.raises(RecordingIntegrityError):
        rig.store.read_file(closed["path"])
    with pytest.raises(RecordingIntegrityError):
        list(rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))


def test_F4_AC7_reading_an_unknown_or_missing_path_raises_integrity_error(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + 1)])
    rig.store.close_all("shutdown")
    (closed,) = rig.closed()
    with pytest.raises(RecordingIntegrityError):
        rig.store.read_file("l2/nope.bin")
    (rig.recordings_dir / closed["path"]).unlink()
    with pytest.raises(RecordingIntegrityError):
        rig.store.read_file(closed["path"])


# --- one closed record per file on a 1-day fixture; day_complete --------------------------------------------------------


def one_day(rig: StoreRig) -> None:
    for i in range(0, DAY, 10 * SECOND):
        t = DAY0 + i
        rig.put([l2_record("BTC", t), l2_record("ETH", t)] if i % (60 * SECOND) == 0 else [l2_record("BTC", t)])


def test_F4_AC7_a_one_day_fixture_has_exactly_one_closed_record_per_file_and_each_matches_its_file(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    one_day(rig)
    rig.advance_to(DAY0 + DAY + 20 * MINUTE)
    closed = rig.closed()
    files = final_files(rig.recordings_dir)
    day0 = [c for c in closed if c["day"] == DAY0_ISO]
    assert len(day0) == 2 and {c["coin"] for c in day0} == {"BTC", "ETH"}
    assert len({c["path"] for c in closed}) == len(closed)
    on_disk = {str(p.relative_to(rig.recordings_dir)).replace("\\", "/"): p for p in files if DAY0_ISO in p.as_posix()}
    assert set(on_disk) == {c["path"] for c in day0}
    for c in day0:
        assert c["transport_sha256"] == sha(on_disk[c["path"]].read_bytes())
        assert c["reason"] == "day_end"


def test_F4_AC7_day_complete_is_written_after_the_upload_delay_and_not_before(tmp_path: Path) -> None:
    rig = make_store(tmp_path)  # storage.upload_delay_min = 15
    rig.put([l2_record("BTC", DAY0 + DAY - SECOND), l2_record("ETH", DAY0 + DAY - SECOND)])
    rig.advance_to(DAY0 + DAY + 15 * MINUTE - SECOND)
    assert rig.of_kind("day_complete") == []
    assert rig.closed() == []  # files of the day stay open until the delay has passed
    rig.advance_to(DAY0 + DAY + 15 * MINUTE)
    (done,) = rig.of_kind("day_complete")
    assert done.payload["day"] == DAY0_ISO
    closed_paths = [c["path"] for c in rig.closed()]
    assert sorted(done.payload["files"]) == sorted(closed_paths) and len(closed_paths) == 2
    closed_seqs = [r.seq for r in rig.of_kind("recording_file_closed")]
    assert max(closed_seqs) < done.seq  # closed and hashed before the day is marked complete
    assert all(c["reason"] == "day_end" for c in rig.closed())


def test_F4_AC7_day_complete_follows_the_configured_delay(tmp_path: Path) -> None:
    rig = make_store(tmp_path, storage__upload_delay_min=5)
    rig.put([l2_record("BTC", DAY0 + DAY - SECOND)])
    rig.advance_to(DAY0 + DAY + 5 * MINUTE - SECOND)
    assert rig.of_kind("day_complete") == []
    rig.advance_to(DAY0 + DAY + 5 * MINUTE)
    assert len(rig.of_kind("day_complete")) == 1


def test_F4_AC7_a_day_is_marked_complete_once(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + DAY - SECOND)])
    rig.advance_to(DAY0 + DAY + 2 * HOUR)
    assert len(rig.of_kind("day_complete")) == 1


def test_F4_AC7_the_current_day_keeps_recording_after_the_previous_day_is_closed(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + DAY - SECOND), l2_record("BTC", DAY0 + DAY + SECOND)])
    rig.advance_to(DAY0 + DAY + 20 * MINUTE)
    rig.put([l2_record("BTC", DAY0 + DAY + 21 * MINUTE)])
    rig.store.close_all("shutdown")
    assert [(c["day"], c["record_count"]) for c in rig.closed()] == [(DAY0_ISO, 1), (DAY1_ISO, 2)]


# --- segment records and unhashed data is a gap -----------------------------------------------------------------------


def segments(rig: StoreRig, stream: str, coin: str | None) -> list[LedgerRecord]:
    return [r for r in rig.of_kind("recording_segment") if r.payload["stream"] == stream and r.payload["coin"] == coin]


def test_F4_AC7_a_segment_record_is_ledgered_every_five_minutes_for_each_open_stream(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    for i in range(0, 16 * 60):
        rig.put([l2_record("BTC", DAY0 + i * SECOND), l2_record("ETH", DAY0 + i * SECOND)])
    for coin in ("BTC", "ETH"):
        segs = segments(rig, STREAM_L2, coin)
        assert len(segs) == 3  # sealed at 5, 10 and 15 minutes; the 16th minute is still open
        assert [s.ts.ms for s in segs] == [DAY0 + 300_000 * k for k in (1, 2, 3)]
        assert [s.payload["segment"] for s in segs] == [0, 1, 2]
        assert [s.payload["record_count"] for s in segs] == [300, 300, 300]
        assert all(s.payload["day"] == DAY0_ISO for s in segs)


def test_F4_AC7_no_segment_is_sealed_one_second_early(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(0, 299)])
    rig.advance_to(DAY0 + 300_000 - 1)
    assert segments(rig, STREAM_L2, "BTC") == []
    rig.advance_to(DAY0 + 300_000)
    assert len(segments(rig, STREAM_L2, "BTC")) == 1


def test_F4_AC7_segment_hashes_are_chained_from_zeros_over_the_records_of_each_segment(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    recs = [l2_record("BTC", DAY0 + i * SECOND, mid=100 + i % 5) for i in range(0, 16 * 60)]
    rig.put(recs)
    segs = segments(rig, STREAM_L2, "BTC")
    prev = GENESIS
    for k, s in enumerate(segs):
        chunk = [r for r in recs if DAY0 + 300_000 * k <= r.receive_ts_ms < DAY0 + 300_000 * (k + 1)]
        assert s.payload["prev_hash"] == prev
        expect = sha(bytes.fromhex(prev) + stream_bytes(chunk))
        assert s.payload["segment_hash"] == expect
        prev = s.payload["segment_hash"]
    assert len({s.payload["segment_hash"] for s in segs}) == len(segs)


def test_F4_AC7_each_stream_has_its_own_chain(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    for i in range(0, 6 * 60):
        rig.put([l2_record("BTC", DAY0 + i * SECOND), l2_record("ETH", DAY0 + i * SECOND, mid=200)])
    (btc,) = segments(rig, STREAM_L2, "BTC")
    (eth,) = segments(rig, STREAM_L2, "ETH")
    assert btc.payload["prev_hash"] == eth.payload["prev_hash"] == GENESIS
    assert btc.payload["segment_hash"] != eth.payload["segment_hash"]


def test_F4_AC7_records_of_the_open_segment_are_not_readable_until_they_are_hashed(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + i * SECOND) for i in range(0, 301)])
    got = list(rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))
    assert [r.receive_ts_ms for r in got] == [DAY0 + i * SECOND for i in range(0, 300)]
    assert rig.store.as_of(STREAM_L2, "BTC", DAY0 + 10 * MINUTE) == got[-1]


def test_F4_AC7_after_a_force_kill_mid_segment_the_unhashed_tail_is_a_gap_and_never_used(tmp_path: Path) -> None:
    proc = spawn_worker("steps", tmp_path)  # 12 minutes of one-second steps, then it waits to be killed
    assert proc.stdin is not None and proc.stdout is not None
    for _ in range(720):
        proc.stdin.write("a\n")
        proc.stdin.flush()
        assert proc.stdout.readline().strip() == "ack"
    proc.kill()  # SIGKILL / TerminateProcess: minutes 10 to 12 were never sealed
    proc.wait(timeout=30)

    clock = FakeClock(DAY0 + 12 * MINUTE)
    with Ledger.open(tmp_path / "ledger", clock=clock) as ledger:
        store = RecordingStore(config=cfg(), clock=clock, ledger=ledger, recordings_dir=tmp_path / "recordings")
        got = list(store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))
        assert [r.receive_ts_ms for r in got] == [DAY0 + i * SECOND for i in range(0, 600)]
        assert store.as_of(STREAM_L2, "BTC", DAY0 + DAY) == got[-1]
        assert open_files(tmp_path / "recordings") == []  # the crashed file was recovered and closed
        recovered = [r.payload for r in ledger.records() if r.kind == "recording_file_closed"]
        assert [c["reason"] for c in recovered] == ["recovered"]
        assert recovered[0]["record_count"] == 600
        assert list(store.read_file(recovered[0]["path"])) == got


def test_F4_AC7_after_force_kills_at_20_random_points_every_file_present_reads_back_complete(tmp_path: Path) -> None:
    rnd = random.Random(20240924)
    for run in range(20):
        base = tmp_path / f"kill{run}"
        base.mkdir()
        steps = rnd.randint(1, 900)
        proc = spawn_worker("random", base)
        assert proc.stdin is not None
        for _ in range(steps):
            proc.stdin.write("a\n")
        proc.stdin.flush()
        proc.kill()  # between two operations, or in the middle of one
        proc.wait(timeout=30)

        clock = FakeClock(DAY0 + DAY + 2 * HOUR)
        with Ledger.open(base / "ledger", clock=clock) as ledger:
            recordings = base / "recordings"
            store = RecordingStore(config=cfg(), clock=clock, ledger=ledger, recordings_dir=recordings)
            closed = {r.payload["path"]: r.payload for r in ledger.records() if r.kind == "recording_file_closed"}
            names = {str(p.relative_to(recordings)).replace("\\", "/") for p in final_files(recordings)}
            assert names == set(closed), f"run {run} ({steps} steps): files {names} vs ledger {set(closed)}"
            for path, c in closed.items():
                raw = (recordings / path).read_bytes()
                assert sha(raw) == c["transport_sha256"] and len(raw) == c["byte_count"]
                assert len(store.read_file(path)) == c["record_count"]  # verifies both hashes; raises if partial
            assert open_files(recordings) == []  # recovery left no temporary file
            times = [r.receive_ts_ms for r in store.scan(STREAM_L2, "BTC", DAY0, DAY0 + 2 * DAY)]
            assert times == sorted(set(times))


# --- compression ratio ----------------------------------------------------------------------------------------------------


def test_F4_AC7_compressed_bytes_are_at_most_25_percent_of_the_uncompressed_json_lines(tmp_path: Path) -> None:
    """A representative book stream: 12 coins, one hour at 4 snapshots per 8 seconds each, a random walk in the top
    levels. (The full 250-coin hour is measured in the 24h dry run, F21.AC2 / ``recording.max_gb_per_day``.)"""
    rnd = random.Random(11)
    rig = make_store(tmp_path)
    plain = 0
    mids = {f"C{i}": 1000 + 37 * i for i in range(12)}
    for k, t in enumerate(range(0, HOUR, 2 * SECOND)):
        for coin in mids:
            mids[coin] += rnd.choice((-1, 0, 0, 1))
            bids = [{"px": Decimal(mids[coin] - 1 - j), "sz": Decimal(rnd.randint(1, 900)) / 10, "n": rnd.randint(1, 6)} for j in range(10)]
            asks = [{"px": Decimal(mids[coin] + 1 + j), "sz": Decimal(rnd.randint(1, 900)) / 10, "n": rnd.randint(1, 6)} for j in range(10)]
            rec = Record(STREAM_L2, coin, DAY0 + t - 40, DAY0 + t, "ws", {"bids": bids, "asks": asks})
            plain += len(serialize_record(rec)) + 1
            rig.put([rec])
    rig.advance_to(DAY0 + HOUR + MINUTE)
    rig.store.close_all("shutdown")
    stored = sum(c["byte_count"] for c in rig.closed())
    assert plain > 5_000_000
    assert stored <= plain * 25 // 100, f"{stored} bytes stored for {plain} bytes of JSON lines"
