"""F10 review round 1, B1: entries the broker has accepted but not yet filled (in flight) count everywhere.

Pinned (see docs/sdlc/copytrade-v1/05-test-plan-F10-r1.md):

* the gate reads ``PaperBroker.pending_entries()`` and treats each pending entry as if it had filled: its margin
  (qty x decision px / leverage) comes off free equity, it counts as an open position, and the open risk the gate
  approved for it counts in the symbol, leader, total and BTC-bucket caps;
* an entry on a coin that already has a pending entry is refused ``entry_in_flight`` (one pinned reason for OPEN and
  ADD, same side or not, except that an opposite-side entry is refused ``opposite_side_entry`` first);
* when the pending entry resolves (filled, rejected, expired) the capacity is released or is carried by the share book.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from tests.risk.conftest import NewRisk
from tests.risk.helpers import T0, RiskEnv
from tests.risk.r1_helpers import book_share, margin_of, mk, outside_bucket, sent

EQUITY = D(300)


def _open(r: RiskEnv, coin: str, n: int, *, leader: str | None = None, **kw: object):  # type: ignore[no-untyped-def]
    return r.gate.submit(
        r.open_req(coin=coin, leader=leader or f"L{n}", share_id=f"S{n}", trade_id=f"T{n}", signal_id=f"s{n}",
                   tids=(200 + n,), **kw)
    )


# ---- simultaneous opens ----------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_B1_five_simultaneous_opens_on_one_coin_send_one_and_refuse_the_rest(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.book("SOL", "100")
    outs = [_open(r, "SOL", i) for i in range(5)]
    assert outs[0].decision.approved and outs[0].result is not None and outs[0].result.accepted
    for later in outs[1:]:
        assert (later.decision.approved, later.decision.reason, later.result) == (False, "entry_in_flight", None)
    assert sent(r) == 1
    r.fill()
    position = r.paper.broker.position("SOL")
    assert position is not None
    assert position.qty * D("1.5") <= D("4.5")  # the symbol cap (1.5 % of 300) holds at the stop
    assert position.margin_usd <= EQUITY


@pytest.mark.integration
def test_F10_B1_opens_on_different_coins_never_commit_more_margin_than_the_equity(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    free = EQUITY
    for i, coin in enumerate(("BTC", "ETH", "SOL", "DOGE")):
        r.book(coin, "100")
        out = _open(r, coin, i)
        d = out.decision
        if d.approved:
            assert margin_of(d) <= free, (coin, margin_of(d), free)
            free -= margin_of(d)
        else:
            assert d.reason == "insufficient_margin", (coin, d.reason)
    r.fill()
    posted = sum((p.margin_usd for p in (r.paper.broker.position(c) for c in ("BTC", "ETH", "SOL", "DOGE")) if p), D(0))
    assert posted <= EQUITY


@pytest.mark.integration
def test_F10_B1_margin_of_a_pending_entry_is_not_free_and_is_released_when_it_expires(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("BTC", leader="LZ", qty="2.5", entry="100", stop="99", leverage=1, share="BIGS")  # margin 250, free 50
    first = _open(r, "ETH", 1)
    assert first.decision.approved and first.result is not None and first.result.accepted
    blocked = _open(r, "DOGE", 2)  # free equity is ~0 while ETH is in flight; DOGE tops out at 5x (20 margin)
    assert (blocked.decision.approved, blocked.decision.reason, blocked.result) == (False, "insufficient_margin", None)
    r.at(T0 + 7000)  # ETH had no book: its window (fill time + 5 s) ran out, so it was rejected, never filled
    r.book("DOGE", "100")
    freed = _open(r, "DOGE", 3)
    assert freed.decision.approved, freed.decision.reason
    assert [e.reason for e in freed.broker_events if e.kind == "reject"] == ["no_book"]


@pytest.mark.integration
def test_F10_B1_a_pending_entry_counts_as_an_open_position(new_risk: NewRisk) -> None:
    r = mk(new_risk, risk__max_open_positions=2)
    for i, coin in enumerate(("SOL", "ETH")):
        r.book(coin, "100")
        assert _open(r, coin, i).result is not None
    r.book("DOGE", "100")
    third = _open(r, "DOGE", 3)
    assert (third.decision.approved, third.decision.reason, third.result) == (False, "max_open_positions", None)
    assert sent(r) == 2


# ---- caps ------------------------------------------------------------------------------------------------------------


def _failed_cap(out_checks: tuple, name: str) -> bool:  # type: ignore[type-arg]
    return any(c.check == name and not c.passed for c in out_checks)


@pytest.mark.integration
def test_F10_B1_a_pending_entry_uses_up_the_leaders_open_risk_cap(new_risk: NewRisk) -> None:
    r = mk(new_risk, returns=outside_bucket())
    r.seed_risk_only("AAA", leader="L1", risk="3.0")  # leader cap 4.5: room 1.5
    r.book("ETH", "100")
    r.book("DOGE", "100")
    first = _open(r, "ETH", 1, leader="L1")
    assert first.decision.approved and first.decision.initial_risk_usd == D("1.5")
    second = _open(r, "DOGE", 2, leader="L1")
    assert (second.decision.approved, second.decision.reason, second.result) == (False, "unexecutable", None)
    assert _failed_cap(second.decision.checks, "leader_risk")


@pytest.mark.integration
def test_F10_B1_pending_entries_use_up_the_total_open_risk_cap(new_risk: NewRisk) -> None:
    r = mk(new_risk, returns=outside_bucket())
    for i in range(5):
        r.seed_risk_only(f"A{i}", leader=f"LA{i}", risk="2.7")  # 13.5 of the 15.0 total cap
    r.book("ETH", "100")
    r.book("DOGE", "100")
    first = _open(r, "ETH", 1)
    assert first.decision.approved and first.decision.initial_risk_usd == D("1.5")
    second = _open(r, "DOGE", 2)
    assert (second.decision.approved, second.decision.reason, second.result) == (False, "unexecutable", None)
    assert _failed_cap(second.decision.checks, "total_risk")


@pytest.mark.integration
def test_F10_B1_pending_entries_use_up_the_btc_bucket_cap(new_risk: NewRisk) -> None:
    r = mk(new_risk)  # no candles: every coin counts as in the bucket (cap 9.0)
    r.seed_risk_only("A1", leader="LA", risk="4.125")
    r.seed_risk_only("A2", leader="LB", risk="4.125")  # 8.25 used, room 0.75
    r.book("ETH", "100")
    r.book("SOL", "100")
    first = _open(r, "ETH", 1)
    assert first.decision.approved and first.decision.qty == D("0.50") and first.decision.initial_risk_usd == D("0.75")
    second = _open(r, "SOL", 2)
    assert (second.decision.approved, second.decision.reason, second.result) == (False, "unexecutable", None)
    assert _failed_cap(second.decision.checks, "btc_bucket_risk")


@pytest.mark.integration
def test_F10_B1_a_partly_sized_pending_entry_counts_at_the_risk_the_gate_approved(new_risk: NewRisk) -> None:
    r = mk(new_risk, returns=outside_bucket())
    r.seed_risk_only("AAA", leader="L1", risk="3.75")  # leader room 0.75
    r.book("ETH", "100")
    r.book("SOL", "100")
    first = _open(r, "ETH", 1, leader="L1")
    assert first.decision.qty == D("0.50")  # cut to 0.75 of risk by the leader cap
    second = _open(r, "SOL", 2, leader="L1")
    assert second.decision.approved is False and second.decision.reason == "unexecutable"


# ---- same coin: entry_in_flight, direction, leverage -----------------------------------------------------------------


@pytest.mark.integration
def test_F10_B1_a_second_entry_on_a_coin_with_a_pending_entry_is_refused_entry_in_flight(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.book("SOL", "100")
    first = _open(r, "SOL", 1)
    assert first.result is not None and first.result.accepted
    second = _open(r, "SOL", 2, stop_px="88")  # a wider stop must not get a fresh leverage either
    assert (second.decision.approved, second.decision.reason, second.result) == (False, "entry_in_flight", None)
    assert sent(r) == 1
    r.fill()
    position = r.paper.broker.position("SOL")
    assert position is not None and position.leverage == first.decision.leverage
    assert position.share_ids == ("S1",)


@pytest.mark.integration
def test_F10_B1_entry_in_flight_also_refuses_an_add_while_an_add_is_pending(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S10")
    r.book("SOL", "100")
    first = r.gate.submit(r.add_req(share_id="S10", signal_id="a1", tids=(301,)))
    assert first.result is not None and first.result.accepted
    second = r.gate.submit(r.add_req(share_id="S10", signal_id="a2", tids=(302,)))
    assert (second.decision.approved, second.decision.reason, second.result) == (False, "entry_in_flight", None)
    assert sent(r) == 1


@pytest.mark.integration
def test_F10_B1_entry_in_flight_also_refuses_an_open_of_another_share_while_an_add_is_pending(
    new_risk: NewRisk,
) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S10")
    r.book("SOL", "100")
    assert r.gate.submit(r.add_req(share_id="S10", signal_id="a1", tids=(301,))).result is not None
    other = r.gate.submit(r.open_req(leader="L2", share_id="S11", trade_id="T11", signal_id="o1", tids=(401,)))
    assert (other.decision.approved, other.decision.reason, other.result) == (False, "entry_in_flight", None)


@pytest.mark.integration
def test_F10_B1_an_opposite_side_entry_against_a_pending_entry_is_refused_before_the_broker(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.book("SOL", "100")
    first = _open(r, "SOL", 1)
    assert first.result is not None and first.result.accepted
    short = r.gate.submit(
        r.open_req(is_long=False, stop_px="101.5", leader="L2", share_id="S2", trade_id="T2", signal_id="s2",
                   tids=(202,))
    )
    assert (short.decision.approved, short.decision.reason, short.result) == (False, "opposite_side_entry", None)
    assert sent(r) == 1
    assert r.paper.records("paper_reject") == []  # the broker never saw it


@pytest.mark.integration
def test_F10_B1_the_check_path_also_sees_pending_entries(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.book("SOL", "100")
    assert _open(r, "SOL", 1).result is not None
    assert r.gate.check(r.open_req(share_id="S2", signal_id="c2", tids=(9,))).reason == "entry_in_flight"


# ---- the pending entry resolves ---------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_B1_a_rejected_pending_entry_frees_the_coin(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    first = _open(r, "SOL", 1)  # no book: it will expire
    assert first.result is not None and first.result.accepted
    r.at(T0 + 7000)
    r.book("SOL", "100")
    again = _open(r, "SOL", 2)
    assert again.decision.approved and again.result is not None and again.result.accepted
    assert [e.reason for e in again.broker_events if e.kind == "reject"] == ["no_book"]


@pytest.mark.integration
def test_F10_B1_a_filled_entry_is_carried_by_the_share_book_not_counted_twice(new_risk: NewRisk) -> None:
    r = mk(new_risk, returns=outside_bucket())
    r.book("ETH", "100")
    first = _open(r, "ETH", 1, leader="L1")
    r.fill()
    r.at(T0 + 1000)
    position = r.paper.broker.position("ETH")
    assert position is not None
    book_share(r, "S1", "ETH", qty=str(position.qty), leader="L1")  # F12 has consumed the fill
    r.book("ETH", "100")
    again = _open(r, "ETH", 2, leader="L1")
    assert again.decision.approved, again.decision.reason
    assert first.decision.initial_risk_usd == D("1.5")
    # leader L1 now carries 1.5 (the filled share, once); the second entry is cut by nothing it would not be otherwise
    assert again.decision.initial_risk_usd == D("1.5")
    assert again.decision.leverage == position.leverage


@pytest.mark.integration
def test_F10_B1_a_filled_entry_is_not_counted_twice_once_the_share_book_carries_it(new_risk: NewRisk) -> None:
    r = mk(new_risk, returns=outside_bucket())
    r.seed_risk_only("AAA", leader="L1", risk="1.5")
    r.book("ETH", "100")
    assert _open(r, "ETH", 1, leader="L1").decision.approved
    r.fill()
    r.at(T0 + 1000)
    position = r.paper.broker.position("ETH")
    assert position is not None
    book_share(r, "S1", "ETH", qty=str(position.qty), leader="L1")  # the book now says 1.5 + 1.5 = 3.0 of 4.5
    r.book("DOGE", "100")
    next_one = _open(r, "DOGE", 2, leader="L1")
    assert next_one.decision.approved, next_one.decision.reason  # counted twice it would be 4.5 and refuse
    assert next_one.decision.initial_risk_usd == D("1.5")


@pytest.mark.integration
@pytest.mark.parametrize("count", [3, 5])
def test_F10_B1_n_simultaneous_opens_on_n_coins_never_exceed_the_position_count_limit(
    new_risk: NewRisk, count: int
) -> None:
    coins = ("BTC", "ETH", "SOL", "DOGE", "AAA")
    r = mk(new_risk, risk__max_open_positions=2)
    for coin in coins:
        r.paper.meta.meta.setdefault(coin, r.paper.meta.meta["DOGE"])
        r.book(coin, "100")
    approved = [_open(r, coin, i).decision.approved for i, coin in enumerate(coins[:count])]
    assert sum(approved) == 2
