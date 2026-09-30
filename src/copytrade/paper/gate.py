"""The gate token (F10.AC1). F11 owns the type so F10 can be built against it.

F10 holds a ``GateAuthority`` and calls ``issue`` only after ``risk_gate.check()`` approved the intent. The broker
is built with the same authority object and verifies every token with it.
"""

from __future__ import annotations

from copytrade.paper.types import GateToken, OrderIntent, StopIntent


class GateAuthority:
    """Issues and verifies single-use gate tokens under a secret ``key`` (never logged)."""

    def __init__(self, key: bytes) -> None:
        raise NotImplementedError

    def issue(self, intent: OrderIntent | StopIntent) -> GateToken:
        """A fresh token bound to exactly ``intent``."""
        raise NotImplementedError

    def verify(self, token: GateToken, intent: OrderIntent | StopIntent) -> bool:
        """``True`` iff ``token`` was issued by this authority for exactly ``intent``. It does not consume the token
        (the broker does) and never raises for a forged or malformed token."""
        raise NotImplementedError
