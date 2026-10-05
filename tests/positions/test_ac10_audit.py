"""F12.AC10 leader-fill audit: schedule, classification, orphans found by audit, incomplete audits and the 72 h bound."""

from __future__ import annotations

from typing import Any

from copytrade.core.domain import ActionKind
from tests.positions.conftest import NewRig
from tests.positions.helpers import SEC, T0, WALLET_A, WALLET_B, make_fill, make_signal

H = 3_600_000
DAY = 24 * H
LAG = 60 * SEC  # exits.missed_exit_max_lag_s


def audit_at(rig: Any, ms: int) -> Any:
    rig.at(ms)
    rig.book_at("SOL", "100", ms + 1000)
    report = rig.mgr.run_fill_audit()
    rig.step(ms + 1000)
    return report


def audit_calls(rig: Any, end_ms: int) -> list[tuple[str, int, int]]:
    """The fetches of the audit itself (its window ends one lag before the audit time), not the reconciliation's."""
    return [c for c in rig.leader_fills.calls if c[2] == end_ms - LAG]


def setup_open(rig: Any) -> Any:
    share = rig.open_share(1)
    rig.leader_state.positions[WALLET_A] = {"SOL": "5"}
    return share


def test_F12_AC10_audit_window_ends_one_missed_exit_lag_before_now_and_starts_at_the_previous_end(
    new_rig: NewRig,
) -> None:
    rig = new_rig()
    setup_open(rig)
    first = T0 + DAY
    audit_at(rig, first)
    assert audit_calls(rig, first) == [(WALLET_A, T0, first - LAG)]
    second = first + DAY
    audit_at(rig, second)
    assert audit_calls(rig, second) == [(WALLET_A, first - LAG, second - LAG)]


def test_F12_AC10_a_reduce_dropped_by_a_dead_subscription_is_found_as_an_orphan_by_the_daily_audit(
    new_rig: NewRig,
) -> None:
    rig = new_rig()
    share = setup_open(rig)
    rig.leader_state.positions[WALLET_A] = {"SOL": "3"}
    event_ms = T0 + 10 * 60_000
    rig.leader_fills.fills[WALLET_A] = [
        make_fill(9, side="A", sz="2", start="5", dir_="Close Long", time_ms=event_ms)]
    audit_at(rig, T0 + DAY)
    (rec,) = rig.records("missed_exit")
    assert (rec["case"], rec["found_by"], rec["event_type"]) == ("orphan", "daily_audit", "reduce")
    assert (rec["share_id"], rec["event_exchange_ms"]) == (share.share_id, event_ms)
    assert rig.records("go_live_blocker")[0]["type"] == "ME"
    assert rig.book.state(share.share_id).qty < share.qty  # brought in line with the leader at once


def test_F12_AC10_a_close_and_reopen_between_two_reconciliations_is_found_the_same_way(new_rig: NewRig) -> None:
    rig = new_rig()
    setup_open(rig)  # the leader is long 5 again at the audit, so only the audit can see the close
    rig.leader_fills.fills[WALLET_A] = [
        make_fill(8, side="A", sz="5", start="5", dir_="Close Long", time_ms=T0 + 100_000),
        make_fill(9, side="B", sz="5", start="0", dir_="Open Long", time_ms=T0 + 130_000)]
    audit_at(rig, T0 + DAY)
    assert [r["event_type"] for r in rig.records("missed_exit")] == ["close"]


def test_F12_AC10_a_leader_close_that_our_own_stop_closes_5_minutes_later_is_a_missed_exit(new_rig: NewRig) -> None:
    rig = new_rig(reconcile__interval_s=600)
    share = setup_open(rig)
    event_ms = rig.xtime.now + 60 * SEC
    rig.leader_fills.fills[WALLET_A] = [
        make_fill(9, side="A", sz="5", start="5", dir_="Close Long", time_ms=event_ms)]
    rig.at(event_ms + 5 * 60_000)
    rig.mark_and_fill("SOL", "98.4")  # our stop closes the share 5 minutes after the leader's close
    assert rig.book.state(share.share_id).status == "closed"
    audit_at(rig, T0 + DAY)
    assert [(r["case"], r["found_by"]) for r in rig.records("missed_exit")] == [("orphan", "daily_audit")]


def test_F12_AC10_exit_closed_by_our_stop_exactly_60s_later_is_handled_and_61s_is_missed(new_rig: NewRig) -> None:
    results = []
    for delay_ms in (60 * SEC, 61 * SEC):
        rig = new_rig(reconcile__interval_s=600)
        setup_open(rig)
        event_ms = rig.xtime.now + 10 * SEC
        rig.leader_fills.fills[WALLET_A] = [
            make_fill(9, side="A", sz="5", start="5", dir_="Close Long", time_ms=event_ms)]
        rig.at(event_ms + delay_ms - 1000)  # the mark; the stop fills one ack delay later
        rig.mark_and_fill("SOL", "98.4")
        audit_at(rig, T0 + DAY)
        results.append(len(rig.records("missed_exit")))
    assert results == [0, 1]


def test_F12_AC10_events_on_coins_where_we_held_no_share_are_not_classified(new_rig: NewRig) -> None:
    rig = new_rig()
    setup_open(rig)
    rig.leader_fills.fills[WALLET_A] = [
        make_fill(9, side="A", sz="5", start="5", dir_="Close Long", time_ms=T0 + 100_000, wallet_coin="ETH")]
    audit_at(rig, T0 + DAY)
    assert rig.records("missed_exit") == []


def test_F12_AC10_an_exit_mirrored_in_time_is_not_a_missed_exit(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.REDUCE, size="1", pre="5", post="4", fraction="0.2", ts=now - 10 * SEC))
    rig.step(now + 1000)
    rig.leader_fills.fills[WALLET_A] = [
        make_fill(2, side="A", sz="1", start="5", dir_="Close Long", time_ms=now - 10 * SEC)]
    audit_at(rig, T0 + DAY)
    assert rig.records("missed_exit") == []


def test_F12_AC10_an_exit_already_ledgered_live_is_not_ledgered_again_by_the_audit(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.REDUCE, size="1", pre="5", post="4", fraction="0.2", ts=now - 61 * SEC))
    rig.step(now + 1000)
    rig.leader_fills.fills[WALLET_A] = [
        make_fill(2, side="A", sz="1", start="5", dir_="Close Long", time_ms=now - 61 * SEC)]
    audit_at(rig, T0 + DAY)
    assert len(rig.records("missed_exit")) == 1


def test_F12_AC10_only_leaders_with_a_share_open_since_the_last_audit_are_fetched(new_rig: NewRig) -> None:
    rig = new_rig()
    setup_open(rig)
    audit_at(rig, T0 + DAY)
    assert {c[0] for c in audit_calls(rig, T0 + DAY)} == {WALLET_A}
    assert all(c[0] != WALLET_B for c in rig.leader_fills.calls)


def test_F12_AC10_the_audit_runs_when_due_from_the_supervisor_loop(new_rig: NewRig) -> None:
    rig = new_rig()
    setup_open(rig)
    rig.step(T0 + DAY - 1)
    assert audit_calls(rig, T0 + DAY - 1) == []
    rig.step(T0 + DAY)
    assert audit_calls(rig, T0 + DAY) != []


def test_F12_AC10_each_audit_is_ledgered_with_its_interval_and_completeness(new_rig: NewRig) -> None:
    rig = new_rig()
    setup_open(rig)
    audit_at(rig, T0 + DAY)
    (rec,) = [r for r in rig.records("fill_audit") if r["leader"] == WALLET_A]
    assert (rec["start_ms"], rec["end_ms"], rec["complete"]) == (T0, T0 + DAY - LAG, True)


def test_F12_AC10_unreachable_71h_then_retrieved_gives_no_breach(new_rig: NewRig) -> None:
    rig = new_rig()
    setup_open(rig)
    first = T0 + DAY
    rig.leader_fills.fail = True
    audit_at(rig, first)
    assert rig.records("fill_audit")[-1]["complete"] is False
    audit_at(rig, first + 71 * H)  # still down at 71 h
    rig.leader_fills.fail = False
    audit_at(rig, first + 71 * H + 15 * 60_000)  # retrieved within 72 h of the first attempt
    assert rig.records("audit_breach") == []
    assert rig.records("fill_audit")[-1]["complete"] is True


def test_F12_AC10_unreachable_72h_is_a_breach_at_the_start_of_the_stretch(new_rig: NewRig) -> None:
    rig = new_rig()
    setup_open(rig)
    first = T0 + DAY
    rig.leader_fills.fail = True
    audit_at(rig, first)
    audit_at(rig, first + 72 * H)
    (breach,) = rig.records("audit_breach")
    assert (breach["leader"], breach["stretch_start_ms"]) == (WALLET_A, T0)


def test_F12_AC10_a_failing_audit_does_not_stop_exits(new_rig: NewRig) -> None:
    rig = new_rig()
    share = setup_open(rig)
    rig.leader_fills.fail = True
    audit_at(rig, T0 + DAY)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(5, ActionKind.CLOSE, ts=now - 100))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"
