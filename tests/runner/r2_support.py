"""Shared steps of the R2 runner tests (real runner over the loopback fakes; see ``world.py``)."""

from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from tests.runner.fake_hl import fill_json
from tests.runner.test_dev_e2e import small_leader
from tests.runner.world import LEADER, World

__all__ = [
    "INTERESTING", "Beat", "SleepLog", "WalkLog", "add_to_position", "cuts_after", "drive", "fill_ledger", "keep_first",
    "ledger_lines", "live_sls", "open_copy", "opened_with", "rate_limit", "restart_on_cut", "wait_real",
]

# the records a kill -9 can fall between (recording bookkeeping records are never interesting)
INTERESTING = frozenset(
    {"fill", "share_state", "paper_stop", "paper_cancel", "paper_order", "risk_decision", "paper_stop_trigger", "trade"}
)


def open_copy(new_world: Any, **config: Any) -> tuple[World, Any]:
    """A followed leader opens; our paper copy (1.00 SOL at about 100) is filled and protected (SL 98.6, TP 103.1)."""
    world: World = new_world(**config)
    small_leader(world)
    world.seed_follow()
    runner, _ = world.start()
    world.leader_open(runner)
    world.run_until(runner, lambda: runner.broker.position("SOL") is not None and runner.broker.stops(), max_steps=40)
    world.step(runner, 3, ms=500)
    return world, runner


def add_to_position(world: World, runner: Any, *, tid: int = 5) -> None:
    """The leader adds 3 SOL at 102 (a higher price, so the new stop is tighter and the gate does not refuse
    ``stop_widening``): our copy adds 0.60 and the stop-loss is re-placed for 1.60."""
    world.hl.mids["SOL"] = "102.0"
    world.hl.leader_positions[LEADER.lower()] = [("SOL", "8.0", "100.0")]
    world.hl.push_user_fills(
        LEADER,
        [
            fill_json(
                tid, coin="SOL", side="B", sz="3.0", px="102.0", direction="Open Long",
                time_ms=world.exchange_ms() - 100, start_position="5.0",
            )
        ],
    )
    world.run_until(
        runner,
        lambda: (p := runner.broker.position("SOL")) is not None
        and p.qty > Decimal("1.00")
        and any(s.kind == "sl" and s.qty == p.qty for s in runner.broker.stops()),
        max_steps=60,
        ms=500,
    )
    world.step(runner, 3, ms=500)


def ledger_lines(world: World) -> list[bytes]:
    return (world.ledger_dir / "ledger.jsonl").read_bytes().splitlines(keepends=True)


def keep_first(world: World, lines: list[bytes], keep: int) -> None:
    """The ledger exactly as a kill -9 left it after record ``keep`` (a suffix of the append-only file is gone)."""
    (world.ledger_dir / "ledger.jsonl").write_bytes(b"".join(lines[:keep]))


def cuts_after(world: World, first: Callable[[Any], bool], *, start_at: int = 0) -> list[int]:
    """How many records to keep for every kill point that falls AFTER the first record satisfying ``first`` and BEFORE
    the next ``runner_checkpoint`` (so the checkpoint in force is the one written before the event)."""
    records = world.records()
    index = next(i for i, r in enumerate(records) if i >= start_at and first(r))
    cuts = []
    for i in range(index, len(records)):
        if records[i].kind == "runner_checkpoint":
            break
        if records[i].kind in INTERESTING:
            cuts.append(i + 1)
    assert cuts, "no kill point found after the event"
    return cuts


def restart_on_cut(world: World, lines: list[bytes], keep: int) -> tuple[Any, Any]:
    keep_first(world, lines, keep)
    return world.start()


def live_sls(runner: Any, coin: str = "SOL") -> list[Any]:
    return [s for s in runner.broker.stops() if s.kind == "sl" and s.coin == coin]


def wait_real(cond: Callable[[], Any], *, seconds: float = 10.0, what: str = "the condition") -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


# ---------------------------------------------------------------------------------------------- ledger scans (AC3)
import threading  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402


@dataclass
class WalkLog:
    """Every whole-ledger walk (a hash-verified pass over ``ledger.jsonl``: ``Ledger.records``, ``read_records``,
    ``verify_ledger`` all go through ``copytrade.ledger.store._walk``) with the thread that started it."""

    threads: list[threading.Thread] = field(default_factory=list)

    def reset(self) -> None:
        self.threads.clear()

    @property
    def total(self) -> int:
        return len(self.threads)

    @property
    def on_trading_thread(self) -> int:
        return sum(t is threading.main_thread() for t in self.threads)


def fill_ledger(world: World, megabytes: int = 50) -> None:
    """A big synthetic history (hash-chained through the real ledger): ``megabytes`` MB of filler records that no
    component reads (an unknown kind), written before the runner is built."""
    from copytrade.ledger.store import Ledger

    blob = "x" * 200_000
    ledger = Ledger.open(world.ledger_dir, clock=world.clock)
    try:
        for i in range(megabytes * 5):
            ledger.append("synthetic_filler", {"i": i, "blob": blob})
    finally:
        ledger.close()


# ---------------------------------------------------------------------------------------- RISK-66 / RISK-67 (AC1, AC2)
from tests.hl.support import FakeClock, FakeSleeper  # noqa: E402


class SleepLog(FakeSleeper):
    """The fake sleeper (advances the fake clock) that remembers WHICH THREAD slept and for how long, so a test can tell
    what blocked the trading thread (the test's own thread) from what a side thread did."""

    def __init__(self, clock: FakeClock) -> None:
        super().__init__(clock)
        self.by_thread: list[tuple[int, float]] = []

    def sleep(self, seconds: float) -> None:
        self.by_thread.append((threading.get_ident(), seconds))
        super().sleep(seconds)

    def trading_thread_s(self) -> float:
        me = threading.get_ident()
        return sum(s for ident, s in self.by_thread if ident == me)


def opened_with(new_world: Any, **deps: Any) -> tuple[World, Any]:
    """Like ``test_dev_e2e.opened`` but the runner is built with ``deps`` (e.g. a ``SleepLog``)."""
    world: World = new_world(**deps.pop("config", {}))
    small_leader(world)
    world.seed_follow()
    runner, _ = world.start(**deps)
    world.leader_open(runner)
    world.run_until(runner, lambda: runner.broker.position("SOL") is not None and runner.broker.stops(), max_steps=40)
    world.step(runner, 3, ms=500)
    return world, runner


def rate_limit(world: World, *types: str) -> None:
    """The fake Hyperliquid answers these info request types with HTTP 429 (what it does when the budget is gone)."""
    world.hl.fail_types.update(types)
    original = world.hl._reply

    def reply(handler: Any, status: int, body: bytes) -> None:
        original(handler, 429 if status == 500 else status, body)

    world.hl._reply = reply  # type: ignore[method-assign,assignment]


@dataclass
class Beat:
    real_s: float  # wall time of one ``Runner.step`` on the calling (trading) thread
    slept_s: float  # fake-clock time that ``step`` spent in sleeps on this thread (retry back-off, budget waits)
    report: Any


def drive(world: World, runner: Any, ms: int, log: SleepLog) -> Beat:
    """One loop iteration as ``World.step`` does it, measured: the loop's time is what ``step`` blocks for."""
    world.clock.advance(ms)
    world.pump_market()
    before = log.trading_thread_s()
    started = time.perf_counter()
    report = runner.step()
    real = time.perf_counter() - started
    time.sleep(0.012)
    return Beat(real_s=real, slept_s=log.trading_thread_s() - before, report=report)
