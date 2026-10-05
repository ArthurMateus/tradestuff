"""F3.AC6: schema validation. A response missing a field or with a wrong type is rejected as a whole and never
partially used; 3 failures in 10 minutes on one endpoint raise one alert.

Payloads are the fixtures under tests/fixtures/exchange/hl/ (SYNTHETIC from the documented shapes, see the README
there: they must be replaced by recorded payloads before /verify). Spec: 04-spec.md F3.AC6, §5, invariant A2, A6.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.core.events import Alert
from copytrade.hl.budget import Priority
from copytrade.hl.errors import HlSchemaError
from copytrade.hl.models import Candle, ClearinghouseState, Fill, L2Book, PortfolioWindow
from copytrade.hl.schema import SchemaFailureMonitor, parse_response
from copytrade.core.money import Price
from tests.hl.support import MINUTE, SECOND, FakeClock, RecordingAlerts, fixture, fill_json, make_rig, ok

pytestmark = pytest.mark.unit
ENDPOINTS = ["allMids", "l2Book", "clearinghouseState", "userFills", "userFillsByTime", "candleSnapshot", "userRole", "portfolio"]


def load(endpoint: str) -> Any:
    return fixture("userFillsByTime" if endpoint == "userFills" else endpoint)


def at(obj: Any, path: list[Any]) -> Any:
    for p in path:
        obj = obj[p]
    return obj


def mutated(endpoint: str, path: list[Any], *, delete: bool = False, value: Any = None) -> Any:
    doc = copy.deepcopy(load(endpoint))
    parent = at(doc, path[:-1])
    if delete:
        del parent[path[-1]]
    else:
        parent[path[-1]] = value
    return doc


# --- recorded (fixture) payloads parse into typed values ----------------------------------------------------------

def test_F3_AC6_all_mids_parses_to_decimal_prices() -> None:
    mids = parse_response("allMids", load("allMids"))
    assert mids["BTC"] == Decimal("67123.5") and isinstance(mids["BTC"], Price)


def test_F3_AC6_l2_book_parses_both_sides() -> None:
    book = parse_response("l2Book", load("l2Book"))
    assert isinstance(book, L2Book) and book.coin == "BTC" and book.time_ms == 1790000000123
    assert [lv.px for lv in book.bids] == [Decimal("67123.0"), Decimal("67122.0")]
    assert [lv.px for lv in book.asks] == [Decimal("67124.0"), Decimal("67125.0")]
    assert book.bids[0].sz == Decimal("1.2345") and book.bids[0].n == 3


def test_F3_AC6_an_empty_book_side_is_valid() -> None:
    doc = load("l2Book")
    doc["levels"] = [[], []]
    book = parse_response("l2Book", doc)
    assert book.bids == () and book.asks == ()


def test_F3_AC6_clearinghouse_state_parses_signed_positions() -> None:
    st_ = parse_response("clearinghouseState", load("clearinghouseState"))
    assert isinstance(st_, ClearinghouseState)
    assert st_.account_value == Decimal("125000.55")
    (pos,) = st_.positions
    assert pos.coin == "BTC" and pos.szi == Decimal("-0.5") and pos.entry_px == Decimal("67000.0")


def test_F3_AC6_clearinghouse_state_with_no_positions_and_null_liquidation_is_valid() -> None:
    doc = load("clearinghouseState")
    doc["assetPositions"] = []
    assert parse_response("clearinghouseState", doc).positions == ()
    doc = load("clearinghouseState")
    doc["assetPositions"][0]["position"]["liquidationPx"] = None
    assert len(parse_response("clearinghouseState", doc).positions) == 1


@pytest.mark.parametrize("endpoint", ["userFills", "userFillsByTime"])
def test_F3_AC6_fills_parse_with_exact_decimals_and_verbatim_dir(endpoint: str) -> None:
    fills = parse_response(endpoint, load(endpoint))
    assert len(fills) == 45 and all(isinstance(f, Fill) for f in fills)
    f0 = fills[0]
    assert f0.px == Decimal("67000.5") and f0.sz == Decimal("0.01") and f0.tid == 700000000000
    assert f0.side in ("B", "A") and f0.dir == "Open Long" and isinstance(f0.crossed, bool)
    assert [f.tid for f in fills] == sorted(f.tid for f in fills)  # order preserved


def test_F3_AC6_an_empty_fill_list_is_valid() -> None:
    assert parse_response("userFillsByTime", []) == ()


def test_F3_AC6_unknown_dir_values_and_extra_fields_pass_through_unchanged() -> None:
    doc = [fill_json(1, dir="Auto-Deleveraging", liquidation={"liquidatedUser": "0xabc", "markPx": "1.0", "method": "market"}, brandNew=1)]
    (fill,) = parse_response("userFillsByTime", doc)
    assert fill.dir == "Auto-Deleveraging"


def test_F3_AC6_candles_parse() -> None:
    candles = parse_response("candleSnapshot", load("candleSnapshot"))
    assert len(candles) == 5 and isinstance(candles[0], Candle)
    assert candles[0].open_ms == 1789990000000 and candles[0].close_ms == 1789990059999
    assert candles[0].open == Decimal("67000.0") and candles[0].interval == "1m" and candles[0].trades == 100


def test_F3_AC6_user_role_parses_to_the_role_string() -> None:
    assert parse_response("userRole", load("userRole")) == "user"


def test_F3_AC6_portfolio_parses_every_window() -> None:
    pf = parse_response("portfolio", load("portfolio"))
    assert set(pf) >= {"day", "week", "month", "allTime", "perpDay", "perpWeek", "perpMonth", "perpAllTime"}
    w = pf["perpMonth"]
    assert isinstance(w, PortfolioWindow)
    assert w.account_value_history[1] == (1789993600000, Decimal("101000.5"))
    assert w.pnl_history[1] == (1789993600000, Decimal("1000.5"))
    assert w.volume == Decimal("250000.0")


# --- rejection: missing field / wrong type -----------------------------------------------------------------------

FILL_REQUIRED = ["coin", "px", "sz", "side", "time", "startPosition", "dir", "closedPnl", "hash", "oid", "crossed", "fee", "tid"]
CANDLE_REQUIRED = ["t", "T", "s", "i", "o", "c", "h", "l", "v", "n"]


@pytest.mark.parametrize("endpoint", ["userFills", "userFillsByTime"])
@pytest.mark.parametrize("key", FILL_REQUIRED)
def test_F3_AC6_a_fill_missing_any_required_field_rejects_the_whole_list(endpoint: str, key: str) -> None:
    doc = mutated(endpoint, [30, key], delete=True)
    with pytest.raises(HlSchemaError) as ei:
        parse_response(endpoint, doc)
    assert ei.value.endpoint == endpoint
    assert ei.value.field.startswith("[30]") and key in ei.value.field


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("px", 67000.5), ("px", None), ("px", "abc"), ("px", "NaN"), ("px", "Infinity"), ("px", "-1"), ("px", ""),
        ("sz", 0.01), ("sz", "1e"), ("fee", 0.01), ("closedPnl", 1.5), ("startPosition", 0.0),
        ("tid", "7"), ("tid", 7.5), ("tid", True), ("oid", "9"), ("time", 1.79e12), ("time", "1790000000000"),
        ("crossed", "true"), ("crossed", 1), ("side", "X"), ("side", 1), ("dir", 5), ("coin", 5), ("hash", 5),
    ],
    ids=repr,
)
def test_F3_AC6_a_fill_with_a_wrong_type_or_bad_value_rejects_the_whole_list(key: str, bad: Any) -> None:
    doc = mutated("userFillsByTime", [12, key], value=bad)
    with pytest.raises(HlSchemaError) as ei:
        parse_response("userFillsByTime", doc)
    assert ei.value.field.startswith("[12]")


def test_F3_AC6_rejection_is_all_or_nothing_no_partial_result_leaks() -> None:
    doc = load("userFillsByTime")
    del doc[44]["tid"]  # only the last of 45 is broken
    with pytest.raises(HlSchemaError):
        parse_response("userFillsByTime", doc)  # raises; there is no returned partial list to inspect


@pytest.mark.parametrize("bad", [{}, "x", None, 5, [[1]], [None], {"a": 1}], ids=repr)
@pytest.mark.parametrize("endpoint", ["userFillsByTime", "candleSnapshot"])
def test_F3_AC6_list_endpoints_reject_the_wrong_container(endpoint: str, bad: Any) -> None:
    with pytest.raises(HlSchemaError):
        parse_response(endpoint, bad)


@pytest.mark.parametrize(
    ("endpoint", "path", "delete"),
    [
        ("allMids", ["BTC"], False),
        ("l2Book", ["coin"], True), ("l2Book", ["time"], True), ("l2Book", ["levels"], True),
        ("l2Book", ["levels", 0, 0, "px"], True), ("l2Book", ["levels", 1, 0, "sz"], True), ("l2Book", ["levels", 0, 0, "n"], True),
        ("clearinghouseState", ["marginSummary"], True), ("clearinghouseState", ["marginSummary", "accountValue"], True),
        ("clearinghouseState", ["assetPositions"], True), ("clearinghouseState", ["time"], True),
        ("clearinghouseState", ["assetPositions", 0, "position", "szi"], True),
        ("clearinghouseState", ["assetPositions", 0, "position", "coin"], True),
        *[("candleSnapshot", [2, k], True) for k in CANDLE_REQUIRED],
        ("userRole", ["role"], True),
        ("portfolio", [0, 1, "accountValueHistory"], True), ("portfolio", [0, 1, "pnlHistory"], True), ("portfolio", [0, 1, "vlm"], True),
    ],
    ids=repr,
)
def test_F3_AC6_missing_required_field_rejects_the_response(endpoint: str, path: list[Any], delete: bool) -> None:
    if endpoint == "allMids":  # a non-string value stands in for "missing" in a flat map
        doc = mutated(endpoint, path, value=None)
    else:
        doc = mutated(endpoint, path, delete=delete)
    with pytest.raises(HlSchemaError) as ei:
        parse_response(endpoint, doc)
    assert ei.value.endpoint == endpoint


@pytest.mark.parametrize(
    ("endpoint", "path", "bad"),
    [
        ("allMids", ["BTC"], 67123.5), ("allMids", ["BTC"], "NaN"), ("allMids", ["ETH"], "-5"), ("allMids", ["ETH"], "abc"),
        ("l2Book", ["time"], "1"), ("l2Book", ["levels", 0, 0, "px"], 67123.0), ("l2Book", ["levels", 0, 0, "sz"], "x"),
        ("l2Book", ["levels", 0, 0, "n"], "3"), ("l2Book", ["levels", 0, 0, "px"], "-1"),
        ("clearinghouseState", ["marginSummary", "accountValue"], 125000.55),
        ("clearinghouseState", ["assetPositions", 0, "position", "szi"], -0.5),
        ("clearinghouseState", ["assetPositions", 0, "position", "szi"], "NaN"),
        ("clearinghouseState", ["time"], 1.79e12),
        ("candleSnapshot", [1, "o"], 67000.0), ("candleSnapshot", [1, "n"], "5"), ("candleSnapshot", [1, "t"], "x"),
        ("candleSnapshot", [1, "h"], "-1"),
        ("userRole", ["role"], 5), ("userRole", ["role"], None),
        ("portfolio", [0, 1, "vlm"], 250000.0), ("portfolio", [0, 1, "accountValueHistory", 0, 1], 100000.0),
        ("portfolio", [0, 1, "pnlHistory", 0, 0], "1789990000000"),
    ],
    ids=repr,
)
def test_F3_AC6_wrong_type_or_bad_value_rejects_the_response(endpoint: str, path: list[Any], bad: Any) -> None:
    with pytest.raises(HlSchemaError) as ei:
        parse_response(endpoint, mutated(endpoint, path, value=bad))
    assert ei.value.endpoint == endpoint


def test_F3_AC6_unknown_request_type_is_rejected() -> None:
    with pytest.raises(HlSchemaError):
        parse_response("order", {"status": "ok"})


def test_F3_AC6_the_error_names_the_endpoint_and_field_but_not_the_payload_values() -> None:
    doc = mutated("userFillsByTime", [3, "px"], value="SECRET-CANARY-VALUE")
    with pytest.raises(HlSchemaError) as ei:
        parse_response("userFillsByTime", doc)
    assert "userFillsByTime" in str(ei.value) and "px" in str(ei.value)
    assert "SECRET-CANARY-VALUE" not in str(ei.value)


@given(px=st.floats(allow_nan=True, allow_infinity=True))
def test_F3_AC6_property_a_json_float_price_is_always_rejected(px: float) -> None:
    doc = [fill_json(1, px=px)]
    with pytest.raises(HlSchemaError):
        parse_response("userFillsByTime", json.loads(json.dumps(doc)))


@given(
    value=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e9"), allow_nan=False, allow_infinity=False, places=6)
)
def test_F3_AC6_property_valid_decimal_strings_round_trip_exactly(value: Decimal) -> None:
    (fill,) = parse_response("userFillsByTime", [fill_json(1, px=str(value), sz=str(value))])
    assert fill.px == value and fill.sz == value


_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8),
    lambda kids: st.lists(kids, max_size=4) | st.dictionaries(st.text(max_size=6), kids, max_size=4),
    max_leaves=12,
)


@given(payload=_JSON, endpoint=st.sampled_from(ENDPOINTS))
def test_F3_AC6_property_arbitrary_json_is_accepted_or_rejected_with_a_schema_error_never_crashes(
    payload: Any, endpoint: str
) -> None:
    try:
        parse_response(endpoint, payload)
    except HlSchemaError:
        pass


# --- the alert: 3 failures in 10 minutes on one endpoint ------------------------------------------------------------

def sm() -> tuple[SchemaFailureMonitor, FakeClock, RecordingAlerts]:
    clock, alerts = FakeClock(), RecordingAlerts()
    return SchemaFailureMonitor(clock=clock, alerts=alerts), clock, alerts


def test_F3_AC6_two_failures_send_no_alert_and_the_third_sends_exactly_one() -> None:
    m, clock, alerts = sm()
    m.record_failure("userFillsByTime")
    clock.advance(SECOND)
    m.record_failure("userFillsByTime")
    assert alerts.sent == []
    clock.advance(SECOND)
    m.record_failure("userFillsByTime")
    (alert,) = alerts.sent
    assert isinstance(alert, Alert) and alert.kind == "schema_failure" and "userFillsByTime" in alert.message


def test_F3_AC6_more_failures_in_the_same_episode_send_no_further_alert() -> None:
    m, clock, alerts = sm()
    for _ in range(9):
        m.record_failure("l2Book")
        clock.advance(SECOND)
    assert len(alerts.of_kind("schema_failure")) == 1


def test_F3_AC6_failures_more_than_ten_minutes_apart_do_not_add_up() -> None:
    m, clock, alerts = sm()
    m.record_failure("l2Book")
    clock.advance(5 * MINUTE)
    m.record_failure("l2Book")
    clock.advance(5 * MINUTE + SECOND)  # the first is now 10 min 1 s old
    m.record_failure("l2Book")
    assert alerts.sent == []


def test_F3_AC6_three_failures_inside_ten_minutes_do_add_up() -> None:
    m, clock, alerts = sm()
    m.record_failure("l2Book")
    clock.advance(5 * MINUTE)
    m.record_failure("l2Book")
    clock.advance(5 * MINUTE - SECOND)  # the first is 9 min 59 s old
    m.record_failure("l2Book")
    assert len(alerts.sent) == 1


def test_F3_AC6_failures_on_different_endpoints_are_counted_separately() -> None:
    m, clock, alerts = sm()
    for ep in ("l2Book", "allMids", "userRole", "l2Book", "allMids", "userRole"):
        m.record_failure(ep)
        clock.advance(SECOND)
    assert alerts.sent == []


def test_F3_AC6_the_client_rejects_a_bad_response_reports_it_and_alerts_on_the_third() -> None:
    bad = fixture("userFillsByTime")
    del bad[7]["tid"]
    rig = make_rig(handler=lambda call: ok(bad))
    for i in range(3):
        with pytest.raises(HlSchemaError):
            rig.client.user_fills_by_time("0x1111111111111111111111111111111111111111", 0, None, priority=Priority.CRITICAL)
        assert len(rig.alerts.of_kind("schema_failure")) == (1 if i == 2 else 0)
