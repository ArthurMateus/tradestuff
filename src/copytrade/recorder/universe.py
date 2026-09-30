"""Recording-universe selection (F4.AC1). Pure function."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

ALWAYS_RECORDED = ("BTC", "ETH", "SOL")


def select_universe(
    *,
    traded_coins: Iterable[str],
    hip3_markets: Iterable[str],
    volume_24h_usd: Mapping[str, Decimal],
    max_coins: int,
) -> tuple[str, ...]:
    """The coins to record, sorted by name.

    Candidates: ``traded_coins`` (core perps only; spot names starting ``@`` or containing ``/`` and ``dex:``
    names are dropped from this input), ``ALWAYS_RECORDED`` and every name in ``hip3_markets``. When there are
    more than ``max_coins`` candidates the lowest 24h volume is dropped first (a missing volume counts as 0; a
    tie drops the name that sorts last). ``ALWAYS_RECORDED`` is never dropped.

    Raises:
        ValueError: ``max_coins`` is smaller than ``len(ALWAYS_RECORDED)``.
    """
    if max_coins < len(ALWAYS_RECORDED):
        raise ValueError(f"max_coins must be at least {len(ALWAYS_RECORDED)} to keep {', '.join(ALWAYS_RECORDED)}")
    always = frozenset(ALWAYS_RECORDED)
    candidates = {coin for coin in traded_coins if _is_core_perp(coin)} | always | set(hip3_markets)
    if len(candidates) <= max_coins:
        return tuple(sorted(candidates))
    others = sorted(candidates - always, key=lambda coin: (-volume_24h_usd.get(coin, Decimal(0)), coin))
    return tuple(sorted(always | set(others[: max_coins - len(always)])))


def _is_core_perp(coin: str) -> bool:
    """A core perp name: not empty, not a spot name (``@n``, ``A/B``) and not a dex market (``dex:COIN``)."""
    return bool(coin) and not coin.startswith("@") and "/" not in coin and ":" not in coin
