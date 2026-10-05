"""Value types and ports of the position manager (F12). Data only; every amount is Decimal-based (A6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from copytrade.core.money import Price, Qty
from copytrade.hl.models import Candle, ClearinghouseState, Fill
from copytrade.signals.models import Signal

PENDING_ENTRY = "pending_entry"
OPEN = "open"
CLOSED = "closed"


@dataclass(frozen=True)
class ShareState:
    """One leader's share of a coin, as the position manager books it.

    ``qty`` is positive coin units (0 while the entry is pending), ``entry_px`` the average fill price.
    ``open_risk_usd`` is ``qty x |entry_px - current_stop_px|``, and 0 once the stop is past the entry (never
    negative). ``initial_risk_usd`` is the same at the entry fill (the estimated exit fee is F18's) and
    ``max_committed_risk_usd`` the highest ``open_risk_usd`` the share has carried. ``atr`` is the ATR stored at entry
    (the trail never reads candles), ``best_px`` the best mark since entry (highest for a long, lowest for a short).
    """

    share_id: str
    trade_id: str
    signal_id: str
    leader: str
    coin: str
    is_long: bool
    status: str
    qty: Qty
    entry_px: Price
    initial_stop_px: Price
    current_stop_px: Price
    initial_risk_usd: Decimal
    open_risk_usd: Decimal
    max_committed_risk_usd: Decimal
    atr: Decimal
    best_px: Price
    tp_done: bool


class CandleReader(Protocol):
    """Closed candles of a coin (the F4 ``CandleStore.get`` signature). May raise (``OSError``)."""

    def get(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Sequence[Candle]: ...


class LeaderState(Protocol):
    """The leader's ``clearinghouseState`` (account value for sizing, positions for reconciliation). May raise."""

    def clearinghouse_state(self, wallet: str) -> ClearinghouseState: ...


class LeaderFills(Protocol):
    """The leader's fills inside ``[start_ms, end_ms]`` (``userFillsByTime``). May raise."""

    def user_fills_by_time(self, wallet: str, start_ms: int, end_ms: int) -> Sequence[Fill]: ...


class EntryPolicy(Protocol):
    """The entry filter (F9, later): the volatility multiplier for an open, or ``None`` to veto it. May raise."""

    def vol_mult(self, signal: Signal) -> Decimal | None: ...
