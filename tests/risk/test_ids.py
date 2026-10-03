"""F10.AC8 deterministic client order IDs (A5)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.risk.ids import client_order_id

BASE: dict[str, Any] = dict(run_id="run1", leader="0xabc", coin="SOL", tids=(11, 22), action="open", share_id="S1")


@pytest.mark.unit
def test_F10_AC8_the_id_is_deterministic_lowercase_hex_and_bounded() -> None:
    a, b = client_order_id(**BASE), client_order_id(**BASE)
    assert a == b
    assert re.fullmatch(r"[0-9a-f]{32,64}", a)


@pytest.mark.unit
def test_F10_AC8_the_order_of_the_signal_tids_does_not_matter() -> None:
    assert client_order_id(**{**BASE, "tids": (22, 11)}) == client_order_id(**BASE)
    assert client_order_id(**{**BASE, "tids": [22, 11]}) == client_order_id(**BASE)


@pytest.mark.unit
@pytest.mark.parametrize(
    "field,other",
    [
        ("run_id", "run2"),
        ("leader", "0xabd"),
        ("coin", "ETH"),
        ("tids", (11, 23)),
        ("action", "close"),
        ("share_id", "S2"),
    ],
)
def test_F10_AC8_every_field_changes_the_id(field: str, other: Any) -> None:
    assert client_order_id(**{**BASE, field: other}) != client_order_id(**BASE)


@pytest.mark.unit
def test_F10_AC8_the_encoding_is_unambiguous_across_field_boundaries() -> None:
    assert client_order_id(**{**BASE, "run_id": "ab", "leader": "c"}) != client_order_id(
        **{**BASE, "run_id": "a", "leader": "bc"}
    )
    assert client_order_id(**{**BASE, "tids": (1, 23)}) != client_order_id(**{**BASE, "tids": (12, 3)})
    assert client_order_id(**{**BASE, "tids": (123,)}) != client_order_id(**{**BASE, "tids": (1, 23)})
    assert client_order_id(**{**BASE, "tids": ()}) != client_order_id(**{**BASE, "tids": (0,)})


@pytest.mark.unit
def test_F10_AC8_unicode_and_empty_text_do_not_collide_or_raise() -> None:
    ids = {
        client_order_id(**{**BASE, "leader": leader}) for leader in ("", "é", "é", "0xabc", "0xABC", "\u0000")
    }
    assert len(ids) == 6


@pytest.mark.unit
@given(
    a=st.tuples(st.text(max_size=6), st.text(max_size=6), st.text(max_size=6), st.lists(st.integers(0, 10**9), max_size=4)),
    b=st.tuples(st.text(max_size=6), st.text(max_size=6), st.text(max_size=6), st.lists(st.integers(0, 10**9), max_size=4)),
)
@settings(max_examples=400)
def test_F10_AC8_property_equal_ids_only_for_equal_inputs(a: Any, b: Any) -> None:
    def make(t: Any) -> str:
        return client_order_id(run_id=t[0], leader=t[1], coin="SOL", tids=t[3], action=t[2], share_id="S1")

    same = (a[0], a[1], a[2], sorted(a[3])) == (b[0], b[1], b[2], sorted(b[3]))
    assert (make(a) == make(b)) == same
