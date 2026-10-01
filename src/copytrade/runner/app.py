"""What ``copytrade run`` does."""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from types import FrameType
from typing import TextIO

from copytrade.core.errors import CopytradeError
from copytrade.runner.deps import RunnerDeps, production_deps
from copytrade.runner.wiring import build_runner


def _stop_signals() -> list[signal.Signals]:
    names = ("SIGINT", "SIGTERM", "SIGBREAK")  # SIGBREAK is the Windows console's Ctrl+Break
    return [getattr(signal, name) for name in names if hasattr(signal, name)]


def _install_stop_handlers(event: threading.Event) -> Callable[[], None]:
    """Make Ctrl+C / SIGTERM / Ctrl+Break set ``event``; return the function that restores the previous handlers."""

    def handler(_number: int, _frame: FrameType | None) -> None:
        event.set()

    previous: dict[signal.Signals, object] = {}
    for number in _stop_signals():
        try:
            previous[number] = signal.signal(number, handler)
        except ValueError:  # not the main thread: the caller owns the stop event then
            break

    def restore() -> None:
        for number, old in previous.items():
            signal.signal(number, old)  # type: ignore[arg-type]

    return restore


def run_app(  # noqa: PLR0913 - the pinned R0 signature
    root: Path,
    env: Mapping[str, str],
    *,
    deps: RunnerDeps | None,
    stop: threading.Event | None,
    out: TextIO,
    err: TextIO,
) -> int:
    """Build the runner and run it until ``stop`` is set (``None``: Ctrl+C / SIGTERM / SIGBREAK set an internal one).
    ``deps=None`` means ``production_deps(root)``. Exit codes: 0 clean stop; 1 any ``CopytradeError`` (one line on
    ``err``: ``copytrade: <message>``, never a secret); the mode refusal is the F1 ``ModeNotPermittedError`` message."""
    restore: Callable[[], None] | None = None
    try:
        runner = build_runner(root, env, deps if deps is not None else production_deps(root))
        event = stop if stop is not None else threading.Event()
        if stop is None:
            restore = _install_stop_handlers(event)
        print("copytrade: running in paper mode; press Ctrl+C to stop", file=out, flush=True)
        code = runner.run(event)
    except (CopytradeError, OSError) as error:
        print(f"copytrade: {error}", file=err, flush=True)
        return 1
    finally:
        if restore is not None:
            restore()
    print("copytrade: stopped cleanly", file=out, flush=True)
    return code
