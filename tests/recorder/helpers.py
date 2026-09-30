"""Test doubles and builders for the F4 tests. Only external boundaries are faked: the local clock, the market
feed, the REST-style sources, the disk probe, the archive backlog, the identity source and the alert sink. The real
F2 ledger, the real F1 config loader, the real recording store and the real recorder run in every test.

Nothing here re-implements the unit under test. Nothing sleeps: tests step a fake clock.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.clock import TimeSource, Timestamp  # noqa: F401  (re-exported for tests)
from copytrade.core.money import Price, Qty
from copytrade.hl.models import BookLevel, Candle, L2Book
from copytrade.ledger.records import LedgerRecord
from copytrade.ledger.store import Ledger
from copytrade.recorder.candles import CandleStore
from copytrade.recorder.identity import ComponentIdentity
from copytrade.recorder.ports import (
    AssetContext,
    Backlog,
    FeedEvent,
    FundingPoint,
)
from copytrade.recorder.records import STREAM_L2, Record
from copytrade.recorder.registry import WalletRegistry
from copytrade.recorder.service import Recorder, RecorderPaths, RecorderPorts
from copytrade.recorder.store import RecordingStore
from tests.hl.support import FakeClock, RecordingAlerts, make_config

SECOND = 1_000
MINUTE = 60_000
HOUR = 3_600_000
DAY = 86_400_000
DAY0 = 1_790_035_200_000  # 2026-09-22T00:00:00Z
DAY0_ISO = "2026-09-22"
DAY1_ISO = "2026-09-23"

__all__ = ["DAY", "DAY0", "HOUR", "MINUTE", "SECOND", "FakeClock", "RecordingAlerts", "make_config"]


def cfg(**overrides: Any) -> Any:
    """The valid fixture config (real F1 loader) with dotted keys written with ``__`` for ``.``."""
    return make_config(**overrides)


def level(px: str, sz: str = "1.5", n: int = 2) -> BookLevel:
    return BookLevel(px=Price(px), sz=Qty(sz), n=n)


def book(coin: str, time_ms: int, *, mid: int = 100, levels: int = 3) -> L2Book:
    bids = tuple(level(str(mid - 1 - i), "1.25", 1 + i) for i in range(levels))
    asks = tuple(level(str(mid + 1 + i), "2.5", 1 + i) for i in range(levels))
    return L2Book(coin=coin, time_ms=time_ms, bids=bids, asks=asks)


def l2_record(coin: str, t_ms: int, *, exchange_ms: int | None = None, mid: int = 100) -> Record:
    return Record(
        stream=STREAM_L2,
        coin=coin,
        exchange_ts_ms=t_ms - 40 if exchange_ms is None else exchange_ms,
        receive_ts_ms=t_ms,
        source="ws",
        data={
            "bids": [{"px": Decimal(mid - 1), "sz": Decimal("1.25"), "n": 1}],
            "asks": [{"px": Decimal(mid + 1), "sz": Decimal("2.5"), "n": 2}],
        },
    )


def stream_records(
    stream: str, coin: str | None, times: Iterable[int], *, source: str = "ws", data: Mapping[str, Any] | None = None
) -> list[Record]:
    return [
        Record(
            stream=stream,
            coin=coin,
            exchange_ts_ms=t - 30,
            receive_ts_ms=t,
            source=source,
            data=dict(data if data is not None else {"i": i}),
        )
        for i, t in enumerate(times)
    ]


# --------------------------------------------------------------------------------------------------
# Boundaries
# --------------------------------------------------------------------------------------------------


class FakeFeed:
    """MarketFeed double. ``script`` maps a poll time (ms) to the events to deliver at that time or later."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.subscribed: list[tuple[str, ...]] = []
        self.pending: list[tuple[int, FeedEvent]] = []
        self.generator: Callable[[int], Sequence[FeedEvent]] | None = None

    def subscribe(self, coins: Sequence[str]) -> None:
        self.subscribed.append(tuple(coins))

    def push(self, event: FeedEvent, at_ms: int | None = None) -> None:
        self.pending.append((self.clock.now_ms() if at_ms is None else at_ms, event))

    def poll(self) -> Sequence[FeedEvent]:
        now = self.clock.now_ms()
        out: list[FeedEvent] = [e for t, e in self.pending if t <= now]
        self.pending = [(t, e) for t, e in self.pending if t > now]
        if self.generator is not None:
            out.extend(self.generator(now))
        return out


class FakeMarketSource:
    def __init__(self, clock: FakeClock, coins: Sequence[str] = ("BTC", "ETH", "SOL")) -> None:
        self.clock = clock
        self.coins = tuple(coins)
        self.down = False
        self.ctx_calls: list[int] = []
        self.funding_calls: list[tuple[str, int]] = []

    def asset_contexts(self) -> Sequence[AssetContext]:
        self.ctx_calls.append(self.clock.now_ms())
        if self.down:
            raise OSError("market source down")
        t = self.clock.now_ms()
        return [
            AssetContext(
                coin=c,
                mark=Price("100.5"),
                oracle=Price("100.25"),
                funding=Decimal("0.0000125"),
                open_interest=Qty("1234.5"),
                time_ms=t,
            )
            for c in self.coins
        ]

    def funding_history(self, coin: str, start_ms: int) -> Sequence[FundingPoint]:
        self.funding_calls.append((coin, start_ms))
        if self.down:
            raise OSError("market source down")
        hour = (self.clock.now_ms() // HOUR) * HOUR
        return [
            FundingPoint(coin=coin, time_ms=t, rate=Decimal("0.0000125"), premium=Decimal("0.0001"))
            for t in range(max(start_ms, hour - 2 * HOUR), hour + 1, HOUR)
        ]


class FakeLeaderboard:
    def __init__(self, clock: FakeClock, body: bytes | None = None) -> None:
        self.clock = clock
        self.body: bytes = body if body is not None else leaderboard_body(["0x" + "a" * 40])
        self.fail_next = 0
        self.fail_always = False
        self.calls: list[int] = []
        self.invalid_body: bytes | None = None

    def fetch(self) -> bytes:
        self.calls.append(self.clock.now_ms())
        if self.fail_always:
            raise OSError("leaderboard down")
        if self.fail_next > 0:
            self.fail_next -= 1
            raise TimeoutError("leaderboard timeout")
        return self.invalid_body if self.invalid_body is not None else self.body


def leaderboard_body(wallets: Sequence[str], *, extra: str = "") -> bytes:
    """A leaderboard JSON shaped like the (synthetic, NEEDS RECORDING) fixture, one row per wallet."""
    rows = ",".join(
        '{"ethAddress":"%s","accountValue":"%d.50","windowPerformances":[["day",{"pnl":"1.5","roi":"0.01","vlm":"10"}]],'
        '"prize":0,"displayName":null}' % (w, 1000 + i)
        for i, w in enumerate(wallets)
    )
    return ('{"leaderboardRows":[%s]%s}' % (rows, extra)).encode("utf-8")


class FakeUniverse:
    def __init__(
        self,
        traded: Iterable[str] = ("BTC", "ETH", "SOL", "DOGE"),
        hip3: Iterable[str] = ("xyz:AAPL",),
        volume: Mapping[str, Decimal] | None = None,
    ) -> None:
        self.traded = frozenset(traded)
        self.hip3 = tuple(hip3)
        self.volume: Mapping[str, Decimal] = volume or {}
        self.lookbacks: list[int] = []

    def traded_coins(self, lookback_days: int) -> frozenset[str]:
        self.lookbacks.append(lookback_days)
        return self.traded

    def hip3_markets(self) -> Sequence[str]:
        return self.hip3

    def volume_24h_usd(self) -> Mapping[str, Decimal]:
        return self.volume


class FakeDisk:
    """DiskProbe double: free GB per directory (by path), with a default for unlisted paths."""

    def __init__(self, default: str = "500") -> None:
        self.default = Decimal(default)
        self.by_path: dict[Path, Decimal] = {}
        self.probed: list[Path] = []

    def set(self, path: Path | None, gb: str) -> None:
        if path is None:
            self.default = Decimal(gb)
            self.by_path.clear()
        else:
            self.by_path[path] = Decimal(gb)

    def free_gb(self, path: Path) -> Decimal:
        self.probed.append(path)
        return self.by_path.get(path, self.default)


class FakeBacklog:
    def __init__(self, days: int = 2, gb: str = "3.5") -> None:
        self.value = Backlog(days=days, gb=Decimal(gb))

    def unarchived_backlog(self) -> Backlog:
        return self.value


@dataclass
class FakeIdentity:
    ident: ComponentIdentity

    def identity(self) -> ComponentIdentity:
        return self.ident


def make_identity(
    *, worktree: str = "/wt/run", commit: str = "a" * 40, dirty: bool = False, lock: str = "b" * 64, pkgs: str = "c" * 64
) -> ComponentIdentity:
    return ComponentIdentity(
        worktree=worktree,
        commit=commit,
        dirty=dirty,
        lockfile_sha256=lock,
        python_version="3.11.15",
        packages_sha256=pkgs,
    )


class FakeCandleSource:
    """CandleSource double: 60 one-minute candles per hour and one hourly candle, for any coin."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.down = False
        self.calls: list[tuple[int, str, str, int, int]] = []
        self.drop_open_ms: set[int] = set()  # minutes the exchange "does not have yet"
        self.close_bias = Decimal("0")

    def fetch(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Sequence[Candle]:
        self.calls.append((self.clock.now_ms(), coin, interval, start_ms, end_ms))
        if self.down:
            raise OSError("candle endpoint unreachable")
        step = MINUTE if interval == "1m" else HOUR
        out = []
        t = (start_ms // step) * step
        while t < end_ms:
            if t >= start_ms and t not in self.drop_open_ms:
                out.append(
                    Candle(
                        open_ms=t,
                        close_ms=t + step - 1,
                        coin=coin,
                        interval=interval,
                        open=Price("100"),
                        high=Price("101"),
                        low=Price("99"),
                        close=Price(Decimal("100.5") + self.close_bias),
                        volume=Qty("12.5"),
                        trades=7,
                    )
                )
            t += step
        return out


class FakeOpenCoins:
    """OpenCoinsSource double over ``(coin, open_ms, close_ms)`` intervals."""

    def __init__(self, intervals: Sequence[tuple[str, int, int]] = ()) -> None:
        self.intervals = list(intervals)

    def coins_open_between(self, start_ms: int, end_ms: int) -> frozenset[str]:
        return frozenset(c for c, a, b in self.intervals if a < end_ms and b > start_ms)


# --------------------------------------------------------------------------------------------------
# Wiring of the real objects around the fakes
# --------------------------------------------------------------------------------------------------


@dataclass
class Rig:
    cfg: Any
    clock: FakeClock
    alerts: RecordingAlerts
    ledger: Ledger
    store: RecordingStore
    registry: WalletRegistry
    feed: FakeFeed
    source: FakeMarketSource
    leaderboard: FakeLeaderboard
    universe: FakeUniverse
    disk: FakeDisk
    backlog: FakeBacklog
    identity: FakeIdentity
    paths: RecorderPaths
    recorder: Recorder
    candle_source: FakeCandleSource
    open_coins: FakeOpenCoins
    candles: CandleStore

    def run(self, seconds: int, *, each: Callable[[], None] | None = None) -> None:
        for _ in range(seconds):
            self.clock.advance(SECOND)
            if each is not None:
                each()
            self.recorder.tick()

    def ledger_of(self, kind: str) -> list[LedgerRecord]:
        return [r for r in self.ledger.records() if r.kind == kind]


def make_rig(base: Path, *, start_ms: int = DAY0, started: bool = True, **overrides: Any) -> Rig:
    config = cfg(**overrides)
    clock = FakeClock(start_ms)
    alerts = RecordingAlerts()
    ledger = Ledger.open(base / "ledger", clock=clock)
    recordings = base / "recordings"
    store = RecordingStore(config=config, clock=clock, ledger=ledger, recordings_dir=recordings)
    registry = WalletRegistry(base / "registry")
    feed = FakeFeed(clock)
    source = FakeMarketSource(clock)
    leaderboard = FakeLeaderboard(clock)
    universe = FakeUniverse()
    disk = FakeDisk()
    backlog = FakeBacklog()
    identity = FakeIdentity(make_identity())
    paths = RecorderPaths(recordings_dir=recordings, ledger_dir=base / "ledger", cache_dir=base / "cache")
    candle_source = FakeCandleSource(clock)
    open_coins = FakeOpenCoins()
    candles = CandleStore(
        config=config,
        clock=clock,
        ledger=ledger,
        alerts=alerts,
        store=store,
        source=candle_source,
        open_coins=open_coins,
    )
    recorder = Recorder(
        config=config,
        clock=clock,
        ledger=ledger,
        alerts=alerts,
        paths=paths,
        ports=RecorderPorts(
            feed=feed,
            source=source,
            leaderboard=leaderboard,
            universe=universe,
            disk=disk,
            backlog=backlog,
            identity=identity,
        ),
        store=store,
        registry=registry,
        candles=candles,
    )
    rig = Rig(
        config, clock, alerts, ledger, store, registry, feed, source, leaderboard, universe, disk, backlog, identity,
        paths, recorder, candle_source, open_coins, candles,
    )  # fmt: skip
    if started:
        recorder.start()
    return rig


def seeded(seed: int = 7) -> random.Random:
    return random.Random(seed)


# --------------------------------------------------------------------------------------------------
# A bare store (no recorder), for the storage-format tests
# --------------------------------------------------------------------------------------------------


@dataclass
class StoreRig:
    cfg: Any
    clock: FakeClock
    ledger: Ledger
    store: RecordingStore
    recordings_dir: Path
    ledger_dir: Path

    def put(self, records: Iterable[Record]) -> None:
        """Move the clock to each record's receive time, ``tick``, then append it (the order the recorder uses)."""
        for r in records:
            if r.receive_ts_ms > self.clock.now_ms():
                self.clock.now = r.receive_ts_ms
            self.store.tick()  # a segment due at this instant is sealed before this record is written
            self.store.append(r)

    def advance_to(self, t_ms: int, *, step_ms: int = SECOND) -> None:
        while self.clock.now_ms() < t_ms:
            self.clock.advance(min(step_ms, t_ms - self.clock.now_ms()))
            self.store.tick()

    def closed(self) -> list[Mapping[str, Any]]:
        return [r.payload for r in self.ledger.records() if r.kind == "recording_file_closed"]

    def of_kind(self, kind: str) -> list[LedgerRecord]:
        return [r for r in self.ledger.records() if r.kind == kind]


def make_store(base: Path, *, start_ms: int = DAY0, compression_level: int | None = None, **overrides: Any) -> StoreRig:
    config = cfg(**overrides)
    clock = FakeClock(start_ms)
    ledger_dir = base / "ledger"
    ledger = Ledger.open(ledger_dir, clock=clock)
    recordings_dir = base / "recordings"
    store = RecordingStore(
        config=config, clock=clock, ledger=ledger, recordings_dir=recordings_dir, compression_level=compression_level
    )
    return StoreRig(config, clock, ledger, store, recordings_dir, ledger_dir)


def final_files(recordings_dir: Path) -> list[Path]:
    """Files with a final name: everything that is not an open ``.part`` / ``.tmp`` file."""
    if not recordings_dir.exists():
        return []
    return sorted(p for p in recordings_dir.rglob("*") if p.is_file() and p.suffix not in (".part", ".tmp"))


def open_files(recordings_dir: Path) -> list[Path]:
    if not recordings_dir.exists():
        return []
    return sorted(p for p in recordings_dir.rglob("*") if p.is_file() and p.suffix in (".part", ".tmp"))


def spawn_worker(mode: str, base: Path) -> Any:
    """Start ``tests.recorder._worker`` in a real subprocess and wait for its ``ready`` line."""
    import os
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo_root / "src"), str(repo_root)])
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "tests.recorder._worker", mode, str(base)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=repo_root,
        env=env,
    )
    assert proc.stdout is not None and proc.stderr is not None
    line = proc.stdout.readline().strip()
    if line != "ready":
        proc.kill()
        proc.wait()
        raise AssertionError(f"worker did not start; stderr:\n{proc.stderr.read()[-2000:]}")
    return proc
