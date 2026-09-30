"""F4.AC3: point-in-time reads. Every record stores the exchange timestamp (where one exists) and the local receive
timestamp; ``as_of(t)`` never returns a record received after ``t``.

Spec: 04-spec.md F4.AC3, invariant D1 (no lookahead). Real ledger and store; hashed data only is readable (F4.AC7).
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.recorder.records import STREAM_ASSET_CTX, STREAM_FUNDING, STREAM_L2, STREAM_LEADERBOARD, STREAM_MIDS, Record
from tests.recorder.helpers import DAY, DAY0, HOUR, SECOND, Rig, StoreRig, book, l2_record, make_store, stream_records

pytestmark = pytest.mark.unit


def times_of(recs: list[Record]) -> list[int]:
    return [r.receive_ts_ms for r in recs]


def test_F4_AC3_as_of_excludes_records_received_after_t_even_when_future_records_exist(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + t) for t in (10, 20, 30, 40, 50)])  # 40 and 50 are "in the future" of t = 25
    rig.store.close_all("shutdown")
    got = rig.store.as_of(STREAM_L2, "BTC", DAY0 + 25)
    assert got is not None and got.receive_ts_ms == DAY0 + 20


def test_F4_AC3_as_of_is_inclusive_at_t_and_excludes_one_millisecond_later(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + t) for t in (10, 20, 30)])
    rig.store.close_all("shutdown")
    at = rig.store.as_of(STREAM_L2, "BTC", DAY0 + 20)
    just_before = rig.store.as_of(STREAM_L2, "BTC", DAY0 + 19)
    assert at is not None and at.receive_ts_ms == DAY0 + 20
    assert just_before is not None and just_before.receive_ts_ms == DAY0 + 10
    assert rig.store.as_of(STREAM_L2, "BTC", DAY0 + 9) is None


def test_F4_AC3_as_of_with_no_record_at_all_is_none_and_never_raises(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    assert rig.store.as_of(STREAM_L2, "BTC", DAY0 + DAY) is None
    rig.put([l2_record("ETH", DAY0 + 1)])
    rig.store.close_all("shutdown")
    assert rig.store.as_of(STREAM_L2, "BTC", DAY0 + DAY) is None  # another coin's record is not a BTC record
    assert rig.store.as_of(STREAM_MIDS, None, DAY0 + DAY) is None  # another stream's neither


def test_F4_AC3_as_of_looks_back_across_a_day_boundary(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + DAY - 5 * SECOND), l2_record("BTC", DAY0 + DAY + 5 * SECOND)])
    rig.store.close_all("shutdown")
    got = rig.store.as_of(STREAM_L2, "BTC", DAY0 + DAY + 1)
    assert got is not None and got.receive_ts_ms == DAY0 + DAY - 5 * SECOND


def test_F4_AC3_as_of_and_scan_order_by_receive_time_not_by_the_order_of_appending(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    recs = [l2_record("BTC", DAY0 + t) for t in (30, 10, 20)]
    for r in recs:
        rig.store.append(r)
    rig.store.close_all("shutdown")
    got = rig.store.as_of(STREAM_L2, "BTC", DAY0 + 25)
    assert got is not None and got.receive_ts_ms == DAY0 + 20
    assert times_of(list(rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))) == [DAY0 + 10, DAY0 + 20, DAY0 + 30]


def test_F4_AC3_scan_is_half_open_from_inclusive_to_exclusive(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + t) for t in (10, 20, 30)])
    rig.store.close_all("shutdown")
    assert times_of(list(rig.store.scan(STREAM_L2, "BTC", DAY0 + 10, DAY0 + 30))) == [DAY0 + 10, DAY0 + 20]
    assert list(rig.store.scan(STREAM_L2, "BTC", DAY0 + 31, DAY0 + 31)) == []
    assert list(rig.store.scan(STREAM_L2, "BTC", DAY0 + 30, DAY0 + 10)) == []


def test_F4_AC3_records_keep_the_exchange_timestamp_and_the_receive_timestamp_apart(tmp_path: Path) -> None:
    rig = make_store(tmp_path)
    rig.put([l2_record("BTC", DAY0 + 1000, exchange_ms=DAY0 + 940), l2_record("BTC", DAY0 + 2000, exchange_ms=None)])
    rig.store.close_all("shutdown")
    a, b = rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY)
    assert (a.exchange_ts_ms, a.receive_ts_ms) == (DAY0 + 940, DAY0 + 1000)
    assert (b.exchange_ts_ms, b.receive_ts_ms) == (None, DAY0 + 2000)


def test_F4_AC3_the_recorder_stamps_both_timestamps_on_every_kind_of_record(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(1)
    rig.feed.push(book("BTC", DAY0 + 400))
    rig.run(3700)
    rig.recorder.shutdown()
    span = (DAY0, DAY0 + DAY)
    l2 = next(iter(rig.store.scan(STREAM_L2, "BTC", *span)))
    ctx = next(iter(rig.store.scan(STREAM_ASSET_CTX, "BTC", *span)))
    fund = next(iter(rig.store.scan(STREAM_FUNDING, "BTC", *span)))
    board = next(iter(rig.store.scan(STREAM_LEADERBOARD, None, *span)))
    assert l2.exchange_ts_ms == DAY0 + 400 and l2.receive_ts_ms == DAY0 + 2 * SECOND
    assert ctx.exchange_ts_ms is not None and ctx.receive_ts_ms >= ctx.exchange_ts_ms
    assert fund.exchange_ts_ms is not None and fund.exchange_ts_ms % HOUR == 0
    assert board.exchange_ts_ms is None and board.receive_ts_ms > 0
    for r in (l2, ctx, fund, board):
        assert type(r.receive_ts_ms) is int


@given(
    times=st.lists(st.integers(0, 10_000), min_size=1, max_size=25),
    t=st.integers(-5, 10_005),
    order=st.randoms(use_true_random=False),
)
def test_F4_AC3_property_as_of_returns_the_latest_record_not_after_t_and_never_a_later_one(
    times: list[int], t: int, order: object
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rig = make_store(Path(tmp))
        try:
            shuffled = list(times)
            order.shuffle(shuffled)  # type: ignore[attr-defined]
            for x in shuffled:
                rig.store.append(l2_record("BTC", DAY0 + x))
            rig.store.close_all("shutdown")
            got = rig.store.as_of(STREAM_L2, "BTC", DAY0 + t)
            eligible = [x for x in times if x <= t]
            if not eligible:
                assert got is None
            else:
                assert got is not None
                assert got.receive_ts_ms == DAY0 + max(eligible)
                assert got.receive_ts_ms <= DAY0 + t
        finally:
            rig.ledger.close()


def test_F4_AC3_a_reader_over_the_ledger_directory_sees_what_the_writer_hashed(tmp_path: Path) -> None:
    from copytrade.recorder.store import RecordingReader

    rig: StoreRig = make_store(tmp_path)
    rig.put(stream_records(STREAM_MIDS, None, [DAY0 + 5, DAY0 + 15]))
    rig.store.close_all("shutdown")
    reader = RecordingReader.from_ledger_dir(rig.recordings_dir, rig.ledger_dir)
    got = reader.as_of(STREAM_MIDS, None, DAY0 + 10)
    assert got is not None and got.receive_ts_ms == DAY0 + 5
