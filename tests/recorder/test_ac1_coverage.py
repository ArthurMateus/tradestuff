"""F4.AC1: recording universe and per-coin coverage (L2, allMids, asset contexts, funding history).

Spec: 04-spec.md F4.AC1 (Amendment 1: the universe always includes SOL), §3.3 ``recording.*``, §4 throughput.
The real recorder and store run over a stub feed and stub REST sources on a fake clock.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.core.money import Price
from copytrade.hl.models import L2Book
from copytrade.recorder.ports import FeedEvent, MidsUpdate
from copytrade.recorder.records import STREAM_ASSET_CTX, STREAM_FUNDING, STREAM_L2, STREAM_MIDS
from copytrade.recorder.universe import ALWAYS_RECORDED, select_universe
from tests.recorder.helpers import DAY, DAY0, HOUR, SECOND, Rig, book, level

pytestmark = pytest.mark.integration


# --- universe selection (pure) --------------------------------------------------------------------------------------


def test_F4_AC1_the_universe_always_includes_btc_eth_and_sol_even_with_no_traded_coins() -> None:
    assert select_universe(traded_coins=[], hip3_markets=[], volume_24h_usd={}, max_coins=250) == ("BTC", "ETH", "SOL")
    assert ALWAYS_RECORDED == ("BTC", "ETH", "SOL")


def test_F4_AC1_the_universe_is_traded_coins_plus_the_always_set_plus_all_hip3_markets_sorted() -> None:
    got = select_universe(
        traded_coins=["DOGE", "BTC", "kPEPE"],
        hip3_markets=["xyz:AAPL", "abc:GOLD"],
        volume_24h_usd={},
        max_coins=250,
    )
    assert got == ("BTC", "DOGE", "ETH", "SOL", "abc:GOLD", "kPEPE", "xyz:AAPL")


def test_F4_AC1_spot_and_dex_names_in_the_traded_input_are_not_core_perps_and_are_dropped() -> None:
    got = select_universe(
        traded_coins=["@1", "PURR/USDC", "xyz:AAPL", "DOGE"], hip3_markets=[], volume_24h_usd={}, max_coins=250
    )
    assert got == ("BTC", "DOGE", "ETH", "SOL")


def test_F4_AC1_over_the_cap_the_lowest_24h_volume_is_dropped_first_and_hip3_counts_toward_the_cap() -> None:
    vols = {"A": Decimal(10), "B": Decimal(30), "C": Decimal(20), "x:H": Decimal(25)}
    got = select_universe(traded_coins=["A", "B", "C"], hip3_markets=["x:H"], volume_24h_usd=vols, max_coins=5)
    assert got == ("B", "BTC", "ETH", "SOL", "x:H")


def test_F4_AC1_a_volume_tie_drops_the_name_that_sorts_last_and_a_missing_volume_counts_as_zero() -> None:
    vols = {"A": Decimal(5), "B": Decimal(5), "C": Decimal(5)}
    assert select_universe(traded_coins=["A", "B", "C"], hip3_markets=[], volume_24h_usd=vols, max_coins=5) == (
        "A",
        "B",
        "BTC",
        "ETH",
        "SOL",
    )
    assert select_universe(traded_coins=["A", "Z"], hip3_markets=[], volume_24h_usd={"A": Decimal(1)}, max_coins=4) == (
        "A",
        "BTC",
        "ETH",
        "SOL",
    )


def test_F4_AC1_btc_eth_sol_survive_the_cap_even_with_zero_volume() -> None:
    vols = {f"C{i}": Decimal(1000 + i) for i in range(50)}
    got = select_universe(traded_coins=list(vols), hip3_markets=[], volume_24h_usd=vols, max_coins=10)
    assert len(got) == 10 and {"BTC", "ETH", "SOL"} <= set(got)


def test_F4_AC1_exactly_at_the_cap_nothing_is_dropped_and_one_over_drops_one() -> None:
    names = [f"C{i:02d}" for i in range(7)]
    vols = {n: Decimal(i + 1) for i, n in enumerate(names)}
    at_cap = select_universe(traded_coins=names, hip3_markets=[], volume_24h_usd=vols, max_coins=10)
    assert len(at_cap) == 10
    over = select_universe(traded_coins=names, hip3_markets=[], volume_24h_usd=vols, max_coins=9)
    assert len(over) == 9 and "C00" not in over


def test_F4_AC1_a_cap_below_the_always_set_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        select_universe(traded_coins=[], hip3_markets=[], volume_24h_usd={}, max_coins=2)


coin_names = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=5)


@given(
    traded=st.sets(coin_names, max_size=40),
    hip3=st.sets(coin_names.map(lambda s: "dx:" + s), max_size=15),
    vols=st.dictionaries(st.one_of(coin_names, coin_names.map(lambda s: "dx:" + s)), st.integers(0, 10**9), max_size=40),
    cap=st.integers(3, 60),
    seed=st.integers(0, 10),
)
def test_F4_AC1_property_universe_is_capped_keeps_the_always_set_and_keeps_the_highest_volumes(
    traded: set[str], hip3: set[str], vols: dict[str, int], cap: int, seed: int
) -> None:
    volumes = {k: Decimal(v) for k, v in vols.items()}
    got = select_universe(traded_coins=traded, hip3_markets=hip3, volume_24h_usd=volumes, max_coins=cap)
    candidates = set(traded) | set(hip3) | set(ALWAYS_RECORDED)
    assert list(got) == sorted(got) and len(set(got)) == len(got)
    assert set(got) <= candidates and len(got) <= cap
    assert set(ALWAYS_RECORDED) <= set(got)
    assert len(got) == min(cap, len(candidates))
    kept_other = [c for c in got if c not in ALWAYS_RECORDED]
    dropped = [c for c in candidates if c not in got]
    for d in dropped:
        for k in kept_other:
            vd, vk = volumes.get(d, Decimal(0)), volumes.get(k, Decimal(0))
            assert vd < vk or (vd == vk and d > k), (d, k)  # lowest volume goes first; a tie drops the later name
    shuffled = list(traded)
    random.Random(seed).shuffle(shuffled)
    assert select_universe(traded_coins=shuffled, hip3_markets=hip3, volume_24h_usd=volumes, max_coins=cap) == got


# --- the recorder subscribes to the universe ------------------------------------------------------------------------


def test_F4_AC1_start_subscribes_the_feed_to_the_universe_including_hip3_and_uses_the_configured_lookback(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory(started=False, recording__universe_lookback_days=7)
    rig.universe.traded = frozenset({"BTC", "DOGE"})
    rig.universe.hip3 = ("xyz:AAPL",)
    rig.recorder.start()
    assert rig.feed.subscribed[-1] == ("BTC", "DOGE", "ETH", "SOL", "xyz:AAPL")
    assert rig.universe.lookbacks == [7]


def test_F4_AC1_start_caps_the_universe_at_max_coins_by_24h_volume(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(started=False, recording__max_coins=10)
    names = [f"C{i:02d}" for i in range(30)]
    rig.universe.traded = frozenset(names)
    rig.universe.hip3 = ("xyz:AAPL",)
    rig.universe.volume = {n: Decimal(i) for i, n in enumerate(names)} | {"xyz:AAPL": Decimal(1000)}
    rig.recorder.start()
    subscribed = rig.feed.subscribed[-1]
    assert len(subscribed) == 10
    assert {"BTC", "ETH", "SOL", "xyz:AAPL"} <= set(subscribed)
    assert {"C29", "C28", "C27"} <= set(subscribed)


# --- what is recorded ------------------------------------------------------------------------------------------------


def test_F4_AC1_an_l2_book_is_recorded_with_top_levels_both_timestamps_and_the_ws_source(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(1)
    raw = L2Book("BTC", DAY0 + 500, tuple(level(str(99 - i), "1.5", 1) for i in range(20)), tuple(level(str(101 + i)) for i in range(20)))
    rig.feed.push(raw)
    rig.run(1)
    rig.recorder.shutdown()
    (rec,) = [r for r in rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY)]
    assert rec.exchange_ts_ms == DAY0 + 500
    assert rec.receive_ts_ms == DAY0 + 2 * SECOND
    assert rec.source == "ws"
    assert len(rec.data["bids"]) == len(rec.data["asks"]) == 10  # recording.l2_levels
    assert rec.data["bids"][0] == {"px": Decimal("99"), "sz": Decimal("1.5"), "n": 1}
    assert rec.data["bids"][9]["px"] == Decimal("90") and rec.data["asks"][9]["px"] == Decimal("110")


@pytest.mark.parametrize("levels", [5, 20])
def test_F4_AC1_the_recorded_depth_follows_recording_l2_levels(rig_factory: Callable[..., Rig], levels: int) -> None:
    rig = rig_factory(recording__l2_levels=levels)
    rig.run(1)
    rig.feed.push(book("ETH", DAY0 + 900, levels=25))
    rig.run(1)
    rig.recorder.shutdown()
    (rec,) = list(rig.store.scan(STREAM_L2, "ETH", DAY0, DAY0 + DAY))
    assert len(rec.data["bids"]) == len(rec.data["asks"]) == levels


def test_F4_AC1_a_book_with_fewer_levels_than_the_configured_depth_is_recorded_as_is(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(1)
    rig.feed.push(book("BTC", DAY0 + 900, levels=2))
    rig.run(1)
    rig.recorder.shutdown()
    (rec,) = list(rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))
    assert len(rec.data["bids"]) == len(rec.data["asks"]) == 2


def test_F4_AC1_allmids_updates_are_recorded_exactly(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(1)
    mids = {"BTC": Price("67123.5"), "ETH": Price("3412.25"), "@1": Price("12.50")}
    rig.feed.push(MidsUpdate(time_ms=DAY0 + 700, mids=mids))
    rig.feed.push(MidsUpdate(time_ms=None, mids=mids))
    rig.run(1)
    rig.recorder.shutdown()
    recs = list(rig.store.scan(STREAM_MIDS, None, DAY0, DAY0 + DAY))
    assert [r.exchange_ts_ms for r in recs] == [DAY0 + 700, None]
    assert all(r.source == "ws" and r.coin is None for r in recs)
    assert {k: str(v) for k, v in recs[0].data["mids"].items()} == {"BTC": "67123.5", "ETH": "3412.25", "@1": "12.50"}


def test_F4_AC1_a_burst_of_events_in_one_poll_is_recorded_without_loss_and_in_order(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(1)
    for i in range(500):
        rig.feed.push(book("BTC", DAY0 + 1000 + i, mid=100 + i))
    rig.run(1)
    rig.recorder.shutdown()
    recs = list(rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))
    assert [r.exchange_ts_ms for r in recs] == [DAY0 + 1000 + i for i in range(500)]


def test_F4_AC1_asset_contexts_are_recorded_every_configured_interval(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(recording__asset_ctx_interval_s=60)
    rig.run(10 * 60)
    rig.recorder.shutdown()
    for coin in ("BTC", "ETH", "SOL"):
        recs = list(rig.store.scan(STREAM_ASSET_CTX, coin, DAY0, DAY0 + DAY))
        times = [r.receive_ts_ms for r in recs]
        assert len(times) >= 10
        assert {b - a for a, b in zip(times, times[1:], strict=False)} == {60_000}
        assert recs[0].source == "rest" and recs[0].exchange_ts_ms == recs[0].receive_ts_ms
        assert {k: str(v) for k, v in recs[0].data.items()} == {
            "mark": "100.5",
            "oracle": "100.25",
            "funding": "0.0000125",
            "open_interest": "1234.5",
        }


def test_F4_AC1_the_asset_context_cadence_follows_config_at_its_minimum(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(recording__asset_ctx_interval_s=10)
    rig.run(120)
    rig.recorder.shutdown()
    times = [r.receive_ts_ms for r in rig.store.scan(STREAM_ASSET_CTX, "BTC", DAY0, DAY0 + DAY)]
    assert len(times) >= 12 and {b - a for a, b in zip(times, times[1:], strict=False)} == {10_000}


def test_F4_AC1_hourly_funding_history_is_recorded_and_no_point_is_recorded_twice(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(int(2.5 * 3600))
    rig.recorder.shutdown()
    for coin in ("BTC", "SOL"):
        recs = list(rig.store.scan(STREAM_FUNDING, coin, DAY0, DAY0 + DAY))
        exchange = [r.exchange_ts_ms for r in recs]
        assert len(exchange) >= 3 and len(set(exchange)) == len(exchange)
        assert all(t is not None and t % HOUR == 0 for t in exchange)
        assert recs[0].source == "rest"
        assert {k: str(v) for k, v in recs[0].data.items()} == {"rate": "0.0000125", "premium": "0.0001"}


def test_F4_AC1_a_rest_source_that_is_down_leaves_a_gap_and_never_stops_the_book_stream(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(1)
    rig.source.down = True
    for i in range(1, 300):
        rig.feed.push(book("BTC", DAY0 + i * SECOND), at_ms=DAY0 + i * SECOND)
    rig.run(300)
    rig.source.down = False
    rig.run(120)
    rig.recorder.shutdown()
    ctx = [r.receive_ts_ms for r in rig.store.scan(STREAM_ASSET_CTX, "BTC", DAY0, DAY0 + DAY)]
    assert not [t for t in ctx if DAY0 + 2 * SECOND < t < DAY0 + 300 * SECOND]  # nothing invented during the outage
    assert any(t > DAY0 + 300 * SECOND for t in ctx)  # recording resumed with the source
    assert len(list(rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))) == 299


def test_F4_AC1_hip3_markets_are_recorded_and_their_file_names_are_safe_on_windows(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(1)
    rig.feed.push(book("xyz:AAPL", DAY0 + 900))
    rig.run(1)
    rig.recorder.shutdown()
    (rec,) = list(rig.store.scan(STREAM_L2, "xyz:AAPL", DAY0, DAY0 + DAY))
    assert rec.coin == "xyz:AAPL"
    (path,) = [c["path"] for c in [r.payload for r in rig.ledger.records() if r.kind == "recording_file_closed"] if c["coin"] == "xyz:AAPL"]
    assert not any(ch in path for ch in '<>:"|?*\\') and path.count("/") >= 1
    assert (rig.paths.recordings_dir / path).is_file()


def test_F4_AC1_coin_names_that_look_like_paths_cannot_escape_the_recordings_directory(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(1)
    rig.feed.push(book("../../evil", DAY0 + 900))
    rig.feed.push(book("a/b", DAY0 + 901))
    rig.run(1)
    rig.recorder.shutdown()
    root = rig.paths.recordings_dir.resolve()
    for c in [r.payload for r in rig.ledger.records() if r.kind == "recording_file_closed"]:
        assert (rig.paths.recordings_dir / c["path"]).resolve().is_relative_to(root)
    assert len(list(rig.store.scan(STREAM_L2, "../../evil", DAY0, DAY0 + DAY))) == 1
    assert len(list(rig.store.scan(STREAM_L2, "a/b", DAY0, DAY0 + DAY))) == 1


# --- one hour against a stub feed -------------------------------------------------------------------------------------


def test_F4_AC1_over_a_one_hour_stub_feed_l2_gaps_are_at_most_5_seconds_in_at_least_99_9_percent_of_intervals(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory(recording__l2_interval_ms=2000)
    coins = [f"C{i:02d}" for i in range(20)]
    rig.universe.traded = frozenset(coins)
    rig.recorder.start()
    emitted: dict[str, int] = dict.fromkeys(coins, 0)

    def stub(now: int) -> Sequence[FeedEvent]:
        out: list[FeedEvent] = []
        if (now - DAY0) % 2000 == 0:
            for c in coins:
                if c == "C03" and DAY0 + 1000 * SECOND < now < DAY0 + 1006 * SECOND:
                    continue  # the exchange skips C03 for six seconds
                emitted[c] += 1
                out.append(book(c, now - 30))
        return out

    rig.feed.generator = stub
    rig.run(3600)
    rig.recorder.shutdown()
    for c in coins:
        recs = list(rig.store.scan(STREAM_L2, c, DAY0, DAY0 + DAY))
        assert len(recs) == emitted[c]  # 0 events lost
        times = [r.receive_ts_ms for r in recs]
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        ok = sum(1 for g in gaps if g <= 5000)
        assert ok / len(gaps) >= 0.999, (c, ok, len(gaps))


@given(n=st.integers(1, 30))
def test_F4_AC1_property_every_polled_event_becomes_exactly_one_record(n: int) -> None:
    import tempfile
    from pathlib import Path

    from tests.recorder.helpers import make_rig

    with tempfile.TemporaryDirectory() as tmp:
        rig = make_rig(Path(tmp))
        try:
            rig.run(1)
            for i in range(n):
                rig.feed.push(book("BTC", DAY0 + 1000 + i))
            rig.run(1)
            rig.recorder.shutdown()
            assert len(list(rig.store.scan(STREAM_L2, "BTC", DAY0, DAY0 + DAY))) == n
        finally:
            rig.ledger.close()


def test_F4_AC1_the_hip3_market_is_subscribed_though_no_followed_wallet_ever_traded_it(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.run(1)
    assert "xyz:AAPL" in rig.feed.subscribed[-1]
