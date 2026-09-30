"""Latency measurement mode (F7.AC6): record stages S1 and S2 per signal without trading."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from copytrade.core.clock import Clock, ClockSync
from copytrade.core.events import AlertSink
from copytrade.hl.budget import Sleeper
from copytrade.hl.rest import HttpTransport
from copytrade.hl.ws import WsConnector
from copytrade.ledger.store import Ledger


@dataclass(frozen=True)
class StageSummary:
    """Nearest-rank percentiles of one stage over ``count`` samples, in whole milliseconds."""

    count: int
    p50_ms: int
    p95_ms: int
    p99_ms: int


@dataclass(frozen=True)
class LatencyReport:
    """``s1`` is leader fill to WebSocket receive (the signal's ``age_ms``); ``s2`` is receive to classified. Both are
    ``None`` when no signal had that stage. ``enough_samples`` is ``signals >= latency.min_signals``."""

    hours: int
    wallets: tuple[str, ...]
    started_ms: int
    ended_ms: int
    signals: int
    s1: StageSummary | None
    s2: StageSummary | None
    enough_samples: bool


@dataclass(frozen=True)
class LatencyBoundaries:
    """The external boundaries of a measurement run (the CLI builds the real ones; tests inject fakes)."""

    clock: Clock
    sleeper: Sleeper
    connector: WsConnector
    transport: HttpTransport
    rng: random.Random
    sync: ClockSync


def percentile(values: Sequence[int], q: int) -> int:
    """Nearest-rank percentile: the value at 1-based rank ``ceil(q / 100 * n)`` of the sorted values.

    Raises:
        ValueError: ``values`` is empty or ``q`` is outside 1..100.
    """
    raise NotImplementedError


def measure_latency(  # noqa: PLR0913
    *,
    hours: int,
    wallets: Sequence[str],
    config: Mapping[str, Any],
    boundaries: LatencyBoundaries,
    ledger: Ledger,
    alerts: AlertSink,
) -> LatencyReport:
    """Follow ``wallets`` (fetching each one's ``clearinghouseState`` first), run the real feed and detector until
    ``hours`` hours of the boundary clock have passed (one tick per second, sleeping through
    ``boundaries.sleeper``), and
    ledger one ``latency_sample`` record per signal (``signal_id``, ``wallet``, ``coin``, ``s1_ms`` = ``age_ms``,
    ``s2_ms``, ``exchange_ts_ms``, ``receive_ts_ms``) besides the detector's own ``signal`` records.

    Nothing is traded: no decision, fill, trade or order record is written and no module of F9 to F12 is used.

    Raises:
        ValueError: ``hours`` is not positive, or ``wallets`` is empty, has an invalid address, or has more than
            ``hl.ws_max_unique_users`` distinct wallets.
    """
    raise NotImplementedError
