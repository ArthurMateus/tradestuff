"""F4.AC4: gap statistics (``recorder gaps --from --to``).

Spec: 04-spec.md F4.AC4. On a 1-hour fixture with one injected 10-minute gap the reported share is 16.7% +/- 0.1%.
Also the failure semantics of F4.AC7 (unhashed data is a gap) and F4.AC5 (a stopped interval is a gap).
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.recorder.gaps import GapStats, gap_stats
from copytrade.recorder.records import STREAM_ASSET_CTX, STREAM_L2, STREAM_MIDS, Record
from copytrade.recorder.store import RecordingReader
from tests.core.helpers import run_cli
from tests.recorder.helpers import DAY0, HOUR, MINUTE, SECOND, StoreRig, l2_record, make_store, stream_records

pytestmark = pytest.mark.unit

TOL = Decimal("0.001")
ISO_FROM = "2026-09-22T00:00:00Z"
ISO_TO = "2026-09-22T01:00:00Z"


def mids_record(t: int, coins: Iterable[str] = ("BTC", "ETH")) -> Record:
    return Record(STREAM_MIDS, None, None, DAY0 + t, "ws", {"mids": {c: Decimal("1.5") for c in coins}})


def ctx_records(coin: str, times: Iterable[int]) -> list[Record]:
    return stream_records(
        STREAM_ASSET_CTX, coin, [DAY0 + t for t in times], source="rest", data={"mark": Decimal("1"), "oracle": Decimal("1")}
    )


def hour_with_gap(rig: StoreRig, *, gap_from: int = 1500, gap_to: int = 2100) -> None:
    """L2 every 2 s and mids every second for BTC and ETH over one hour, none between gap_from and gap_to (seconds)."""
    recs: list[Record] = []
    for t in range(0, 3601, 2):
        if not (gap_from < t < gap_to):
            recs += [l2_record("BTC", DAY0 + t * SECOND), l2_record("ETH", DAY0 + t * SECOND)]
    recs += [mids_record(t * SECOND) for t in range(0, 3601) if not (gap_from < t < gap_to)]
    rig.put(sorted(recs, key=lambda r: r.receive_ts_ms))
    rig.advance_to(DAY0 + 3601 * SECOND + 6 * MINUTE)
    rig.store.close_all("shutdown")


def test_F4_AC4_a_one_hour_fixture_with_a_ten_minute_gap_reports_16_7_percent(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    hour_with_gap(rig)
    stats = gap_stats(rig.store, DAY0, DAY0 + HOUR)
    for coin in ("BTC", "ETH"):
        assert isinstance(stats[coin], GapStats)
        assert abs(stats[coin].l2_gap_share - Decimal("0.1667")) <= TOL
        assert abs(stats[coin].mid_gap_share - Decimal("0.1667")) <= TOL


def test_F4_AC4_a_gap_free_hour_reports_zero(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    hour_with_gap(rig, gap_from=10, gap_to=10)
    stats = gap_stats(rig.store, DAY0, DAY0 + HOUR)
    assert stats["BTC"] == GapStats(Decimal(0), Decimal(0))


def test_F4_AC4_the_gap_is_the_whole_interval_between_snapshots_not_the_part_beyond_five_seconds(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + t) for t in (0, 1000, 11_000, 12_000)])
    rig.store.close_all("shutdown")
    stats = gap_stats(rig.store, DAY0, DAY0 + 12_000, ("BTC",))
    assert stats["BTC"].l2_gap_share == Decimal(10_000) / Decimal(12_000)


def test_F4_AC4_l2_threshold_exactly_5000_ms_is_not_a_gap_and_5001_is(tmp_path: Path) -> None:
    ok = make_store(tmp_path / "a")
    ok.put([l2_record("BTC", DAY0 + t) for t in (0, 5000, 10_000)])
    ok.store.close_all("shutdown")
    assert gap_stats(ok.store, DAY0, DAY0 + 10_000, ("BTC",))["BTC"].l2_gap_share == 0
    bad = make_store(tmp_path / "b")
    bad.put([l2_record("BTC", DAY0 + t) for t in (0, 5001, 10_002)])
    bad.store.close_all("shutdown")
    assert gap_stats(bad.store, DAY0, DAY0 + 10_002, ("BTC",))["BTC"].l2_gap_share == 1


def test_F4_AC4_mid_threshold_exactly_60_seconds_is_not_a_gap_and_60001_ms_is(tmp_path: Path) -> None:
    ok = make_store(tmp_path / "a")
    ok.put([l2_record("BTC", DAY0), mids_record(0), mids_record(60_000), mids_record(120_000)])
    ok.store.close_all("shutdown")
    assert gap_stats(ok.store, DAY0, DAY0 + 120_000, ("BTC",))["BTC"].mid_gap_share == 0
    bad = make_store(tmp_path / "b")
    bad.put([l2_record("BTC", DAY0), mids_record(0), mids_record(60_001), mids_record(120_002)])
    bad.store.close_all("shutdown")
    assert gap_stats(bad.store, DAY0, DAY0 + 120_002, ("BTC",))["BTC"].mid_gap_share == 1


def test_F4_AC4_a_mid_gap_is_covered_by_the_marks_of_the_same_coin_and_the_other_way_round(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put(
        sorted(
            [l2_record("BTC", DAY0 + t * SECOND) for t in range(0, 601, 2)]
            + [mids_record(t * SECOND) for t in (0, 30, 60, 90)]  # mids stop after 90 s
            + ctx_records("BTC", range(0, 601, 60)),  # marks continue every 60 s
            key=lambda r: r.receive_ts_ms,
        )
    )
    rig.store.close_all("shutdown")
    assert gap_stats(rig.store, DAY0, DAY0 + 600 * SECOND, ("BTC",))["BTC"].mid_gap_share == 0


def test_F4_AC4_marks_of_another_coin_do_not_cover_a_coins_mid_gap(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put(
        sorted(
            [l2_record("BTC", DAY0 + t * SECOND) for t in range(0, 301, 2)]
            + [mids_record(t * SECOND, coins=("ETH",)) for t in range(0, 301, 30)]
            + ctx_records("ETH", range(0, 301, 60)),
            key=lambda r: r.receive_ts_ms,
        )
    )
    rig.store.close_all("shutdown")
    assert gap_stats(rig.store, DAY0, DAY0 + 300 * SECOND, ("BTC",))["BTC"].mid_gap_share == 1


def test_F4_AC4_the_window_edges_count_as_snapshots_so_missing_head_and_tail_are_gaps(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + t * SECOND) for t in range(20, 81, 2)])
    rig.store.close_all("shutdown")
    got = gap_stats(rig.store, DAY0, DAY0 + 100 * SECOND, ("BTC",))["BTC"].l2_gap_share
    assert got == Decimal(20 + 20) / Decimal(100)


def test_F4_AC4_a_coin_with_no_data_in_the_window_is_entirely_a_gap(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + 1)])
    rig.store.close_all("shutdown")
    stats = gap_stats(rig.store, DAY0, DAY0 + HOUR, ("SOL",))
    assert stats["SOL"] == GapStats(Decimal(1), Decimal(1))


def test_F4_AC4_default_coins_are_those_with_any_l2_record_in_the_window(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + 1), l2_record("ETH", DAY0 + 2), l2_record("SOL", DAY0 + 2 * HOUR)])
    rig.store.close_all("shutdown")
    assert set(gap_stats(rig.store, DAY0, DAY0 + HOUR)) == {"BTC", "ETH"}


def test_F4_AC4_a_window_that_is_empty_or_reversed_is_a_value_error(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    for lo, hi in ((DAY0, DAY0), (DAY0 + 5, DAY0)):
        with pytest.raises(ValueError):
            gap_stats(rig.store, lo, hi)


def test_F4_AC4_data_not_covered_by_a_ledgered_hash_is_a_gap(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + t * SECOND) for t in range(0, 3600, 2)])  # last 5 minutes are still unhashed
    got = gap_stats(rig.store, DAY0, DAY0 + HOUR, ("BTC",))["BTC"].l2_gap_share
    assert Decimal("0.083") <= got <= Decimal("0.085")  # (3600 - 3298) / 3600: sealed up to 3298 s


def test_F4_AC4_a_stopped_interval_is_reported_and_never_back_filled(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + t * SECOND) for t in range(0, 601, 2)])
    rig.store.close_all("disk_floor")
    rig.put([l2_record("BTC", DAY0 + t * SECOND) for t in range(1200, 1801, 2)])
    rig.store.close_all("shutdown")
    times = [r.receive_ts_ms for r in rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + HOUR)]
    assert not [t for t in times if DAY0 + 600 * SECOND < t < DAY0 + 1200 * SECOND]
    share = gap_stats(rig.store, DAY0, DAY0 + 1800 * SECOND, ("BTC",))["BTC"].l2_gap_share
    assert abs(share - Decimal(600) / Decimal(1800)) <= Decimal("0.0001")


@given(
    times=st.sets(st.integers(0, 200), min_size=1, max_size=40),
    extra=st.integers(0, 200),
)
def test_F4_AC4_property_shares_are_fractions_and_an_extra_snapshot_never_increases_the_gap(
    times: set[int], extra: int
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        a = make_store(base / "a")
        b = make_store(base / "b")
        try:
            for rig, ts in ((a, times), (b, times | {extra})):
                rig.put([l2_record("BTC", DAY0 + t * SECOND) for t in sorted(ts)])
                rig.store.close_all("shutdown")
            before = gap_stats(a.store, DAY0, DAY0 + 200 * SECOND, ("BTC",))["BTC"].l2_gap_share
            after = gap_stats(b.store, DAY0, DAY0 + 200 * SECOND, ("BTC",))["BTC"].l2_gap_share
            assert 0 <= after <= before <= 1
        finally:
            a.ledger.close()
            b.ledger.close()


# --- the CLI ----------------------------------------------------------------------------------------------------------


def cli(rig: StoreRig, *extra: str) -> tuple[int, str, str]:
    result = run_cli(
        ["recorder", "gaps", "--recordings-dir", str(rig.recordings_dir), "--ledger-dir", str(rig.ledger_dir), *extra]
    )
    return result.code, result.stdout, result.stderr


def test_F4_AC4_recorder_gaps_prints_one_line_per_coin_with_the_percentages(tmp_path: Path) -> None:
    rig = make_store(tmp_path)  # the recorder still holds the ledger: the CLI must not need the writer lock
    hour_with_gap(rig)
    code, out, err = cli(rig, "--from", ISO_FROM, "--to", ISO_TO)
    assert code == 0, err
    lines = {line.split()[0]: line for line in out.strip().splitlines()}
    assert set(lines) == {"BTC", "ETH"}
    for line in lines.values():
        assert "l2_gap_pct=16.7" in line and "mid_gap_pct=16.7" in line


def test_F4_AC4_recorder_gaps_rejects_a_window_that_is_not_forward_or_has_no_offset(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    assert cli(rig, "--from", ISO_TO, "--to", ISO_FROM)[0] == 2
    assert cli(rig, "--from", ISO_FROM, "--to", ISO_FROM)[0] == 2
    assert cli(rig, "--from", "2026-09-22T00:00:00", "--to", ISO_TO)[0] == 2
    assert cli(rig, "--from", "yesterday", "--to", ISO_TO)[0] == 2


def test_F4_AC4_recorder_gaps_on_an_unreadable_directory_exits_1(tmp_path: Path) -> None:
    result = run_cli(
        ["recorder", "gaps", "--recordings-dir", str(tmp_path / "no"), "--ledger-dir", str(tmp_path / "nope"), "--from", ISO_FROM, "--to", ISO_TO]
    )
    assert result.code == 1


def test_F4_AC4_a_reader_over_the_ledger_directory_gives_the_same_stats_as_the_writer(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    hour_with_gap(rig)
    reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
    assert gap_stats(reader, DAY0, DAY0 + HOUR) == gap_stats(rig.store, DAY0, DAY0 + HOUR)
