"""F3.AC1 (client side), F3.AC2, and the info-only rule (F1.AC3 must keep holding).

Spec: 04-spec.md F3.AC2, §3.2 hl.rest_timeout_s / hl.retry_max / hl.backoff_*, invariant B4, F1.AC3.
The transport, sleeping and the clock are faked (external boundaries); the loopback tests use the real
standard-library transport against a local server. Nothing here reaches Hyperliquid.
"""

from __future__ import annotations

import ast
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from copytrade.hl.budget import Priority
from copytrade.hl.errors import (
    HlBudgetError,
    HlHttpError,
    HlRateLimitedError,
    HlRequestError,
    HlTimeoutError,
)
from copytrade.hl.models import Fill
from copytrade.hl.rest import HttpResponse, StdlibHttpTransport
from tests.hl.support import (
    MINUTE,
    SECOND,
    WALLET_A,
    always,
    fixture,
    make_rig,
    max_window_sum,
    ok,
    oracle_weight,
    raising,
    status,
)

pytestmark = pytest.mark.unit
C, S = Priority.CRITICAL, Priority.SCORING


# --- AC2: timeout ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("timeout_s", [2, 10, 30])
def test_F3_AC2_every_request_carries_the_configured_timeout(timeout_s: int) -> None:
    rig = make_rig(hl__rest_timeout_s=timeout_s)
    rig.client.all_mids(priority=C)
    rig.client.l2_book("BTC", priority=C)
    assert [c.timeout_s for c in rig.http.calls] == [timeout_s, timeout_s]


def test_F3_AC2_every_retry_also_carries_the_timeout() -> None:
    rig = make_rig(handler=always(429), hl__rest_timeout_s=7, hl__retry_max=3)
    with pytest.raises(HlRateLimitedError):
        rig.client.all_mids(priority=C)
    assert len(rig.http.calls) == 4
    assert {c.timeout_s for c in rig.http.calls} == {7}


# --- AC2: 429 -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("retry_max", [0, 1, 5, 8])
def test_F3_AC2_a_server_that_always_returns_429_sees_exactly_retry_max_plus_one_requests(retry_max: int) -> None:
    rig = make_rig(handler=always(429, "Too Many Requests"), hl__retry_max=retry_max)
    with pytest.raises(HlRateLimitedError):
        rig.client.all_mids(priority=C)
    assert len(rig.http.calls) == retry_max + 1
    assert len(rig.sleeper.sleeps) == retry_max  # one backoff between attempts, none after the last


def test_F3_AC2_429_backoff_grows_exponentially_from_base_and_is_capped_at_max() -> None:
    rig = make_rig(handler=always(429), hl__retry_max=8, hl__backoff_base_s=1, hl__backoff_max_s=10)
    with pytest.raises(HlRateLimitedError):
        rig.client.all_mids(priority=C)
    sleeps = rig.sleeper.sleeps
    assert len(sleeps) == 8
    for n, s in enumerate(sleeps):
        assert min(10, 2**n) <= s <= 10
    assert sleeps[-1] == 10  # capped


def test_F3_AC2_backoff_starts_at_the_configured_base_not_at_one_second() -> None:
    rig = make_rig(handler=always(429), hl__retry_max=2, hl__backoff_base_s=10, hl__backoff_max_s=300)
    with pytest.raises(HlRateLimitedError):
        rig.client.all_mids(priority=C)
    assert 10 <= rig.sleeper.sleeps[0] <= 20
    assert 20 <= rig.sleeper.sleeps[1] <= 40


def test_F3_AC2_backoff_jitter_differs_between_seeds_and_repeats_for_the_same_seed() -> None:
    def sleeps(seed: int) -> list[float]:
        rig = make_rig(seed=seed, handler=always(429), hl__retry_max=8, hl__backoff_max_s=300)
        with pytest.raises(HlRateLimitedError):
            rig.client.all_mids(priority=C)
        return rig.sleeper.sleeps

    assert sleeps(1) == sleeps(1)
    assert sleeps(1) != sleeps(2)


def test_F3_AC2_no_endpoint_receives_more_than_one_request_per_second_while_it_returns_429() -> None:
    rig = make_rig(handler=always(429), hl__retry_max=5, hl__backoff_base_s=1)
    for _ in range(3):  # back-to-back calls, no pause between them
        with pytest.raises(HlRateLimitedError):
            rig.client.all_mids(priority=C)
    times = rig.http.times("allMids")
    assert len(times) == 18
    assert all(b - a >= SECOND for a, b in zip(times, times[1:], strict=False))


def test_F3_AC2_429_then_success_returns_the_data_after_the_retries() -> None:
    answers = iter([status(429), status(429)])

    def handler(call):  # type: ignore[no-untyped-def]
        return next(answers, None) or ok(fixture("allMids"))

    rig = make_rig(handler=handler)
    mids = rig.client.all_mids(priority=C)
    assert set(mids) == {"BTC", "ETH", "SOL", "@1"}
    assert len(rig.http.calls) == 3
    assert len(rig.sleeper.sleeps) == 2


# --- AC2: timeouts --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("retry_max", [0, 3, 8])
def test_F3_AC2_a_server_that_always_times_out_sees_retry_max_plus_one_requests(retry_max: int) -> None:
    rig = make_rig(handler=raising(TimeoutError("timed out")), hl__retry_max=retry_max)
    with pytest.raises(HlTimeoutError):
        rig.client.all_mids(priority=C)
    assert len(rig.http.calls) == retry_max + 1
    assert len(rig.sleeper.sleeps) == retry_max
    for n, s in enumerate(rig.sleeper.sleeps):
        assert min(60, 2**n) <= s <= 60


def test_F3_AC2_timeout_then_success_recovers() -> None:
    state = {"n": 0}

    def handler(call):  # type: ignore[no-untyped-def]
        state["n"] += 1
        if state["n"] == 1:
            raise TimeoutError
        return ok(fixture("userRole"))

    rig = make_rig(handler=handler)
    assert rig.client.user_role(WALLET_A, priority=C) == "user"
    assert len(rig.http.calls) == 2


# --- other statuses -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("code", [403, 451, 500, 502, 404])
def test_F3_AC2_other_error_statuses_are_raised_at_once_without_retry(code: int) -> None:
    rig = make_rig(handler=always(code, "nope"))
    with pytest.raises(HlHttpError) as ei:
        rig.client.all_mids(priority=C)
    assert ei.value.status == code
    assert len(rig.http.calls) == 1
    assert rig.sleeper.sleeps == []


# --- AC1 at client level --------------------------------------------------------------------------------------

def test_F3_AC1_client_waits_for_the_window_instead_of_exceeding_the_budget() -> None:
    rig = make_rig(hl__rest_weight_budget_per_min=100, hl__weight_userRole=20)
    for _ in range(6):
        rig.client.user_role(WALLET_A, priority=C)
    t = rig.http.times("userRole")
    assert len(t) == 6
    assert t[5] - t[0] >= MINUTE  # the sixth 20-weight request needs the first one to leave the window
    assert max_window_sum([(x, 20) for x in t]) <= 100


def test_F3_AC1_client_traffic_over_ten_minutes_respects_budget_and_scoring_share_including_late_item_weight() -> None:
    rig = make_rig(hl__rest_weight_budget_per_min=900, hl__scoring_weight_share=0.5)
    events: list[tuple[int, int]] = []
    scoring: list[tuple[int, int]] = []
    fills_n = len(fixture("userFillsByTime"))
    end = rig.clock.now_ms() + 10 * MINUTE
    while rig.clock.now_ms() < end and len(rig.http.calls) < 400:
        before = len(rig.http.calls)
        rig.client.user_fills_by_time(WALLET_A, 0, None, priority=S)
        events.append((rig.http.calls[before].t_ms, oracle_weight("userFillsByTime", fills_n)))
        scoring.append(events[-1])
        before = len(rig.http.calls)
        rig.client.all_mids(priority=C)
        events.append((rig.http.calls[before].t_ms, oracle_weight("allMids")))
    assert max_window_sum(events) <= 900
    assert max_window_sum(scoring) <= 450


def test_F3_AC1_scoring_request_that_can_never_fit_its_share_fails_without_sending() -> None:
    rig = make_rig(hl__rest_weight_budget_per_min=100, hl__scoring_weight_share=0.1)
    with pytest.raises(HlBudgetError):
        rig.client.user_fills_by_time(WALLET_A, 0, None, priority=S)
    assert rig.http.calls == []


def test_F3_AC1_critical_request_with_the_same_weight_is_served() -> None:
    rig = make_rig(hl__rest_weight_budget_per_min=100, hl__scoring_weight_share=0.1)
    assert len(rig.client.user_fills_by_time(WALLET_A, 0, None, priority=C)) == 45


# --- typed calls and request bodies ---------------------------------------------------------------------------

def test_F3_AC2_user_fills_by_time_request_body() -> None:
    rig = make_rig()
    fills = rig.client.user_fills_by_time(WALLET_A, 1_789_990_000_000, 1_789_999_000_000, priority=C)
    body = rig.http.calls[0].body
    assert body == {
        "type": "userFillsByTime",
        "user": WALLET_A,
        "startTime": 1_789_990_000_000,
        "endTime": 1_789_999_000_000,
        "aggregateByTime": True,
    }
    assert all(isinstance(f, Fill) for f in fills)


def test_F3_AC2_open_ended_user_fills_by_time_omits_end_time() -> None:
    rig = make_rig()
    rig.client.user_fills_by_time(WALLET_A, 5, None, priority=C)
    assert "endTime" not in rig.http.calls[0].body


# --- info-only (F1.AC3 keeps holding) --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rtype",
    ["order", "cancel", "cancelByCloid", "modify", "batchModify", "withdraw3", "usdSend", "approveAgent", "action", "", "meta\n"],
    ids=repr,
)
def test_F1_AC3_info_only_client_refuses_action_like_request_types_without_sending(rtype: str) -> None:
    rig = make_rig()
    with pytest.raises(HlRequestError):
        rig.client.info(rtype, {}, priority=C)
    assert rig.http.calls == []


@pytest.mark.parametrize(
    "url", ["https://api.hyperliquid.xyz/exchange", "http://127.0.0.1:9/exchange", "https://x/info/../exchange", "https://x/exchange/info"]
)
def test_F1_AC3_client_refuses_any_exchange_url_at_construction(url: str) -> None:
    with pytest.raises(HlRequestError):
        make_rig(url=url)


def test_F1_AC3_every_request_goes_to_the_info_url_only() -> None:
    rig = make_rig()
    rig.client.all_mids(priority=C)
    rig.client.l2_book("BTC", priority=C)
    rig.client.clearinghouse_state(WALLET_A, priority=C)
    rig.client.user_fills_by_time(WALLET_A, 0, None, priority=C)
    rig.client.candles("BTC", "1m", 0, 1, priority=C)
    rig.client.user_role(WALLET_A, priority=C)
    rig.client.portfolio(WALLET_A, priority=C)
    assert len(rig.http.calls) == 7
    assert all(c.url.endswith("/info") and "/exchange" not in c.url for c in rig.http.calls)


def test_F1_AC3_hl_package_has_no_exchange_endpoint_literal_and_no_signing_imports() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "copytrade" / "hl"
    banned_imports = ("hyperliquid", "eth_account", "eth_keys", "web3", "coincurve", "ecdsa", "nacl")
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "/exchange" not in node.value, f"{path.name}: literal names the /exchange endpoint"
            if isinstance(node, ast.Import):
                assert not any(a.name.split(".")[0] in banned_imports for a in node.names), path.name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned_imports, path.name


# --- the real transport against a local loopback server ------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    log: list[tuple[str, dict]] = []  # type: ignore[type-arg]
    reply: tuple[int, str] = (200, "{}")
    hold: threading.Event | None = None

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).log.append((self.path, body))
        hold = type(self).hold
        if hold is not None:
            hold.wait(5)
        code, text = type(self).reply
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(text.encode())

    def log_message(self, *args: object) -> None:  # silence
        return


@contextmanager
def loopback(reply: tuple[int, str], hold: threading.Event | None = None) -> Iterator[tuple[str, type[_Handler]]]:
    handler = type("H", (_Handler,), {"log": [], "reply": reply, "hold": hold})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/info", handler
    finally:
        if hold is not None:
            hold.set()
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_F3_AC2_stdlib_transport_returns_status_and_body_from_a_local_server() -> None:
    with loopback((403, "blocked in your region")) as (url, handler):
        resp = StdlibHttpTransport().post(url, json.dumps({"type": "allMids"}), timeout_s=2)
    assert resp == HttpResponse(status=403, body="blocked in your region")
    assert handler.log == [("/info", {"type": "allMids"})]


def test_F3_AC2_stdlib_transport_raises_timeout_error_when_the_server_never_answers() -> None:
    hold = threading.Event()
    with loopback((200, "{}"), hold) as (url, _):
        with pytest.raises(TimeoutError):
            StdlibHttpTransport().post(url, json.dumps({"type": "allMids"}), timeout_s=0.3)


def test_F3_AC2_a_real_local_server_that_always_returns_429_sees_at_most_retry_max_plus_one_requests_per_call() -> None:
    with loopback((429, "slow down")) as (url, handler):
        rig = make_rig(url=url, transport=StdlibHttpTransport(), hl__retry_max=3)
        with pytest.raises(HlRateLimitedError):
            rig.client.all_mids(priority=C)
    assert len(handler.log) == 4
    assert {p for p, _ in handler.log} == {"/info"}
    assert all(b == {"type": "allMids"} for _, b in handler.log)
