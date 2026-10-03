"""R0.AC5 (reload round trips), R0.AC6 (uncertain state) and R0.AC7 (corrupt ledger). Run, stop (or hard-kill),
restart: same positions, shares, stops, follow state; old tokens cannot replay; pending exits are re-queued under new
client order ids; no duplicate_order refusals. Real runner, real ledger, real gate/broker/manager; only Hyperliquid and
Telegram are loopback fakes. See the test plan for the pinned reload design (broker state is replayed from the ledger,
the manager/book state comes from the latest ``runner_checkpoint`` record)."""

from __future__ import annotations

import io
import threading
from decimal import Decimal
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from copytrade.core.errors import CopytradeError
from copytrade.core.money import Price, Qty
from copytrade.ledger.errors import LedgerCorruptError
from copytrade.paper.gate import GateAuthority
from copytrade.paper.types import OrderIntent
from copytrade.runner import reload as rl
from copytrade.runner.app import run_app
from copytrade.runner.wiring import build_runner
from tests.hl.ws_server import wait_for
from tests.runner.fake_hl import fill_json
from tests.runner.world import ALERTS_CHAT, LEADER, T0, World

OLD_KEY = b"k" * 32


def fingerprint(runner: Any) -> tuple[Any, ...]:
    positions = tuple(
        (p.coin, p.qty, p.avg_entry_px, p.leverage, p.share_ids, p.share_qtys) for p in runner.broker.positions()
    )
    stops = sorted(
        (s.coin, s.kind, s.side, s.qty, s.trigger_px, s.share_id) for s in runner.broker.stops()
    )
    shares = sorted(
        (
            s.share_id, s.trade_id, s.signal_id, s.leader, s.coin, s.is_long, s.status, s.qty, s.entry_px,
            s.initial_stop_px, s.current_stop_px, s.atr, s.best_px, s.tp_done,
        )
        for s in runner.book.states()
    )
    return positions, stops, shares, runner.broker.cash_usd(), runner.follow.followed


def assert_no_duplicates(world: World) -> None:
    for record in world.records("risk_decision"):
        assert record.payload["reason"] != "duplicate_order"
    for record in world.records("paper_reject"):
        assert record.payload["reason"] not in ("duplicate_client_order_id", "gate_token_reused", "invalid_gate_token")
    assert "duplicate" not in world.alert_kinds_sent()


def opened_world(new_world: Any, **config: Any) -> tuple[World, Any]:
    world: World = new_world(**config)
    world.seed_follow()
    runner, _ = world.start(gate_key=OLD_KEY)
    world.leader_open(runner)
    world.step(runner, 3)
    assert runner.broker.position("SOL") is not None and runner.broker.stops()
    return world, runner


# ------------------------------------------------------------------------------------------ AC5 round trips


@pytest.mark.parametrize("how", ["clean_stop", "hard_kill"])
def test_R0_AC5_restart_restores_positions_shares_stops_cash_and_follow_state(new_world: Any, how: str) -> None:
    world, run1 = opened_world(new_world)
    before = fingerprint(run1)
    if how == "clean_stop":
        assert run1.stop() == 0
    else:
        world.hard_kill(run1)
    run2, report = world.start()
    assert report.uncertain == () and report.entries_blocked is False
    assert report.restored_positions == 1 and report.restored_stops == len(before[1])
    assert fingerprint(run2) == before
    world.step(run2, 10)
    assert fingerprint(run2) == before  # nothing drifted after the first steps either
    assert_no_duplicates(world)


def test_R0_AC5_restored_stops_are_registered_under_new_client_order_ids(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    old_ids = {s.client_order_id for s in run1.broker.stops()}
    run1.stop()
    run2, _ = world.start()
    new_ids = {s.client_order_id for s in run2.broker.stops()}
    assert new_ids and not (new_ids & old_ids)
    assert all(world_ledger_has(world, cid) for cid in new_ids)  # they are in the ledger: a later restart sees them


def world_ledger_has(world: World, cid: str) -> bool:
    return any(r.client_order_id == cid for r in world.records())


def test_R0_AC5_a_restored_stop_still_triggers_and_closes_the_position(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    trigger = min(s.trigger_px for s in run1.broker.stops() if s.kind == "sl")
    run1.stop()
    run2, _ = world.start()
    world.hl.mids["SOL"] = str(trigger - 1)
    world.run_until(run2, lambda: run2.broker.position("SOL") is None)
    fills = [r for r in world.records("fill") if r.payload["exit_reason"] == "stop_loss"]
    assert len(fills) == 1
    assert_no_duplicates(world)


def test_R0_AC5_old_gate_tokens_cannot_replay_after_a_restart(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    position = run1.broker.position("SOL")
    assert position is not None
    now = run1.last_advanced_ms
    assert now is not None
    intent = OrderIntent(
        client_order_id="replay-1", coin="SOL", side="sell", qty=Qty(position.qty), action=ActionKind.CLOSE,
        decided_at_ms=now, decision_px=Price("100"), trade_id="t", share_id=position.share_ids[0], leverage=None,
        exit_reason="manual",
    )
    old_token = GateAuthority(OLD_KEY).issue(intent)  # run 1 was started with OLD_KEY
    run1.stop()
    run2, _ = world.start()  # a fresh per-process key
    result = run2.broker.submit(intent, old_token)
    assert (result.accepted, result.reason) == (False, "invalid_gate_token")
    assert run2.broker.position("SOL") is not None  # and nothing was closed


def test_R0_AC5_the_follow_state_is_restored_and_the_leader_is_resubscribed(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    run1.stop()
    run2, _ = world.start()
    assert run2.follow.followed == frozenset({LEADER})
    world.subscribe_ready(run2)
    assert LEADER in run2.follow.subscribed


def test_R0_AC5_a_replayed_leader_fill_after_a_restart_creates_no_second_signal_or_order(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    orders_before = len(world.records("paper_order"))
    signals_before = len(world.records("signal"))
    run1.stop()
    run2, _ = world.start()
    world.subscribe_ready(run2)
    replay = next(f for f in world.hl.leader_fills[LEADER.lower()] if f["tid"] == 1)  # the very same fill (tid 1, the one run 1 opened with) comes again, e.g. in a resync snapshot
    world.hl.push_user_fills(LEADER, [replay], snapshot=True)
    world.step(run2, 15, ms=200)
    assert len(world.records("signal")) == signals_before
    assert len(world.records("paper_order")) == orders_before
    assert_no_duplicates(world)


def test_R0_AC5_a_dropped_leader_with_an_open_share_stays_subscribed_after_a_restart(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    run1.stop()
    world.seed_ledger(
        [
            (
                "select_cycle",
                {
                    "t_ms": T0 + 600_000, "status": "applied", "eligible_count": 0, "followed": [],
                    "decisions": [{"kind": "drop", "wallet": LEADER, "replaces": None, "reason": "ineligible"}],
                },
            )
        ]
    )
    run2, report = world.start()
    assert report.uncertain == ()
    assert run2.follow.followed == frozenset()
    assert LEADER in run2.follow.subscribed  # held for its open share: its exit must still be mirrored
    world.subscribe_ready(run2)


def test_R0_AC5_a_leader_that_was_paused_by_the_copy_result_rule_is_not_restored_as_followed(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    world.seed_ledger([("leader_paused", {"wallet": LEADER, "t_ms": T0 - 1_000})])
    run1, _ = world.start()
    assert LEADER not in run1.follow.followed


def test_R0_AC5_after_a_restart_stop_ids_and_synthetic_tids_do_not_repeat(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    run1.stop()
    n_stops = len(world.records("paper_stop"))
    run2, _ = world.start()
    world.hl.mids["SOL"] = "102.0"  # +1.33 R: the trailing stop ratchets, a new stop id is needed (below the 2 R TP)
    world.run_until(run2, lambda: len(world.records("paper_stop")) > n_stops + len(run2.broker.stops()))
    world.step(run2, 5)
    assert_no_duplicates(world)
    ids = [r.client_order_id for r in world.records("paper_stop")]
    assert len(ids) == len(set(ids))


def test_R0_AC5_the_order_rate_window_survives_a_restart(new_world: Any) -> None:
    world, run1 = opened_world(new_world, risk__max_orders_per_min=1)
    run1.stop()
    run2, _ = world.start()
    world.hl.leader_positions[LEADER.lower()] = [("SOL", "5.0", "100.0"), ("ETH", "1.0", "3400.0")]
    world.subscribe_ready(run2)
    world.hl.push_user_fills(
        LEADER,
        [fill_json(50, coin="ETH", side="B", sz="1.0", px="3400.0", direction="Open Long", time_ms=world.exchange_ms() - 100)],
    )
    world.step(run2, 30, ms=200)
    reasons = [r.payload["reason"] for r in world.records("risk_decision") if r.payload["coin"] == "ETH"]
    assert "rate_limit" in reasons and run2.broker.position("ETH") is None


def test_R0_AC5_a_checkpoint_is_written_while_running_and_stop_writes_the_last_one_and_a_stop_record(
    new_world: Any,
) -> None:
    world, run1 = opened_world(new_world)
    assert world.records(rl.KIND_CHECKPOINT), "written while running, not only at the end"
    assert world.records(rl.KIND_CHECKPOINT)[-1].seq > world.records("fill")[-1].seq  # it knows the entry fill
    run1.stop()
    assert world.records(rl.KIND_CHECKPOINT)[-1].seq < world.records("runner_stop")[-1].seq
    assert world.records("runner_stop")[-1].payload["run_id"] == run1.run_id


# --------------------------------------------------------------------- pending exits and entries at the restart


def pending_close(new_world: Any) -> tuple[World, Any, set[str]]:
    world, run1 = opened_world(new_world)
    world.leader_close()
    for _ in range(8):  # no fresh books: the close order cannot fill and stays pending
        world.step(run1, 1, ms=300, pump=False)
        if run1.broker.pending_exits():
            break
    old = {e.client_order_id for e in run1.broker.pending_exits()}
    assert old, "the close must be pending"
    return world, run1, old


@pytest.mark.parametrize("how", ["clean_stop", "hard_kill"])
def test_R0_AC5_pending_exits_are_requeued_under_new_ids_and_then_fill_exactly_once(new_world: Any, how: str) -> None:
    world, run1, old = pending_close(new_world)
    if how == "clean_stop":
        run1.stop()
    else:
        world.hard_kill(run1)
    run2, report = world.start()
    assert {r.old_client_order_id for r in report.requeued_exits} == old
    new = {r.new_client_order_id for r in report.requeued_exits}
    assert new and not (new & old)
    assert {e.client_order_id for e in run2.broker.pending_exits()} == new
    assert report.uncertain == ()
    world.run_until(run2, lambda: run2.broker.position("SOL") is None)
    exits = [r for r in world.records("fill") if r.payload["exit_reason"] == "leader_close"]
    assert len(exits) == 1
    assert run2.book.states()[0].status == "closed"
    assert_no_duplicates(world)


def test_R0_AC5_a_pending_entry_is_dropped_at_a_restart_not_resurrected(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    run1, _ = world.start()
    world.subscribe_ready(run1)
    world.hl.leader_positions[LEADER.lower()] = [("SOL", "5.0", "100.0")]
    world.hl.push_user_fills(
        LEADER,
        [fill_json(1, coin="SOL", side="B", sz="5.0", px="100.0", direction="Open Long", time_ms=world.exchange_ms() - 200)],
    )
    for _ in range(10):  # entry accepted, but no fresh book can fill it
        world.step(run1, 1, ms=100, pump=False)
        if run1.broker.pending_entries():
            break
    assert run1.broker.pending_entries()
    old = {e.client_order_id for e in run1.broker.pending_entries()}
    world.hard_kill(run1)
    run2, report = world.start()
    assert run2.broker.pending_entries() == () and run2.broker.positions() == ()
    cancelled = {r.client_order_id or r.payload["client_order_id"] for r in world.records("paper_cancel")}
    assert old <= cancelled  # the ledger says what happened to them
    assert all(s.status != "pending_entry" for s in run2.book.states())
    assert report.restored_positions == 0


# ------------------------------------------------------------------------------------- AC6 uncertain state


def alert_arrived(world: World, code: str) -> None:
    wait_for(
        lambda: any(rl.ALERT_STARTUP_UNCERTAIN in t and code in t for t in world.tg.sent(ALERTS_CHAT)),
        what=f"the startup_uncertain alert naming {code}",
    )


def test_R0_AC6_an_unknown_coin_is_flagged_alerted_and_entries_are_refused_until_the_po_acknowledges(
    new_world: Any,
) -> None:
    world, run1 = opened_world(new_world)
    run1.stop()
    world.hl.universe[:] = [u for u in world.hl.universe if u["name"] != "SOL"]  # the exchange no longer lists SOL
    run2, report = world.start()
    assert [u.code for u in report.uncertain] == [rl.UNKNOWN_COIN] and "SOL" in report.uncertain[0].detail
    assert report.entries_blocked and run2.entries_blocked and run2.gate.paused
    assert report.restored_positions == 1  # flagged, not dropped
    alert_arrived(world, rl.UNKNOWN_COIN)
    # the PO acknowledges with /resume on Telegram
    world.telegram_ready()
    world.tg.push_text("/resume")
    wait_for(lambda: not run2.gate.paused, what="the acknowledgement")
    assert not run2.entries_blocked


def test_R0_AC6_new_entries_are_refused_while_unacknowledged_and_work_again_after_resume(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    run1.stop()
    # an exit state that cannot be proven: an unfinished exit order for a share the broker does not hold
    world.seed_ledger(
        [
            (
                "paper_order",
                {
                    "coin": "SOL", "side": "sell", "action": "close", "requested_qty": Decimal("1"), "qty": Decimal("1"),
                    "decision_px": Decimal("100"), "decided_at_ms": T0, "trade_id": "tX", "share_id": "ghost-share",
                    "leverage": None, "exit_reason": "leader_close",
                },
                "ghost-exit-1",
            )
        ]
    )
    run2, report = world.start()
    try:
        assert rl.EXIT_STATE_UNPROVEN in [u.code for u in report.uncertain] and report.entries_blocked
        assert any("ghost-exit-1" in u.detail or "ghost-share" in u.detail for u in report.uncertain)
        world.hl.leader_positions[LEADER.lower()] = [("SOL", "5.0", "100.0"), ("ETH", "1.0", "3400.0")]
        world.subscribe_ready(run2)
        world.hl.push_user_fills(
            LEADER,
            [fill_json(60, coin="ETH", side="B", sz="1.0", px="3400.0", direction="Open Long", time_ms=world.exchange_ms() - 100)],
        )
        world.step(run2, 20, ms=200)
        assert run2.broker.position("ETH") is None
        assert "paused" in [r.payload["reason"] for r in world.records("risk_decision") if r.payload["coin"] == "ETH"]
        world.telegram_ready()
        world.tg.push_text("/resume")
        wait_for(lambda: not run2.gate.paused, what="the acknowledgement")
        world.hl.push_user_fills(
            LEADER,
            [fill_json(61, coin="ETH", side="B", sz="1.0", px="3400.0", direction="Open Long", time_ms=world.exchange_ms() - 100)],
        )

        def eth_filled() -> bool:
            world.pump_market(("ETH",))  # world.step pumps SOL only: keep an ETH book available at the fill
            return run2.broker.position("ETH") is not None

        world.run_until(run2, eth_filled, max_steps=600)
    finally:
        run2.stop()


def test_R0_AC6_exits_and_stops_of_restored_positions_keep_working_while_entries_are_refused(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    run1.stop()
    (world.state_dir / "risk_state.json").unlink()
    run2, report = world.start()
    assert rl.MISSING_RISK_STATE_FILE in [u.code for u in report.uncertain] and run2.entries_blocked
    world.leader_close()
    world.pump_market()
    world.run_until(run2, lambda: run2.broker.position("SOL") is None)  # the mirrored exit went out
    assert [r for r in world.records("fill") if r.payload["exit_reason"] == "leader_close"]


def test_R0_AC6_a_share_without_a_position_is_flagged(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    position = run1.broker.position("SOL")
    assert position is not None
    share_id = position.share_ids[0]
    qty, trade = position.qty, run1.book.states()[0].trade_id
    run1.stop()
    from copytrade.core.clock import TimeSource, Timestamp
    from copytrade.core.money import Fee, Funding, Pnl
    from copytrade.ledger.records import FillRecord, TradeRecord
    from copytrade.ledger.store import Ledger

    ledger = Ledger.open(world.ledger_dir, clock=world.clock)
    now = Timestamp(world.exchange_ms(), TimeSource.DERIVED)
    ledger.append_fill(
        FillRecord(
            time=now, coin="SOL", side="sell", qty=Qty(abs(qty)), price=Price("100"), fee=Fee("0.01"),
            funding=Funding("0"), client_order_id="late-close", trade_id=trade, share_id=share_id,
            exit_reason="leader_close",
        )
    )
    ledger.append_trade(TradeRecord(trade_id=trade, share_id=share_id, coin="SOL", closed_at=now, pnl_usd=Pnl("0"), flags=frozenset()))
    ledger.close()  # a close fill the last checkpoint does not know about
    run2, report = world.start()
    assert rl.SHARE_WITHOUT_POSITION in [u.code for u in report.uncertain]
    assert run2.broker.positions() == () and run2.entries_blocked
    alert_arrived(world, rl.SHARE_WITHOUT_POSITION)


def test_R0_AC6_a_position_without_a_share_is_flagged_and_left_open(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    run1, _ = world.start(gate_key=OLD_KEY)
    world.step(run1, 3)
    now = run1.last_advanced_ms
    assert now is not None
    intent = OrderIntent(
        client_order_id="orphan-open", coin="SOL", side="buy", qty=Qty("1"), action=ActionKind.OPEN,
        decided_at_ms=now, decision_px=Price("100"), trade_id="t-orphan", share_id="orphan-share", leverage=2,
        exit_reason=None,
    )
    assert run1.broker.submit(intent, GateAuthority(OLD_KEY).issue(intent)).accepted  # a position the manager never booked
    world.run_until(run1, lambda: run1.broker.position("SOL") is not None, ms=1000)
    world.hard_kill(run1)
    run2, report = world.start()
    assert rl.POSITION_WITHOUT_SHARE in [u.code for u in report.uncertain] and report.entries_blocked
    assert run2.broker.position("SOL") is not None  # never silently dropped
    alert_arrived(world, rl.POSITION_WITHOUT_SHARE)


def test_R0_AC6_a_clean_first_start_flags_nothing_and_does_not_pause(new_world: Any) -> None:
    world: World = new_world()
    run1, report = world.start()
    assert report.uncertain == () and not report.entries_blocked and not run1.gate.paused
    assert not any(rl.ALERT_STARTUP_UNCERTAIN in t for t in world.tg.sent())


def test_R0_AC6_a_manual_pause_survives_a_restart_and_is_not_an_uncertainty(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    run1.gate.pause()
    run1.stop()
    run2, report = world.start()
    assert report.uncertain == () and run2.gate.paused and run2.entries_blocked


# ------------------------------------------------------------------------------------- AC7 corrupt ledger


def corrupt_middle_line(world: World) -> bytes:
    path = world.ledger_dir / "ledger.jsonl"
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(lines[:2] + lines[3:]))  # delete a middle record: the chain breaks
    return path.read_bytes()


def test_R0_AC7_a_corrupt_ledger_refuses_to_start_and_touches_nothing(new_world: Any, network_guard: Any) -> None:
    world, run1 = opened_world(new_world)
    run1.stop()
    damaged = corrupt_middle_line(world)
    connects, threads = len(network_guard.all_connects), threading.active_count()
    http_before, tg_before = len(world.hl.http_requests), world.tg.request_count()
    with pytest.raises(LedgerCorruptError):
        build_runner(world.root or world.write_config(), world.env, world.deps())
    assert (world.ledger_dir / "ledger.jsonl").read_bytes() == damaged  # not repaired, not extended
    assert len(network_guard.all_connects) == connects and threading.active_count() == threads
    assert len(world.hl.http_requests) == http_before and world.tg.request_count() == tg_before


def test_R0_AC7_run_app_exits_non_zero_with_one_line_naming_the_record(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    run1.stop()
    corrupt_middle_line(world)
    err = io.StringIO()
    code = run_app(world.root or world.write_config(), world.env, deps=world.deps(), stop=threading.Event(), out=io.StringIO(), err=err)
    assert code == 1
    lines = [ln for ln in err.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("copytrade:")
    assert issubclass(LedgerCorruptError, CopytradeError)


def test_R0_AC7_a_torn_final_line_is_repaired_by_the_ledger_and_the_start_goes_on(new_world: Any) -> None:
    world, run1 = opened_world(new_world)
    run1.stop()
    path = world.ledger_dir / "ledger.jsonl"
    path.write_bytes(path.read_bytes() + b'{"seq": 99999, "kind": "x"')  # a crash mid-append (F2 repairs it)
    run2, report = world.start()
    assert report.restored_positions == 1
