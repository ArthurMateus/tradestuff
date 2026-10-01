"""Helpers for the F10 tests. The REAL risk gate, paper broker, gate authority and F2 ledger are used; only true
boundaries (time, market data, meta) and the features that are not built yet (F12 share book and account view, F8
calendar) are faked. Nothing here re-implements the unit under test.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.config import Config
from copytrade.core.errors import ClockUnsyncedError
from copytrade.core.money import Price, Qty
from copytrade.ledger.records import LedgerRecord
from copytrade.paper.gate import GateAuthority
from copytrade.paper.types import GateToken, OrderIntent, StopIntent
from copytrade.risk.gate import RiskGate
from copytrade.risk.types import AddRequest, ExitRequest, OpenRequest, ShareExposure, StopRequest
from tests.paper.helpers import D0, KEY, Env, FakeAlerts, make_config

D = Decimal
T0 = D0 + 100_000  # exchange "now" of most tests: later than every seeded fill, inside the same UTC hour


class FakeAccount:
    """Mark-to-market equity (F12/F21, not built)."""

    def __init__(self, equity: str | None = "300") -> None:
        self.equity: Decimal | None = None if equity is None else D(equity)
        self.raises = False

    def equity_usd(self) -> Decimal | None:
        if self.raises:
            raise RuntimeError("equity source down")
        return self.equity


class FakeShares:
    """The open shares (F12, not built)."""

    def __init__(self) -> None:
        self.shares: list[ShareExposure] = []
        self.raises = False

    def open_shares(self) -> Sequence[ShareExposure]:
        if self.raises:
            raise RuntimeError("share book down")
        return tuple(self.shares)


class FakeReturns:
    """1h returns per coin (F4 candles)."""

    def __init__(self) -> None:
        self.series: dict[str, list[Decimal]] = {}
        self.calls: list[tuple[str, int]] = []

    def hourly_returns(self, coin: str, days: int) -> Sequence[Decimal] | None:
        self.calls.append((coin, days))
        return self.series.get(coin)


class FakeExchangeTime:
    """The exchange-time clock (ClockSync in production). ``now`` is exchange ms."""

    def __init__(self, now_ms: int) -> None:
        self.now = now_ms
        self.unsynced = False

    def exchange_now(self) -> Timestamp:
        if self.unsynced:
            raise ClockUnsyncedError("no clock-offset estimate exists yet")
        return Timestamp(ms=self.now, source=TimeSource.DERIVED)


class FakeCalendar:
    """A blackout calendar (F8 is not built): blocks entries with ``reason`` while set."""

    def __init__(self) -> None:
        self.reason: str | None = None

    def blocks_entries(self, now_ms: int) -> str | None:
        return self.reason


class SpyAuthority(GateAuthority):
    """The REAL authority that also records every ``issue`` (a recording subclass, not a replacement)."""

    def __init__(self, key: bytes) -> None:
        super().__init__(key)
        self.issued: list[tuple[OrderIntent | StopIntent, GateToken]] = []

    def issue(self, intent: OrderIntent | StopIntent) -> GateToken:
        token = super().issue(intent)
        self.issued.append((intent, token))
        return token


_PRICE_FIELDS = ("decision_px", "stop_px", "current_stop_px", "trigger_px")


def _priced(base: dict[str, Any]) -> dict[str, Any]:
    """Every price field as a ``Price`` and every quantity as a ``Qty``, whatever the test passed."""
    for key in _PRICE_FIELDS:
        if key in base:
            base[key] = Price(str(base[key]))
    for key in ("qty", "our_share_qty", "leader_add_size", "leader_pre_add_position"):
        if key in base:
            base[key] = Qty(str(base[key]))
    return base


def wide_returns(n: int = 24) -> list[Decimal]:
    """A BTC-like 1h return series (period 4, zero mean)."""
    return [D("0.01"), D("-0.01"), D("0.01"), D("-0.01")] * (n // 4)


def same_returns(n: int = 24) -> list[Decimal]:
    """Perfectly correlated with ``wide_returns`` (corr = 1)."""
    return [r * 2 for r in wide_returns(n)]


def opposite_returns(n: int = 24) -> list[Decimal]:
    """Perfectly anti-correlated with ``wide_returns`` (corr = -1)."""
    return [-r for r in wide_returns(n)]


def uncorrelated_returns(n: int = 24) -> list[Decimal]:
    """Exactly uncorrelated with ``wide_returns`` (corr = 0)."""
    return [D("0.01"), D("0.01"), D("-0.01"), D("-0.01")] * (n // 4)


@dataclass
class RiskEnv:
    paper: Env
    gate: RiskGate
    account: FakeAccount
    shares: FakeShares
    returns: FakeReturns
    xtime: FakeExchangeTime
    calendar: FakeCalendar
    authority: SpyAuthority
    state_dir: Path
    config: Config
    _seq: int = field(default=0)

    # -- time ---------------------------------------------------------------------------------------------
    def at(self, now_ms: int) -> None:
        """Move the exchange clock (and the local clock used for ledger stamps) to ``now_ms``."""
        self.xtime.now = now_ms
        self.paper.clock.now = now_ms

    # -- seeding open shares: a REAL broker position plus the matching F12 view ------------------------------
    def seed(  # noqa: PLR0913
        self,
        coin: str,
        *,
        leader: str = "LX",
        is_long: bool = True,
        qty: str = "1.0",
        entry: str = "100",
        stop: str = "98.5",
        leverage: int = 5,
        share: str | None = None,
        open_risk: str | None = None,
        on_broker: bool = True,
        mark: str | None = None,
    ) -> ShareExposure:
        self._seq += 1
        share_id = share or f"SEED{self._seq}"
        if on_broker:
            # seeded positions are opened in the past (before the exchange "now" of the test)
            local_now = self.paper.clock.now
            issued_before = len(self.authority.issued)
            decided = D0 + 2000 * self._seq  # the broker's time only moves forward
            self.paper.clock.now = decided
            self.paper.open_position(
                "buy" if is_long else "sell", qty, px=entry, coin=coin, leverage=leverage,
                coid=f"seed-{self._seq}", share=share_id, trade=f"TS{self._seq}", decided=decided,
            )
            self.paper.clock.now = local_now
            del self.authority.issued[issued_before:]  # the seed's own tokens are not the gate's
        risk = D(qty) * abs(D(entry) - D(stop)) if open_risk is None else D(open_risk)
        exposure = ShareExposure(
            share_id=share_id, trade_id=f"TS{self._seq}", coin=coin, leader=leader, is_long=is_long,
            qty=Qty(qty), entry_px=Price(entry), stop_px=Price(stop), mark_px=Price(mark or entry),
            open_risk_usd=risk,
        )
        self.shares.shares.append(exposure)
        return exposure

    def seed_risk_only(self, coin: str, *, leader: str, risk: str, is_long: bool = True, qty: str = "1.0") -> None:
        """An open share that only exists in the share book (used to fill a cap without a broker position)."""
        self.seed(coin, leader=leader, is_long=is_long, qty=qty, open_risk=risk, on_broker=False)

    # -- request builders ---------------------------------------------------------------------------------
    def open_req(self, **kw: Any) -> OpenRequest:
        base: dict[str, Any] = dict(
            run_id="run1", signal_id="sig1", leader="L1", coin="SOL", is_long=True, tids=(101,), trade_id="T10",
            share_id="S10", decision_px=Price("100"), stop_px=Price("98.5"), vol_mult=D(1),
            leader_position_notional_usd=D(500), leader_account_value_usd=D(1000),
            leader_av_time_ms=self.xtime.now - 1000,
        )
        base.update(kw)
        return OpenRequest(**_priced(base))

    def add_req(self, **kw: Any) -> AddRequest:
        base: dict[str, Any] = dict(
            run_id="run1", signal_id="sig2", leader="L1", coin="SOL", is_long=True, tids=(102,), trade_id="T10",
            share_id="S10", decision_px=Price("100"), stop_px=Price("98.5"), current_stop_px=Price("98.5"),
            our_share_qty=Qty("1.0"), leader_add_size=Qty("0.5"), leader_pre_add_position=Qty("1.0"),
        )
        base.update(kw)
        return AddRequest(**_priced(base))

    def exit_req(self, **kw: Any) -> ExitRequest:
        base: dict[str, Any] = dict(
            run_id="run1", signal_id="sig3", leader="L1", coin="SOL", is_long=True, tids=(103,), trade_id="T10",
            share_id="S10", qty=Qty("1.0"), close=True, decision_px=Price("100"), reason="leader_close",
        )
        base.update(kw)
        return ExitRequest(**_priced(base))

    def stop_req(self, **kw: Any) -> StopRequest:
        base: dict[str, Any] = dict(
            run_id="run1", signal_id="sig4", leader="L1", coin="SOL", kind="sl", is_long=True, qty=Qty("1.0"),
            trigger_px=Price("98.5"), trade_id="T10", share_id="S10",
        )
        base.update(kw)
        return StopRequest(**_priced(base))

    # -- books and time for the fills ------------------------------------------------------------------------
    def book(self, coin: str, px: str, *, at: int | None = None) -> None:
        self.paper.flat_book(coin, (self.xtime.now if at is None else at) + 1000, px)

    def fill(self) -> None:
        """Advance the broker to the ack time of anything sent at the current exchange time."""
        self.paper.advance(self.xtime.now + 1000)

    # -- ledger reads ----------------------------------------------------------------------------------------
    def decisions(self) -> list[LedgerRecord]:
        return self.paper.records("risk_decision")

    def last_decision_payload(self) -> dict[str, Any]:
        return dict(self.decisions()[-1].payload)


def build_risk_env(
    tmp_path: Path,
    *,
    equity: str | None = "300",
    key: bytes = KEY,
    config: Config | None = None,
    returns: dict[str, list[Decimal]] | None = None,
    marked: bool = True,
    **overrides: Any,
) -> RiskEnv:
    """Build the real gate over the real broker. ``marked=True`` also takes one equity mark at ``T0`` (F10 review B4:
    an entry needs a fresh mark); the default is True so every entry test starts with a fresh mark."""
    authority = SpyAuthority(key)
    cfg = config if config is not None else make_config(**overrides)
    # the broker must be built with the SAME authority object the gate holds
    paper = _rebuild_with_authority(tmp_path, cfg, authority)
    account, shares, rets = FakeAccount(equity), FakeShares(), FakeReturns()
    if returns:
        rets.series.update(returns)
    xtime, calendar = FakeExchangeTime(T0), FakeCalendar()
    paper.clock.now = T0
    state_dir = tmp_path / "risk_state"
    state_dir.mkdir()
    gate = RiskGate(
        config=cfg, broker=paper.broker, meta=paper.meta, account=account, shares=shares, returns=rets,
        exchange_time=xtime, calendar=calendar, ledger=paper.ledger, alerts=paper.alerts, authority=authority,
        state_dir=state_dir,
    )
    if marked:
        gate.mark_equity(T0)
    return RiskEnv(paper, gate, account, shares, rets, xtime, calendar, authority, state_dir, cfg)


def _rebuild_with_authority(tmp_path: Path, cfg: Config, authority: SpyAuthority) -> Env:
    """A paper Env whose broker uses ``authority`` (``build_env`` constructs its own)."""
    from copytrade.ledger.store import Ledger
    from copytrade.paper.broker import PaperBroker
    from tests.paper.helpers import FakeBooks, FakeClock, FakeFunding, FakeMeta

    clock = FakeClock()
    ledger_dir = tmp_path / "ledger2"
    books, funding, alerts, meta = FakeBooks(), FakeFunding(), FakeAlerts(), FakeMeta()
    ledger = Ledger.open(ledger_dir, clock=clock)
    broker = PaperBroker(
        config=cfg, books=books, meta=meta, funding=funding, ledger=ledger, clock=clock, alerts=alerts,
        authority=authority,
    )
    return Env(broker, authority, books, meta, funding, alerts, clock, ledger, ledger_dir, cfg)


def rebuild_gate(renv: RiskEnv, *, marked: bool = True) -> RiskEnv:
    """Simulate a process restart of the risk gate: a NEW gate and broker over the same ledger, state dir and books."""
    from copytrade.ledger.store import Ledger
    from copytrade.paper.broker import PaperBroker

    renv.paper.ledger.close()
    ledger = Ledger.open(renv.paper.ledger_dir, clock=renv.paper.clock)
    authority = SpyAuthority(KEY)
    broker = PaperBroker(
        config=renv.config, books=renv.paper.books, meta=renv.paper.meta, funding=renv.paper.funding, ledger=ledger,
        clock=renv.paper.clock, alerts=renv.paper.alerts, authority=authority,
    )
    paper = replace(renv.paper, broker=broker, authority=authority, ledger=ledger)
    gate = RiskGate(
        config=renv.config, broker=broker, meta=paper.meta, account=renv.account, shares=renv.shares,
        returns=renv.returns, exchange_time=renv.xtime, calendar=renv.calendar, ledger=ledger,
        alerts=paper.alerts, authority=authority, state_dir=renv.state_dir,
    )
    if marked:
        gate.mark_equity(renv.xtime.now)  # a restarted gate has no mark yet (B4): the supervisor marks at once
    return replace(renv, paper=paper, gate=gate, authority=authority)

