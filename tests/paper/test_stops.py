# mypy: disable-error-code="union-attr"
"""F11.AC7: SL and TP trigger on the MARK and fill at the book at trigger time + paper.ack_delay_ms, never at a
guaranteed price. Long stop at 99, next book bid 97.0 -> the fill is <= 97.0. Exit retries and partial exits follow
F11.AC8 (an exit must not leave an orphan, C4)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from tests.paper.helpers import Env
from tests.paper.helpers import NewEnv

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.money import Fee, Price, Qty
from tests.paper.helpers import D0

T = D0 + 60_000


def _long_with_stop(e: Env, trigger: str = "99", kind: str = "sl", tid: str = "stop1") -> None:
    e.open_position("buy", "1.0", px="100")
    assert e.stop(kind, "sell", "1.0", trigger, coid=tid).accepted


@pytest.mark.unit
def test_F11_AC7_spec_example_long_stop_99_fills_at_the_next_bid_97(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    e.book("SOL", T + 500, [("98.5", "10")], [("98.6", "10")])  # before the ack delay: must not be used
    e.book("SOL", T + 1000, [("97.0", "10")], [("97.1", "10")])
    assert e.mark("SOL", "98.9", T) == []  # trigger observed; the fill is not instantaneous
    assert e.advance(T + 999) == []
    (ev,) = e.advance(T + 1000)
    fill = ev.fill
    assert fill.price <= Price("97.0") and fill.price == Price("97.0")
    assert fill.price != Price("99")  # never at the trigger price
    assert fill.exit_reason == "stop_loss" and fill.side == "sell" and fill.qty == Qty("1.0")
    assert fill.fee == Fee("0.04365")  # 97 x 4.5 bps
    assert fill.time == Timestamp(T + 1000, TimeSource.EXCHANGE)
    assert ev.trade.pnl_usd == D("-3.08865")  # -3 - 0.045 - 0.04365
    assert ev.trade.flags == frozenset()
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_F11_AC7_stop_triggers_when_the_mark_equals_the_trigger_and_not_one_tick_above(new_env: NewEnv) -> None:
    above = new_env()
    _long_with_stop(above)
    above.flat_book("SOL", T + 1000, "98")
    above.mark("SOL", "99.01", T)
    assert above.advance(T + 1000) == []
    assert above.broker.position("SOL") is not None

    equal = new_env()
    _long_with_stop(equal)
    equal.flat_book("SOL", T + 1000, "98")
    equal.mark("SOL", "99", T)
    assert [ev.kind for ev in equal.advance(T + 1000)] == ["fill"]


@pytest.mark.unit
def test_F11_AC7_trigger_uses_the_mark_not_the_book(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    e.book("SOL", T, [("98", "10")], [("98.1", "10")])  # the book trades below the stop ...
    e.mark("SOL", "100", T)  # ... but the mark does not
    e.advance(T + 2000)
    assert e.broker.position("SOL") is not None


@pytest.mark.unit
def test_F11_AC7_take_profit_long_fills_at_the_book_which_may_beat_the_target(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e, trigger="110", kind="tp", tid="tp1")
    e.mark("SOL", "109.99", T)
    e.book("SOL", T + 1000, [("110.5", "5")], [("110.6", "5")])
    assert e.advance(T + 1000) == []  # 109.99 did not trigger
    e.mark("SOL", "110", T + 5000)
    e.book("SOL", T + 6000, [("110.5", "5")], [("110.6", "5")])
    (ev,) = e.advance(T + 6000)
    assert ev.fill.price == Price("110.5") and ev.fill.exit_reason == "take_profit"
    assert ev.trade.pnl_usd == D("10.405275")  # +10.5 - 0.045 - 110.5 x 0.00045


@pytest.mark.unit
def test_F11_AC7_short_stop_loss_buys_at_the_ask(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("sell", "1.0", px="100")
    e.stop("sl", "buy", "1.0", "101")
    e.mark("SOL", "101", T)
    e.book("SOL", T + 1000, [("102.9", "5")], [("103", "5")])
    (ev,) = e.advance(T + 1000)
    assert ev.fill.price == Price("103") and ev.fill.side == "buy" and ev.fill.exit_reason == "stop_loss"
    assert ev.trade.pnl_usd == D("-3.09135")  # -3 - 0.045 - 103 x 0.00045


@pytest.mark.unit
def test_F11_AC7_short_take_profit(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("sell", "1.0", px="100")
    e.stop("tp", "buy", "1.0", "90")
    e.mark("SOL", "90.01", T)
    assert e.advance(T + 1000) == []
    e.mark("SOL", "90", T + 5000)
    e.book("SOL", T + 6000, [("89.4", "5")], [("89.5", "5")])
    (ev,) = e.advance(T + 6000)
    assert ev.fill.price == Price("89.5") and ev.fill.exit_reason == "take_profit"
    assert ev.trade.pnl_usd == D("10.414725")  # +10.5 - 0.045 - 89.5 x 0.00045


@pytest.mark.unit
def test_F11_AC7_a_second_mark_does_not_create_a_second_exit_order(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    e.mark("SOL", "98", T)
    e.mark("SOL", "97", T + 200)
    e.flat_book("SOL", T + 1000, "97")
    e.flat_book("SOL", T + 1200, "96")
    events = e.advance(T + 2000)
    assert [ev.kind for ev in events] == ["fill"]
    assert len(e.fills()) == 2 and len(e.trades()) == 1


@pytest.mark.unit
def test_F11_AC7_once_the_share_is_closed_its_other_stops_are_inert(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    assert e.stop("tp", "sell", "1.0", "110", coid="tp1").accepted
    e.mark("SOL", "98", T)
    e.flat_book("SOL", T + 1000, "97")
    e.advance(T + 1000)
    assert e.mark("SOL", "111", T + 10_000) == []
    e.flat_book("SOL", T + 11_000, "111")
    assert e.advance(T + 11_000) == []
    assert len(e.fills()) == 2


@pytest.mark.unit
def test_F11_AC7_a_cancelled_stop_never_fires(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    assert e.broker.cancel_stop("stop1") is True
    assert e.broker.cancel_stop("stop1") is False
    e.mark("SOL", "50", T)
    e.flat_book("SOL", T + 1000, "50")
    assert e.advance(T + 1000) == []


@pytest.mark.unit
def test_F11_AC7_a_stop_on_a_position_that_does_not_exist_is_refused(new_env: NewEnv) -> None:
    e = new_env()
    assert e.stop("sl", "sell", "1.0", "99").reason == "exceeds_position"


@pytest.mark.unit
def test_F11_AC7_partial_depth_on_a_stop_exit_fills_what_it_can_and_retries_the_rest(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    e.mark("SOL", "98", T)
    # mid 97.05, floor 92.2: only 0.4 is available inside the band (the 80.0 level is outside it)
    e.book("SOL", T + 1000, [("97.0", "0.4"), ("80.0", "5")], [("97.1", "5")])
    e.book("SOL", T + 2000, [("96.0", "5")], [("96.1", "5")])
    (first,) = e.advance(T + 1000)
    assert first.kind == "partial_fill" and first.fill.qty == Qty("0.4") and first.fill.price == Price("97.0")
    assert first.trade is None and e.broker.position("SOL").qty == Qty("0.6")
    (second,) = e.advance(T + 2000)  # exits.retry_interval_s = 1 s
    assert second.fill.qty == Qty("0.6") and second.fill.price == Price("96.0")
    assert e.broker.position("SOL") is None
    (trade,) = e.trades()
    assert trade.pnl_usd == D("-3.68838")  # -1.2 - 2.4 gross; fees 0.045 + 0.01746 + 0.02592
    assert len(e.records("partial_fill")) == 1
