"""Latency measurement mode (F7.AC6): record stages S1 and S2 per signal without trading."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from copytrade.core.clock import Clock, ClockSync
from copytrade.core.events import AlertSink
from copytrade.hl.access import AccessMonitor
from copytrade.hl.budget import Priority, RateBudget, Sleeper
from copytrade.hl.errors import HlRequestError
from copytrade.hl.ledger_port import DowntimeRecord
from copytrade.hl.rest import HlRestClient, HttpTransport
from copytrade.hl.schema import SchemaFailureMonitor
from copytrade.hl.wallet import normalize_wallet
from copytrade.hl.ws import HlWsFeed, WsConnector
from copytrade.ledger.store import Ledger
from copytrade.signals.detector import SignalDetector
from copytrade.signals.models import KIND_LATENCY_SAMPLE, Signal

KIND_DOWNTIME = "downtime"
# How often the run polls the feed. The feed's ``recv`` never blocks, so a signal is timestamped when the next poll
# drains it, so S1 is an upper bound (up to this interval too high). The interval is a floor on that error
# (target p50 700 ms) and is kept well below it. The feed itself only needs one tick per second.
TICK_INTERVAL_S = 0.1
_MS_PER_HOUR = 3_600_000


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
    if not values:
        raise ValueError("percentile of no values")
    if type(q) is not int or not 1 <= q <= 100:
        raise ValueError("q must be an int from 1 to 100")
    ordered = sorted(values)
    return ordered[-(-q * len(ordered) // 100) - 1]


def _summarise(values: Sequence[int]) -> StageSummary | None:
    if not values:
        return None
    return StageSummary(
        count=len(values), p50_ms=percentile(values, 50), p95_ms=percentile(values, 95), p99_ms=percentile(values, 99)
    )


class _LedgerDowntime:
    """Ledgers the feed's and the access monitor's downtime intervals (kind ``downtime``)."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def record_downtime(self, record: DowntimeRecord) -> None:
        self._ledger.append(
            KIND_DOWNTIME,
            {
                "kind": record.kind,
                "start_ms": record.start_ms,
                "end_ms": record.end_ms,
                "wallets": list(record.wallets),
            },
        )


class _SampleRecorder:
    """The signal consumer of a measurement run: one ``latency_sample`` record per signal, and nothing else."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger
        self.signals = 0
        self.s1_ms: list[int] = []
        self.s2_ms: list[int] = []

    def on_signals(self, signals: Sequence[Signal]) -> None:
        for signal in signals:
            self._ledger.append(
                KIND_LATENCY_SAMPLE,
                {
                    "signal_id": signal.signal_id,
                    "wallet": signal.wallet,
                    "coin": signal.coin,
                    "s1_ms": signal.age_ms,
                    "s2_ms": signal.s2_ms,
                    "exchange_ts_ms": signal.exchange_ts.ms,
                    "receive_ts_ms": signal.receive_ts.ms,
                },
            )
            self.signals += 1
            self.s2_ms.append(signal.s2_ms)
            if signal.age_ms is not None:
                self.s1_ms.append(signal.age_ms)


def _distinct_wallets(wallets: Sequence[str], limit: int) -> tuple[str, ...]:
    distinct: dict[str, None] = {}
    for wallet in wallets:
        try:
            distinct[normalize_wallet(wallet)] = None
        except HlRequestError as exc:
            raise ValueError("a wallet is not a 0x address of 40 hex digits") from exc
    if not distinct:
        raise ValueError("at least one wallet is required")
    if len(distinct) > limit:
        raise ValueError(f"at most {limit} distinct wallets can be followed (hl.ws_max_unique_users)")
    return tuple(distinct)


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
    ``hours`` hours of the boundary clock have passed (polling every ``TICK_INTERVAL_S``, sleeping through
    ``boundaries.sleeper``), and ledger one ``latency_sample`` record per signal (``signal_id``, ``wallet``,
    ``coin``, ``s1_ms`` = ``age_ms``, ``s2_ms``, ``exchange_ts_ms``, ``receive_ts_ms``) besides the detector's own
    ``signal`` records.

    A wallet that the ledger already follows (an earlier, interrupted run over the same ledger) is re-followed from
    the state fetched now. Fills whose ``tid`` the ledger already holds are duplicates and are not sampled again.

    Nothing is traded: no decision, fill, trade or order record is written and no module of F9 to F12 is used.

    Raises:
        ValueError: ``hours`` is not positive, or ``wallets`` is empty, has an invalid address, or has more than
            ``hl.ws_max_unique_users`` distinct wallets. Raised before any request, sleep or ledger write.
        CopytradeError: a request failed for good, or the ledger could not be written.
    """
    if type(hours) is not int or hours <= 0:
        raise ValueError("hours must be a positive int")
    followed = _distinct_wallets(wallets, int(config["hl.ws_max_unique_users"]))

    clock = boundaries.clock
    started_ms = clock.now_ms()
    recorder = _SampleRecorder(ledger)
    downtime = _LedgerDowntime(ledger)
    schema_monitor = SchemaFailureMonitor(clock=clock, alerts=alerts)
    access = AccessMonitor(config=config, clock=clock, alerts=alerts, ledger=downtime)
    rest = HlRestClient(
        config=config,
        clock=clock,
        transport=boundaries.transport,
        sleeper=boundaries.sleeper,
        rng=boundaries.rng,
        budget=RateBudget(
            budget_per_min=int(config["hl.rest_weight_budget_per_min"]),
            scoring_share=config["hl.scoring_weight_share"],
            clock=clock,
        ),
        access=access,
        schema_monitor=schema_monitor,
    )
    detector = SignalDetector(
        config=config, clock=clock, sync=boundaries.sync, ledger=ledger, sink=recorder, alerts=alerts
    )
    feed = HlWsFeed(
        config=config,
        clock=clock,
        connector=boundaries.connector,
        rest=rest,
        rng=boundaries.rng,
        sink=detector,
        ledger=downtime,
        alerts=alerts,
        schema_monitor=schema_monitor,
    )
    for wallet in followed:
        state = rest.clearinghouse_state(wallet, priority=Priority.CRITICAL)
        detector.end_follow(wallet)
        detector.begin_follow(wallet, state, clock.now_ms())
        feed.subscribe_user(wallet)

    end_ms = started_ms + hours * _MS_PER_HOUR
    while True:
        boundaries.sync.tick()
        feed.tick()
        access.tick()
        remaining_ms = end_ms - clock.now_ms()
        if remaining_ms <= 0:
            break
        boundaries.sleeper.sleep(min(TICK_INTERVAL_S, remaining_ms / 1000))

    return LatencyReport(
        hours=hours,
        wallets=followed,
        started_ms=started_ms,
        ended_ms=clock.now_ms(),
        signals=recorder.signals,
        s1=_summarise(recorder.s1_ms),
        s2=_summarise(recorder.s2_ms),
        enough_samples=recorder.signals >= int(config["latency.min_signals"]),
    )
