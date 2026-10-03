# mypy: disable-error-code="attr-defined"
"""F10 review round 2 (RISK-20): ``/flatten`` must not leave a position open while reporting nothing outstanding.

Pinned (docs/sdlc/copytrade-v1/05-test-plan-F10-r2.md):

* ``flatten`` loops in passes after the pause: each pass re-reads ``broker.positions()`` and submits a full close for
  every ``(coin, share_id)`` not yet covered by an ACCEPTED flatten close in this run; it stops after a pass in which
  no close was newly accepted, and after a fixed maximum number of passes. Every pass's outcomes are in the report (so
  every ``broker_events`` reaches the caller).
* ``FlattenReport.still_open``: tuple of ``(coin, share_id, qty)`` for every share in a fresh ``positions()`` that no
  accepted flatten close of this run covers (a close refused ``exceeds_position`` does not cover it). An accepted close
  that has not filled yet counts as covered. ``in_flight`` is unchanged: a fresh ``pending_entries()``.
"""

from __future__ import annotations

import threading
from decimal import Decimal as D

import pytest

from copytrade.core.money import Qty
from copytrade.paper.types import OrderIntent
from copytrade.risk.gate import STATE_FILENAME
from copytrade.risk.state import load_state
from copytrade.risk.types import FlattenReport
from tests.risk.conftest import NewRisk
from tests.risk.helpers import T0, RiskEnv
from tests.risk.r1_helpers import mk, sent


def _flatten_closes(r: RiskEnv) -> list[OrderIntent]:
    return [i for i, _ in r.authority.issued if isinstance(i, OrderIntent) and i.exit_reason == "flatten"]


def _accepted_closes(r: RiskEnv, report: FlattenReport) -> list[str]:
    """Share ids of the flatten closes the broker accepted in this report (sorted)."""
    by_order = {i.client_order_id: i.share_id for i in _flatten_closes(r)}
    return sorted(by_order[o.result.client_order_id] for o in report if o.result is not None and o.result.accepted)


def _still_open(report: FlattenReport) -> tuple[tuple[str, str, D], ...]:
    return tuple((c, s, D(q)) for c, s, q in report.still_open)  # type: ignore[attr-defined]


def _entry_due_with_another_position_held(r: RiskEnv) -> None:
    """ETH is held (booked); a SOL OPEN was accepted at T0 and fills at T0 + 1000 (due when flatten runs at +1500)."""
    r.seed("ETH", leader="L2", qty="1.0", entry="100", stop="98.5", share="E1")
    r.book("SOL", "100")
    first = r.gate.submit(r.open_req())
    assert first.result is not None and first.result.accepted
    r.at(T0 + 1500)
    r.book("SOL", "100")
    r.book("ETH", "100")


# ---- T20a ------------------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_RISK20a_an_entry_that_fills_during_the_flatten_is_closed_in_the_same_flatten(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _entry_due_with_another_position_held(r)
    report = r.gate.flatten(run_id="runF")
    closes = _flatten_closes(r)
    assert sorted(c.share_id for c in closes) == ["E1", "S10"]  # SOL is closed too, not only ETH
    assert _accepted_closes(r, report) == ["E1", "S10"]
    fills = [e for o in report for e in o.broker_events if e.kind == "fill"]
    assert len(fills) == 1  # the SOL entry's fill is in some outcome's broker_events (F12 will see it)
    assert report.in_flight == ()
    assert _still_open(report) == ()
    r.paper.advance(T0 + 4000)
    assert r.paper.broker.positions() == ()  # both really closed
    assert r.paper.records("paper_reject") == []


@pytest.mark.integration
def test_F10_RISK20a_the_fill_of_the_entry_closed_by_the_flatten_closes_the_whole_filled_quantity(
    new_risk: NewRisk,
) -> None:
    r = mk(new_risk)
    _entry_due_with_another_position_held(r)
    r.gate.flatten(run_id="runF")
    sol_close = next(c for c in _flatten_closes(r) if c.share_id == "S10")
    r.paper.advance(T0 + 4000)
    trades = [t for t in r.paper.trades() if t.coin == "SOL"]
    assert len(trades) == 1 and D(str(sol_close.qty)) > 0
    assert r.paper.broker.position("SOL") is None


@pytest.mark.integration
def test_F10_RISK20a_an_entry_not_yet_due_is_in_flight_and_not_still_open(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("ETH", leader="L2", qty="1.0", entry="100", stop="98.5", share="E1")
    r.book("ETH", "100")
    r.book("DOGE", "100")
    first = r.gate.submit(r.open_req(coin="DOGE", share_id="D1", trade_id="TD"))
    assert first.result is not None and first.result.accepted  # fills at T0 + 1000, flatten runs at T0
    report = r.gate.flatten(run_id="runF")
    assert _accepted_closes(r, report) == ["E1"]
    assert [(p.coin, p.share_id) for p in report.in_flight] == [("DOGE", "D1")]
    assert _still_open(report) == ()  # DOGE is not a position yet, ETH has its accepted close


@pytest.mark.integration
def test_F10_RISK20a_the_next_flatten_closes_the_entry_that_was_not_yet_due(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.book("DOGE", "100")
    first = r.gate.submit(r.open_req(coin="DOGE", share_id="D1", trade_id="TD"))
    assert first.result is not None and first.result.accepted
    report = r.gate.flatten(run_id="run1")
    assert len(report.in_flight) == 1 and _still_open(report) == ()
    r.at(T0 + 1500)
    r.book("DOGE", "100")
    second = r.gate.flatten(run_id="run2")
    assert _accepted_closes(r, second) == ["D1"]
    assert second.in_flight == () and _still_open(second) == ()


# ---- T20a2 -----------------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_RISK20a2_the_passes_send_one_close_per_share_and_produce_no_duplicate_outcomes(
    new_risk: NewRisk,
) -> None:
    r = mk(new_risk)
    _entry_due_with_another_position_held(r)
    report = r.gate.flatten(run_id="runF")
    assert [o.decision.reason for o in report if o.decision.reason == "duplicate_order"] == []
    assert len(_flatten_closes(r)) == 2 and sent(r) == 3  # the OPEN plus one close per share, nothing twice
    assert len(report) == 2
    assert all(o.result is not None and o.result.accepted for o in report)


@pytest.mark.integration
def test_F10_RISK20a2_a_rerun_in_the_same_run_id_sends_no_second_order_for_closed_shares(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _entry_due_with_another_position_held(r)
    r.gate.flatten(run_id="runF")
    before = sent(r)
    again = r.gate.flatten(run_id="runF")
    assert sent(r) == before
    assert not [o for o in again if o.result is not None and o.result.accepted]
    assert len(r.paper.records("paper_reject")) == 0


# ---- T20b ------------------------------------------------------------------------------------------------------------


def _share_with_a_pending_partial_reduce(r: RiskEnv) -> None:
    """S1 (1.0 SOL) with an accepted REDUCE of 0.4 that fills at T0 + 1000 (flatten runs at T0, before it)."""
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    r.book("SOL", "100")
    reduce = r.gate.submit(r.exit_req(share_id="S1", qty="0.4", close=False))
    assert reduce.result is not None and reduce.result.accepted, reduce


@pytest.mark.integration
def test_F10_RISK20b_a_close_refused_exceeds_position_is_reported_as_still_open(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _share_with_a_pending_partial_reduce(r)
    report = r.gate.flatten(run_id="run1")
    refused = [o for o in report if o.result is not None and not o.result.accepted]
    assert refused and all(o.result is not None and o.result.reason == "exceeds_position" for o in refused)
    assert _accepted_closes(r, report) == []
    assert _still_open(report) == (("SOL", "S1", D("1.0")),)
    assert report.in_flight == ()
    assert r.gate.paused is True


@pytest.mark.integration
def test_F10_RISK20b_a_new_run_after_the_reduce_fills_closes_the_residual(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _share_with_a_pending_partial_reduce(r)
    first = r.gate.flatten(run_id="run1")
    assert _still_open(first) == (("SOL", "S1", D("1.0")),)
    r.at(T0 + 1500)
    r.book("SOL", "100")
    r.paper.advance(T0 + 1500)  # the reduce filled at T0 + 1000: 0.60 stays open
    position = r.paper.broker.position("SOL")
    assert position is not None and position.qty == D("0.60")
    second = r.gate.flatten(run_id="run2")
    assert _accepted_closes(r, second) == ["S1"]
    last = _flatten_closes(r)[-1]
    assert (last.share_id, D(str(last.qty))) == ("S1", D("0.60"))
    assert _still_open(second) == () and second.in_flight == ()
    r.paper.advance(T0 + 4000)
    assert r.paper.broker.positions() == ()


@pytest.mark.integration
def test_F10_RISK20b_a_share_that_cannot_be_closed_never_makes_the_flatten_loop_forever(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _share_with_a_pending_partial_reduce(r)  # every close of S1 is refused while the reduce is pending
    box: list[FlattenReport] = []
    worker = threading.Thread(target=lambda: box.append(r.gate.flatten(run_id="run1")), daemon=True)
    worker.start()
    worker.join(timeout=30)
    assert not worker.is_alive(), "flatten is still looping on a share that never closes"
    assert len(box) == 1
    assert len(box[0]) <= 10  # a small fixed number of passes, not one outcome per spin
    assert not [o for o in box[0] if o.result is not None and o.result.accepted]
    assert _still_open(box[0]) == (("SOL", "S1", D("1.0")),)
    assert sent(r) <= 1 + 10  # the REDUCE plus a bounded number of refused closes


@pytest.mark.integration
def test_F10_RISK20b_only_the_uncovered_share_is_still_open_when_another_share_closes(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("ETH", leader="L2", qty="2.0", entry="100", stop="98.5", share="E1")  # seeds first: broker time moves on
    r.book("ETH", "100")
    _share_with_a_pending_partial_reduce(r)
    report = r.gate.flatten(run_id="run1")
    assert _accepted_closes(r, report) == ["E1"]
    assert _still_open(report) == (("SOL", "S1", D("1.0")),)
    assert Qty("1.0") == D("1.0")


# ---- T20c ------------------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_RISK20c_flatten_with_nothing_open_and_nothing_pending_returns_an_empty_report_and_pauses(
    new_risk: NewRisk,
) -> None:
    r = mk(new_risk)
    report = r.gate.flatten(run_id="run1")
    assert isinstance(report, FlattenReport)
    assert len(report) == 0 and report.in_flight == () and _still_open(report) == ()
    assert report.pause_saved is True
    assert r.gate.paused is True
    assert load_state(r.state_dir / STATE_FILENAME).manual_pause is True
    assert sent(r) == 0
