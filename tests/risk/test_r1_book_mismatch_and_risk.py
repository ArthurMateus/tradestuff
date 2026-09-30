"""F10 review round 1: B2 (broker and share book disagree), B3 (an add is sized at the share's current stop) and B5
(negative open risk never loosens a cap).

Pinned:

* B2: an entry on a coin whose broker position has share IDs different from the share book's shares on that coin is
  refused ``position_mismatch`` (only when the broker holds a position on the coin; a booked share with no broker
  position is the round-0 behaviour and is unchanged). This also covers an entry submitted in the same ``submit`` call
  whose own ``advance_to`` filled an earlier entry on that coin (F12 has not consumed the fill, so the book lacks the
  share). Free equity is equity minus the margin of ALL broker positions (``PaperBroker.positions()``), listed in the
  book or not.
* B3: an ADD is sized, capped and risk-recorded at ``current_stop_px`` (the stop the share keeps), never at the add's
  own tighter ``stop_px``; the decision's ``initial_risk_usd`` is ``qty x |decision_px - current_stop_px|``.
* B5: every cap sum floors each share's ``open_risk_usd`` at 0.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from copytrade.core.money import Price, Qty
from tests.risk.conftest import NewRisk
from tests.risk.helpers import T0
from tests.risk.r1_helpers import forget_share, margin_of, mk, outside_bucket, sent

# ---- B2 --------------------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_B2_a_broker_share_missing_from_the_book_refuses_an_open_on_that_coin(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="LX", qty="0.5", entry="100", stop="80", leverage=5, share="HIDDEN")
    forget_share(r, "HIDDEN")
    r.book("SOL", "100")
    out = r.gate.submit(r.open_req(stop_px="99"))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "position_mismatch", None)
    assert sent(r) == 0


@pytest.mark.integration
def test_F10_B2_a_broker_share_missing_from_the_book_refuses_an_add_on_that_coin(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    r.seed("SOL", leader="LX", qty="0.5", entry="100", stop="98.5", share="HIDDEN")
    forget_share(r, "HIDDEN")
    r.book("SOL", "100")
    out = r.gate.submit(r.add_req(share_id="S1"))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "position_mismatch", None)


@pytest.mark.integration
def test_F10_B2_a_booked_share_the_broker_does_not_hold_refuses_an_entry_when_the_coin_has_a_position(
    new_risk: NewRisk,
) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    r.seed_risk_only("SOL", leader="LG", risk="1.0")  # the book lists a ghost share on SOL the broker never held
    r.book("SOL", "100")
    out = r.gate.submit(r.open_req(share_id="S2", trade_id="T2"))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "position_mismatch", None)


@pytest.mark.integration
def test_F10_B2_matching_share_ids_are_not_a_mismatch(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    r.seed("SOL", leader="L2", qty="0.5", entry="100", stop="98.5", share="S2")
    r.book("SOL", "100")
    out = r.gate.submit(r.open_req(share_id="S3", trade_id="T3", leader="L3"))
    assert out.decision.approved, out.decision.reason


@pytest.mark.integration
def test_F10_B2_a_mismatch_on_another_coin_does_not_refuse_this_coin(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("BTC", leader="LX", qty="0.5", entry="100", stop="98.5", share="HIDDEN")
    forget_share(r, "HIDDEN")
    r.book("ETH", "100")
    out = r.gate.submit(r.open_req(coin="ETH"))
    assert out.decision.approved, out.decision.reason


@pytest.mark.integration
def test_F10_B2_margin_counts_every_broker_position_including_coins_the_book_does_not_list(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("BTC", leader="LZ", qty="2.6", entry="100", stop="99", leverage=1, share="BIG")  # margin 260: free 40
    forget_share(r, "BIG")
    r.book("SOL", "100")
    d = r.gate.submit(r.open_req()).decision
    assert d.approved, d.reason
    assert d.leverage is not None and d.leverage >= 3  # 100 of notional needs leverage 3 to fit 40 of free equity
    assert margin_of(d) <= D(40)


@pytest.mark.integration
def test_F10_B2_no_free_equity_left_by_an_unlisted_position_refuses_the_entry(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("BTC", leader="LZ", qty="3.0", entry="100", stop="99", leverage=1, share="BIG")  # margin 300 = all of it
    forget_share(r, "BIG")
    r.book("SOL", "100")
    out = r.gate.submit(r.open_req())
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "insufficient_margin", None)


@pytest.mark.integration
def test_F10_B2_an_entry_whose_own_advance_fills_an_earlier_entry_on_its_coin_is_refused(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.book("SOL", "100")
    first = r.gate.submit(r.open_req(share_id="S1", trade_id="T1", signal_id="a", tids=(1,)))
    assert first.result is not None and first.result.accepted
    r.at(T0 + 1000)  # the first entry fills inside the next submit's advance_to; F12 has not seen the fill yet
    r.book("SOL", "100")
    second = r.gate.submit(r.open_req(share_id="S2", trade_id="T2", signal_id="b", tids=(2,), leader="L2"))
    assert [e.kind for e in second.broker_events] == ["fill"]
    assert (second.decision.approved, second.decision.reason, second.result) == (False, "position_mismatch", None)
    assert sent(r) == 1


@pytest.mark.integration
def test_F10_B2_an_add_whose_own_advance_fills_an_earlier_add_is_refused(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S10")
    r.book("SOL", "100")
    first = r.gate.submit(r.add_req(share_id="S10", signal_id="a1", tids=(301,)))
    assert first.result is not None and first.result.accepted
    r.at(T0 + 1000)
    r.book("SOL", "100")
    second = r.gate.submit(r.add_req(share_id="S10", signal_id="a2", tids=(302,)))
    assert [e.kind for e in second.broker_events] == ["fill"]
    assert (second.decision.approved, second.decision.reason, second.result) == (False, "position_mismatch", None)


@pytest.mark.integration
def test_F10_B2_margin_of_a_position_filled_by_the_submits_own_advance_counts_for_another_coin(
    new_risk: NewRisk,
) -> None:
    r = mk(new_risk)
    r.seed("BTC", leader="LZ", qty="2.5", entry="100", stop="99", leverage=1, share="BIG")  # margin 250, free 50
    r.book("SOL", "100")
    first = r.gate.submit(r.open_req(share_id="S1", trade_id="T1", signal_id="a", tids=(1,)))
    assert first.decision.approved
    r.at(T0 + 1000)
    r.book("ETH", "100")
    second = r.gate.submit(r.open_req(coin="ETH", share_id="S2", trade_id="T2", signal_id="b", tids=(2,), leader="L2"))
    assert [e.kind for e in second.broker_events] == ["fill"]  # the SOL position now exists (and is unlisted)
    free = D(300) - D(250) - margin_of(first.decision)
    if second.decision.approved:
        assert margin_of(second.decision) <= free
    else:
        assert second.decision.reason == "insufficient_margin"


# ---- B3 --------------------------------------------------------------------------------------------------------------


def _add_at_stops(new_risk: NewRisk, stop_px: str, current: str = "98"):  # type: ignore[no-untyped-def]
    r = mk(new_risk)
    r.seed("SOL", leader="LX", qty="1.0", entry="100", stop=current, leverage=5, share="S10")  # open risk 2.0
    r.book("SOL", "100")
    req = r.add_req(
        share_id="S10", stop_px=Price(stop_px), current_stop_px=Price(current), our_share_qty=Qty("1.0"),
        leader_add_size=Qty("5"), leader_pre_add_position=Qty("1"),
    )
    return r, r.gate.check(req)


@pytest.mark.unit
@pytest.mark.parametrize("stop_px", ["98", "99", "99.5", "99.9", "99.99"])
def test_F10_B3_an_add_is_sized_at_the_shares_current_stop_whatever_its_own_tighter_stop(
    new_risk: NewRisk, stop_px: str
) -> None:
    _r, d = _add_at_stops(new_risk, stop_px)
    assert d.approved, d.reason
    assert d.qty == D("0.50")  # share room 3.0 - 2.0 = 1.0 of risk, at 2 of stop distance per unit: 0.5
    assert d.initial_risk_usd == D("1.00")  # recorded at the stop the share keeps (100 - 98), not at the add's own


@pytest.mark.integration
@pytest.mark.parametrize("stop_px", ["99", "99.9"])
def test_F10_B3_the_share_risk_after_an_add_never_exceeds_the_share_cap(new_risk: NewRisk, stop_px: str) -> None:
    r, d = _add_at_stops(new_risk, stop_px)
    assert d.qty is not None
    share_risk_after = (D("1.0") + d.qty) * (D("100") - D("98"))  # the whole share at the stop it keeps
    assert share_risk_after <= D("0.01") * D(300)
    out = r.gate.submit(
        r.add_req(share_id="S10", stop_px=Price(stop_px), current_stop_px=Price("98"), our_share_qty=Qty("1.0"),
                  leader_add_size=Qty("5"), leader_pre_add_position=Qty("1"))
    )
    assert out.result is not None and out.result.accepted
    assert sent(r) == 1 and r.authority.issued[0][0].qty == d.qty  # type: ignore[union-attr]


@pytest.mark.unit
def test_F10_B3_a_widening_stop_is_still_refused(new_risk: NewRisk) -> None:
    _r, d = _add_at_stops(new_risk, "97")  # the add's stop is beyond the share's current stop of 98
    assert (d.approved, d.reason) == (False, "stop_widening")


@pytest.mark.unit
def test_F10_B3_the_liquidation_rule_uses_the_current_stop_of_the_added_share(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    # 5x on SOL liquidates about 17.5 % away; a current stop 7 away (x3 = 21) breaks the rule, however tight the add's stop
    r.seed("SOL", leader="LX", qty="0.1", entry="100", stop="93", leverage=5, share="S10")
    r.book("SOL", "100")
    d = r.gate.check(
        r.add_req(share_id="S10", stop_px=Price("99.9"), current_stop_px=Price("93"), our_share_qty=Qty("0.1"),
                  leader_add_size=Qty("1"), leader_pre_add_position=Qty("1"))
    )
    assert (d.approved, d.reason) == (False, "add_leverage_unsafe")


# ---- B5 --------------------------------------------------------------------------------------------------------------


def _total_cap_qty(new_risk: NewRisk, locked: str | None) -> Qty | None:
    r = mk(new_risk, returns=outside_bucket())
    for i in range(5):
        r.seed_risk_only(f"A{i}", leader=f"LA{i}", risk="2.85")  # 14.25 of the 15.00 total cap
    if locked is not None:
        r.seed("ZZ", leader="LN", on_broker=False, open_risk=locked)
    r.book("ETH", "100")
    d = r.gate.check(r.open_req(coin="ETH", leader="L9"))
    assert d.approved, d.reason
    return d.qty


@pytest.mark.unit
def test_F10_B5_a_locked_profit_share_does_not_free_room_under_the_total_cap(new_risk: NewRisk) -> None:
    assert _total_cap_qty(new_risk, "-5") == D("0.50")  # room 0.75 of risk at 1.5 per unit, never 5.75


@pytest.mark.unit
@pytest.mark.parametrize("locked", ["-0.01", "-5", "-1000"])
def test_F10_B5_any_negative_open_risk_counts_as_zero_in_the_total_cap(new_risk: NewRisk, locked: str) -> None:
    assert _total_cap_qty(new_risk, locked) == _total_cap_qty(new_risk, "0") == _total_cap_qty(new_risk, None)


@pytest.mark.unit
def test_F10_B5_a_locked_profit_share_does_not_free_room_under_the_leader_cap(new_risk: NewRisk) -> None:
    r = mk(new_risk, returns=outside_bucket())
    r.seed_risk_only("C1", leader="L1", risk="3.75")  # leader cap 4.5: room 0.75
    r.seed("C2", leader="L1", on_broker=False, open_risk="-5")
    r.book("ETH", "100")
    d = r.gate.check(r.open_req(coin="ETH", leader="L1"))
    assert d.approved and d.qty == D("0.50")


@pytest.mark.unit
def test_F10_B5_a_locked_profit_share_does_not_free_room_under_the_symbol_cap(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed_risk_only("SOL", leader="LA", risk="3.75")  # symbol cap 4.5: room 0.75
    r.seed("SOL", leader="LB", on_broker=False, open_risk="-5")
    r.book("SOL", "100")
    d = r.gate.check(r.open_req(coin="SOL", leader="L9", share_id="S9"))
    assert d.approved and d.qty == D("0.50")


@pytest.mark.unit
def test_F10_B5_a_locked_profit_share_does_not_free_room_under_the_btc_bucket_cap(new_risk: NewRisk) -> None:
    r = mk(new_risk)  # no candles: every coin is in the bucket (cap 9.0)
    r.seed_risk_only("C1", leader="LA", risk="4.125")
    r.seed_risk_only("C2", leader="LB", risk="4.125")  # 8.25 used, room 0.75
    r.seed("C3", leader="LC", on_broker=False, open_risk="-5")
    r.book("SOL", "100")
    d = r.gate.check(r.open_req(coin="SOL", leader="L9"))
    assert d.approved and d.qty == D("0.50")


@pytest.mark.unit
def test_F10_B5_the_shares_own_negative_open_risk_does_not_widen_its_share_cap_on_an_add(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="LX", qty="1.0", entry="100", stop="97", leverage=5, share="S10", open_risk="-2")
    r.book("SOL", "100")
    d = r.gate.check(
        r.add_req(share_id="S10", stop_px=Price("97"), current_stop_px=Price("97"), our_share_qty=Qty("1.0"),
                  leader_add_size=Qty("5"), leader_pre_add_position=Qty("1"))
    )
    assert d.approved and d.qty == D("1.00")  # share room 3.0 (not 5.0) at 3 per unit
    assert d.initial_risk_usd == D("3.00")


@pytest.mark.unit
def test_F10_B5_a_share_in_profit_with_zero_risk_is_unchanged(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed_risk_only("SOL", leader="LA", risk="0")
    r.book("SOL", "100")
    d = r.gate.check(r.open_req(coin="SOL", leader="L9", share_id="S9"))
    assert d.approved and d.qty == D("1.00")

