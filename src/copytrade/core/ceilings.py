"""Hard ceilings and floors compiled into code (F1.AC2, invariant A3).

Every §3 key with a Max has it here as a constant; config can never raise it. Floors (Min) likewise.
Keys whose bound is another key (e.g. ``select.min_followed`` <= ``select.max_followed``) are
checked by the loader as cross-key rules.

The module also exposes ``HIGH_LEVERAGE_COIN_UNIVERSE: frozenset[str]``, the compiled set that
``risk.high_leverage_coins`` must be a subset of ({BTC, ETH, SOL}, spec §3.6).

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Bounds:
    """Compiled bounds of one §3 key. ``None`` means unbounded on that side.

    ``min_exclusive`` is True where the spec says "> x" (e.g. ``storage.price_usd_per_gb_month`` > 0).
    """

    min: int | Decimal | None
    max: int | Decimal | None
    min_exclusive: bool


def ceiling_for(key: str) -> Bounds:
    """Return the compiled bounds of a numeric §3 key.

    Raises:
        KeyError: ``key`` is not a numeric §3 key.
    """
    raise NotImplementedError
