"""Adapters from the feature ports (F3/F4/F6/F10/F12) to the real REST client, the WebSocket connector and live data.

Every adapter is READ-ONLY toward Hyperliquid (info endpoint and info WebSocket only)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from copytrade.core.clock import Clock, OffsetEstimate
from copytrade.core.money import Price
from copytrade.hl.models import L2Book
from copytrade.hl.rest import HlRestClient
from copytrade.hl.ws import WsConnector
from copytrade.paper.types import CoinMeta
from copytrade.recorder.ports import AssetContext, FeedEvent, FundingPoint


class ExchangeOffsetSource:
    """``core.clock.OffsetSource``. One estimate = one ``l2Book`` info request for ``probe_coin`` at CRITICAL priority:
    ``offset_ms = book.time_ms - midpoint(local before, local after)`` and ``uncertainty_ms = max(1, ceil((after -
    before) / 2))`` plus 1 ms of exchange timestamp granularity. ``OSError`` / ``HlError`` from the request propagate
    as ``OSError`` (ClockSync treats that as a failed estimate)."""

    def __init__(self, *, rest: HlRestClient, clock: Clock, probe_coin: str) -> None:
        raise NotImplementedError

    def estimate(self) -> OffsetEstimate:
        raise NotImplementedError


class MarketHub:
    """``recorder.ports.MarketFeed`` over the info WebSocket (``l2Book`` per coin and ``allMids``), and the live-data
    store behind it: it is the ONLY consumer of the socket, the recorder polls it, and it keeps (a) the recent L2
    books per coin (``paper.ports.BookSource``) and (b) the latest mids (marks).

    - ``subscribe(coins)`` replaces the subscription set (subscribes the new coins, unsubscribes the dropped ones,
      ``allMids`` once). ``poll()`` never blocks and never raises: a lost connection is retried on a later poll
      (jittered backoff, resubscribing everything) and polls return ``()`` meanwhile.
    - Frames: ``{"channel":"l2Book","data":{"coin","time","levels":[bids,asks]}}`` -> ``L2Book``;
      ``{"channel":"allMids","data":{"mids":{coin: px}}}`` -> ``MidsUpdate(time_ms=None, ...)``. Anything else
      (subscriptionResponse, pong, malformed, non-finite or negative prices) is dropped and counted, never raised.
    - ``first_book_at_or_after(coin, time_ms)``: the earliest kept book with ``time_ms >= time_ms``, else ``None``
      (the paper broker then treats the book as unavailable). Books older than ``paper.max_book_age_ms`` x 4 are
      pruned and at most 64 books per coin are kept.
    - ``mids()``: latest mid per coin as ``Price`` and ``mid_time_ms`` the local receive time of that update.
    """

    def __init__(self, *, connector: WsConnector, clock: Clock, max_book_age_ms: int, seed: int) -> None:
        raise NotImplementedError

    def subscribe(self, coins: Sequence[str]) -> None:
        raise NotImplementedError

    def poll(self) -> Sequence[FeedEvent]:
        raise NotImplementedError

    def first_book_at_or_after(self, coin: str, time_ms: int) -> L2Book | None:
        raise NotImplementedError

    def mids(self) -> Mapping[str, Price]:
        raise NotImplementedError

    def mid_time_ms(self) -> int | None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class RestMarketSource:
    """``recorder.ports.MarketSource`` over ``metaAndAssetCtxs`` and ``fundingHistory`` (CRITICAL priority)."""

    def __init__(self, *, rest: HlRestClient, clock: Clock) -> None:
        raise NotImplementedError

    def asset_contexts(self) -> Sequence[AssetContext]:
        raise NotImplementedError

    def funding_history(self, coin: str, start_ms: int) -> Sequence[FundingPoint]:
        raise NotImplementedError


class RestMetaSource:
    """``paper.ports.MetaSource`` over ``metaAndAssetCtxs``: ``fetch()`` -> ``{coin: CoinMeta(sz_decimals,
    max_leverage)}`` for every listed (not delisted) core perp; ``delisted()`` -> coins the exchange flags
    ``isDelisted``. A failed fetch raises ``OSError`` (the gate then refuses entries ``meta_unavailable``)."""

    def __init__(self, *, rest: HlRestClient) -> None:
        raise NotImplementedError

    def fetch(self) -> Mapping[str, CoinMeta]:
        raise NotImplementedError

    def delisted(self) -> frozenset[str]:
        raise NotImplementedError


class HttpLeaderboardSource:
    """``recorder.ports.LeaderboardSource``: HTTP GET of ``url`` (the stats host) with a ``timeout_s`` deadline for
    the whole exchange; returns the body bytes exactly as received. Non-2xx, timeout, or a body above 64 MiB raises
    ``OSError`` / ``TimeoutError``. No redirects are followed."""

    def __init__(self, *, url: str, timeout_s: float) -> None:
        raise NotImplementedError

    def fetch(self) -> bytes:
        raise NotImplementedError


class ConfigCostModel:
    """``scoring.models.CostModel`` from config only: ``taker_fee_bps`` = ``cost.taker_fee_bps``; ``half_spread_bps``
    and ``delay_bps`` = the ``cost.fallback_half_spread_bps.*`` / ``cost.fallback_delay_slippage_bps.*`` value of the
    coin's tier (``major`` for BTC and ETH, ``alt`` otherwise) times ``cost.fallback_half_spread_mult`` for the
    spread (the conservative fallback of the F11 cost model; recorded data is stage 2)."""

    def __init__(self, config: Mapping[str, object]) -> None:
        raise NotImplementedError

    def taker_fee_bps(self) -> Decimal:
        raise NotImplementedError

    def half_spread_bps(self, coin: str, t_ms: int) -> Decimal:
        raise NotImplementedError

    def delay_bps(self, coin: str, t_ms: int) -> Decimal:
        raise NotImplementedError
