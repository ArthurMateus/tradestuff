"""Fixtures for the R0 tests: a factory that builds the loopback world inside the test body."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest

from tests.runner.world import World, world_ctx

NewWorld = Callable[..., World]


@pytest.fixture
def new_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[NewWorld]:
    stack = ExitStack()
    count = 0

    def factory(**config: Any) -> World:
        nonlocal count
        count += 1
        sub = tmp_path / f"w{count}"
        sub.mkdir()
        return stack.enter_context(world_ctx(sub, monkeypatch, **config))

    yield factory
    stack.close()
