"""F2.AC1/AC6 support: payload validation and canonical encoding (A6 money is Decimal), no secret ever stored (F1.AC5),
and hostile content cannot break the one-record-per-line structure.

Spec: 04-spec.md F2.AC1, F2.AC6, F1.AC4, F1.AC5, invariant A6.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.secrets import SecretValue
from copytrade.ledger.errors import DuplicateClientOrderIdError
from copytrade.ledger.store import Ledger, verify_ledger
from tests.harness import CANARY_SECRETS, find_canary_leaks
from tests.ledger.helpers import ledger_file, raw_lines

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("bad", [0.1, float("nan"), float("inf"), -0.0], ids=repr)
def test_F2_AC1_float_in_a_payload_is_refused(ledger: Ledger, bad: float) -> None:
    with pytest.raises(TypeError):
        ledger.append("note", {"price": bad})


def test_F2_AC1_float_nested_inside_containers_is_refused(ledger: Ledger) -> None:
    with pytest.raises(TypeError):
        ledger.append("note", {"levels": [{"px": [1, 2, 0.5]}]})


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")], ids=str)
def test_F2_AC1_non_finite_decimal_is_refused(ledger: Ledger, bad: Decimal) -> None:
    with pytest.raises(ValueError):
        ledger.append("note", {"x": bad})


@pytest.mark.parametrize("bad", [{1: "a"}, {None: "a"}, {("a",): 1}], ids=repr)
def test_F2_AC1_non_string_keys_are_refused(ledger: Ledger, bad: dict[Any, Any]) -> None:
    with pytest.raises((TypeError, ValueError)):
        ledger.append("note", bad)


@pytest.mark.parametrize("bad", [object(), {1, 2}, b"bytes", lambda: 1], ids=["object", "set", "bytes", "lambda"])
def test_F2_AC1_unserialisable_values_are_refused(ledger: Ledger, bad: object) -> None:
    with pytest.raises(TypeError):
        ledger.append("note", {"x": bad})


@pytest.mark.parametrize("kind", ["", "Bad Kind", "1decision", "a-b", "x\n", "é"], ids=repr)
def test_F2_AC1_kind_must_be_a_lower_snake_identifier(ledger: Ledger, kind: str) -> None:
    with pytest.raises(ValueError):
        ledger.append(kind, {"a": 1})


def test_F2_AC1_a_refused_append_writes_nothing_uses_no_sequence_number_and_leaves_the_ledger_usable(
    ledger: Ledger, ledger_dir: Path
) -> None:
    first = ledger.append("note", {"a": 1})
    before = ledger_file(ledger_dir).read_bytes()
    with pytest.raises(TypeError):
        ledger.append("note", {"a": 0.5})
    with pytest.raises(ValueError):
        ledger.append("Bad Kind", {"a": 1})
    assert ledger_file(ledger_dir).read_bytes() == before
    assert not ledger.failed
    second = ledger.append("note", {"a": 2})
    assert (first.seq, second.seq) == (1, 2)
    assert verify_ledger(ledger_dir).ok


def test_F2_AC1_decimals_round_trip_exactly_including_scale_and_sign(ledger: Ledger) -> None:
    values = [Decimal("1.10"), Decimal("0.00000001"), Decimal("-0"), Decimal("1E+3"), Decimal("123456789012345678901234567890.123456789")]
    ledger.append("note", {"values": values})
    stored = next(iter(ledger.records())).payload["values"]
    assert [str(v) for v in stored] == [str(v) for v in values]
    assert all(isinstance(v, Decimal) for v in stored)


def test_F2_AC1_hostile_text_cannot_break_the_one_record_per_line_layout(ledger: Ledger, ledger_dir: Path) -> None:
    nasty = "line1\nline2\r\nline3  \x00\x1b[31m\U0001f4a5 ‮evil﻿"
    ledger.append("note", {"note": nasty, "key\nwith newline": "v"})
    ledger.append("note", {"after": 1})
    assert len(raw_lines(ledger_dir)) == 2
    first = next(iter(ledger.records()))
    assert first.payload["note"] == nasty and first.payload["key\nwith newline"] == "v"
    assert verify_ledger(ledger_dir).ok


def test_F2_AC1_a_one_megabyte_payload_round_trips(ledger: Ledger, ledger_dir: Path) -> None:
    big = "x" * 1_000_000
    ledger.append("note", {"big": big, "unicode": "é" * 1000})
    assert next(iter(ledger.records())).payload["big"] == big
    assert verify_ledger(ledger_dir).ok


def test_F2_AC1_empty_payload_is_allowed(ledger: Ledger) -> None:
    assert dict(ledger.append("note", {}).payload) == {}


def test_F2_AC1_the_caller_cannot_mutate_a_stored_record_through_the_payload_it_passed(ledger: Ledger, ledger_dir: Path) -> None:
    payload: dict[str, Any] = {"list": [1, 2]}
    ledger.append("note", payload)
    payload["list"].append(3)
    payload["new"] = 1
    stored = next(iter(ledger.records()))
    assert dict(stored.payload) == {"list": [1, 2]}
    assert verify_ledger(ledger_dir).ok


# --- secrets (F1.AC5) --------------------------------------------------------------------------------

def test_F2_F1_AC5_a_secret_value_is_refused_and_never_revealed(ledger: Ledger, ledger_dir: Path) -> None:
    secret = SecretValue(CANARY_SECRETS["COPYTRADE_LLM_API_KEY"])
    with pytest.raises(TypeError):
        ledger.append("note", {"key": secret})
    assert find_canary_leaks(ledger_file(ledger_dir).read_bytes().decode("utf-8", errors="replace")) == []


def test_F2_F1_AC5_normal_operation_never_writes_environment_secrets_into_the_ledger(
    ledger: Ledger, ledger_dir: Path, canary_secrets: dict[str, str]
) -> None:
    assert all(os.environ[name] == value for name, value in canary_secrets.items())  # canaries are live in the env
    for i in range(5):
        ledger.append("note", {"i": i}, client_order_id=f"c-{i}")
    with pytest.raises(DuplicateClientOrderIdError):
        ledger.append("note", {"i": 0}, client_order_id="c-0")
    text = ledger_file(ledger_dir).read_bytes().decode("utf-8", errors="replace")
    assert find_canary_leaks(text) == []
