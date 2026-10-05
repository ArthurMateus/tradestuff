"""The ``/flatten`` PIN check (F14.AC5): PBKDF2-HMAC-SHA256, constant-time compare, sliding-window lockout.

Fails closed: no configured hash or salt means no PIN is ever accepted. The PIN, hash and salt never leave this
module (no log, no exception message).
"""

from __future__ import annotations

import hashlib
import hmac
from collections import deque
from typing import Literal

from copytrade.core.secrets import SecretValue

PBKDF2_ITERATIONS = 200_000

PinResult = Literal["ok", "bad_pin", "pin_locked", "pin_not_configured"]


class PinGuard:
    """Failures are counted inside a sliding ``lockout_ms`` window. At ``max_attempts`` the lock lasts until the last
    failure plus ``lockout_ms`` (free exactly at that boundary); a correct PIN clears the failures."""

    def __init__(
        self, pin_hash: SecretValue | None, pin_salt: SecretValue | None, *, max_attempts: int, lockout_ms: int
    ) -> None:
        self._hash = pin_hash
        self._salt = pin_salt
        self._max_attempts = max_attempts
        self._lockout_ms = lockout_ms
        self._failures: deque[int] = deque()
        self._locked_until_ms = 0

    def is_locked(self, now_ms: int) -> bool:
        return now_ms < self._locked_until_ms

    def check(self, pin: str, now_ms: int) -> PinResult:
        if self._hash is None or self._salt is None:
            return "pin_not_configured"
        if self.is_locked(now_ms):
            return "pin_locked"
        candidate = hashlib.pbkdf2_hmac(
            "sha256", pin.encode("utf-8"), self._salt.reveal().encode("utf-8"), PBKDF2_ITERATIONS
        ).hex()
        if hmac.compare_digest(candidate.encode("ascii"), self._hash.reveal().strip().lower().encode("utf-8")):
            self._failures.clear()
            return "ok"
        self._record_failure(now_ms)
        return "bad_pin"

    def _record_failure(self, now_ms: int) -> None:
        while self._failures and now_ms - self._failures[0] >= self._lockout_ms:
            self._failures.popleft()
        self._failures.append(now_ms)
        if len(self._failures) >= self._max_attempts:
            self._locked_until_ms = now_ms + self._lockout_ms
            self._failures.clear()
