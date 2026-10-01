"""F14 test rig: the REAL gate, paper broker, ledger, book and position manager (tests/positions rig) plus a loopback
fake of the Telegram server. The bot is imported and built inside the factory so a missing module fails the test itself.
"""

from __future__ import annotations

import hashlib
import importlib
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from copytrade.core.secrets import SecretValue
from tests.harness import CANARY_SECRETS
from tests.paper.helpers import FakeClock
from tests.positions.helpers import Rig, build_rig
from tests.telegram.fake_server import FakeTelegram

TOKEN = CANARY_SECRETS["COPYTRADE_TELEGRAM_TOKEN"]
PIN = "482915"
WRONG_PIN = "000111"
SALT = "salt-for-the-f14-tests"
PIN_ITERATIONS = 200_000  # pinned: PBKDF2-HMAC-SHA256, salt and PIN as UTF-8, hex digest
PIN_HASH = hashlib.pbkdf2_hmac("sha256", PIN.encode(), SALT.encode(), PIN_ITERATIONS).hex()

OWNER = 111111111  # telegram.allowed_user_id == telegram.control_chat_id in the fixture config
ALERTS_CHAT = -1001111111111
MIN_MS = 60_000
START_MS = 1_800_000_000_000


def tg(name: str) -> Any:
    """``copytrade.telegram.<name>``, imported inside the test so a missing module fails that test."""
    return importlib.import_module(f"copytrade.telegram.{name}")


class SpyLock:
    """The supervisor's one gate lock (R0 contract RISK-25). Counts how often it was taken."""

    def __init__(self) -> None:
        self.entered = 0
        self.depth = 0

    def __enter__(self) -> None:
        self.entered += 1
        self.depth += 1

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.depth -= 1


@dataclass
class BotEnv:
    rig: Rig
    server: FakeTelegram
    bot: Any
    clock: FakeClock
    lock: SpyLock
    base_url: str

    def pump(self) -> None:
        """One supervisor tick of the Telegram side: take commands, sync trade posts, deliver what is due."""
        self.bot.poll_once()
        self.bot.sync_posts()
        self.bot.flush()

    def command(self, text: str, **kw: Any) -> int:
        message_id = self.server.push_text(text, **kw)
        self.pump()
        return message_id

    def advance(self, ms: int) -> None:
        self.clock.now += ms

    def audits(self) -> list[dict[str, Any]]:
        return self.rig.records("telegram_audit")


def make_api(base_url: str, **kw: Any) -> Any:
    return tg("api").TelegramApi(base_url, SecretValue(TOKEN), **kw)


def make_bot(rig: Rig, base_url: str, clock: FakeClock, lock: SpyLock, **kw: Any) -> Any:
    api = make_api(base_url, timeout_s=kw.pop("timeout_s", 0.5))
    return tg("bot").TelegramBot(
        config=rig.config, api=api, gate=rig.gate, manager=rig.mgr, book=rig.book, ledger=rig.env.ledger,
        clock=clock, gate_lock=lock, run_id="run1",
        pin_hash=kw.pop("pin_hash", SecretValue(PIN_HASH)), pin_salt=kw.pop("pin_salt", SecretValue(SALT)), **kw,
    )


@contextmanager
def bot_env(tmp_path: Path, monkeypatch: Any, **overrides: Any) -> Iterator[BotEnv]:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    prime = bool(overrides.pop("prime", True))  # True: one start-up poll on an empty server (the backlog drain)
    server = FakeTelegram(token=TOKEN)
    base_url = server.start()
    rig = build_rig(tmp_path, **overrides)
    clock, lock = FakeClock(START_MS), SpyLock()
    server.date_fn = lambda: clock.now // 1000  # a message pushed "now" is dated by the bot's clock
    try:
        env = BotEnv(rig, server, make_bot(rig, base_url, clock, lock), clock, lock, base_url)
        if prime:
            env.bot.poll_once()
        yield env
    finally:
        server.stop()
        rig.env.ledger.close()


__all__ = ["PIN_HASH", "ALERTS_CHAT", "MIN_MS", "OWNER", "PIN", "SALT", "TOKEN", "WRONG_PIN", "BotEnv", "Rig", "bot_env",
           "make_api", "make_bot", "tempfile", "tg"]
