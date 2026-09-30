"""F6.AC7 [unit]: cadence.

A cycle starts every ``scoring.interval_min`` +/- 2 min. A cycle that has not finished within
``select.max_cycle_duration_min`` keeps the previous followed set and is logged ``cycle_overrun``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from copytrade.selection.models import KIND_CYCLE_OVERRUN, STATUS_APPLIED, STATUS_OVERRUN
from tests.scoring.wallets import healthy
from tests.selection.helpers import (
    D,
    HEALTHY_OVERRIDES,
    HEALTHY_START_MS,
    HOUR,
    MINUTE,
    AdvancingStore,
    FakeInputs,
    Rig,
    established,
    healthy_wallets,
    leaderboard_body,
    make_rig,
    w,
)

TOLERANCE = 2 * MINUTE


def test_F6_AC7_a_cycle_is_due_before_the_first_one_and_then_one_interval_later(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, inputs=FakeInputs(healthy_wallets(3)), start_ms=HEALTHY_START_MS, **HEALTHY_OVERRIDES)
    try:
        assert rig.manager.next_due_ms is None and rig.manager.due() is True
        start = rig.clock.now_ms()
        rig.manager.run_cycle(p95_latency_s=D(3))
        assert abs(rig.manager.next_due_ms - (start + 60 * MINUTE)) <= TOLERANCE
        rig.advance(57 * MINUTE)
        assert rig.manager.due() is False
        rig.advance(6 * MINUTE)  # 63 minutes after the start
        assert rig.manager.due() is True
    finally:
        rig.ledger.close()


def test_F6_AC7_the_interval_follows_scoring_interval_min(tmp_path: Path) -> None:
    rig = make_rig(
        tmp_path, inputs=FakeInputs(healthy_wallets(3)), start_ms=HEALTHY_START_MS,
        scoring__interval_min=15, select__max_cycle_duration_min=10, **HEALTHY_OVERRIDES,
    )
    try:
        start = rig.clock.now_ms()
        rig.manager.run_cycle(p95_latency_s=D(3))
        assert abs(rig.manager.next_due_ms - (start + 15 * MINUTE)) <= TOLERANCE
    finally:
        rig.ledger.close()


def test_F6_AC7_starts_stay_one_interval_apart_even_when_each_cycle_takes_ten_minutes(tmp_path: Path) -> None:
    holder: dict[str, Rig] = {}
    store = AdvancingStore(lambda ms: holder["rig"].clock.advance(ms))
    store.next_ms = 10 * MINUTE
    rig = make_rig(
        tmp_path, inputs=FakeInputs(healthy_wallets(3)), store=store, start_ms=HEALTHY_START_MS, **HEALTHY_OVERRIDES
    )
    holder["rig"] = rig
    try:
        starts: list[int] = []
        end = HEALTHY_START_MS + 6 * HOUR
        while rig.clock.now_ms() < end:
            if rig.manager.due():
                starts.append(rig.clock.now_ms())
                assert rig.manager.run_cycle(p95_latency_s=D(3)).status == STATUS_APPLIED
            else:
                rig.advance(30_000)
        gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
        assert len(starts) >= 5
        assert all(abs(g - 60 * MINUTE) <= TOLERANCE for g in gaps), gaps
    finally:
        rig.ledger.close()


# --- overrun ----------------------------------------------------------------------------------------------------


def overrun_rig(tmp_path: Path, **kwargs: object) -> tuple[Rig, AdvancingStore]:
    holder: dict[str, Rig] = {}
    store = AdvancingStore(lambda ms: holder["rig"].clock.advance(ms))
    provider_extra = [healthy(w(0))]
    rig = established(tmp_path, n=8, extra=provider_extra, store=store, **kwargs)
    holder["rig"] = rig
    rig.board.outcome = leaderboard_body(1000, first=[w(i) for i in range(0, 9)])
    return rig, store


def test_F6_AC7_a_cycle_that_overruns_keeps_the_previous_followed_set_and_is_logged(tmp_path: Path) -> None:
    rig, store = overrun_rig(tmp_path)
    try:
        before = rig.manager.followed
        assert rig.manager.run_cycle(p95_latency_s=D(3)).status == STATUS_APPLIED  # w0 has a streak of 1 now
        log_before = list(rig.spy.log)
        store.next_ms = 46 * MINUTE
        started = rig.clock.now_ms()
        report = rig.manager.run_cycle(p95_latency_s=D(3))  # w0 would have joined in this cycle
        assert report.status == STATUS_OVERRUN and report.decisions == ()
        assert rig.manager.followed == before and w(0) not in rig.manager.followed
        assert rig.spy.log == log_before
        logged = rig.records(KIND_CYCLE_OVERRUN)
        assert len(logged) == 1
        assert (logged[0]["started_ms"], logged[0]["finished_ms"]) == (started, started + 46 * MINUTE)
        assert rig.records("select_cycle")[-1]["status"] == STATUS_OVERRUN
    finally:
        rig.ledger.close()


def test_F6_AC7_the_overrun_boundary_exactly_45_minutes_is_fine_one_ms_more_is_an_overrun(tmp_path: Path) -> None:
    rig, store = overrun_rig(tmp_path)
    try:
        rig.manager.run_cycle(p95_latency_s=D(3))  # streak 1 for w0
        store.next_ms = 45 * MINUTE
        assert rig.manager.run_cycle(p95_latency_s=D(3)).status == STATUS_APPLIED
        assert w(0) in rig.manager.followed
        assert rig.records(KIND_CYCLE_OVERRUN) == []
    finally:
        rig.ledger.close()
    (tmp_path / "again").mkdir()
    rig2, store2 = overrun_rig(tmp_path / "again")
    try:
        rig2.manager.run_cycle(p95_latency_s=D(3))
        store2.next_ms = 45 * MINUTE + 1
        assert rig2.manager.run_cycle(p95_latency_s=D(3)).status == STATUS_OVERRUN
        assert w(0) not in rig2.manager.followed
    finally:
        rig2.ledger.close()


@pytest.mark.parametrize("limit,ok_ms,over_ms", [(10, 10 * MINUTE, 10 * MINUTE + 1), (30, 30 * MINUTE, 30 * MINUTE + 1)])
def test_F6_AC7_the_overrun_limit_is_read_from_config(tmp_path: Path, limit: int, ok_ms: int, over_ms: int) -> None:
    rig, store = overrun_rig(tmp_path, select__max_cycle_duration_min=limit)
    try:
        store.next_ms = ok_ms
        assert rig.manager.run_cycle(p95_latency_s=D(3)).status == STATUS_APPLIED
        store.next_ms = over_ms
        assert rig.manager.run_cycle(p95_latency_s=D(3)).status == STATUS_OVERRUN
    finally:
        rig.ledger.close()


def test_F6_AC7_an_overrun_does_not_move_the_next_start_off_the_schedule(tmp_path: Path) -> None:
    rig, store = overrun_rig(tmp_path)
    try:
        store.next_ms = 46 * MINUTE
        started = rig.clock.now_ms()
        rig.manager.run_cycle(p95_latency_s=D(3))
        assert abs(rig.manager.next_due_ms - (started + 60 * MINUTE)) <= TOLERANCE
    finally:
        rig.ledger.close()
