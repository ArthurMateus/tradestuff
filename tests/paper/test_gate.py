# mypy: disable-error-code="union-attr"
"""The gate token (F10.AC1, A1 single chokepoint, A2 fail closed, A5 idempotency). The broker refuses every order
that lacks a valid, single-use token issued by the GateAuthority for exactly that intent. Exchange-originated events
(liquidation, delisting, a stop trigger) need no token: their orders were approved when the stop was placed."""

from __future__ import annotations

import inspect
from dataclasses import replace

import pytest
from typing import Any
from tests.paper.helpers import NewEnv
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.ledger.errors import LedgerWriteError
from copytrade.paper.broker import PaperBroker
from copytrade.paper.gate import GateAuthority
from copytrade.paper.types import GateToken, OrderIntent, StopIntent
from tests.paper.helpers import D0, KEY, fresh_env, restart

FILL_T = D0 + 1000


def _forged() -> GateToken:
    return GateToken(token_id="forged-1", intent_digest="0" * 64, mac="0" * 64)


@pytest.mark.unit
def test_F10_AC1_the_broker_entry_points_require_a_token_parameter_with_no_default() -> None:
    for name in ("submit", "place_stop"):
        params = inspect.signature(getattr(PaperBroker, name)).parameters
        assert "token" in params and params["token"].default is inspect.Parameter.empty


@pytest.mark.unit
def test_F10_AC1_a_valid_token_is_accepted_and_the_order_fills(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", FILL_T, "100")
    intent = e.order("buy", "1.0")
    result = e.broker.submit(intent, e.authority.issue(intent))
    assert (result.accepted, result.reason, result.client_order_id) == (True, None, "c1")
    assert [ev.kind for ev in e.advance(FILL_T)] == ["fill"]
    assert e.ledger.has_client_order_id("c1")  # A5: the accepted order holds its ID in the ledger


@pytest.mark.unit
@pytest.mark.parametrize("action", [ActionKind.OPEN, ActionKind.ADD, ActionKind.REDUCE, ActionKind.CLOSE])
def test_F10_AC1_every_action_kind_is_refused_without_a_valid_token(new_env: NewEnv, action: Any) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", coid="seed")
    before = len(e.fills())
    side = "buy" if action in (ActionKind.OPEN, ActionKind.ADD) else "sell"
    intent = e.order(side, "1.0", coid="x1", action=action, decided=D0 + 60_000, share="S1")
    result = e.broker.submit(intent, _forged())
    assert (result.accepted, result.reason) == (False, "invalid_gate_token")
    e.flat_book("SOL", D0 + 61_000, "100")
    e.advance(D0 + 62_000)
    assert len(e.fills()) == before
    assert not e.ledger.has_client_order_id("x1")
    assert e.records("paper_reject")[-1].payload["reason"] == "invalid_gate_token"


@pytest.mark.unit
def test_F10_AC1_a_stop_without_a_valid_token_is_refused_and_never_armed(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    stop = StopIntent("stop1", "SOL", "sl", "sell", Qty("1.0"), Price("99"), "T1", "S1")
    assert e.broker.place_stop(stop, _forged()).reason == "invalid_gate_token"
    e.mark("SOL", "1", D0 + 20_000)  # a liquidation may happen, but the refused stop must not fire
    kinds = {ev.fill.exit_reason for ev in e.events if ev.fill}
    assert "stop_loss" not in kinds


@pytest.mark.unit
def test_F10_AC1_a_token_from_a_different_authority_is_refused(new_env: NewEnv) -> None:
    e = new_env()
    other = GateAuthority(b"some-other-secret-key-0123456789")
    intent = e.order("buy", "1.0")
    assert e.broker.submit(intent, other.issue(intent)).reason == "invalid_gate_token"


@pytest.mark.unit
@pytest.mark.parametrize(
    "change",
    [{"qty": Qty("2.0")}, {"coin": "ETH"}, {"side": "sell"}, {"client_order_id": "other"}, {"share_id": "S9"},
     {"leverage": 6}, {"action": ActionKind.ADD}],
)
def test_F10_AC1_a_token_is_bound_to_the_exact_intent(new_env: NewEnv, change: Any) -> None:
    e = new_env()
    approved = e.order("buy", "1.0")
    token = e.authority.issue(approved)
    tampered = replace(approved, **change)
    assert e.broker.submit(tampered, token).reason == "invalid_gate_token"


@pytest.mark.unit
def test_F10_AC1_a_tampered_or_malformed_token_is_refused_without_raising(new_env: NewEnv) -> None:
    e = new_env()
    intent = e.order("buy", "1.0")
    good = e.authority.issue(intent)
    flipped = replace(good, mac=("1" if good.mac[0] != "1" else "2") + good.mac[1:])
    assert e.broker.submit(intent, flipped).reason == "invalid_gate_token"
    assert e.broker.submit(intent, GateToken("x", "y", "z")).reason == "invalid_gate_token"
    assert e.broker.submit(intent, GateToken("", "", "")).reason == "invalid_gate_token"
    assert e.records("fill") == []


@pytest.mark.unit
def test_F10_AC1_a_token_is_single_use(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", FILL_T, "100")
    intent = e.order("buy", "1.0")
    token = e.authority.issue(intent)
    assert e.broker.submit(intent, token).accepted
    again = e.broker.submit(intent, token)
    assert (again.accepted, again.reason) == (False, "gate_token_reused")
    e.advance(FILL_T)
    assert len(e.fills()) == 1


@pytest.mark.unit
def test_F10_AC1_a_token_is_consumed_even_when_the_order_is_refused_on_the_merits(new_env: NewEnv) -> None:
    e = new_env()
    bad = e.order("buy", "1.0", coin="NOPE")
    token = e.authority.issue(bad)
    assert e.broker.submit(bad, token).reason == "unknown_coin"
    assert e.broker.submit(bad, token).reason == "gate_token_reused"


@pytest.mark.unit
def test_F10_AC1_authority_issues_unique_tokens_and_verifies_only_its_own(new_env: NewEnv) -> None:
    e = new_env()
    intent = e.order("buy", "1.0")
    t1, t2 = e.authority.issue(intent), e.authority.issue(intent)
    assert t1.token_id != t2.token_id
    assert e.authority.verify(t1, intent) is True
    assert e.authority.verify(_forged(), intent) is False
    assert e.authority.verify(t1, replace(intent, qty=Qty("1.1"))) is False
    assert GateAuthority(b"a-different-key-0123456789abcdef").verify(t1, intent) is False


@pytest.mark.unit
def test_F10_AC1_authority_never_raises_on_garbage_tokens() -> None:
    auth = GateAuthority(KEY)
    intent = OrderIntent("c", "SOL", "buy", Qty("1.0"), ActionKind.OPEN, D0, Price("100"), "T", "S", 5, None)
    for token in (GateToken("", "", ""), GateToken("a" * 10_000, "b", "c"), GateToken("‮\U0001f600", "é", "ß")):
        try:
            assert auth.verify(token, intent) is False
        except (AttributeError, TypeError):
            pytest.fail("verify must return False for a bad token, not raise")


@pytest.mark.unit
def test_A5_same_client_order_id_with_a_fresh_token_is_a_duplicate_and_fills_once(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", FILL_T, "100")
    first = e.submit(e.order("buy", "1.0"))
    second = e.submit(e.order("buy", "1.0"))  # fresh token, same client order ID
    assert first.accepted
    assert (second.accepted, second.reason) == (False, "duplicate_client_order_id")
    e.advance(FILL_T)
    assert len(e.fills()) == 1 and e.broker.position("SOL").qty == Qty("1.0")


@pytest.mark.unit
def test_A5_a_restart_does_not_double_submit_the_same_client_order_id(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", coid="c-restart")
    e2 = restart(e)
    try:
        e2.flat_book("SOL", D0 + 61_000, "100")
        result = e2.submit(e2.order("buy", "1.0", coid="c-restart", decided=D0 + 60_000))
        assert (result.accepted, result.reason) == (False, "duplicate_client_order_id")
        e2.advance(D0 + 62_000)
        assert len(e2.fills()) == 1  # 0 extra fills
    finally:
        e2.ledger.close()


@pytest.mark.unit
@settings(max_examples=20)
@given(
    qty=st.integers(min_value=10, max_value=10_000),
    side=st.sampled_from(["buy", "sell"]),
    coin=st.sampled_from(["BTC", "ETH", "SOL", "DOGE", "NOPE"]),
    copies=st.integers(min_value=1, max_value=4),
)
def test_A1_property_no_order_ever_fills_without_a_valid_token_and_a_valid_one_fills_at_most_once(qty: Any, side: Any, coin: Any, copies: Any) -> None:
    with fresh_env() as e:
        e.flat_book(coin, FILL_T, "100")
        intent = e.order(side, str(qty), coin=coin, px="100")
        assert not e.broker.submit(intent, _forged()).accepted
        e.advance(FILL_T)
        assert e.records("fill") == []
        for _ in range(copies):
            e.submit(intent)  # fresh token each time, same client order ID
        e.advance(FILL_T + 1)
        assert len(e.records("fill")) <= 1


@pytest.mark.unit
def test_A2_a_ledger_that_cannot_record_the_order_makes_submit_raise_and_nothing_fills(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", FILL_T, "100")
    e.ledger.close()  # any append now raises LedgerWriteError (F2.AC6)
    with pytest.raises(LedgerWriteError):
        e.submit(e.order("buy", "1.0"))
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_A2_a_ledger_failure_at_fill_time_raises_and_the_broker_keeps_failing_closed(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", FILL_T, "100")
    assert e.submit(e.order("buy", "1.0")).accepted
    e.ledger.close()
    with pytest.raises(LedgerWriteError):
        e.broker.advance_to(FILL_T)
    with pytest.raises(LedgerWriteError):  # never continues silently (F2.AC6, B5)
        e.submit(e.order("buy", "1.0", coid="c2"))
