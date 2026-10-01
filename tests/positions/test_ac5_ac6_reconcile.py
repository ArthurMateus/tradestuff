"""F12.AC5 leader reconciliation, F12.AC6 missed-exit detector, and the broker reconciliation (A7)."""

from __future__ import annotations

from decimal import Decimal as D
from typing import Any

from copytrade.core.domain import ActionKind
from tests.positions.conftest import NewRig
from tests.positions.helpers import SEC, WALLET_A, make_fill, make_signal

INTERVAL_MS = 300 * SEC  # reconcile.interval_s


def held(rig: Any, size: str = "5") -> Any:
    """A share on SOL (leader A, leader size 5), with the leader's own state agreeing."""
    share = rig.open_share(1)
    rig.leader_state.positions[WALLET_A] = {"SOL": size}
    return share


def pass_at(rig: Any, ms: int) -> Any:
    rig.at(ms)
    rig.book_at("SOL", "100", ms + 1000)
    report = rig.mgr.reconcile()
    rig.step(ms + 1000)
    return report


def close_fill(tid: int, at_ms: int, **kw: Any) -> Any:
    return make_fill(tid, side="A", sz="5", start="5", dir_="Close Long", time_ms=at_ms, **kw)


# ------------------------------------------------------------------------------------------------ AC5

def test_F12_AC5_leader_flat_closes_our_share_with_reconcile_close_and_alerts(new_rig: NewRig) -> None:
    rig = new_rig()
    share = held(rig)
    start = rig.xtime.now + INTERVAL_MS
    rig.leader_state.positions[WALLET_A] = {}
    rig.leader_fills.fills[WALLET_A] = [close_fill(9, start - 61 * SEC)]
    pass_at(rig, start)
    assert rig.book.state(share.share_id).status == "closed"
    assert any(o["exit_reason"] == "reconcile_close" for o in rig.orders() if o["action"] == "close")
    assert "reconcile_close" in rig.alert_kinds()
    assert len(rig.records("missed_exit")) == 1  # F12.AC6 runs


def test_F12_AC5_leader_reversed_on_the_coin_closes_our_share(new_rig: NewRig) -> None:
    rig = new_rig()
    share = held(rig)
    start = rig.xtime.now + INTERVAL_MS
    rig.leader_state.positions[WALLET_A] = {"SOL": "-3"}
    pass_at(rig, start)
    assert rig.book.state(share.share_id).status == "closed"
    assert "reconcile_close" in rig.alert_kinds()


def test_F12_AC5_leader_still_long_and_all_fills_seen_changes_nothing(new_rig: NewRig) -> None:
    rig = new_rig()
    share = held(rig)
    start = rig.xtime.now + INTERVAL_MS
    rig.leader_fills.fills[WALLET_A] = [make_fill(1, side="B", sz="5", start="0", dir_="Open Long", time_ms=start - 200_000)]
    orders = len(rig.orders())
    pass_at(rig, start)
    assert len(rig.orders()) == orders and rig.book.state(share.share_id).status == "open"
    assert rig.records("missed_exit") == [] and rig.alert_kinds() == []


def test_F12_AC5_dropped_reduce_that_keeps_the_sign_is_caught_by_the_size_comparison(new_rig: NewRig) -> None:
    rig = new_rig()
    share = held(rig, size="3")  # the leader holds 3, we believe 5
    start = rig.xtime.now + INTERVAL_MS
    rig.leader_fills.fills[WALLET_A] = [
        make_fill(9, side="A", sz="2", start="5", dir_="Close Long", time_ms=start - 61 * SEC)]
    pass_at(rig, start)
    assert rig.book.state(share.share_id).qty == D("0.60")  # the late reduce (2 of 5) was mirrored
    (missed,) = rig.records("missed_exit")
    assert missed["event_type"] == "reduce" and missed["case"] == "orphan"


def test_F12_AC5_size_mismatch_without_any_fetched_fill_still_alerts_and_never_closes(new_rig: NewRig) -> None:
    rig = new_rig()
    share = held(rig, size="3")
    pass_at(rig, rig.xtime.now + INTERVAL_MS)
    assert rig.book.state(share.share_id).status == "open"  # unknowable event: do not guess a close
    assert "leader_mismatch" in rig.alert_kinds()


def test_F12_AC5_failed_leader_state_fetch_closes_nothing_and_alerts(new_rig: NewRig) -> None:
    rig = new_rig()
    share = held(rig)
    rig.leader_state.fail = True
    pass_at(rig, rig.xtime.now + INTERVAL_MS)
    assert rig.book.state(share.share_id).status == "open"
    assert "reconcile_failed" in rig.alert_kinds()


def test_F12_AC5_runs_every_interval_and_after_a_resync(new_rig: NewRig) -> None:
    rig = new_rig()
    held(rig)
    start = rig.xtime.now
    calls = rig.leader_state.calls
    rig.step(start + INTERVAL_MS - 1)
    assert rig.leader_state.calls == calls  # not yet
    rig.step(start + INTERVAL_MS)
    assert rig.leader_state.calls > calls
    calls = rig.leader_state.calls
    rig.mgr.on_resync()
    assert rig.leader_state.calls > calls


# ------------------------------------------------------------------------------------------------ AC6

def test_F12_AC6_dropped_exit_found_by_reconciliation_61s_late_is_a_missed_exit(new_rig: NewRig) -> None:
    rig = new_rig()
    share = held(rig)
    start = rig.xtime.now + INTERVAL_MS
    event_ms = start - 61 * SEC
    rig.leader_state.positions[WALLET_A] = {}
    rig.leader_fills.fills[WALLET_A] = [close_fill(9, event_ms)]
    pass_at(rig, start)
    (rec,) = rig.records("missed_exit")
    assert rec["leader"] == WALLET_A and rec["coin"] == "SOL" and rec["share_id"] == share.share_id
    assert (rec["event_type"], rec["case"], rec["found_by"]) == ("close", "orphan", "reconciliation")
    assert (rec["event_exchange_ms"], rec["detected_ms"], rec["lag_ms"]) == (event_ms, start, 61 * SEC)
    assert rec["missed_exit_id"]


def test_F12_AC6_exit_found_exactly_60s_late_is_not_a_missed_exit(new_rig: NewRig) -> None:
    rig = new_rig()
    share = held(rig)
    start = rig.xtime.now + INTERVAL_MS
    rig.leader_state.positions[WALLET_A] = {}
    rig.leader_fills.fills[WALLET_A] = [close_fill(9, start - 60 * SEC)]
    pass_at(rig, start)
    assert rig.records("missed_exit") == [] and rig.records("go_live_blocker") == []
    assert rig.book.state(share.share_id).status == "closed"  # it is still mirrored at once


def test_F12_AC6_live_exit_mirrored_61s_late_is_a_missed_exit_of_case_late(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 61 * SEC))
    rig.step(now + 1000)
    (rec,) = rig.records("missed_exit")
    assert (rec["case"], rec["found_by"], rec["lag_ms"], rec["event_type"]) == ("late", "live", 61 * SEC, "close")
    assert rig.book.state(share.share_id).status == "closed"  # the late close still goes through the gate


def test_F12_AC6_live_exit_mirrored_60s_after_its_timestamp_is_not_missed(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 60 * SEC))
    assert rig.records("missed_exit") == []


def test_F12_AC6_late_mirror_while_entries_are_paused_is_a_missed_exit_and_no_pause_follows(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.open_share(1)
    rig.gate.pause()
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 61 * SEC))
    assert len(rig.records("missed_exit")) == 1
    rig.gate.resume()
    assert rig.gate.paused is False  # detection itself never paused anything


def test_F12_AC6_detection_never_pauses_entries(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 120 * SEC))
    rig.step(now + 1000)
    assert rig.gate.paused is False
    rig.open_share(3, coin="ETH")  # a new entry still works


def test_F12_AC6_each_missed_exit_writes_a_go_live_blocker_and_alerts_with_the_running_count(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.leader_state.account_value = D("1000")
    rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.REDUCE, size="1", pre="5", post="4", fraction="0.2", ts=now - 61 * SEC))
    rig.step(now + 1000)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(3, ActionKind.CLOSE, size="4", pre="4", ts=now - 61 * SEC))
    records = rig.records("missed_exit")
    assert len(records) == 2 and len({r["missed_exit_id"] for r in records}) == 2  # two on one share
    blockers = rig.records("go_live_blocker")
    assert [b["type"] for b in blockers] == ["ME", "ME"]
    assert [b["missed_exit_id"] for b in blockers] == [r["missed_exit_id"] for r in records]
    messages = [a.message for a in rig.env.alerts.sent if a.kind == "missed_exit"]
    assert len(messages) == 2 and "1/3" in messages[0] and "2/3" in messages[1]
    assert all("ME" in m for m in messages)


def test_F12_AC6_partial_skipped_under_the_ten_dollar_rule_is_not_a_missed_exit(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.leader_state.account_value = D("600")
    rig.open_share(1, notional="40")  # $20
    rig.feed(make_signal(2, ActionKind.REDUCE, size="1", pre="5", post="4", fraction="0.4",
                         ts=rig.xtime.now - 10 * SEC))
    assert rig.records("missed_exit") == [] and len(rig.records("signal_skip")) == 1


def test_F12_AC6_a_skip_recorded_61s_after_the_event_is_a_missed_exit(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.leader_state.account_value = D("600")
    rig.open_share(1, notional="40")
    rig.feed(make_signal(2, ActionKind.REDUCE, size="1", pre="5", post="4", fraction="0.4",
                         ts=rig.xtime.now - 61 * SEC))
    assert len(rig.records("missed_exit")) == 1


# ---------------------------------------------------------------------------------- broker reconciliation (A7)

def test_F12_A7_broker_share_the_book_does_not_know_is_alerted_and_closed(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.env.open_position("buy", "0.5", coin="ETH", coid="orphan1", share="ORPHAN", trade="TORPH",
                          decided=rig.xtime.now)
    start = rig.xtime.now + INTERVAL_MS
    rig.book_at("ETH", "100", start + 1000)
    rig.at(start)
    rig.mgr.reconcile()
    assert "position_mismatch" in rig.alert_kinds()
    rig.step(start + 1000)
    assert rig.env.broker.position("ETH") is None  # an orphaned copy is never left open


def test_F12_A7_booked_share_the_broker_does_not_hold_is_dropped_and_alerted(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    now = rig.xtime.now
    rig.env.submit(rig.env.order("sell", "1.00", coid="out-of-band", action=ActionKind.CLOSE, decided=now,
                                 share=share.share_id, trade=share.trade_id, reason="manual"))
    rig.env.flat_book("SOL", now + 1000, "100")
    rig.env.advance(now + 1000)  # the broker closed it; the manager was never told
    rig.at(now + 1000)
    rig.leader_state.positions[WALLET_A] = {"SOL": "5"}
    rig.mgr.reconcile()
    assert rig.book.state(share.share_id).status == "closed"
    assert rig.book.open_shares() == ()
    assert "position_mismatch" in rig.alert_kinds()
    assert any(e["event"] == "ghost_share_dropped" for e in rig.share_events(share.share_id))


def test_F12_A7_booked_quantity_that_differs_from_the_broker_is_corrected_and_alerted(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    now = rig.xtime.now
    rig.env.submit(rig.env.order("sell", "0.40", coid="out-of-band", action=ActionKind.REDUCE, decided=now,
                                 share=share.share_id, trade=share.trade_id, reason="manual"))
    rig.env.flat_book("SOL", now + 1000, "100")
    rig.env.advance(now + 1000)
    rig.at(now + 1000)
    rig.leader_state.positions[WALLET_A] = {"SOL": "5"}
    rig.mgr.reconcile()
    corrected = rig.book.state(share.share_id)
    assert corrected.status == "open" and corrected.qty == D("0.60")
    assert corrected.open_risk_usd == D("0.60") * D("1.5")
    assert "position_mismatch" in rig.alert_kinds()


def test_F12_A7_agreement_between_book_and_broker_raises_no_alert(new_rig: NewRig) -> None:
    rig = new_rig()
    held(rig)
    rig.mgr.reconcile()
    assert "position_mismatch" not in rig.alert_kinds()


def test_F12_A7_exits_are_not_blocked_by_a_failed_reconcile_or_candle_or_policy_source(new_rig: NewRig) -> None:
    rig = new_rig()
    share = held(rig)
    rig.leader_state.fail = True
    rig.leader_fills.fail = True
    rig.candles.fail = True
    rig.policy.fail = True
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 100))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"


