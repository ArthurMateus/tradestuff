"""``Runner``: the running copy-trading engine (paper only). Built by ``wiring.build_runner``."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from copytrade.runner.reload import Requeued, Uncertainty

ALERT_FLATTEN_INCOMPLETE = "flatten_incomplete"
FLATTEN_RERUN_INTERVAL_S = 5
FLATTEN_RERUN_MAX = 12


@dataclass(frozen=True)
class RunnerPaths:
    """``ledger_dir``, ``recordings_dir``, ``cache_dir`` from ``storage.*`` (relative paths are relative to the root);
    ``state_dir`` = ``<parent of ledger_dir>/state`` (the risk gate's state file lives there)."""

    ledger_dir: Path
    recordings_dir: Path
    cache_dir: Path
    state_dir: Path


@dataclass(frozen=True)
class StartReport:
    restored_positions: int
    restored_stops: int
    requeued_exits: tuple[Requeued, ...]
    uncertain: tuple[Uncertainty, ...]
    entries_blocked: bool


@dataclass(frozen=True)
class StepReport:
    """``advanced_to_ms``: the exchange ms handed to ``advance_to`` in this iteration (``None`` when it was skipped);
    ``skipped``: ``timebase.SKIP_*`` or ``None``."""

    advanced_to_ms: int | None
    skipped: str | None


class Runner:
    """The real components, wired. Read-only attributes (for diagnostics and tests): ``config``, ``paths``,
    ``run_id``, ``ledger``, ``sync`` (ClockSync), ``broker``, ``gate``, ``book``, ``manager``, ``bot``,
    ``recorder``, ``follow`` (FollowManager), ``detector``, ``feed`` (HlWsFeed), ``hub`` (MarketHub),
    ``policy`` (RunnerEntryPolicy), ``flatten_runs`` (the run ids of every ``flatten`` call so far:
    the bot's first, then the supervisor's re-runs), ``gate_lock``
    (the ONE ``threading.RLock`` shared by the loop, the sinks and the bot), ``threads``, ``last_advanced_ms``,
    ``entries_blocked``, ``stopping``.

    Built by ``build_runner`` (nothing is started, no network is touched, the ledger is open)."""

    config: Any
    paths: RunnerPaths
    run_id: str
    ledger: Any
    sync: Any
    broker: Any
    gate: Any
    book: Any
    manager: Any
    bot: Any
    recorder: Any
    follow: Any
    detector: Any
    feed: Any
    hub: Any
    policy: Any
    flatten_runs: tuple[str, ...]
    gate_lock: Any
    threads: tuple[threading.Thread, ...]
    last_advanced_ms: int | None
    entries_blocked: bool
    stopping: bool

    def start(self) -> StartReport:
        """Reload from the ledger (set broker time first), alert on anything uncertain and pause entries, start the
        Telegram poll, flush and watchdog threads, write the ``runner_start`` ledger record."""
        raise NotImplementedError

    def step(self) -> StepReport:
        """ONE loop iteration, called by the trading thread. Order (every gate or manager call under ``gate_lock``):
        ``ClockSync.tick``; time-base target (skip while unsynced or on a jump); ``manager.advance_to(target)``;
        marks and delistings; ``gate.mark_equity(target)`` every ``eval.mark_interval_s``; ``feed.tick``;
        recorder tick; follow cycle when due; backfill step; flatten re-runs; periodic retention and checkpoint.
        Raises ``RuntimeError`` before ``start()`` (nothing is wired to the broker before the reload)."""
        raise NotImplementedError

    def request_stop(self, reason: str) -> None:
        """Ask for a clean stop (thread-safe, idempotent). New entries are refused from this call on."""
        raise NotImplementedError

    def stop(self) -> int:
        """Clean stop: refuse new entries, leave stops and exits as they are, write a final checkpoint and
        ``runner_stop`` record, flush the recorder, the Telegram outbox (bounded) and the ledger, join the threads.
        Returns the exit code, 0. Idempotent."""
        raise NotImplementedError

    def run(self, stop: threading.Event) -> int:
        """``start()``, ``step()`` until ``stop`` is set or ``request_stop`` was called, then ``stop()``; sleeps
        ``thread_pause_s`` (real time) between iterations. A ``CopytradeError`` or ``OSError`` from the loop is
        re-raised AFTER a best-effort ``stop()`` (threads joined, files closed); ``run_app`` turns it into exit 1."""
        raise NotImplementedError
