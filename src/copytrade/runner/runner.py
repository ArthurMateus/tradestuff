"""``Runner``: the running copy-trading engine (paper only). Built by ``wiring.build_runner``."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.clock import ClockSync
from copytrade.core.config import Config
from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert, AlertSink
from copytrade.hl.errors import HlError
from copytrade.hl.ws import HlWsFeed
from copytrade.ledger.codec import dumps, encode_value
from copytrade.ledger.store import Ledger
from copytrade.paper.broker import PaperBroker
from copytrade.paper.settings import PaperSettings
from copytrade.paper.types import MarkUpdate
from copytrade.positions.book import PositionBook
from copytrade.positions.manager import PositionManager
from copytrade.recorder.service import Recorder
from copytrade.risk.gate import STATE_FILENAME, RiskGate
from copytrade.runner.adapters import MarketHub, RestMarketSource, RestMetaSource
from copytrade.runner.deps import RunnerDeps
from copytrade.runner.flatten import (
    ALERT_FLATTEN_INCOMPLETE,
    FLATTEN_RERUN_INTERVAL_S,
    FLATTEN_RERUN_MAX,
    FlattenSupervisor,
)
from copytrade.runner.policy import RunnerEntryPolicy
from copytrade.runner.reload import (
    KIND_CHECKPOINT,
    KIND_RUNNER_START,
    KIND_RUNNER_STOP,
    ReloadParts,
    ReloadResult,
    Requeued,
    Uncertainty,
    announce_and_pause,
    checkpoint_payload,
    reload_state,
    scan_ledger,
)
from copytrade.runner.retention import prune_recordings
from copytrade.runner.sources import BookShares, MarkedAccount, PacedInputs
from copytrade.runner.tail import LedgerTail
from copytrade.runner.timebase import ALERT_CLOCK_JUMP, ALERT_LOOP_STALLED, SKIP_CLOCK_JUMP, TimeBase
from copytrade.selection.manager import FollowManager
from copytrade.signals.detector import SignalDetector
from copytrade.telegram.bot import TelegramBot

_log = logging.getLogger(__name__)

SELECTION_WORK_INTERVAL_S = 10  # one paced scoring-input slice (see ``PacedInputs``) per this much local time
CHECKPOINT_MIN_INTERVAL_S = 1  # a changed state is written at most once per second ...
CHECKPOINT_FORCE_INTERVAL_S = 60  # ... and an unchanged one at least once per minute (cursors, best prices)
HOURLY_MS = 3_600_000  # retention pruning and the recording-universe refresh
POSTS_INTERVAL_MS = 1_000  # trade posts are synced on a timer, not only when a command arrives
THREAD_JOIN_TIMEOUT_S = 8.0
SECTION_ALERT_INTERVAL_MS = 600_000
ALERT_SECTION_FAILED = "runner_section_failed"
__all__ = [
    "ALERT_FLATTEN_INCOMPLETE",
    "FLATTEN_RERUN_INTERVAL_S",
    "FLATTEN_RERUN_MAX",
    "Runner",
    "RunnerParts",
    "RunnerPaths",
    "StartReport",
    "StepReport",
]


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


@dataclass(frozen=True)
class RunnerParts:
    """The wired components (built by ``wiring``; nothing is started)."""

    config: Config
    paths: RunnerPaths
    run_id: str
    ledger: Ledger
    sync: ClockSync
    timebase: TimeBase
    hub: MarketHub
    meta: RestMetaSource
    market: RestMarketSource
    broker: PaperBroker
    gate: RiskGate
    book: PositionBook
    manager: PositionManager
    bot: TelegramBot
    recorder: Recorder
    follow: FollowManager
    detector: SignalDetector
    feed: HlWsFeed
    policy: RunnerEntryPolicy
    supervisor: FlattenSupervisor
    gate_lock: threading.RLock
    inputs: PacedInputs
    shares: BookShares
    account: MarkedAccount
    relay: AlertSink
    stopping: threading.Event


class Runner:
    """The real components, wired. Read-only attributes (for diagnostics and tests): ``config``, ``paths``,
    ``run_id``, ``ledger``, ``sync`` (ClockSync), ``broker``, ``gate``, ``book``, ``manager``, ``bot``,
    ``recorder``, ``follow`` (FollowManager), ``detector``, ``feed`` (HlWsFeed), ``hub`` (MarketHub),
    ``policy`` (RunnerEntryPolicy), ``flatten_runs`` (the run ids of every ``flatten`` call so far:
    the bot's first, then the supervisor's re-runs), ``gate_lock``
    (the ONE ``threading.RLock`` shared by the loop, the sinks and the bot), ``threads``, ``last_advanced_ms``,
    ``entries_blocked``, ``stopping``.

    Built by ``build_runner`` (nothing is started, no network is touched, the ledger is open). Threading: the trading
    thread calls ``start``/``step``/``stop``; the Telegram poll, the Telegram flush and the watchdog run on their own
    daemon threads and never touch the broker, the manager or the exchange except through the bot, which takes the gate
    lock. EVERY call into the gate, the broker, the manager and the share book is made under ``gate_lock``."""

    def __init__(self, *, parts: RunnerParts, deps: RunnerDeps) -> None:
        self.config = parts.config
        self.paths = parts.paths
        self.run_id = parts.run_id
        self.ledger = parts.ledger
        self.sync = parts.sync
        self.broker = parts.broker
        self.gate = parts.gate
        self.book = parts.book
        self.manager = parts.manager
        self.bot = parts.bot
        self.recorder = parts.recorder
        self.follow = parts.follow
        self.detector = parts.detector
        self.feed = parts.feed
        self.hub = parts.hub
        self.policy = parts.policy
        self.gate_lock = parts.gate_lock
        self.threads: tuple[threading.Thread, ...] = ()
        self.last_advanced_ms: int | None = None
        self._parts = parts
        self._deps = deps
        self._clock = deps.clock
        self._timebase = parts.timebase
        self._paper = PaperSettings.from_config(parts.config)
        self._stopping = parts.stopping
        self._stop_requested = threading.Event()
        self._threads_stop = threading.Event()
        self._lifecycle = threading.Lock()
        self._started = False
        self._stopped = False
        self._tail: LedgerTail | None = None
        self._jump_alerted = False
        self._known_followed: frozenset[str] = frozenset()
        self._last_step_ms = self._clock.now_ms()
        self._last_mark_ms: int | None = None
        self._last_fingerprint: bytes | None = None
        self._last_checkpoint_ms = 0
        self._next_selection_ms = 0
        self._next_delist_ms = 0
        self._next_hourly_ms = 0
        self._next_posts_ms = 0
        self._section_alerted: dict[str, int] = {}
        self._mark_interval_ms = int(parts.config["eval.mark_interval_s"]) * 1000
        self._stall_ms = 3 * int(parts.config["ledger.heartbeat_interval_s"]) * 1000
        self._stall_alerted = False

    # ------------------------------------------------------------------------------------------------ views
    @property
    def flatten_runs(self) -> tuple[str, ...]:
        return self._parts.supervisor.runs

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    @property
    def entries_blocked(self) -> bool:
        """New entries are refused: the persisted pause (manual, drawdown, or an unacknowledged startup uncertainty)
        or a stop in progress."""
        return self.gate.paused or self.stopping

    # ------------------------------------------------------------------------------------------------ start
    def start(self) -> StartReport:
        """Reload from the ledger (set broker time first), alert on anything uncertain and pause entries, start the
        Telegram poll, flush and watchdog threads, write the ``runner_start`` ledger record."""
        with self._lifecycle:
            if self._started or self._stopped:
                raise RuntimeError("the runner was already started")
            self._started = True
        parts = self._parts
        parts.sync.tick()
        with self.gate_lock:
            result = self._reload()
            self._known_followed = self.follow.followed
        self._section("feed", self.feed.tick)  # connect and resync the restored wallets (B3) before anything else
        self._section("mids", lambda: self.hub.seed_mids(parts.market.all_mids()))  # marks before the first frame
        prune_recordings(
            self.config, recordings_dir=self.paths.recordings_dir, ledger=self.ledger, now_ms=self._clock.now_ms()
        )
        parts.recorder.start()
        with self.gate_lock:
            self.ledger.append(
                KIND_RUNNER_START,
                {
                    "run_id": self.run_id,
                    "mode": "paper",
                    "restored_positions": result.restored_positions,
                    "restored_stops": result.restored_stops,
                    "requeued_exits": len(result.requeued_exits),
                    "uncertain": [u.code for u in result.uncertain],
                },
            )
            self._write_checkpoint(force=True)
        self._tail = LedgerTail(self.paths.ledger_dir)
        self._start_threads()
        self._last_step_ms = self._clock.now_ms()
        return StartReport(
            restored_positions=result.restored_positions,
            restored_stops=result.restored_stops,
            requeued_exits=result.requeued_exits,
            uncertain=result.uncertain,
            entries_blocked=self.entries_blocked,
        )

    def _reload(self) -> ReloadResult:
        parts = self._parts
        reload_parts = ReloadParts(
            broker=self.broker,
            gate=self.gate,
            manager=self.manager,
            follow=self.follow,
            book=self.book,
            state_file=self.paths.state_dir / STATE_FILENAME,
            send_alert=parts.relay,
            fetch_rules=parts.meta.fetch,
            watch_gap=self.feed.open_gap,
        )
        now_ms = self._exchange_now_ms()
        scan = scan_ledger(self.ledger, self._paper, now_ms=self._clock.now_ms())
        result = reload_state(reload_parts, scan, now_ms=now_ms)
        announce_and_pause(reload_parts, result.uncertain)
        return result

    def _exchange_now_ms(self) -> int:
        """The synced exchange time, or 0 when unsynced (the reload then keeps the ledger's last known time)."""
        sync = self._parts.sync
        return 0 if sync.refusal_reason(ActionKind.OPEN) is not None else sync.exchange_now().ms

    # ------------------------------------------------------------------------------------------------ the loop
    def step(self) -> StepReport:
        """ONE loop iteration, called by the trading thread. Order (every gate or manager call under ``gate_lock``):
        ``ClockSync.tick``; time-base target (skip while unsynced or on a jump); ``manager.advance_to(target)``;
        marks and delistings; ``gate.mark_equity(target)`` every ``eval.mark_interval_s``; ``feed.tick``;
        recorder tick; follow cycle when due; backfill step; flatten re-runs; periodic retention and checkpoint.
        Raises ``RuntimeError`` before ``start()`` (nothing is wired to the broker before the reload)."""
        if not self._started or self._stopped:
            raise RuntimeError("step() needs a started, not yet stopped runner")
        self._parts.sync.tick()
        advanced, skipped = self._advance_and_mark()
        self._section("feed", self.feed.tick)
        self._section("recorder", self.recorder.tick)
        self._selection()
        with self.gate_lock:
            self._parts.supervisor.rerun_if_due()
            self._book_copy_results()
            self._write_checkpoint()
        self._hourly()
        self._last_step_ms = self._clock.now_ms()
        return StepReport(advanced_to_ms=advanced, skipped=skipped)

    def _advance_and_mark(self) -> tuple[int | None, str | None]:
        with self.gate_lock:
            target, reason = self._timebase.next_target_ms()
            if target is None:
                if reason == SKIP_CLOCK_JUMP and not self._jump_alerted:
                    self._jump_alerted = True
                    self._parts.relay.send(
                        Alert(
                            kind=ALERT_CLOCK_JUMP,
                            message="The exchange clock estimate jumped: broker time is not advanced until it settles.",
                        )
                    )
                return None, reason
            self._jump_alerted = False
            self.manager.advance_to(target)
            self.last_advanced_ms = target
            self._mark(target)
        self._delistings(target)
        with self.gate_lock:
            if self._last_mark_ms is None or target - self._last_mark_ms >= self._mark_interval_ms:
                self._last_mark_ms = target
                self.gate.mark_equity(target)
        return target, None

    def _mark(self, target: int) -> None:
        """Give every held coin its live mid at this iteration's exchange time (stops, liquidations, trailing)."""
        stamped = self.hub.mid_time_ms()
        if stamped is None or self._clock.now_ms() - stamped > int(self.config["feed.stale_after_s"]) * 1000:
            return
        mids = self.hub.mids()
        for position in self.broker.positions():
            mid = mids.get(position.coin)
            if mid is not None:
                self.manager.on_mark(MarkUpdate(coin=position.coin, mark=mid, time_ms=target))

    def _delistings(self, target: int) -> None:
        now = self._clock.now_ms()
        if now < self._next_delist_ms:
            return
        self._next_delist_ms = now + self._paper.meta_refresh_ms
        try:
            delisted = self._parts.meta.delisted()
        except OSError:
            _log.warning("delisting check failed", extra={"event": "delist_check_failed"})
            return
        with self.gate_lock:
            for position in self.broker.positions():
                if position.coin not in delisted:
                    continue
                price = self.hub.mids().get(position.coin) or self.book.mark_px(position.coin)
                if price is not None:
                    self.manager.on_delist(position.coin, price, target)
                else:
                    self._alert_section(f"delist:{position.coin}", "no price to settle a delisted coin")

    def _section(self, name: str, work: Callable[[], object]) -> None:
        """Run a part of the loop that must not take the loop down: a network or disk failure in it is logged and
        alerted (at most once per ``SECTION_ALERT_INTERVAL_MS``); exits and stops do not depend on any of them."""
        try:
            work()
        except (OSError, HlError) as exc:
            _log.warning("loop section failed", extra={"event": "section_failed", "section": name}, exc_info=True)
            self._alert_section(name, f"{type(exc).__name__}")

    def _alert_section(self, name: str, detail: str) -> None:
        now = self._clock.now_ms()
        if now - self._section_alerted.get(name, -SECTION_ALERT_INTERVAL_MS) >= SECTION_ALERT_INTERVAL_MS:
            self._section_alerted[name] = now
            self._parts.relay.send(
                Alert(kind=ALERT_SECTION_FAILED, message=f"{name} failed ({detail}); trading goes on")
            )

    def _selection(self) -> None:
        """The follow cycle when due and one paced scoring-input slice every ``SELECTION_WORK_INTERVAL_S``."""
        now = self._clock.now_ms()
        if now >= self._next_selection_ms:
            self._next_selection_ms = now + SELECTION_WORK_INTERVAL_S * 1000
            self._section("scoring_inputs", self._parts.inputs.work)
        if self.follow.due():
            self._section("follow_cycle", lambda: self.follow.run_cycle(p95_latency_s=None))
        self.follow.tick()
        self._tell_dropped_leaders()

    def _tell_dropped_leaders(self) -> None:
        followed = self.follow.followed
        dropped = self._known_followed - followed
        self._known_followed = followed
        if dropped:
            with self.gate_lock:
                for wallet in sorted(dropped):
                    self.manager.leader_dropped(wallet)
            self._section("recording_universe", self.recorder.refresh_universe)

    def _book_copy_results(self) -> None:
        """Our closed copies feed the per-leader pause (F6.AC2): every ``trade`` record appended since the last step."""
        assert self._tail is not None  # noqa: S101 - set by start()
        for record in self._tail.poll():
            if record.kind != "trade":
                continue
            share = self.book.state(record.payload["share_id"])
            if share is None or not share.leader.startswith("0x"):
                continue
            equity = self._parts.account.equity_usd() or Decimal(0)
            self.follow.on_copy_closed(share.leader, pnl_usd=Decimal(record.payload["pnl_usd"]), equity_usd=equity)

    def _hourly(self) -> None:
        now = self._clock.now_ms()
        if now < self._next_hourly_ms:
            return
        first = self._next_hourly_ms == 0
        self._next_hourly_ms = now + HOURLY_MS
        self._section(
            "retention",
            lambda: prune_recordings(
                self.config, recordings_dir=self.paths.recordings_dir, ledger=self.ledger, now_ms=now
            ),
        )
        if not first:
            self._section("recording_universe", self.recorder.refresh_universe)

    # ------------------------------------------------------------------------------------------ checkpoints
    def _write_checkpoint(self, *, force: bool = False) -> None:
        """Write a ``runner_checkpoint`` when the structural state changed (at most once per
        ``CHECKPOINT_MIN_INTERVAL_S``), at least once per ``CHECKPOINT_FORCE_INTERVAL_S``, or when forced. The caller
        holds the gate lock."""
        exported = self.manager.export_state()
        entries = self.gate.export_entries()
        fingerprint = dumps(encode_value({"state": exported["state"], "entries": entries}))
        now = self._clock.now_ms()
        since_ms = now - self._last_checkpoint_ms
        changed = fingerprint != self._last_fingerprint
        if not (
            force
            or (changed and since_ms >= CHECKPOINT_MIN_INTERVAL_S * 1000)
            or since_ms >= CHECKPOINT_FORCE_INTERVAL_S * 1000
        ):
            return
        self.ledger.append(
            KIND_CHECKPOINT,
            checkpoint_payload(
                run_id=self.run_id,
                last_advanced_ms=self.last_advanced_ms,
                risk_state_expected=(self.paths.state_dir / STATE_FILENAME).exists(),
                manager=exported,
                gate_entries=entries,
            ),
        )
        self._last_fingerprint, self._last_checkpoint_ms = fingerprint, now

    # ------------------------------------------------------------------------------------------------ threads
    def _start_threads(self) -> None:
        bot = self.bot
        self.threads = (
            threading.Thread(target=self._loop("telegram-poll", self._poll_work), name="r0-telegram-poll", daemon=True),
            threading.Thread(
                target=self._loop("telegram-flush", bot.flush, final=bot.flush), name="r0-telegram-flush", daemon=True
            ),
            threading.Thread(target=self._loop("watchdog", self._watch), name="r0-watchdog", daemon=True),
        )
        for thread in self.threads:
            thread.start()

    def _loop(
        self, role: str, work: Callable[[], Any], *, final: Callable[[], Any] | None = None
    ) -> Callable[[], None]:
        """The body of a side thread: ``work`` every ``thread_pause_s`` until the stop, then ``final`` once. A step that
        raises is logged and the thread goes on (a dead poll or flush thread would silence the bot)."""

        def run() -> None:
            while not self._threads_stop.is_set():
                self._guarded_thread_call(role, work)
                self._threads_stop.wait(self._deps.thread_pause_s)
            if final is not None:
                self._guarded_thread_call(role, final)

        return run

    @staticmethod
    def _guarded_thread_call(name: str, work: Callable[[], Any]) -> None:
        try:
            work()
        except Exception:
            _log.exception("a runner thread step failed", extra={"event": "thread_step_failed", "thread": name})

    def _poll_work(self) -> None:
        self.bot.poll_once()
        now = self._clock.now_ms()
        if now >= self._next_posts_ms:
            self._next_posts_ms = now + POSTS_INTERVAL_MS
            self.bot.sync_posts()

    def _watch(self) -> None:
        """The stall heartbeat: no completed ``step`` for 3 x ``ledger.heartbeat_interval_s`` of local time."""
        silent_ms = self._clock.now_ms() - self._last_step_ms
        if silent_ms > self._stall_ms and not self._stall_alerted:
            self._stall_alerted = True
            self._parts.relay.send(
                Alert(
                    kind=ALERT_LOOP_STALLED,
                    message=f"The trading loop has not completed an iteration for {silent_ms // 1000} s.",
                )
            )
        elif silent_ms <= self._stall_ms:
            self._stall_alerted = False

    # ------------------------------------------------------------------------------------------------ stop
    def request_stop(self, reason: str) -> None:
        """Ask for a clean stop (thread-safe, idempotent). New entries are refused from this call on."""
        if not self._stopping.is_set():
            _log.info("stop requested", extra={"event": "runner_stop_requested", "reason": reason})
        self._stopping.set()
        self._stop_requested.set()

    def stop(self) -> int:
        """Clean stop: refuse new entries, leave stops and exits as they are, write a final checkpoint and
        ``runner_stop`` record, flush the recorder, the Telegram outbox (bounded) and the ledger, join the threads.
        Returns the exit code, 0. Idempotent."""
        with self._lifecycle:
            if self._stopped:
                return 0
            self._stopped = True
        self.request_stop("stop")
        started = self._tail is not None
        with self.gate_lock:
            if started:
                self._best_effort("the final checkpoint", lambda: self._write_checkpoint(force=True))
                self._best_effort(
                    "the stop record",
                    lambda: self.ledger.append(KIND_RUNNER_STOP, {"run_id": self.run_id, "reason": "stop"}),
                )
                self._best_effort("the recorder shutdown", self.recorder.shutdown)
            self.hub.close()
        self._threads_stop.set()
        for thread in self.threads:
            thread.join(timeout=THREAD_JOIN_TIMEOUT_S)
        self._best_effort("closing the ledger", self.ledger.close)
        return 0

    @staticmethod
    def _best_effort(what: str, work: Callable[[], Any]) -> None:
        try:
            work()
        except Exception:
            _log.exception("%s failed during the stop", what, extra={"event": "stop_step_failed"})

    def run(self, stop: threading.Event) -> int:
        """``start()``, ``step()`` until ``stop`` is set or ``request_stop`` was called, then ``stop()``; sleeps
        ``thread_pause_s`` (real time) between iterations. A ``CopytradeError`` or ``OSError`` from the loop is
        re-raised AFTER a best-effort ``stop()`` (threads joined, files closed); ``run_app`` turns it into exit 1."""
        try:
            self.start()
            while not stop.is_set() and not self._stop_requested.is_set():
                self.step()
                self._stop_requested.wait(self._deps.thread_pause_s)
        except BaseException:
            self.stop()
            raise
        return self.stop()
