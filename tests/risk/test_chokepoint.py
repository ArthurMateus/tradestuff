"""F10.AC1 single chokepoint (A1), AC8 idempotency (A5) and the F11 token contracts.

The real gate, broker, authority and ledger run together; the authority is a recording subclass of the real one."""

from __future__ import annotations

import ast
from dataclasses import replace
from decimal import Decimal as D
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from copytrade.paper.types import OrderIntent, StopIntent
from copytrade.risk.ids import client_order_id
from tests.core.helpers import REPO_ROOT
from tests.risk.conftest import NewRisk
from tests.risk.helpers import RiskEnv, rebuild_gate

SRC = REPO_ROOT / "src" / "copytrade"
GATE_FILE = SRC / "risk" / "gate.py"
SENSITIVE = {"submit", "place_stop", "issue"}


def _calls(path: Any) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    } & SENSITIVE


# ---- static chokepoint checks ---------------------------------------------------------------------------------------


@pytest.mark.unit
def test_F10_AC1_only_the_risk_gate_module_calls_broker_submit_place_stop_or_authority_issue() -> None:
    offenders = {
        str(p.relative_to(SRC)): sorted(_calls(p))
        for p in SRC.rglob("*.py")
        if _calls(p) and p != GATE_FILE
    }
    assert offenders == {}
    # non-vacuous: the gate module really is the one caller of all three
    assert _calls(GATE_FILE) == SENSITIVE


@pytest.mark.unit
def test_F10_AC1_the_risk_package_has_no_float_literal_and_no_float_call() -> None:
    offenders: list[str] = []
    files = sorted((SRC / "risk").rglob("*.py"))
    assert {"gate.py", "sizing.py", "leverage.py", "ids.py", "settings.py"} <= {p.name for p in files}
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                offenders.append(f"{path.name}:{node.lineno} float literal")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
                offenders.append(f"{path.name}:{node.lineno} float()")
    assert offenders == []


# ---- every kind of order passes through the gate and carries a token bound to exactly that intent -----------------------


def _prep(r: RiskEnv) -> None:
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    r.book("SOL", "100")


CASES: list[tuple[str, Any]] = [
    ("open", lambda r: r.open_req()),
    ("add", lambda r: r.add_req(share_id="S1")),
    ("reduce", lambda r: r.exit_req(share_id="S1", close=False, qty="0.4", reason="leader_reduce")),
    ("close", lambda r: r.exit_req(share_id="S1", reason="leader_close")),
    ("flatten_reason", lambda r: r.exit_req(share_id="S1", reason="flatten")),
    ("dropped_leader_exit", lambda r: r.exit_req(share_id="S1", reason="leader_dropped")),
    ("reconstruction_settlement", lambda r: r.exit_req(share_id="S1", reason="reconstruction_settlement")),
    ("stop_loss", lambda r: r.stop_req(share_id="S1", kind="sl", trigger_px="98.5")),
    ("take_profit", lambda r: r.stop_req(share_id="S1", kind="tp", trigger_px="103")),
]


@pytest.mark.integration
@pytest.mark.parametrize("name,build", CASES, ids=[c[0] for c in CASES])
def test_F10_AC1_every_order_kind_reaches_the_broker_only_through_a_gate_issued_token(
    new_risk: NewRisk, name: str, build: Any
) -> None:
    r = new_risk()
    _prep(r)
    request = build(r)
    out = r.gate.place_stop(request) if name in ("stop_loss", "take_profit") else r.gate.submit(request)
    assert out.decision.approved, out.decision
    assert out.result is not None and out.result.accepted, out.result
    assert len(r.authority.issued) == 1
    intent, token = r.authority.issued[0]
    assert r.authority.verify(token, intent)
    assert intent.client_order_id == out.decision.client_order_id == out.result.client_order_id
    if isinstance(intent, StopIntent):
        assert (intent.kind, intent.side, intent.share_id) == (request.kind, "sell", "S1")
    else:
        assert isinstance(intent, OrderIntent)
        assert intent.coin == request.coin and intent.share_id == request.share_id
        assert intent.action is out.decision.action


@pytest.mark.integration
def test_F10_AC1_a_token_binds_the_exact_intent_including_time_price_reason_and_leverage(new_risk: NewRisk) -> None:
    r = new_risk()
    _prep(r)
    r.gate.submit(r.open_req())
    r.gate.submit(r.exit_req(share_id="S1", reason="leader_close"))
    (open_intent, open_token), (exit_intent, exit_token) = r.authority.issued
    assert isinstance(open_intent, OrderIntent) and isinstance(exit_intent, OrderIntent)
    assert r.authority.verify(open_token, open_intent)
    for changed in (
        replace(open_intent, decided_at_ms=open_intent.decided_at_ms + 1),
        replace(open_intent, decision_px=open_intent.decision_px + 1),
        replace(open_intent, leverage=(open_intent.leverage or 1) + 1),
        replace(open_intent, qty=open_intent.qty + D("0.01")),
        replace(open_intent, client_order_id=open_intent.client_order_id + "x"),
    ):
        assert not r.authority.verify(open_token, changed)
    assert not r.authority.verify(exit_token, replace(exit_intent, exit_reason="flatten"))
    assert exit_intent.leverage is None and exit_intent.exit_reason == "leader_close"
    assert exit_intent.action is ActionKind.CLOSE and exit_intent.side == "sell"
    assert open_intent.side == "buy" and open_intent.action is ActionKind.OPEN


@pytest.mark.integration
def test_F10_AC1_a_refused_request_never_reaches_the_authority_or_the_broker(new_risk: NewRisk) -> None:
    r = new_risk()
    r.gate.pause()
    before = len(r.paper.records())
    out = r.gate.submit(r.open_req())
    assert out.decision.approved is False and out.result is None
    assert r.authority.issued == []
    kinds = {rec.kind for rec in r.paper.records()[before:]}
    assert kinds <= {"risk_decision"}  # the audit record only: no paper_order, no paper_reject


@pytest.mark.integration
def test_F10_AC1_a_stop_is_placed_through_the_gate_and_is_not_blocked_by_a_pause(new_risk: NewRisk) -> None:
    r = new_risk()
    _prep(r)
    r.gate.pause()
    out = r.gate.place_stop(r.stop_req(share_id="S1"))
    assert out.decision.approved and out.result is not None and out.result.accepted
    assert isinstance(r.authority.issued[0][0], StopIntent)


# ---- fresh token per attempt ----------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_F11_contract_each_attempt_gets_a_fresh_single_use_token_even_after_a_broker_refusal(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    r.seed_risk_only("SOL", leader="L1", risk="1.5")  # the share book says S1 exists; the broker has no position
    req = r.exit_req(share_id=r.shares.shares[0].share_id)
    first = r.gate.submit(req)
    second = r.gate.submit(req)
    for out in (first, second):
        assert out.decision.approved
        assert out.result is not None and (out.result.accepted, out.result.reason) == (False, "exceeds_position")
    assert len(r.authority.issued) == 2
    (i1, t1), (i2, t2) = r.authority.issued
    assert t1.token_id != t2.token_id
    assert r.authority.verify(t1, i1) and r.authority.verify(t2, i2)


# ---- time base and ordering ---------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_F11_contract_decided_at_ms_is_the_exchange_time_stamped_at_submit(new_risk: NewRisk) -> None:
    r = new_risk()
    _prep(r)
    r.xtime.now += 5000  # the exchange clock is ahead of the local clock the ledger uses
    r.book("SOL", "100")
    out = r.gate.submit(r.open_req())
    assert out.result is not None and out.result.accepted, out
    intent = r.authority.issued[0][0]
    assert isinstance(intent, OrderIntent)
    assert intent.decided_at_ms == r.xtime.now
    assert r.paper.records("paper_order")[-1].payload["decided_at_ms"] == r.xtime.now


@pytest.mark.integration
def test_F10_F11_contract_exits_are_stamped_in_the_exchange_time_base_too(new_risk: NewRisk) -> None:
    r = new_risk()
    _prep(r)
    r.xtime.now += 7000
    out = r.gate.submit(r.exit_req(share_id="S1"))
    assert out.result is not None and out.result.accepted, out
    intent = r.authority.issued[0][0]
    assert isinstance(intent, OrderIntent) and intent.decided_at_ms == r.xtime.now


@pytest.mark.integration
def test_F10_F11_contract_the_gate_advances_the_broker_to_exchange_time_before_every_submit(new_risk: NewRisk) -> None:
    r = new_risk()
    r.book("SOL", "100")
    first = r.gate.submit(r.open_req())  # decided at T0, fills at T0 + 1000 (ack delay)
    assert first.result is not None and first.result.accepted
    assert r.paper.broker.position("SOL") is None  # not yet: nothing has advanced the broker past T0
    r.xtime.now += 5000
    r.book("SOL", "100")
    second = r.gate.submit(r.open_req(tids=(555,), share_id="S11"))
    assert second.result is not None and second.result.accepted, second
    assert r.paper.broker.position("SOL") is not None  # the gate's own advance_to filled the first order


@pytest.mark.integration
def test_F10_F11_contract_an_exit_is_still_sent_when_the_exchange_clock_is_unsynced(new_risk: NewRisk) -> None:
    r = new_risk()
    _prep(r)
    r.xtime.unsynced = True
    out = r.gate.submit(r.exit_req(share_id="S1"))
    assert out.decision.approved and out.result is not None and out.result.accepted, out


# ---- AC8 idempotency -----------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_AC8_the_client_order_id_is_derived_from_run_leader_coin_tids_action_and_share(new_risk: NewRisk) -> None:
    r = new_risk()
    _prep(r)
    open_out = r.gate.submit(r.open_req(tids=(9, 3)))
    close_out = r.gate.submit(r.exit_req(share_id="S1", tids=(77,)))
    assert open_out.decision.client_order_id == client_order_id(
        run_id="run1", leader="L1", coin="SOL", tids=(3, 9), action="open", share_id="S10"
    )
    assert close_out.decision.client_order_id == client_order_id(
        run_id="run1", leader="L1", coin="SOL", tids=(77,), action="close", share_id="S1"
    )
    assert open_out.decision.client_order_id != close_out.decision.client_order_id


@pytest.mark.integration
def test_F10_AC8_resubmitting_the_same_intent_after_a_restart_produces_no_extra_fill(new_risk: NewRisk) -> None:
    r = new_risk()
    r.book("SOL", "100")
    first = r.gate.submit(r.open_req())
    assert first.result is not None and first.result.accepted
    r.fill()
    assert len(r.paper.fills()) == 1

    r2 = rebuild_gate(r)  # the restart: new broker and gate over the same ledger
    try:
        r2.at(r.xtime.now + 20_000)
        r2.book("SOL", "100")
        again = r2.gate.submit(r2.open_req())
        assert again.result is None or not again.result.accepted
        r2.fill()
        assert len(r2.paper.fills()) == 1
        assert len(r2.paper.records("paper_order")) == 1
    finally:
        r2.paper.ledger.close()


@pytest.mark.integration
def test_F10_AC8_the_same_signal_submitted_twice_in_a_row_fills_once(new_risk: NewRisk) -> None:
    r = new_risk()
    r.book("SOL", "100")
    a = r.gate.submit(r.open_req())
    b = r.gate.submit(r.open_req())
    assert a.result is not None and a.result.accepted
    assert b.result is None or not b.result.accepted
    r.fill()
    assert len(r.paper.fills()) == 1
    assert len(r.authority.issued) in (1, 2)
    if len(r.authority.issued) == 2:
        assert r.authority.issued[0][1].token_id != r.authority.issued[1][1].token_id
