"""Fixtures for the R0 tests: a factory that builds the loopback world inside the test body."""

from __future__ import annotations

import ctypes
import faulthandler
import threading
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


# ---------------------------------------------------------------------------------------------- per-test timeout
RUNNER_TEST_TIMEOUT_S = 150  # the slowest runner test takes well under 30 s; a hung one (a socket, a loop) must fail fast


class RunnerTestTimeout(BaseException):
    """Raised in the main thread when a runner test runs longer than ``RUNNER_TEST_TIMEOUT_S`` (BaseException so that
    no ``except Exception`` of the code under test swallows it; pytest reports it as a failure of that one test)."""


@pytest.fixture(autouse=True)
def _runner_test_timeout() -> Iterator[None]:
    """Stdlib only (pytest-timeout is not a dependency): a timer thread injects ``RunnerTestTimeout`` into the main
    thread (works on Windows; there is no SIGALRM there); ``faulthandler`` aborts the process if even that cannot
    unblock a call stuck in the OS, so a hung test can never block the run for 20 minutes."""
    main_id = threading.main_thread().ident
    assert main_id is not None

    def fire() -> None:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(main_id), ctypes.py_object(RunnerTestTimeout))

    timer = threading.Timer(RUNNER_TEST_TIMEOUT_S, fire)
    timer.daemon = True
    timer.start()
    faulthandler.dump_traceback_later(RUNNER_TEST_TIMEOUT_S + 60, exit=True)
    try:
        yield
    finally:
        timer.cancel()
        faulthandler.cancel_dump_traceback_later()
