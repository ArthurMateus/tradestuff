"""F12.AC4 first exit wins, leader closes and flips, and the signals F12 must ignore."""

from __future__ import annotations

from decimal import Decimal as D

from copytrade.core.domain import ActionKind
from tests.positions.conftest import NewRig
from tests.positions.helpers import WALLET_A, WALLET_B, make_signal


def close_sig(tid: int, **kw):  # type: ignore[no-untyped-def]
    return make_signal(tid, ActionKind.CLOSE, **kw)


def settle(rig, *signals, px: str = "100"):  # type: ignore[no-untyped-def]
    now = rig.xtime.now
    rig.book_at("SOL", px, now + 1000)
    rig.feed(*signals)
    rig.step(now + 1000)


def test_F12_AC4_leader_close_closes_our_share_with_a_reduce_only_order(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    settle(rig, close_sig(2, ts=rig.xtime.now - 100))
    assert rig.book.state(share.share_id).status == "closed"
    assert rig.book.open_shares() == () and rig.env.broker.position("SOL") is None
    closing = [d for d in rig.decisions() if d.get("action") == "close"]
    assert closing and closing[-1]["approved"] is True
    assert [t.share_id for t in rig.env.trades()] == [share.share_id]
    assert rig.active_stops() == []


def test_F12_AC4_after_our_stop_closes_the_share_later_leader_events_are_ignored(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    rig.mark_and_fill("SOL", "98.4")
    assert rig.book.state(share.share_id).status == "closed"
    orders = len(rig.orders())
    now = rig.xtime.now
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 100),
             make_signal(3, ActionKind.REDUCE, size="1", pre="7.5", post="6.5", fraction="0.2", ts=now - 100),
             close_sig(4, size="6.5", ts=now - 100))
    assert len(rig.orders()) == orders  # nothing sent
    assert rig.records("missed_exit") == []  # a leader close after our own stop is not a missed exit
    assert {s["reason"] for s in rig.records("signal_skip")} == {"first_exit_won"}


def test_F12_AC4_leaders_next_open_after_going_flat_is_a_new_signal_and_opens(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.open_share(1)
    rig.mark_and_fill("SOL", "98.4")
    now = rig.xtime.now
    rig.feed(close_sig(2, ts=now - 100))  # the leader goes flat: ignored, and it ends the ignore window
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(3, ActionKind.OPEN, ts=now - 100))
    rig.step(now + 1000)
    new = rig.share_of(WALLET_A, "SOL")
    assert new is not None and new.status == "open" and new.signal_id.endswith(":3:0")


def test_F12_AC4_leader_reduce_to_nonzero_after_our_stop_keeps_the_ignore_window_open(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.open_share(1)
    rig.mark_and_fill("SOL", "98.4")
    now = rig.xtime.now
    orders = len(rig.orders())
    rig.feed(make_signal(2, ActionKind.REDUCE, size="1", pre="5", post="4", fraction="0.2", ts=now - 100))
    rig.feed(make_signal(3, ActionKind.ADD, size="1", pre="4", post="5", ts=now - 100))
    assert len(rig.orders()) == orders and rig.share_of(WALLET_A, "SOL") is None


def test_F12_AC4_flip_closes_first_and_opens_only_after_the_close_fills(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(close_sig(2, size="5", from_flip=True, ts=now - 100),
             make_signal(2, ActionKind.OPEN, is_long=False, size="3", leg=1, from_flip=True, ts=now - 100))
    assert [o["action"] for o in rig.orders()][-1] == "close"  # only the close has been sent
    assert rig.book.state(share.share_id).status == "open"  # not closed until it fills
    rig.book_at("SOL", "100", now + 2000)
    rig.step(now + 1000)  # the close fills; the open goes out now
    rig.step(now + 2000)  # and fills
    assert rig.book.state(share.share_id).status == "closed"
    new = rig.share_of(WALLET_A, "SOL")
    assert new is not None and new.is_long is False and new.share_id != share.share_id
    assert all(d.get("reason") != "opposite_side_entry" for d in rig.decisions())
    assert rig.held("SOL").qty < 0


def test_F12_AC4_flip_open_leg_waits_while_the_close_has_not_filled(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    now = rig.xtime.now  # no book for the close fill: it is rejected, so the share stays long
    rig.feed(close_sig(2, size="5", from_flip=True, ts=now - 100),
             make_signal(2, ActionKind.OPEN, is_long=False, size="3", leg=1, from_flip=True, ts=now - 100))
    rig.step(now + 1000)
    rig.step(now + 2000)
    assert [o["action"] for o in rig.orders()] == ["open", "close"]  # no second open while the close is pending
    assert rig.book.state(share.share_id).is_long is True


def test_F12_AC4_flip_after_our_stop_already_closed_the_share_opens_the_new_side_directly(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.open_share(1)
    rig.mark_and_fill("SOL", "98.4")
    now = rig.xtime.now
    rig.book_at("SOL", "98.4", now + 1000)
    rig.feed(close_sig(2, size="5", from_flip=True, ts=now - 100),
             make_signal(2, ActionKind.OPEN, is_long=False, size="3", leg=1, from_flip=True, ts=now - 100))
    rig.step(now + 1000)
    new = rig.share_of(WALLET_A, "SOL")
    assert new is not None and new.is_long is False


def test_F12_AC4_flip_with_the_open_refused_still_closes_our_share(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    rig.policy.mult = None  # F9 vetoes the new side
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(close_sig(2, size="5", from_flip=True, ts=now - 100),
             make_signal(2, ActionKind.OPEN, is_long=False, size="3", leg=1, from_flip=True, ts=now - 100))
    rig.step(now + 1000)
    rig.step(now + 2000)
    assert rig.book.state(share.share_id).status == "closed" and rig.share_of(WALLET_A, "SOL") is None


def test_F12_AC4_pre_existing_and_unparsed_signals_are_ignored(new_rig: NewRig) -> None:
    rig = new_rig()
    for tid, outcome in ((1, "pre_existing"), (2, "out_of_scope"), (3, "unparseable")):
        rig.feed(make_signal(tid, ActionKind.OPEN, outcome=outcome, ts=rig.xtime.now - 100))
    assert rig.orders() == [] and rig.book.states() == ()


def test_F12_AC4_exit_for_a_share_we_never_opened_is_ignored(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.feed(close_sig(1, ts=rig.xtime.now - 100),
             make_signal(2, ActionKind.REDUCE, size="1", pre="5", post="4", fraction="0.2", ts=rig.xtime.now - 100),
             make_signal(3, ActionKind.ADD, size="1", pre="5", post="6", ts=rig.xtime.now - 100))
    assert rig.orders() == []
    assert {s["reason"] for s in rig.records("signal_skip")} == {"no_share"}
    assert rig.records("missed_exit") == []


def test_F12_AC4_exit_from_another_leader_never_touches_our_share(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1, wallet=WALLET_A)
    rig.feed(close_sig(2, wallet=WALLET_B, ts=rig.xtime.now - 100))
    assert rig.book.state(share.share_id).status == "open" and len(rig.orders()) == 1


def test_F12_AC4_redelivered_signal_is_one_order_only(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    sig = close_sig(2, ts=now - 100)
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(sig)
    before = len(rig.orders())
    rig.feed(sig)  # the same event again (a reconnect replay)
    rig.step(now + 1000)
    assert len(rig.orders()) == before
    assert len(rig.records("missed_exit")) == 0


def test_F12_AC4_exit_signal_with_a_clock_flag_still_executes_but_an_add_does_not(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    now = rig.xtime.now
    flags = frozenset({"clock_unsynced"})
    orders = len(rig.orders())
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 100, flags=flags))
    assert len(rig.orders()) == orders
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(close_sig(3, ts=now - 100, flags=flags))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"


def test_F12_AC4_open_signal_with_a_veto_or_missing_leader_value_opens_nothing_and_does_not_raise(
    new_rig: NewRig,
) -> None:
    rig = new_rig()
    rig.policy.mult = None
    rig.feed(make_signal(1, ActionKind.OPEN, ts=rig.xtime.now - 100))
    rig.policy.mult = D(1)
    rig.leader_state.fail = True
    rig.feed(make_signal(2, ActionKind.OPEN, ts=rig.xtime.now - 100))
    rig.leader_state.fail = False
    rig.policy.fail = True
    rig.feed(make_signal(3, ActionKind.OPEN, ts=rig.xtime.now - 100))
    assert rig.orders() == [] and rig.book.states() == ()
    assert len(rig.records("signal_skip")) == 3


def test_F12_AC8_dropped_leader_keeps_its_shares_managed_by_our_stop_and_its_exits(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    rig.mgr.leader_dropped(WALLET_A)
    assert rig.book.state(share.share_id).status == "open"
    rig.mark("SOL", "104")
    assert rig.book.state(share.share_id).current_stop_px == D("102.5")  # the trail still runs
    settle(rig, close_sig(2, ts=rig.xtime.now - 100), px="104")  # and the leader's close still closes it
    assert rig.book.state(share.share_id).status == "closed"


def test_F12_AC8_dropped_leader_share_is_still_closed_by_its_stop(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    rig.mgr.leader_dropped(WALLET_A)
    rig.mark_and_fill("SOL", "98.4")
    assert rig.book.state(share.share_id).status == "closed"
