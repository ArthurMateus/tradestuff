"""F12.AC3 mirrored partial exits: the $10 rules, the lot rounding and the mirrored add."""

from __future__ import annotations

from decimal import Decimal as D

from hypothesis import given
from hypothesis import strategies as st

from copytrade.core.domain import ActionKind
from tests.positions.conftest import NewRig
from tests.positions.helpers import make_signal, pos

PLAN = dict(px=D("100"), sz_decimals=2, min_order_usd=D("10"))


def plan(qty: str, fraction: str) -> tuple[str, D]:
    result = pos("rules").reduce_plan(share_qty=D(qty), fraction=D(fraction), **PLAN)
    return result.kind, result.qty


def test_F12_AC3_vector_share_50_dollars_at_fraction_0_4_reduces_20_dollars() -> None:
    assert plan("0.50", "0.4") == ("reduce", D("0.20"))


def test_F12_AC3_vector_share_20_dollars_at_fraction_0_4_is_skipped() -> None:
    assert plan("0.20", "0.4")[0] == "partial_below_min"  # $8


def test_F12_AC3_vector_share_30_dollars_at_fraction_0_7_closes_all() -> None:
    assert plan("0.30", "0.7") == ("close_all_remainder_below_min", D("0.30"))  # $9 remainder


def test_F12_AC3_reduce_notional_boundary_exactly_10_dollars_executes() -> None:
    assert plan("0.25", "0.4") == ("reduce", D("0.10"))
    assert plan("0.24", "0.4")[0] == "partial_below_min"  # 0.096 -> 0.09 = $9


def test_F12_AC3_remainder_boundary_exactly_10_dollars_keeps_the_partial() -> None:
    assert plan("0.30", "0.699") == ("reduce", D("0.20"))  # remainder exactly $10
    assert plan("0.30", "0.7")[0] == "close_all_remainder_below_min"  # 0.21 leaves $9


def test_F12_AC3_reduce_quantity_rounds_down_to_the_lot() -> None:
    assert plan("0.33", "0.5") == ("reduce", D("0.16"))  # 0.165 -> 0.16 (never up)


@given(qty=st.integers(1, 100_000).map(lambda c: D(c) / 100), f=st.integers(1, 999).map(lambda c: D(c) / 1000),
       px=st.integers(1, 100_000).map(lambda c: D(c) / 100))
def test_F12_AC3_plan_properties_never_exceed_the_share_and_respect_lot_and_minimum(qty: D, f: D, px: D) -> None:
    result = pos("rules").reduce_plan(share_qty=qty, fraction=f, px=px, sz_decimals=2, min_order_usd=D("10"))
    assert 0 <= result.qty <= qty
    assert result.qty == result.qty.quantize(D("0.01"))
    if result.kind == "reduce":
        assert result.qty * px >= 10 and (qty - result.qty) * px >= 10 and result.qty <= qty * f
    elif result.kind == "close_all_remainder_below_min":
        assert result.qty == qty
    else:
        assert result.kind == "partial_below_min" and result.qty == 0


def open_share_of(rig, notional: str):  # type: ignore[no-untyped-def]
    rig.leader_state.account_value = D("600")
    return rig.open_share(1, notional=notional)


def reduce_sig(tid: int, fraction: str, **kw: object):  # type: ignore[no-untyped-def]
    return make_signal(tid, ActionKind.REDUCE, size="1", pre="5", post="3", fraction=fraction, **kw)  # type: ignore[arg-type]


def test_F12_AC3_leader_reduce_reduces_our_share_by_the_fraction(new_rig: NewRig) -> None:
    rig = new_rig()
    share = open_share_of(rig, "100")  # $50 -> 0.50 SOL
    assert share.qty == D("0.50")
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(reduce_sig(2, "0.4", ts=now - 100))
    rig.step(now + 1000)
    after = rig.book.state(share.share_id)
    assert (after.status, after.qty) == ("open", D("0.30"))
    assert rig.held("SOL").share_qtys == (D("0.30"),)
    assert after.open_risk_usd == D("0.30") * D("1.5")
    assert "reduced" in [e["event"] for e in rig.share_events(share.share_id)]


def test_F12_AC3_partial_below_minimum_is_skipped_logged_and_sends_nothing(new_rig: NewRig) -> None:
    rig = new_rig()
    share = open_share_of(rig, "40")  # $20
    orders = len(rig.orders())
    rig.feed(reduce_sig(2, "0.4", ts=rig.xtime.now - 100))
    assert len(rig.orders()) == orders
    assert rig.book.state(share.share_id).qty == D("0.20")
    (skip,) = rig.records("signal_skip")
    assert (skip["reason"], skip["share_id"]) == ("partial_below_min", share.share_id)
    assert rig.records("missed_exit") == []  # a rule-based skip is never a missed exit


def test_F12_AC3_remainder_below_minimum_closes_the_whole_share(new_rig: NewRig) -> None:
    rig = new_rig()
    share = open_share_of(rig, "60")  # $30
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(reduce_sig(2, "0.7", ts=now - 100))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"
    assert rig.env.broker.position("SOL") is None
    assert any(e["event"] == "closed" and e.get("reason") == "close_all_remainder_below_min"
               for e in rig.share_events(share.share_id))


def test_F12_AC3_reduce_after_a_take_profit_uses_the_remaining_quantity(new_rig: NewRig) -> None:
    rig = new_rig(exits__trail_start_r=D("5"))
    share = rig.open_share(1)  # 1.00 SOL
    rig.mark_and_fill("SOL", "103")  # TP: 0.50 left
    now = rig.xtime.now
    rig.book_at("SOL", "103", now + 1000)
    rig.feed(reduce_sig(2, "0.5", ts=now - 100))  # 0.25 of 0.50
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).qty == D("0.25")


def test_F12_AC3_leader_add_is_mirrored_through_the_gate_in_proportion(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)  # 1.00 SOL, stop 98.5
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 100))  # +50% of the leader
    rig.step(now + 1000)
    after = rig.book.state(share.share_id)
    assert after.qty == D("1.50") and after.entry_px == D("100")
    assert after.current_stop_px == D("98.5")  # an add never widens the stop
    assert after.open_risk_usd == D("2.25")
    assert after.max_committed_risk_usd >= D("2.25")
    (sl,) = rig.active_stops(share.share_id)
    assert D(str(sl["qty"])) == D("1.50")
    assert "added" in [e["event"] for e in rig.share_events(share.share_id)]


def test_F12_AC3_add_fill_price_updates_the_average_entry(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100.4", now + 1000)
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 100))
    rig.step(now + 1000)
    after = rig.book.state(share.share_id)
    assert abs(after.entry_px - D("100.1333")) < D("0.001")
    assert after.entry_px == rig.held("SOL").avg_entry_px


def test_F12_AC3_add_refused_by_the_gate_leaves_the_share_unchanged_but_exits_still_work(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    rig.gate.pause()
    now = rig.xtime.now
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 100))
    assert rig.book.state(share.share_id).qty == D("1.00")
    assert any(d.get("reason") == "paused" for d in rig.decisions())
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(3, ActionKind.CLOSE, ts=now - 100))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"  # a pause never blocks an exit


def test_F12_AC3_second_add_is_sized_on_the_booked_quantity_not_the_stale_one(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 100))
    rig.step(now + 1000)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(3, ActionKind.ADD, size="1.5", pre="7.5", post="9", ts=now - 100))  # +20% of 1.50
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).qty == D("1.80")
