"""F1.AC6: UTC epoch-ms timestamps with a source tag; clock-offset guard.

The offset is re-estimated every ``clock.offset_interval_s``. With uncertainty above
``clock.max_offset_uncertainty_ms``, or no estimate for more than ``clock.max_estimate_age_s``, opens
and adds are refused ``clock_unsynced`` within 1 s, one alert is sent, and exits continue.

The local clock and the offset source are external boundaries: fakes are injected, no sleeping.
Spec: 04-spec.md F1.AC6, §3.1 clock.*, §5 "Clock offset unknown or too large" and "NTP unreachable", B1/B2.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.core.clock import ClockSync, OffsetEstimate, TimeSource, Timestamp
from copytrade.core.config import load_config
from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert
from tests.core.helpers import ConfigTree

pytestmark = pytest.mark.unit

T0 = 1_790_000_000_000  # 2026-09-21T14:13:20Z in epoch ms
SECOND = 1_000
ENTRIES = (ActionKind.OPEN, ActionKind.ADD)
EXITS = (ActionKind.REDUCE, ActionKind.CLOSE)


class FakeClock:
    def __init__(self, now_ms: int = T0) -> None:
        self.now = now_ms

    def now_ms(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


@dataclass
class ScriptedOffsetSource:
    """Returns ``good`` estimates until told otherwise; ``fail`` makes it raise like an unreachable NTP server."""

    next_estimate: OffsetEstimate | None = field(default_factory=lambda: OffsetEstimate(offset_ms=250, uncertainty_ms=20))
    calls: int = 0

    def estimate(self) -> OffsetEstimate:
        self.calls += 1
        if self.next_estimate is None:
            raise OSError("offset source unreachable")
        return self.next_estimate


@dataclass
class RecordingAlerts:
    sent: list[Alert] = field(default_factory=list)

    def send(self, alert: Alert) -> None:
        self.sent.append(alert)

    def of_kind(self, kind: str) -> list[Alert]:
        return [a for a in self.sent if a.kind == kind]


def make_sync(
    *, interval_s: int = 600, max_unc_ms: int = 100, max_age_s: int = 1800
) -> tuple[ClockSync, FakeClock, ScriptedOffsetSource, RecordingAlerts]:
    clock, source, alerts = FakeClock(), ScriptedOffsetSource(), RecordingAlerts()
    sync = ClockSync(
        offset_interval_s=interval_s,
        max_offset_uncertainty_ms=max_unc_ms,
        max_estimate_age_s=max_age_s,
        clock=clock,
        source=source,
        alerts=alerts,
    )
    return sync, clock, source, alerts


def tick_every_second(sync: ClockSync, clock: FakeClock, seconds: int) -> None:
    for _ in range(seconds):
        clock.advance(SECOND)
        sync.tick()


def refusals(sync: ClockSync, kinds: Iterable[ActionKind]) -> list[str | None]:
    return [sync.refusal_reason(k) for k in kinds]


# --- timestamps -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("source", list(TimeSource))
def test_F1_AC6_timestamp_is_epoch_ms_with_a_source_tag(source: TimeSource) -> None:
    ts = Timestamp(ms=T0, source=source)
    assert ts.ms == T0 and ts.source is source


def test_F1_AC6_source_tags_are_exchange_local_derived() -> None:
    assert {s.value for s in TimeSource} == {"exchange", "local", "derived"}


@pytest.mark.parametrize("ms", [float(T0), T0 + 0.5, True, "1790000000000", None], ids=repr)
def test_F1_AC6_timestamp_rejects_non_integer_ms(ms: object) -> None:
    with pytest.raises(TypeError):
        Timestamp(ms=ms, source=TimeSource.LOCAL)  # type: ignore[arg-type]


@pytest.mark.parametrize("source", ["exchange", None, 1], ids=repr)
def test_F1_AC6_timestamp_requires_a_timesource(source: object) -> None:
    with pytest.raises(TypeError):
        Timestamp(ms=T0, source=source)  # type: ignore[arg-type]


def test_F1_AC6_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        Timestamp.from_datetime(datetime(2026, 9, 29, 12, 0, 0), TimeSource.LOCAL)


def test_F1_AC6_aware_datetime_in_another_zone_is_converted_to_utc() -> None:
    brt = timezone(timedelta(hours=-3))  # the PO's zone
    ts = Timestamp.from_datetime(datetime(2026, 9, 29, 21, 0, 0, 123_999, tzinfo=brt), TimeSource.EXCHANGE)
    assert ts.ms == int(datetime(2026, 9, 30, 0, 0, 0, tzinfo=timezone.utc).timestamp()) * 1000 + 123
    assert ts.to_datetime() == datetime(2026, 9, 30, 0, 0, 0, 123_000, tzinfo=timezone.utc)
    assert ts.to_datetime().utcoffset() == timedelta(0)


@given(ms=st.integers(min_value=0, max_value=4_102_444_800_000), source=st.sampled_from(list(TimeSource)))
def test_F1_AC6_property_datetime_round_trip_preserves_ms_and_source(ms: int, source: TimeSource) -> None:
    ts = Timestamp(ms=ms, source=source)
    back = Timestamp.from_datetime(ts.to_datetime(), source)
    assert back == ts


# --- offset estimation cadence ------------------------------------------------------------------------------

def test_F1_AC6_offset_is_estimated_on_first_tick_and_then_every_interval() -> None:
    sync, clock, source, _ = make_sync(interval_s=600)
    sync.tick()
    assert source.calls == 1
    clock.advance(600 * SECOND - 1)
    sync.tick()
    assert source.calls == 1  # one ms before the interval: not yet
    clock.advance(1)
    sync.tick()
    assert source.calls == 2  # exactly at the interval
    tick_every_second(sync, clock, 600)
    assert source.calls == 3


def test_F1_AC6_exchange_now_applies_the_offset_and_is_tagged_derived() -> None:
    sync, clock, source, _ = make_sync()
    source.next_estimate = OffsetEstimate(offset_ms=-1_234, uncertainty_ms=5)
    sync.tick()
    now = sync.exchange_now()
    assert now.ms == clock.now - 1_234
    assert now.source is TimeSource.DERIVED


def test_F1_AC6_from_config_uses_the_clock_keys(tmp_path: Path) -> None:
    config = load_config(
        ConfigTree()
        .set("clock.offset_interval_s", 900)
        .set("clock.max_offset_uncertainty_ms", 50)
        .set("clock.max_estimate_age_s", 1200)
        .write(tmp_path / "config")
    )
    sync = ClockSync.from_config(config, clock=FakeClock(), source=ScriptedOffsetSource(), alerts=RecordingAlerts())
    assert (sync.offset_interval_s, sync.max_offset_uncertainty_ms, sync.max_estimate_age_s) == (900, 50, 1200)


# --- synced: nothing refused ---------------------------------------------------------------------------------

def test_F1_AC6_synced_clock_refuses_nothing() -> None:
    sync, _, _, alerts = make_sync()
    sync.tick()
    assert refusals(sync, ActionKind) == [None] * len(ActionKind)
    assert alerts.sent == []


def test_F1_AC6_before_any_estimate_entries_are_refused_fail_closed() -> None:
    sync, _, _, _ = make_sync()
    assert refusals(sync, ENTRIES) == ["clock_unsynced"] * 2
    assert refusals(sync, EXITS) == [None, None]


# --- uncertainty threshold -------------------------------------------------------------------------------------

@pytest.mark.parametrize(("uncertainty_ms", "refused"), [(99, False), (100, False), (101, True)])
def test_F1_AC6_uncertainty_boundary(uncertainty_ms: int, refused: bool) -> None:
    sync, _, source, _ = make_sync(max_unc_ms=100)
    source.next_estimate = OffsetEstimate(offset_ms=0, uncertainty_ms=uncertainty_ms)
    sync.tick()
    expected = "clock_unsynced" if refused else None
    assert refusals(sync, ENTRIES) == [expected, expected]
    assert refusals(sync, EXITS) == [None, None]


def test_F1_AC6_high_uncertainty_refuses_entries_immediately_alerts_once_and_keeps_exits() -> None:
    sync, clock, source, alerts = make_sync(interval_s=60, max_unc_ms=100)
    sync.tick()
    source.next_estimate = OffsetEstimate(offset_ms=0, uncertainty_ms=450)
    clock.advance(60 * SECOND)
    sync.tick()  # the re-estimate that sees the bad uncertainty
    assert refusals(sync, ENTRIES) == ["clock_unsynced"] * 2  # within 1 s: at once
    assert refusals(sync, EXITS) == [None, None]
    tick_every_second(sync, clock, 300)  # five more bad re-estimates
    assert len(alerts.of_kind("clock_unsynced")) == 1


# --- estimate age threshold ------------------------------------------------------------------------------------

def test_F1_AC6_estimate_age_boundary_and_single_alert_while_source_is_down() -> None:
    sync, clock, source, alerts = make_sync(interval_s=600, max_age_s=1800)
    sync.tick()  # the last good estimate, at T0
    source.next_estimate = None  # NTP / server time unreachable from now on
    tick_every_second(sync, clock, 1800)  # age exactly 1800 s: "more than" is not yet reached
    assert refusals(sync, ENTRIES) == [None, None]
    assert alerts.of_kind("clock_unsynced") == []
    tick_every_second(sync, clock, 1)  # 1801 s: refused within 1 s of crossing the limit
    assert refusals(sync, ENTRIES) == ["clock_unsynced"] * 2
    assert refusals(sync, EXITS) == [None, None]
    tick_every_second(sync, clock, 3600)
    assert refusals(sync, ENTRIES) == ["clock_unsynced"] * 2
    assert len(alerts.of_kind("clock_unsynced")) == 1


def test_F1_AC6_failing_offset_source_never_raises_out_of_tick() -> None:
    sync, clock, source, _ = make_sync(interval_s=60)
    source.next_estimate = None
    sync.tick()
    tick_every_second(sync, clock, 180)  # several failed attempts
    assert source.calls >= 2


# --- recovery and a second episode ---------------------------------------------------------------------------

def test_F1_AC6_recovery_clears_the_refusal_and_a_new_episode_alerts_again() -> None:
    sync, clock, source, alerts = make_sync(interval_s=60, max_unc_ms=100)
    source.next_estimate = OffsetEstimate(offset_ms=0, uncertainty_ms=500)
    sync.tick()
    assert refusals(sync, ENTRIES) == ["clock_unsynced"] * 2

    source.next_estimate = OffsetEstimate(offset_ms=0, uncertainty_ms=10)
    tick_every_second(sync, clock, 60)
    assert refusals(sync, ENTRIES) == [None, None]

    source.next_estimate = OffsetEstimate(offset_ms=0, uncertainty_ms=500)
    tick_every_second(sync, clock, 60)
    assert refusals(sync, ENTRIES) == ["clock_unsynced"] * 2
    assert len(alerts.of_kind("clock_unsynced")) == 2
