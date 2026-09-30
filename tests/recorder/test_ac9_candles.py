"""F4.AC9: hourly candle store (edge-hypothesis A4.2, A4.8; ``recording.candle_store``; test 26).

Spec: 04-spec.md F4.AC9, §3.3, §3.9 ``eval.missing_data_retry_max_h``, §4 (hourly fetch budget), §10 (F4 owns the
store and the request interface; the open-coin set is a stub here, F21 wires the real one).
Real store, ledger and candle store; the candle endpoint and the open-coin set are the only fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from copytrade.recorder.candles import ALERT_CANDLES_UNREACHABLE, CandleStore
from copytrade.recorder.records import STREAM_CANDLE_1H, STREAM_CANDLE_1M, STREAM_L2, Record
from tests.recorder.helpers import DAY0, HOUR, MINUTE, SECOND, Rig, book

pytestmark = pytest.mark.integration

H10, H11, H12, H13 = (DAY0 + h * HOUR for h in (10, 11, 12, 13))
X, Y = "XCOIN", "YCOIN"


def scenario(rig_factory: Callable[..., Rig], **kw: object) -> Rig:
    """A share open on X from 10:20 to 12:40 and a mirror open on Y from 11:00 to 11:30."""
    rig = rig_factory(start_ms=H10, **kw)
    rig.open_coins.intervals = [(X, H10 + 20 * MINUTE, H12 + 40 * MINUTE), (Y, H11, H11 + 30 * MINUTE)]
    return rig


def step(rig: Rig, to_ms: int, *, by_ms: int = MINUTE) -> None:
    while rig.clock.now_ms() < to_ms:
        rig.clock.advance(min(by_ms, to_ms - rig.clock.now_ms()))
        rig.store.tick()
        rig.candles.tick()


def closed(rig: Rig, stream: str, coin: str) -> list[dict[str, Any]]:
    return [dict(r.payload) for r in rig.ledger.records() if r.kind == "recording_file_closed" and r.payload["stream"] == stream and r.payload["coin"] == coin]


def open_ms(r: Record) -> int:
    assert r.exchange_ts_ms is not None
    return r.exchange_ts_ms


def stored(rig: Rig, stream: str, coin: str) -> list[Record]:
    return list(rig.store.scan(stream, coin, DAY0, DAY0 + 30 * 86_400_000))


def test_F4_AC9_the_fixture_gives_candle_files_for_x_at_hours_10_11_12_and_for_y_at_hour_11_each_with_a_closed_record(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = scenario(rig_factory)
    step(rig, H13 + 10 * MINUTE)
    rig.store.close_all("shutdown")
    for stream in (STREAM_CANDLE_1M, STREAM_CANDLE_1H):
        assert len(closed(rig, stream, X)) == 3
        assert len(closed(rig, stream, Y)) == 1
        assert closed(rig, stream, "ZCOIN") == []
    assert [r.exchange_ts_ms for r in stored(rig, STREAM_CANDLE_1H, X)] == [H10, H11, H12]
    assert [r.exchange_ts_ms for r in stored(rig, STREAM_CANDLE_1H, Y)] == [H11]
    assert [r.exchange_ts_ms for r in stored(rig, STREAM_CANDLE_1M, X)] == [H10 + i * MINUTE for i in range(180)]
    assert [r.exchange_ts_ms for r in stored(rig, STREAM_CANDLE_1M, Y)] == [H11 + i * MINUTE for i in range(60)]


def test_F4_AC9_only_coins_with_something_open_in_that_hour_are_ever_requested(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    step(rig, H13 + 10 * MINUTE)
    wanted = {(c[1], c[3], c[4]) for c in rig.candle_source.calls}
    assert {coin for coin, _, _ in wanted} == {X, Y}
    assert not [w for w in wanted if w[0] == Y and not (H11 <= w[1] < H12)]
    assert not [w for w in wanted if w[0] == X and not (H10 <= w[1] < H13)]


def test_F4_AC9_an_hour_is_fetched_after_it_has_closed_and_not_before(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    step(rig, H11 - 1)
    assert rig.candle_source.calls == []
    step(rig, H11 + 5 * MINUTE)
    assert rig.candle_source.calls and all(t >= H11 for t, *_ in rig.candle_source.calls)


def test_F4_AC9_each_candle_carries_its_fetch_time_and_the_candle_fields(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    step(rig, H11 + 10 * MINUTE)
    rig.store.close_all("shutdown")
    recs = stored(rig, STREAM_CANDLE_1H, X)
    assert [r.exchange_ts_ms for r in recs] == [H10]
    r = recs[0]
    assert H11 <= r.receive_ts_ms < H11 + 10 * MINUTE and r.source == "rest"
    assert {k: str(v) for k, v in r.data.items()} == {
        "interval": "1h",
        "open_ms": str(H10),
        "close_ms": str(H10 + HOUR - 1),
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100.5",
        "volume": "12.5",
        "trades": "7",
    }


def test_F4_AC9_candle_files_are_hashed_like_any_recording_file(rig_factory: Callable[..., Rig]) -> None:
    import hashlib

    rig = scenario(rig_factory)
    step(rig, H13 + 10 * MINUTE)
    rig.store.close_all("shutdown")
    files = closed(rig, STREAM_CANDLE_1M, X)
    assert len(files) == 3
    for f in files:
        raw = (rig.paths.recordings_dir / f["path"]).read_bytes()
        assert f["transport_sha256"] == hashlib.sha256(raw).hexdigest()
        assert f["record_count"] == 60 and len(f["stream_sha256"]) == 64
        assert len(rig.store.read_file(f["path"])) == 60


def test_F4_AC9_a_completed_hour_is_not_fetched_again_and_a_restart_does_not_refetch_it(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    step(rig, H12 + 10 * MINUTE)
    calls = len(rig.candle_source.calls)
    step(rig, H12 + 40 * MINUTE)
    assert len(rig.candle_source.calls) == calls
    rig.store.close_all("shutdown")
    fresh = CandleStore(
        config=rig.cfg, clock=rig.clock, ledger=rig.ledger, alerts=rig.alerts, store=rig.store,
        source=rig.candle_source, open_coins=rig.open_coins,
    )  # fmt: skip
    rig.clock.advance(MINUTE)
    fresh.tick()
    assert len(rig.candle_source.calls) == calls  # the store, not memory, says these hours are done


# --- missing candles, unreachable endpoint ---------------------------------------------------------------------------------------------------------------


def test_F4_AC9_a_candle_missing_at_first_fetch_is_fetched_later_stored_once_and_the_rest_stay_as_stored(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = scenario(rig_factory)
    rig.candle_source.drop_open_ms = {H10 + 17 * MINUTE}
    step(rig, H11 + 5 * MINUTE)
    first = {open_ms(r): r.receive_ts_ms for r in stored(rig, STREAM_CANDLE_1M, X) if open_ms(r) < H11}
    assert len(first) == 59 and H10 + 17 * MINUTE not in first
    rig.candle_source.drop_open_ms = set()
    step(rig, H11 + 40 * MINUTE)
    rig.store.close_all("shutdown")
    after = {open_ms(r): r.receive_ts_ms for r in stored(rig, STREAM_CANDLE_1M, X) if open_ms(r) < H11}
    assert sorted(after) == [H10 + i * MINUTE for i in range(60)]
    assert {k: v for k, v in after.items() if k != H10 + 17 * MINUTE} == first  # the 59 are untouched
    assert after[H10 + 17 * MINUTE] >= H11 + 5 * MINUTE  # its fetch time is when it was fetched


def test_F4_AC9_a_stored_candle_is_never_replaced_even_if_the_exchange_now_says_something_else(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    step(rig, H11 + 10 * MINUTE)
    rig.candle_source.close_bias = Decimal("5")
    rig.candle_source.drop_open_ms = {H10 + 3 * MINUTE}  # forces another fetch of the hour
    step(rig, H11 + 40 * MINUTE)
    got = rig.candles.get(X, "1m", H10, H11)
    assert len(got) == 60
    assert {c.close for c in got if c.open_ms != H10 + 3 * MINUTE} == {Decimal("100.5")}
    rig.store.close_all("shutdown")
    times = [r.exchange_ts_ms for r in stored(rig, STREAM_CANDLE_1M, X) if open_ms(r) < H11]
    assert len(times) == len(set(times))


def test_F4_AC9_with_the_endpoint_unreachable_the_fetch_is_retried_every_retry_interval_and_other_recording_continues(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = scenario(rig_factory, storage__retry_interval_min=15)
    rig.candle_source.down = True
    rig.feed.generator = lambda now: [book("BTC", now - 30)] if (now - DAY0) % 2000 == 0 else []
    rig.run(1)
    while rig.clock.now_ms() < H11 + 80 * MINUTE:
        rig.run(60)
    attempts = sorted({t for t, coin, interval, s, _ in rig.candle_source.calls if s >= H10 and s < H11})
    assert len(attempts) >= 5
    diffs = [b - a for a, b in zip(attempts, attempts[1:], strict=False)]
    assert all(15 * MINUTE <= d <= 16 * MINUTE for d in diffs), diffs
    rig.recorder.shutdown()
    assert len(stored(rig, STREAM_L2, "BTC")) > 1000  # recording of everything else went on


def test_F4_AC9_one_alert_per_alert_interval_while_the_endpoint_stays_down(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    rig.candle_source.down = True
    step(rig, H11 + 5 * HOUR + 50 * MINUTE, by_ms=5 * MINUTE)
    assert len(rig.alerts.of_kind(ALERT_CANDLES_UNREACHABLE)) == 1
    step(rig, H11 + 6 * HOUR + 30 * MINUTE, by_ms=5 * MINUTE)
    assert len(rig.alerts.of_kind(ALERT_CANDLES_UNREACHABLE)) == 2
    assert ALERT_CANDLES_UNREACHABLE == "candles_unreachable"


def test_F4_AC9_when_the_endpoint_comes_back_within_the_retry_window_the_hour_is_stored(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    rig.candle_source.down = True
    step(rig, H11 + 2 * HOUR, by_ms=5 * MINUTE)
    assert stored(rig, STREAM_CANDLE_1H, X) == []
    rig.candle_source.down = False
    step(rig, H11 + 2 * HOUR + 20 * MINUTE, by_ms=5 * MINUTE)
    rig.store.close_all("shutdown")
    assert [r.exchange_ts_ms for r in stored(rig, STREAM_CANDLE_1H, X)] == [H10, H11]
    assert [r.exchange_ts_ms for r in stored(rig, STREAM_CANDLE_1H, Y)] == [H11]


def test_F4_AC9_retries_stop_after_the_missing_data_retry_window_of_72_hours(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    rig.open_coins.intervals = [(X, H10 + 20 * MINUTE, H10 + 40 * MINUTE)]
    rig.candle_source.down = True
    step(rig, H11 + 72 * HOUR - 5 * MINUTE, by_ms=5 * MINUTE)
    inside = len(rig.candle_source.calls)
    assert inside > 0
    step(rig, H11 + 72 * HOUR + 30 * MINUTE, by_ms=5 * MINUTE)
    late = [t for t, *_ in rig.candle_source.calls if t > H11 + 72 * HOUR]
    assert late == []  # nothing after the window closed
    step(rig, H11 + 80 * HOUR, by_ms=5 * MINUTE)
    assert not [t for t, *_ in rig.candle_source.calls if t > H11 + 72 * HOUR]


# --- readers go through the store ------------------------------------------------------------------------------------------------------------------------------


def test_F4_AC9_a_reader_gets_stored_candles_without_any_fetch(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    step(rig, H11 + 10 * MINUTE)
    calls = len(rig.candle_source.calls)
    rig.candle_source.down = True  # the exchange is gone: the store still answers
    got = rig.candles.get(X, "1m", H10 + 5 * MINUTE, H10 + 10 * MINUTE)
    assert [c.open_ms for c in got] == [H10 + i * MINUTE for i in range(5, 10)]
    assert all(c.interval == "1m" and c.coin == X for c in got)
    assert len(rig.candle_source.calls) == calls


def test_F4_AC9_a_reader_needing_a_candle_that_is_not_there_yet_gets_it_fetched_and_hashed_first(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    step(rig, H11 + 10 * MINUTE)
    calls = len(rig.candle_source.calls)
    got = rig.candles.get("QCOIN", "1m", H10, H11)  # nothing was ever open on Q
    assert [c.open_ms for c in got] == [H10 + i * MINUTE for i in range(60)]
    assert len(rig.candle_source.calls) == calls + 1
    assert len(closed(rig, STREAM_CANDLE_1M, "QCOIN")) == 1  # hashed before it is served
    again = rig.candles.get("QCOIN", "1m", H10, H11)
    assert again == got and len(rig.candle_source.calls) == calls + 1


def test_F4_AC9_a_reader_needing_a_missing_candle_from_an_unreachable_exchange_gets_an_error_not_a_guess(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = scenario(rig_factory)
    rig.candle_source.down = True
    with pytest.raises(OSError):
        rig.candles.get("QCOIN", "1h", H10, H11)


def test_F4_AC9_get_returns_typed_decimal_candles_sorted_by_open_time(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    got = rig.candles.get(X, "1h", H10, H13)
    assert [c.open_ms for c in got] == [H10, H11, H12]
    assert all(isinstance(c.close, Decimal) and isinstance(c.volume, Decimal) for c in got)
    assert list(got) == sorted(got, key=lambda c: c.open_ms)
    assert SECOND == 1000


def test_F4_AC9_the_recorder_process_drives_the_candle_store(rig_factory: Callable[..., Rig]) -> None:
    rig = scenario(rig_factory)
    rig.run(int(1.2 * 3600))
    rig.recorder.shutdown()
    assert [r.exchange_ts_ms for r in stored(rig, STREAM_CANDLE_1H, X)] == [H10]
