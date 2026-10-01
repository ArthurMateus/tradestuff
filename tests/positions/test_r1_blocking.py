"""F12 review round 1, blocking code findings RISK-31..34 (P1..P5) and the TTL rule. Real gate, broker, ledger and
manager; only the exchange clock, books, candles and the leader's exchange state are faked. Each test says whether it
fails on the round-1 code (red) or pins a guard that already exists (guard) and which mutant it kills."""

from __future__ import annotations

from decimal import Decimal as D
from typing import Any

import pytest

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.domain import ActionKind
from tests.positions.conftest import NewRig
from tests.positions.helpers import MIN, SEC, WALLET_A, make_signal

MAX_AGE = 5_000  # filter.max_signal_age_ms in the fixture config


def acts(rig: Any) -> list[str]:
    """Every order the broker accepted, by action, in order."""
    return [o["action"] for o in rig.orders()]


def skips(rig: Any) -> dict[str, str]:
    """signal_id -> reason of every ``signal_skip`` record (last one wins)."""
    return {s["signal_id"]: s["reason"] for s in rig.records("signal_skip")}


def flip_signals(*, ts: int, tid: int = 2, size: str = "5", new_size: str = "3") -> tuple[Any, Any]:
    """The leader flips long -> short: the close leg of the long and the open leg of the short."""
    return (
        make_signal(tid, ActionKind.CLOSE, size=size, from_flip=True, ts=ts),
        make_signal(tid, ActionKind.OPEN, is_long=False, size=new_size, leg=1, from_flip=True, ts=ts),
    )


def books(rig: Any, coin: str, px: str, start: int, stop: int, every: int = 500) -> None:
    for t in range(start, stop + 1, every):
        rig.book_at(coin, px, t)


def ticking_clock(rig: Any, start_ms: int, step_ms: int) -> dict[str, int]:
    """A real clock: every read of the exchange time moves on by ``step_ms`` (the external boundary, scripted)."""
    state = {"t": start_ms}

    def exchange_now() -> Timestamp:
        t = state["t"]
        state["t"] += step_ms
        return Timestamp(ms=t, source=TimeSource.DERIVED)

    rig.xtime.exchange_now = exchange_now
    return state


def freeze_clock(rig: Any, at_ms: int) -> None:
    """Back to a fixed clock at ``at_ms`` (also moves the broker-facing fake clocks)."""
    rig.xtime.exchange_now = lambda: Timestamp(ms=at_ms, source=TimeSource.DERIVED)
    rig.xtime.now = at_ms
    rig.env.clock.now = at_ms


# ================================================================================================ RISK-31 / P1, P5


@pytest.mark.parametrize("close_fill_after_ms", [6_000, 30 * MIN])
def test_F12_R1_P1_flip_open_leg_older_than_the_signal_ttl_is_skipped_stale_not_fired(
    new_rig: NewRig, close_fill_after_ms: int
) -> None:
    """RED. Our close needs a long time to fill (no book); when it finally fills, the open leg is stale."""
    rig = new_rig()
    share = rig.open_share(1)
    now = rig.xtime.now
    close_leg, open_leg = flip_signals(ts=now - 100)
    rig.feed(close_leg, open_leg)  # no book: the close stays pending
    rig.step(now + SEC)
    assert acts(rig) == ["open", "close"]
    t = now + close_fill_after_ms
    rig.book_at("SOL", "100", t)
    rig.book_at("SOL", "100", t + SEC)  # a book for the new entry, so only the age check can stop it
    rig.step(t)
    rig.step(t + SEC)
    assert rig.book.state(share.share_id).status == "closed"  # the close leg is an exit: it still executes
    assert acts(rig) == ["open", "close"], "a stale flip leg must never open"
    assert rig.share_of(WALLET_A, "SOL") is None and rig.env.broker.position("SOL") is None
    assert skips(rig)[open_leg.signal_id] == "stale_signal"


def test_F12_R1_P1_leader_closing_the_flipped_short_cancels_the_waiting_open_leg(new_rig: NewRig) -> None:
    """RED. Within the TTL (so only the 'later leader signal' rule can stop it): the leader flipped, then closed the
    short 2 s later; our close fills afterwards; no short may be opened."""
    rig = new_rig()
    share = rig.open_share(1)
    now = rig.xtime.now
    close_leg, open_leg = flip_signals(ts=now - 100)
    rig.feed(close_leg, open_leg)
    rig.step(now + 2 * SEC)
    rig.feed(make_signal(3, ActionKind.CLOSE, is_long=False, size="3", pre="3", ts=now + 2 * SEC - 100))
    books(rig, "SOL", "100", now + 3 * SEC, now + 9 * SEC)
    rig.step(now + 3 * SEC)  # the close fills here (age of the open leg 3.1 s < 5 s)
    rig.step(now + 4 * SEC)
    assert rig.book.state(share.share_id).status == "closed"
    assert acts(rig) == ["open", "close"]
    assert rig.share_of(WALLET_A, "SOL") is None and rig.env.broker.position("SOL") is None


def _pending_entry_with_flip_leg(rig: Any, *, leader_closes_short: bool) -> int:
    """Our long entry is pending (no book: it will be rejected at now+6001); the leader flips and may close the short.
    Returns ``now``. The flip's signal times lie 3 s ahead, so the leg is still inside the TTL when the rejection lands."""
    now = rig.xtime.now
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    close_leg, open_leg = flip_signals(ts=now + 3 * SEC)
    rig.feed(close_leg, open_leg)
    if leader_closes_short:
        rig.feed(make_signal(3, ActionKind.CLOSE, is_long=False, size="3", pre="3", ts=now + 3 * SEC))
    return int(now)


def _later_long_opens_and_is_closed_by_the_leader(rig: Any, t: int) -> None:
    """2 s after t the leader opens a new long (we copy it) and 2 s later closes it."""
    rig.leader_state.positions[WALLET_A] = {"SOL": "5"}
    books(rig, "SOL", "100", t + SEC, t + 8 * SEC)
    rig.at(t)
    rig.feed(make_signal(4, ActionKind.OPEN, size="5", ts=t - 100))
    rig.step(t + SEC)
    assert rig.share_of(WALLET_A, "SOL") is not None, "the later long did not open: the test setup is wrong"
    rig.feed(make_signal(5, ActionKind.CLOSE, size="5", ts=t + SEC - 100))
    rig.step(t + 2 * SEC)
    rig.step(t + 3 * SEC)


@pytest.mark.parametrize("leader_closes_short", [True, False])
def test_F12_R1_P5_a_rejected_entrys_flip_leg_never_fires_when_a_later_unrelated_share_closes(
    new_rig: NewRig, leader_closes_short: bool
) -> None:
    """RED. Rejected entry, flip, (short closed). A new long opens and closes later: no orphan SHORT may appear."""
    rig = new_rig()
    now = _pending_entry_with_flip_leg(rig, leader_closes_short=leader_closes_short)
    rig.step(now + 6_001)  # the entry is rejected (no book at its fill): the pending share and its flip are dead
    assert rig.share_of(WALLET_A, "SOL") is None
    _later_long_opens_and_is_closed_by_the_leader(rig, now + 7 * SEC)
    assert acts(rig) == ["open", "open", "close"], "an orphan flip leg opened a position"
    assert rig.env.broker.position("SOL") is None
    assert all(s.is_long for s in rig.book.states())


def test_F12_R1_P5_a_ghost_dropped_entrys_flip_leg_never_fires(new_rig: NewRig) -> None:
    """RED. The rejection event is lost (the broker is advanced behind the manager's back); reconcile drops the ghost
    share; its flip leg must die with it."""
    rig = new_rig()
    now = _pending_entry_with_flip_leg(rig, leader_closes_short=False)
    rig.at(now + 6_001)
    rig.env.advance(now + 6_001)  # the rejection reaches the broker only
    rig.leader_state.positions[WALLET_A] = {}
    rig.mgr.reconcile()
    assert "ghost_share_dropped" in [e["event"] for e in rig.share_events()]
    _later_long_opens_and_is_closed_by_the_leader(rig, now + 7 * SEC)
    assert acts(rig) == ["open", "open", "close"]
    assert rig.env.broker.position("SOL") is None


def test_F12_R1_P5_a_later_leader_signal_on_the_coin_cancels_a_waiting_flip_leg(new_rig: NewRig) -> None:
    """RED. A close in flight (no book), the flip's open leg waits; the leader then REDUCES the new short (any later
    signal of that leader on the coin); when our close fills the leg must not open."""
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    close_leg, open_leg = flip_signals(ts=now - 100)
    rig.feed(close_leg, open_leg)
    rig.step(now + SEC)
    rig.feed(
        make_signal(
            3, ActionKind.REDUCE, is_long=False, size="1", pre="3", post="2", fraction="0.3333", ts=now + SEC - 100
        )
    )
    books(rig, "SOL", "100", now + 2 * SEC, now + 9 * SEC)
    rig.step(now + 2 * SEC)
    rig.step(now + 3 * SEC)
    assert "open" not in acts(rig)[1:]
    assert rig.share_of(WALLET_A, "SOL") is None


def test_F12_R1_P5_flip_leg_within_the_ttl_still_fires_after_the_close_fills(new_rig: NewRig) -> None:
    """GUARD (kills a mutant that discards every leg): the normal flip still opens the new side."""
    rig = new_rig()
    share = rig.open_share(1)
    now = rig.xtime.now
    close_leg, open_leg = flip_signals(ts=now - 100)
    rig.feed(close_leg, open_leg)
    rig.step(now + SEC)
    books(rig, "SOL", "100", now + 2 * SEC, now + 9 * SEC)
    rig.step(now + 2 * SEC)
    rig.step(now + 3 * SEC)
    assert rig.book.state(share.share_id).status == "closed"
    new = rig.share_of(WALLET_A, "SOL")
    assert new is not None and new.is_long is False and new.status == "open"


# ====================================================================================== the TTL in the entry paths


@pytest.mark.parametrize(("age_ms", "opens"), [(MAX_AGE - 1, True), (MAX_AGE, True), (MAX_AGE + 1, False)])
def test_F12_R1_TTL_an_open_older_than_the_signal_age_limit_is_skipped_stale_signal(
    new_rig: NewRig, age_ms: int, opens: bool
) -> None:
    """age = exchange now - signal time. At the limit it still opens (RED only for the one-over case)."""
    rig = new_rig()
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + SEC)
    sig = make_signal(1, ActionKind.OPEN, size="5", ts=now - age_ms)
    rig.feed(sig)
    rig.step(now + SEC)
    if opens:
        assert acts(rig) == ["open"] and rig.share_of(WALLET_A, "SOL") is not None
    else:
        assert acts(rig) == [] and rig.share_of(WALLET_A, "SOL") is None
        assert skips(rig)[sig.signal_id] == "stale_signal"


def test_F12_R1_TTL_a_deferred_add_replayed_after_the_age_limit_is_skipped_but_a_deferred_close_is_not(
    new_rig: NewRig,
) -> None:
    """RED for the add (stale_signal, no order). GUARD for the close: an exit is never refused for its age (A2/F10.AC7)."""
    rig = new_rig()
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + SEC)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    add = make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 4_800)  # age 4.8 s now
    close = make_signal(3, ActionKind.CLOSE, size="7.5", ts=now - 4_800)
    rig.feed(add, close)  # the entry is pending: both wait
    books(rig, "SOL", "100", now + 2 * SEC, now + 9 * SEC)
    rig.step(now + SEC)  # the entry fills: replay at an age of 5.8 s
    rig.step(now + 2 * SEC)
    assert "add" not in acts(rig)
    assert skips(rig)[add.signal_id] == "stale_signal"
    assert acts(rig) == ["open", "close"]  # the old close is still mirrored
    assert rig.share_of(WALLET_A, "SOL") is None or rig.share_of(WALLET_A, "SOL").status == "open"


def test_F12_R1_TTL_a_live_add_older_than_the_limit_is_skipped_stale_signal(new_rig: NewRig) -> None:
    """RED."""
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    add = make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - MAX_AGE - 1)
    rig.feed(add)
    assert acts(rig) == ["open"] and skips(rig)[add.signal_id] == "stale_signal"


# ============================================================================================ RISK-32 / P3


@pytest.mark.parametrize("lead_ms", range(0, 1_000, 100))
def test_F12_R1_P3_leader_close_while_our_take_profit_fills_is_never_refused_and_forgotten(
    new_rig: NewRig, lead_ms: int
) -> None:
    """RED for lead 100 and 200 ms (the clock crosses the TP fill between the manager's read of the pending exits and
    the gate's own advance); the other offsets are guards that the normal path works. The clock ticks like a real one."""
    rig = new_rig(exits__trail_start_r=D("5"))
    share = rig.open_share(1)
    now = rig.xtime.now
    books(rig, "SOL", "103", now + 500, now + 6 * SEC)
    rig.mark("SOL", "103")  # the TP (0.50) triggers and fills at now + 1 s
    clock = ticking_clock(rig, now + SEC - lead_ms, 100)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now + 900))
    after = clock["t"]
    freeze_clock(rig, after)
    # the book never lags the broker (every fill the gate produced is booked before the call returns)
    held = rig.env.broker.position("SOL")
    booked = rig.book.state(share.share_id)
    assert held is not None
    assert booked.qty == held.share_qtys[0], "the share book is behind a fill the broker already made"
    # the leader's exit is on its way: within one ack (plus the book cadence) nothing of the share is left
    rig.step(after + 1_500)
    assert rig.book.state(share.share_id).status == "closed", "the rest of the share was left open"
    assert rig.env.broker.position("SOL") is None
    assert rig.active_stops() == []


def test_F12_R1_P3_a_refused_close_of_an_open_share_is_retried_with_a_distinct_id(new_rig: NewRig) -> None:
    """RED (lead 100 ms case): after the share_closed refusal the manager retries once and the retry carries its own id."""
    rig = new_rig(exits__trail_start_r=D("5"))
    rig.open_share(1)
    now = rig.xtime.now
    books(rig, "SOL", "103", now + 500, now + 6 * SEC)
    rig.mark("SOL", "103")
    clock = ticking_clock(rig, now + SEC - 100, 100)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now + 900))
    freeze_clock(rig, clock["t"])
    closes = [d for d in rig.decisions() if d.get("action") == "close"]
    assert closes and closes[-1]["approved"] is True, "the last close decision is a refusal: nothing retried it"
    assert len({d["client_order_id"] for d in closes}) == len(closes)


# ============================================================================================ RISK-33 / P2


def _lost_entry_fill(rig: Any, *, signals_after: tuple[Any, ...] = ()) -> int:
    """Our entry fills at the broker, but the manager never sees the event (the broker is advanced behind its back)."""
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + SEC)
    rig.leader_state.positions[WALLET_A] = {"SOL": "5"}
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    rig.at(now + SEC)
    rig.env.advance(now + SEC)
    held = rig.held("SOL")
    assert held.share_qtys == (D("1.00"),)
    assert rig.share_of(WALLET_A, "SOL").status == "pending_entry"
    if signals_after:
        rig.feed(*signals_after)
    return int(now)


def test_F12_R1_P2_reconcile_heals_a_pending_share_the_broker_holds_as_open_with_protection(new_rig: NewRig) -> None:
    """RED."""
    rig = new_rig(exits__tp_enabled=False)
    _lost_entry_fill(rig)
    rig.mgr.reconcile()
    share = rig.share_of(WALLET_A, "SOL")
    assert share is not None and share.status == "open"
    assert (share.qty, share.entry_px) == (D("1.00"), D("100"))
    assert share.current_stop_px == D("98.5") and share.open_risk_usd == D("1.50")
    (stop,) = rig.active_stops(share.share_id)
    assert (stop["kind"], D(str(stop["qty"])), D(str(stop["trigger_px"]))) == ("sl", D("1.00"), D("98.5"))
    assert [s.share_id for s in rig.book.open_shares()] == [share.share_id]
    assert "position_mismatch" in rig.alert_kinds()
    assert "opened" in [e["event"] for e in rig.share_events(share.share_id)]


def test_F12_R1_P2_healing_replays_the_leader_close_that_arrived_while_the_fill_was_unknown(new_rig: NewRig) -> None:
    """RED. The leader's CLOSE was deferred forever behind the lost fill."""
    rig = new_rig(exits__tp_enabled=False)
    now = rig.xtime.now
    close = make_signal(2, ActionKind.CLOSE, size="5", ts=now + 500)
    _lost_entry_fill(rig, signals_after=(close,))
    rig.leader_state.positions[WALLET_A] = {}
    books(rig, "SOL", "100", now + SEC, now + 9 * SEC)
    rig.mgr.reconcile()
    assert acts(rig).count("close") == 1, "exactly one close, not zero and not two"
    rig.step(now + 3 * SEC)
    assert rig.env.broker.position("SOL") is None
    assert rig.book.states()[0].status == "closed"


def test_F12_R1_P2_reconcile_also_reads_leaders_whose_only_share_is_still_pending(new_rig: NewRig) -> None:
    """RED. A leader with a pending share is fetched by reconcile (so a lost fill is healed AND the leader checked)."""
    rig = new_rig()
    now = rig.xtime.now
    rig.leader_state.positions[WALLET_A] = {"SOL": "5"}
    rig.book_at("SOL", "100", now + SEC)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    assert rig.share_of(WALLET_A, "SOL").status == "pending_entry"
    calls = rig.leader_state.calls
    rig.mgr.reconcile()
    assert rig.leader_state.calls > calls
    assert rig.share_of(WALLET_A, "SOL").status == "pending_entry"  # still pending at the broker: nothing is changed


def test_F12_R1_P2_a_pending_share_still_pending_at_the_broker_is_left_alone(new_rig: NewRig) -> None:
    """GUARD (kills a mutant that heals every pending share): book and broker agree, no alert, no second order."""
    rig = new_rig()
    now = rig.xtime.now
    rig.leader_state.positions[WALLET_A] = {"SOL": "5"}
    rig.book_at("SOL", "100", now + SEC)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    rig.mgr.reconcile()
    assert rig.share_of(WALLET_A, "SOL").status == "pending_entry"
    assert "position_mismatch" not in rig.alert_kinds() and acts(rig) == ["open"]
    rig.step(now + SEC)
    assert rig.share_of(WALLET_A, "SOL").status == "open"


# ============================================================================================ RISK-34 / P4


def test_F12_R1_P4_an_add_in_the_opposite_direction_is_skipped_invalid_signal(new_rig: NewRig) -> None:
    """RED. The leader flipped long->short and adds to the short while our long close is still in flight."""
    rig = new_rig()
    share = rig.open_share(1)
    now = rig.xtime.now
    close_leg, open_leg = flip_signals(ts=now - 100)
    rig.feed(close_leg, open_leg)  # no book: the close stays pending
    add = make_signal(3, ActionKind.ADD, is_long=False, size="1", pre="3", post="4", ts=now - 50)
    rig.feed(add)
    assert acts(rig) == ["open", "close"], "an add was sent against our long share"
    assert skips(rig)[add.signal_id] == "invalid_signal"
    assert rig.book.state(share.share_id).qty == D("1.00")


def test_F12_R1_P4_a_reduce_in_the_opposite_direction_is_skipped_invalid_signal(new_rig: NewRig) -> None:
    """RED. Same for a reduce of the new short: it must not reduce our long."""
    rig = new_rig()
    share = rig.open_share(1)
    rig.leader_state.positions[WALLET_A] = {"SOL": "-3"}
    now = rig.xtime.now
    reduce_ = make_signal(
        3, ActionKind.REDUCE, is_long=False, size="1", pre="3", post="2", fraction="0.3333", ts=now - 50
    )
    rig.feed(reduce_)
    assert acts(rig) == ["open"], "a reduce of the leader's short was mirrored on our long"
    assert skips(rig)[reduce_.signal_id] == "invalid_signal"
    assert rig.book.state(share.share_id).qty == D("1.00")


def test_F12_R1_P4_a_wrong_direction_signal_alerts_bad_signal_and_reconciles(new_rig: NewRig) -> None:
    """RED: the alert kind is ``bad_signal`` and the leader is read (reconcile) so a missed flip is found."""
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    rig.leader_state.positions[WALLET_A] = {"SOL": "-3"}
    calls = rig.leader_state.calls
    rig.feed(make_signal(3, ActionKind.ADD, is_long=False, size="1", pre="3", post="4", ts=now - 50))
    assert "bad_signal" in rig.alert_kinds()
    assert rig.leader_state.calls > calls


def test_F12_R1_P4_an_add_while_our_close_is_in_flight_is_skipped(new_rig: NewRig) -> None:
    """RED. Same direction: the leader closes (our close is pending, no book) and then adds; no add may go out."""
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 100))  # no book: pending
    add = make_signal(3, ActionKind.ADD, size="1", pre="5", post="6", ts=now - 50)
    rig.feed(add)
    assert acts(rig) == ["open", "close"], "an add was sent while the close was in flight"
    assert add.signal_id in skips(rig)


def test_F12_R1_P4_same_direction_add_and_reduce_still_work(new_rig: NewRig) -> None:
    """GUARD (kills a mutant that skips every add or reduce): the direction check must not break the normal path."""
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    now = rig.xtime.now
    books(rig, "SOL", "100", now + SEC, now + 4 * SEC)
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 50))
    rig.step(now + SEC)
    assert rig.book.state(share.share_id).qty == D("1.50")
    rig.feed(make_signal(3, ActionKind.REDUCE, size="1.5", pre="7.5", post="6", fraction="0.2", ts=now + SEC - 50))
    rig.step(now + 2 * SEC)
    assert rig.book.state(share.share_id).qty == D("1.20")
