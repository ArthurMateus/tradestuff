"""R0 developer tests: the broker's books replayed from the ledger (``replay_broker``) and installed into a fresh broker
(``PaperBroker.restore``). Real broker, real ledger; only books, meta, funding and the clock are fakes."""

from __future__ import annotations

from decimal import Decimal

import pytest

from copytrade.core.domain import ActionKind
from copytrade.ledger.store import read_records
from copytrade.paper.errors import PaperBrokerFailedError
from copytrade.paper.gate import GateAuthority
from copytrade.paper.restore import BrokerSnapshot, replay_broker
from copytrade.paper.settings import PaperSettings
from copytrade.paper.types import CoinMeta
from tests.paper.helpers import D0, HOUR_MS, Env, build_env, restart

D = Decimal


def snapshot_of(env: Env) -> BrokerSnapshot:
    return replay_broker(read_records(env.ledger_dir), PaperSettings.from_config(env.config))


def thirds_book(env: Env, t: int, coin: str = "SOL") -> None:
    """Asks at three prices so the fill's average price does not terminate (the cost must still be exact)."""
    env.book(coin, t, [("99.9", "100")], [("100.1", "0.30"), ("100.3", "0.30"), ("100.7", "0.40")])


def test_replay_matches_a_broker_that_opened_scaled_in_and_partly_closed(tmp_path) -> None:
    env = build_env(tmp_path)
    thirds_book(env, D0 + 1000)
    env.advance(D0)
    assert env.submit(env.order("buy", "1.0", coid="o1", decided=D0)).accepted
    env.advance(D0 + 1000)
    assert env.stop("sl", "sell", "1.0", "95", coid="s1").accepted
    env.book("SOL", D0 + 5000, [("101.1", "100")], [("101.3", "100")])
    env.advance(D0 + 4000)
    reduce = env.order("sell", "0.37", coid="x1", action=ActionKind.REDUCE, decided=D0 + 4000, reason="leader_reduce")
    assert env.submit(reduce).accepted
    env.advance(D0 + 5000)
    snap = snapshot_of(env)
    view = env.broker.position("SOL")
    assert view is not None
    (position,) = snap.positions
    assert position.leverage == view.leverage
    assert tuple(share.share_id for share in position.shares) == view.share_ids
    assert snap.cash == env.broker.cash_usd()
    assert [s.client_order_id for s in snap.stops] == ["s1"]
    assert snap.entries == () and snap.exits == () and snap.unproven_exits == ()
    fresh = restart(env)
    result = fresh.broker.restore(snap, now_ms=D0 + 6000, rules=env.meta.meta)
    restored = fresh.broker.position("SOL")
    assert restored == view  # exact: quantities, average price (a repeating decimal), margin, liquidation price
    assert fresh.broker.cash_usd() == env.broker.cash_usd()
    assert [r.old_client_order_id for r in result.stops] == ["s1"]


def test_replay_of_a_closed_trade_leaves_no_position_and_the_realised_cash(tmp_path) -> None:
    env = build_env(tmp_path)
    env.open_position("buy", "1.0", px="100")
    env.flat_book("SOL", D0 + 4000, "110")
    env.advance(D0 + 3000)
    close = env.order("sell", "1.0", coid="c1", action=ActionKind.CLOSE, decided=D0 + 3000, reason="leader_close")
    assert env.submit(close).accepted
    env.advance(D0 + 4000)
    assert env.broker.position("SOL") is None
    snap = snapshot_of(env)
    assert snap.positions == () and snap.cash == env.broker.cash_usd()
    assert ("S1", "SOL") in snap.retired


def test_a_pending_exit_is_requeued_under_a_new_id_and_a_second_restart_does_not_grow_the_suffix(tmp_path) -> None:
    env = build_env(tmp_path)
    env.open_position("buy", "1.0", px="100")
    env.advance(D0 + 2000)
    close = env.order("sell", "1.0", coid="c1", action=ActionKind.CLOSE, decided=D0 + 2000, reason="leader_close")
    assert env.submit(close).accepted  # no book at or after its fill time: it stays pending
    assert [e.client_order_id for e in env.broker.pending_exits()] == ["c1"]
    snap = snapshot_of(env)
    assert [e.client_order_id for e in snap.exits] == ["c1"] and snap.exits[0].qty == D("1.0")
    first = restart(env)
    r1 = first.broker.restore(snap, now_ms=D0 + 3000, rules=env.meta.meta)
    assert [(r.old_client_order_id, r.new_client_order_id) for r in r1.exits] == [("c1", "c1:r1")]
    assert [e.client_order_id for e in first.broker.pending_exits()] == ["c1:r1"]
    second = restart(first)
    r2 = second.broker.restore(snapshot_of(first), now_ms=D0 + 4000, rules=env.meta.meta)
    assert [r.new_client_order_id for r in r2.exits] == ["c1:r2"]  # not c1:r1:r1
    second.flat_book("SOL", D0 + 6000, "100")
    second.advance(D0 + 6000)
    assert second.broker.position("SOL") is None  # the re-queued exit fills exactly once
    assert len([r for r in second.records("fill") if r.payload["exit_reason"] == "leader_close"]) == 1


def test_pending_entries_are_dropped_and_unprovable_exits_cancelled_with_a_reason(tmp_path) -> None:
    env = build_env(tmp_path)
    env.advance(D0)
    assert env.submit(env.order("buy", "1.0", coid="e1", decided=D0)).accepted  # never filled: no book
    ghost = env.order("sell", "1.0", coid="g1", coin="SOL", action=ActionKind.CLOSE, share="NOPE", reason="x")
    assert not env.submit(ghost).accepted  # the broker refuses it, so craft the ledger record the way a crash would
    env.ledger.append(
        "paper_order",
        {
            "coin": "SOL", "side": "sell", "action": "close", "requested_qty": D("1"), "qty": D("1"),
            "decision_px": D("100"), "decided_at_ms": D0, "trade_id": "T9", "share_id": "ghost", "leverage": None,
            "exit_reason": "x",
        },
        client_order_id="g2",
    )
    snap = snapshot_of(env)
    assert snap.entries == ("e1",) and [e.client_order_id for e in snap.unproven_exits] == ["g2"]
    fresh = restart(env)
    result = fresh.broker.restore(snap, now_ms=D0 + 1000, rules=env.meta.meta)
    assert result.dropped_entries == ("e1",) and result.dropped_exits == ("g2",)
    assert fresh.broker.pending_entries() == () and fresh.broker.pending_exits() == ()
    reasons = {(r.payload["client_order_id"], r.payload["reason"]) for r in fresh.records("paper_cancel")}
    assert ("e1", "restart") in reasons and ("g2", "restart_unproven") in reasons
    assert snapshot_of(fresh).entries == () and snapshot_of(fresh).unproven_exits == ()  # a second restart is quiet


def test_a_triggered_stop_becomes_a_pending_exit_with_its_stop_reason(tmp_path) -> None:
    env = build_env(tmp_path)
    env.open_position("buy", "1.0", px="100")
    assert env.stop("sl", "sell", "1.0", "98", coid="sl1").accepted
    env.mark("SOL", "97", D0 + 2000)
    assert [e.client_order_id for e in env.broker.pending_exits()] == ["sl1"] and env.broker.stops() == ()
    snap = snapshot_of(env)
    assert snap.stops == () and [(e.client_order_id, e.exit_reason) for e in snap.exits] == [("sl1", "stop_loss")]


def test_a_liquidation_and_a_funding_payment_are_replayed(tmp_path) -> None:
    env = build_env(tmp_path)
    env.open_position("buy", "1.0", px="100", leverage=20)
    env.funding.set("SOL", (D0 // HOUR_MS + 1) * HOUR_MS, "0.0001", "100")
    env.advance((D0 // HOUR_MS + 1) * HOUR_MS + 1000)
    assert env.records("paper_funding")
    snap = snapshot_of(env)
    assert snap.cash == env.broker.cash_usd() and snap.last_funding_hour_ms is not None
    view = env.broker.position("SOL")
    assert view is not None
    env.mark("SOL", str(view.liquidation_px - 1), D0 + HOUR_MS + 5000)
    assert env.broker.position("SOL") is None
    liquidated = snapshot_of(env)
    assert liquidated.positions == () and liquidated.cash == env.broker.cash_usd()


def test_restore_needs_a_fresh_broker_and_unknown_coins_get_conservative_rules(tmp_path) -> None:
    env = build_env(tmp_path)
    env.open_position("buy", "1.0", px="100", leverage=3)
    snap = snapshot_of(env)
    with pytest.raises(PaperBrokerFailedError):
        env.broker.restore(snap, now_ms=D0 + 9000, rules=env.meta.meta)  # the broker already holds the position
    fresh = restart(env)
    result = fresh.broker.restore(snap, now_ms=D0 + 9000, rules={"ETH": CoinMeta(4, 25)})
    assert result.unknown_coins == ("SOL",)
    assert fresh.broker.position("SOL") is not None  # flagged, never dropped
    assert fresh.broker.position("SOL").leverage == 3  # type: ignore[union-attr]


def test_the_restored_broker_has_its_time_set_and_rejects_old_gate_tokens(tmp_path) -> None:
    env = build_env(tmp_path)
    env.open_position("buy", "1.0", px="100")
    snap = snapshot_of(env)
    fresh = restart(env)
    fresh.broker.restore(snap, now_ms=D0 + 7000, rules=env.meta.meta)
    entry = fresh.order("buy", "1.0", coid="late", decided=D0 + 7000, share="S2", trade="T2")
    old_token = GateAuthority(b"the-key-of-the-previous-process-0123").issue(entry)
    assert fresh.broker.submit(entry, old_token).reason == "invalid_gate_token"  # a token of the old key never replays
    stale = fresh.order("buy", "1.0", coid="late2", decided=D0 + 6000, share="S3", trade="T3")
    assert fresh.broker.submit(stale, fresh.token(stale)).reason == "stale_decision"  # broker time was set first
