"""F12.AC1 per-leader shares, the F10 ShareBook port, fills before the next gate call, ids and the share ledger."""

from __future__ import annotations

from decimal import Decimal as D

from copytrade.core.domain import ActionKind
from copytrade.risk.types import ShareExposure
from tests.positions.conftest import NewRig
from tests.positions.helpers import WALLET_A, WALLET_B, make_signal


def close_sig(tid: int, **kw: object) -> object:
    return make_signal(tid, ActionKind.CLOSE, **kw)  # type: ignore[arg-type]


def test_F12_AC1_share_holds_qty_entry_stops_tp_risk_and_max_committed_risk(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    assert share.status == "open"
    assert (share.leader, share.coin, share.is_long) == (WALLET_A, "SOL", True)
    assert share.qty == D("1.00")
    assert share.entry_px == D("100")
    assert share.initial_stop_px == D("98.5")
    assert share.current_stop_px == D("98.5")
    assert share.tp_done is False
    assert share.initial_risk_usd == D("1.5")
    assert share.open_risk_usd == D("1.5")
    assert share.max_committed_risk_usd >= share.initial_risk_usd


def test_F12_AC1_leader_event_changes_only_that_leaders_share(new_rig: NewRig) -> None:
    rig = new_rig()
    a = rig.open_share(1, wallet=WALLET_A, coin="ETH")
    b = rig.open_share(2, wallet=WALLET_B, coin="ETH")
    assert a.share_id != b.share_id
    now = rig.xtime.now
    rig.book_at("ETH", "100", now + 1000)
    rig.feed(close_sig(3, wallet=WALLET_A, coin="ETH"))
    rig.step(now + 1000)
    assert rig.book.state(a.share_id).status == "closed"
    after = rig.book.state(b.share_id)
    assert (after.status, after.qty, after.current_stop_px, after.entry_px) == (
        "open", b.qty, b.current_stop_px, b.entry_px)
    assert [s.share_id for s in rig.book.open_shares()] == [b.share_id]
    assert rig.held("ETH").share_ids == (b.share_id,)


def test_F12_AC1_book_implements_the_F10_port_with_exact_exposure_fields(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    rig.mark("SOL", "100.5")
    (exposure,) = rig.book.open_shares()
    assert isinstance(exposure, ShareExposure)
    assert (exposure.share_id, exposure.trade_id, exposure.coin, exposure.leader) == (
        share.share_id, share.trade_id, "SOL", WALLET_A)
    assert exposure.is_long is True
    assert (exposure.qty, exposure.entry_px, exposure.stop_px) == (D("1.00"), D("100"), D("98.5"))
    assert exposure.mark_px == D("100.5")
    assert exposure.open_risk_usd == D("1.5")


def test_F12_AC1_pending_entry_is_not_listed_as_open_share(new_rig: NewRig) -> None:
    rig = new_rig()
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    assert rig.book.open_shares() == ()  # the gate counts the in-flight entry itself
    (state,) = rig.book.states()
    assert state.status == "pending_entry"
    rig.step(now + 1000)
    assert [s.status for s in rig.book.states()] == ["open"]


def test_F12_AC1_open_risk_is_never_negative_when_stop_is_past_entry(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    rig.open_share(1)
    rig.mark("SOL", "110")  # the trail lifts the stop above the entry
    (exposure,) = rig.book.open_shares()
    assert exposure.stop_px > exposure.entry_px
    assert exposure.open_risk_usd == D(0)


def test_F12_AC1_short_share_mirrors_direction_and_stop_side(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1, is_long=False)
    assert share.is_long is False
    assert share.initial_stop_px == D("101.5")
    assert share.open_risk_usd == D("1.5")


def test_F12_AC1_share_ids_are_deterministic_unique_per_coin_and_leader(new_rig: NewRig) -> None:
    one, two = new_rig(), new_rig()
    s1 = one.open_share(1)
    s2 = two.open_share(1)
    assert (s1.share_id, s1.trade_id) == (s2.share_id, s2.trade_id)
    other_leader = one.open_share(2, wallet=WALLET_B)
    other_coin = one.open_share(3, coin="ETH")
    assert len({s1.share_id, other_leader.share_id, other_coin.share_id}) == 3
    assert len({s1.trade_id, other_leader.trade_id, other_coin.trade_id}) == 3


def test_F12_AC1_client_order_ids_are_deterministic_across_identical_runs(new_rig: NewRig) -> None:
    ids = []
    for _ in range(2):
        rig = new_rig()
        share = rig.open_share(1)
        now = rig.xtime.now
        rig.book_at("SOL", "100", now + 1000)
        rig.feed(close_sig(2))  # type: ignore[arg-type]
        rig.step(now + 1000)
        assert rig.book.state(share.share_id).status == "closed"
        ids.append([o["_coid"] for o in rig.orders()])
    assert ids[0] == ids[1] and len(ids[0]) == 2 and len(set(ids[0])) == 2


def test_F12_AC1_entry_fill_price_not_decision_price_sets_entry_and_stop(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1, fill_px="100.2")
    assert share.entry_px == D("100.2")
    assert share.initial_stop_px == D("98.7")  # fill - 2 x ATR(14) = 100.2 - 1.5
    assert share.initial_risk_usd == share.qty * D("1.5")


def test_F12_AC1_every_share_state_change_is_ledgered_in_order(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    rig.mark("SOL", "104")  # trail: stop 104 - 1.5 = 102.5
    now = rig.xtime.now
    rig.book_at("SOL", "104", now + 1000)
    rig.feed(close_sig(2))  # type: ignore[arg-type]
    rig.step(now + 1000)
    events = rig.share_events(share.share_id)
    names = [e["event"] for e in events]
    assert names.index("opened") < names.index("stop_moved") < names.index("closed")
    opened = events[names.index("opened")]
    assert (D(str(opened["qty"])), D(str(opened["entry_px"])), D(str(opened["stop_px"]))) == (
        D("1.00"), D("100"), D("98.5"))
    assert D(str(opened["open_risk_usd"])) == D("1.5")
    moved = events[names.index("stop_moved")]
    assert D(str(moved["stop_px"])) == D("102.5")
    assert all({"share_id", "leader", "coin", "qty", "stop_px", "open_risk_usd", "event"} <= set(e) for e in events)
    seqs = [e["_seq"] for e in events]
    assert seqs == sorted(seqs)
