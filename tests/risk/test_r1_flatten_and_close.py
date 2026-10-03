# mypy: disable-error-code="attr-defined"
"""F10 review round 1: B6 (``/flatten`` is complete and pauses first) and B7 (a CLOSE is netted against the fills of
its own ``submit``).

Pinned:

* B6: ``flatten`` (1) sets the persisted manual pause FIRST, before any order; (2) closes every share of every broker
  position (``PaperBroker.positions()`` with ``PositionView.share_qtys``), whether or not the share book lists it, and
  works when the share book cannot be read; (3) returns the same sequence of ``Outcome`` as before but as a tuple
  subclass (``FlattenReport``) that also carries ``in_flight``: the ``PendingEntry`` records (``pending_entries()``)
  still in flight after the closes were sent. An entry in flight when flatten ran is blocked by the pause; once it
  fills, running ``flatten`` again under a new ``run_id`` closes it (the supervisor, F21, re-runs it while the report
  shows entries in flight).
* B7: for ``close=True`` the gate nets the request's quantity against the fills of THIS submit's ``advance_to``
  (``Outcome.broker_events``) for that share: entry fills add to it, exit fills take from it, and both the book check
  and the broker order use the netted quantity. A request with no such fills is unchanged (round-0 ``exceeds_share``
  stays).
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.ledger.errors import LedgerWriteError
from copytrade.paper.types import OrderIntent
from copytrade.risk.gate import STATE_FILENAME
from copytrade.risk.state import load_state
from tests.risk.conftest import NewRisk
from tests.risk.helpers import T0, RiskEnv
from tests.risk.r1_helpers import failing_ledger_writes, forget_share, mk, sent


def _intents(r: RiskEnv) -> dict[str, OrderIntent]:
    return {i.share_id: i for i, _ in r.authority.issued if isinstance(i, OrderIntent)}


# ---- B6 --------------------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_B6_flatten_sets_the_persisted_pause_before_it_sends_anything(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    r.book("SOL", "100")
    with failing_ledger_writes(b"paper_order"), pytest.raises(LedgerWriteError):
        r.gate.flatten(run_id="run1")  # the first close cannot be written
    assert r.gate.paused is True
    assert load_state(r.state_dir / STATE_FILENAME).manual_pause is True


@pytest.mark.integration
def test_F10_B6_flatten_leaves_the_gate_paused_and_entries_refused(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    r.book("SOL", "100")
    assert r.gate.paused is False
    r.gate.flatten(run_id="run1")
    assert r.gate.paused is True
    assert r.gate.check(r.open_req(coin="ETH")).reason == "paused"
    assert load_state(r.state_dir / STATE_FILENAME).manual_pause is True


@pytest.mark.integration
def test_F10_B6_flatten_with_nothing_open_still_pauses(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    assert list(r.gate.flatten(run_id="run1")) == []
    assert r.gate.paused is True


@pytest.mark.integration
def test_F10_B6_flatten_closes_every_share_of_every_broker_position_even_ones_the_book_lacks(
    new_risk: NewRisk,
) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="LX", qty="1.0", entry="100", stop="98.5", share="H1")
    r.seed("SOL", leader="LX", qty="0.5", entry="100", stop="98.5", share="H2")
    r.seed("BTC", leader="LY", is_long=False, qty="0.2", entry="100", stop="101.5", share="H3")
    r.seed("ETH", leader="L1", qty="0.3", entry="100", stop="98.5", share="E1")
    for hidden in ("H1", "H2", "H3"):
        forget_share(r, hidden)  # only E1 is in the book
    for coin in ("SOL", "BTC", "ETH"):
        r.book(coin, "100")
    outs = r.gate.flatten(run_id="run1")
    assert len(outs) == 4
    assert all(o.decision.approved and o.decision.action is ActionKind.CLOSE for o in outs)
    assert all(o.result is not None and o.result.accepted for o in outs)
    sent_orders = _intents(r)
    assert {k: (v.side, v.qty, v.exit_reason) for k, v in sent_orders.items()} == {
        "H1": ("sell", D("1.0"), "flatten"),
        "H2": ("sell", D("0.5"), "flatten"),
        "H3": ("buy", D("0.2"), "flatten"),
        "E1": ("sell", D("0.3"), "flatten"),
    }
    r.fill()
    assert r.paper.broker.positions() == ()
    assert len(r.paper.trades()) == 4


@pytest.mark.integration
def test_F10_B6_flatten_works_when_the_share_book_cannot_be_read(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    r.book("SOL", "100")
    r.shares.raises = True
    outs = r.gate.flatten(run_id="run1")
    assert len(outs) == 1 and outs[0].result is not None and outs[0].result.accepted
    assert r.gate.paused is True


@pytest.mark.integration
def test_F10_B6_running_flatten_twice_in_one_run_still_sends_nothing_twice(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="H1")
    forget_share(r, "H1")
    r.book("SOL", "100")
    r.gate.flatten(run_id="run1")
    again = r.gate.flatten(run_id="run1")
    assert all(o.result is None or not o.result.accepted for o in again)
    assert sent(r) == 1


@pytest.mark.integration
def test_F10_B6_flatten_reports_the_entries_still_in_flight(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.book("SOL", "100")
    first = r.gate.submit(r.open_req())
    assert first.result is not None and first.result.accepted
    report = r.gate.flatten(run_id="run1")
    in_flight = getattr(report, "in_flight")  # noqa: B009 - the new attribute of the FlattenReport tuple
    assert [(p.coin, p.client_order_id, p.qty) for p in in_flight] == [
        ("SOL", first.decision.client_order_id, first.decision.qty)
    ]
    assert len(report) == 0  # nothing is held yet, so there is nothing to close yet
    assert r.gate.paused is True
    assert r.gate.check(r.open_req(coin="ETH", share_id="S2", signal_id="x", tids=(9,))).reason == "paused"


@pytest.mark.integration
def test_F10_B6_an_entry_in_flight_when_flatten_ran_is_closed_by_the_next_flatten_once_it_fills(
    new_risk: NewRisk,
) -> None:
    r = mk(new_risk)
    r.book("SOL", "100")
    first = r.gate.submit(r.open_req())
    assert first.result is not None and first.result.accepted
    r.gate.flatten(run_id="run1")
    r.fill()  # the pending entry fills; F12 has not listed the share
    r.at(T0 + 1000)
    r.book("SOL", "100")
    position = r.paper.broker.position("SOL")
    assert position is not None
    second = r.gate.flatten(run_id="run2")
    assert len(second) == 1 and second[0].decision.approved
    assert second[0].result is not None and second[0].result.accepted
    issued = _intents(r)["S10"]
    assert (issued.action, issued.side, issued.qty, issued.exit_reason) == (
        ActionKind.CLOSE, "sell", position.qty, "flatten",
    )
    assert getattr(second, "in_flight") == ()  # noqa: B009
    r.paper.advance(T0 + 2500)
    assert r.paper.broker.position("SOL") is None
    assert r.gate.check(r.open_req(share_id="S11", signal_id="y", tids=(10,))).reason == "paused"
    assert list(r.gate.flatten(run_id="run3")) == []


# ---- B7 --------------------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_B7_a_close_built_before_an_add_fills_closes_the_whole_share(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", leverage=5, share="S10")
    r.book("SOL", "100")  # the ADD fills at T0 + 1000
    add = r.gate.submit(r.add_req(share_id="S10"))
    assert add.result is not None and add.result.accepted and add.decision.qty == D("0.50")
    r.at(T0 + 1000)
    r.book("SOL", "100")  # the CLOSE fills at T0 + 2000
    out = r.gate.submit(r.exit_req(share_id="S10", qty="1.0", close=True))  # F12 built it from the pre-add book
    assert [e.kind for e in out.broker_events] == ["fill"]  # the ADD
    assert out.decision.approved, out.decision.reason
    assert out.decision.qty == D("1.50")
    assert out.result is not None and out.result.accepted, out.result
    last = r.authority.issued[-1][0]
    assert isinstance(last, OrderIntent) and (last.action, last.qty) == (ActionKind.CLOSE, D("1.50"))
    r.paper.advance(T0 + 2500)
    assert r.paper.broker.position("SOL") is None
    assert r.paper.records("paper_reject") == []
    assert len(r.paper.trades()) == 1  # the share closed once, in one trade


@pytest.mark.integration
def test_F10_B7_a_close_built_before_a_take_profit_partial_fill_closes_what_is_left(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", leverage=5, share="S10")
    tp = r.gate.place_stop(r.stop_req(kind="tp", share_id="S10", qty=Qty("0.5"), trigger_px=Price("103")))
    assert tp.result is not None and tp.result.accepted
    r.book("SOL", "103")  # the take-profit fills at T0 + 1000
    r.paper.mark("SOL", "103", T0)  # the mark reaches the trigger: the exit is now pending
    r.at(T0 + 1000)
    r.book("SOL", "103")  # the CLOSE fills at T0 + 2000
    out = r.gate.submit(r.exit_req(share_id="S10", qty="1.0", close=True))  # built before the partial fill
    assert [e.kind for e in out.broker_events] == ["fill"]  # the take-profit
    assert out.decision.approved, out.decision.reason
    assert out.decision.qty == D("0.50")
    assert out.result is not None and out.result.accepted, out.result  # never ``exceeds_position``
    r.paper.advance(T0 + 2500)
    assert r.paper.broker.position("SOL") is None
    assert r.paper.records("paper_reject") == []


@pytest.mark.unit
def test_F10_B7_a_close_with_no_fills_in_its_submit_is_unchanged(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S10")
    r.book("SOL", "100")
    out = r.gate.submit(r.exit_req(share_id="S10", qty="1.0", close=True))
    assert out.broker_events == ()
    assert out.decision.approved and out.decision.qty == D("1.0")


@pytest.mark.unit
def test_F10_B7_a_close_above_the_share_with_no_fills_is_still_refused_exceeds_share(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S10")
    r.book("SOL", "100")
    out = r.gate.submit(r.exit_req(share_id="S10", qty="1.01", close=True))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "exceeds_share", None)


@pytest.mark.integration
def test_F10_B7_fills_of_another_share_do_not_change_a_close(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", leverage=5, share="S10")
    r.seed("ETH", leader="L2", qty="1.0", entry="100", stop="98.5", leverage=5, share="E10")
    r.book("ETH", "100")
    add = r.gate.submit(r.add_req(coin="ETH", leader="L2", share_id="E10", trade_id="TE"))
    assert add.result is not None and add.result.accepted
    r.at(T0 + 1000)
    r.book("SOL", "100")
    out = r.gate.submit(r.exit_req(share_id="S10", qty="1.0", close=True))
    assert [e.kind for e in out.broker_events] == ["fill"]  # the ETH add, not this share
    assert out.decision.approved and out.decision.qty == D("1.0")
