"""Exponential backoff with jitter (F3.AC2, F3.AC3)."""

from __future__ import annotations

import math
import random

_MAX_DOUBLINGS = 62  # 2**62 already exceeds any permitted max_s / base_s ratio; avoids float overflow


def backoff_delay_s(attempt: int, *, base_s: float, max_s: float, rng: random.Random) -> float:
    """Delay before retry number ``attempt`` (0-based).

    Contract: ``min(max_s, base_s * 2**attempt) <= delay <= max_s``, at most twice the un-jittered
    value, and random (drawn from ``rng``) so that it is not constant. Jitter is upward only, so the
    exponential floor (and with it the "at most one request per second" rule at ``base_s`` = 1) always holds.

    Raises:
        ValueError: ``attempt`` < 0, ``base_s`` <= 0 or ``max_s`` < ``base_s``.
    """
    if attempt < 0:
        raise ValueError("attempt must not be negative")
    if not base_s > 0:
        raise ValueError("base_s must be positive")
    if not max_s >= base_s:
        raise ValueError("max_s must not be below base_s")
    floor = min(max_s, base_s * math.ldexp(1.0, min(attempt, _MAX_DOUBLINGS)))
    return min(max_s, floor + rng.random() * floor)
