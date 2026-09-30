# mypy: disable-error-code="union-attr"
"""F11 round 2 (F10.AC1, A1): the gate token digest does not depend on the ambient Decimal context (RISK-4), and the
token is bound to EVERY field of the intent it approved, whichever field changes.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_DOWN, Context, Decimal, localcontext
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.paper.helpers import D0, KEY, Env, NewEnv

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.paper.gate import GateAuthority, intent_digest
from copytrade.paper.types import OrderIntent, StopIntent

D = Decimal
BIG = "12345678901234567890.123456789012345"  # 35 significant digits: more than the default context's 28
BIG_NEXT = "12345678901234567890.123456789012346"  # differs in the 35th digit only

DEFAULT_CTX = Context(prec=28)


def _issue_in_default_context(authority: GateAuthority, intent: OrderIntent | StopIntent) -> Any:
    with localcontext(DEFAULT_CTX):
        return authority.issue(intent)


# ------------------------------------------------------------------------------------------------- RISK-4


@pytest.mark.unit
def test_R2_RISK4_an_order_token_issued_in_the_default_context_verifies_in_the_broker_for_a_35_digit_price(
    new_env: NewEnv,
) -> None:
    e = new_env()
    intent = replace(e.order("buy", "1.0", coid="big1"), decision_px=Price(BIG))
    token = _issue_in_default_context(e.authority, intent)
    e.advance(D0)  # RISK-26: an entry needs broker time first
    result = e.broker.submit(intent, token)
    assert (result.accepted, result.reason) == (True, None)


@pytest.mark.unit
def test_R2_RISK4_a_stop_token_issued_in_the_default_context_verifies_in_the_broker_for_a_35_digit_trigger(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    intent = StopIntent(
        client_order_id="stop-big",
        coin="SOL",
        kind="tp",
        side="sell",
        qty=Qty("2.0"),
        trigger_px=Price(BIG),
        trade_id="T1",
        share_id="S1",
    )
    token = _issue_in_default_context(e.authority, intent)
    result = e.broker.place_stop(intent, token)
    assert (result.accepted, result.reason) == (True, None)


@pytest.mark.unit
def test_R2_RISK4_a_35_digit_value_stays_bound_to_its_last_digit() -> None:
    authority = GateAuthority(KEY)
    intent = StopIntent("s1", "SOL", "tp", "sell", Qty("2.0"), Price(BIG), "T1", "S1")
    for ambient in (DEFAULT_CTX, Context(prec=60), Context(prec=5)):
        with localcontext(ambient):
            token = authority.issue(intent)
            assert authority.verify(token, intent)
            assert not authority.verify(token, replace(intent, trigger_px=Price(BIG_NEXT)))


@pytest.mark.unit
@pytest.mark.parametrize(
    "ambient",
    [
        Context(prec=1),
        Context(prec=5),
        Context(prec=28),
        Context(prec=60),
        Context(prec=200),
        Context(prec=28, rounding=ROUND_DOWN),
        Context(prec=9, Emax=20, Emin=-20),
    ],
)
def test_R2_RISK4_the_digest_does_not_depend_on_the_ambient_context(ambient: Context) -> None:
    intent = OrderIntent("c1", "SOL", "buy", Qty("1.5"), ActionKind.OPEN, D0, Price(BIG), "T1", "S1", 5, None)
    with localcontext(Context(prec=60)):
        reference = intent_digest(intent)
    with localcontext(ambient):
        assert intent_digest(intent) == reference


_digits = st.integers(min_value=1, max_value=10**40 - 1)


@pytest.mark.unit
@settings(max_examples=60)
@given(a=_digits, b=_digits, scale=st.integers(min_value=0, max_value=20), prec=st.integers(min_value=1, max_value=80))
def test_R2_RISK4_property_digest_is_context_independent_and_distinct_values_have_distinct_digests(
    a: int, b: int, scale: int, prec: int
) -> None:
    def digest(value: int, context_prec: int) -> str:
        intent = StopIntent("s1", "SOL", "sl", "sell", Qty("1"), Price(Decimal(f"{value}E-{scale}")), "T1", "S1")
        with localcontext(Context(prec=context_prec)):
            return intent_digest(intent)

    assert digest(a, prec) == digest(a, 60) == digest(a, 28)
    if a != b:
        assert digest(a, prec) != digest(b, prec)


# ------------------------------------------------------------------------------- binding to every field


def _entry(e: Env) -> OrderIntent:  # the intent every entry case starts from
    return e.order("buy", "1.5", coid="c1", coin="SOL", decided=D0, px="100", share="S1", trade="T1", leverage=5)


def _exit(e: Env) -> OrderIntent:
    return e.order(
        "sell",
        "1.5",
        coid="c1",
        coin="SOL",
        action=ActionKind.REDUCE,
        decided=D0,
        px="100",
        share="S1",
        trade="T1",
        reason="manual",
    )


_ORDER_CHANGES: list[tuple[str, str, Any]] = [
    ("entry", "coin", "BTC"),
    ("entry", "side", "sell"),
    ("entry", "qty", Qty("1.51")),
    ("entry", "qty", Qty("15")),
    ("entry", "action", ActionKind.ADD),
    ("entry", "action", ActionKind.CLOSE),
    ("entry", "client_order_id", "c2"),
    ("entry", "share_id", "S2"),
    ("entry", "trade_id", "T2"),
    ("entry", "leverage", 6),
    ("entry", "leverage", None),
    ("entry", "decision_px", Price("100.01")),
    ("entry", "decided_at_ms", D0 + 1),
    ("entry", "exit_reason", "manual"),
    ("exit", "coin", "BTC"),
    ("exit", "side", "buy"),
    ("exit", "qty", Qty("1.0")),
    ("exit", "action", ActionKind.CLOSE),
    ("exit", "client_order_id", "c2"),
    ("exit", "share_id", "S2"),
    ("exit", "trade_id", "T2"),
    ("exit", "leverage", 5),
    ("exit", "decision_px", Price("99")),
    ("exit", "decided_at_ms", D0 - 1),
    ("exit", "exit_reason", "stop_loss"),
    ("exit", "exit_reason", None),
    ("exit", "exit_reason", ""),
]


@pytest.mark.unit
@pytest.mark.parametrize(("base", "field_name", "value"), _ORDER_CHANGES)
def test_R2_F10_AC1_a_token_does_not_verify_when_any_single_order_field_changes(
    new_env: NewEnv, base: str, field_name: str, value: Any
) -> None:
    e = new_env()
    intent = _entry(e) if base == "entry" else _exit(e)
    changed = replace(intent, **{field_name: value})
    assert changed != intent
    token = e.authority.issue(intent)
    assert e.authority.verify(token, intent)
    assert not e.authority.verify(token, changed)
    assert intent_digest(intent) != intent_digest(changed)
    result = e.broker.submit(changed, token)
    assert (result.accepted, result.reason) == (False, "invalid_gate_token")


_STOP_BASE = StopIntent("stop1", "SOL", "sl", "sell", Qty("2.0"), Price("95"), "T1", "S1")
_STOP_CHANGES: list[tuple[str, Any]] = [
    ("client_order_id", "stop2"),
    ("coin", "BTC"),
    ("kind", "tp"),
    ("side", "buy"),
    ("qty", Qty("1.0")),
    ("qty", Qty("2.01")),
    ("trigger_px", Price("95.01")),
    ("trigger_px", Price("94.99")),
    ("trade_id", "T2"),
    ("share_id", "S2"),
]


@pytest.mark.unit
@pytest.mark.parametrize(("field_name", "value"), _STOP_CHANGES)
def test_R2_F10_AC1_a_token_does_not_verify_when_any_single_stop_field_changes(
    new_env: NewEnv, field_name: str, value: Any
) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    changed = replace(_STOP_BASE, **{field_name: value})
    token = e.authority.issue(_STOP_BASE)
    assert e.authority.verify(token, _STOP_BASE)
    assert not e.authority.verify(token, changed)
    assert intent_digest(_STOP_BASE) != intent_digest(changed)
    result = e.broker.place_stop(changed, token)
    assert (result.accepted, result.reason) == (False, "invalid_gate_token")


@pytest.mark.unit
def test_R2_F10_AC1_moving_text_between_adjacent_fields_changes_the_digest() -> None:
    """No two intents share an encoding: the boundary between two adjacent text fields is part of what is signed."""
    base = OrderIntent("ab", "SOL", "buy", Qty("1"), ActionKind.OPEN, D0, Price("100"), "T1", "S1", 5, None)
    moved = replace(base, client_order_id="a", coin="bSOL")
    trade = replace(base, trade_id="T", share_id="1S1")
    trade_base = replace(base, trade_id="T1", share_id="S1")
    assert intent_digest(base) != intent_digest(moved)
    assert intent_digest(trade_base) != intent_digest(trade)
    stop = StopIntent("ab", "SOL", "sl", "sell", Qty("1"), Price("90"), "T1", "S1")
    assert intent_digest(stop) != intent_digest(replace(stop, client_order_id="a", coin="bSOL"))


@pytest.mark.unit
def test_R2_F10_AC1_an_order_token_never_verifies_a_stop_and_a_stop_token_never_verifies_an_order() -> None:
    authority = GateAuthority(KEY)
    order = OrderIntent("c1", "SOL", "sell", Qty("1"), ActionKind.CLOSE, D0, Price("90"), "T1", "S1", None, "manual")
    stop = StopIntent("c1", "SOL", "sl", "sell", Qty("1"), Price("90"), "T1", "S1")
    assert not authority.verify(authority.issue(order), stop)
    assert not authority.verify(authority.issue(stop), order)


@pytest.mark.unit
@pytest.mark.parametrize("key", [b"", bytearray()])
def test_R2_F10_AC1_an_authority_with_an_empty_key_is_refused(key: bytes) -> None:
    with pytest.raises(ValueError, match="key"):
        GateAuthority(key)


@pytest.mark.unit
def test_R2_F10_AC1_a_token_issued_under_another_key_does_not_verify() -> None:
    a, b = GateAuthority(b"a" * 32), GateAuthority(b"b" * 32)
    intent = OrderIntent("c1", "SOL", "buy", Qty("1"), ActionKind.OPEN, D0, Price("100"), "T1", "S1", 5, None)
    token = a.issue(intent)
    assert a.verify(token, intent) and not b.verify(token, intent)


_SEPARATORS = ["|", ",", ":", ";", " ", "\x00", "\n", '"', "\\", "[", "]", "'", "/"]


@pytest.mark.unit
@pytest.mark.parametrize("sep", _SEPARATORS)
def test_R2_F10_AC1_a_separator_character_inside_a_field_cannot_be_moved_to_the_next_field(sep: str) -> None:
    """Whatever character an encoder might join fields with, text that contains it must not collide with the same
    characters split differently across two adjacent fields."""
    order = OrderIntent("c1", "SOL", "buy", Qty("1"), ActionKind.OPEN, D0, Price("100"), "T1", "S1", 5, None)
    one = replace(order, client_order_id=f"a{sep}b", coin="c")
    two = replace(order, client_order_id="a", coin=f"b{sep}c")
    assert intent_digest(one) != intent_digest(two)
    three = replace(order, trade_id=f"t{sep}u", share_id="v")
    four = replace(order, trade_id="t", share_id=f"u{sep}v")
    assert intent_digest(three) != intent_digest(four)
    stop = StopIntent("s1", "SOL", "sl", "sell", Qty("1"), Price("90"), "T1", "S1")
    assert intent_digest(replace(stop, client_order_id=f"a{sep}b", coin="c")) != intent_digest(
        replace(stop, client_order_id="a", coin=f"b{sep}c")
    )
