"""External boundaries of the risk gate (F10). Tests inject fakes for what is not built yet (F12, F8) or is a true
boundary (time, market data); F21 wires the real adapters."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from copytrade.core.clock import Timestamp
from copytrade.risk.types import ShareExposure


class AccountView(Protocol):
    """Mark-to-market equity of the paper account (F12/F21)."""

    def equity_usd(self) -> Decimal | None:
        """Equity in USD, or ``None`` when unknown. May raise."""
        ...


class ShareBook(Protocol):
    """Every open share (F12). May raise."""

    def open_shares(self) -> Sequence[ShareExposure]: ...


class ReturnsSource(Protocol):
    """1h returns of ``coin`` over the last ``days`` days (F4 candles), oldest first, or ``None`` when unknown."""

    def hourly_returns(self, coin: str, days: int) -> Sequence[Decimal] | None: ...


class ExchangeTime(Protocol):
    """The exchange-time clock (``ClockSync`` satisfies it). Raises ``ClockUnsyncedError`` while unsynced."""

    def exchange_now(self) -> Timestamp: ...


class EntryCalendar(Protocol):
    """Economic-calendar blackout port (F8, NOT built in v0)."""

    def blocks_entries(self, now_ms: int) -> str | None:
        """A reason when entries are blocked at ``now_ms`` (exchange time), else ``None``."""
        ...


class AlwaysAllowCalendar:
    """The v0 calendar: F8 is on hold, so no entry is ever blocked."""

    def blocks_entries(self, now_ms: int) -> str | None:
        raise NotImplementedError
