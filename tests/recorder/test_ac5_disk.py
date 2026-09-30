"""F4.AC5: disk guard. Alert threshold, hard floor (recording stops safely, opens and adds refused with ``disk_low``,
exits and the ledger continue), automatic resume above floor + margin, and the stopped interval is a gap.

Spec: 04-spec.md F4.AC5, §3.3 ``recording.disk_*``, §5 "Free disk below the alert threshold / hard floor", invariants A2, A8.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from copytrade.recorder.gaps import gap_stats
from copytrade.recorder.records import STREAM_L2
from copytrade.recorder.service import ALERT_DISK_FLOOR, ALERT_DISK_FREE_LOW, DISK_LOW, KIND_DOWNTIME
from tests.recorder.helpers import DAY, DAY0, HOUR, MINUTE, SECOND, Rig, book

pytestmark = pytest.mark.integration

ENTRIES = (ActionKind.OPEN, ActionKind.ADD)
EXITS = (ActionKind.REDUCE, ActionKind.CLOSE)


def feed_books(rig: Rig, coin: str = "BTC") -> None:
    """One book per second for ``coin`` as long as the test runs."""
    rig.feed.generator = lambda now: [book(coin, now - 30)]


def l2_times(rig: Rig, coin: str = "BTC") -> list[int]:
    return [r.receive_ts_ms for r in rig.store.scan(STREAM_L2, coin, DAY0, DAY0 + 30 * DAY)]


def closed(rig: Rig) -> list[dict[str, Any]]:
    return [dict(r.payload) for r in rig.ledger.records() if r.kind == "recording_file_closed"]


# --- checks and the alert threshold ------------------------------------------------------------------------------------


def test_F4_AC5_free_space_is_probed_on_every_volume_holding_the_three_directories_each_check_interval(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()  # recording.disk_check_interval_s = 60
    rig.run(300)
    for path in (rig.paths.recordings_dir, rig.paths.ledger_dir, rig.paths.cache_dir):
        assert 4 <= rig.disk.probed.count(path) <= 6


def test_F4_AC5_the_check_interval_follows_config(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(recording__disk_check_interval_s=10)
    rig.run(300)
    assert 28 <= rig.disk.probed.count(rig.paths.recordings_dir) <= 32


def test_F4_AC5_no_alert_at_exactly_the_alert_threshold_and_one_alert_just_below_it(rig_factory: Callable[..., Rig]) -> None:
    at = rig_factory()
    at.disk.set(None, "20.00")
    at.run(300)
    assert at.alerts.of_kind(ALERT_DISK_FREE_LOW) == []
    below = rig_factory()
    below.disk.set(None, "19.99")
    below.run(300)
    assert len(below.alerts.of_kind(ALERT_DISK_FREE_LOW)) == 1
    assert below.recorder.recording is True  # an alert is not a stop


def test_F4_AC5_the_alert_states_the_free_gb_and_the_unarchived_backlog(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.backlog.value = type(rig.backlog.value)(days=3, gb=Decimal("4.25"))
    rig.disk.set(None, "17.5")
    rig.run(120)
    (alert,) = rig.alerts.of_kind(ALERT_DISK_FREE_LOW)
    assert "17.5" in alert.message
    assert "3" in alert.message and "4.25" in alert.message


def test_F4_AC5_the_low_disk_alert_repeats_at_most_once_per_six_hours(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.disk.set(None, "15")
    rig.run(6 * 3600 - 2 * MINUTE // SECOND)
    assert len(rig.alerts.of_kind(ALERT_DISK_FREE_LOW)) == 1
    rig.run(4 * MINUTE // SECOND)
    assert len(rig.alerts.of_kind(ALERT_DISK_FREE_LOW)) == 2


def test_F4_AC5_a_low_volume_that_only_holds_the_cache_directory_still_triggers_the_alert(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.disk.set(None, "500")
    rig.disk.set(rig.paths.cache_dir, "12")
    rig.run(120)
    assert len(rig.alerts.of_kind(ALERT_DISK_FREE_LOW)) == 1


# --- the hard floor ---------------------------------------------------------------------------------------------------------


def test_F4_AC5_at_exactly_the_floor_recording_continues_and_just_below_it_stops_within_two_check_intervals(
    rig_factory: Callable[..., Rig],
) -> None:
    at = rig_factory()
    feed_books(at)
    at.disk.set(None, "8.00")
    at.run(300)
    assert at.recorder.recording is True and at.recorder.refusal_reason(ActionKind.OPEN) is None
    below = rig_factory()
    feed_books(below)
    below.run(120)
    below.disk.set(None, "7.99")
    dropped_at = below.clock.now_ms()
    below.run(2 * 60)
    assert below.recorder.recording is False
    assert below.clock.now_ms() - dropped_at <= 2 * 60 * SECOND


def test_F4_AC5_at_the_floor_open_files_are_closed_atomically_with_reason_disk_floor_and_one_alert_is_sent(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    feed_books(rig)
    rig.run(200)
    rig.disk.set(None, "5.0")
    rig.run(180)
    files = closed(rig)
    assert files and {f["reason"] for f in files} == {"disk_floor"}
    assert len(files) == len({f["path"] for f in files})
    for f in files:
        assert (rig.paths.recordings_dir / f["path"]).is_file()  # renamed into place: no partial file
    assert not [p for p in rig.paths.recordings_dir.rglob("*") if p.suffix in (".part", ".tmp")]
    assert len(rig.alerts.of_kind(ALERT_DISK_FLOOR)) == 1
    rig.run(600)
    assert len(rig.alerts.of_kind(ALERT_DISK_FLOOR)) == 1  # still one while it stays stopped


def test_F4_AC5_while_stopped_opens_and_adds_are_refused_with_disk_low_and_exits_are_never_refused(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    assert [rig.recorder.refusal_reason(a) for a in ENTRIES + EXITS] == [None] * 4
    rig.disk.set(None, "3.0")
    rig.run(180)
    assert rig.recorder.recording is False
    assert [rig.recorder.refusal_reason(a) for a in ENTRIES] == [DISK_LOW, DISK_LOW]
    assert DISK_LOW == "disk_low"
    assert [rig.recorder.refusal_reason(a) for a in EXITS] == [None, None]


def test_F4_AC5_while_stopped_nothing_is_written_and_nothing_is_buffered_for_later(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    feed_books(rig)
    rig.run(120)
    rig.disk.set(None, "4.0")
    rig.run(180)
    stop = rig.clock.now_ms()
    rig.run(600)
    rig.disk.set(None, "50")
    rig.run(180)
    rig.recorder.shutdown()
    times = l2_times(rig)
    hole = [t for t in times if stop < t < stop + 600 * SECOND]
    assert hole == []


def test_F4_AC5_the_ledger_heartbeat_and_ledger_appends_continue_while_recording_is_stopped(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.disk.set(None, "4.0")
    rig.run(180)
    before = len(rig.ledger_of("component_heartbeat"))
    rig.run(60)
    assert len(rig.ledger_of("component_heartbeat")) >= before + 5
    rig.ledger.append("note", {"still": "writing"})
    assert rig.ledger.failed is False


def test_F4_AC5_the_stop_is_ledgered_as_disk_low_downtime_once_recording_resumes(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    feed_books(rig)
    rig.run(120)
    rig.disk.set(None, "4.0")
    t_drop = rig.clock.now_ms()
    rig.run(600)
    rig.disk.set(None, "50")
    t_up = rig.clock.now_ms()
    rig.run(180)
    (rec,) = [r for r in rig.ledger_of(KIND_DOWNTIME) if r.payload["kind"] == "disk_low"]
    assert t_drop < rec.payload["start_ms"] <= t_drop + 2 * MINUTE
    assert t_up < rec.payload["end_ms"] <= t_up + 2 * MINUTE
    assert rec.payload["wallets"] == []


# --- resume ------------------------------------------------------------------------------------------------------------------


def test_F4_AC5_recording_resumes_at_floor_plus_margin_and_not_a_hundredth_of_a_gb_earlier(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()  # floor 8, margin 2
    feed_books(rig)
    rig.disk.set(None, "3")
    rig.run(180)
    assert rig.recorder.recording is False
    rig.disk.set(None, "9.99")
    rig.run(300)
    assert rig.recorder.recording is False and rig.recorder.refusal_reason(ActionKind.OPEN) == DISK_LOW
    rig.disk.set(None, "10.00")
    rig.run(180)
    assert rig.recorder.recording is True and rig.recorder.refusal_reason(ActionKind.OPEN) is None


def test_F4_AC5_the_margin_follows_config(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(recording__disk_resume_margin_gb=5)
    rig.disk.set(None, "3")
    rig.run(180)
    rig.disk.set(None, "12.99")
    rig.run(180)
    assert rig.recorder.recording is False
    rig.disk.set(None, "13")
    rig.run(180)
    assert rig.recorder.recording is True


def test_F4_AC5_after_resume_the_stopped_interval_is_a_gap_and_new_records_land_in_a_new_file(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    feed_books(rig)
    rig.run(300)
    rig.disk.set(None, "4")
    rig.run(300)
    rig.disk.set(None, "50")
    rig.run(600)
    rig.recorder.shutdown()
    files = closed(rig)
    assert [f["reason"] for f in files if f["stream"] == STREAM_L2 and f["coin"] == "BTC"] == ["disk_floor", "shutdown"]
    assert len({f["path"] for f in files}) == len(files)
    stats = gap_stats(rig.store, DAY0 + 10 * SECOND, DAY0 + 1200 * SECOND, ("BTC",))["BTC"]
    assert Decimal("0.2") < stats.l2_gap_share < Decimal("0.5")


def test_F4_AC5_two_stops_give_two_alerts_and_two_downtime_intervals(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    for _ in range(2):
        rig.disk.set(None, "4")
        rig.run(180)
        rig.disk.set(None, "50")
        rig.run(180)
    assert len(rig.alerts.of_kind(ALERT_DISK_FLOOR)) == 2
    assert len([r for r in rig.ledger_of(KIND_DOWNTIME) if r.payload["kind"] == "disk_low"]) == 2


def test_F4_AC5_the_floor_follows_config(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(recording__disk_floor_free_gb=6)
    rig.disk.set(None, "6.00")
    rig.run(300)
    assert rig.recorder.recording is True
    rig.disk.set(None, "5.99")
    rig.run(180)
    assert rig.recorder.recording is False


def test_F4_AC5_a_floor_stop_on_any_one_of_the_three_volumes_stops_recording(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.disk.set(rig.paths.ledger_dir, "2")
    rig.run(180)
    assert rig.recorder.recording is False


def test_F4_AC5_a_day_end_while_stopped_still_closes_and_marks_the_day_complete(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(start_ms=DAY0 + DAY - 30 * MINUTE)
    feed_books(rig)
    rig.run(600)
    rig.disk.set(None, "4")
    rig.run(3600)
    assert [r.payload["day"] for r in rig.ledger_of("day_complete")] == ["2026-09-22"]
    assert HOUR == 3_600_000
