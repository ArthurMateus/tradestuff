"""Typed, validated Hyperliquid responses (F3.AC6). Money fields are Decimal-based, never float."""

from __future__ import annotations

from dataclasses import dataclass

from copytrade.core.money import Notional, Price, Qty


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
