"""What ``copytrade run`` does."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from copytrade.runner.deps import RunnerDeps


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
    raise NotImplementedError
