"""R0.AC13: the adapters from the F3/F4/F6/F10/F12 ports to the real REST client, the real WebSocket connector and live
data, against the loopback fake Hyperliquid. Read-only toward the exchange."""

from __future__ import annotations

import ast
import json
import random
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.money import Price
from copytrade.hl.access import AccessMonitor
from copytrade.hl.budget import RateBudget
from copytrade.hl.connector import WebsocketsConnector
from copytrade.hl.errors import HlError
from copytrade.hl.models import L2Book
from copytrade.hl.rest import HlRestClient, StdlibHttpTransport
from copytrade.hl.schema import SchemaFailureMonitor
from copytrade.recorder.ports import AssetContext, FundingPoint, MidsUpdate
from copytrade.runner.adapters import (
    ConfigCostModel,
    ExchangeOffsetSource,
    HttpLeaderboardSource,
    MarketHub,
    RestMarketSource,
    RestMetaSource,
)
from tests.core.helpers import REPO_ROOT
from tests.hl.support import FIXTURES, T0, FakeClock, FakeSleeper, RecordingAlerts, RecordingLedger, make_config
from tests.hl.ws_server import wait_for
from tests.runner.fake_hl import FakeHl

D = Decimal


class Env:
    def __init__(self, hl: FakeHl, clock: FakeClock, offset: list[int]) -> None:
        self.hl, self.clock, self.offset = hl, clock, offset
        self.config = make_config()
        self.alerts = RecordingAlerts()
        self.rest = HlRestClient(
            config=self.config, clock=clock, transport=StdlibHttpTransport(), sleeper=FakeSleeper(clock),
            rng=random.Random(1), budget=RateBudget(budget_per_min=900, scoring_share=D("0.5"), clock=clock),
            access=AccessMonitor(config=self.config, clock=clock, alerts=self.alerts, ledger=RecordingLedger()),
            schema_monitor=SchemaFailureMonitor(clock=clock, alerts=self.alerts), info_url=hl.info_url,
        )

    def hub(self, **kw: Any) -> MarketHub:
        connector = WebsocketsConnector(self.hl.ws_url, connect_timeout_s=2.0, max_message_bytes=1 << 20)
        return MarketHub(connector=connector, clock=self.clock, max_book_age_ms=kw.pop("max_book_age_ms", 5000), seed=1)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    clock = FakeClock(T0)
    offset = [0]
    hl = FakeHl(exchange_ms=lambda: clock.now + offset[0]).start()
    try:
        yield Env(hl, clock, offset)
    finally:
        hl.stop()


def poll_until(env: Env, hub: MarketHub, cond: Any, *, what: str) -> list[Any]:
    got: list[Any] = []

    def check() -> Any:
        got.extend(hub.poll())
        return cond(got)

    wait_for(check, what=what)
    return got


# ------------------------------------------------------------------------------ ExchangeOffsetSource


@pytest.mark.parametrize("true_offset", [0, 4_321, -2_500])
def test_R0_AC13_offset_source_recovers_the_exchange_offset_from_one_l2book_request(env: Env, true_offset: int) -> None:
    env.offset[0] = true_offset
    estimate = ExchangeOffsetSource(rest=env.rest, clock=env.clock, probe_coin="BTC").estimate()
    assert abs(estimate.offset_ms - true_offset) <= estimate.uncertainty_ms
    assert 1 <= estimate.uncertainty_ms <= 5  # no round-trip time elapsed on the fake clock
    assert [t for t, _ in env.hl.http_requests] == ["l2Book"]  # exactly one cheap request


def test_R0_AC13_offset_uncertainty_covers_the_round_trip_and_the_truth_stays_inside(env: Env) -> None:
    env.offset[0] = 1_000
    env.hl.hook = lambda: env.clock.advance(40)  # the request takes 40 ms of local time
    estimate = ExchangeOffsetSource(rest=env.rest, clock=env.clock, probe_coin="BTC").estimate()
    assert estimate.uncertainty_ms >= 20
    assert abs(estimate.offset_ms - 1_000) <= estimate.uncertainty_ms


def test_R0_AC13_offset_source_failure_is_an_oserror_for_clocksync(env: Env) -> None:
    env.hl.fail_types.add("l2Book")
    with pytest.raises(OSError):
        ExchangeOffsetSource(rest=env.rest, clock=env.clock, probe_coin="BTC").estimate()


# ------------------------------------------------------------------------------------------ MarketHub


def test_R0_AC13_hub_subscribes_l2_per_coin_and_all_mids_once(env: Env) -> None:
    hub = env.hub()
    hub.subscribe(["SOL", "ETH"])
    wait_for(lambda: hub.poll() == () and len(env.hl.subscribed("l2Book")) == 2, what="the subscriptions")
    assert {s["coin"] for s in env.hl.subscribed("l2Book")} == {"SOL", "ETH"}
    assert len(env.hl.subscribed("allMids")) == 1
    hub.close()


def test_R0_AC13_hub_turns_l2_frames_into_books_and_keeps_them_for_the_paper_broker(env: Env) -> None:
    hub = env.hub()
    hub.subscribe(["SOL"])
    wait_for(lambda: hub.poll() == () and env.hl.subscribed("l2Book"), what="the subscription")
    env.hl.push_l2("SOL", T0 + 1_000)
    events = poll_until(env, hub, lambda got: any(isinstance(e, L2Book) for e in got), what="the l2Book frame")
    book = next(e for e in events if isinstance(e, L2Book))
    assert book.coin == "SOL" and book.time_ms == T0 + 1_000 and book.bids[0].px < book.asks[0].px
    assert hub.first_book_at_or_after("SOL", T0 + 1_000) == book
    assert hub.first_book_at_or_after("SOL", T0 + 1_001) is None
    assert hub.first_book_at_or_after("XYZ", 0) is None
    env.hl.push_l2("SOL", T0 + 2_000)
    poll_until(env, hub, lambda got: sum(isinstance(e, L2Book) for e in got) >= 1, what="a second book")
    later = hub.first_book_at_or_after("SOL", T0 + 1_001)
    assert later is not None and later.time_ms == T0 + 2_000  # the EARLIEST book at or after the time
    hub.close()


def test_R0_AC13_hub_keeps_at_most_64_books_per_coin(env: Env) -> None:
    hub = env.hub()
    hub.subscribe(["SOL"])
    wait_for(lambda: hub.poll() == () and env.hl.subscribed("l2Book"), what="the subscription")
    for i in range(100):
        env.hl.push_l2("SOL", T0 + i)
    wait_for(lambda: (hub.poll(), hub.first_book_at_or_after("SOL", T0 + 99))[1] is not None, what="the last book")
    oldest = hub.first_book_at_or_after("SOL", 0)
    assert oldest is not None and oldest.time_ms >= T0 + 100 - 64
    hub.close()


def test_R0_AC13_hub_turns_all_mids_into_prices_and_marks_the_receive_time(env: Env) -> None:
    hub = env.hub()
    hub.subscribe(["SOL"])
    wait_for(lambda: hub.poll() == () and env.hl.subscribed("allMids"), what="the subscription")
    env.hl.mids["SOL"] = "101.5"
    env.hl.push_mids()
    events = poll_until(env, hub, lambda got: any(isinstance(e, MidsUpdate) for e in got), what="the allMids frame")
    update = next(e for e in events if isinstance(e, MidsUpdate))
    assert update.mids["SOL"] == Price("101.5")
    assert hub.mids()["SOL"] == Price("101.5") and hub.mid_time_ms() == T0
    hub.close()


def test_R0_AC13_hub_replaces_the_subscription_set(env: Env) -> None:
    hub = env.hub()
    hub.subscribe(["SOL", "ETH"])
    wait_for(lambda: hub.poll() == () and len(env.hl.subscribed("l2Book")) == 2, what="the subscriptions")
    hub.subscribe(["ETH"])
    hub.poll()

    def unsubscribed() -> bool:
        hub.poll()
        texts = [t for side in env.hl.connections() for t in side.received]
        return any('"unsubscribe"' in t and '"SOL"' in t for t in texts)

    wait_for(unsubscribed, what="the unsubscribe of SOL")
    hub.close()


@pytest.mark.parametrize(
    "frame",
    [
        "not json at all",
        "[]",
        json.dumps({"channel": "l2Book", "data": {"coin": "SOL", "time": 1, "levels": [[{"px": "NaN", "sz": "1", "n": 1}], []]}}),
        json.dumps({"channel": "l2Book", "data": {"coin": "SOL", "time": 1, "levels": [[{"px": "-5", "sz": "1", "n": 1}], []]}}),
        json.dumps({"channel": "l2Book", "data": {"coin": "SOL", "time": "x", "levels": [[], []]}}),
        json.dumps({"channel": "allMids", "data": {"mids": {"SOL": "Infinity"}}}),
        json.dumps({"channel": "allMids", "data": {"mids": {"SOL": "-1"}}}),
        json.dumps({"channel": "mystery", "data": {}}),
        json.dumps({"channel": "pong"}),
    ],
)
def test_R0_AC13_hub_drops_malformed_frames_without_raising_and_keeps_working(env: Env, frame: str) -> None:
    hub = env.hub()
    hub.subscribe(["SOL"])
    wait_for(lambda: hub.poll() == () and env.hl.subscribed("l2Book"), what="the subscription")
    env.hl.push_raw_to_market(frame)
    env.hl.push_l2("SOL", T0 + 5)
    events = poll_until(env, hub, lambda got: any(isinstance(e, L2Book) and e.time_ms == T0 + 5 for e in got), what="a good frame")
    assert all(isinstance(e, L2Book | MidsUpdate) for e in events)
    assert all(
        e.mids[c] > 0 and e.mids[c].is_finite() for e in events if isinstance(e, MidsUpdate) for c in e.mids
    )
    hub.close()


def test_R0_AC13_hub_survives_a_lost_connection_and_resubscribes_after_a_backoff(env: Env) -> None:
    hub = env.hub()
    hub.subscribe(["SOL"])
    wait_for(lambda: hub.poll() == () and env.hl.subscribed("l2Book"), what="the subscription")
    first = len(env.hl.connections())
    env.hl.drop_market_connections()

    def reconnected() -> bool:
        env.clock.advance(2_000)  # the jittered backoff runs on the injected clock
        assert hub.poll() is not None  # never raises
        return len(env.hl.connections()) > first and len(env.hl.subscribed("l2Book")) >= 2

    wait_for(reconnected, what="the reconnect and resubscribe")
    hub.close()


def test_R0_AC13_hub_poll_never_blocks_and_never_raises_when_nothing_listens(env: Env) -> None:
    env.hl.stop()  # the exchange is gone
    hub = env.hub()
    hub.subscribe(["SOL"])
    for _ in range(5):
        env.clock.advance(1_000)
        assert tuple(hub.poll()) == ()
    hub.close()
    hub.close()  # idempotent


# ----------------------------------------------------------------------------- REST market and meta sources


def test_R0_AC13_asset_contexts_come_from_one_meta_and_asset_ctxs_request(env: Env) -> None:
    env.hl.mids["SOL"] = "123.45"
    contexts = RestMarketSource(rest=env.rest, clock=env.clock).asset_contexts()
    assert {c.coin for c in contexts} == {"BTC", "ETH", "SOL"}
    sol = next(c for c in contexts if c.coin == "SOL")
    assert isinstance(sol, AssetContext)
    assert sol.mark == Price("123.45") and sol.oracle == Price("123.45")
    assert sol.funding == D("0.0000125") and sol.open_interest == D("1000.0")
    assert [t for t, _ in env.hl.http_requests] == ["metaAndAssetCtxs"]


def test_R0_AC13_funding_history_returns_hourly_points_from_the_start_time(env: Env) -> None:
    start = T0 - 5 * 3_600_000
    points = RestMarketSource(rest=env.rest, clock=env.clock).funding_history("SOL", start)
    assert points and all(isinstance(p, FundingPoint) and p.coin == "SOL" and p.time_ms >= start for p in points)
    assert all(p.rate == D("0.0000125") for p in points)
    assert [p.time_ms for p in points] == sorted(p.time_ms for p in points)
    request = env.hl.requests_of("fundingHistory")[0]
    assert request["coin"] == "SOL" and request["startTime"] == start


def test_R0_AC13_market_source_failures_are_the_kind_the_recorder_treats_as_a_gap(env: Env) -> None:
    env.hl.fail_types.update({"metaAndAssetCtxs", "fundingHistory"})
    source = RestMarketSource(rest=env.rest, clock=env.clock)
    with pytest.raises((OSError, HlError)):
        source.asset_contexts()
    with pytest.raises((OSError, HlError)):
        source.funding_history("SOL", T0)


def test_R0_AC13_meta_source_gives_lot_and_leverage_rules_and_excludes_delisted_coins(env: Env) -> None:
    meta = RestMetaSource(rest=env.rest)
    rules = meta.fetch()
    assert (rules["SOL"].sz_decimals, rules["SOL"].max_leverage) == (2, 20)
    assert (rules["BTC"].sz_decimals, rules["BTC"].max_leverage) == (5, 40)
    assert meta.delisted() == frozenset()
    env.hl.universe[1] = {**env.hl.universe[1], "isDelisted": True}  # ETH
    assert "ETH" not in meta.fetch() and meta.delisted() == frozenset({"ETH"})


def test_R0_AC13_meta_source_failure_is_an_oserror_so_the_gate_refuses_entries(env: Env) -> None:
    env.hl.fail_types.add("metaAndAssetCtxs")
    with pytest.raises((OSError, HlError)):
        RestMetaSource(rest=env.rest).fetch()


# ------------------------------------------------------------------------------------ leaderboard source


def test_R0_AC13_leaderboard_body_is_returned_exactly_as_received(env: Env) -> None:
    body = HttpLeaderboardSource(url=env.hl.leaderboard_url, timeout_s=3.0).fetch()
    assert body == (FIXTURES / "leaderboard.json").read_bytes()


@pytest.mark.parametrize("status", [404, 500, 503])
def test_R0_AC13_leaderboard_non_2xx_is_an_oserror(env: Env, status: int) -> None:
    env.hl.leaderboard_status = status
    with pytest.raises(OSError):
        HttpLeaderboardSource(url=env.hl.leaderboard_url, timeout_s=3.0).fetch()


def test_R0_AC13_leaderboard_has_a_deadline_for_the_whole_exchange(env: Env) -> None:
    env.hl.leaderboard_delay_s = 10.0
    with pytest.raises(TimeoutError):
        HttpLeaderboardSource(url=env.hl.leaderboard_url, timeout_s=0.3).fetch()
    env.hl.release()


def test_R0_AC13_leaderboard_connection_refused_is_an_oserror() -> None:
    from tests.hl.ws_server import closed_port

    with pytest.raises(OSError):
        HttpLeaderboardSource(url=f"http://127.0.0.1:{closed_port()}/leaderboard", timeout_s=1.0).fetch()


# ------------------------------------------------------------------------------------------- cost model


@pytest.mark.parametrize(
    ("coin", "spread", "delay"),
    [("BTC", D("3.0"), D("5.0")), ("ETH", D("3.0"), D("5.0")), ("SOL", D("12.0"), D("15.0")), ("DOGE", D("12.0"), D("15.0"))],
)
def test_R0_AC13_cost_model_is_the_conservative_config_fallback(coin: str, spread: Decimal, delay: Decimal) -> None:
    model = ConfigCostModel(make_config())
    assert model.taker_fee_bps() == D("4.5")
    assert model.half_spread_bps(coin, T0) == spread  # cost.fallback_half_spread_bps x cost.fallback_half_spread_mult 1.5
    assert model.delay_bps(coin, T0) == delay
    assert all(isinstance(v, Decimal) for v in (model.taker_fee_bps(), model.half_spread_bps(coin, T0), model.delay_bps(coin, T0)))


# --------------------------------------------------------------------------------- built from config only


def test_R0_AC13_the_websocket_connector_is_built_from_config_not_from_constants() -> None:
    found = 0
    for path in sorted((REPO_ROOT / "src" / "copytrade" / "runner").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("WebsocketsConnector"):
                found += 1
                for kw in node.keywords:
                    if kw.arg in ("connect_timeout_s", "max_message_bytes"):
                        assert not isinstance(kw.value, ast.Constant), f"{path.name}: {kw.arg} is hard-coded"
    assert found == 1


def test_R0_AC13_adapters_are_read_only_toward_the_exchange(env: Env) -> None:
    RestMarketSource(rest=env.rest, clock=env.clock).asset_contexts()
    RestMetaSource(rest=env.rest).fetch()
    ExchangeOffsetSource(rest=env.rest, clock=env.clock, probe_coin="BTC").estimate()
    assert env.hl.bad_paths == []
    assert {t for t, _ in env.hl.http_requests} <= {"metaAndAssetCtxs", "l2Book"}
    assert Path(env.hl.info_url).name == "info"
