"""F10 and F11 contracts for F12: every ``Outcome.broker_events`` (and every flatten pass) books its fills before
the next gate call; partial fills, liquidations, delistings, stale books and oversized closes."""

from __future__ import annotations

from decimal import Decimal as D

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from tests.positions.conftest import NewRig
from tests.positions.helpers import WALLET_A, WALLET_B, make_signal


def test_F12_F10_fills_returned_by_a_gate_advance_are_booked_before_the_call_returns(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    a = rig.open_share(1, wallet=WALLET_A, coin="SOL")
    now = rig.xtime.now
    rig.book_at("ETH", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.OPEN, wallet=WALLET_B, coin="ETH", size="5", ts=now - 100))
    assert rig.share_of(WALLET_B, "ETH").status == "pending_entry"
    rig.at(now + 1500)  # the supervisor has NOT advanced the broker: the next gate call will
    rig.book_at("SOL", "100", now + 2500)
    rig.feed(make_signal(3, ActionKind.CLOSE, wallet=WALLET_A, coin="SOL", ts=now + 1400))
    b = rig.share_of(WALLET_B, "ETH")
    assert b.status == "open" and b.qty == D("1.0000") and b.entry_px == D("100")  # booked by the submit's advance
    assert [s["kind"] for s in rig.active_stops(b.share_id)] == ["sl"]
    assert rig.book.state(a.share_id).status == "open"  # its own close has not filled yet


def test_F12_F10_on_broker_events_books_events_the_caller_obtained_itself(new_rig: NewRig) -> None:
    rig = new_rig()
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    rig.at(now + 1000)
    events = rig.env.broker.advance_to(now + 1000)
    assert rig.share_of(WALLET_A, "SOL").status == "pending_entry"
    rig.mgr.on_broker_events(events)
    assert rig.share_of(WALLET_A, "SOL").status == "open"
    rig.mgr.on_broker_events(events)  # the same events twice change nothing
    assert rig.share_of(WALLET_A, "SOL").qty == D("1.00")


def test_F12_F10_flatten_closes_every_share_and_books_every_pass(new_rig: NewRig) -> None:
    rig = new_rig()
    sol = rig.open_share(1, wallet=WALLET_A, coin="SOL")
    eth = rig.open_share(2, wallet=WALLET_B, coin="ETH")
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.book_at("ETH", "100", now + 1000)
    report = rig.mgr.flatten(run_id="flat1")
    assert len(report) == 2 and all(o.decision.approved for o in report)
    rig.step(now + 1000)
    assert rig.book.state(sol.share_id).status == "closed" and rig.book.state(eth.share_id).status == "closed"
    assert rig.book.open_shares() == () and rig.env.broker.positions() == ()
    assert rig.gate.paused  # the kill switch pauses first


def test_F12_F10_flatten_with_an_entry_in_flight_is_finished_by_a_second_flatten(new_rig: NewRig) -> None:
    rig = new_rig()
    sol = rig.open_share(1, wallet=WALLET_A, coin="SOL")
    now = rig.xtime.now
    rig.book_at("ETH", "100", now + 1000)
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.OPEN, wallet=WALLET_B, coin="ETH", size="5", ts=now - 100))
    report = rig.mgr.flatten(run_id="flat1")
    assert [p.coin for p in report.in_flight] == ["ETH"]
    rig.step(now + 1000)  # the ETH entry fills now, and the SOL close
    eth = rig.share_of(WALLET_B, "ETH")
    assert eth is not None and eth.status == "open"  # booked, so that the next flatten can see it
    assert rig.book.state(sol.share_id).status == "closed"
    now = rig.xtime.now
    rig.book_at("ETH", "100", now + 1000)
    again = rig.mgr.flatten(run_id="flat2")
    assert all(o.decision.approved for o in again)
    rig.step(now + 1000)
    assert rig.book.open_shares() == () and rig.env.broker.positions() == ()


def test_F12_F11_partial_entry_fill_books_the_filled_quantity_only(new_rig: NewRig) -> None:
    rig = new_rig()
    now = rig.xtime.now
    rig.env.book("SOL", now + 1000, [("100", "0.4")], [("100", "0.4")])
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))  # would be 1.00
    rig.step(now + 1000)
    share = rig.share_of(WALLET_A, "SOL")
    assert share.qty == D("0.40") and share.open_risk_usd == D("0.60")
    assert D(str(rig.active_stops(share.share_id)[0]["qty"])) == D("0.40")
    assert rig.held("SOL").share_qtys == (D("0.40"),)


def test_F12_F11_partial_exit_fill_reduces_the_book_and_the_rest_fills_later(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    now = rig.xtime.now
    rig.env.book("SOL", now + 1000, [("100", "0.4")], [("100", "0.4")])
    rig.book_at("SOL", "100", now + 2000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 100))
    rig.step(now + 1000)
    assert (rig.book.state(share.share_id).status, rig.book.state(share.share_id).qty) == ("open", D("0.60"))
    assert [e["event"] for e in rig.share_events(share.share_id)][-1] == "reduced"
    assert D(str(rig.active_stops(share.share_id)[0]["qty"])) <= D("0.60")  # never a stop larger than the share
    rig.step(now + 2000)
    assert rig.book.state(share.share_id).status == "closed"


def test_F12_F11_liquidation_closes_the_share_frees_the_book_and_is_ledgered(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    rig.mark("SOL", "2")  # far below the 1x liquidation price
    assert rig.book.state(share.share_id).status == "closed"
    assert rig.book.open_shares() == () and rig.env.broker.position("SOL") is None
    assert [e for e in rig.share_events(share.share_id) if e["event"] == "liquidated"]
    assert rig.active_stops() == []
    assert "liquidated" in rig.alert_kinds()


def test_F12_F11_delisting_settles_the_share_and_frees_the_book(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    rig.mgr.advance_to(rig.xtime.now)
    rig.mgr.on_delist("SOL", Price("90"), rig.xtime.now)
    assert rig.book.state(share.share_id).status == "closed"
    assert rig.book.open_shares() == () and rig.env.broker.position("SOL") is None
    assert [e for e in rig.share_events(share.share_id) if e["event"] == "delisted"]
    assert rig.active_stops() == []


def test_F12_F11_exits_and_stops_do_not_depend_on_meta(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    rig.env.meta.fail = True  # the exchange meta endpoint is down (and the snapshot is stale)
    rig.at(rig.xtime.now + 2 * 3_600_000)
    rig.mgr.advance_to(rig.xtime.now)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 100))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"


def test_F12_F11_oversized_close_after_an_unseen_fill_resyncs_alerts_and_retries(new_rig: NewRig) -> None:
    rig = new_rig(exits__trail_start_r=D("5"))
    share = rig.open_share(1)  # 1.00, TP for 0.50 at 103
    now = rig.xtime.now
    rig.book_at("SOL", "103", now + 1000)
    rig.mark("SOL", "103")
    rig.at(now + 1000)
    rig.env.advance(now + 1000)  # the TP fills at the broker; its events never reach the manager
    assert rig.held("SOL").share_qtys == (D("0.50"),)
    assert rig.book.state(share.share_id).qty == D("1.00")  # stale
    now = rig.xtime.now
    rig.book_at("SOL", "103", now + 1000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 100))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"
    assert rig.env.broker.position("SOL") is None
    assert "position_mismatch" in rig.alert_kinds()
    closes = [d for d in rig.decisions() if d.get("action") == "close"]
    assert len(closes) == 2 and closes[-1]["approved"] is True
    assert len({d["client_order_id"] for d in closes}) == 2  # the retry has its own deterministic id
