"""Canonical JSON encoding of ledger payloads (F2.AC1, invariant A6).

A payload is a tree of ``str``, ``int``, ``bool``, ``None``, finite ``Decimal``, lists (tuples are stored as
lists) and mappings with ``str`` keys. Anything else is refused: a ``float`` (money is Decimal), a non-finite
``Decimal``, a non-``str`` key, a ``str`` subclass or any other type (so a ``SecretValue`` can never be
written). Refusals name the type, never the value.

Stored form: JSON with sorted keys, no whitespace and ASCII only, so a record is one line, key order never
changes the bytes and hostile text (newlines, U+2028, NUL) cannot break the line structure.

A ``Decimal`` is stored as ``{"$dec": "<str>"}`` and keeps its exact scale, so ``Decimal("1.0")``, ``"1.0"``
and ``1`` stay three different values. To keep that marker unambiguous, every mapping key that starts with
``$`` is stored with one extra ``$`` in front and loses it again on decoding.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_DEPTH = 32
_DECIMAL_TAG = "$dec"
_ESCAPE = "$"


def dumps(value: object) -> bytes:
    """Deterministic ASCII JSON bytes of an already encoded tree (sorted keys, compact, no NaN)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def encode_value(value: object, depth: int = 0) -> Any:
    """Validate ``value`` and return the JSON-ready tree that represents it.

    Raises:
        TypeError: a float, a key that is not a ``str``, or any type outside the allowed set.
        ValueError: a non-finite ``Decimal`` or nesting deeper than ``MAX_DEPTH``.
    """
    if depth > MAX_DEPTH:
        raise ValueError(f"payload is nested deeper than {MAX_DEPTH} levels")
    if value is None or type(value) is bool or type(value) is str or type(value) is int:
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("a Decimal in a payload must be finite")
        return {_DECIMAL_TAG: str(value)}
    if isinstance(value, float):
        raise TypeError("floats are not allowed in a payload; use Decimal (A6)")
    if isinstance(value, Mapping):
        encoded: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"payload keys must be str, not {type(key).__name__}")
            stored_key = _ESCAPE + key if key.startswith(_ESCAPE) else key
            encoded[stored_key] = encode_value(item, depth + 1)
        return encoded
    if isinstance(value, (list, tuple)):
        return [encode_value(item, depth + 1) for item in value]
    raise TypeError(f"{type(value).__name__} cannot be stored in a payload")


def decode_value(value: object, depth: int = 0) -> Any:
    """Rebuild a payload value from its JSON tree (the inverse of ``encode_value``).

    Raises:
        ValueError: the tree is not something ``encode_value`` produces.
    """
    if depth > MAX_DEPTH:
        raise ValueError("stored payload is nested too deeply")
    if value is None or type(value) is bool or type(value) is str or type(value) is int:
        return value
    if isinstance(value, list):
        return [decode_value(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if value.keys() == {_DECIMAL_TAG}:
            return _decode_decimal(value[_DECIMAL_TAG])
        decoded: dict[str, Any] = {}
        for key, item in value.items():
            if key.startswith(_ESCAPE + _ESCAPE):
                key = key[1:]  # noqa: PLW2901 - the stored key loses its escape
            elif key.startswith(_ESCAPE):
                raise ValueError("stored payload has an unescaped reserved key")
            decoded[key] = decode_value(item, depth + 1)
        return decoded
    raise ValueError(f"stored payload holds a {type(value).__name__}")


def _decode_decimal(text: object) -> Decimal:
    if type(text) is not str:
        raise ValueError("stored Decimal is not text")
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("stored Decimal is malformed") from exc
    if not result.is_finite():
        raise ValueError("stored Decimal is not finite")
    return result
