"""R2.AC1 at the unit level: the restart catch-up of an UNVERIFIED time base is forward-only and never trusts the clock.

While the baseline is unverified and no synced sample has arrived, broker time follows the live exchange time the
``live_time_ms`` source reports (newest book / raw estimate) but only ever forward, and entries stay refused."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.errors import ClockUnsyncedError
from copytrade.runner.timebase import SKIP_CLOCK_UNSYNCED, TimeBase
from tests.hl.support import FakeClock
from tests.runner.world import T0

UNCERT = 100


class Unsynced:
    def exchange_now(self) -> Timestamp:
        raise ClockUnsyncedError("unsynced")


class Live:
    def __init__(self) -> None:
        self.ms: int | None = None

    def __call__(self) -> int | None:
        return self.ms


def unverified(replayed_ms: int) -> tuple[TimeBase, FakeClock, Live]:
    clock, live = FakeClock(T0), Live()
    tb = TimeBase(
        exchange_time=Unsynced(),
        clock=clock,
        max_offset_uncertainty_ms=UNCERT,
        monotonic_ms=clock.now_ms,
        live_time_ms=live,
    )
    tb.seed_unverified(replayed_ms)
    return tb, clock, live


def test_R2_AC1_broker_time_jumps_forward_to_the_live_time_and_entries_stay_refused() -> None:
    tb, clock, live = unverified(T0 - 120_000)
    assert tb.next_target_ms() == (T0 - 120_000, SKIP_CLOCK_UNSYNCED)  # nothing live is known yet
    live.ms = T0 + 5_000
    assert tb.next_target_ms() == (T0 + 5_000, SKIP_CLOCK_UNSYNCED)
    clock.advance(1_000)
    assert tb.next_target_ms() == (T0 + 6_000, SKIP_CLOCK_UNSYNCED)  # then it runs on the monotonic projection


def test_R2_AC1_a_live_time_behind_the_projection_never_moves_broker_time_back() -> None:
    tb, clock, live = unverified(T0)
    live.ms = T0 - 30_000
    clock.advance(2_000)
    assert tb.next_target_ms() == (T0 + 2_000, SKIP_CLOCK_UNSYNCED)
    live.ms = T0 + 1_999  # a book that is a little older than the projection (latency): the projection stands
    clock.advance(1_000)
    assert tb.next_target_ms() == (T0 + 3_000, SKIP_CLOCK_UNSYNCED)


@given(st.lists(st.tuples(st.integers(0, 5_000), st.one_of(st.none(), st.integers(-200_000, 200_000))), max_size=40))
def test_R2_AC1_broker_time_is_forward_only_whatever_the_live_time_reports(
    steps: list[tuple[int, int | None]],
) -> None:
    tb, clock, live = unverified(T0 - 60_000)
    last = T0 - 60_000
    for advance_ms, offset in steps:
        clock.advance(advance_ms)
        live.ms = None if offset is None else clock.now_ms() + offset
        target, reason = tb.next_target_ms()
        assert target is not None and target >= last
        assert reason == SKIP_CLOCK_UNSYNCED
        last = target
