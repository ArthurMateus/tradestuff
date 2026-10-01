"""F12 review round 1: pins for the eight blocking mutant survivors (senior-dev gaps 2-9) and the section 4 advisories.
These guard behaviour that exists on the round-1 code, so they PASS today (GUARD); each names the mutant it kills.
Real gate, broker, ledger and manager; only the clock, books, candles and the leader's exchange state are faked."""

from __future__ import annotations

from decimal import Decimal as D
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from copytrade.risk.ids import client_order_id
from tests.positions.conftest import NewRig
from tests.positions.helpers import SEC, WALLET_A, WALLET_B, make_signal
from tests.positions.test_r1_blocking import acts, books, freeze_clock, skips, ticking_clock

RUN = "run1"


def poison_stop(rig: Any, share_id: str, kind: str, seq: int) -> None:
    """Pretend the stop with this deterministic id was already sent (a replay): the gate refuses it ``duplicate_order``.
    The ledger is the real one; only an unrelated record carries the id."""
    cid = client_order_id(
        run_id=RUN, leader=WALLET_A, coin="SOL", tids=(), action=f"{kind}:{share_id}:{kind}:{seq}", share_id=share_id
    )
    rig.env.ledger.append(
        "paper_reject", {"client_order_id": cid, "coin": "SOL", "reason": "seeded"}, client_order_id=cid
    )


def share_id_of(tid: int = 1, wallet: str = WALLET_A) -> str:
    return f"share:{make_signal(tid, ActionKind.OPEN, wallet=wallet).signal_id}"


# ============================================================ gap: no stop can be placed after the entry fill


def test_F12_R1_GUARD_a_share_whose_initial_stop_is_refused_is_closed_at_once_and_alerted(new_rig: NewRig) -> None:
    """Kills: dropping the stop_failed alert, the close-for-cause call, or the 'cid is None' branch in _place_protection."""
    rig = new_rig(exits__tp_enabled=False)
    poison_stop(rig, share_id_of(), "sl", 1)
    now = rig.xtime.now
    books(rig, "SOL", "100", now + SEC, now + 6 * SEC)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    rig.step(now + SEC)
    assert "stop_failed" in rig.alert_kinds()
    assert rig.active_stops() == []
    closes = [o for o in rig.orders() if o["action"] == "close"]
    assert len(closes) == 1 and closes[0]["exit_reason"] == "stop_failed"
    rig.step(now + 2 * SEC)
    assert rig.env.broker.position("SOL") is None and rig.book.open_shares() == ()
    assert rig.book.states()[0].status == "closed"


# ======================================================= gap: register the new stop BEFORE cancelling the old one


def test_F12_R1_GUARD_a_refused_trailed_stop_leaves_the_old_stop_in_place(new_rig: NewRig) -> None:
    """Kills: cancel-then-place order in _trail (the share would be left with no stop)."""
    rig = new_rig(exits__tp_enabled=False)
    poison_stop(rig, share_id_of(), "sl", 2)  # the trail's stop
    share = rig.open_share(1)
    rig.mark("SOL", "104")
    (stop,) = rig.active_stops(share.share_id)
    assert (D(str(stop["trigger_px"])), D(str(stop["qty"]))) == (D("98.5"), D("1.00"))
    assert rig.book.state(share.share_id).current_stop_px == D("98.5")  # the stored stop follows the real one
    assert "stop_failed" in rig.alert_kinds()
    assert [c for c in rig.records("paper_cancel") if c.get("target") == "stop"] == []


def test_F12_R1_GUARD_a_refused_replacement_after_a_take_profit_leaves_the_old_stop_in_place(new_rig: NewRig) -> None:
    """Kills: cancel-then-place order in _replace_stop."""
    rig = new_rig(exits__trail_start_r=D("5"))
    poison_stop(rig, share_id_of(), "sl", 3)  # sl:1, tp:2, then the re-placed stop
    share = rig.open_share(1)
    rig.mark_and_fill("SOL", "103")
    assert rig.book.state(share.share_id).qty == D("0.50")
    stops = rig.active_stops(share.share_id)
    assert [s["kind"] for s in stops] == ["sl"], "the old stop must still protect the share"
    assert "stop_failed" in rig.alert_kinds()


def test_F12_R1_GUARD_a_trail_that_is_not_tighter_places_no_new_stop(new_rig: NewRig) -> None:
    """Kills: the 'tighter' test in _trail (a non-tighter stop would be re-placed on every mark)."""
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    rig.mark("SOL", "104")
    placed = len(rig.records("paper_stop"))
    issued = len(rig.authority.issued)
    for px in ("104", "103", "103.5", "104"):
        rig.mark("SOL", px)
    assert len(rig.records("paper_stop")) == placed and len(rig.authority.issued) == issued
    assert rig.book.state(share.share_id).current_stop_px == D("102.5")


# ===================================================================================== gap: closing self-heal


def test_F12_R1_GUARD_an_add_filling_while_our_close_is_pending_leaves_a_remainder_that_is_closed(
    new_rig: NewRig,
) -> None:
    """Kills: the 'closing and nothing pending' branch of _exit_filled (the add's quantity would stay open, unmanaged
    by the leader's exit)."""
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    now = rig.xtime.now
    books(rig, "SOL", "100", now + 500, now + 8 * SEC)
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 50))  # fills at +1 s
    rig.at(now + 500)
    rig.feed(make_signal(3, ActionKind.CLOSE, size="7.5", ts=now + 400))  # sized for 1.00: the add is not booked yet
    rig.step(now + SEC)  # the add fills
    rig.step(now + 2 * SEC)  # the close fills for the old quantity: the add's part is left
    rig.step(now + 3 * SEC)
    rig.step(now + 4 * SEC)
    assert rig.book.state(share.share_id).status == "closed"
    assert rig.env.broker.position("SOL") is None
    reasons = [o["exit_reason"] for o in rig.orders() if o["action"] == "close"]
    assert "close_remainder" in reasons


# ============================================================ gap: deferred leader exit and add replayed after the fill


def test_F12_R1_GUARD_a_leader_close_that_arrived_while_the_entry_was_pending_closes_right_after_the_fill(
    new_rig: NewRig,
) -> None:
    """Kills: dropping the deferred replay in _opened (the share would stay open with the leader flat)."""
    rig = new_rig()
    now = rig.xtime.now
    books(rig, "SOL", "100", now + SEC, now + 8 * SEC)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    rig.feed(make_signal(2, ActionKind.CLOSE, size="5", ts=now - 50))
    assert acts(rig) == ["open"]
    rig.step(now + SEC)  # the entry fills; the close goes out in the same step
    assert acts(rig) == ["open", "close"]
    rig.step(now + 2 * SEC)
    assert rig.book.states()[0].status == "closed" and rig.env.broker.position("SOL") is None


def test_F12_R1_GUARD_a_leader_add_that_arrived_while_the_entry_was_pending_is_mirrored_after_the_fill(
    new_rig: NewRig,
) -> None:
    """Kills: dropping the deferred replay of an add."""
    rig = new_rig(exits__tp_enabled=False)
    now = rig.xtime.now
    books(rig, "SOL", "100", now + SEC, now + 8 * SEC)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 50))
    rig.step(now + SEC)
    assert acts(rig) == ["open", "add"]
    rig.step(now + 2 * SEC)
    assert rig.book.states()[0].qty == D("1.50")


# =================================================== gap: every fill is booked before the next gate call (F10 contract)


@pytest.mark.parametrize("lead_ms", range(0, 1_000, 100))
@pytest.mark.parametrize("second", ["open", "add"])
def test_F12_R1_GUARD_a_fill_produced_inside_a_gate_call_is_booked_and_protected(
    new_rig: NewRig, second: str, lead_ms: int
) -> None:
    """Another leader's entry on ETH fills at now + 1 s. A real clock ticks across that moment during our next gate call
    (an open, or an add). Whether the fill surfaces in the manager's own sync or inside the gate's advance, it must
    be booked and protected. Kills: dropping ``_book_events(outcome.broker_events)`` after an open or an add submit,
    or dropping the sync before a signal."""
    rig = new_rig(exits__tp_enabled=False)
    if second == "add":
        rig.open_share(1)
    now = rig.xtime.now
    books(rig, "ETH", "100", now + 500, now + 8 * SEC)
    books(rig, "SOL", "100", now + 500, now + 8 * SEC)
    rig.feed(make_signal(7, ActionKind.OPEN, wallet=WALLET_B, coin="ETH", size="5", ts=now - 100))
    other = rig.share_of(WALLET_B, "ETH")
    assert other.status == "pending_entry"
    clock = ticking_clock(rig, now + SEC - lead_ms, 100)
    if second == "open":
        rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    else:
        rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 100))
    freeze_clock(rig, clock["t"])
    booked = rig.book.state(other.share_id)
    held = rig.env.broker.position("ETH")
    if held is None:  # the clock never reached the fill in this call: nothing can be behind
        assert booked.status == "pending_entry"
        return
    # the broker filled it during this call (small leads): the book must not be behind
    assert booked.status == "open" and booked.qty == held.share_qtys[0]
    assert [s["kind"] for s in rig.active_stops(other.share_id)] == ["sl"]


@pytest.mark.parametrize("lead_ms", [100, 200])
def test_F12_R1_GUARD_a_fill_produced_inside_an_exit_submit_is_booked_before_the_call_returns(
    new_rig: NewRig, lead_ms: int
) -> None:
    """The TP fill surfaces inside the gate advance of the leader's close. Kills: dropping the booking of an exit
    submit's events in _submit_exit (the book would stay at 1.00 while the broker holds 0.50)."""
    rig = new_rig(exits__trail_start_r=D("5"))
    share = rig.open_share(1)
    now = rig.xtime.now
    books(rig, "SOL", "103", now + 500, now + 6 * SEC)
    rig.mark("SOL", "103")
    clock = ticking_clock(rig, now + SEC - lead_ms, 100)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now + 900))
    freeze_clock(rig, clock["t"])
    held = rig.env.broker.position("SOL")
    assert held is not None and rig.book.state(share.share_id).qty == held.share_qtys[0]


def test_F12_R1_GUARD_a_signal_sees_the_fill_that_happened_before_it_arrived(new_rig: NewRig) -> None:
    """The entry fills at the broker at now + 1 s; the leader's close arrives at now + 1.1 s before anyone advanced
    the manager. The signal's own sync books the fill, so the close goes out at once (it is not deferred)."""
    rig = new_rig()
    now = rig.xtime.now
    books(rig, "SOL", "100", now + SEC, now + 8 * SEC)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    rig.at(now + 1_100)
    rig.feed(make_signal(2, ActionKind.CLOSE, size="5", ts=now + 1_050))
    assert acts(rig) == ["open", "close"]


# ================================================= gap: flat and reversed leader boundary in _reconcile_share


@pytest.mark.parametrize(
    ("is_long", "leader_holds", "closes"),
    [
        (True, {}, True),  # the coin is absent: flat
        (True, {"SOL": "0"}, True),  # exactly flat (the boundary)
        (True, {"SOL": "-0.5"}, True),  # reversed
        (True, {"SOL": "0.0001"}, False),  # one step the right side: stays
        (True, {"SOL": "5"}, False),
        (False, {}, True),
        (False, {"SOL": "0"}, True),
        (False, {"SOL": "0.5"}, True),
        (False, {"SOL": "-0.0001"}, False),
        (False, {"SOL": "-5"}, False),
    ],
)
def test_F12_R1_GUARD_reconcile_closes_the_share_when_the_leader_is_flat_or_reversed_and_not_one_step_before(
    new_rig: NewRig, is_long: bool, leader_holds: dict[str, str], closes: bool
) -> None:
    """Kills: ``size * direction <= 0`` weakened to ``< 0`` (flat would not close) or to ``<= tiny`` / ``< 1``."""
    rig = new_rig()
    share = rig.open_share(1, is_long=is_long)
    now = rig.xtime.now
    rig.leader_state.positions[WALLET_A] = dict(leader_holds)
    books(rig, "SOL", "100", now + SEC, now + 4 * SEC)
    rig.mgr.reconcile()
    if closes:
        assert acts(rig) == ["open", "close"] and "reconcile_close" in rig.alert_kinds()
        rig.step(now + SEC)
        rig.step(now + 2 * SEC)
        assert rig.book.state(share.share_id).status == "closed"
    else:
        assert acts(rig) == ["open"] and rig.book.state(share.share_id).status == "open"
        assert "reconcile_close" not in rig.alert_kinds()


# ============================================================================ gap: the add is sized at the share's stop


def test_F12_R1_GUARD_an_add_is_sized_at_the_shares_current_stop_not_at_its_own_tighter_stop(new_rig: NewRig) -> None:
    """The add at 110 has its own stop at 108.5, but the share keeps its stop at 98.5: the risk of the added quantity is
    measured to 98.5, which caps it to 0.13 (at its own stop it would be the proportional 0.50). Kills: passing the
    add's stop instead of ``share.current_stop_px`` in AddRequest (F10 B3)."""
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    now = rig.xtime.now
    books(rig, "SOL", "110", now + SEC, now + 4 * SEC)
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", px="110", ts=now - 100))
    rig.step(now + SEC)
    after = rig.book.state(share.share_id)
    assert after.qty == D("1.13")
    assert after.current_stop_px == D("98.5")  # an add never moves the stop


# ============================================================================================ gap: stop <= 0 boundary


@pytest.mark.parametrize(
    ("tr", "invalid"),
    [("49.98", False), ("50", True), ("50.02", True), ("60", True)],
)
def test_F12_R1_GUARD_an_open_whose_stop_is_zero_or_below_is_skipped_before_the_gate_is_asked(
    new_rig: NewRig, tr: str, invalid: bool
) -> None:
    """stop = 100 - 2 x ATR. Exactly 0 is invalid. Kills: ``stop <= 0`` weakened to ``< 0`` in _open_share (the gate
    would be asked and refuse it itself, so the manager's own skip is pinned by 'no decision at all')."""
    rig = new_rig()
    rig.candles.set_flat("SOL", tr=D(tr))
    now = rig.xtime.now
    sig = make_signal(1, ActionKind.OPEN, size="5", ts=now - 100)
    rig.feed(sig)
    if invalid:
        assert skips(rig)[sig.signal_id] == "invalid_stop" and rig.decisions() == []
    else:
        assert skips(rig).get(sig.signal_id) != "invalid_stop" and rig.decisions() != []


@pytest.mark.parametrize(("tr", "invalid"), [("50", True), ("50.02", True), ("60", True)])
def test_F12_R1_GUARD_an_add_whose_stop_is_zero_or_below_is_skipped_before_the_gate_is_asked(
    new_rig: NewRig, tr: str, invalid: bool
) -> None:
    """Kills: ``stop <= 0`` weakened to ``< 0`` in _handle_add."""
    rig = new_rig()
    rig.open_share(1)
    decisions = len(rig.decisions())
    rig.candles.set_flat("SOL", tr=D(tr))
    now = rig.xtime.now
    add = make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 50)
    rig.feed(add)
    assert invalid and skips(rig)[add.signal_id] == "invalid_stop"
    assert len(rig.decisions()) == decisions and acts(rig) == ["open"]


# ================================================================================================ section 4 pins


def test_F12_R1_GUARD_after_an_accepted_close_later_leader_exits_send_nothing_more(new_rig: NewRig) -> None:
    """The ``closing`` flag after an accepted CLOSE: a second close and a reduce are not sent. Kills: not setting it."""
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 100))  # no book: pending
    assert acts(rig) == ["open", "close"]
    rig.feed(make_signal(3, ActionKind.REDUCE, size="1", pre="5", post="4", fraction="0.2", ts=now - 50))
    assert acts(rig) == ["open", "close"]


def test_F12_R1_GUARD_a_pending_share_the_broker_neither_holds_nor_has_pending_is_dropped_as_a_ghost(
    new_rig: NewRig,
) -> None:
    """The rejection event was lost: reconcile drops the share, alerts, and the leader's next open works. Kills: the
    ghost branch for pending shares in _reconcile_broker."""
    rig = new_rig()
    now = rig.xtime.now
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))  # no book: rejected at the fill
    rig.at(now + 6_001)
    rig.env.advance(now + 6_001)  # the manager never sees the rejection
    assert rig.share_of(WALLET_A, "SOL").status == "pending_entry"
    rig.leader_state.positions[WALLET_A] = {}
    rig.mgr.reconcile()
    assert rig.share_of(WALLET_A, "SOL") is None
    assert "ghost_share_dropped" in [e["event"] for e in rig.share_events()]
    assert "position_mismatch" in rig.alert_kinds()
