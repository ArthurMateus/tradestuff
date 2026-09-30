# mypy: disable-error-code="union-attr"
"""F11 round 2, Amendment 8: stale decisions (RISK-1) and opposite-side entries (RISK-2).

Amendment 8: the broker never fills at a book earlier than its own time. An OPEN/ADD decided before the broker's
current time is refused ``stale_decision``; an exit (CLOSE/REDUCE/stop) with an old decision time is never refused and
fills no earlier than the broker's current time. A flip is CLOSE, then OPEN after the close fills: an OPEN/ADD on the
opposite side of the coin's position is refused ``opposite_side_entry`` and an entry never reduces a position.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.paper.helpers import BASE, D0, HOUR_MS, Env, NewEnv, fresh_env

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty

NOW = D0 + 60_000  # the broker's time in the stale-decision tests


def _long_open_at_now(e: Env) -> None:
    e.open_position("buy", "2.0", px="100")
    e.advance(NOW)


# ------------------------------------------------------------------------------------------------- RISK-1


@pytest.mark.unit
@pytest.mark.parametrize("action", [ActionKind.OPEN, ActionKind.ADD])
def test_R2_RISK1_an_entry_decided_before_the_broker_time_is_refused_stale_decision(
    new_env: NewEnv, action: ActionKind
) -> None:
    e = new_env()
    e.advance(NOW)
    e.flat_book("SOL", NOW + 1000, "100")
    result = e.submit(e.order("buy", "1.0", decided=NOW - 1, action=action))
    assert (result.accepted, result.reason) == (False, "stale_decision")
    assert e.advance(NOW + 5000) == []  # nothing is pending, nothing fills
    assert e.broker.position("SOL") is None and e.fills() == []


@pytest.mark.unit
@pytest.mark.parametrize("action", [ActionKind.OPEN, ActionKind.ADD])
def test_R2_RISK1_an_entry_decided_exactly_at_the_broker_time_is_accepted_and_fills(
    new_env: NewEnv, action: ActionKind
) -> None:
    e = new_env()
    e.advance(NOW)
    e.flat_book("SOL", NOW + 1000, "100")
    result = e.submit(e.order("buy", "1.0", decided=NOW, action=action))
    assert (result.accepted, result.reason) == (True, None)
    (ev,) = e.advance(NOW + 1000)
    assert ev.kind == "fill" and ev.fill.time.ms == NOW + 1000


@pytest.mark.unit
def test_R2_RISK1_an_entry_one_ms_later_than_the_broker_time_is_accepted(new_env: NewEnv) -> None:
    e = new_env()
    e.advance(NOW)
    assert e.submit(e.order("buy", "1.0", decided=NOW + 1)).accepted


@pytest.mark.unit
def test_R2_RISK1_the_broker_time_is_the_time_it_was_advanced_to_not_the_local_clock(new_env: NewEnv) -> None:
    """Pinned reading of "the broker's current time": the latest time given to ``advance_to`` (Amendment 11:
    marks and delistings never move it; a replay has no wall clock). A local clock that ran ahead without the broker being advanced does
    not make a decision stale."""
    e = new_env()
    e.clock.now = D0 + 3_600_000
    e.flat_book("SOL", D0 + 1000, "100")
    assert e.submit(e.order("buy", "1.0", decided=D0)).accepted


@pytest.mark.unit
@pytest.mark.parametrize("action", [ActionKind.CLOSE, ActionKind.REDUCE])
def test_R2_RISK1_an_exit_with_an_old_decision_time_is_accepted_and_fills_no_earlier_than_broker_time(
    new_env: NewEnv, action: ActionKind
) -> None:
    e = new_env()
    _long_open_at_now(e)
    e.flat_book("SOL", D0 + 2000, "100")  # a recorded book from BEFORE the broker's time: must not be used
    e.flat_book("SOL", NOW + 1000, "110")
    qty = "2.0" if action is ActionKind.CLOSE else "1.0"
    result = e.submit(e.order("sell", qty, coid="x1", action=action, decided=D0 + 1500, share="S1"))
    assert (result.accepted, result.reason) == (True, None)
    # the exit's own decision time is long past, so its "exit_unfilled" alert event may precede the fill (Amendment 10)
    events = [ev for ev in e.advance(NOW + 1000) if ev.kind != "exit_unfilled_alert"]
    assert [ev.kind for ev in events] == ["fill"]
    fill = events[0].fill
    assert fill.time.ms == NOW + 1000 and fill.time.ms >= NOW
    assert fill.price == Price("110")


@pytest.mark.unit
def test_R2_RISK1_a_stop_trigger_with_an_old_mark_time_fills_no_earlier_than_broker_time(new_env: NewEnv) -> None:
    e = new_env()
    _long_open_at_now(e)
    assert e.stop("sl", "sell", "2.0", "95").accepted
    e.flat_book("SOL", D0 + 2000, "100")
    e.flat_book("SOL", NOW + 1000, "94")
    e.mark("SOL", "94", D0 + 3000)  # a mark stamped before the broker's time
    events = [ev for ev in e.advance(NOW + 1000) if ev.kind != "exit_unfilled_alert"]  # Amendment 10
    assert [ev.kind for ev in events] == ["fill"]
    assert events[0].fill.time.ms >= NOW and events[0].fill.price == Price("94")
    assert events[0].fill.exit_reason == "stop_loss"


@pytest.mark.unit
def test_R2_RISK1_no_fill_precedes_a_funding_boundary_that_was_already_charged(new_env: NewEnv) -> None:
    """Funding for the hour at B1 is charged once the broker's time passes it. An entry decided before B1 is then
    refused, and an exit decided before B1 fills after it, so no fill can dodge or duplicate the charge."""
    b1 = BASE + HOUR_MS
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", b1, "0.0001", "100")
    e.advance(b1 + 10_000)
    assert [r.payload["hour_ms"] for r in e.records("paper_funding")] == [b1]
    e.flat_book("SOL", b1 - 4000, "100")
    e.flat_book("SOL", b1 + 11_000, "100")
    add = e.submit(e.order("buy", "1.0", coid="add1", action=ActionKind.ADD, decided=b1 - 5000, share="S2", trade="T2"))
    assert (add.accepted, add.reason) == (False, "stale_decision")
    exit_ = e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.REDUCE, decided=b1 - 5000))
    assert exit_.accepted
    events = [ev for ev in e.advance(b1 + 11_000) if ev.kind != "exit_unfilled_alert"]  # Amendment 10
    assert [ev.kind for ev in events] == ["fill"] and events[0].fill.time.ms >= b1 + 10_000
    assert all(f.time.ms >= D0 + 1000 for f in e.fills())
    assert [f.time.ms for f in e.fills()][1:] == [b1 + 11_000]


@pytest.mark.unit
@settings(max_examples=40, deadline=None)
@given(
    now_offset=st.integers(min_value=1000, max_value=2 * HOUR_MS),
    lag=st.integers(min_value=0, max_value=3 * HOUR_MS),
    is_exit=st.booleans(),
)
def test_R2_RISK1_property_no_fill_is_ever_earlier_than_the_broker_time_at_submission(
    now_offset: int, lag: int, is_exit: bool
) -> None:
    with fresh_env() as e:
        e.open_position("buy", "2.0", px="100")
        now = D0 + 1000 + now_offset
        for hour in (BASE + HOUR_MS, BASE + 2 * HOUR_MS, BASE + 3 * HOUR_MS):
            e.funding.set("SOL", hour, "0.0001", "100")
        e.advance(now)
        e.flat_book("SOL", D0 + 2000, "90")  # a stale book, from before the broker's time
        e.flat_book("SOL", now + 1000, "110")
        e.flat_book("SOL", now + 2000, "111")
        decided = now - lag
        if is_exit:
            intent = e.order("sell", "1.0", coid="x1", action=ActionKind.REDUCE, decided=decided)
        else:
            intent = e.order("buy", "1.0", coid="x1", action=ActionKind.ADD, decided=decided, share="S2", trade="T2")
        result = e.submit(intent)
        if is_exit:
            assert result.accepted
        else:
            assert result.accepted == (lag == 0)
        e.advance(now + 20_000)
        new_fills = [f for f in e.fills() if f.client_order_id == "x1"]
        assert all(f.time.ms >= now for f in new_fills)
        assert bool(new_fills) == result.accepted


# ------------------------------------------------------------------------------------------------- RISK-2


@pytest.mark.unit
@pytest.mark.parametrize("action", [ActionKind.OPEN, ActionKind.ADD])
@pytest.mark.parametrize("share", ["S1", "S2"])
def test_R2_RISK2_an_entry_opposite_to_a_long_position_is_refused_opposite_side_entry(
    new_env: NewEnv, action: ActionKind, share: str
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.flat_book("SOL", D0 + 11_000, "100")
    e.advance(D0 + 10_000)  # Amendment 11 (RISK-23): the supervisor has advanced broker time to the decision time
    result = e.submit(
        e.order("sell", "0.5", coid="o2", action=action, decided=D0 + 10_000, share=share, trade="T" + share[1])
    )
    assert (result.accepted, result.reason) == (False, "opposite_side_entry")
    assert e.advance(D0 + 11_000) == []
    assert e.broker.position("SOL").qty == Qty("1.0")  # an entry never reduces a position
    assert len(e.fills()) == 1 and e.trades() == []


@pytest.mark.unit
@pytest.mark.parametrize("action", [ActionKind.OPEN, ActionKind.ADD])
def test_R2_RISK2_an_entry_opposite_to_a_short_position_is_refused_opposite_side_entry(
    new_env: NewEnv, action: ActionKind
) -> None:
    e = new_env()
    e.open_position("sell", "1.0", px="100")
    e.flat_book("SOL", D0 + 11_000, "100")
    e.advance(D0 + 10_000)  # Amendment 11 (RISK-23): the supervisor has advanced broker time to the decision time
    result = e.submit(e.order("buy", "1.0", coid="o2", action=action, decided=D0 + 10_000, share="S2", trade="T2"))
    assert (result.accepted, result.reason) == (False, "opposite_side_entry")
    assert e.advance(D0 + 11_000) == []
    assert e.broker.position("SOL").qty == Qty("-1.0")


@pytest.mark.unit
def test_R2_RISK2_an_opposite_entry_larger_than_the_position_is_refused_and_opens_no_short(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.flat_book("SOL", D0 + 11_000, "100")
    result = e.submit(e.order("sell", "3.0", coid="o2", decided=D0 + 10_000, share="S2", trade="T2"))
    assert result.accepted is False
    e.advance(D0 + 11_000)
    assert e.broker.position("SOL").qty == Qty("1.0")


@pytest.mark.unit
def test_R2_RISK2_an_entry_on_another_coin_or_after_the_close_is_still_fine(new_env: NewEnv) -> None:
    """Controls: the refusal is only for the coin that holds a position, and a flip is CLOSE, then OPEN."""
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.open_position("sell", "0.1", px="1000", coin="BTC", coid="o2", share="S2", trade="T2", decided=D0 + 10_000)
    assert e.broker.position("BTC").qty == Qty("-0.1")
    e.flat_book("SOL", D0 + 21_000, "100")
    assert e.submit(e.order("sell", "1.0", coid="cl", action=ActionKind.CLOSE, decided=D0 + 20_000)).accepted
    assert [ev.kind for ev in e.advance(D0 + 21_000)] == ["fill"]
    e.open_position("sell", "1.0", px="100", coid="o3", share="S3", trade="T3", decided=D0 + 30_000)
    assert e.broker.position("SOL").qty == Qty("-1.0")


@pytest.mark.unit
def test_R2_RISK2_two_entries_accepted_while_flat_never_net_against_each_other(new_env: NewEnv) -> None:
    """Both are accepted before either fills (no position yet). When the buy has filled, the sell entry on the same
    share must not reduce it: the position stays what the first entry made it."""
    e = new_env()
    e.flat_book("SOL", D0 + 1000, "100")
    assert e.submit(e.order("buy", "1.0", coid="c1")).accepted
    e.submit(e.order("sell", "0.5", coid="c2"))  # same share S1, opposite side (may be refused already, or later)
    e.advance(D0 + 1000)
    e.advance(D0 + 20_000)
    assert e.broker.position("SOL").qty == Qty("1.0")
    assert [f.client_order_id for f in e.fills()] == ["c1"]
    assert e.trades() == []
    assert e.broker.cash_usd() == D("299.955")


@pytest.mark.unit
def test_R2_RISK2_a_liquidated_share_never_lets_a_pending_entry_open_a_naked_short_on_its_ids(
    new_env: NewEnv,
) -> None:
    """A long S1 is liquidated while a sell entry that names S1 / T1 is still pending (it was accepted while the coin
    was flat). It must not fill as a short that reuses the closed share's IDs."""
    e = new_env()
    e.flat_book("SOL", D0 + 1000, "100")
    e.flat_book("SOL", D0 + 6000, "100")
    assert e.submit(e.order("buy", "1.0", coid="c1", decided=D0)).accepted
    e.submit(e.order("sell", "1.0", coid="c2", decided=D0 + 5000))  # S1 / T1 again, opposite side, decided later
    e.advance(D0 + 1000)
    assert e.broker.position("SOL").qty == Qty("1.0")
    events = e.mark("SOL", "80", D0 + 3000)  # below the liquidation price 82.5
    assert [ev.kind for ev in events] == ["liquidated"]
    e.advance(D0 + 20_000)
    assert e.broker.position("SOL") is None
    assert [f.client_order_id for f in e.fills() if f.client_order_id.startswith("c")] == ["c1"]


@pytest.mark.unit
def test_R2_RISK2_a_closed_share_never_lets_a_pending_entry_open_a_naked_short_on_its_ids(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", D0 + 1000, "100")
    e.flat_book("SOL", D0 + 12_000, "100")
    e.flat_book("SOL", D0 + 16_000, "100")
    assert e.submit(e.order("buy", "1.0", coid="c1", decided=D0)).accepted
    e.submit(e.order("sell", "1.0", coid="c3", decided=D0 + 15_000))  # S1 / T1 again, decided long after the close
    e.advance(D0 + 1000)
    assert e.submit(e.order("sell", "1.0", coid="c2", action=ActionKind.CLOSE, decided=D0 + 11_000)).accepted
    e.advance(D0 + 12_000)
    assert e.broker.position("SOL") is None
    e.advance(D0 + 30_000)
    assert e.broker.position("SOL") is None
    assert "c3" not in [f.client_order_id for f in e.fills()]


@pytest.mark.unit
def test_R2_RISK2_a_pending_opposite_entry_never_counts_as_a_reduction_of_the_share_an_exit_needs(
    new_env: NewEnv,
) -> None:
    """An entry never reduces a position, so an entry that is still pending (accepted while the coin was flat) must
    not use up the share's quantity: a full CLOSE of the share is still admitted."""
    e = new_env()
    e.flat_book("SOL", D0 + 1000, "100")
    e.flat_book("SOL", D0 + 12_000, "100")
    assert e.submit(e.order("buy", "1.0", coid="c1")).accepted
    e.submit(e.order("sell", "1.0", coid="c3", decided=D0 + 15_000))  # S1 again, opposite side, still pending
    e.advance(D0 + 1000)
    result = e.submit(e.order("sell", "1.0", coid="c2", action=ActionKind.CLOSE, decided=D0 + 11_000))
    assert (result.accepted, result.reason) == (True, None)
    events = [ev for ev in e.advance(D0 + 12_000) if ev.kind != "exit_unfilled_alert"]  # Amendment 10
    assert [ev.kind for ev in events] == ["fill"]
    assert e.broker.position("SOL") is None


@pytest.mark.unit
@pytest.mark.parametrize("second_leverage", [10, 2])
def test_R2_RISK2_the_leverage_of_a_merged_position_is_not_overwritten_by_a_later_entry(
    new_env: NewEnv, second_leverage: int
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", leverage=5)
    before = e.broker.position("SOL")
    e.open_position(
        "buy",
        "1.0",
        px="100",
        leverage=second_leverage,
        coid="o2",
        share="S2",
        trade="T2",
        decided=D0 + 10_000,
        action=ActionKind.ADD,
    )
    after = e.broker.position("SOL")
    assert before.leverage == 5 and after.leverage == 5
    assert after.liquidation_px == before.liquidation_px == Price("82.5")
    assert after.margin_usd == D("40")  # 2 x 100 / 5
