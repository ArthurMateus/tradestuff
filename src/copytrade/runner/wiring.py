"""The composition root."""

from __future__ import annotations

import random
import secrets
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import copytrade
from copytrade.core.clock import Clock, ClockSync
from copytrade.core.config import Config
from copytrade.core.errors import ConfigError, CopytradeError
from copytrade.core.events import Alert, AlertSink
from copytrade.core.secrets import Secrets, SecretValue
from copytrade.core.startup import startup
from copytrade.hl.access import AccessMonitor
from copytrade.hl.budget import Priority, RateBudget, Sleeper
from copytrade.hl.connector import WebsocketsConnector
from copytrade.hl.errors import HlBudgetError
from copytrade.hl.rest import CallLimit, HlRestClient, StdlibHttpTransport
from copytrade.hl.schema import SchemaFailureMonitor
from copytrade.hl.ws import FillSink, HlWsFeed
from copytrade.ledger.store import Ledger
from copytrade.paper.broker import PaperBroker
from copytrade.paper.gate import GateAuthority
from copytrade.positions.book import PositionBook
from copytrade.positions.manager import PositionManager
from copytrade.recorder.candles import CandleStore
from copytrade.recorder.registry import WalletRegistry
from copytrade.recorder.service import Recorder, RecorderPaths, RecorderPorts
from copytrade.recorder.store import RecordingStore
from copytrade.risk.gate import RiskGate
from copytrade.risk.ports import AlwaysAllowCalendar
from copytrade.runner.adapters import (
    ConfigCostModel,
    ExchangeOffsetSource,
    HttpLeaderboardSource,
    HubTap,
    MarketHub,
    RestMarketSource,
    RestMetaSource,
)
from copytrade.runner.clockwork import BackgroundClock
from copytrade.runner.deps import RunnerDeps
from copytrade.runner.disk import SystemDiskProbe, check_start_disk
from copytrade.runner.failfast import TradingSleeper
from copytrade.runner.flatten import FlattenSupervisor
from copytrade.runner.offthread import BackgroundConnector, BackgroundLeaderboard
from copytrade.runner.policy import RunnerEntryPolicy
from copytrade.runner.runner import Runner, RunnerParts, RunnerPaths
from copytrade.runner.sources import (
    BookShares,
    FollowedUniverse,
    LedgerDowntime,
    LedgerScores,
    MarkedAccount,
    NoBacklog,
    PacedInputs,
    RestCandles,
    RestLeaderData,
    StoredReturns,
)
from copytrade.runner.timebase import GuardedExchangeTime, SyncedExchangeTime, TimeBase
from copytrade.selection.backfill import Backfiller
from copytrade.selection.manager import FollowManager
from copytrade.signals.detector import SignalDetector
from copytrade.signals.models import Signal, SignalSink
from copytrade.telegram.api import TelegramApi
from copytrade.telegram.bot import TelegramBot

_PROBE_COIN = "BTC"
CATCH_UP_MAX_AHEAD_MS = 30_000  # a book stamped further ahead of the local clock is not a live exchange time
_TELEGRAM_ID_KEYS = ("telegram.allowed_user_id", "telegram.control_chat_id", "telegram.alerts_chat_id")
_LEADERBOARD_TIMEOUT_FACTOR = 3  # the leaderboard body is large: three REST timeouts for the whole GET


class RunnerStartError(CopytradeError):
    """The runner cannot be built from this configuration or environment (the message names the key or variable)."""


class _FailFastSleeper:
    """Sleeper of the scoring REST client: a request that does not fit the rate budget now (or needs a retry back-off)
    fails at once instead of blocking the trading thread; the caller tries again on a later slice."""

    def sleep(self, seconds: float) -> None:
        raise HlBudgetError(
            f"the rate budget has no room for this request now (would wait {seconds:.1f} s)", wait_s=seconds
        )


class AlertRelay:
    """The ``AlertSink`` every component receives. The bot needs the gate and the manager, which need an alert sink, so
    the bot is bound later; alerts raised before that are kept and delivered at the bind."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sink: AlertSink | None = None
        self._early: list[Alert] = []

    def bind(self, sink: AlertSink) -> None:
        with self._lock:
            self._sink, early = sink, self._early
            self._early = []
        for alert in early:
            sink.send(alert)

    def send(self, alert: Alert) -> None:
        with self._lock:
            sink = self._sink
            if sink is None:
                self._early.append(alert)
                return
        sink.send(alert)


class _LockedSignals:
    """The detector's ``SignalSink``: every signal reaches the position manager under the one gate lock (RISK-25)."""

    def __init__(self, lock: threading.RLock) -> None:
        self._lock = lock
        self._manager: PositionManager | None = None

    def bind(self, manager: PositionManager) -> None:
        self._manager = manager

    def on_signals(self, signals: Sequence[Signal]) -> None:
        manager = self._manager
        if manager is None:
            raise RunnerStartError("a signal arrived before the position manager was wired")
        with self._lock:
            manager.on_signals(signals)


@dataclass(frozen=True)
class _Exchange:
    """Everything that talks to Hyperliquid or tells the time."""

    rest: HlRestClient  # the trading thread's: fail-fast once the runner is started
    rest_clock: HlRestClient  # the clock estimates' (they run on a worker thread, so they may wait out a back-off)
    rest_scoring: HlRestClient
    trading_sleeper: TradingSleeper
    clock_worker: BackgroundClock
    access: AccessMonitor
    schema_monitor: SchemaFailureMonitor
    sync: ClockSync
    timebase: TimeBase
    guarded: GuardedExchangeTime
    connector: BackgroundConnector  # the leader feed's
    hub_connector: BackgroundConnector
    hub: MarketHub
    market: RestMarketSource
    meta: RestMetaSource


def _paths(root: Path, config: Mapping[str, object]) -> RunnerPaths:
    ledger_dir = root / str(config["storage.ledger_dir"])
    return RunnerPaths(
        ledger_dir=ledger_dir,
        recordings_dir=root / str(config["storage.recordings_dir"]),
        cache_dir=root / str(config["storage.cache_dir"]),
        state_dir=ledger_dir.parent / "state",
    )


def _engine_module_files() -> list[Path]:
    """The source file of every loaded ``copytrade`` module (the F1 engine path set check covers them)."""
    files = {
        str(getattr(module, "__file__", None))
        for name, module in list(sys.modules.items())
        if (name == "copytrade" or name.startswith("copytrade.")) and getattr(module, "__file__", None)
    }
    return sorted(Path(file) for file in files)


def build_runner(root: Path, env: Mapping[str, str], deps: RunnerDeps) -> Runner:
    """Run the F1 startup checks (``core.startup.startup``: path set, config, mode, secrets from ``env`` only), open
    the ledger (``LedgerCorruptError`` propagates: start refused), check the disk (``DiskSpaceError``), build every
    component with ONE shared ``gate_lock`` and a per-process ``GateAuthority`` key, wire the bot as the AlertSink of
    every component. Opens no network connection. Raises ``CopytradeError`` subclasses only."""
    code_root = Path(copytrade.__file__ or "").resolve().parents[2]
    started = startup(root, env, code_root=code_root, engine_module_files=_engine_module_files())
    config = started.config
    if started.secrets.telegram_token is None:
        raise RunnerStartError("COPYTRADE_TELEGRAM_TOKEN is not set: the runner cannot alert without it")
    for key in _TELEGRAM_ID_KEYS:
        if config[key] == 0:
            raise ConfigError("set your own Telegram id (the committed file holds a 0 placeholder)", key=key)
    paths = _paths(root, config)
    check_start_disk(config, deps.disk or SystemDiskProbe(), (paths.ledger_dir, paths.recordings_dir, paths.cache_dir))
    ledger = Ledger.open(paths.ledger_dir, clock=deps.clock)
    try:
        parts = _assemble(config, started.secrets, paths, ledger, deps)
    except BaseException:
        ledger.close()
        raise
    return Runner(parts=parts, deps=deps)


def _rest_client(  # noqa: PLR0913 - the shared parts and the two optional behaviours of the clients
    config: Config,
    deps: RunnerDeps,
    sleeper: Sleeper,
    shared: tuple[RateBudget, AccessMonitor, SchemaFailureMonitor],
    *,
    escalate_cooldown: bool = False,
    call_limit: CallLimit | None = None,
) -> HlRestClient:
    budget, access, schema_monitor = shared
    return HlRestClient(
        config=config,
        clock=deps.clock,
        transport=StdlibHttpTransport(),
        sleeper=sleeper,
        rng=random.Random(),  # noqa: S311 - retry jitter, not security
        budget=budget,
        access=access,
        schema_monitor=schema_monitor,
        info_url=deps.endpoints.info_url,
        escalate_cooldown=escalate_cooldown,
        call_limit=call_limit,
    )


def _live_exchange_ms(hub: MarketHub, clock: Clock) -> Callable[[], int | None]:
    """The live exchange time a restart with an unverified clock catches broker time up to: ONLY the newest hub book
    time that a second book confirms (RISK-73: never the raw clock estimate, which a retried request or a wall-clock
    step can put ahead of the exchange for good), and never one that is more than ``CATCH_UP_MAX_AHEAD_MS`` ahead of
    the local clock (a bogus future stamp)."""

    def live() -> int | None:
        confirmed = hub.confirmed_book_time_ms()
        if confirmed is None or confirmed > clock.now_ms() + CATCH_UP_MAX_AHEAD_MS:
            return None
        return confirmed

    return live


def _build_exchange(config: Config, deps: RunnerDeps, ledger: Ledger, relay: AlertRelay) -> _Exchange:
    """Two REST clients over ONE rate budget, access monitor and schema monitor: the trading thread's (real sleeper,
    CRITICAL work) and the scoring one (never sleeps: a request that does not fit the budget fails and is retried)."""
    clock = deps.clock
    budget = RateBudget(
        budget_per_min=config["hl.rest_weight_budget_per_min"],
        scoring_share=config["hl.scoring_weight_share"],
        clock=clock,
    )
    access = AccessMonitor(config=config, clock=clock, alerts=relay, ledger=LedgerDowntime(ledger))
    schema_monitor = SchemaFailureMonitor(clock=clock, alerts=relay)
    shared = (budget, access, schema_monitor)
    trading_sleeper = TradingSleeper(deps.sleeper)
    rest = _rest_client(config, deps, trading_sleeper, shared, escalate_cooldown=True, call_limit=trading_sleeper)
    rest_clock = _rest_client(config, deps, deps.sleeper, shared)
    sync = ClockSync.from_config(
        config,
        clock=clock,
        source=ExchangeOffsetSource(rest=rest_clock, clock=clock, probe_coin=_PROBE_COIN, sleeper=deps.sleeper),
        alerts=relay,
    )
    connector = WebsocketsConnector(
        deps.endpoints.ws_url,
        connect_timeout_s=float(config["hl.ws_connect_timeout_s"]),
        max_message_bytes=int(config["hl.ws_max_message_bytes"]),
    )
    hub_connector = BackgroundConnector(connector, name="hub-connect")
    hub = MarketHub(
        connector=hub_connector, clock=clock, max_book_age_ms=config["paper.max_book_age_ms"], seed=secrets.randbits(32)
    )
    clock_worker = BackgroundClock(sync)
    timebase = (
        TimeBase(
            exchange_time=SyncedExchangeTime(sync),
            clock=clock,
            max_offset_uncertainty_ms=sync.max_offset_uncertainty_ms,
            resample=clock_worker,
            live_time_ms=_live_exchange_ms(hub, clock),
        )
        if deps.monotonic_ms is None
        else TimeBase(
            exchange_time=SyncedExchangeTime(sync),
            clock=clock,
            max_offset_uncertainty_ms=sync.max_offset_uncertainty_ms,
            monotonic_ms=deps.monotonic_ms,
            resample=clock_worker,
            live_time_ms=_live_exchange_ms(hub, clock),
        )
    )
    return _Exchange(
        rest=rest,
        rest_clock=rest_clock,
        rest_scoring=_rest_client(config, deps, _FailFastSleeper(), shared, call_limit=trading_sleeper),
        trading_sleeper=trading_sleeper,
        clock_worker=clock_worker,
        access=access,
        schema_monitor=schema_monitor,
        sync=sync,
        timebase=timebase,
        guarded=GuardedExchangeTime(timebase),
        connector=BackgroundConnector(connector, name="feed-connect"),
        hub_connector=hub_connector,
        hub=hub,
        market=RestMarketSource(rest=rest, clock=clock),
        meta=RestMetaSource(rest=rest),
    )


def _assemble(config: Config, secrets_in: Secrets, paths: RunnerPaths, ledger: Ledger, deps: RunnerDeps) -> RunnerParts:
    clock = deps.clock
    gate_lock = threading.RLock()
    relay = AlertRelay()
    run_id = f"r{clock.now_ms()}"
    authority = GateAuthority(deps.gate_key or secrets.token_bytes(32))
    ex = _build_exchange(config, deps, ledger, relay)

    broker = PaperBroker(
        config=config,
        books=ex.hub,
        meta=ex.meta,
        funding=ex.market,
        ledger=ledger,
        clock=clock,
        alerts=relay,
        authority=authority,
    )
    book = PositionBook()
    shares = BookShares(book, gate_lock)
    account = MarkedAccount(
        broker=broker,
        mids=ex.hub.mids,
        mid_time_ms=ex.hub.mid_time_ms,
        clock=clock,
        max_age_ms=config["feed.stale_after_s"] * 1000,
    )
    store = RecordingStore(config=config, clock=clock, ledger=ledger, recordings_dir=paths.recordings_dir)
    candles = CandleStore(
        config=config,
        clock=clock,
        ledger=ledger,
        alerts=relay,
        store=store,
        source=RestCandles(ex.rest),
        open_coins=shares,
    )
    gate = RiskGate(
        config=config,
        broker=broker,
        meta=ex.meta,
        account=account,
        shares=book,
        returns=StoredReturns(get=candles.get, clock=clock),
        exchange_time=ex.guarded,
        calendar=AlwaysAllowCalendar(),
        ledger=ledger,
        alerts=relay,
        authority=authority,
        state_dir=paths.state_dir,
    )

    signals = _LockedSignals(gate_lock)
    detector = SignalDetector(
        config=config, clock=clock, sync=ex.sync, ledger=ledger, sink=cast(SignalSink, signals), alerts=relay
    )
    feed = HlWsFeed(
        config=config,
        clock=clock,
        connector=ex.connector,
        rest=ex.rest,
        rng=random.Random(),  # noqa: S311 - reconnect jitter, not security
        sink=cast(FillSink, detector),
        ledger=LedgerDowntime(ledger),
        alerts=relay,
        schema_monitor=ex.schema_monitor,
    )
    leaderboard_source = HttpLeaderboardSource(
        url=deps.endpoints.leaderboard_url, timeout_s=float(config["hl.rest_timeout_s"]) * _LEADERBOARD_TIMEOUT_FACTOR
    )
    leaderboard = BackgroundLeaderboard(leaderboard_source.fetch, name="follow-leaderboard")
    recorder_leaderboard = BackgroundLeaderboard(leaderboard_source.fetch, name="recorder-leaderboard")
    inputs = PacedInputs(
        Backfiller(config=config, clock=clock, rest=ex.rest_scoring, candles=RestCandles(ex.rest_scoring))
    )
    follow = FollowManager(
        config=config,
        clock=clock,
        ledger=ledger,
        alerts=relay,
        feed=feed,
        registry=detector,
        states=RestLeaderData(ex.rest_scoring, Priority.SCORING),
        shares=shares,
        leaderboard=leaderboard,
        inputs=inputs,
        scores=LedgerScores(ledger),
        costs=ConfigCostModel(config),
    )
    hub_tap = HubTap(ex.hub)
    recorder = Recorder(
        config=config,
        clock=clock,
        ledger=ledger,
        alerts=relay,
        paths=RecorderPaths(
            recordings_dir=paths.recordings_dir, ledger_dir=paths.ledger_dir, cache_dir=paths.cache_dir
        ),
        ports=RecorderPorts(
            feed=hub_tap,
            source=ex.market,
            leaderboard=recorder_leaderboard,
            universe=FollowedUniverse(
                rest=ex.rest,
                clock=clock,
                wallets=lambda: follow.subscribed | shares.wallets(),
                held_coins=lambda: shares.coins() | frozenset(p.coin for p in broker.positions()),
            ),
            disk=deps.disk or SystemDiskProbe(),
            backlog=NoBacklog(),
            identity=deps.identity,
        ),
        store=store,
        registry=WalletRegistry(paths.recordings_dir),
        candles=candles,
    )
    stopping = threading.Event()
    policy = RunnerEntryPolicy(
        follow=follow, feed=feed, recorder=recorder, access=ex.access, is_stopping=stopping.is_set
    )
    leader_data = RestLeaderData(ex.rest, Priority.CRITICAL)
    manager = PositionManager(
        config=config,
        gate=gate,
        broker=broker,
        book=book,
        ledger=ledger,
        alerts=relay,
        exchange_time=ex.guarded,
        candles=candles,
        leader_state=leader_data,
        leader_fills=leader_data,
        policy=policy,
        run_id=run_id,
    )
    signals.bind(manager)
    supervisor = FlattenSupervisor(
        manager=manager,
        alerts=relay,
        now_ms=clock.now_ms,
        held=lambda: bool(broker.positions() or broker.pending_exits() or broker.pending_entries()),
    )
    bot = TelegramBot(
        config=config,
        api=TelegramApi(deps.endpoints.telegram_base_url, cast(SecretValue, secrets_in.telegram_token)),
        gate=gate,
        manager=cast(PositionManager, supervisor),  # the bot only ever calls ``flatten``
        book=book,
        ledger=ledger,
        clock=clock,
        gate_lock=gate_lock,
        pin_hash=secrets_in.telegram_pin_hash,
        pin_salt=secrets_in.telegram_pin_salt,
        run_id=run_id,
    )
    relay.bind(bot)
    return RunnerParts(
        config=config,
        paths=paths,
        run_id=run_id,
        ledger=ledger,
        sync=ex.sync,
        clock_worker=ex.clock_worker,
        follow_leaderboard=leaderboard,
        offthread=(ex.connector, ex.hub_connector, leaderboard, recorder_leaderboard),
        trading_sleeper=ex.trading_sleeper,
        timebase=ex.timebase,
        hub=ex.hub,
        hub_tap=hub_tap,
        meta=ex.meta,
        market=ex.market,
        broker=broker,
        gate=gate,
        book=book,
        manager=manager,
        bot=bot,
        recorder=recorder,
        store=store,
        follow=follow,
        detector=detector,
        feed=feed,
        policy=policy,
        supervisor=supervisor,
        gate_lock=gate_lock,
        inputs=inputs,
        shares=shares,
        account=account,
        relay=relay,
        stopping=stopping,
    )
