# mypy: disable-error-code="union-attr"
"""F11 round 4, Amendment 11: clamp, never ignore; broker time is only what ``advance_to`` says.

RISK-21 (a mark stamped ahead of the broker, by any amount, must never switch a stop, a liquidation or a delisting off),
RISK-17 (one +1 h mark on a coin never delays a stop or a close on another), RISK-22 (a chain of marks never walks the
broker's time), RISK-23 (an entry decided too far ahead is refused ``bad_decision_time``), RISK-19 (a far-future exit
decision is clamped), and the once-per-(source, coin) ``bad_timestamp`` alert (worded "clamped").
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.paper.types import BrokerEvent, MarkUpdate
from tests.paper.helpers import D0, HOUR_MS, Env, NewEnv, fresh_env, make_config

T = D0 + 10_000  # the broker's time in every test here (the time given to advance_to)
TOL = 5000  # filter.max_signal_age_ms in the fixture config
ACK = 1000
ALERT_AFTER = 10_000  # exits.alert_after_s in the fixture config, in ms

# (filter.max_signal_age_ms, how far the exchange stamps run ahead of the broker's time): the RISK-21 reproductions
SKEWS = [
    pytest.param(500, 700, id="tol500_skew700"),
    pytest.param(5000, 6000, id="tol5000_skew6s"),
    pytest.param(5000, 30 * 24 * HOUR_MS, id="tol5000_skew30d"),
]


def _mark(e: Env, coin: str, px: str, time_ms: int) -> list[BrokerEvent]:
    """A mark straight into the broker (``Env.mark`` would advance broker time to the mark's time first)."""
    return list(e.broker.on_mark(MarkUpdate(coin, Price(px), time_ms)))


def _long_with_stop(e: Env, *, trigger: str = "95") -> None:
    """5x SOL long of 1.0 at 100 (liquidation trigger 82.5, bankruptcy 80) with an SL, at broker time T."""
    e.open_position("buy", "1.0", px="100", leverage=5)
    e.advance(T)
    assert e.stop("sl", "sell", "1.0", trigger).accepted


def _alert_events(events: list[BrokerEvent]) -> list[BrokerEvent]:
    return [ev for ev in events if ev.kind == "exit_unfilled_alert"]


# ----------------------------------------------------------------- RISK-21: skew never switches protection off


@pytest.mark.unit
@pytest.mark.parametrize(("tol", "skew"), SKEWS)
def test_R4_RISK21_a_stop_loss_still_fires_and_fills_at_now_plus_ack_when_marks_run_ahead(
    new_env: NewEnv, tol: int, skew: int
) -> None:
    e = new_env(config=make_config(filter__max_signal_age_ms=tol))
    _long_with_stop(e)
    now = T + 1000
    e.advance(now)
    e.flat_book("SOL", now + ACK, "94")
    assert _mark(e, "SOL", "95", now + skew) == []  # the stop triggers: an exit is decided, no event yet
    assert list(e.broker._stops) == []  # noqa: SLF001 - the stop is spent, not dropped
    (event,) = [ev for ev in e.advance(now + ACK) if ev.kind == "fill"]
    assert event.fill.exit_reason == "stop_loss"
    assert event.fill.time.ms == now + ACK and event.fill.price == Price("94")  # now + ack, not skew + ack
    assert e.broker.position("SOL") is None
    (trade,) = e.trades()
    assert trade.flags == frozenset()  # closed by the stop, not liquidated


@pytest.mark.unit
@pytest.mark.parametrize(("tol", "skew"), SKEWS)
def test_R4_RISK21_a_liquidation_still_fires_when_marks_run_ahead(new_env: NewEnv, tol: int, skew: int) -> None:
    e = new_env(config=make_config(filter__max_signal_age_ms=tol))
    _long_with_stop(e)
    (event,) = _mark(e, "SOL", "80", T + skew)  # gaps through the stop and the liquidation price 82.5
    assert event.kind == "liquidated" and event.time_ms == T
    assert event.fill.time.ms == T and event.fill.price == Price("80")
    assert event.trade.closed_at.ms == T
    assert e.broker.position("SOL") is None


@pytest.mark.unit
@pytest.mark.parametrize(("tol", "skew"), SKEWS)
def test_R4_RISK21_a_one_shot_delisting_still_settles_and_strands_no_position(
    new_env: NewEnv, tol: int, skew: int
) -> None:
    e = new_env(config=make_config(filter__max_signal_age_ms=tol))
    _long_with_stop(e)
    (event,) = e.broker.on_delist("SOL", Price("90"), T + skew)
    assert event.kind == "delisted_force_settle" and event.time_ms == T
    assert event.fill.time.ms == T and event.fill.price == Price("90")
    assert e.broker.position("SOL") is None and list(e.broker._stops) == []  # noqa: SLF001
    assert e.trades()[0].flags == frozenset({"delisted_force_settle"})


@pytest.mark.unit
@pytest.mark.parametrize(("tol", "skew"), SKEWS[:2])
def test_R4_RISK21_chronic_skew_every_loop_the_supervisor_advances_then_feeds_ahead_marks(
    new_env: NewEnv, tol: int, skew: int
) -> None:
    """The reviewer's N1: advance_to(local clock) each loop, exchange marks stamped ``skew`` ahead, price falling. The
    protection must engage on the first mark that crosses the stop, never go quiet."""
    e = new_env(config=make_config(filter__max_signal_age_ms=tol))
    e.open_position("buy", "1", px="100", leverage=5)
    assert e.stop("sl", "sell", "1", "95").accepted
    fills: list[BrokerEvent] = []
    for step in range(2, 40):
        local = D0 + step * 1000
        fills += [ev for ev in e.advance(local) if ev.kind == "fill"]
        px = str(max(D(100) - D(step), D(40)))
        e.flat_book("SOL", local + ACK, px)
        _mark(e, "SOL", px, local + skew)
    fills += [ev for ev in e.advance(D0 + 60_000) if ev.kind == "fill"]
    assert e.broker.position("SOL") is None
    assert fills and fills[0].fill.exit_reason == "stop_loss"
    assert e.trades()[0].flags == frozenset()  # a stop-loss loss, not a full-margin liquidation
    assert e.broker.cash_usd() > D("290")  # 300 wallet: a ~6 USD stop loss, not the 20 USD margin


# ---------------------------------------------------------------- RISK-17 regression: coin A never delays coin B


@pytest.mark.unit
@pytest.mark.parametrize("bogus_coin", ["BTC", "ETH"])
def test_R4_RISK17_a_plus_one_hour_mark_on_coin_a_does_not_delay_a_stop_on_coin_b(
    new_env: NewEnv, bogus_coin: str
) -> None:
    e = new_env()
    _long_with_stop(e)
    _mark(e, bogus_coin, "60000", T + HOUR_MS)
    e.advance(T + 1000)
    e.flat_book("SOL", T + 1000 + ACK, "94")
    assert _mark(e, "SOL", "95", T + 1000) == []
    (event,) = [ev for ev in e.advance(T + 1000 + ACK) if ev.kind == "fill"]
    assert event.fill.exit_reason == "stop_loss" and event.fill.time.ms == T + 1000 + ACK
    assert e.trades()[0].flags == frozenset()
    assert e.broker.cash_usd() == D("293.9127")  # 300 - 0.045 - 6 - 94 x 0.00045


@pytest.mark.unit
@pytest.mark.parametrize("bogus_coin", ["BTC", "ETH"])
def test_R4_RISK17_a_plus_one_hour_mark_on_coin_a_does_not_delay_a_close_on_coin_b(
    new_env: NewEnv, bogus_coin: str
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    _mark(e, bogus_coin, "60000", T + HOUR_MS)
    e.flat_book("SOL", T + ACK, "101")
    assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=T, px="100")).accepted
    (event,) = e.advance(T + ACK)
    assert event.kind == "fill" and event.fill.time.ms == T + ACK and event.fill.price == Price("101")


# ------------------------------------------------------------------ RISK-22: marks never walk broker time forward


@pytest.mark.unit
@settings(max_examples=40, deadline=None)
@given(
    gaps=st.lists(st.integers(min_value=1, max_value=4900), min_size=1, max_size=60),
    coins=st.lists(st.sampled_from(["SOL", "BTC", "ETH"]), min_size=60, max_size=60),
    final_px=st.sampled_from(["94", "80"]),
)
def test_R4_RISK22_property_a_chain_of_marks_never_moves_broker_time_fill_times_or_stamps(
    gaps: list[int], coins: list[str], final_px: str
) -> None:
    """Marks each less than 4.9 s after the previous one (each 'plausible' on its own) never move broker time: a
    trigger fills at the advance_to time + ack, a liquidation is stamped with the advance_to time, and an entry
    decided at the advance_to time is still not stale."""
    with fresh_env() as e:
        _long_with_stop(e)
        stamp = T
        for gap, coin in zip(gaps, coins, strict=False):
            stamp += gap
            price = "96" if coin == "SOL" else "60000"  # the SOL stop (95) is not reached on the way
            assert _mark(e, coin, price, stamp) == []
        e.flat_book("SOL", T + ACK, "94")
        e.flat_book("BTC", T + ACK, "60000")
        events = _mark(e, "SOL", final_px, stamp + 1)
        if final_px == "80":  # liquidation: stamped with broker time
            (event,) = events
            assert event.kind == "liquidated" and event.time_ms == T and event.fill.time.ms == T
            assert e.fills()[-1].time.ms == T
        else:
            assert events == []
            probe = e.submit(e.order("buy", "0.001", coid="b1", coin="BTC", decided=T, px="60000", share="S2",
                                     trade="T2"))
            assert (probe.accepted, probe.reason) == (True, None)  # broker time is still T
            filled = [ev for ev in e.advance(T + ACK) if ev.kind == "fill"]
            stop_fill = next(ev for ev in filled if ev.fill.exit_reason == "stop_loss")
            assert stop_fill.fill.time.ms == T + ACK  # never later than advance_to time + ack
            assert all(ev.fill.time.ms == T + ACK for ev in filled)
        assert all(f.time.ms <= T + ACK for f in e.fills())


@pytest.mark.unit
def test_R4_RISK22_720_marks_4900_ms_apart_do_not_delay_the_stop_by_a_single_ms(new_env: NewEnv) -> None:
    """The reviewer's reproduction: 720 marks 4.9 s apart put broker time 3,530 s ahead under Amendment 10."""
    e = new_env()
    _long_with_stop(e)
    for k in range(1, 721):
        assert _mark(e, "BTC", "60000", T + 4900 * k) == []
    e.flat_book("SOL", T + ACK, "94")
    assert _mark(e, "SOL", "95", T + 4900 * 721) == []
    (event,) = [ev for ev in e.advance(T + ACK) if ev.kind == "fill"]
    assert event.fill.time.ms == T + ACK and event.fill.exit_reason == "stop_loss"


@pytest.mark.unit
def test_R4_on_mark_never_moves_broker_time_or_resolves_pending_orders(new_env: NewEnv) -> None:
    """Broker time changes only through advance_to: a mark stamped past a pending fill's time does not fill it."""
    e = new_env()
    e.advance(T)
    e.flat_book("SOL", T + ACK, "100")
    assert e.submit(e.order("buy", "1.0", decided=T)).accepted
    assert _mark(e, "BTC", "60000", T + 4000) == []  # within the tolerance and past the fill time T + ACK
    assert e.broker.position("SOL") is None and e.fills() == []
    stale = e.submit(e.order("buy", "0.5", coid="c2", decided=T, share="S2", trade="T2"))
    assert (stale.accepted, stale.reason) == (True, None)  # broker time is still T (a later time would be stale)
    (event, _second) = e.advance(T + ACK)
    assert event.kind == "fill" and event.fill.time.ms == T + ACK


@pytest.mark.unit
def test_R4_on_delist_never_moves_broker_time_or_resolves_pending_orders_on_other_coins(new_env: NewEnv) -> None:
    e = new_env()
    e.advance(T)
    e.flat_book("SOL", T + ACK, "100")
    assert e.submit(e.order("buy", "1.0", decided=T)).accepted
    assert list(e.broker.on_delist("BTC", Price("60000"), T + 4000)) == []  # nothing held on BTC
    assert e.broker.position("SOL") is None and e.fills() == []
    stale = e.submit(e.order("buy", "0.5", coid="c2", decided=T, share="S2", trade="T2"))
    assert (stale.accepted, stale.reason) == (True, None)


@pytest.mark.unit
def test_R4_a_mark_or_delisting_never_crosses_a_funding_boundary_for_the_broker(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.advance(T)
    e.funding.set("SOL", D0 - 600_000 + HOUR_MS, "0.0001", "100")
    _mark(e, "BTC", "60000", T + HOUR_MS)
    list(e.broker.on_delist("BTC", Price("60000"), T + HOUR_MS))
    assert e.records("paper_funding") == []
    e.advance(D0 - 600_000 + HOUR_MS)
    assert len(e.records("paper_funding")) == 1  # only advance_to accrues funding


@pytest.mark.unit
def test_R4_broker_time_is_the_max_of_the_advance_to_times(new_env: NewEnv) -> None:
    """``_now_ms = max(_now_ms, t)``: an earlier advance_to does not move time back."""
    e = new_env()
    e.advance(T)
    e.broker.advance_to(T - 5000)
    e.flat_book("SOL", T + ACK, "100")
    result = e.submit(e.order("buy", "1.0", decided=T - 1))
    assert (result.accepted, result.reason) == (False, "stale_decision")


# ------------------------------------------------------------------- clamped decision times, stamps, ledger


@pytest.mark.unit
def test_R4_a_stop_triggered_by_an_ahead_mark_is_decided_at_broker_time_and_alerted_from_it(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    mark_time = T + 3000  # ahead of broker time, within the tolerance
    assert _mark(e, "SOL", "95", mark_time) == []
    assert _alert_events(e.advance(T + ALERT_AFTER - 1)) == []
    (alert,) = _alert_events(e.advance(T + ALERT_AFTER))  # no book: the exit cannot fill; timed from min(mark, now)
    assert alert.time_ms == T + ALERT_AFTER


@pytest.mark.unit
def test_R4_a_stop_triggered_by_a_far_future_mark_is_decided_at_broker_time_and_alerted_from_it(
    new_env: NewEnv,
) -> None:
    e = new_env()
    _long_with_stop(e)
    assert _mark(e, "SOL", "95", T + HOUR_MS) == []
    (alert,) = _alert_events(e.advance(T + ALERT_AFTER))
    assert alert.time_ms == T + ALERT_AFTER


@pytest.mark.unit
def test_R4_the_stop_trigger_ledger_row_keeps_the_raw_mark_time(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    _mark(e, "SOL", "95", T + HOUR_MS)
    (row,) = e.records("paper_stop_trigger")
    assert row.payload["time_ms"] == T + HOUR_MS
    assert row.payload["client_order_id"] == "stop1"


@pytest.mark.unit
def test_R4_a_liquidation_by_an_ahead_mark_within_the_tolerance_is_stamped_with_broker_time(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    (event,) = _mark(e, "SOL", "80", T + 3000)
    assert event.kind == "liquidated" and event.time_ms == T == event.fill.time.ms == event.trade.closed_at.ms
    assert "bad_timestamp" not in e.alerts.kinds()  # within the tolerance: no alert


@pytest.mark.unit
def test_R4_a_delisting_within_the_tolerance_is_stamped_with_broker_time(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    (event,) = e.broker.on_delist("SOL", Price("90"), T + 3000)
    assert event.time_ms == T == event.fill.time.ms and "bad_timestamp" not in e.alerts.kinds()


@pytest.mark.unit
def test_R4_a_late_mark_or_delisting_is_stamped_with_broker_time_not_its_own(new_env: NewEnv) -> None:
    e = new_env()
    _long_with_stop(e)
    (event,) = _mark(e, "SOL", "80", T - 4000)
    assert event.kind == "liquidated" and event.time_ms == T
    e2 = new_env()
    _long_with_stop(e2)
    (settled,) = e2.broker.on_delist("SOL", Price("90"), T - 4000)
    assert settled.time_ms == T and settled.fill.time.ms == T


@pytest.mark.unit
@pytest.mark.parametrize("offset", [TOL + 1, HOUR_MS, 30 * 24 * HOUR_MS])
def test_R4_RISK19_a_far_future_exit_decision_is_clamped_accepted_and_fills_at_now_plus_ack(
    new_env: NewEnv, offset: int
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    e.flat_book("SOL", T + ACK, "101")
    result = e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=T + offset, px="100"))
    assert (result.accepted, result.reason) == (True, None)  # never refused, never waiting for the far future
    (event,) = e.advance(T + ACK)
    assert event.kind == "fill" and event.fill.time.ms == T + ACK and event.fill.price == Price("101")
    assert e.broker.position("SOL") is None
    assert e.alerts.kinds().count("bad_timestamp") == 1


@pytest.mark.unit
@pytest.mark.parametrize("offset", [TOL + 1, HOUR_MS, 30 * 24 * HOUR_MS])
def test_R4_RISK19_a_far_future_exit_decision_alerts_from_the_clamped_decision_time(
    new_env: NewEnv, offset: int
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=T + offset, px="100")).accepted
    assert _alert_events(e.advance(T + ALERT_AFTER - 1)) == []
    (alert,) = _alert_events(e.advance(T + ALERT_AFTER))  # no book: timed from min(decided, now) = T
    assert alert.time_ms == T + ALERT_AFTER and alert.client_order_id == "x1"
    assert e.alerts.kinds().count("exit_unfilled") == 1


@pytest.mark.unit
def test_R4_an_exit_decided_ahead_within_the_tolerance_is_clamped_to_broker_time_without_an_alert(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    e.flat_book("SOL", T + ACK, "101")
    assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=T + 2000, px="100")).accepted
    (event,) = e.advance(T + ACK)  # decided is clamped to T: fill at T + ack, not T + 2000 + ack
    assert event.fill.time.ms == T + ACK
    assert "bad_timestamp" not in e.alerts.kinds()


@pytest.mark.unit
def test_R4_an_exit_decided_in_the_past_still_fills_at_now_plus_ack_and_alerts_from_its_decision(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    decided = T - 30_000
    assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=decided, px="100")).accepted
    (alert,) = _alert_events(e.advance(T + 1))
    assert alert.time_ms == decided + ALERT_AFTER


# ------------------------------------------------------------------- the bad_timestamp alert (worded "clamped")


@pytest.mark.unit
def test_R4_bad_timestamp_alert_fires_once_per_source_and_coin(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    for k in range(5):
        _mark(e, "BTC", "60000", T + HOUR_MS + k)
    assert e.alerts.kinds().count("bad_timestamp") == 1
    _mark(e, "ETH", "3000", T + HOUR_MS)  # another coin: its own alert
    assert e.alerts.kinds().count("bad_timestamp") == 2
    e.broker.on_delist("BTC", Price("60000"), T + HOUR_MS)  # same coin, another source: its own alert
    e.broker.on_delist("BTC", Price("60000"), T + HOUR_MS + 1)
    assert e.alerts.kinds().count("bad_timestamp") == 3


@pytest.mark.unit
def test_R4_bad_timestamp_alert_is_worded_clamped_and_names_the_coin(new_env: NewEnv) -> None:
    e = new_env()
    e.advance(T)
    _mark(e, "BTC", "60000", T + HOUR_MS)
    (alert,) = [a for a in e.alerts.sent if a.kind == "bad_timestamp"]
    assert "clamped" in alert.message and "BTC" in alert.message
    assert "ignored" not in alert.message


@pytest.mark.unit
def test_R4_bad_timestamp_alert_is_cleared_when_a_timestamp_that_is_not_ahead_arrives(new_env: NewEnv) -> None:
    e = new_env()
    e.advance(T)
    _mark(e, "BTC", "60000", T + HOUR_MS)
    _mark(e, "BTC", "60000", T + HOUR_MS + 1)
    assert e.alerts.kinds().count("bad_timestamp") == 1
    _mark(e, "BTC", "60000", T + 100)  # not ahead: recovery
    _mark(e, "BTC", "60000", T + HOUR_MS)  # ahead again: alerts again
    assert e.alerts.kinds().count("bad_timestamp") == 2


@pytest.mark.unit
def test_R4_bad_timestamp_recovery_of_one_coin_does_not_clear_another(new_env: NewEnv) -> None:
    e = new_env()
    e.advance(T)
    _mark(e, "BTC", "60000", T + HOUR_MS)
    _mark(e, "ETH", "3000", T + HOUR_MS)
    _mark(e, "ETH", "3000", T)  # ETH recovers
    _mark(e, "BTC", "60000", T + HOUR_MS)  # BTC did not: still one alert for it
    assert e.alerts.kinds().count("bad_timestamp") == 2
    _mark(e, "ETH", "3000", T + HOUR_MS)  # ETH goes bad again
    assert e.alerts.kinds().count("bad_timestamp") == 3


@pytest.mark.unit
@pytest.mark.parametrize("tol", [500, 2000, 5000])
def test_R4_bad_timestamp_boundary_at_the_tolerance_no_alert_one_ms_more_alerts(new_env: NewEnv, tol: int) -> None:
    e = new_env(config=make_config(filter__max_signal_age_ms=tol))
    e.advance(T)
    _mark(e, "BTC", "60000", T + tol - 1)
    _mark(e, "BTC", "60000", T + tol)
    assert e.alerts.kinds().count("bad_timestamp") == 0
    _mark(e, "BTC", "60000", T + tol + 1)
    assert e.alerts.kinds().count("bad_timestamp") == 1


@pytest.mark.unit
def test_R4_bad_timestamp_none_while_broker_time_is_zero(new_env: NewEnv) -> None:
    """Before the first advance_to (startup) every external stamp is 'ahead'; that is not bad data (RISK-25)."""
    e = new_env()
    assert _mark(e, "BTC", "60000", D0 + HOUR_MS) == []
    assert list(e.broker.on_delist("XRP", Price("1"), D0 + HOUR_MS)) == []
    assert e.alerts.kinds() == []
    e.advance(T)  # the first advance: from now on the same stamp is ahead of broker time
    _mark(e, "BTC", "60000", T + HOUR_MS)
    assert e.alerts.kinds().count("bad_timestamp") == 1


@pytest.mark.unit
def test_R4_bad_timestamp_alert_sink_failure_does_not_latch_the_broker(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)

    def boom(_alert: object) -> None:
        raise RuntimeError("sink down")

    e.alerts.send = boom  # type: ignore[assignment]
    _mark(e, "BTC", "60000", T + HOUR_MS)  # must not raise or latch (Amendment 8: non-money dependency)
    assert e.broker.position("SOL").qty == D("1.0")
    e.flat_book("SOL", T + ACK, "100")
    assert e.submit(e.order("buy", "0.1", coid="a1", action=ActionKind.ADD, decided=T, share="S2", trade="T2")).accepted


# ------------------------------------------------------------------------- RISK-23: entry decided too far ahead


@pytest.mark.unit
@pytest.mark.parametrize("tol", [500, 2000, 5000])
@pytest.mark.parametrize("action", [ActionKind.OPEN, ActionKind.ADD])
def test_R4_RISK23_an_entry_more_than_the_tolerance_ahead_is_refused_bad_decision_time(
    new_env: NewEnv, tol: int, action: ActionKind
) -> None:
    e = new_env(config=make_config(filter__max_signal_age_ms=tol))
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    result = e.submit(e.order("buy", "0.5", coid="e1", action=action, decided=T + tol + 1, share="S2", trade="T2"))
    assert (result.accepted, result.reason) == (False, "bad_decision_time")
    assert [r.payload["reason"] for r in e.records("paper_reject")] == ["bad_decision_time"]
    e.flat_book("SOL", T + tol + 1 + ACK, "100")
    assert e.advance(T + tol + 1 + ACK) == []  # nothing was queued
    assert e.broker.position("SOL").qty == D("1.0")


@pytest.mark.unit
@pytest.mark.parametrize("tol", [500, 2000, 5000])
def test_R4_RISK23_an_entry_exactly_at_the_tolerance_ahead_is_accepted_inclusive_boundary(
    new_env: NewEnv, tol: int
) -> None:
    e = new_env(config=make_config(filter__max_signal_age_ms=tol))
    e.advance(T)
    e.flat_book("SOL", T + tol + ACK, "100")
    below = e.submit(e.order("buy", "0.5", coid="e0", decided=T + tol - 1, share="S0", trade="T0"))
    exact = e.submit(e.order("buy", "0.5", coid="e1", decided=T + tol, share="S1", trade="T1"))
    assert (below.accepted, below.reason) == (True, None)
    assert (exact.accepted, exact.reason) == (True, None)
    events = e.advance(T + tol + ACK)
    assert [ev.kind for ev in events] == ["fill", "fill"]
    assert e.fills()[-1].time.ms == T + tol + ACK  # an accepted entry fills at its decision time + ack


@pytest.mark.unit
@pytest.mark.parametrize("offset", [HOUR_MS, 30 * 24 * HOUR_MS])
def test_R4_RISK23_an_entry_far_ahead_is_refused_no_broker_time_while_broker_time_is_zero(
    new_env: NewEnv, offset: int
) -> None:
    """Round 5 (RISK-26) INVERTS this test, which used to assert the far-ahead entry was ACCEPTED at broker time 0
    (RISK-25 startup). Intent kept: an entry decided far ahead must never be silently accepted. With no broker time
    there is nothing to be ahead of, but also nothing to check staleness against, so the entry is refused
    ``no_broker_time`` until the first ``advance_to`` (an accepted one filled at a made-up time and price)."""
    e = new_env()
    e.flat_book("SOL", D0 + offset + ACK, "100")
    result = e.submit(e.order("buy", "0.5", coid="e1", decided=D0 + offset))
    assert (result.accepted, result.reason) == (False, "no_broker_time")


@pytest.mark.unit
def test_R4_RISK23_a_stale_entry_is_still_refused_stale_decision(new_env: NewEnv) -> None:
    e = new_env()
    e.advance(T)
    result = e.submit(e.order("buy", "0.5", coid="e1", decided=T - 1))
    assert (result.accepted, result.reason) == (False, "stale_decision")


@pytest.mark.unit
def test_R4_RISK23_the_refusal_needs_advance_to_not_a_mark(new_env: NewEnv) -> None:
    """A mark stamped ahead does not make a later entry 'within the tolerance': time moves only through advance_to."""
    e = new_env()
    e.advance(T)
    _mark(e, "BTC", "60000", T + 4000)
    result = e.submit(e.order("buy", "0.5", coid="e1", decided=T + TOL + 1))
    assert (result.accepted, result.reason) == (False, "bad_decision_time")
    e.advance(T + 4000)
    e.flat_book("SOL", T + TOL + 1 + ACK, "100")
    again = e.submit(e.order("buy", "0.5", coid="e2", decided=T + TOL + 1))
    assert (again.accepted, again.reason) == (True, None)
