"""The gate token (F10.AC1). F11 owns the type so F10 can be built against it.

F10 holds a ``GateAuthority`` and calls ``issue`` only after ``risk_gate.check()`` approved the intent. The broker
is built with the same authority object and verifies every token with it.

A token is ``(token_id, intent_digest, mac)``. ``intent_digest`` is the SHA-256 of an unambiguous encoding of every
field of the approved intent, and ``mac`` is HMAC-SHA256 of ``token_id`` and ``intent_digest`` under the authority's
secret key. Without the key a token cannot be forged, and changing any intent field breaks the binding.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from decimal import Decimal

from copytrade.paper.types import GateToken, OrderIntent, StopIntent

_TOKEN_ID_BYTES = 16


def _decimal_text(value: Decimal) -> str:
    """One text per numeric value (``1.0`` and ``1.00`` agree), positional notation."""
    return format(value.normalize(), "f")


def intent_digest(intent: OrderIntent | StopIntent) -> str:
    """SHA-256 (hex) over every field of ``intent``, encoded as a JSON list so no two intents share an encoding.

    Raises:
        TypeError: ``intent`` is neither an ``OrderIntent`` nor a ``StopIntent``, or a field has the wrong type.
    """
    fields: list[str | int | None]
    if isinstance(intent, OrderIntent):
        fields = [
            "order",
            intent.client_order_id,
            intent.coin,
            intent.side,
            _decimal_text(intent.qty),
            intent.action.value,
            intent.decided_at_ms,
            _decimal_text(intent.decision_px),
            intent.trade_id,
            intent.share_id,
            intent.leverage,
            intent.exit_reason,
        ]
    elif isinstance(intent, StopIntent):
        fields = [
            "stop",
            intent.client_order_id,
            intent.coin,
            intent.kind,
            intent.side,
            _decimal_text(intent.qty),
            _decimal_text(intent.trigger_px),
            intent.trade_id,
            intent.share_id,
        ]
    else:
        raise TypeError("only an OrderIntent or a StopIntent can be approved")
    encoded = json.dumps(fields, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


class GateAuthority:
    """Issues and verifies single-use gate tokens under a secret ``key`` (never logged, never in ``repr``)."""

    def __init__(self, key: bytes) -> None:
        if len(key) == 0:
            raise ValueError("the gate authority key must not be empty")
        self._key = bytes(key)

    def __repr__(self) -> str:
        return "GateAuthority(<key hidden>)"

    def _mac(self, token_id: str, digest: str) -> str:
        message = json.dumps([token_id, digest], separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def issue(self, intent: OrderIntent | StopIntent) -> GateToken:
        """A fresh token bound to exactly ``intent``."""
        digest = intent_digest(intent)
        token_id = secrets.token_hex(_TOKEN_ID_BYTES)
        return GateToken(token_id=token_id, intent_digest=digest, mac=self._mac(token_id, digest))

    def verify(self, token: GateToken, intent: OrderIntent | StopIntent) -> bool:
        """``True`` iff ``token`` was issued by this authority for exactly ``intent``. It does not consume the token
        (the broker does) and never raises for a forged or malformed token."""
        try:
            expected_digest = intent_digest(intent)
            claimed = (token.token_id, token.intent_digest, token.mac)
            if not all(type(part) is str for part in claimed):
                return False
            genuine = hmac.compare_digest(
                self._mac(token.token_id, token.intent_digest).encode("ascii"), token.mac.encode("utf-8")
            )
            bound = hmac.compare_digest(expected_digest.encode("ascii"), token.intent_digest.encode("utf-8"))
        except (TypeError, ValueError, AttributeError, ArithmeticError):  # a malformed token is simply not valid
            return False
        return genuine and bound
