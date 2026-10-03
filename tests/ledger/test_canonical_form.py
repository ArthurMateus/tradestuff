"""Round 2 (F2.AC1): the stored form is the canonical form, and the payload codec's ``$`` escape is airtight.

A hash covers the canonical bytes, so a line can be rewritten in ways that keep the hash valid: whitespace, key
order, duplicate keys, ``\\u`` escapes, ``\\r``, ``-0``. Verification must still refuse every one of them at
that line's sequence number, because the stored bytes must equal what ``encode_line`` would write.

Spec: 04-spec.md F2.AC1, invariant A6.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.ledger.codec import MAX_DEPTH, decode_value, encode_value
from copytrade.ledger.errors import LedgerCorruptError
from copytrade.ledger.records import GENESIS_HASH
from copytrade.ledger.store import Ledger, read_records, verify_ledger
from tests.ledger.helpers import FakeClock, ledger_file, raw_lines


def _build(directory: Path) -> None:
    with Ledger.open(directory, clock=FakeClock()) as ledger:
        ledger.append("note", {"a": 0, "b": "note", "c": [1, 2]})
        ledger.append("note", {"a": 0, "b": "note", "c": [1, 2]}, client_order_id="c-2")
        ledger.append("note", {"a": 0, "b": "note", "c": [1, 2]})


def _reordered(line: bytes) -> bytes:
    parsed = json.loads(line)
    reversed_items = dict(reversed(list(parsed.items())))
    return json.dumps(reversed_items, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"


REWRITES: dict[str, Callable[[bytes], bytes]] = {
    "space_after_comma": lambda line: line.replace(b",", b", ", 1),
    "space_after_colon": lambda line: line.replace(b":", b": ", 1),
    "space_before_brace": lambda line: b" " + line,
    "spaces_before_newline": lambda line: line[:-1] + b"  \n",
    "reordered_keys": _reordered,
    "duplicate_key_same_value": lambda line: line.replace(b'"kind":"note"', b'"kind":"note","kind":"note"', 1),
    "unicode_escape_in_string": lambda line: line.replace(b'"note"', b'"\\u006eote"', 1),
    "unicode_escape_in_key": lambda line: line.replace(b'"kind"', b'"\\u006bind"', 1),
    "carriage_return": lambda line: line[:-1] + b"\r\n",
    "negative_zero_int": lambda line: line.replace(b'"a":0', b'"a":-0', 1),
    "escaped_slash_solidus": lambda line: line.replace(b'"note"', b'"n\\u006fte"', 1),
}


@pytest.mark.parametrize("name", sorted(REWRITES))
@pytest.mark.parametrize("target", [1, 2, 3])
def test_F2_AC1_non_canonical_rewrite_with_a_valid_hash_fails_verification_at_that_seq(
    ledger_dir: Path, name: str, target: int
) -> None:
    _build(ledger_dir)
    lines = raw_lines(ledger_dir)
    rewritten = REWRITES[name](lines[target - 1])
    assert rewritten != lines[target - 1], "the rewrite must actually change the bytes"
    # The rewrite is meaningless to the parser: the same record, so the same hash. Only the bytes differ.
    assert json.loads(rewritten) == json.loads(lines[target - 1])
    lines[target - 1] = rewritten
    ledger_file(ledger_dir).write_bytes(b"".join(lines))

    result = verify_ledger(ledger_dir)
    assert not result.ok
    assert result.failed_seq == target
    with pytest.raises(LedgerCorruptError) as caught:
        list(read_records(ledger_dir))
    assert caught.value.seq == target
    with pytest.raises(LedgerCorruptError) as opened:
        Ledger.open(ledger_dir, clock=FakeClock())
    assert opened.value.seq == target


def test_F2_AC1_the_untouched_ledger_used_by_the_rewrite_tests_verifies(ledger_dir: Path) -> None:
    _build(ledger_dir)
    result = verify_ledger(ledger_dir)
    assert result.ok
    assert result.record_count == 3


# ---- the "$" escape in the payload codec ------------------------------------------------------------------

RESERVED_LOOKING = {
    "$dec": "1.5",
    "$": "bare",
    "$$dec": {"$dec": "nested", "$$": 1},
    "outer": {"inner": {"$dec": ["x", {"$dec": "y"}]}},
    "$$$": None,
}


def test_F2_AC1_dollar_keys_round_trip_as_strings_and_maps_never_as_decimal() -> None:
    restored = decode_value(encode_value(RESERVED_LOOKING))
    assert restored == RESERVED_LOOKING
    assert restored["$dec"] == "1.5"
    assert type(restored["$dec"]) is str
    assert not isinstance(restored["$$dec"], Decimal)
    assert restored["$$dec"]["$dec"] == "nested"
    assert not any(isinstance(v, Decimal) for v in restored["outer"]["inner"]["$dec"])


def test_F2_AC1_a_user_dec_map_is_not_a_decimal_but_a_real_decimal_still_is() -> None:
    user = {"$dec": "1.5"}
    assert decode_value(encode_value(user)) == user
    assert decode_value(encode_value(Decimal("1.5"))) == Decimal("1.5")
    assert type(decode_value(encode_value(Decimal("1.5")))) is Decimal
    assert encode_value(user) != encode_value(Decimal("1.5"))


def test_F2_AC1_every_dollar_key_is_stored_with_one_extra_dollar() -> None:
    assert encode_value({"$dec": 1, "$": 2, "$$x": 3, "plain": 4}) == {"$$dec": 1, "$$": 2, "$$$x": 3, "plain": 4}


@given(
    st.recursive(
        st.none() | st.booleans() | st.integers() | st.text(max_size=8),
        lambda inner: st.lists(inner, max_size=3)
        | st.dictionaries(st.text(alphabet="$decx", max_size=5), inner, max_size=3),
        max_leaves=12,
    )
)
def test_F2_AC1_property_encode_then_decode_is_the_identity_and_never_invents_a_decimal(value: Any) -> None:
    def no_decimal(v: Any) -> bool:
        if isinstance(v, dict):
            return all(no_decimal(x) for x in v.values())
        if isinstance(v, list):
            return all(no_decimal(x) for x in v)
        return not isinstance(v, Decimal)

    restored = decode_value(encode_value(value))
    assert restored == value
    assert no_decimal(restored)


def test_F2_AC1_dollar_keys_survive_a_real_ledger_round_trip(ledger_dir: Path) -> None:
    with Ledger.open(ledger_dir, clock=FakeClock()) as ledger:
        appended = ledger.append("note", RESERVED_LOOKING)
        assert appended.payload == RESERVED_LOOKING
    assert verify_ledger(ledger_dir).ok
    (record,) = list(read_records(ledger_dir))
    assert record.payload == RESERVED_LOOKING
    assert type(record.payload["$dec"]) is str


@pytest.mark.parametrize("key", ["$foo", "$", "$decimal", "$dec2"])
def test_F2_AC1_decoding_an_unescaped_reserved_key_is_refused(key: str) -> None:
    with pytest.raises(ValueError, match="reserved"):
        decode_value({key: 1})
    with pytest.raises(ValueError, match="reserved"):
        decode_value({"ok": [{"deep": {key: 1}}]})


@pytest.mark.parametrize(
    "stored",
    [{"$dec": "1", "x": 1}, {"$dec": 5}, {"$dec": "abc"}, {"$dec": "NaN"}, {"$dec": "Infinity"}, {"$dec": None}],
    ids=["dec_plus_sibling", "dec_not_text", "dec_malformed", "dec_nan", "dec_infinite", "dec_null"],
)
def test_F2_AC1_a_malformed_stored_decimal_marker_is_refused(stored: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        decode_value(stored)


def test_F2_AC1_a_stored_line_with_an_unescaped_reserved_key_fails_verification(ledger_dir: Path) -> None:
    with Ledger.open(ledger_dir, clock=FakeClock()) as ledger:
        ledger.append("note", {"$foo": 1})  # stored as "$$foo"
    (line,) = raw_lines(ledger_dir)
    assert b'"$$foo"' in line
    # Forge the line as an attacker would: same content with the key stored unescaped, hash recomputed so that
    # the chain itself is intact. Only the codec's refusal of the bare "$foo" can catch it.
    forged = json.loads(line)
    forged["payload"] = {"$foo": 1}
    body = {k: v for k, v in forged.items() if k != "hash"}
    escaped_body = dict(body, payload={"$$foo": 1})
    forged["hash"] = hashlib.sha256(
        bytes.fromhex(GENESIS_HASH)
        + json.dumps(escaped_body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    ledger_file(ledger_dir).write_bytes(
        json.dumps(forged, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    )
    result = verify_ledger(ledger_dir)
    assert not result.ok
    assert result.failed_seq == 1


# ---- nesting depth guard ---------------------------------------------------------------------------------


def _nested_maps(levels: int) -> Any:
    value: Any = "leaf"
    for _ in range(levels):
        value = {"k": value}
    return value


def _nested_lists(levels: int) -> Any:
    value: Any = "leaf"
    for _ in range(levels):
        value = [value]
    return value


@pytest.mark.parametrize("build", [_nested_maps, _nested_lists])
def test_F2_AC1_nesting_exactly_at_the_limit_is_accepted_and_one_deeper_is_refused(
    build: Callable[[int], Any],
) -> None:
    assert decode_value(encode_value(build(MAX_DEPTH))) == build(MAX_DEPTH)
    with pytest.raises(ValueError, match="deep"):
        encode_value(build(MAX_DEPTH + 1))
    with pytest.raises(ValueError, match="deep"):
        decode_value(build(MAX_DEPTH + 1))


@pytest.mark.parametrize("build", [_nested_maps, _nested_lists])
def test_F2_AC1_absurdly_deep_input_is_a_value_error_not_a_recursion_error(build: Callable[[int], Any]) -> None:
    with pytest.raises(ValueError, match="deep"):
        encode_value(build(100_000))
    with pytest.raises(ValueError, match="deep"):
        decode_value(build(100_000))


def test_F2_AC1_appending_a_too_deep_payload_writes_nothing_and_leaves_the_ledger_usable(ledger: Ledger) -> None:
    ledger.append("note", {"n": _nested_maps(MAX_DEPTH - 1)})
    before = ledger.last_seq
    with pytest.raises(ValueError, match="deep"):
        ledger.append("note", {"n": _nested_maps(MAX_DEPTH + 1)})
    assert ledger.last_seq == before
    assert not ledger.failed
    ledger.append("note", {"ok": True})
    assert ledger.verify().ok


def test_F2_AC1_a_stored_line_nested_past_the_recursion_limit_fails_verification_cleanly(ledger_dir: Path) -> None:
    _build(ledger_dir)
    lines = raw_lines(ledger_dir)
    lines[1] = b'{"payload":' + b"[" * 200_000 + b"]" * 200_000 + b"}\n"
    ledger_file(ledger_dir).write_bytes(b"".join(lines))
    result = verify_ledger(ledger_dir)
    assert not result.ok
    assert result.failed_seq == 2
