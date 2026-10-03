"""F3.AC1 and F3.AC6 round 2 (advisory boundaries): a request weighing exactly the whole budget, the schema-failure
10-minute window edge, and the alert episode reset after a quiet period.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from copytrade.hl.budget import Priority, RateBudget
from copytrade.hl.schema import SchemaFailureMonitor
from tests.hl.support import MINUTE, SECOND, FakeClock, RecordingAlerts

pytestmark = pytest.mark.unit


def budget(total: int = 100, share: str = "0.5") -> tuple[RateBudget, FakeClock]:
    clock = FakeClock()
    return RateBudget(budget_per_min=total, scoring_share=Decimal(share), clock=clock), clock


def sm() -> tuple[SchemaFailureMonitor, FakeClock, RecordingAlerts]:
    clock, alerts = FakeClock(), RecordingAlerts()
    return SchemaFailureMonitor(clock=clock, alerts=alerts), clock, alerts


# --- budget: weight == whole budget ----------------------------------------------------------------------------------


def test_F3_AC1_a_request_weighing_exactly_the_whole_budget_is_served_on_an_empty_window() -> None:
    b, _ = budget(100)
    assert b.wait_ms(100, Priority.CRITICAL) == 0
    assert b.try_acquire(100, Priority.CRITICAL)
    assert b.used() == 100
    assert not b.try_acquire(1, Priority.CRITICAL)


def test_F3_AC1_a_request_weighing_exactly_the_whole_budget_waits_for_the_window_it_is_not_refused_for_good() -> None:
    b, clock = budget(100)
    assert b.try_acquire(1, Priority.CRITICAL)
    assert b.wait_ms(100, Priority.CRITICAL) == MINUTE  # it fits once that 1 has left, so it is not "never"
    clock.advance(MINUTE)
    assert b.try_acquire(100, Priority.CRITICAL)


def test_F3_AC1_a_scoring_request_weighing_exactly_the_scoring_cap_is_served_and_one_more_never_is() -> None:
    b, _ = budget(100, "0.5")
    assert b.wait_ms(50, Priority.SCORING) == 0
    assert b.wait_ms(51, Priority.SCORING) is None
    assert b.try_acquire(50, Priority.SCORING)


# --- schema failure monitor ------------------------------------------------------------------------------------------


def test_F3_AC6_a_failure_exactly_ten_minutes_old_no_longer_counts() -> None:
    m, clock, alerts = sm()
    m.record_failure("l2Book")
    clock.advance(5 * MINUTE)
    m.record_failure("l2Book")
    clock.advance(5 * MINUTE)  # the first is exactly 10 minutes old
    m.record_failure("l2Book")
    assert alerts.sent == []


def test_F3_AC6_a_failure_one_ms_short_of_ten_minutes_old_still_counts() -> None:
    m, clock, alerts = sm()
    m.record_failure("l2Book")
    clock.advance(5 * MINUTE)
    m.record_failure("l2Book")
    clock.advance(5 * MINUTE - 1)
    m.record_failure("l2Book")
    assert len(alerts.sent) == 1


def test_F3_AC6_a_later_burst_after_a_quiet_period_alerts_again() -> None:
    m, clock, alerts = sm()
    for _ in range(3):
        m.record_failure("allMids")
        clock.advance(SECOND)
    assert len(alerts.sent) == 1
    clock.advance(11 * MINUTE)  # quiet: the episode is over
    m.record_failure("allMids")
    m.record_failure("allMids")
    assert len(alerts.sent) == 1  # two failures are not yet a new burst
    m.record_failure("allMids")
    assert len(alerts.sent) == 2
    assert "allMids" in alerts.sent[1].message


def test_F3_AC6_a_sustained_failure_stream_is_one_episode_not_one_alert_per_window() -> None:
    m, clock, alerts = sm()
    for _ in range(60):  # a failure every 30 s for 30 minutes: the trailing window never drops below 3
        m.record_failure("userRole")
        clock.advance(30 * SECOND)
    assert len(alerts.sent) == 1
