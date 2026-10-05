"""F3.AC5 round 2 (senior-dev BLOCKING 3): access thresholds. Recovery success-rate bucket boundary (95%), window expiry
of the access-error count and of the success-rate sample, and the multi-minute bucket gap. Fake clock, no sleeping.
"""

from __future__ import annotations

import pytest

from copytrade.hl.access import AccessMonitor
from tests.hl.support import MINUTE, SECOND, FakeClock, RecordingAlerts, RecordingLedger, T0, make_config

pytestmark = pytest.mark.unit


def monitor(**overrides: object) -> tuple[AccessMonitor, FakeClock]:
    clock = FakeClock()
    m = AccessMonitor(config=make_config(**overrides), clock=clock, alerts=RecordingAlerts(), ledger=RecordingLedger())
    return m, clock


def tripped(**overrides: object) -> tuple[AccessMonitor, FakeClock]:
    m, clock = monitor(**overrides)
    for _ in range(20):
        m.record_response(200, "{}")
    for _ in range(3):
        m.record_response(403, "")
    m.tick()
    assert m.degraded
    return m, clock


def one_minute(m: AccessMonitor, clock: FakeClock, *, ok: int, failed: int) -> None:
    """All requests of one whole minute at its first instant, then the minute elapses and the monitor ticks."""
    for _ in range(ok):
        m.record_response(200, "{}")
    for _ in range(failed):
        m.record_timeout()
    clock.advance(MINUTE)
    m.tick()


# --- recovery bucket at 95% ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("ok", "failed"), [(95, 5), (19, 1), (190, 10)])
def test_F3_AC5_a_minute_at_exactly_95_percent_success_counts_as_healthy(ok: int, failed: int) -> None:
    m, clock = tripped(access__recover_min=1)
    one_minute(m, clock, ok=ok, failed=failed)
    assert not m.degraded


@pytest.mark.parametrize(("ok", "failed"), [(94, 6), (189, 11), (92, 8), (90, 10), (0, 1)])
def test_F3_AC5_a_minute_just_under_95_percent_success_is_not_healthy_and_never_clears(ok: int, failed: int) -> None:
    m, clock = tripped(access__recover_min=1)
    for _ in range(6):
        one_minute(m, clock, ok=ok, failed=failed)
    assert m.degraded


def test_F3_AC5_a_minute_just_under_95_percent_restarts_the_recovery_count() -> None:
    m, clock = tripped(access__recover_min=3)
    one_minute(m, clock, ok=100, failed=0)
    one_minute(m, clock, ok=100, failed=0)
    one_minute(m, clock, ok=94, failed=6)  # just under: the two healthy minutes no longer count
    one_minute(m, clock, ok=100, failed=0)
    one_minute(m, clock, ok=100, failed=0)
    assert m.degraded
    one_minute(m, clock, ok=95, failed=5)  # exactly 95%: the third consecutive healthy minute
    assert not m.degraded


# --- access-error window expiry (403/451 count) ----------------------------------------------------------------------


@pytest.mark.parametrize("window_min", [1, 5, 30])
@pytest.mark.parametrize("codes", [(403, 403, 403), (451, 403, 451)])
@pytest.mark.parametrize(("offset_ms", "degraded"), [(-1, True), (0, False), (1, False)])
def test_F3_AC5_an_access_error_leaves_the_count_window_after_exactly_the_window(
    window_min: int, codes: tuple[int, int, int], offset_ms: int, degraded: bool
) -> None:
    m, clock = monitor(access__degraded_window_min=window_min)
    window = window_min * MINUTE
    first = T0 + SECOND
    clock.now = T0
    for _ in range(40):  # healthy traffic throughout, so only the access-error count can trip
        m.record_response(200, "{}")
    clock.now = first
    m.record_response(codes[0], "")
    clock.now = first + SECOND
    for _ in range(40):
        m.record_response(200, "{}")
    m.record_response(codes[1], "")
    clock.now = first + window + offset_ms  # the first error is window + offset_ms old
    for _ in range(40):
        m.record_response(200, "{}")
    m.record_response(codes[2], "")
    m.tick()
    assert m.degraded is degraded


@pytest.mark.parametrize(("offset_ms", "degraded"), [(-1, False), (0, True), (1, True)])
def test_F3_AC5_a_success_leaves_the_success_rate_sample_after_exactly_the_window(
    offset_ms: int, degraded: bool
) -> None:
    m, clock = monitor()  # window 5 min, minimum success rate 0.5
    clock.now = T0
    for _ in range(10):
        m.record_response(200, "{}")
    clock.now = T0 + 5 * MINUTE + offset_ms  # the ten successes are this old
    for _ in range(10):
        m.record_timeout()
    m.tick()
    assert m.degraded is degraded  # 10 old successes still count one ms before expiry (10/20), not at expiry (0/10)


# --- multi-minute gap between two evaluations ------------------------------------------------------------------------


def test_F3_AC5_a_multi_minute_gap_without_ticks_never_counts_as_consecutive_healthy_minutes() -> None:
    m, clock = tripped(access__recover_min=2)
    one_minute(m, clock, ok=100, failed=0)  # 1 healthy minute
    assert m.degraded
    for _ in range(100):
        m.record_response(200, "{}")
    clock.advance(3 * MINUTE)  # nobody ticked for three whole minutes
    m.tick()
    assert m.degraded  # the silent minutes are not healthy, so the run of healthy minutes is broken
    one_minute(m, clock, ok=100, failed=0)
    assert m.degraded  # only one healthy minute since the gap
    one_minute(m, clock, ok=100, failed=0)
    assert not m.degraded
