"""Round 2: fail-closed guards that survived hand mutation in the first review.

1. F7.AC4: ``core`` missing from ``markets.allowed_dexes`` makes a plain coin ``out_of_scope``.
2. F7.AC1: a ``side`` other than ``B`` or ``A`` is ``unparseable`` (never silently a sell).
3. F7.AC5 / invariant A2: a stale or over-uncertain clock-offset estimate gives ``age_ms`` None, flag
   ``clock_unsynced``, opens and adds refused, exits never.

The shipped config loader fixes ``markets.allowed_dexes`` to ``["core"]``, so the detector is given a plain mapping
with the key changed (its constructor takes a ``Mapping``); everything else is the real collaborators.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from copytrade.core.clock import ClockSync
from copytrade.core.domain import ActionKind
from copytrade.hl.models import Fill
from copytrade.ledger.store import Ledger
from copytrade.signals.classify import UnparseableFillError, classify_fill
from copytrade.signals.detector import SignalDetector
from copytrade.signals.models import FLAG_CLOCK_UNSYNCED, OUT_OF_SCOPE, UNPARSEABLE
from tests.signals.helpers import (
    T0,
    WALLET_A,
    FakeClock,
    FakeOffsetSource,
    RecordingAlerts,
    RecordingSignals,
    Rig,
    make_config,
    make_rig,
    mkfill,
    state,
)

pytestmark = pytest.mark.unit


def _rig_with_dexes(directory: Path, dexes: list[str]) -> Rig:
    real = make_config()
    config = {
        "markets.allowed_dexes": dexes,
        "clock.max_offset_uncertainty_ms": real["clock.max_offset_uncertainty_ms"],
    }
    clock = FakeClock(T0)
    offset = FakeOffsetSource()
    alerts = RecordingAlerts()
    sync = ClockSync.from_config(real, clock=clock, source=offset, alerts=alerts)
    sync.tick()
    ledger = Ledger.open(directory / "ledger", clock=clock)
    sink = RecordingSignals(ledger)
    detector = SignalDetector(config=config, clock=clock, sync=sync, ledger=ledger, sink=sink, alerts=alerts)
    detector.begin_follow(WALLET_A, state(), T0)
    return Rig(real, clock, offset, sync, ledger, sink, alerts, detector, directory)


# --- 1. scope: core not allowed ---------------------------------------------------------------------------------


def test_F7_AC4_a_plain_coin_is_out_of_scope_when_core_is_not_an_allowed_dex(tmp_path: Path) -> None:
    rig = _rig_with_dexes(tmp_path, ["xyz"])
    try:
        got = rig.feed([mkfill(1, coin="BTC", dir="Buy")])  # unknown dir: scope must win over dir
        assert [(s.outcome, s.action, s.leg) for s in got] == [(OUT_OF_SCOPE, None, 0)]
        assert rig.alerts.of_kind("unparseable_fill") == []  # out of scope is not a parse problem
        assert len(rig.ledger_signals()) == 1 and rig.ledger_signals()[0]["outcome"] == OUT_OF_SCOPE
        assert rig.feed([mkfill(1, coin="BTC", dir="Buy")]) == []  # deduplicated
        assert len(rig.ledger_signals()) == 1
    finally:
        rig.ledger.close()


def test_F7_AC4_a_flip_on_a_plain_coin_is_one_out_of_scope_signal_when_core_is_not_allowed(tmp_path: Path) -> None:
    rig = _rig_with_dexes(tmp_path, [])
    try:
        got = rig.feed([mkfill(1, coin="ETH", side="A", sz="3", start="1")])
        assert [s.outcome for s in got] == [OUT_OF_SCOPE]
    finally:
        rig.ledger.close()


def test_F7_AC4_a_plain_coin_stays_in_scope_when_core_is_allowed(tmp_path: Path) -> None:
    rig = _rig_with_dexes(tmp_path, ["core"])
    try:
        got = rig.feed([mkfill(1, coin="BTC")])
        assert [(s.outcome, s.action) for s in got] == [(None, ActionKind.OPEN)]
    finally:
        rig.ledger.close()


# --- 2. unknown side --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["X", "b", "a", "", "BUY", "SELL", " B", "B ", "Б"])
def test_F7_AC1_classify_fill_rejects_a_side_that_is_neither_B_nor_A(side: str) -> None:
    with pytest.raises(UnparseableFillError):
        classify_fill(mkfill(1, side=side, dir="Open Long"))


@pytest.mark.parametrize("side", ["X", "b", "", "SELL"])
def test_F7_AC1_an_unknown_side_is_unparseable_with_an_alert_never_a_sell(tmp_path: Path, side: str) -> None:
    rig = make_rig(tmp_path)
    try:
        fill = mkfill(1, side=side, sz="1", start="0", dir="Open Long")  # a known dir, so only the side is wrong
        got = rig.feed([fill])
        assert [(s.outcome, s.action, s.is_long, s.post_position) for s in got] == [(UNPARSEABLE, None, None, None)]
        assert len(rig.alerts.of_kind("unparseable_fill")) == 1
        assert len(rig.ledger_signals()) == 1
        assert rig.feed([fill]) == []  # deduplicated
        assert len(rig.ledger_signals()) == 1 and len(rig.alerts.of_kind("unparseable_fill")) == 1
    finally:
        rig.ledger.close()


# --- 3. stale or over-uncertain clock estimate ------------------------------------------------------------------


def _entry_exit_fills() -> list[Fill]:
    return [mkfill(1), mkfill(2, side="A", sz="1", start="1")]  # an open, then a close


def _assert_unsynced(rig: Rig) -> None:
    got = rig.feed(_entry_exit_fills())
    assert [s.age_ms for s in got] == [None, None]
    assert all(FLAG_CLOCK_UNSYNCED in s.flags for s in got)
    assert [s.refusal_reason() for s in got] == ["clock_unsynced", None]
    assert rig.ledger_signals()[0]["age_ms"] is None


def _assert_synced(rig: Rig) -> None:
    (opened,) = rig.feed([mkfill(1, time_ms=T0 - 700)])
    assert opened.age_ms is not None and FLAG_CLOCK_UNSYNCED not in opened.flags
    assert opened.refusal_reason() is None


def test_F7_AC5_a_stale_offset_estimate_gives_no_age_and_refuses_entries(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)  # one estimate taken at T0
    try:
        limit_ms = rig.sync.max_estimate_age_s * 1000
        rig.clock.advance(limit_ms + 1)  # no tick since: the estimate is one ms too old
        _assert_unsynced(rig)
    finally:
        rig.ledger.close()


def test_F7_AC5_an_offset_estimate_exactly_at_the_max_age_is_still_trusted(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    try:
        rig.clock.advance(rig.sync.max_estimate_age_s * 1000)
        assert rig.sync.refusal_reason(ActionKind.OPEN) is None  # ClockSync's own boundary
        (s,) = rig.feed([mkfill(1, time_ms=rig.clock.now_ms() - 700)])
        assert s.age_ms == 700 and s.refusal_reason() is None
    finally:
        rig.ledger.close()


def test_F7_AC5_an_estimate_one_ms_under_the_max_age_is_trusted(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    try:
        rig.clock.advance(rig.sync.max_estimate_age_s * 1000 - 1)
        _assert_synced(rig)
    finally:
        rig.ledger.close()


def test_F7_AC5_a_stale_estimate_follows_the_configured_max_age(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, clock__max_estimate_age_s=600)
    try:
        assert rig.sync.max_estimate_age_s == 600
        rig.clock.advance(600_001)
        _assert_unsynced(rig)
    finally:
        rig.ledger.close()


def test_F7_AC5_an_offset_uncertainty_over_the_max_gives_no_age_and_refuses_entries(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, uncertainty_ms=101)  # clock.max_offset_uncertainty_ms = 100
    try:
        _assert_unsynced(rig)
    finally:
        rig.ledger.close()


def test_F7_AC5_an_offset_uncertainty_exactly_at_the_max_is_trusted(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, uncertainty_ms=100)
    try:
        _assert_synced(rig)
    finally:
        rig.ledger.close()


def test_F7_AC5_the_uncertainty_limit_follows_config(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, clock__max_offset_uncertainty_ms=30, uncertainty_ms=31)
    try:
        _assert_unsynced(rig)
    finally:
        rig.ledger.close()


def test_F7_AC5_an_add_is_refused_as_clock_unsynced_while_the_estimate_is_stale(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    try:
        rig.clock.advance(rig.sync.max_estimate_age_s * 1000 + 1)
        (s,) = rig.feed([mkfill(1, side="B", sz="1", start="1")])
        assert s.action is ActionKind.ADD and s.age_ms is None
        assert s.refusal_reason() == "clock_unsynced"
    finally:
        rig.ledger.close()


def test_F7_AC5_a_fresh_estimate_restores_the_age_after_a_stale_spell(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    try:
        rig.clock.advance(rig.sync.max_estimate_age_s * 1000 + 1)
        (stale,) = rig.feed([mkfill(1)])
        assert stale.age_ms is None
        rig.sync.tick()  # a new estimate is taken
        (fresh,) = rig.feed([mkfill(2, time_ms=rig.clock.now_ms() - 500)])
        assert fresh.age_ms == 500 and fresh.refusal_reason() is None
    finally:
        rig.ledger.close()
