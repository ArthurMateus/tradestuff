"""F4.AC2: hourly leaderboard snapshots (compressed, fetch timestamp, sha256), retries, ``missing`` and the wallet registry.

Spec: 04-spec.md F4.AC2, D2 (every wallet ever seen stays), §3.3 ``recording.leaderboard_interval_min``.
The leaderboard endpoint is the only fake: a stub that returns fixture bytes or fails.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from copytrade.recorder.records import STREAM_LEADERBOARD, Record
from copytrade.recorder.registry import WalletRegistry, wallets_in_leaderboard
from copytrade.recorder.service import ALERT_LEADERBOARD_MISSING
from tests.recorder.helpers import DAY, DAY0, HOUR, MINUTE, SECOND, Rig, leaderboard_body

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "exchange" / "hl" / "leaderboard.json"
A, B, C = ("0x" + c * 40 for c in "abc")


def snaps(rig: Rig) -> list[Record]:
    return list(rig.store.scan(STREAM_LEADERBOARD, None, DAY0, DAY0 + 30 * DAY))


# --- fixture parsing ---------------------------------------------------------------------------------------------------


def test_F4_AC2_wallets_are_read_from_the_leaderboard_fixture_lower_cased_in_order() -> None:
    raw = FIXTURE.read_bytes()
    assert wallets_in_leaderboard(raw) == (
        "0x" + "1" * 40,
        "0x" + "2" * 40,
        "0xabcdef0123456789abcdef0123456789abcdef01",
        "0x" + "3" * 40,
        "0x" + "4" * 40,
    )


@pytest.mark.parametrize("bad", [b"", b"not json", b"[]", b'{"rows": []}', b'{"leaderboardRows": 5}', b"\xff\xfe"])
def test_F4_AC2_a_body_that_is_not_a_leaderboard_is_a_value_error(bad: bytes) -> None:
    with pytest.raises(ValueError):
        wallets_in_leaderboard(bad)


def test_F4_AC2_an_empty_leaderboard_has_no_wallets() -> None:
    assert wallets_in_leaderboard(b'{"leaderboardRows": []}') == ()


# --- the wallet registry -----------------------------------------------------------------------------------------------


def test_F4_AC2_the_registry_keeps_every_wallet_ever_added_across_restarts(tmp_path: Path) -> None:
    reg = WalletRegistry(tmp_path / "reg")
    assert reg.add([A, B]) == 2
    assert reg.add([B, C.upper().replace("0X", "0x")]) == 1  # B is known; C arrives in upper case and is lower-cased
    assert reg.wallets() == frozenset({A, B, C})
    again = WalletRegistry(tmp_path / "reg")
    assert again.wallets() == frozenset({A, B, C})


def test_F4_AC2_the_registry_ignores_things_that_are_not_wallet_addresses(tmp_path: Path) -> None:
    reg = WalletRegistry(tmp_path / "reg")
    assert reg.add(["", "0x123", "not an address", "0x" + "g" * 40, A + "00"]) == 0
    assert reg.wallets() == frozenset()


def test_F4_AC2_the_registry_has_no_way_to_forget_a_wallet(tmp_path: Path) -> None:
    reg = WalletRegistry(tmp_path / "reg")
    for name in ("remove", "delete", "discard", "clear", "pop", "prune", "forget", "drop"):
        assert not hasattr(reg, name)


# --- snapshots ----------------------------------------------------------------------------------------------------------


def test_F4_AC2_a_snapshot_stores_the_body_exactly_with_its_fetch_time_and_sha256(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    body = FIXTURE.read_bytes()
    rig.leaderboard.body = body
    rig.run(1)
    rig.recorder.shutdown()
    (snap,) = snaps(rig)
    assert snap.coin is None and snap.source == "rest"
    assert snap.data["status"] == "ok"
    assert snap.data["body"] == body.decode("utf-8")
    assert snap.data["sha256"] == hashlib.sha256(body).hexdigest()
    assert snap.receive_ts_ms == rig.leaderboard.calls[0]


def test_F4_AC2_snapshots_are_taken_every_interval_within_plus_or_minus_five_minutes(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()  # recording.leaderboard_interval_min = 60
    rig.run(6 * 3600)
    rig.recorder.shutdown()
    times = [s.receive_ts_ms for s in snaps(rig)]
    assert len(times) >= 6
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert all(55 * MINUTE <= g <= 65 * MINUTE for g in gaps), gaps


def test_F4_AC2_the_interval_follows_config_at_its_minimum(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(recording__leaderboard_interval_min=15)
    rig.run(2 * 3600)
    rig.recorder.shutdown()
    times = [s.receive_ts_ms for s in snaps(rig)]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert len(times) >= 7 and all(10 * MINUTE <= g <= 20 * MINUTE for g in gaps), gaps


def test_F4_AC2_a_large_leaderboard_is_stored_compressed_and_partitioned_by_day(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    wallets = ["0x%040x" % i for i in range(3000)]
    body = leaderboard_body(wallets)
    rig.leaderboard.body = body
    rig.run(1)
    rig.recorder.shutdown()
    closed = [r.payload for r in rig.ledger.records() if r.kind == "recording_file_closed" and r.payload["stream"] == STREAM_LEADERBOARD]
    (file,) = closed
    assert "2026-09-22" in file["path"] and file["coin"] is None
    assert file["byte_count"] < len(body) // 2


# --- failure: retries, missing, one alert -------------------------------------------------------------------------------


def test_F4_AC2_a_failed_fetch_is_retried_and_a_later_success_is_stored_without_a_missing_record(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    rig.leaderboard.fail_next = 2
    rig.run(HOUR // SECOND - 1)
    rig.recorder.shutdown()
    assert len(rig.leaderboard.calls) == 3
    assert rig.leaderboard.calls[-1] - rig.leaderboard.calls[0] < HOUR
    assert [s.data["status"] for s in snaps(rig)] == ["ok"]
    assert rig.alerts.of_kind(ALERT_LEADERBOARD_MISSING) == []


def test_F4_AC2_a_fetch_that_fails_every_time_is_retried_three_times_within_the_hour_then_recorded_missing_with_one_alert(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    rig.leaderboard.fail_always = True
    rig.run(HOUR // SECOND - 1)
    calls = rig.leaderboard.calls
    assert len(calls) == 4  # the first attempt and 3 retries
    assert calls[-1] - calls[0] < HOUR
    rig.recorder.shutdown()
    (snap,) = snaps(rig)
    assert snap.data["status"] == "missing" and "body" not in snap.data
    assert snap.receive_ts_ms - calls[0] <= HOUR
    assert len(rig.alerts.of_kind(ALERT_LEADERBOARD_MISSING)) == 1


def test_F4_AC2_after_a_missing_snapshot_the_next_hourly_snapshot_is_still_attempted_and_stored(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    rig.leaderboard.fail_always = True
    rig.run(HOUR // SECOND)
    rig.leaderboard.fail_always = False
    rig.run(HOUR // SECOND)
    rig.recorder.shutdown()
    assert [s.data["status"] for s in snaps(rig)] == ["missing", "ok"]


def test_F4_AC2_a_timeout_counts_as_a_failed_fetch_like_any_other_error(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.leaderboard.fail_next = 1  # the stub raises TimeoutError for this one
    rig.run(600)
    rig.recorder.shutdown()
    assert [s.data["status"] for s in snaps(rig)] == ["ok"]
    assert len(rig.leaderboard.calls) == 2


# --- wallet registry fed by snapshots -------------------------------------------------------------------------------------


def test_F4_AC2_wallets_seen_in_any_snapshot_stay_in_the_registry_after_they_leave_the_leaderboard(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    rig.leaderboard.body = leaderboard_body([A, B])
    rig.run(1)
    assert rig.registry.wallets() == frozenset({A, B})
    rig.leaderboard.body = leaderboard_body([B, C])
    rig.run(HOUR // SECOND)
    assert rig.registry.wallets() == frozenset({A, B, C})
    assert WalletRegistry(rig.paths.recordings_dir.parent / "registry").wallets() == frozenset({A, B, C})


def test_F4_AC2_a_body_that_is_not_json_does_not_crash_the_recorder_or_touch_the_registry(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.leaderboard.body = leaderboard_body([A])
    rig.run(1)
    rig.leaderboard.invalid_body = b"<html>502 Bad Gateway</html>"
    rig.run(HOUR // SECOND + 10)
    assert rig.registry.wallets() == frozenset({A})


def test_F4_AC2_the_store_has_no_way_to_delete_or_prune_a_snapshot(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    for name in ("delete", "remove", "prune", "unlink", "purge"):
        assert not hasattr(rig.store, name)


def test_F4_AC2_a_recorded_snapshot_parses_as_the_json_that_was_fetched(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.leaderboard.body = FIXTURE.read_bytes()
    rig.run(1)
    rig.recorder.shutdown()
    (snap,) = snaps(rig)
    assert json.loads(snap.data["body"]) == json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert SECOND == 1000
