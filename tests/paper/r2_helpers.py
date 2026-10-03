"""Round-2 helpers for the F11 tests: failing external boundaries around the REAL broker, gate authority and F2
ledger. The wrappers only inject faults at true boundaries (alert sink, book/meta/funding ports, disk); they never
stand in for the unit under test.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from copytrade.core.events import Alert
from copytrade.hl.models import L2Book
from copytrade.ledger.records import FillRecord, LedgerRecord, TradeRecord
from copytrade.ledger.store import Ledger
from copytrade.paper.broker import PaperBroker
from copytrade.paper.gate import GateAuthority
from copytrade.paper.types import CoinMeta, FundingSnapshot
from tests.paper.helpers import (
    KEY,
    Env,
    FakeAlerts,
    FakeBooks,
    FakeClock,
    FakeFunding,
    FakeMeta,
    make_config,
)


class FlakyAlerts(FakeAlerts):
    """An alert sink that raises ``error`` while it is set (the Telegram adapter is an external boundary)."""

    def __init__(self) -> None:
        super().__init__()
        self.error: Exception | None = None
        self.attempts = 0

    def send(self, alert: Alert) -> None:
        self.attempts += 1
        if self.error is not None:
            raise self.error
        super().send(alert)


class FlakyBooks(FakeBooks):
    """A book port that raises ``error`` while it is set (a corrupt or truncated recording, a decoder error)."""

    def __init__(self) -> None:
        super().__init__()
        self.error: Exception | None = None

    def first_book_at_or_after(self, coin: str, time_ms: int) -> L2Book | None:
        if self.error is not None:
            raise self.error
        return super().first_book_at_or_after(coin, time_ms)


class FlakyMeta(FakeMeta):
    """A meta port that raises ``error`` while it is set."""

    def __init__(self) -> None:
        super().__init__()
        self.error: Exception | None = None

    def fetch(self) -> Mapping[str, CoinMeta]:
        if self.error is not None:
            raise self.error
        return super().fetch()


class FlakyFunding(FakeFunding):
    """A funding port that raises ``error`` while it is set, and can answer with a scripted (wrong) snapshot."""

    def __init__(self) -> None:
        super().__init__()
        self.error: Exception | None = None
        self.override: FundingSnapshot | None = None

    def funding_at(self, coin: str, hour_ms: int) -> FundingSnapshot | None:
        if self.error is not None:
            raise self.error
        if self.override is not None:
            return self.override
        return super().funding_at(coin, hour_ms)


class LiveBooks(FakeBooks):
    """A live book port: a snapshot exists only once ``horizon`` (the driver's current time) has reached it, so a
    question about a moment that has not happened yet is answered ``None`` (not with a snapshot from the future)."""

    def __init__(self) -> None:
        super().__init__()
        self.horizon = 0

    def first_book_at_or_after(self, coin: str, time_ms: int) -> L2Book | None:
        for book in self.by_coin.get(coin, []):
            if time_ms <= book.time_ms <= self.horizon:
                return book
        return None


class StuckBooks(FakeBooks):
    """A buggy port that answers every question with one fixed book, whatever coin and time were asked."""

    def __init__(self, book: L2Book) -> None:
        super().__init__()
        self.book = book

    def first_book_at_or_after(self, coin: str, time_ms: int) -> L2Book | None:
        return self.book


class FailingLedger:
    """The real F2 ledger with a disk that fails on the ``fail_at``-th write (1-based) with ``error``.

    Counts every write attempt (``append``, ``append_fill``, ``append_trade``); a failing attempt writes nothing."""

    def __init__(self, inner: Ledger, fail_at: int | None, error: Exception) -> None:
        self._inner = inner
        self._fail_at = fail_at
        self._error = error
        self.attempts = 0

    def _gate(self) -> None:
        self.attempts += 1
        if self._fail_at is not None and self.attempts == self._fail_at:
            raise self._error

    def append(self, kind: str, payload: Mapping[str, Any], *, client_order_id: str | None = None) -> LedgerRecord:
        self._gate()
        return self._inner.append(kind, payload, client_order_id=client_order_id)

    def append_fill(self, fill: FillRecord) -> LedgerRecord:
        self._gate()
        return self._inner.append_fill(fill)

    def append_trade(self, trade: TradeRecord) -> LedgerRecord:
        self._gate()
        return self._inner.append_trade(trade)

    def has_client_order_id(self, client_order_id: str) -> bool:
        return self._inner.has_client_order_id(client_order_id)

    def close(self) -> None:
        self._inner.close()


@contextmanager
def custom_env(  # noqa: PLR0913 - one knob per boundary
    *,
    books: FakeBooks | None = None,
    meta: FakeMeta | None = None,
    funding: FakeFunding | None = None,
    alerts: FakeAlerts | None = None,
    fail_at: int | None = None,
    ledger_error: Exception | None = None,
) -> Iterator[Env]:
    """A throw-away environment whose boundaries can be replaced by faulty ones. ``fail_at`` (with
    ``ledger_error``) makes the ledger's disk fail on that write; ``env.ledger`` is then the ``FailingLedger``."""
    from copytrade.ledger.errors import LedgerWriteError  # noqa: PLC0415

    clock = FakeClock()
    with tempfile.TemporaryDirectory() as tmp:
        ledger_dir = Path(tmp) / "ledger"
        real = Ledger.open(ledger_dir, clock=clock)
        wrapped = FailingLedger(real, fail_at, ledger_error or LedgerWriteError("disk full"))
        fake_books = books if books is not None else FakeBooks()
        fake_meta = meta if meta is not None else FakeMeta()
        fake_funding = funding if funding is not None else FakeFunding()
        fake_alerts = alerts if alerts is not None else FakeAlerts()
        authority = GateAuthority(KEY)
        config = make_config()
        try:
            broker = PaperBroker(
                config=config,
                books=fake_books,
                meta=fake_meta,
                funding=fake_funding,
                ledger=cast("Ledger", wrapped),
                clock=clock,
                alerts=fake_alerts,
                authority=authority,
            )
            yield Env(
                broker,
                authority,
                fake_books,
                fake_meta,
                fake_funding,
                fake_alerts,
                clock,
                cast("Ledger", wrapped),
                ledger_dir,
                config,
            )
        finally:
            real.close()
