"""Helpers for the F11 tests: fake external boundaries (books, meta, funding, alerts, clock) and an environment
builder around the REAL broker, gate authority and F2 ledger. Nothing here re-implements the unit under test.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.config import Config
from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert
from copytrade.core.money import Price, Qty
from copytrade.hl.models import BookLevel, L2Book
from copytrade.ledger.records import (
    KIND_FILL,
    KIND_TRADE,
    FillRecord,
    LedgerRecord,
    TradeRecord,
    decode_fill,
    decode_trade,
)
from copytrade.ledger.store import Ledger, read_records
from copytrade.paper.broker import PaperBroker
from copytrade.paper.gate import GateAuthority
from copytrade.paper.types import (
    BrokerEvent,
    CoinMeta,
    FundingSnapshot,
    GateToken,
    MarkUpdate,
    OrderIntent,
    StopIntent,
    SubmitResult,
)
from tests.core.helpers import fixture_leaves

HOUR_MS = 3_600_000
BASE = 1_789_999_200_000  # an exact UTC hour boundary (497222 h since the epoch)
D0 = BASE + 600_000  # 10 minutes into that hour: no boundary is crossed by the short tests
FEE_RATE = Decimal("0.00045")  # 4.5 bps

D = Decimal
NewEnv = Callable[..., "Env"]
KEY = b"f11-test-authority-key-0123456789"

DEFAULT_META = {
    "BTC": CoinMeta(sz_decimals=5, max_leverage=40),
    "ETH": CoinMeta(sz_decimals=4, max_leverage=25),
    "SOL": CoinMeta(sz_decimals=2, max_leverage=20),
    "DOGE": CoinMeta(sz_decimals=0, max_leverage=10),
}


class FakeClock:
    """The local clock (an external boundary)."""

    def __init__(self, now_ms: int = D0) -> None:
        self.now = now_ms

    def now_ms(self) -> int:
        return self.now


class FakeBooks:
    """Recorded books. Serves the earliest snapshot at or after a time, even one from the future (replay)."""

    def __init__(self) -> None:
        self.by_coin: dict[str, list[L2Book]] = {}

    def add(self, book: L2Book) -> None:
        books = self.by_coin.setdefault(book.coin, [])
        books.append(book)
        books.sort(key=lambda b: b.time_ms)

    def first_book_at_or_after(self, coin: str, time_ms: int) -> L2Book | None:
        for b in self.by_coin.get(coin, []):
            if b.time_ms >= time_ms:
                return b
        return None


class FakeMeta:
    def __init__(self, meta: Mapping[str, CoinMeta] | None = None) -> None:
        self.meta = dict(DEFAULT_META if meta is None else meta)
        self.fetches = 0
        self.fail = False

    def fetch(self) -> Mapping[str, CoinMeta]:
        self.fetches += 1
        if self.fail:
            raise OSError("meta endpoint down")
        return dict(self.meta)


class FakeFunding:
    def __init__(self) -> None:
        self.points: dict[tuple[str, int], FundingSnapshot] = {}

    def set(self, coin: str, hour_ms: int, rate: str, oracle_px: str) -> None:
        self.points[(coin, hour_ms)] = FundingSnapshot(coin, hour_ms, D(rate), Price(oracle_px))

    def funding_at(self, coin: str, hour_ms: int) -> FundingSnapshot | None:
        return self.points.get((coin, hour_ms))


class FakeAlerts:
    def __init__(self) -> None:
        self.sent: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.sent.append(alert)

    def kinds(self) -> list[str]:
        return [a.kind for a in self.sent]


def lvl(px: str, sz: str) -> BookLevel:
    return BookLevel(px=Price(px), sz=Qty(sz), n=1)


def make_book(coin: str, time_ms: int, bids: Sequence[tuple[str, str]], asks: Sequence[tuple[str, str]]) -> L2Book:
    return L2Book(
        coin=coin,
        time_ms=time_ms,
        bids=tuple(lvl(p, s) for p, s in bids),
        asks=tuple(lvl(p, s) for p, s in asks),
    )


def make_config(**overrides: Any) -> Config:
    """The valid fixture config as one Config (dotted keys), with ``overrides`` (dots written as ``__``)."""
    data = dict(fixture_leaves())
    for key, value in overrides.items():
        data[key.replace("__", ".")] = value
    return Config(data)


@dataclass
class Env:
    broker: PaperBroker
    authority: GateAuthority
    books: FakeBooks
    meta: FakeMeta
    funding: FakeFunding
    alerts: FakeAlerts
    clock: FakeClock
    ledger: Ledger
    ledger_dir: Path
    config: Config
    events: list[BrokerEvent] = field(default_factory=list)

    # -- driving time ------------------------------------------------------------------------------
    def advance(self, now_ms: int) -> list[BrokerEvent]:
        self.clock.now = now_ms
        out = list(self.broker.advance_to(now_ms))
        self.events += out
        return out

    def mark(self, coin: str, px: str, time_ms: int) -> list[BrokerEvent]:
        self.clock.now = max(self.clock.now, time_ms)
        # the supervisor advances broker time from the F1 clock every loop (Amendment 10), so a mark is
        # always delivered in the broker's own time base
        self.events += list(self.broker.advance_to(self.clock.now))
        out = list(self.broker.on_mark(MarkUpdate(coin, Price(px), time_ms)))
        self.events += out
        return out

    # -- orders --------------------------------------------------------------------------------------
    def order(  # noqa: PLR0913
        self,
        side: str,
        qty: str,
        *,
        coid: str = "c1",
        coin: str = "SOL",
        action: ActionKind | None = None,
        decided: int = D0,
        px: str = "100",
        share: str = "S1",
        trade: str = "T1",
        leverage: int | None = None,
        reason: str | None = None,
    ) -> OrderIntent:
        entry = action in (None, ActionKind.OPEN, ActionKind.ADD)
        act = action if action is not None else ActionKind.OPEN
        return OrderIntent(
            client_order_id=coid,
            coin=coin,
            side=side,
            qty=Qty(qty),
            action=act,
            decided_at_ms=decided,
            decision_px=Price(px),
            trade_id=trade,
            share_id=share,
            leverage=(5 if leverage is None else leverage) if entry else None,
            exit_reason=None if entry else (reason or "manual"),
        )

    def token(self, intent: OrderIntent | StopIntent) -> GateToken:
        return self.authority.issue(intent)

    def submit(self, intent: OrderIntent) -> SubmitResult:
        return self.broker.submit(intent, self.token(intent))

    def stop(
        self,
        kind: str,
        side: str,
        qty: str,
        trigger: str,
        *,
        coid: str = "stop1",
        coin: str = "SOL",
        share: str = "S1",
        trade: str = "T1",
    ) -> SubmitResult:
        intent = StopIntent(
            client_order_id=coid,
            coin=coin,
            kind=kind,
            side=side,
            qty=Qty(qty),
            trigger_px=Price(trigger),
            trade_id=trade,
            share_id=share,
        )
        return self.broker.place_stop(intent, self.token(intent))

    def book(self, coin: str, t: int, bids: Sequence[tuple[str, str]], asks: Sequence[tuple[str, str]]) -> None:
        self.books.add(make_book(coin, t, bids, asks))

    def flat_book(self, coin: str, t: int, px: str, depth: str = "1000") -> None:
        self.books.add(make_book(coin, t, [(px, depth)], [(px, depth)]))

    def open_position(
        self,
        side: str = "buy",
        qty: str = "1.0",
        *,
        px: str = "100",
        coin: str = "SOL",
        leverage: int = 5,
        decided: int = D0,
        coid: str = "open1",
        share: str = "S1",
        trade: str = "T1",
        action: ActionKind = ActionKind.OPEN,
    ) -> list[BrokerEvent]:
        """Open (or add) at exactly ``px`` through a zero-spread book at decided + 1000 and return the fill events."""
        self.flat_book(coin, decided + 1000, px)
        # Amendment 11: broker time is only what advance_to says, and an entry decided more than the tolerance
        # ahead of it is refused (bad_decision_time): the supervisor has advanced to the decision time by now
        self.events += list(self.broker.advance_to(max(decided, self.clock.now)))
        result = self.submit(
            self.order(
                side, qty, coid=coid, coin=coin, decided=decided, px=px, share=share, trade=trade,
                leverage=leverage, action=action,
            )
        )
        assert result.accepted, result
        return self.advance(decided + 1000)

    # -- ledger reads --------------------------------------------------------------------------------
    def records(self, kind: str | None = None) -> list[LedgerRecord]:
        return [r for r in read_records(self.ledger_dir) if kind is None or r.kind == kind]

    def fills(self) -> list[FillRecord]:
        return [decode_fill(r) for r in self.records(KIND_FILL)]

    def trades(self) -> list[TradeRecord]:
        return [decode_trade(r) for r in self.records(KIND_TRADE)]


def build_env(tmp_path: Path, *, config: Config | None = None, key: bytes = KEY, meta: FakeMeta | None = None) -> Env:
    clock = FakeClock()
    ledger_dir = tmp_path / "ledger"
    books, funding, alerts = FakeBooks(), FakeFunding(), FakeAlerts()
    fake_meta = meta if meta is not None else FakeMeta()
    authority = GateAuthority(key)
    ledger = Ledger.open(ledger_dir, clock=clock)
    cfg = config if config is not None else make_config()
    try:
        broker = PaperBroker(
            config=cfg, books=books, meta=fake_meta, funding=funding, ledger=ledger, clock=clock, alerts=alerts,
            authority=authority,
        )
    except BaseException:
        ledger.close()
        raise
    return Env(broker, authority, books, fake_meta, funding, alerts, clock, ledger, ledger_dir, cfg)


def restart(env: Env) -> Env:
    """Simulate a process restart: close the ledger, reopen it, build a NEW broker over the same recorded books,
    meta, funding and authority key. (Full state reconstruction is F13's job, not F11's.)"""
    env.ledger.close()
    ledger = Ledger.open(env.ledger_dir, clock=env.clock)
    authority = GateAuthority(KEY)
    broker = PaperBroker(
        config=env.config, books=env.books, meta=env.meta, funding=env.funding, ledger=ledger, clock=env.clock,
        alerts=env.alerts, authority=authority,
    )
    return Env(broker, authority, env.books, env.meta, env.funding, env.alerts, env.clock, ledger, env.ledger_dir,
               env.config)


@contextmanager
def fresh_env(**kwargs: Any) -> Iterator[Env]:
    """A throw-away environment for Hypothesis tests (a function-scoped fixture cannot be used with @given)."""
    with tempfile.TemporaryDirectory() as tmp:
        built = build_env(Path(tmp), **kwargs)
        try:
            yield built
        finally:
            built.ledger.close()
