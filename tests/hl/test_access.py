"""F3.AC5: access degraded (K10). Spec: 04-spec.md F3.AC5, §3.2 access.*, §5 "HL 403/451 or geo-block".

Fake clock, no sleeping. Cases keep at least 10 requests in the window whenever the success RATE matters,
because the spec does not say how a tiny sample is treated (see the test plan, decision D3).
"""

from __future__ import annotations

import pytest

from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert
from copytrade.hl.budget import Priority
from copytrade.hl.access import ACCESS_DEGRADED, AccessMonitor, is_region_block_body
from copytrade.hl.errors import HlHttpError
from copytrade.hl.ledger_port import DowntimeRecord
from tests.hl.support import (
    MINUTE,
    SECOND,
    WALLET_A,
    FakeClock,
    RecordingAlerts,
    RecordingLedger,
    always,
    make_config,
    make_rig,
)

pytestmark = pytest.mark.unit

REGION_BODIES = ["Service unavailable in your region", "This service is not available in your jurisdiction"]


def monitor(**overrides: object) -> tuple[AccessMonitor, FakeClock, RecordingAlerts, RecordingLedger]:
    clock, alerts, ledger = FakeClock(), RecordingAlerts(), RecordingLedger()
    return AccessMonitor(config=make_config(**overrides), clock=clock, alerts=alerts, ledger=ledger), clock, alerts, ledger


def healthy(m: AccessMonitor, clock: FakeClock, n: int = 20) -> None:
    for _ in range(n):
        m.record_response(200, "{}")
        clock.advance(100)


def tick_for(m: AccessMonitor, clock: FakeClock, seconds: int) -> None:
    for _ in range(seconds):
        clock.advance(SECOND)
        m.tick()


def serve_healthy_minutes(m: AccessMonitor, clock: FakeClock, minutes: int) -> None:
    """60 successful requests per minute, ticking every second."""
    for _ in range(minutes * 60):
        clock.advance(SECOND)
        m.record_response(200, "{}")
        m.tick()


# --- trigger: 403 / 451 / region body ------------------------------------------------------------------------------

def test_F3_AC5_three_403s_within_the_window_degrade_access_and_two_do_not() -> None:
    m, clock, _, _ = monitor()
    healthy(m, clock)
    m.record_response(403, "")
    m.record_response(403, "")
    m.tick()
    assert not m.degraded
    m.record_response(403, "")
    m.tick()
    assert m.degraded


def test_F3_AC5_403_and_451_count_together() -> None:
    m, clock, _, _ = monitor()
    healthy(m, clock)
    for code in (403, 451, 403):
        m.record_response(code, "")
    m.tick()
    assert m.degraded


@pytest.mark.parametrize("body", REGION_BODIES)
def test_F3_AC5_a_region_block_body_counts_as_an_access_error(body: str) -> None:
    assert is_region_block_body(body)
    m, clock, _, _ = monitor()
    healthy(m, clock)
    for _ in range(3):
        m.record_response(400, body)
    m.tick()
    assert m.degraded


@pytest.mark.parametrize("body", ["", "Too Many Requests", "internal error", '{"status":"ok"}'])
def test_F3_AC5_ordinary_bodies_are_not_region_blocks(body: str) -> None:
    assert not is_region_block_body(body)


def test_F3_AC5_error_count_of_one_trips_on_the_first_403() -> None:
    m, clock, _, _ = monitor(access__degraded_error_count=1)
    healthy(m, clock)
    m.tick()
    assert not m.degraded
    m.record_response(403, "")
    m.tick()
    assert m.degraded


def test_F3_AC5_error_count_of_two_needs_two() -> None:
    m, clock, _, _ = monitor(access__degraded_error_count=2)
    healthy(m, clock)
    m.record_response(451, "")
    m.tick()
    assert not m.degraded
    m.record_response(451, "")
    m.tick()
    assert m.degraded


def test_F3_AC5_error_count_threshold_at_the_config_maximum() -> None:
    m, clock, _, _ = monitor(access__degraded_error_count=20)
    healthy(m, clock, 400)  # keep the success rate far above the limit
    for _ in range(19):
        m.record_response(403, "")
    m.tick()
    assert not m.degraded
    m.record_response(403, "")
    m.tick()
    assert m.degraded


def test_F3_AC5_errors_spread_wider_than_the_window_do_not_add_up() -> None:
    m, clock, _, _ = monitor(access__degraded_window_min=5)
    healthy(m, clock)
    m.record_response(403, "")  # t0
    clock.advance(100 * SECOND)
    healthy(m, clock)
    m.record_response(403, "")  # t0 + ~102 s
    clock.advance(200 * SECOND)  # t0 + ~302 s: the first error is now out of the 5-minute window
    healthy(m, clock)
    m.record_response(403, "")
    m.tick()
    assert not m.degraded


def test_F3_AC5_errors_inside_the_window_do_add_up() -> None:
    m, clock, _, _ = monitor(access__degraded_window_min=5)
    healthy(m, clock)
    m.record_response(403, "")
    clock.advance(100 * SECOND)
    healthy(m, clock)
    m.record_response(403, "")
    clock.advance(150 * SECOND)  # about 254 s after the first
    healthy(m, clock)
    m.record_response(403, "")
    m.tick()
    assert m.degraded


# --- trigger: success rate -----------------------------------------------------------------------------------------

@pytest.mark.parametrize(("ok_n", "fail_n", "degraded"), [(8, 12, True), (10, 10, False), (12, 8, False), (0, 20, True)])
def test_F3_AC5_success_rate_below_the_minimum_degrades_at_exactly_below_not_at(
    ok_n: int, fail_n: int, degraded: bool
) -> None:
    m, clock, _, _ = monitor()  # minimum 0.5
    for _ in range(ok_n):
        m.record_response(200, "{}")
    for i in range(fail_n):
        m.record_timeout() if i % 2 else m.record_response(500, "")
    m.tick()
    assert m.degraded is degraded


@pytest.mark.parametrize(("ok_n", "degraded"), [(16, True), (18, False)])
def test_F3_AC5_success_rate_follows_the_configured_minimum(ok_n: int, degraded: bool) -> None:
    m, _, _, _ = monitor(access__degraded_min_success_rate=0.9)
    for _ in range(ok_n):
        m.record_response(200, "{}")
    for _ in range(20 - ok_n):
        m.record_timeout()
    # 16/20 = 0.8 < 0.9 degraded; 18/20 = 0.9 is not below 0.9
    m.tick()
    assert m.degraded is degraded


def test_F3_AC5_rate_limited_429s_are_not_access_denial() -> None:
    m, clock, _, _ = monitor()
    healthy(m, clock, 10)
    for _ in range(200):
        m.record_response(429, "")
    m.tick()
    assert not m.degraded


# --- effects -------------------------------------------------------------------------------------------------------

def _trip(m: AccessMonitor, clock: FakeClock) -> int:
    healthy(m, clock)
    for _ in range(3):
        m.record_response(403, "")
    tripped_at = clock.now_ms()
    m.tick()
    assert m.degraded
    return tripped_at


def test_F3_AC5_opens_and_adds_are_refused_and_exits_are_not() -> None:
    m, clock, _, _ = monitor()
    assert m.refusal_reason(ActionKind.OPEN) is None
    _trip(m, clock)
    assert m.refusal_reason(ActionKind.OPEN) == ACCESS_DEGRADED == "access_degraded"
    assert m.refusal_reason(ActionKind.ADD) == "access_degraded"
    assert m.refusal_reason(ActionKind.REDUCE) is None
    assert m.refusal_reason(ActionKind.CLOSE) is None


def test_F3_AC5_exactly_one_alert_within_60_seconds_and_no_repeats_while_degraded() -> None:
    m, clock, alerts, _ = monitor()
    _trip(m, clock)
    tick_for(m, clock, 60)
    assert len(alerts.of_kind("access_degraded")) == 1
    for _ in range(30):  # more errors during the episode
        m.record_response(403, "")
    tick_for(m, clock, 120)
    assert len(alerts.of_kind("access_degraded")) == 1
    assert all(isinstance(a, Alert) for a in alerts.sent)


def test_F3_AC5_the_client_keeps_sending_requests_while_degraded() -> None:
    rig = make_rig(handler=always(403, "blocked"))
    for _ in range(3):
        with pytest.raises(HlHttpError):
            rig.client.all_mids(priority=Priority.CRITICAL)
    rig.access.tick()
    assert rig.access.degraded
    sent_before = len(rig.http.calls)
    with pytest.raises(HlHttpError):
        rig.client.user_role(WALLET_A, priority=Priority.CRITICAL)
    assert len(rig.http.calls) == sent_before + 1  # exits, reconciliation and recording keep retrying


# --- recovery ------------------------------------------------------------------------------------------------------

def test_F3_AC5_clears_after_recover_min_healthy_minutes_and_not_before() -> None:
    m, clock, alerts, ledger = monitor()  # recover_min 10
    tripped_at = _trip(m, clock)
    serve_healthy_minutes(m, clock, 9)
    assert m.degraded  # 9 healthy minutes
    serve_healthy_minutes(m, clock, 2)  # 11 healthy minutes: one minute of slack for the minute buckets
    assert not m.degraded
    assert m.refusal_reason(ActionKind.OPEN) is None
    (rec,) = ledger.of_kind("access_degraded")
    assert isinstance(rec, DowntimeRecord)
    assert rec.wallets == ()
    assert tripped_at - 2 * SECOND <= rec.start_ms <= tripped_at + SECOND  # the moment it tripped
    assert rec.end_ms <= clock.now_ms() and rec.end_ms - rec.start_ms >= 10 * MINUTE


def test_F3_AC5_recover_min_follows_config() -> None:
    m, clock, _, _ = monitor(access__recover_min=1)
    _trip(m, clock)
    serve_healthy_minutes(m, clock, 3)
    assert not m.degraded


def test_F3_AC5_no_traffic_never_clears_the_state() -> None:
    m, clock, _, ledger = monitor()
    _trip(m, clock)
    tick_for(m, clock, 30 * 60)
    assert m.degraded
    assert ledger.of_kind("access_degraded") == []


def test_F3_AC5_a_bad_minute_restarts_the_recovery_clock() -> None:
    m, clock, _, _ = monitor()
    _trip(m, clock)
    serve_healthy_minutes(m, clock, 8)
    for _ in range(120):  # a burst of failures: far below 95% success
        m.record_timeout()
    burst_at = clock.now_ms()
    serve_healthy_minutes(m, clock, 9)
    assert m.degraded  # only 9 minutes since the burst
    serve_healthy_minutes(m, clock, 3)
    assert not m.degraded
    assert clock.now_ms() - burst_at >= 10 * MINUTE


def test_F3_AC5_a_success_rate_above_95_percent_counts_as_healthy() -> None:
    m, clock, _, _ = monitor(access__recover_min=1)
    _trip(m, clock)
    for _minute in range(4):
        for i in range(60):  # 2 failures in 60 = 96.7% success
            clock.advance(SECOND)
            m.record_timeout() if i < 2 else m.record_response(200, "{}")
            m.tick()
    assert not m.degraded


def test_F3_AC5_a_success_rate_well_below_95_percent_never_clears_the_state() -> None:
    m, clock, _, _ = monitor(access__recover_min=1)
    _trip(m, clock)
    for _minute in range(15):
        for i in range(60):  # 10 failures in 60 = 83% success
            clock.advance(SECOND)
            m.record_timeout() if i % 6 == 0 else m.record_response(200, "{}")
            m.tick()
    assert m.degraded


def test_F3_AC5_a_second_episode_alerts_again() -> None:
    m, clock, alerts, ledger = monitor(access__recover_min=1)
    _trip(m, clock)
    tick_for(m, clock, 5)
    serve_healthy_minutes(m, clock, 3)
    assert not m.degraded
    for _ in range(3):
        m.record_response(451, "")
    tick_for(m, clock, 5)
    assert m.degraded
    assert len(alerts.of_kind("access_degraded")) == 2
    assert len(ledger.of_kind("access_degraded")) == 1  # the first episode's downtime; the second is still open
