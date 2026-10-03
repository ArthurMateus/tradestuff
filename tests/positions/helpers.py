"""Helpers for the F12 tests. The REAL risk gate, paper broker, gate authority, F2 ledger and F12 position manager run
in every test. Only true boundaries are faked: the exchange-time clock, equity source, candle reader, the leader's
exchange state and fills, the entry policy (F9, not built) and the alert sink. Nothing re-implements the unit under
test, and the F12 modules are imported inside the factory so a missing module fails the test itself.
"""

from __future__ import annotations

import importlib
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.domain import ActionKind
from copytrade.core.money import Notional, Price, Qty
from copytrade.hl.models import Candle, ClearinghouseState, Fill, LeaderPosition
from copytrade.paper.types import MarkUpdate, PositionView
from copytrade.risk.gate import RiskGate
from copytrade.signals.detector import signal_id
from copytrade.signals.models import Signal
from tests.paper.helpers import BASE, D0, HOUR_MS, KEY, Env, make_config
from tests.risk.helpers import (
    T0,
    FakeAccount,
    FakeExchangeTime,
    FakeCalendar,
    FakeReturns,
    SpyAuthority,
    _rebuild_with_authority,
)

D = Decimal
WALLET_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
WALLET_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
SEC = 1_000
MIN = 60_000
ATR = D("0.75")  # the constant true range of the default candles: stop distance = 2 x 0.75 = 1.5


def pos(name: str) -> Any:
    """``copytrade.positions.<name>``, imported inside the test so a missing module fails that test."""
    return importlib.import_module(f"copytrade.positions.{name}")


class FakeCandles:
    """The F4 candle reader (``CandleStore.get`` signature). Serves bars with ``open_ms >= start_ms`` and
    ``close_ms <= end_ms`` only, so a bar still forming is never returned."""

    def __init__(self) -> None:
        self.bars: dict[tuple[str, str], list[Candle]] = {}
        self.fail = False
        self.calls: list[tuple[str, str, int, int]] = []

    def set_flat(self, coin: str, *, n: int = 20, tr: Decimal = ATR, interval: str = "1h", last_close_ms: int = BASE) -> None:
        """``n`` closed bars ending at ``last_close_ms``, each with true range ``tr`` around 100."""
        bars = []
        for i in range(n):
            close_ms = last_close_ms - (n - 1 - i) * HOUR_MS
            bars.append(
                Candle(
                    open_ms=close_ms - HOUR_MS, close_ms=close_ms, coin=coin, interval=interval,
                    open=Price("100"), high=Price(str(D(100) + tr / 2)), low=Price(str(D(100) - tr / 2)),
                    close=Price("100"), volume=Qty("10"), trades=10,
                )
            )
        self.bars[(coin, interval)] = bars

    def add_bar(self, bar: Candle) -> None:
        self.bars.setdefault((bar.coin, bar.interval), []).append(bar)

    def get(self, coin: str, interval: str, start_ms: int, end_ms: int) -> tuple[Candle, ...]:
        self.calls.append((coin, interval, start_ms, end_ms))
        if self.fail:
            raise OSError("candle store down")
        return tuple(b for b in self.bars.get((coin, interval), []) if b.open_ms >= start_ms and b.close_ms <= end_ms)


class FakeLeaderState:
    """The leader's ``clearinghouseState`` (an exchange boundary). ``positions`` maps wallet -> coin -> signed szi."""

    def __init__(self, xtime: FakeExchangeTime) -> None:
        self._xtime = xtime
        self.account_value = D("1000")
        self.positions: dict[str, dict[str, str]] = {}
        self.fail = False
        self.calls = 0

    def clearinghouse_state(self, wallet: str) -> ClearinghouseState:
        self.calls += 1
        if self.fail:
            raise OSError("info endpoint down")
        held = self.positions.get(wallet, {})
        return ClearinghouseState(
            account_value=Notional(str(self.account_value)),
            positions=tuple(
                LeaderPosition(coin=c, szi=Qty(v), entry_px=Price("100") if D(v) != 0 else None)
                for c, v in held.items()
            ),
            time_ms=self._xtime.now,
        )


class FakeLeaderFills:
    """``userFillsByTime`` (an exchange boundary): returns the stored fills inside ``[start_ms, end_ms]``."""

    def __init__(self) -> None:
        self.fills: dict[str, list[Fill]] = {}
        self.fail = False
        self.calls: list[tuple[str, int, int]] = []

    def user_fills_by_time(self, wallet: str, start_ms: int, end_ms: int) -> Sequence[Fill]:
        self.calls.append((wallet, start_ms, end_ms))
        if self.fail:
            raise OSError("info endpoint down")
        return tuple(f for f in self.fills.get(wallet, []) if start_ms <= f.time_ms <= end_ms)


class FakePolicy:
    """The entry policy (F9 is not built): ``vol_mult(signal)`` or ``None`` to veto the open."""

    def __init__(self) -> None:
        self.mult: Decimal | None = D(1)
        self.fail = False

    def vol_mult(self, signal: Signal) -> Decimal | None:  # noqa: ARG002
        if self.fail:
            raise RuntimeError("policy down")
        return self.mult


def make_signal(  # noqa: PLR0913
    tid: int,
    action: ActionKind,
    *,
    wallet: str = WALLET_A,
    coin: str = "SOL",
    is_long: bool = True,
    size: str = "5",
    pre: str | None = None,
    post: str | None = None,
    fraction: str | None = None,
    px: str = "100",
    ts: int = T0,
    leg: int = 0,
    from_flip: bool = False,
    outcome: str | None = None,
    flags: frozenset[str] = frozenset(),
) -> Signal:
    """A typed leader signal built like the F7 detector builds it (same ``signal_id``)."""
    qty = D(size)
    if action is ActionKind.OPEN:
        pre_q, post_q = D(pre or "0"), D(post or size)
    elif action is ActionKind.ADD:
        pre_q = D(pre or "5")
        post_q = D(post) if post is not None else pre_q + qty
    elif action is ActionKind.REDUCE:
        pre_q = D(pre or "5")
        post_q = D(post) if post is not None else pre_q - qty
    else:
        pre_q, post_q = D(pre or size), D(post or "0")
    return Signal(
        signal_id=signal_id(wallet, tid, leg), wallet=wallet, coin=coin, tid=tid, leg=leg, from_flip=from_flip,
        action=action, is_long=is_long, size=Qty(size), pre_position=Qty(str(pre_q)), post_position=Qty(str(post_q)),
        reduce_fraction=None if fraction is None else D(fraction), px=Price(px),
        exchange_ts=Timestamp(ts, TimeSource.EXCHANGE), receive_ts=Timestamp(ts + 50, TimeSource.LOCAL), age_ms=50,
        s2_ms=1, outcome=outcome, flags=flags,
    )


def make_fill(  # noqa: PLR0913
    tid: int, *, wallet_coin: str = "SOL", side: str = "A", sz: str = "1", start: str = "5", time_ms: int = T0,
    dir_: str = "Close Long", px: str = "100",
) -> Fill:
    """A leader fill as ``userFillsByTime`` returns it."""
    return Fill(
        coin=wallet_coin, px=Price(px), sz=Qty(sz), side=side, time_ms=time_ms, start_position=Qty(start), dir=dir_,
        closed_pnl=Qty("0"), fee=Qty("0.01"), crossed=True, oid=tid + 1_000_000, tid=tid, hash="0x" + f"{tid:064x}",
    )


@dataclass
class Rig:
    env: Env
    gate: RiskGate
    book: Any
    mgr: Any
    account: FakeAccount
    xtime: FakeExchangeTime
    candles: FakeCandles
    leader_state: FakeLeaderState
    leader_fills: FakeLeaderFills
    policy: FakePolicy
    authority: SpyAuthority
    config: Any

    # -- time --------------------------------------------------------------------------------------------
    def at(self, now_ms: int) -> None:
        """Move the exchange and local clocks to ``now_ms`` and take a fresh equity mark (B4)."""
        self.xtime.now = now_ms
        self.env.clock.now = now_ms
        self.gate.mark_equity(now_ms)

    def step(self, now_ms: int) -> list[Any]:
        """The supervisor loop: set the clocks, then ``advance_to`` through the manager."""
        self.at(now_ms)
        return list(self.mgr.advance_to(now_ms))

    def book_at(self, coin: str, px: str, at_ms: int) -> None:
        self.env.flat_book(coin, at_ms, px)

    def mark(self, coin: str, px: str) -> list[Any]:
        """A mark at the current exchange time, delivered like the supervisor does (advance first)."""
        self.mgr.advance_to(self.xtime.now)
        return list(self.mgr.on_mark(MarkUpdate(coin, Price(px), self.xtime.now)))

    def mark_and_fill(self, coin: str, mark_px: str, *, fill_px: str | None = None) -> None:
        """Mark, then let the triggered exit fill one ack delay later at ``fill_px`` (default: the mark)."""
        now = self.xtime.now
        self.book_at(coin, fill_px or mark_px, now + 1000)
        self.mark(coin, mark_px)
        self.step(now + 1000)

    # -- driving signals ----------------------------------------------------------------------------------
    def feed(self, *signals: Signal) -> None:
        self.mgr.on_signals(list(signals))

    def open_share(  # noqa: PLR0913
        self, tid: int = 1, *, wallet: str = WALLET_A, coin: str = "SOL", is_long: bool = True,
        notional: str = "500", fill_px: str = "100", ts: int | None = None,
    ) -> Any:
        """A leader OPEN, our entry and its fill one ack delay later. Returns the open ``ShareState``."""
        now = self.xtime.now
        self.book_at(coin, fill_px, now + 1000)
        size = str(D(notional) / D("100"))
        self.feed(make_signal(tid, ActionKind.OPEN, wallet=wallet, coin=coin, is_long=is_long, size=size,
                              ts=now - 100 if ts is None else ts))
        self.step(now + 1000)
        share = self.share_of(wallet, coin)
        assert share is not None, "the share did not open"
        return share

    def held(self, coin: str) -> PositionView:
        """The broker's merged position on ``coin`` (it must exist)."""
        position = self.env.broker.position(coin)
        assert position is not None, f"the broker holds no {coin}"
        return position

    def share_of(self, wallet: str, coin: str) -> Any:
        for state in self.book.states():
            if state.leader == wallet and state.coin == coin and state.status != "closed":
                return state
        return None

    # -- ledger reads ---------------------------------------------------------------------------------------
    def records(self, kind: str) -> list[dict[str, Any]]:
        return [dict(r.payload) | {"_coid": r.client_order_id, "_seq": r.seq} for r in self.env.records(kind)]

    def share_events(self, share_id: str | None = None) -> list[dict[str, Any]]:
        return [r for r in self.records("share_state") if share_id is None or r["share_id"] == share_id]

    def orders(self) -> list[dict[str, Any]]:
        return self.records("paper_order")

    def active_stops(self, share_id: str | None = None) -> list[dict[str, Any]]:
        """Registered stops that were neither cancelled nor triggered (from the ledger)."""
        gone = {r["client_order_id"] for r in self.records("paper_cancel") if r.get("target") == "stop"}
        gone |= {r["client_order_id"] for r in self.records("paper_stop_trigger")}
        return [
            r for r in self.records("paper_stop")
            if r["_coid"] not in gone and (share_id is None or r["share_id"] == share_id)
        ]

    def decisions(self) -> list[dict[str, Any]]:
        return self.records("risk_decision")

    def alert_kinds(self) -> list[str]:
        return self.env.alerts.kinds()


def _build(tmp_path: Path, **overrides: Any) -> Rig:
    equity = overrides.pop("equity", "300")
    authority = SpyAuthority(KEY)
    cfg = make_config(**overrides)
    env = _rebuild_with_authority(tmp_path, cfg, authority)
    env.clock.now = T0
    account, xtime = FakeAccount(equity), FakeExchangeTime(T0)
    candles, leader_fills, policy = FakeCandles(), FakeLeaderFills(), FakePolicy()
    leader_state = FakeLeaderState(xtime)
    for coin in ("SOL", "ETH", "BTC"):
        candles.set_flat(coin)
    state_dir = tmp_path / "risk_state"
    state_dir.mkdir()
    book = pos("book").PositionBook()
    gate = RiskGate(
        config=cfg, broker=env.broker, meta=env.meta, account=account, shares=book, returns=FakeReturns(),
        exchange_time=xtime, calendar=FakeCalendar(), ledger=env.ledger, alerts=env.alerts, authority=authority,
        state_dir=state_dir,
    )
    gate.mark_equity(T0)
    mgr = pos("manager").PositionManager(
        config=cfg, gate=gate, broker=env.broker, book=book, ledger=env.ledger, alerts=env.alerts,
        exchange_time=xtime, candles=candles, leader_state=leader_state, leader_fills=leader_fills, policy=policy,
        run_id="run1",
    )
    return Rig(env, gate, book, mgr, account, xtime, candles, leader_state, leader_fills, policy, authority, cfg)


def build_rig(tmp_path: Path, **overrides: Any) -> Rig:
    """The real gate, broker, ledger and manager over fakes for the true boundaries. Config overrides use ``__`` for
    dots (``exits__tp_enabled=False``); ``equity="300"`` sets the account equity."""
    return _build(tmp_path, **overrides)


@contextmanager
def fresh_rig(**overrides: Any) -> Iterator[Rig]:
    """A throw-away rig for Hypothesis tests (a function-scoped fixture cannot be used with ``@given``)."""
    with tempfile.TemporaryDirectory() as tmp:
        rig = _build(Path(tmp), **overrides)
        try:
            yield rig
        finally:
            rig.env.ledger.close()


__all__ = ["BASE", "D0", "T0", "WALLET_A", "WALLET_B", "Rig", "build_rig", "fresh_rig", "make_fill", "make_signal"]
