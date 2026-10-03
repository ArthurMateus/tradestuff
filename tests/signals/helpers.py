"""Test doubles and builders for the F7 tests. Only external boundaries are faked: the local clock, the clock-offset
source, the alert sink and the downstream signal consumer. The real F1 config loader and clock sync, the real F2
ledger and the real F7 detector run in every test.

Nothing here re-implements the unit under test. Nothing sleeps.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.clock import ClockSync, OffsetEstimate
from copytrade.core.money import Notional, Price, Qty
from copytrade.hl.models import ClearinghouseState, Fill, LeaderPosition
from copytrade.ledger.store import Ledger
from copytrade.signals.detector import SignalDetector
from copytrade.signals.models import Signal
from tests.hl.support import T0, WALLET_A, WALLET_B, FakeClock, RecordingAlerts, make_config

__all__ = ["T0", "WALLET_A", "WALLET_B", "FakeClock", "RecordingAlerts", "make_config"]

SECOND = 1_000


class FakeOffsetSource:
    """The clock-offset source (an external boundary): exchange time minus local time, with an uncertainty."""

    def __init__(self, offset_ms: int = 0, uncertainty_ms: int = 20) -> None:
        self.offset_ms = offset_ms
        self.uncertainty_ms = uncertainty_ms
        self.fail = False

    def estimate(self) -> OffsetEstimate:
        if self.fail:
            raise OSError("no offset source")
        return OffsetEstimate(offset_ms=self.offset_ms, uncertainty_ms=self.uncertainty_ms)


def natural_dir(start: str, side: str, sz: str) -> str:
    """The ``dir`` text Hyperliquid would give this fill (used only to build realistic fills)."""
    pre = Decimal(start)
    post = pre + (Decimal(sz) if side == "B" else -Decimal(sz))
    if pre == 0:
        return "Open Long" if post > 0 else "Open Short"
    if (pre > 0) != (post > 0) and post != 0:
        return "Long > Short" if pre > 0 else "Short > Long"
    if abs(post) > abs(pre):
        return "Open Long" if pre > 0 else "Open Short"
    return "Close Long" if pre > 0 else "Close Short"


def mkfill(
    tid: int,
    *,
    coin: str = "BTC",
    side: str = "B",
    sz: str = "1",
    start: str = "0",
    time_ms: int | None = None,
    dir: str | None = None,
    px: str = "100",
) -> Fill:
    return Fill(
        coin=coin,
        px=Price(px),
        sz=Qty(sz),
        side=side,
        time_ms=T0 if time_ms is None else time_ms,
        start_position=Qty(start),
        dir=natural_dir(start, side, sz) if dir is None else dir,
        closed_pnl=Qty("0"),
        fee=Qty("0.01"),
        crossed=True,
        oid=tid + 1_000_000,
        tid=tid,
        hash="0x" + f"{tid:064x}",
    )


def state(held: dict[str, str] | None = None, *, time_ms: int = T0) -> ClearinghouseState:
    """A ``clearinghouseState`` with the given signed positions (coin -> szi)."""
    positions = tuple(
        LeaderPosition(coin=c, szi=Qty(v), entry_px=Price("100") if Decimal(v) != 0 else None)
        for c, v in (held or {}).items()
    )
    return ClearinghouseState(account_value=Notional("100000"), positions=positions, time_ms=time_ms)


@dataclass
class RecordingSignals:
    """The downstream consumer. Notes, at delivery time, how many signal records the ledger already held."""

    ledger: Ledger
    batches: list[tuple[Signal, ...]] = field(default_factory=list)
    ledgered_at_delivery: list[int] = field(default_factory=list)

    def on_signals(self, signals: Sequence[Signal]) -> None:
        self.batches.append(tuple(signals))
        self.ledgered_at_delivery.append(sum(1 for r in self.ledger.records() if r.kind == "signal"))

    @property
    def signals(self) -> list[Signal]:
        return [s for b in self.batches for s in b]


@dataclass
class Rig:
    cfg: Any
    clock: FakeClock
    offset: FakeOffsetSource
    sync: ClockSync
    ledger: Ledger
    sink: RecordingSignals
    alerts: RecordingAlerts
    detector: SignalDetector
    directory: Path

    def ledger_signals(self) -> list[dict[str, Any]]:
        return [dict(r.payload) for r in self.ledger.records() if r.kind == "signal"]

    def feed(self, fills: Sequence[Fill], wallet: str = WALLET_A) -> list[Signal]:
        before = len(self.sink.signals)
        self.detector.on_fills(wallet, fills)
        return self.sink.signals[before:]


def make_rig(
    directory: Path,
    *,
    offset_ms: int = 0,
    uncertainty_ms: int = 20,
    follow: Sequence[str] = (WALLET_A,),
    held: dict[str, str] | None = None,
    clock: FakeClock | None = None,
    synced: bool = True,
    **overrides: Any,
) -> Rig:
    config = make_config(**overrides)
    clk = clock or FakeClock(T0)
    offset = FakeOffsetSource(offset_ms, uncertainty_ms)
    alerts = RecordingAlerts()
    sync = ClockSync.from_config(config, clock=clk, source=offset, alerts=alerts)
    if synced:
        sync.tick()
    ledger = Ledger.open(directory / "ledger", clock=clk)
    sink = RecordingSignals(ledger)
    detector = SignalDetector(config=config, clock=clk, sync=sync, ledger=ledger, sink=sink, alerts=alerts)
    for w in follow:
        detector.begin_follow(w, state(held), T0)
    return Rig(config, clk, offset, sync, ledger, sink, alerts, detector, directory)
