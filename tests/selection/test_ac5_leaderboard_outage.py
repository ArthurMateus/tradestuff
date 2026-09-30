"""F6.AC5 [unit]: leaderboard outage (failure case).

Triggers: an HTTP error, a timeout, a schema failure, or fewer than 1 000 rows. Effect: the current followed set is
kept, 0 wallets are added, and one alert is sent per outage. Followed wallets keep being re-scored from fills.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copytrade.selection.models import ALERT_LEADERBOARD_OUTAGE, STATUS_APPLIED, STATUS_LEADERBOARD_OUTAGE
from tests.selection.helpers import D, established, healthy_wallets, leaderboard_body, w
from tests.scoring.wallets import healthy

OUTAGES: dict[str, bytes | Exception] = {
    "http-error": OSError("HTTP 503 from the leaderboard host"),
    "timeout": TimeoutError("leaderboard timed out"),
    "not-json": b"<html>Bad gateway</html>",
    "schema-rows-not-a-list": json.dumps({"leaderboardRows": "x"}).encode(),
    "schema-no-rows-key": json.dumps({"rows": []}).encode(),
    "empty-body": b"",
    "999-rows": leaderboard_body(999),
    "no-rows": json.dumps({"leaderboardRows": []}).encode(),
}


@pytest.mark.parametrize("outage", list(OUTAGES), ids=list(OUTAGES))
def test_F6_AC5_an_outage_keeps_the_followed_set_adds_nobody_and_alerts_once(tmp_path: Path, outage: str) -> None:
    rig = established(tmp_path, extra=[healthy(w(0))])
    try:
        followed = rig.manager.followed
        calls_before = list(rig.spy.log)
        rig.board.outcome = OUTAGES[outage]
        for _ in range(3):
            report = rig.manager.run_cycle(p95_latency_s=D(3))
            assert report.status == STATUS_LEADERBOARD_OUTAGE
            assert report.decisions == () and set(report.followed) == followed
        assert rig.manager.followed == followed
        assert rig.spy.log == calls_before  # no subscribe, no unsubscribe, no begin_follow, no end_follow
        assert w(0) not in rig.manager.followed
        assert [a.kind for a in rig.alerts.sent].count(ALERT_LEADERBOARD_OUTAGE) == 1
        assert [r["status"] for r in rig.records("select_cycle")][-3:] == [STATUS_LEADERBOARD_OUTAGE] * 3
    finally:
        rig.ledger.close()


def test_F6_AC5_exactly_1000_rows_is_not_an_outage(tmp_path: Path) -> None:
    rig = established(tmp_path)
    try:
        rig.board.outcome = leaderboard_body(1000)
        assert rig.manager.run_cycle(p95_latency_s=D(3)).status == STATUS_APPLIED
        assert rig.alerts.sent == []
    finally:
        rig.ledger.close()


def test_F6_AC5_followed_wallets_keep_being_re_scored_from_fills_during_an_outage(tmp_path: Path) -> None:
    rig = established(tmp_path, extra=[healthy(w(0))])
    try:
        rig.inputs.refreshed.clear()
        rig.store.cycles.clear()
        rig.board.outcome = OSError("down")
        rig.manager.run_cycle(p95_latency_s=D(3))
        assert set(rig.inputs.refreshed) >= set(rig.manager.followed)
        assert len(rig.store.cycles) == 1
        scored = {s.address for s in rig.store.cycles[0].scores}
        assert scored == set(rig.manager.followed)  # the followed, and only them: no candidate list to score
    finally:
        rig.ledger.close()


def test_F6_AC5_a_new_outage_after_recovery_alerts_again_and_recovery_resumes_normal_cycles(tmp_path: Path) -> None:
    rig = established(tmp_path, extra=[healthy(w(0))])
    try:
        good = leaderboard_body(1000, first=[w(0), *(w(i) for i in range(1, 9))])
        rig.board.outcome = OSError("down")
        rig.manager.run_cycle(p95_latency_s=D(3))
        rig.board.outcome = good
        assert rig.manager.run_cycle(p95_latency_s=D(3)).status == STATUS_APPLIED
        rig.board.outcome = TimeoutError()
        rig.manager.run_cycle(p95_latency_s=D(3))
        rig.manager.run_cycle(p95_latency_s=D(3))
        assert [a.kind for a in rig.alerts.sent].count(ALERT_LEADERBOARD_OUTAGE) == 2
        rig.board.outcome = good
        for _ in range(2):
            rig.manager.run_cycle(p95_latency_s=D(3))
        assert w(0) in rig.manager.followed  # normal selection is back: the candidate joined after confirming
    finally:
        rig.ledger.close()


def test_F6_AC5_an_outage_before_anything_is_followed_follows_nobody(tmp_path: Path) -> None:
    from tests.selection.helpers import HEALTHY_OVERRIDES, HEALTHY_START_MS, FakeInputs, make_rig

    rig = make_rig(tmp_path, inputs=FakeInputs(healthy_wallets(8)), start_ms=HEALTHY_START_MS, **HEALTHY_OVERRIDES)
    try:
        rig.board.outcome = OSError("down")
        for _ in range(3):
            assert rig.manager.run_cycle(p95_latency_s=D(3)).status == STATUS_LEADERBOARD_OUTAGE
        assert rig.manager.followed == frozenset() and rig.spy.log == []
    finally:
        rig.ledger.close()
