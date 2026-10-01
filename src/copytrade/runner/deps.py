"""The true external boundaries of the runner, injected so tests can run it on loopback with a fake clock."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from copytrade.core.clock import Clock, SystemClock
from copytrade.hl.budget import Sleeper
from copytrade.recorder.identity import IdentitySource, SystemIdentitySource
from copytrade.recorder.ports import DiskProbe
from copytrade.runner.endpoints import Endpoints, mainnet_endpoints

DEFAULT_THREAD_PAUSE_S = 0.5


@dataclass(frozen=True)
class RunnerDeps:
    """``clock``: the local clock. ``sleeper``: used by the REST client's backoff. ``identity``: the recorder's
    identity source. ``disk``: ``None`` means the real ``SystemDiskProbe``. ``thread_pause_s``: idle time between two
    iterations of the Telegram poll thread, the flush thread and the watchdog thread (real seconds).
    ``gate_key``: ``None`` means a fresh random 32-byte key per process (old tokens can never replay); a test passes
    a fixed key only to prove that a different key rejects old tokens. ``monotonic_ms``: the monotonic clock behind
    broker time (``None`` means ``time.monotonic_ns() // 1_000_000``); a test injects one it can move apart from the
    wall
    clock."""

    clock: Clock
    sleeper: Sleeper
    endpoints: Endpoints
    identity: IdentitySource
    disk: DiskProbe | None
    thread_pause_s: float
    gate_key: bytes | None
    monotonic_ms: Callable[[], int] | None = None


class _RealSleeper:
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def production_deps(root: Path) -> RunnerDeps:
    """SystemClock, a real ``time.sleep`` sleeper, mainnet endpoints, ``SystemIdentitySource(root)``, the real disk
    probe, ``DEFAULT_THREAD_PAUSE_S`` and a per-process random gate key."""
    return RunnerDeps(
        clock=SystemClock(),
        sleeper=_RealSleeper(),
        endpoints=mainnet_endpoints(),
        identity=SystemIdentitySource(root),
        disk=None,
        thread_pause_s=DEFAULT_THREAD_PAUSE_S,
        gate_key=secrets.token_bytes(32),
    )
