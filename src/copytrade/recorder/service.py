"""The recorder process loop (F4.AC1, AC2, AC5, AC6, AC8, AC9)."""

from __future__ import annotations

import hashlib
import logging
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert, AlertSink
from copytrade.hl.models import L2Book
from copytrade.ledger.store import Ledger
from copytrade.recorder.candles import CandleStore
from copytrade.recorder.identity import ComponentReporter, IdentitySource
from copytrade.recorder.ports import (
    SOURCE_FAILURES,
    BacklogSource,
    DiskProbe,
    FeedEvent,
    LeaderboardSource,
    MarketFeed,
    MarketSource,
    MidsUpdate,
    UniverseSource,
)
from copytrade.recorder.records import (
    STREAM_ASSET_CTX,
    STREAM_FUNDING,
    STREAM_L2,
    STREAM_LEADERBOARD,
    STREAM_MIDS,
    Record,
)
from copytrade.recorder.registry import WalletRegistry, wallets_in_leaderboard
from copytrade.recorder.store import RecordingStore
from copytrade.recorder.universe import select_universe

DISK_LOW = "disk_low"
ALERT_DISK_FREE_LOW = "disk_free_low"
ALERT_DISK_FLOOR = "disk_floor_stopped"
ALERT_LEADERBOARD_MISSING = "leaderboard_missing"
KIND_DOWNTIME = "downtime"
LEADERBOARD_RETRIES = 3
LEADERBOARD_RETRY_DELAY_MS = 300_000  # at most; shortened so that all retries fit inside one snapshot interval
DISK_ALERT_REPEAT_MS = 6 * 3_600_000  # F4.AC5: one low-disk alert per 6 h
HOUR_MS = 3_600_000
_MINUTE_MS = 60_000
# A leaderboard body that cannot be read (not UTF-8, not JSON, no rows) is a failed fetch like any transport error.
_FETCH_FAILURES: tuple[type[Exception], ...] = (*SOURCE_FAILURES, ValueError)
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecorderPaths:
    """The three directories whose volumes the disk guard watches."""

    recordings_dir: Path
    ledger_dir: Path
    cache_dir: Path


@dataclass(frozen=True)
class RecorderPorts:
    feed: MarketFeed
    source: MarketSource
    leaderboard: LeaderboardSource
    universe: UniverseSource
    disk: DiskProbe
    backlog: BacklogSource
    identity: IdentitySource


class Recorder:
    """Drives every recording stream from ``tick()`` (called at least once per second). Never raises for a source
    failure (the stream just has a gap); ledger and disk-write failures propagate (fail closed).

    Records written (stream: data keys; ``receive_ts_ms`` = injected clock at processing):
    - ``l2`` (per coin, ``source="ws"``, ``exchange_ts_ms`` = book time): ``bids`` and ``asks``, each a list of the top
      ``recording.l2_levels`` levels as ``{"px", "sz", "n"}``.
    - ``mids`` (coin ``None``, ``source="ws"``): ``mids`` = ``{coin: px}``.
    - ``asset_ctx`` (per coin, ``source="rest"``, every ``recording.asset_ctx_interval_s``): ``mark``, ``oracle``,
      ``funding``, ``open_interest``.
    - ``funding`` (per coin, ``source="rest"``, hourly, each ``time_ms`` at most once): ``rate``, ``premium``;
      ``exchange_ts_ms`` = the point's time.
    - ``leaderboard`` (coin ``None``, ``source="rest"``, every ``recording.leaderboard_interval_min``): ``status``
      (``"ok"`` or ``"missing"``); for ``ok`` also ``body`` (the JSON text exactly as fetched) and ``sha256`` (hex of
      the body's UTF-8 bytes). A body that is not a UTF-8 leaderboard JSON counts as a failed fetch: it is retried and
      never stored, and the wallet registry is left alone.

    The blocking REST work is spread out: a tick makes at most one funding-history call (one coin), and the leaderboard
    and asset-context fetches are one call each, so the feed is polled again within a few calls' time.

    Disk guard (F4.AC5): every ``recording.disk_check_interval_s`` the free space of the three directories' volumes is
    probed and the smallest figure decides. A probe that fails counts as no free space (A2). Below the floor the
    recorder closes its files, drops what the feed delivers and stops fetching, until the free space reaches floor +
    margin.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        config: Mapping[str, Any],
        clock: Clock,
        ledger: Ledger,
        alerts: AlertSink,
        paths: RecorderPaths,
        ports: RecorderPorts,
        store: RecordingStore,
        registry: WalletRegistry,
        candles: CandleStore | None = None,
    ) -> None:
        self._clock = clock
        self._ledger = ledger
        self._alerts = alerts
        self._paths = paths
        self._ports = ports
        self._store = store
        self._registry = registry
        self._candles = candles
        self._max_coins = int(config["recording.max_coins"])
        self._lookback_days = int(config["recording.universe_lookback_days"])
        self._l2_levels = int(config["recording.l2_levels"])
        self._asset_ctx_ms = int(config["recording.asset_ctx_interval_s"]) * 1000
        self._leaderboard_ms = int(config["recording.leaderboard_interval_min"]) * _MINUTE_MS
        self._disk_check_ms = int(config["recording.disk_check_interval_s"]) * 1000
        self._disk_alert_gb = Decimal(config["recording.disk_alert_free_gb"])
        self._disk_floor_gb = Decimal(config["recording.disk_floor_free_gb"])
        self._disk_resume_gb = self._disk_floor_gb + Decimal(config["recording.disk_resume_margin_gb"])
        self._reporter = ComponentReporter(
            component="recorder",
            source=ports.identity,
            ledger=ledger,
            clock=clock,
            heartbeat_interval_s=int(config["ledger.heartbeat_interval_s"]),
        )
        self._universe: tuple[str, ...] = ()
        self._universe_set: frozenset[str] = frozenset()
        self._recording = True
        self._stopped_since_ms = 0
        self._next_disk_check_ms = 0
        self._last_low_alert_ms: int | None = None
        self._next_ctx_ms: int | None = None
        self._next_funding_cycle_ms: int | None = None
        self._funding_queue: deque[str] = deque()
        self._funding_last: dict[str, int] = {}
        self._board_cycle_ms: int | None = None  # when the current leaderboard snapshot cycle was due
        self._board_next_attempt_ms = 0
        self._board_attempts = 0

    def start(self) -> None:
        """Ledger ``component_start`` (component ``"recorder"``), choose the universe (``select_universe`` with
        ``recording.max_coins``), and subscribe the feed to it."""
        self._reporter.start()
        self.refresh_universe()

    def refresh_universe(self) -> None:
        """Choose the universe again from the universe source and subscribe the feed to it (F21 calls this on its own
        schedule; the universe is otherwise fixed at ``start``)."""
        source = self._ports.universe
        self._universe = select_universe(
            traded_coins=source.traded_coins(self._lookback_days),
            hip3_markets=source.hip3_markets(),
            volume_24h_usd=source.volume_24h_usd(),
            max_coins=self._max_coins,
        )
        self._universe_set = frozenset(self._universe)
        self._ports.feed.subscribe(self._universe)

    def tick(self) -> None:
        now = self._clock.now_ms()
        self._reporter.tick()
        self._check_disk(now)
        events = self._ports.feed.poll()  # always drained, so a stopped recorder does not let the feed pile up
        self._store.tick()
        if not self._recording:
            return
        self._record_events(events, now)
        self._poll_asset_contexts(now)
        self._poll_funding(now)
        self._poll_leaderboard(now)
        if self._candles is not None:
            self._candles.tick()

    @property
    def recording(self) -> bool:
        """False while stopped at the disk floor."""
        return self._recording

    def refusal_reason(self, action: ActionKind) -> str | None:
        """``"disk_low"`` for OPEN and ADD while stopped at the disk floor; ``None`` otherwise (exits never)."""
        if not self._recording and action in (ActionKind.OPEN, ActionKind.ADD):
            return DISK_LOW
        return None

    def shutdown(self) -> None:
        """Close every open file with reason ``shutdown``."""
        self._store.close_all("shutdown")

    # --- the disk guard --------------------------------------------------------------------------------------------

    def _check_disk(self, now: int) -> None:
        if now < self._next_disk_check_ms:
            return
        self._next_disk_check_ms = now + self._disk_check_ms
        free, where = self._smallest_free_gb()
        if free < self._disk_alert_gb and (
            self._last_low_alert_ms is None or now - self._last_low_alert_ms >= DISK_ALERT_REPEAT_MS
        ):
            self._last_low_alert_ms = now
            self._send(ALERT_DISK_FREE_LOW, self._low_disk_message(free, where))
        if self._recording and free < self._disk_floor_gb:
            self._stop(now, free, where)
        elif not self._recording and free >= self._disk_resume_gb:
            self._resume(now)

    def _smallest_free_gb(self) -> tuple[Decimal, Path]:
        """The least free space over the three directories and the directory it is measured on. A probe that raises
        ``OSError`` counts as no free space."""
        smallest: tuple[Decimal, Path] | None = None
        for path in (self._paths.recordings_dir, self._paths.ledger_dir, self._paths.cache_dir):
            try:
                free = self._ports.disk.free_gb(path)
            except OSError as exc:
                _log.error(
                    "free disk space unknown", extra={"event": "disk_probe_failed", "error_type": type(exc).__name__}
                )
                free = Decimal(0)
            if smallest is None or free < smallest[0]:
                smallest = (free, path)
        assert smallest is not None  # noqa: S101 - the tuple above is never empty
        return smallest

    def _low_disk_message(self, free: Decimal, where: Path) -> str:
        try:
            backlog = self._ports.backlog.unarchived_backlog()
            archive = f"{backlog.days} finished day(s), {backlog.gb} GB, not yet archived"
        except SOURCE_FAILURES:
            archive = "the unarchived backlog is unknown"
        return (
            f"Free disk space is {free} GB on the volume of {where} (alert below {self._disk_alert_gb} GB, recording "
            f"stops below {self._disk_floor_gb} GB); {archive}"
        )

    def _stop(self, now: int, free: Decimal, where: Path) -> None:
        self._recording = False
        self._stopped_since_ms = now
        self._send(
            ALERT_DISK_FLOOR,
            f"Free disk space is {free} GB on the volume of {where}, below the floor of {self._disk_floor_gb} GB: "
            "recording stopped, opens and adds are refused (disk_low); exits and the ledger continue",
        )
        self._store.close_all("disk_floor")
        _log.error("recording stopped at the disk floor", extra={"event": "recording_stopped", "free_gb": str(free)})

    def _resume(self, now: int) -> None:
        self._ledger.append(
            KIND_DOWNTIME,
            {"kind": DISK_LOW, "start_ms": self._stopped_since_ms, "end_ms": now, "wallets": []},
        )
        self._recording = True
        _log.warning("recording resumed", extra={"event": "recording_resumed"})

    def _send(self, kind: str, message: str) -> None:
        try:
            self._alerts.send(Alert(kind=kind, message=message))
        except OSError as exc:
            _log.warning(
                "recorder alert delivery failed",
                extra={"event": "recorder_alert_failed", "error_type": type(exc).__name__},
            )

    # --- the streams -----------------------------------------------------------------------------------------------

    def _record_events(self, events: Sequence[FeedEvent], now: int) -> None:
        for event in events:
            if isinstance(event, L2Book):
                self._store.append(self._l2_record(event, now))
            elif isinstance(event, MidsUpdate):
                self._store.append(Record(STREAM_MIDS, None, event.time_ms, now, "ws", {"mids": dict(event.mids)}))

    def _l2_record(self, book: L2Book, now: int) -> Record:
        depth = self._l2_levels
        return Record(
            STREAM_L2,
            book.coin,
            book.time_ms,
            now,
            "ws",
            {
                "bids": [{"px": level.px, "sz": level.sz, "n": level.n} for level in book.bids[:depth]],
                "asks": [{"px": level.px, "sz": level.sz, "n": level.n} for level in book.asks[:depth]],
            },
        )

    def _poll_asset_contexts(self, now: int) -> None:
        if self._next_ctx_ms is not None and now < self._next_ctx_ms:
            return
        self._next_ctx_ms = _next_due(self._next_ctx_ms, self._asset_ctx_ms, now)
        try:
            contexts = self._ports.source.asset_contexts()
        except SOURCE_FAILURES as exc:
            _log.warning(
                "asset contexts unavailable", extra={"event": "asset_ctx_failed", "error_type": type(exc).__name__}
            )
            return
        received = self._clock.now_ms()
        for ctx in contexts:
            if ctx.coin in self._universe_set:
                data = {
                    "mark": ctx.mark,
                    "oracle": ctx.oracle,
                    "funding": ctx.funding,
                    "open_interest": ctx.open_interest,
                }
                self._store.append(Record(STREAM_ASSET_CTX, ctx.coin, ctx.time_ms, received, "rest", data))

    def _poll_funding(self, now: int) -> None:
        if self._next_funding_cycle_ms is None or now >= self._next_funding_cycle_ms:
            self._next_funding_cycle_ms = _next_due(self._next_funding_cycle_ms, HOUR_MS, now)
            self._funding_queue = deque(self._universe)
        if not self._funding_queue:
            return
        coin = self._funding_queue.popleft()
        last = self._funding_last.get(coin)
        if last is None:
            earlier = self._store.as_of(STREAM_FUNDING, coin, now)
            last = None if earlier is None else earlier.exchange_ts_ms
        start_ms = last if last is not None else (now // HOUR_MS - 1) * HOUR_MS
        try:
            points = self._ports.source.funding_history(coin, start_ms)
        except SOURCE_FAILURES as exc:
            _log.warning(
                "funding history unavailable", extra={"event": "funding_failed", "error_type": type(exc).__name__}
            )
            return
        received = self._clock.now_ms()
        for point in sorted(points, key=lambda p: p.time_ms):
            if point.coin == coin and (last is None or point.time_ms > last):
                data = {"rate": point.rate, "premium": point.premium}
                self._store.append(Record(STREAM_FUNDING, coin, point.time_ms, received, "rest", data))
                last = point.time_ms
        if last is not None:
            self._funding_last[coin] = last

    def _poll_leaderboard(self, now: int) -> None:
        if self._board_cycle_ms is None:
            self._board_cycle_ms = self._board_next_attempt_ms = now
        if now < self._board_next_attempt_ms:
            return
        try:
            body = self._ports.leaderboard.fetch()
            wallets = wallets_in_leaderboard(body)
            text = body.decode("utf-8")
        except _FETCH_FAILURES as exc:
            _log.warning(
                "leaderboard fetch failed", extra={"event": "leaderboard_failed", "error_type": type(exc).__name__}
            )
            self._leaderboard_failed(now)
            return
        received = self._clock.now_ms()
        data = {"status": "ok", "body": text, "sha256": hashlib.sha256(body).hexdigest()}
        self._store.append(Record(STREAM_LEADERBOARD, None, None, received, "rest", data))
        self._registry.add(wallets)
        self._next_board_cycle(now)

    def _leaderboard_failed(self, now: int) -> None:
        self._board_attempts += 1
        if self._board_attempts <= LEADERBOARD_RETRIES:
            delay_ms = min(LEADERBOARD_RETRY_DELAY_MS, self._leaderboard_ms // (LEADERBOARD_RETRIES + 1))
            self._board_next_attempt_ms = now + delay_ms
            return
        self._store.append(Record(STREAM_LEADERBOARD, None, None, now, "rest", {"status": "missing"}))
        self._send(
            ALERT_LEADERBOARD_MISSING,
            f"The leaderboard snapshot is missing: {LEADERBOARD_RETRIES + 1} attempts failed; the next one is due "
            "in the next interval",
        )
        self._next_board_cycle(now)

    def _next_board_cycle(self, now: int) -> None:
        """The snapshot cycle is over (stored or missing): the next one is due one interval after this one was."""
        assert self._board_cycle_ms is not None  # noqa: S101 - set on the first poll
        self._board_cycle_ms = _next_due(self._board_cycle_ms, self._leaderboard_ms, now)
        self._board_next_attempt_ms = self._board_cycle_ms
        self._board_attempts = 0


def _next_due(previous_due_ms: int | None, interval_ms: int, now: int) -> int:
    """The next time of a fixed-rate schedule after ``previous_due_ms`` (``None``: the first run, now); a schedule that
    fell behind by more than an interval restarts from now instead of firing in a burst."""
    if previous_due_ms is None:
        return now + interval_ms
    following = previous_due_ms + interval_ms
    return following if following > now else now + interval_ms
