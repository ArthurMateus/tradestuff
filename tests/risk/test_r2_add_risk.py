# mypy: disable-error-code="attr-defined"
"""F10 review round 2 (RISK-21): an ADD that filled in the ``advance_to`` of the very submit that decides the next entry
still counts in every risk cap, until the share book carries it.

Pinned (docs/sdlc/copytrade-v1/05-test-plan-F10-r2.md):

* For an ADD the gate keeps its record after the order leaves ``pending_entries()`` while the broker still holds the
  share AND the broker's quantity for that ``(coin, share_id)`` is greater than the share book's quantity for it. The
  record is one more exposure (same coin, share id and leader, ``open_risk_usd`` = the risk approved for the add) in the
  share, symbol, leader, total and BTC-bucket sums; it never enters ``unbooked_share_ids`` (``position_mismatch`` is
  unchanged). It is dropped when the book's quantity is at least the broker's, or the share is no longer held (a leak can
  only overcount).
* An ADD's ``share_used_usd`` is the counted risk of every exposure with that coin and share id: the book's share, a
  filled-add record and a pending add.
Numbers (equity 300, fixture caps): share 3.0, symbol 4.5, leader 4.5, total 15.0, bucket 9.0.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from copytrade.core.money import Price, Qty
from copytrade.risk.types import Decision, ShareExposure
from tests.risk.conftest import NewRisk
from tests.risk.helpers import T0, RiskEnv, uncorrelated_returns, wide_returns
from tests.risk.r1_helpers import mk

SHARE_CAP = D("3.0")
TOTAL_CAP = D("15.0")
TOL = D("0.01")


def _env(new_risk: NewRisk, **overrides: object) -> RiskEnv:
    returns = {"BTC": wide_returns()}
    for coin in ("ETH", "XRP", "DOGE", "LTC"):
        returns[coin] = uncorrelated_returns()  # outside the BTC bucket; SOL has no candles and counts as inside
    overrides.setdefault("risk__max_position_notional_equity_mult", D("3.0"))
    return mk(new_risk, returns=returns, **overrides)


def _share_with_a_pending_add(r: RiskEnv) -> Decision:
    """Share S10 on SOL: 0.3 booked at risk 0.3 (stop 99). ADD1 is sized by the share cap to risk 2.7 and sent at T0;
    it fills at T0 + 1000. Afterwards the exchange clock is at T0 + 1000 with a book, the share book still says 0.3."""
    r.seed("SOL", leader="L1", qty="0.3", entry="100", stop="99", leverage=5, share="S10")
    r.book("SOL", "100")
    add1 = r.gate.submit(
        r.add_req(share_id="S10", stop_px="99", current_stop_px="99", leader_add_size="10", leader_pre_add_position="1")
    )
    assert add1.result is not None and add1.result.accepted, add1
    assert add1.decision.initial_risk_usd is not None
    assert abs(add1.decision.initial_risk_usd - D("2.7")) <= TOL, add1.decision.initial_risk_usd
    r.at(T0 + 1000)
    r.book("SOL", "100")
    return add1.decision


def _add2(r: RiskEnv) -> object:
    return r.gate.submit(
        r.add_req(
            share_id="S10",
            stop_px="99",
            current_stop_px="99",
            leader_add_size="10",
            leader_pre_add_position="1",
            signal_id="sig2b",
            tids=(103,),
        )
    )


def _risk_of(d: Decision) -> D:
    return D(0) if not d.approved or d.initial_risk_usd is None else d.initial_risk_usd


# ---- T21a ------------------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_RISK21a_a_second_add_decided_when_the_first_fills_sees_the_first_adds_risk(new_risk: NewRisk) -> None:
    r = _env(new_risk)
    add1 = _share_with_a_pending_add(r)
    add2 = _add2(r)
    assert [e.kind for e in add2.broker_events] == ["fill"]  # ADD1 filled in this submit's own advance_to
    assert add2.decision.approved is False or add2.decision.qty == 0, add2.decision
    assert D("0.3") + _risk_of(add1) + _risk_of(add2.decision) <= SHARE_CAP + TOL


@pytest.mark.integration
def test_F10_RISK21a_the_share_never_exceeds_its_cap_after_both_adds_fill(new_risk: NewRisk) -> None:
    r = _env(new_risk)
    _share_with_a_pending_add(r)
    add2 = _add2(r)
    r.at(T0 + 3000)
    r.book("SOL", "100")
    r.paper.advance(T0 + 3000)
    position = r.paper.broker.position("SOL")
    assert position is not None
    true_risk = position.qty * D("1")  # every unit of the share has its stop one dollar from 100
    assert true_risk <= SHARE_CAP + TOL, (true_risk, add2.decision)


@pytest.mark.integration
def test_F10_RISK21a_the_refusal_of_the_second_add_is_not_a_position_mismatch(new_risk: NewRisk) -> None:
    r = _env(new_risk)
    _share_with_a_pending_add(r)
    add2 = _add2(r)
    assert add2.decision.reason != "position_mismatch"


# ---- T21b ------------------------------------------------------------------------------------------------------------


def _fill_the_book_to_total_room(r: RiskEnv, *, room: str) -> None:
    """Risk-only shares of three other leaders, so that the total booked (with S10's 0.3) is 11.3 before ADD1."""
    r.seed_risk_only("XRP", leader="LA", risk="4.0")
    r.seed_risk_only("DOGE", leader="LB", risk="4.0")
    r.seed_risk_only("LTC", leader="LC", risk="3.0")


def _open_eth(r: RiskEnv) -> object:
    return r.gate.submit(
        r.open_req(coin="ETH", leader="L2", share_id="E1", trade_id="TE", signal_id="e1", tids=(300,), stop_px="98.5")
    )


@pytest.mark.integration
def test_F10_RISK21b_an_open_on_another_coin_decided_when_the_add_fills_sees_its_risk_in_the_total(
    new_risk: NewRisk,
) -> None:
    r = _env(new_risk)
    _fill_the_book_to_total_room(r, room="")
    add1 = _share_with_a_pending_add(r)
    r.book("ETH", "100")
    eth = _open_eth(r)
    assert [e.kind for e in eth.broker_events] == ["fill"]  # ADD1
    booked_and_add = D("11.3") + _risk_of(add1)
    assert eth.decision.approved, eth.decision.reason
    assert booked_and_add + _risk_of(eth.decision) <= TOTAL_CAP + TOL, (booked_and_add, eth.decision.initial_risk_usd)


@pytest.mark.integration
def test_F10_RISK21b_the_leader_cap_of_the_adds_leader_counts_the_filled_add(new_risk: NewRisk) -> None:
    r = _env(new_risk, risk__max_leader_open_risk_fraction=D("0.011"))  # leader cap 3.3
    add1 = _share_with_a_pending_add(r)  # leader L1: booked 0.3 + ADD1 2.7 = 3.0, room 0.3
    r.book("ETH", "100")
    out = r.gate.submit(r.open_req(coin="ETH", leader="L1", share_id="E1", trade_id="TE", signal_id="e1", tids=(300,)))
    assert D("0.3") + _risk_of(add1) + _risk_of(out.decision) <= D("3.3") + TOL


@pytest.mark.integration
def test_F10_RISK21b_the_symbol_cap_counts_the_filled_add_for_an_open_on_the_same_coin(new_risk: NewRisk) -> None:
    r = _env(new_risk, risk__max_symbol_open_risk_fraction=D("0.011"))  # symbol cap 3.3
    add1 = _share_with_a_pending_add(r)  # SOL symbol: 0.3 + 2.7 = 3.0, room 0.3
    out = r.gate.submit(
        r.open_req(coin="SOL", leader="L2", share_id="S11", trade_id="T11", signal_id="s11", tids=(301,), stop_px="99")
    )
    assert out.decision.reason != "position_mismatch"
    assert D("0.3") + _risk_of(add1) + _risk_of(out.decision) <= D("3.3") + TOL


# ---- T21c ------------------------------------------------------------------------------------------------------------


def _f12_books_the_add(r: RiskEnv) -> None:
    """What F12 does once it has consumed the fill: the share's quantity and risk now include the add."""
    position = r.paper.broker.position("SOL")
    assert position is not None
    qty = position.qty
    r.shares.shares[:] = [s for s in r.shares.shares if s.share_id != "S10"]
    r.shares.shares.append(
        ShareExposure(
            share_id="S10",
            trade_id="TS1",
            coin="SOL",
            leader="L1",
            is_long=True,
            qty=Qty(str(qty)),
            entry_px=Price("100"),
            stop_px=Price("99"),
            mark_px=Price("100"),
            open_risk_usd=qty * D("1"),
        )
    )


def _eth_open_risk_now(r: RiskEnv) -> D:
    out = r.gate.check(r.open_req(coin="ETH", leader="L2", share_id="E1", trade_id="TE", signal_id="e1", tids=(300,)))
    return _risk_of(out)


@pytest.mark.integration
def test_F10_RISK21c_the_record_is_dropped_when_the_book_catches_up_so_nothing_counts_twice(
    new_risk: NewRisk,
) -> None:
    r = _env(new_risk)
    _fill_the_book_to_total_room(r, room="")
    _share_with_a_pending_add(r)
    r.book("ETH", "100")
    r.paper.advance(T0 + 1000)  # ADD1 fills; F12 has not consumed it yet: 11.3 booked + the add's 2.7, room 1.0
    before = _eth_open_risk_now(r)
    assert D("0.9") <= before <= D("1.0") + TOL, before
    _f12_books_the_add(r)  # the book now holds 3.0 at risk 3.0: 11.0 + 3.0 = 14.0, room 1.0
    after = _eth_open_risk_now(r)
    assert D("0.9") <= after <= D("1.0") + TOL, after  # counted twice it would be 0


@pytest.mark.integration
def test_F10_RISK21c_nothing_leaks_after_the_share_is_fully_closed(new_risk: NewRisk) -> None:
    r = _env(new_risk)
    _fill_the_book_to_total_room(r, room="")
    r.book("ETH", "100")
    baseline = _eth_open_risk_now(r)  # booked 11.0 elsewhere, room 4.0: the per-trade risk (1.5) is the limit
    assert baseline > D("1.4")
    _share_with_a_pending_add(r)
    close = r.gate.submit(r.exit_req(share_id="S10", qty="0.3", close=True))  # nets ADD1's fill: closes 3.0
    assert close.result is not None and close.result.accepted, close
    assert [e.kind for e in close.broker_events] == ["fill"]
    r.paper.advance(T0 + 2500)
    assert r.paper.broker.position("SOL") is None
    r.shares.shares[:] = [s for s in r.shares.shares if s.share_id != "S10"]  # F12 closes the share in the book
    assert _eth_open_risk_now(r) >= baseline - TOL  # a leaked 2.7 would leave room 1.3
