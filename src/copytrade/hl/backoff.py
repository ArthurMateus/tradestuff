"""Exponential backoff with jitter (F3.AC2, F3.AC3)."""

from __future__ import annotations

import random


def backoff_delay_s(attempt: int, *, base_s: float, max_s: float, rng: random.Random) -> float:
    """Delay before retry number ``attempt`` (0-based).

    Contract: ``min(max_s, base_s * 2**attempt) <= delay <= max_s``, at most twice the un-jittered
    value, and random (drawn from ``rng``) so that it is not constant.

    Raises:
        ValueError: ``attempt`` < 0, ``base_s`` <= 0 or ``max_s`` < ``base_s``.
    """
    raise NotImplementedError
