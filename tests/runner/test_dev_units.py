"""R0 developer tests: the small runner pieces that the end-to-end tests reach only indirectly. No sockets, no threads;
only true boundaries (clock, REST candles, the exchange manager call) are faked."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from copytrade.core.errors import ClockUnsyncedError
from copytrade.core.events import Alert
from copytrade.core.money import Price
from copytrade.hl.errors import HlBudgetError
from copytrade.hl.models import Candle
from copytrade.ledger.store import Ledger
from copytrade.paper.types import PendingEntry
from copytrade.risk.types import FlattenReport
from copytrade.runner.adapters import MarketHub
from copytrade.runner.flatten import ALERT_FLATTEN_INCOMPLETE, FLATTEN_RERUN_INTERVAL_S, FLATTEN_RERUN_MAX, FlattenSupervisor
from copytrade.runner.sources import MarkedAccount, PacedInputs, StoredReturns
from copytrade.runner.tail import LedgerTail
from copytrade.runner.timebase import GuardedExchangeTime, TimeBase
from tests.hl.support import T0, FakeClock
from tests.risk.helpers import FakeExchangeTime

D = Decimal
HOUR = 3_600_000


# ---------------------------------------------------------------------------------------- FlattenSupervisor


class FakeManager:
    def __init__(self, unfinished: int) -> None:
        self.unfinished = unfinished
        self.run_ids: list[str] = []

    def flatten(self, *, run_id: str) -> FlattenReport:
        self.run_ids.append(run_id)
        open_left = (("SOL", "s1", D("1")),) if len(self.run_ids) <= self.unfinished else ()
        return FlattenReport((), in_flight=(), still_open=open_left, pause_saved=True)


class Alerts:
    def __init__(self) -> None:
        self.sent: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.sent.append(alert)


def supervisor(unfinished: int) -> tuple[FlattenSupervisor, FakeManager, FakeClock, Alerts]:
    clock, manager, alerts = FakeClock(T0), FakeManager(unfinished), Alerts()
    return FlattenSupervisor(manager=manager, alerts=alerts, now_ms=clock.now_ms), manager, clock, alerts  # type: ignore[arg-type]


def test_every_flatten_call_gets_a_new_run_id_and_a_finished_report_is_not_rerun() -> None:
    sup, manager, clock, _ = supervisor(unfinished=0)
    sup.flatten(run_id="base")
    sup.flatten(run_id="base")  # the PO sends /flatten twice: a second run, never a duplicate id
    assert manager.run_ids == ["base:flatten:1", "base:flatten:2"] and sup.runs == tuple(manager.run_ids)
    clock.advance(10 * FLATTEN_RERUN_INTERVAL_S * 1000)
    sup.rerun_if_due()
    assert len(manager.run_ids) == 2


def test_an_unfinished_flatten_is_rerun_every_interval_with_new_ids_until_it_finishes() -> None:
    sup, manager, clock, alerts = supervisor(unfinished=3)
    sup.flatten(run_id="r")
    sup.rerun_if_due()
    assert len(manager.run_ids) == 1  # not due yet
    for expected in (2, 3, 4):
        clock.advance(FLATTEN_RERUN_INTERVAL_S * 1000)
        sup.rerun_if_due()
        assert len(manager.run_ids) == expected
    clock.advance(FLATTEN_RERUN_INTERVAL_S * 1000)
    sup.rerun_if_due()
    assert len(manager.run_ids) == 4 and len(set(manager.run_ids)) == 4 and alerts.sent == []  # the 4th finished


def test_a_flatten_that_never_finishes_stops_after_the_limit_with_one_alert() -> None:
    sup, manager, clock, alerts = supervisor(unfinished=10**6)
    sup.flatten(run_id="r")
    for _ in range(FLATTEN_RERUN_MAX + 5):
        clock.advance(FLATTEN_RERUN_INTERVAL_S * 1000)
        sup.rerun_if_due()
    assert len(manager.run_ids) == 1 + FLATTEN_RERUN_MAX
    assert [a.kind for a in alerts.sent] == [ALERT_FLATTEN_INCOMPLETE]
    sup.flatten(run_id="r")  # a new /flatten starts a fresh series
    assert len(manager.run_ids) == 2 + FLATTEN_RERUN_MAX


def test_in_flight_entries_alone_keep_the_flatten_open() -> None:
    clock, alerts = FakeClock(T0), Alerts()
    entry = PendingEntry("c", "SOL", "buy", ActionKind.OPEN, D("1"), Price("100"), 1, "s", "t", T0)  # type: ignore[arg-type]

    class Manager:
        calls = 0

        def flatten(self, *, run_id: str) -> FlattenReport:
            self.calls += 1
            return FlattenReport((), in_flight=(entry,) if self.calls == 1 else (), still_open=(), pause_saved=True)

    manager = Manager()
    sup = FlattenSupervisor(manager=manager, alerts=alerts, now_ms=clock.now_ms)  # type: ignore[arg-type]
    sup.flatten(run_id="r")
    clock.advance(FLATTEN_RERUN_INTERVAL_S * 1000)
    sup.rerun_if_due()
    assert manager.calls == 2


# ---------------------------------------------------------------------------------------------- LedgerTail


def test_the_tail_returns_only_the_records_appended_since_the_last_poll(tmp_path: Path) -> None:
    clock = FakeClock(T0)
    ledger = Ledger.open(tmp_path, clock=clock)
    ledger.append("a", {"n": 1})
    tail = LedgerTail(tmp_path)  # starts at the end of what exists
    assert tail.poll() == []
    ledger.append("b", {"n": 2})
    ledger.append("c", {"n": 3})
    assert [r.kind for r in tail.poll()] == ["b", "c"] and tail.poll() == []
    (tmp_path / "ledger.jsonl").open("ab").write(b'{"torn": ')  # a half-written line is left for later
    assert tail.poll() == []
    ledger.close()


def test_a_tail_over_a_missing_ledger_is_empty(tmp_path: Path) -> None:
    assert LedgerTail(tmp_path / "nowhere").poll() == []


# ----------------------------------------------------------------------------- the guarded exchange clock


def test_the_guarded_clock_follows_the_accepted_target_and_goes_dark_on_a_refused_sample() -> None:
    clock, xt = FakeClock(T0), FakeExchangeTime(T0 + 500)
    base = TimeBase(exchange_time=xt, clock=clock, max_offset_uncertainty_ms=100)
    guarded = GuardedExchangeTime(base)
    with pytest.raises(ClockUnsyncedError):
        guarded.exchange_now()  # nothing accepted yet
    assert base.next_target_ms() == (T0 + 500, None)
    clock.advance(250)
    assert guarded.exchange_now().ms == T0 + 750  # projected with local time between iterations
    xt.now += 3_600_000
    assert base.next_target_ms()[0] is None
    with pytest.raises(ClockUnsyncedError):
        guarded.exchange_now()  # a jump: no raw clock reaches the gate
    xt.now -= 3_600_000
    xt.unsynced = True
    base.next_target_ms()
    with pytest.raises(ClockUnsyncedError):
        guarded.exchange_now()


# ---------------------------------------------------------------------------------------------- StoredReturns


def candle(open_ms: int, close: str) -> Candle:
    px = Price(close)
    return Candle(open_ms, open_ms + HOUR - 1, "BTC", "1h", px, px, px, px, D("1"), 1)  # type: ignore[arg-type]


def test_returns_are_close_to_close_over_the_whole_window_oldest_first() -> None:
    clock = FakeClock(10 * HOUR * 24 + 1234)
    end = clock.now // HOUR * HOUR
    hours = 2 * 24
    closes = [100 + i for i in range(hours + 1)]
    calls: list[tuple[str, str, int, int]] = []

    def get(coin: str, interval: str, start: int, stop: int) -> list[Candle]:
        calls.append((coin, interval, start, stop))
        return [candle(start + i * HOUR, str(c)) for i, c in enumerate(closes)]

    series = StoredReturns(get=get, clock=clock).hourly_returns("BTC", 2)
    assert series is not None and len(series) == hours
    assert series[0] == D(101) / D(100) - 1 and series[-1] == D(148) / D(147) - 1
    assert calls == [("BTC", "1h", end - (hours + 1) * HOUR, end)]


def test_returns_are_unknown_when_an_hour_is_missing_or_the_store_fails() -> None:
    clock = FakeClock(10 * HOUR * 24)
    hours = 24
    start = clock.now - (hours + 1) * HOUR
    full = [candle(start + i * HOUR, "100") for i in range(hours + 1)]
    assert StoredReturns(get=lambda *a: full[:-1], clock=clock).hourly_returns("BTC", 1) is None
    assert StoredReturns(get=lambda *a: full[1:], clock=clock).hourly_returns("BTC", 1) is None

    def broken(*_a: Any) -> list[Candle]:
        raise OSError("candles unreachable")

    assert StoredReturns(get=broken, clock=clock).hourly_returns("BTC", 1) is None


# ---------------------------------------------------------------------------------------------- MarkedAccount


class FakeBroker:
    def __init__(self, cash: str, positions: list[Any]) -> None:
        self._cash, self._positions = D(cash), positions

    def cash_usd(self) -> Decimal:
        return self._cash

    def positions(self) -> list[Any]:
        return self._positions


class Pos:
    def __init__(self, coin: str, qty: str, avg: str) -> None:
        self.coin, self.qty, self.avg_entry_px = coin, D(qty), Price(avg)


def account(positions: list[Any], mids: dict[str, Price], stamped: int | None, clock: FakeClock) -> MarkedAccount:
    return MarkedAccount(
        broker=FakeBroker("300", positions), mids=lambda: mids, mid_time_ms=lambda: stamped, clock=clock, max_age_ms=30_000
    )  # type: ignore[arg-type]


def test_equity_is_cash_plus_unrealised_pnl_at_the_live_mid_long_and_short() -> None:
    clock = FakeClock(T0)
    longs = account([Pos("SOL", "2", "100")], {"SOL": Price("105")}, T0 - 1000, clock)
    shorts = account([Pos("SOL", "-2", "100")], {"SOL": Price("105")}, T0 - 1000, clock)
    assert longs.equity_usd() == D(310) and shorts.equity_usd() == D(290)


def test_equity_without_positions_needs_no_marks_but_with_positions_unknown_marks_mean_unknown() -> None:
    clock = FakeClock(T0)
    assert account([], {}, None, clock).equity_usd() == D(300)
    held = [Pos("SOL", "1", "100")]
    assert account(held, {"SOL": Price("100")}, None, clock).equity_usd() is None  # no mids ever
    assert account(held, {"SOL": Price("100")}, T0 - 30_001, clock).equity_usd() is None  # older than the stale limit
    assert account(held, {"SOL": Price("100")}, T0 - 30_000, clock).equity_usd() == D(300)
    assert account(held, {"ETH": Price("100")}, T0, clock).equity_usd() is None  # no mid for the held coin


# ------------------------------------------------------------------------------------------------- PacedInputs


class FakeBackfiller:
    def __init__(self, undone: int) -> None:
        self.refreshed: list[str] = []
        self.pending = undone
        self.complete = False
        self.candidates: list[str] = []
        self.fail = False

    def set_candidates(self, wallets: Any) -> None:
        self.candidates = list(wallets)

    def step(self) -> bool:
        if self.pending == 0:
            return False
        self.pending -= 1
        return True

    def refresh(self, wallet: str) -> None:
        if self.fail:
            raise HlBudgetError("no room")
        self.refreshed.append(wallet)

    def inputs(self, wallet: str, t_ms: int) -> None:
        return None


def test_work_backfills_first_then_refreshes_the_candidates_in_turn_and_survives_a_failed_fetch() -> None:
    backfiller = FakeBackfiller(undone=2)
    inputs = PacedInputs(backfiller)  # type: ignore[arg-type]
    inputs.set_candidates(["0xA", "0xb", "0xC"])
    assert backfiller.candidates == ["0xa", "0xb", "0xc"]
    inputs.work()
    inputs.work()
    assert backfiller.refreshed == []  # the first backfill comes first
    for _ in range(4):
        inputs.work()
    assert backfiller.refreshed == ["0xa", "0xb", "0xc", "0xa"]
    backfiller.fail = True
    inputs.work()  # a request that does not fit the budget is not an error
    inputs.refresh("0xa")  # the cycle's own refresh does nothing
    assert backfiller.refreshed == ["0xa", "0xb", "0xc", "0xa"]


# -------------------------------------------------------------------------------------------------- MarketHub


class NoConnector:
    def connect(self) -> Any:
        raise OSError("nothing listens")


def test_seeded_mids_are_marks_with_a_receive_time_and_bad_prices_are_ignored() -> None:
    clock = FakeClock(T0)
    hub = MarketHub(connector=NoConnector(), clock=clock, max_book_age_ms=5000, seed=1)
    assert hub.mids() == {} and hub.mid_time_ms() is None
    hub.seed_mids({"SOL": Price("100"), "BAD": Price("0")})
    assert hub.mids() == {"SOL": Price("100")} and hub.mid_time_ms() == T0
