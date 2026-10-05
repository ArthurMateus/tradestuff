"""External boundaries of the paper broker (F11). Tests inject fakes; F21 wires real adapters over F3 and F4.

F11 owns these ports so it depends on no unmerged code. Only Protocols live here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from copytrade.hl.models import L2Book
from copytrade.paper.types import CoinMeta, FundingSnapshot


class BookSource(Protocol):
    """Recorded or live L2 books. May return books from the future (replay); the broker never uses one whose
    ``time_ms`` is after its current time (D1, no lookahead)."""

    def first_book_at_or_after(self, coin: str, time_ms: int) -> L2Book | None:
        """The earliest snapshot of ``coin`` with ``time_ms >= time_ms``, or ``None`` when there is none (yet)."""
        ...


class MetaSource(Protocol):
    """The exchange ``meta`` (tick, lot and max leverage per coin). May raise ``OSError``."""

    def fetch(self) -> Mapping[str, CoinMeta]: ...


class FundingSource(Protocol):
    """Actual hourly funding. May raise ``OSError``."""

    def funding_at(self, coin: str, hour_ms: int) -> FundingSnapshot | None:
        """The rate and oracle price for the funding hour starting at ``hour_ms``, or ``None`` if not known."""
        ...
