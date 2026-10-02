"""The R0 test world: the REAL runner (real gate, paper broker, ledger, recorder, F3 feed, F6, F7, F12 and F14 bot)
over loopback fakes of Hyperliquid and Telegram. Faked: Hyperliquid and Telegram (real sockets, 127.0.0.1), the local
clock, the sleeper, the disk probe and the recorder's identity source. Nothing here re-implements the unit under test.

Time: ``clock`` is the LOCAL clock; the fake exchange is ``clock + offset_ms``. ``step`` moves the clock, pushes fresh
market frames and calls ``Runner.step`` on the test (trading) thread.
"""

from __future__ import annotations

import dataclasses
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copytrade.ledger.store import Ledger
from copytrade.runner.deps import RunnerDeps
from copytrade.runner.endpoints import Endpoints
from copytrade.runner.runner import Runner, StartReport
from copytrade.runner.wiring import build_runner
from tests.core.helpers import ConfigTree, make_root, same_kind
from tests.hl.support import T0, FakeClock, FakeSleeper
from tests.hl.ws_server import wait_for
from tests.recorder.helpers import FakeDisk, FakeIdentity, make_identity
from tests.runner.fake_hl import FakeHl, fill_json
from tests.telegram.fake_server import FakeTelegram
from tests.telegram.helpers import PIN, PIN_HASH, SALT, TOKEN

LEADER = "0x" + "a" * 40
LEADER_B = "0x" + "b" * 40
OWNER = 111111111
ALERTS_CHAT = -1001111111111
SECRETS = {"token": TOKEN, "pin_hash": PIN_HASH, "salt": SALT}

__all__ = ["ALERTS_CHAT", "LEADER", "LEADER_B", "OWNER", "PIN", "SECRETS", "T0", "World", "world_ctx"]


def secret_leaks(text: str) -> list[str]:
    """Names of the secrets that appear in ``text`` (the whole value, or any 12-character piece of the token)."""
    from tests.harness import canary_fragments

    found = []
    for name, value in SECRETS.items():
        if value in text or (name == "token" and any(f in text for f in canary_fragments(value))):
            found.append(name)
    return found


@dataclass
class World:
    base: Path
    clock: FakeClock
    hl: FakeHl
    tg: FakeTelegram
    disk: FakeDisk
    tree: ConfigTree
    offset_ms: int = 0
    wall_skew_ms: int = 0  # how far the LOCAL WALL clock was stepped away from the monotonic one (see ``step_wall``)
    _poll_base: int = 0
    runners: list[Runner] = field(default_factory=list)
    root: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    _tg_url: str = ""

    # ------------------------------------------------------------------------------------------ configuration
    def exchange_ms(self) -> int:
        """The true exchange time: the monotonic timeline plus ``offset_ms`` (a wall-clock step does not move it)."""
        return self.mono_ms() + self.offset_ms

    def mono_ms(self) -> int:
        """The injected monotonic clock: follows ``clock`` except for the steps made with ``step_wall``."""
        return self.clock.now - self.wall_skew_ms

    def step_wall(self, ms: int) -> None:
        """Windows steps the local WALL clock by ``ms`` (negative: back) while the monotonic clock and the exchange
        carry on: every offset estimate taken before the step is now wrong by ``ms``."""
        self.clock.advance(ms)
        self.wall_skew_ms += ms

    @property
    def sample_bias_ms(self) -> int:
        return self.hl.book_time_bias_ms

    @sample_bias_ms.setter
    def sample_bias_ms(self, value: int) -> None:
        self.hl.book_time_bias_ms = value

    def configure(self, **overrides: Any) -> None:
        """Set config keys (dots written as ``__``) before the root is written (or call ``write_config`` after)."""
        for key, value in overrides.items():
            dotted = key.replace("__", ".")
            self.tree.set(dotted, same_kind(self.tree.get(dotted), value))

    def write_config(self) -> Path:
        fake = make_root(self.base / "rootdir", self.tree)
        self.root = fake.root
        return fake.root

    def data(self, name: str) -> Path:
        return self.base / "data" / name

    @property
    def ledger_dir(self) -> Path:
        return self.data("ledger")

    @property
    def state_dir(self) -> Path:
        return self.data("state")

    @property
    def recordings_dir(self) -> Path:
        return self.data("recordings")

    def endpoints(self) -> Endpoints:
        return Endpoints(
            info_url=self.hl.info_url,
            ws_url=self.hl.ws_url,
            leaderboard_url=self.hl.leaderboard_url,
            telegram_base_url=self._tg_url,
        )

    def deps(self, **over: Any) -> RunnerDeps:
        values: dict[str, Any] = {
            "clock": self.clock,
            "sleeper": FakeSleeper(self.clock),
            "endpoints": self.endpoints(),
            "identity": FakeIdentity(make_identity()),
            "disk": self.disk,
            "thread_pause_s": 0.01,
            "gate_key": None,
        }
        if "monotonic_ms" in {f.name for f in dataclasses.fields(RunnerDeps)}:  # R0 fix round: always inject (drop the guard)
            values["monotonic_ms"] = self.mono_ms
        values.update(over)
        return RunnerDeps(**values)

    # ------------------------------------------------------------------------------------------ building
    def build(self, *, env: dict[str, str] | None = None, **deps_over: Any) -> Runner:
        root = self.root or self.write_config()
        self._poll_base = len(self.tg.calls("getUpdates"))
        runner = build_runner(root, self.env if env is None else env, self.deps(**deps_over))
        self.runners.append(runner)
        return runner

    def start(self, **deps_over: Any) -> tuple[Runner, StartReport]:
        runner = self.build(**deps_over)
        return runner, runner.start()

    # ------------------------------------------------------------------------------------------ driving
    def pump_market(self, coins: tuple[str, ...] = ("SOL",)) -> None:
        for coin in coins:
            self.hl.push_l2(coin, self.exchange_ms())
        self.hl.push_mids()

    def step(self, runner: Runner, n: int = 1, ms: int = 1000, *, pump: bool = True) -> Any:
        report = None
        for _ in range(n):
            self.clock.advance(ms)
            if pump:
                self.pump_market()
            report = runner.step()
            time.sleep(0.012)  # real sockets deliver asynchronously: a fake WebSocket frame takes 5-11 ms (books lag ~3 steps at 2 ms)
        return report

    def run_until(self, runner: Runner, cond: Callable[[], Any], *, max_steps: int = 400, ms: int = 200) -> Any:
        for _ in range(max_steps):
            value = cond()
            if value:
                return value
            self.step(runner, 1, ms)
        value = cond()
        assert value, "the condition did not become true within the step budget"
        return value

    def wait_text(self, needle: str, *, chat: int | None = None) -> None:
        wait_for(lambda: any(needle in t for t in self.tg.sent(chat)), what=f"a Telegram message containing {needle!r}")

    def telegram_ready(self) -> None:
        """The CURRENT runner's poll thread has completed its first (backlog-draining) poll: a second getUpdates request
        of this run has arrived (counted above the number received before the runner was built, so an earlier run's
        polls do not count)."""
        wait_for(lambda: len(self.tg.calls("getUpdates")) >= self._poll_base + 2, what="the first Telegram poll of this run")

    # ------------------------------------------------------------------------------------------ the ledger
    def seed_ledger(self, records: list[tuple[Any, ...]]) -> None:
        """Append ``(kind, payload[, client_order_id])`` records to the (closed) ledger before a runner is built."""
        ledger = Ledger.open(self.ledger_dir, clock=self.clock)
        try:
            for kind, payload, *cid in records:
                ledger.append(kind, payload, client_order_id=cid[0] if cid else None)
        finally:
            ledger.close()

    def seed_follow(self, wallet: str = LEADER) -> None:
        """What an earlier run left behind: the wallet is followed (F6 cycle record + F7 follow record). The wallet
        also traded SOL two days ago (exchange history), so SOL is in the recording universe and its books are live."""
        self.hl.leader_fills.setdefault(wallet.lower(), []).append(
            fill_json(
                8_000_000, coin="SOL", side="B", sz="1.0", px="100.0", direction="Open Long",
                time_ms=T0 - 2 * 86_400_000,
            )
        )
        self.seed_ledger(
            [
                ("follow_started", {"wallet": wallet, "followed_at_ms": T0 - 3_600_000, "held": []}),
                (
                    "select_cycle",
                    {
                        "t_ms": T0 - 3_600_000,
                        "status": "applied",
                        "eligible_count": 1,
                        "followed": [wallet],
                        "decisions": [{"kind": "join", "wallet": wallet, "replaces": None, "reason": None}],
                    },
                ),
            ]
        )

    def records(self, kind: str | None = None, *, directory: Path | None = None) -> list[Any]:
        """Ledger records read lock-free (works while a runner holds the ledger)."""
        from copytrade.ledger.store import read_records

        return [r for r in read_records(directory or self.ledger_dir) if kind is None or r.kind == kind]

    def ledger_text(self) -> str:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in self.ledger_dir.rglob("*") if p.is_file())

    # ------------------------------------------------------------------------------------------ scenarios
    def subscribe_ready(self, runner: Runner, wallet: str = LEADER) -> None:
        self.run_until(runner, lambda: self.hl.user_subscribed(wallet))

    def leader_open(self, runner: Runner, *, wallet: str = LEADER, coin: str = "SOL", tid: int = 1, long: bool = True) -> None:
        """The leader opens 5 SOL at 100 (a WebSocket fill); our paper entry fills one ack delay later."""
        self.subscribe_ready(runner, wallet)
        szi = "5.0" if long else "-5.0"
        self.hl.leader_positions[wallet.lower()] = [(coin, szi, "100.0")]
        fill = fill_json(
            tid, coin=coin, side="B" if long else "A", sz="5.0", px="100.0",
            direction="Open Long" if long else "Open Short", time_ms=self.exchange_ms() - 200,
        )
        self.hl.push_user_fills(wallet, [fill])
        self.run_until(runner, lambda: runner.broker.position(coin) is not None)

    def leader_close(self, *, wallet: str = LEADER, coin: str = "SOL", tid: int = 2, long: bool = True) -> None:
        """The leader's full close arrives (a WebSocket fill). The caller steps afterwards."""
        self.hl.leader_positions[wallet.lower()] = []
        fill = fill_json(
            tid, coin=coin, side="A" if long else "B", sz="5.0", px="100.0",
            direction="Close Long" if long else "Close Short", time_ms=self.exchange_ms() - 100,
            start_position="5.0" if long else "-5.0",
        )
        self.hl.push_user_fills(wallet, [fill])

    def hard_kill(self, runner: Runner) -> None:
        """What kill -9 leaves behind: the ledger and state directories exactly as they are NOW; nothing the clean
        stop would add (final checkpoint, runner_stop) survives."""
        snap = self.base / "killed"
        shutil.rmtree(snap, ignore_errors=True)
        shutil.copytree(self.ledger_dir, snap / "ledger", ignore=shutil.ignore_patterns("*.lock"))
        if self.state_dir.exists():
            shutil.copytree(self.state_dir, snap / "state")
        runner.stop()
        shutil.rmtree(self.ledger_dir)
        shutil.copytree(snap / "ledger", self.ledger_dir)
        if (snap / "state").exists():
            shutil.rmtree(self.state_dir, ignore_errors=True)
            shutil.copytree(snap / "state", self.state_dir)

    def alert_kinds_sent(self) -> str:
        return "\n".join(self.tg.sent(ALERTS_CHAT))

    def close(self) -> None:
        for runner in self.runners:
            try:
                runner.stop()
            except Exception:
                pass


@contextmanager
def world_ctx(base: Path, monkeypatch: Any, **config: Any) -> Iterator[World]:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    clock = FakeClock(T0)
    holder: dict[str, World] = {}
    hl = FakeHl(exchange_ms=lambda: holder["w"].exchange_ms()).start()
    tg = FakeTelegram(token=TOKEN)
    tg_url = tg.start()
    tg.date_fn = lambda: clock.now // 1000
    tree = ConfigTree()
    data = base / "data"
    tree.set("storage.ledger_dir", str(data / "ledger"))
    tree.set("storage.recordings_dir", str(data / "recordings"))
    tree.set("storage.cache_dir", str(data / "cache"))
    world = World(base=base, clock=clock, hl=hl, tg=tg, disk=FakeDisk("500"), tree=tree)
    world._tg_url = tg_url
    world.env = {
        "COPYTRADE_TELEGRAM_TOKEN": TOKEN,
        "COPYTRADE_TELEGRAM_PIN_HASH": PIN_HASH,
        "COPYTRADE_TELEGRAM_PIN_SALT": SALT,
    }
    holder["w"] = world
    world.configure(**config)
    try:
        yield world
    finally:
        world.close()
        hl.stop()
        tg.stop()

