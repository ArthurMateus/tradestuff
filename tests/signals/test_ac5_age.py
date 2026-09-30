"""F7.AC5: every signal carries the exchange timestamp, the local receive timestamp and
``age_ms = (receive_local + offset) - exchange_ts``; an age below minus ``clock.max_offset_uncertainty_ms`` is
``clock_anomaly`` and refused for opens (and adds).

Spec: 04-spec.md F7.AC5, F1.AC6 (clock offset), §3.1 ``clock.max_offset_uncertainty_ms``, invariants B1, B2.
The real ``ClockSync`` runs over a fake offset source, so the offset the detector uses is the real one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.core.clock import TimeSource
from copytrade.core.domain import ActionKind
from copytrade.signals.models import FLAG_CLOCK_ANOMALY, FLAG_CLOCK_UNSYNCED
from tests.signals.helpers import T0, Rig, make_rig, mkfill

pytestmark = pytest.mark.unit


def test_F7_AC5_a_signal_carries_both_timestamps_with_their_sources_and_the_age(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(offset_ms=250)  # exchange clock = local clock + 250 ms
    (s,) = rig.feed([mkfill(1, time_ms=T0 + 250 - 700)])
    assert (s.exchange_ts.ms, s.exchange_ts.source) == (T0 + 250 - 700, TimeSource.EXCHANGE)
    assert (s.receive_ts.ms, s.receive_ts.source) == (T0, TimeSource.LOCAL)
    assert s.age_ms == 700
    assert s.flags == frozenset() and s.refusal_reason() is None
    (p,) = rig.ledger_signals()
    assert p["age_ms"] == 700 and p["exchange_ts"]["ms"] == T0 + 250 - 700 and p["receive_ts"]["ms"] == T0


@pytest.mark.parametrize(
    ("offset", "delta", "age"), [(0, -1500, 1500), (-300, -300, 0), (400, -100, 500), (0, 0, 0), (0, 3_600_000, -3_600_000)]
)
def test_F7_AC5_age_is_receive_plus_offset_minus_exchange_time(
    rig_factory: Callable[..., Rig], offset: int, delta: int, age: int
) -> None:
    rig = rig_factory(offset_ms=offset)
    (s,) = rig.feed([mkfill(1, time_ms=T0 + delta)])  # the local clock is frozen at T0
    assert s.age_ms == age == T0 + offset - (T0 + delta)


def test_F7_AC5_the_receive_time_is_the_moment_the_batch_arrived(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    fill = mkfill(1, time_ms=T0 - 200)
    rig.clock.advance(5_000)
    (s,) = rig.feed([fill])
    assert s.receive_ts.ms == T0 + 5_000 and s.age_ms == 5_200


@pytest.mark.parametrize(("age", "anomaly"), [(-99, False), (-100, False), (-101, True), (-5_000, True), (0, False), (10_000, False)])
def test_F7_AC5_an_age_below_minus_the_max_offset_uncertainty_is_a_clock_anomaly(
    rig_factory: Callable[..., Rig], age: int, anomaly: bool
) -> None:
    rig = rig_factory()  # clock.max_offset_uncertainty_ms = 100
    (s,) = rig.feed([mkfill(1, time_ms=T0 - age)])
    assert s.age_ms == age
    assert (FLAG_CLOCK_ANOMALY in s.flags) is anomaly
    assert s.refusal_reason() == ("clock_anomaly" if anomaly else None)
    assert FLAG_CLOCK_ANOMALY == "clock_anomaly"


@pytest.mark.parametrize(("limit", "age", "anomaly"), [(10, -10, False), (10, -11, True), (500, -500, False), (500, -501, True)])
def test_F7_AC5_the_anomaly_threshold_follows_config(
    rig_factory: Callable[..., Rig], limit: int, age: int, anomaly: bool
) -> None:
    rig = rig_factory(clock__max_offset_uncertainty_ms=limit, uncertainty_ms=5)
    (s,) = rig.feed([mkfill(1, time_ms=T0 - age)])
    assert (FLAG_CLOCK_ANOMALY in s.flags) is anomaly


def test_F7_AC5_a_clock_anomaly_refuses_opens_and_adds_but_never_exits(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    future = T0 + 10_000
    got = rig.feed(
        [
            mkfill(1, side="B", sz="1", start="0", time_ms=future),
            mkfill(2, side="B", sz="1", start="1", time_ms=future),
            mkfill(3, side="A", sz="1", start="2", time_ms=future),
            mkfill(4, side="A", sz="1", start="1", time_ms=future),
        ]
    )
    assert [s.action for s in got] == [ActionKind.OPEN, ActionKind.ADD, ActionKind.REDUCE, ActionKind.CLOSE]
    assert all(FLAG_CLOCK_ANOMALY in s.flags for s in got)  # every leg is flagged...
    assert [s.refusal_reason() for s in got] == ["clock_anomaly", "clock_anomaly", None, None]  # ...exits are never refused


def test_F7_AC5_both_halves_of_a_flip_are_flagged_and_only_the_open_half_is_refused(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    close_leg, open_leg = rig.feed([mkfill(1, side="A", sz="3", start="1", time_ms=T0 + 10_000)])
    assert FLAG_CLOCK_ANOMALY in close_leg.flags and FLAG_CLOCK_ANOMALY in open_leg.flags
    assert close_leg.refusal_reason() is None and open_leg.refusal_reason() == "clock_anomaly"


def test_F7_AC5_a_very_old_fill_has_a_large_positive_age_and_is_still_signalled_for_the_exit_path(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    old = T0 - 3 * 3_600_000
    got = rig.feed([mkfill(1, side="A", sz="1", start="1", time_ms=old), mkfill(2, time_ms=old)])
    assert [s.age_ms for s in got] == [3 * 3_600_000] * 2  # F9 refuses the stale open; F7 must not drop the exit
    assert [s.action for s in got] == [ActionKind.CLOSE, ActionKind.OPEN]
    assert all(s.flags == frozenset() for s in got)


def test_F7_AC5_while_the_clock_is_unsynced_the_age_is_unknown_and_entries_are_refused_but_exits_are_signalled(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, synced=False)
    try:
        got = rig.feed([mkfill(1), mkfill(2, side="A", sz="1", start="1")])
        assert [s.age_ms for s in got] == [None, None]
        assert all(FLAG_CLOCK_UNSYNCED in s.flags for s in got)
        assert [s.refusal_reason() for s in got] == ["clock_unsynced", None]
        assert FLAG_CLOCK_UNSYNCED == "clock_unsynced"
        assert rig.ledger_signals()[0]["age_ms"] is None
    finally:
        rig.ledger.close()


def test_F7_AC5_after_the_clock_syncs_the_age_is_known_again(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, synced=False)
    try:
        rig.feed([mkfill(1)])
        rig.sync.tick()
        (s,) = rig.feed([mkfill(2, time_ms=T0 - 400)])
        assert s.age_ms == 400 and FLAG_CLOCK_UNSYNCED not in s.flags
    finally:
        rig.ledger.close()


def test_F7_AC5_the_offset_used_is_the_one_current_when_the_batch_arrives(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(offset_ms=100)
    (a,) = rig.feed([mkfill(1, time_ms=T0)])
    rig.offset.offset_ms = 600
    rig.clock.advance(601_000)  # the next estimate is due
    rig.sync.tick()
    (b,) = rig.feed([mkfill(2, time_ms=T0 + 601_000)])
    assert (a.age_ms, b.age_ms) == (100, 600)


@given(
    offset=st.integers(-2000, 2000),
    exchange_delta=st.integers(-10_000_000, 10_000_000),
    wait=st.integers(0, 10_000),
)
def test_F7_AC5_property_age_is_always_receive_plus_offset_minus_exchange(offset: int, exchange_delta: int, wait: int) -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        rig = make_rig(Path(tmp), offset_ms=offset)
        try:
            rig.clock.advance(wait)
            (s,) = rig.feed([mkfill(1, time_ms=T0 + exchange_delta)])
            assert s.age_ms == (T0 + wait) + offset - (T0 + exchange_delta)
            assert isinstance(s.age_ms, int)
            assert (FLAG_CLOCK_ANOMALY in s.flags) == (s.age_ms < -100)
        finally:
            rig.ledger.close()


def test_F7_AC5_s2_is_the_receive_to_classified_time_of_the_injected_clock(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    got = rig.feed([mkfill(1), mkfill(2, coin="ETH")])
    assert [s.s2_ms for s in got] == [0, 0]  # a frozen clock: no time passes while classifying
    assert all(isinstance(s.s2_ms, int) and s.s2_ms >= 0 for s in got)
