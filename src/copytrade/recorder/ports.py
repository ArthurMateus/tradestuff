"""External boundaries of the recorder (F4). Tests inject fakes; F21 wires real adapters.

Only Protocols and value types live here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from copytrade.core.money import Price, Qty
from copytrade.hl.errors import HlError
from copytrade.hl.models import Candle, L2Book

# What a REST-style source may raise for "the source failed": the recorder records a gap and carries on.
# A real adapter over ``HlRestClient`` can simply let ``HlError`` through.
SOURCE_FAILURES: tuple[type[Exception], ...] = (OSError, HlError)


@dataclass(frozen=True)
class MidsUpdate:
    """One ``allMids`` update: every coin's mid. ``time_ms`` is the exchange time when the feed gives one."""

    time_ms: int | None
    mids: Mapping[str, Price]


FeedEvent = L2Book | MidsUpdate


class MarketFeed(Protocol):
    """The live market WebSocket (L2 books and ``allMids``). ``poll`` never blocks."""

    def subscribe(self, coins: Sequence[str]) -> None:
        """Replace the subscription set with ``coins`` (the recording universe)."""
        ...

    def poll(self) -> Sequence[FeedEvent]:
        """Every event received since the last call, in arrival order."""
        ...


@dataclass(frozen=True)
class AssetContext:
    """Mark, oracle, funding and open interest of one coin (a ``metaAndAssetCtxs`` row)."""

    coin: str
    mark: Price
    oracle: Price
    funding: Decimal
    open_interest: Qty
    time_ms: int | None


@dataclass(frozen=True)
class FundingPoint:
    """One hourly funding-history point."""

    coin: str
    time_ms: int
    rate: Decimal
    premium: Decimal


class MarketSource(Protocol):
    """REST-style market data. Both calls may raise ``OSError`` or ``TimeoutError``."""

    def asset_contexts(self) -> Sequence[AssetContext]: ...

    def funding_history(self, coin: str, start_ms: int) -> Sequence[FundingPoint]:
        """Funding points with ``time_ms >= start_ms``."""
        ...


class LeaderboardSource(Protocol):
    """The full leaderboard JSON exactly as fetched. ``fetch`` may raise ``OSError`` or ``TimeoutError``."""

    def fetch(self) -> bytes: ...


class UniverseSource(Protocol):
    """Inputs of the recording universe (F4.AC1)."""

    def traded_coins(self, lookback_days: int) -> frozenset[str]:
        """Core perps traded in the last ``lookback_days`` by any followed or top-K candidate wallet."""
        ...

    def hip3_markets(self) -> Sequence[str]: ...

    def volume_24h_usd(self) -> Mapping[str, Decimal]: ...


class CandleSource(Protocol):
    """Exchange candles (the real one wraps ``HlRestClient.candles`` at CRITICAL priority). May raise ``OSError``."""

    def fetch(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Sequence[Candle]: ...


class OpenCoinsSource(Protocol):
    """Coins with an open share, shadow or mirror during a window (owned by F12; a stub set in F4 tests)."""

    def coins_open_between(self, start_ms: int, end_ms: int) -> frozenset[str]: ...


class DiskProbe(Protocol):
    """Free space of the volume holding ``path`` in GB. An external boundary. A path that does not exist yet is probed
    through its nearest existing parent; ``OSError`` means the space cannot be read, and the recorder then stops
    recording (A2: unknown free space is treated as none)."""

    def free_gb(self, path: Path) -> Decimal: ...


@dataclass(frozen=True)
class Backlog:
    """Finished days not yet archived (from F23): how many days and how many GB."""

    days: int
    gb: Decimal


class BacklogSource(Protocol):
    def unarchived_backlog(self) -> Backlog: ...
