"""Local wallet registry (F4.AC2, D2): every wallet ever seen stays. There is no removal API."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


class WalletRegistry:
    """Persistent set of lower-case wallet addresses under ``directory`` (created if needed).

    ``add`` ignores anything that is not a 0x + 40-hex address. State survives a new instance over the same directory.
    """

    def __init__(self, directory: Path) -> None:
        raise NotImplementedError

    def add(self, wallets: Iterable[str]) -> int:
        """Add wallets; return how many were new. Durable before returning."""
        raise NotImplementedError

    def wallets(self) -> frozenset[str]:
        raise NotImplementedError


def wallets_in_leaderboard(body: bytes) -> tuple[str, ...]:
    """The ``ethAddress`` of every row of ``leaderboardRows`` in a leaderboard JSON body, lower-cased, in order.

    Raises:
        ValueError: ``body`` is not JSON or has no ``leaderboardRows`` list.
    """
    raise NotImplementedError
