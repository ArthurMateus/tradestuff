"""The one definition of which Hyperliquid coin names are in v1's universe (R4.AC1)."""

from __future__ import annotations

PSEUDO_COIN_PREFIX = "#"


def is_pseudo_coin(coin: str) -> bool:
    """``#N`` names appear in fills but are not perps: not in the meta universe, and candleSnapshot answers 500."""
    return coin.startswith(PSEUDO_COIN_PREFIX)


def is_core_perp(coin: str) -> bool:
    """A core perp name: not empty, not a pseudo-coin (``#N``), not spot (``@n``, ``A/B``), not a HIP-3 dex
    perp (``dex:COIN``)."""
    return bool(coin) and not (is_pseudo_coin(coin) or coin.startswith("@") or "/" in coin or ":" in coin)
