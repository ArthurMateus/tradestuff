# mypy: disable-error-code="union-attr"
"""F11 round 3, Amendment 10 (RISK-17, RISK-19): one bad timestamp never moves the broker's time.

The broker's trusted time is the time given to ``advance_to``. A mark, a delisting or an exit stamped more than
``filter.max_signal_age_ms`` ahead of it is bad data: ignored with an error log and an alert, it never advances the
broker's time and never delays an exit or a stop, on any coin (held or not). A mark within the tolerance advances time
normally; a mark that is merely late never blocks an exit. The ``exit_unfilled`` alert is timed from the exit's own
decision time (a stop trigger: the mark's own time) plus ``exits.alert_after_s``, never from a clamped time.

Pinned readings (the developer may not need to ask): a delisting stamped too far ahead is ignored, it is not
settled at the trusted time (returns no events, does not raise); a far-future exit decided_at_ms is either refused at
once or filled at the normal time, or at least alerted within the alert window: it never waits silently.
"""

from __future__ import annotations

import logging
from decimal import Decimal as D

import pytest
from tests.paper.helpers import BASE, D0, HOUR_MS, Env, NewEnv, make_config

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.paper.types import BrokerEvent, MarkUpdate

T = D0 + 10_000  # the broker's trusted time in every test here (the time given to advance_to)
TOL = 5000  # filter.max_signal_age_ms in the fixture config
ACK = 1000
ALERT_AFTER = 10_000  # exits.alert_after_s in the fixture config, in ms

BOGUS_OFFSETS = [
    pytest.param(TOL + 1, id="one_ms_beyond_tolerance"),
    pytest.param(HOUR_MS, id="one_hour_ahead"),
    pytest.param(30 * 24 * HOUR_MS, id="thirty_days_ahead"),
]


def _long_with_stop(e: Env, *, trigger: str = "95") -> None:
    """5x SOL long of 1.0 at 100 (liquidation trigger 82.5, bankruptcy 80) with an SL, at broker time T."""
    e.open_position("buy", "1.0", px="100", leverage=5)
    e.advance(T)
    assert e.stop("sl", "sell", "1.0", trigger).accepted


def _bogus_mark(e: Env, coin: str, px: str, time_ms: int) -> list[BrokerEvent]:
    """A mark straight into the broker (the helper ``Env.mark`` would also move the fake local clock)."""
    return list(e.broker.on_mark(MarkUpdate(coin, Price(px), time_ms)))


def _kinds(events: list[BrokerEvent]) -> list[str]:
    return [ev.kind for ev in events]


# --------------------------------------------------------------------------- the reviewer's repro, and more


@pytest.mark.unit
@pytest.mark.parametrize("offset", BOGUS_OFFSETS)
@pytest.mark.parametrize("bogus_coin", ["BTC", "ETH"], ids=["btc_not_held", "eth_not_held"])
def test_R3_RISK17_a_bogus_future_mark_on_another_coin_does_not_delay_the_stop_loss(
    new_env: NewEnv, offset: int, bogus_coin: str
) -> None:
    e = new_env()
    _long_with_stop(e)
    assert _bogus_mark(e, bogus_coin, "60000", T + offset) == []
    e.flat_book("SOL", T + 2000, "94")
    assert _kinds(e.mark("SOL", "95", T + 1000)) == []  # the stop triggers: the exit is decided at T + 1000
    events = e.advance(T + 2000)
    (fill_event,) = events
    assert fill_event.kind == "fill"
    assert fill_event.fill.exit_reason == "stop_loss"
    assert fill_event.fill.time.ms == T + 2000  # the normal time, not the bogus one
    assert fill_event.fill.price == Price("94")
    assert e.broker.position("SOL") is None
    (trade,) = e.trades()
    assert trade.flags == frozenset()  # closed by the stop, not liquidated
    assert e.broker.cash_usd() == D("293.9127")  # 300 - 0.045 - 6 - 94 x 0.00045


@pytest.mark.unit
@pytest.mark.parametrize("offset", BOGUS_OFFSETS)
def test_R3_RISK17_the_liquidation_is_not_stamped_with_a_bogus_future_time(new_env: NewEnv, offset: int) -> None:
    e = new_env()
    _long_with_stop(e)
    assert _bogus_mark(e, "BTC", "60000", T + offset) == []
    events = e.mark("SOL", "80", T + 1000)  # gaps through the stop and the liquidation price 82.5
    (event,) = events
    assert event.kind == "liquidated" and event.time_ms == T + 1000
    assert event.fill.time.ms == T + 1000 and event.fill.price == Price("80")
    assert event.trade.closed_at.ms == T + 1000
    assert e.fills()[-1].time.ms == T + 1000


@pytest.mark.unit
@pytest.mark.parametrize("offset", BOGUS_OFFSETS)
def test_R3_RISK17_a_close_decided_at_the_normal_time_still_fills_after_a_bogus_mark(
    new_env: NewEnv, offset: int
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    assert _bogus_mark(e, "BTC", "60000", T + offset) == []
    e.flat_book("SOL", T + 2000, "101")
    result = e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=T + 1000, px="100"))
    assert result.accepted
    (event,) = e.advance(T + 2000)
    assert event.kind == "fill" and event.fill.time.ms == T + 2000 and event.fill.price == Price("101")


@pytest.mark.unit
@pytest.mark.parametrize("offset", BOGUS_OFFSETS)
def test_R3_RISK17_a_bogus_mark_on_the_held_coin_is_ignored_even_at_a_liquidating_price(
    new_env: NewEnv, offset: int
) -> None:
    e = new_env()
    _long_with_stop(e)
    assert _bogus_mark(e, "SOL", "50", T + offset) == []  # would trigger the stop AND liquidate, if believed
    assert e.broker.position("SOL").qty == D("1.0")
    assert len(e.fills()) == 1  # only the entry
    assert list(e.broker._stops) == ["stop1"]  # noqa: SLF001 - the stop is still registered: nothing was triggered
    e.flat_book("SOL", T + 2000, "94")
    e.mark("SOL", "95", T + 1000)
    (event,) = e.advance(T + 2000)
    assert event.fill.exit_reason == "stop_loss" and event.fill.time.ms == T + 2000


@pytest.mark.unit
@pytest.mark.parametrize("offset", BOGUS_OFFSETS)
@pytest.mark.parametrize("coin", ["BTC", "SOL"])
def test_R3_RISK17_a_bogus_mark_does_not_advance_the_broker_time(new_env: NewEnv, offset: int, coin: str) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    _bogus_mark(e, coin, "100", T + offset)
    e.flat_book("SOL", T + 1000, "100")
    # decided at the trusted time T: refused ``stale_decision`` if the bogus mark had moved the broker's time
    result = e.submit(e.order("buy", "0.5", coid="add1", action=ActionKind.ADD, decided=T, share="S2", trade="T2"))
    assert (result.accepted, result.reason) == (True, None)


@pytest.mark.unit
def test_R3_RISK17_a_bogus_mark_does_not_crawl_the_funding_clock_over_an_hour_boundary(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.advance(T)
    b1 = BASE + HOUR_MS
    e.funding.set("SOL", b1, "0.0001", "100")
    _bogus_mark(e, "BTC", "60000", T + HOUR_MS)  # its stamp is past the boundary b1
    assert e.records("paper_funding") == []
    assert e.broker.cash_usd() == D("299.91")
    assert "funding_missing" not in e.alerts.kinds()


@pytest.mark.unit
@pytest.mark.parametrize("tol", [500, 2000, 5000])
def test_R3_RISK17_the_tolerance_is_filter_max_signal_age_ms_exactly(new_env: NewEnv, tol: int) -> None:
    """At the tolerance the mark advances the broker's time; one ms more and it is ignored."""
    accepted = new_env(config=make_config(filter__max_signal_age_ms=tol))
    accepted.open_position("buy", "1.0", px="100")
    accepted.advance(T)
    _bogus_mark(accepted, "BTC", "60000", T + tol)
    accepted.flat_book("SOL", T + tol + 1000, "100")
    early = accepted.submit(accepted.order("buy", "0.5", coid="e1", action=ActionKind.ADD, decided=T + tol - 1,
                                           share="S2", trade="T2"))
    assert (early.accepted, early.reason) == (False, "stale_decision")  # the mark did advance time to T + tol
    on_time = accepted.submit(accepted.order("buy", "0.5", coid="e2", action=ActionKind.ADD, decided=T + tol,
                                             share="S2", trade="T2"))
    assert on_time.accepted

    ignored = new_env(config=make_config(filter__max_signal_age_ms=tol))
    ignored.open_position("buy", "1.0", px="100")
    ignored.advance(T)
    _bogus_mark(ignored, "BTC", "60000", T + tol + 1)
    ignored.flat_book("SOL", T + 1000, "100")
    result = ignored.submit(ignored.order("buy", "0.5", coid="e3", action=ActionKind.ADD, decided=T, share="S2",
                                          trade="T2"))
    assert (result.accepted, result.reason) == (True, None)  # the mark did not advance time


@pytest.mark.unit
def test_R3_RISK17_a_mark_within_the_tolerance_still_triggers_the_stop_at_its_own_time(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    e.flat_book("SOL", T + TOL + ACK, "94")
    assert e.mark("SOL", "95", T + TOL) == []
    (event,) = e.advance(T + TOL + ACK)
    assert event.fill.time.ms == T + TOL + ACK and event.fill.exit_reason == "stop_loss"


@pytest.mark.unit
def test_R3_RISK17_a_mark_that_is_merely_late_never_blocks_an_exit(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    e.flat_book("SOL", T + ACK, "94")
    late = T - HOUR_MS  # an hour old: still a price, and the stop is still hit
    assert _bogus_mark(e, "SOL", "95", late) == []
    (event,) = [ev for ev in e.advance(T + ACK) if ev.kind == "fill"]  # (an alert timed from the mark may also come)
    assert event.fill.exit_reason == "stop_loss" and event.fill.time.ms == T + ACK


@pytest.mark.unit
def test_R3_RISK17_an_exit_with_a_very_old_decision_time_fills_at_the_broker_time(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    e.flat_book("SOL", T + ACK, "99")
    assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=T - HOUR_MS, px="100")).accepted
    (event,) = [ev for ev in e.advance(T + ACK) if ev.kind == "fill"]  # (an alert timed from the decision may come)
    assert event.fill.time.ms == T + ACK


# ---------------------------------------------------------------------------------------- delisting


@pytest.mark.unit
@pytest.mark.parametrize("offset", BOGUS_OFFSETS)
def test_R3_RISK17_a_bogus_future_delisting_is_ignored_and_does_not_move_time(new_env: NewEnv, offset: int) -> None:
    e = new_env()
    _long_with_stop(e)
    assert list(e.broker.on_delist("SOL", Price("90"), T + offset)) == []
    assert e.broker.position("SOL").qty == D("1.0")
    assert len(e.fills()) == 1 and e.records("paper_funding") == []
    e.flat_book("SOL", T + 1000, "100")
    result = e.submit(e.order("buy", "0.5", coid="add1", action=ActionKind.ADD, decided=T, share="S2", trade="T2"))
    assert (result.accepted, result.reason) == (True, None)  # not stale, not delisted, time not moved


@pytest.mark.unit
def test_R3_RISK17_a_delisting_within_the_tolerance_settles_at_its_own_time(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    (event,) = e.broker.on_delist("SOL", Price("90"), T + TOL)
    assert event.kind == "delisted_force_settle" and event.fill.time.ms == T + TOL and event.fill.price == Price("90")


# --------------------------------------------------------------------------- error log and alert path


@pytest.mark.unit
def test_R3_RISK17_a_bogus_mark_is_logged_as_an_error_and_alerted(
    new_env: NewEnv, caplog: pytest.LogCaptureFixture
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        _bogus_mark(e, "BTC", "60000", T + HOUR_MS)
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    assert len(e.alerts.sent) >= 1
    assert "exit_unfilled" not in e.alerts.kinds()
    assert e.broker.position("SOL").qty == D("1.0")  # and the broker is not latched: it still works
    e.mark("SOL", "99", T + 1000)


@pytest.mark.unit
def test_R3_RISK17_a_bogus_delisting_is_logged_as_an_error_and_alerted(
    new_env: NewEnv, caplog: pytest.LogCaptureFixture
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        e.broker.on_delist("SOL", Price("90"), T + HOUR_MS)
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    assert len(e.alerts.sent) >= 1
    assert "delisted_force_settle" not in e.alerts.kinds()


# ------------------------------------------------------------------------------ the exit_unfilled alert


def _alert_events(events: list[BrokerEvent]) -> list[BrokerEvent]:
    return [ev for ev in events if ev.kind == "exit_unfilled_alert"]


@pytest.mark.unit
def test_R3_RISK17_the_alert_is_timed_from_the_exits_own_decision_time_not_from_the_broker_time(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    decided = T - 30_000  # an old decision: its fill time is clamped to T, its alert is not
    assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=decided, px="100")).accepted
    events = e.advance(T + 1)  # no book at all: the exit cannot fill
    (alert,) = _alert_events(events)
    assert alert.time_ms == decided + ALERT_AFTER and alert.client_order_id == "x1"
    assert e.alerts.kinds().count("exit_unfilled") == 1


@pytest.mark.unit
def test_R3_RISK17_the_alert_of_an_exit_decided_in_the_future_within_tolerance_is_not_early_or_late(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    decided = T + 2000
    assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=decided, px="100")).accepted
    assert _alert_events(e.advance(decided + ALERT_AFTER - 1)) == []
    (alert,) = _alert_events(e.advance(decided + ALERT_AFTER))
    assert alert.time_ms == decided + ALERT_AFTER


@pytest.mark.unit
def test_R3_RISK17_the_alert_of_a_stop_trigger_is_timed_from_the_marks_own_time(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    mark_time = T - 20_000  # late: the fill time is clamped to T, the alert is timed from the mark
    assert _bogus_mark(e, "SOL", "95", mark_time) == []  # a stop trigger decides an exit, it returns no event
    events = e.advance(T + 1)  # no book: the stop-triggered exit cannot fill
    (alert,) = _alert_events(events)
    assert alert.time_ms == mark_time + ALERT_AFTER


@pytest.mark.unit
def test_R3_RISK17_the_alert_of_a_stop_trigger_within_the_tolerance_is_timed_from_the_mark(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    mark_time = T + 3000
    assert _bogus_mark(e, "SOL", "95", mark_time) == []
    assert _alert_events(e.advance(mark_time + ALERT_AFTER - 1)) == []
    (alert,) = _alert_events(e.advance(mark_time + ALERT_AFTER))
    assert alert.time_ms == mark_time + ALERT_AFTER


@pytest.mark.unit
def test_R3_RISK17_a_bogus_mark_never_makes_the_alert_of_a_stop_exit_late(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    _bogus_mark(e, "BTC", "60000", T + HOUR_MS)
    mark_time = T + 1000
    assert _bogus_mark(e, "SOL", "95", mark_time) == []
    events = e.advance(mark_time + ALERT_AFTER)
    (alert,) = _alert_events(events)
    assert alert.time_ms == mark_time + ALERT_AFTER
    assert e.alerts.kinds().count("exit_unfilled") == 1


# ------------------------------------------------------------------- RISK-19: a far-future exit decision


@pytest.mark.unit
@pytest.mark.parametrize("offset", [TOL + 1, HOUR_MS, 30 * 24 * HOUR_MS], ids=["just_beyond", "one_hour", "thirty_days"])
def test_R3_RISK19_a_far_future_exit_decision_does_not_wait_silently(new_env: NewEnv, offset: int) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    for at in range(T + 1000, T + 20_001, 1000):
        e.flat_book("SOL", at, "100")
    result = e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=T + offset, px="100"))
    if not result.accepted:  # refused at once as bad data: not silent, not waiting
        assert result.reason
        return
    events = e.advance(T + 20_000)
    filled = [ev for ev in events if ev.kind == "fill"]
    alerted = "exit_unfilled" in e.alerts.kinds()
    assert filled or alerted, "an exit stamped in the far future must fill at the normal time, be refused, or alert"
    if filled:
        assert filled[0].fill.time.ms <= T + 20_000 and e.broker.position("SOL") is None
