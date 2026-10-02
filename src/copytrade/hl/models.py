"""Typed, validated Hyperliquid responses (F3.AC6). Money fields are Decimal-based, never float."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from copytrade.core.money import Notional, Pnl, Price, Qty


@dataclass(frozen=True)
class Fill:
    """One leader fill (``userFills`` / ``userFillsByTime`` / WS ``userFills``). ``dir`` is passed through verbatim."""

    coin: str
    px: Price
    sz: Qty
    side: str  # "B" or "A"
    time_ms: int
    start_position: Qty
    dir: str
    closed_pnl: Qty
    fee: Qty
    crossed: bool
    oid: int
    tid: int
    hash: str
    liquidation: bool = False  # the fill carries the exchange's ``liquidation`` object (whatever ``dir`` says)


@dataclass(frozen=True)
class BookLevel:
    px: Price
    sz: Qty
    n: int


@dataclass(frozen=True)
class L2Book:
    coin: str
    time_ms: int
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]


@dataclass(frozen=True)
class LeaderPosition:
    coin: str
    szi: Qty  # signed: long > 0, short < 0
    entry_px: Price | None
    unrealized_pnl: Pnl | None = None  # as the exchange reports it; None when the payload omits it


@dataclass(frozen=True)
class ClearinghouseState:
    account_value: Notional
    positions: tuple[LeaderPosition, ...]
    time_ms: int


@dataclass(frozen=True)
class Candle:
    open_ms: int
    close_ms: int
    coin: str
    interval: str
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Qty
    trades: int


@dataclass(frozen=True)
class PortfolioWindow:
    """One ``portfolio`` window ("day", "week", "month", "allTime", "perpDay", ...)."""

    account_value_history: tuple[tuple[int, Notional], ...]
    pnl_history: tuple[tuple[int, Qty], ...]
    volume: Qty


@dataclass(frozen=True)
class CoinSpec:
    """One ``meta`` universe row: lot size decimals, maximum leverage (integer x) and the delisting flag."""

    name: str
    sz_decimals: int
    max_leverage: int
    is_delisted: bool


@dataclass(frozen=True)
class AssetCtxRow:
    """One ``metaAndAssetCtxs`` context row (same index as the universe row): mark and oracle price, hourly funding
    rate (fraction) and open interest."""

    coin: str
    mark_px: Price
    oracle_px: Price
    funding: Decimal
    open_interest: Qty


@dataclass(frozen=True)
class MetaAndCtxs:
    """``metaAndAssetCtxs``: the universe and one context row per coin."""

    coins: tuple[CoinSpec, ...]
    contexts: tuple[AssetCtxRow, ...]


@dataclass(frozen=True)
class FundingRow:
    """One ``fundingHistory`` point: hourly funding rate and premium at ``time_ms``."""

    coin: str
    time_ms: int
    rate: Decimal
    premium: Decimal
