"""R2.AC6 (pin gap, money path): the duplicate-stop dedupe of ``PaperBroker.restore`` (``_restore_stop``).

A kill -9 between the new ``paper_stop`` record and the ``paper_cancel`` of the old one leaves TWO live stops for one
share in the ledger. The restore must leave exactly ONE live, correct stop and must LEDGER the cancel of the duplicate
(otherwise the next restart finds it live again). Both halves are pinned separately: removing the duplicate guard (the
broker would hold two stops) and removing the cancel inside the guard's branch (the duplicate stays live in the ledger)
each fail one test below. Real broker and ledger; books, meta, funding, clock are the usual fakes."""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path

from copytrade.ledger.store import read_records
from copytrade.paper.restore import BrokerSnapshot, StopSnap, replay_broker
from copytrade.paper.settings import PaperSettings
from tests.paper.helpers import D0, Env, build_env, restart

D = Decimal


def snapshot_of(env: Env) -> BrokerSnapshot:
    return replay_broker(read_records(env.ledger_dir), PaperSettings.from_config(env.config))


def duplicated(tmp_path: Path) -> tuple[Env, BrokerSnapshot]:
    """One share with a stop-loss ``s1``; a kill -9 left a second, identical live ``paper_stop`` record ``s2``."""
    env = build_env(tmp_path)
    env.open_position("buy", "1.0", px="100")
    assert env.stop("sl", "sell", "1.0", "95", coid="s1").accepted
    original = env.records("paper_stop")[0].payload
    env.ledger.append("paper_stop", dict(original), client_order_id="s2")
    snap = snapshot_of(env)
    assert sorted(s.client_order_id for s in snap.stops) == ["s1", "s2"], "the torn ledger holds the stop twice"
    return env, snap


def cancels(env: Env) -> dict[str, str]:
    return {r.payload["client_order_id"]: r.payload["reason"] for r in env.records("paper_cancel")}


def test_R2_AC6_two_surviving_stops_for_one_share_leave_exactly_one_live_stop(tmp_path: Path) -> None:
    env, snap = duplicated(tmp_path)
    fresh = restart(env)
    result = fresh.broker.restore(snap, now_ms=D0 + 2000, rules=env.meta.meta)
    live = fresh.broker.stops()
    assert len(live) == 1, [(s.client_order_id, s.qty, s.trigger_px) for s in live]
    (stop,) = live
    assert (stop.coin, stop.kind, stop.side, stop.qty, stop.trigger_px, stop.share_id) == (
        "SOL", "sl", "sell", D("1.0"), D("95"), "S1",
    )
    assert len(result.stops) == 1 and result.stops[0].new_client_order_id == stop.client_order_id


def test_R2_AC6_the_duplicate_is_cancelled_in_the_ledger_so_a_second_restart_does_not_find_it_live(tmp_path: Path) -> None:
    env, snap = duplicated(tmp_path)
    fresh = restart(env)
    fresh.broker.restore(snap, now_ms=D0 + 2000, rules=env.meta.meta)
    after = snapshot_of(fresh)  # what a second restart would replay
    assert len(after.stops) == 1, [s.client_order_id for s in after.stops]
    reasons = cancels(fresh)
    assert reasons.get("s1") == "restart" and reasons.get("s2") == "restart"  # BOTH originals are retired
    second = restart(fresh)
    second.broker.restore(after, now_ms=D0 + 3000, rules=env.meta.meta)
    assert len(second.broker.stops()) == 1
    assert len(snapshot_of(second).stops) == 1


def test_R2_AC6_the_surviving_stop_still_triggers_exactly_once(tmp_path: Path) -> None:
    env, snap = duplicated(tmp_path)
    fresh = restart(env)
    fresh.broker.restore(snap, now_ms=D0 + 2000, rules=env.meta.meta)
    fresh.flat_book("SOL", D0 + 6000, "94")
    fresh.mark("SOL", "94", D0 + 3000)
    fresh.advance(D0 + 6000)
    assert fresh.broker.position("SOL") is None
    stop_exits = [r for r in fresh.records("fill") if r.payload["exit_reason"] == "stop_loss"]
    assert len(stop_exits) == 1  # a duplicate would have tried to close the share twice


def test_R2_AC6_a_stop_whose_share_is_gone_is_cancelled_with_a_reason_and_not_registered(tmp_path: Path) -> None:
    """The other half of the same branch (``share is None``): a live stop in the ledger for a share the position no
    longer holds is cancelled and never registered."""
    env = build_env(tmp_path)
    env.open_position("buy", "1.0", px="100")
    assert env.stop("sl", "sell", "1.0", "95", coid="s1").accepted
    snap = snapshot_of(env)
    ghost = StopSnap(
        client_order_id="g1", coin="SOL", kind="sl", side="sell", qty=D("1.0"), trigger_px=D("90"),
        trade_id="T9", share_id="NOT-HELD",
    )
    fresh = restart(env)
    fresh.broker.restore(dataclasses.replace(snap, stops=(*snap.stops, ghost)), now_ms=D0 + 2000, rules=env.meta.meta)
    assert [s.share_id for s in fresh.broker.stops()] == ["S1"]
    assert cancels(fresh).get("g1") == "restart"
    assert [s.client_order_id for s in snapshot_of(fresh).stops] == [fresh.broker.stops()[0].client_order_id]


def test_R2_AC6_a_stop_that_differs_in_trigger_is_not_a_duplicate(tmp_path: Path) -> None:
    """Guard against an over-eager dedupe (a key made of fewer fields): the stop-loss and the take-profit of one share,
    or two stops at different prices, are different orders and both survive."""
    env = build_env(tmp_path)
    env.open_position("buy", "1.0", px="100")
    assert env.stop("sl", "sell", "1.0", "95", coid="s1").accepted
    assert env.stop("tp", "sell", "0.5", "110", coid="t1").accepted
    assert env.stop("sl", "sell", "1.0", "94", coid="s2").accepted
    snap = snapshot_of(env)
    fresh = restart(env)
    fresh.broker.restore(snap, now_ms=D0 + 2000, rules=env.meta.meta)
    shape = sorted((s.kind, s.qty, s.trigger_px) for s in fresh.broker.stops())
    assert shape == [("sl", D("1.0"), D("94")), ("sl", D("1.0"), D("95")), ("tp", D("0.5"), D("110"))]
