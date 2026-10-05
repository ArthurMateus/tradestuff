"""Fixtures for the F14 tests (own file): the bot environment is built inside the test body."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest

from tests.telegram.helpers import BotEnv, bot_env

NewBot = Callable[..., BotEnv]


@pytest.fixture
def new_bot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[NewBot]:
    stack = ExitStack()
    count = 0

    def factory(**overrides: Any) -> BotEnv:
        nonlocal count
        count += 1
        sub = tmp_path / f"bot{count}"
        sub.mkdir()
        return stack.enter_context(bot_env(sub, monkeypatch, **overrides))

    yield factory
    stack.close()
