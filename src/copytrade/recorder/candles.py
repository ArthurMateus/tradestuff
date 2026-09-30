"""Hourly candle store (F4.AC9): 1m and 1h candles of every coin with an open share, shadow or mirror."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.events import Alert, AlertSink
from copytrade.core.money import Price, Qty
from copytrade.hl.errors import HlError
from copytrade.hl.models import Candle
from copytrade.ledger.store import Ledger
from copytrade.recorder.ports import SOURCE_FAILURES, CandleSource, OpenCoinsSource
from copytrade.recorder.records import STREAM_CANDLE_1H, STREAM_CANDLE_1M, Record
from copytrade.recorder.store import FileKey, RecordingIntegrityError, RecordingStore

HOUR_MS = 3_600_000
MINUTE_MS = 60_000
ALERT_CANDLES_UNREACHABLE = "candles_unreachable"
KIND_CANDLES_ABANDONED = "candles_abandoned"

_INTERVALS: tuple[tuple[str, str, int], ...] = (
    ("1m", STREAM_CANDLE_1M, MINUTE_MS),
    ("1h", STREAM_CANDLE_1H, HOUR_MS),
)
_STEP_BY_INTERVAL = {interval: (stream, step) for interval, stream, step in _INTERVALS}
_log = logging.getLogger(__name__)


@dataclass
class _Job:
    """One coin's candles for one closed hour, until they are all stored or the retry window has passed."""

    coin: str
    hour_ms: int
    deadline_ms: int
    next_at_ms: int = 0


class CandleStore:
    """Fetches, stores (through ``RecordingStore``, streams ``candle_1m`` and ``candle_1h``) and serves candles.

    Candle record: ``exchange_ts_ms`` = candle open time, ``receive_ts_ms`` = fetch time, ``source`` = ``"rest"``,
    ``data`` keys ``interval``, ``open_ms``, ``close_ms``, ``open``, ``high``, ``low``, ``close``, ``volume``,
    ``trades``. Files are per coin, interval and UTC hour (each closed with its own ``recording_file_closed``).
    A stored candle (same coin, interval, ``open_ms``) is never replaced or duplicated, and a candle that has not closed
    yet is never stored (it would be frozen half-formed).

    What is stored is the only state: which hours are done is read from the store, so a restart repeats nothing. A job
    that is still incomplete when its retry window ends is dropped with a ``candles_abandoned`` ledger record naming
    what is missing (F12.AC9 treats such a cost as uncomputable).

    Order of work. A tick serves the oldest hour that has a job due, all its coins, then returns, so a backlog is worked
    off one hour per tick and never starves the recorder's own streams for long. While the source is unreachable nothing
    is tried until ``storage.retry_interval_min`` after the last failure, and then the oldest hour is tried first, so
    the hours are stored in order once it is back. An hour that is only incomplete (the source answered without every
    candle) is retried on its own schedule and blocks nothing.

    The source is called from ``tick`` and ``get``, so a slow source blocks the caller: F21's adapter must bound each
    call.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        config: Mapping[str, Any],
        clock: Clock,
        ledger: Ledger,
        alerts: AlertSink,
        store: RecordingStore,
        source: CandleSource,
        open_coins: OpenCoinsSource,
    ) -> None:
        self._retry_ms = int(config["storage.retry_interval_min"]) * MINUTE_MS
        self._alert_interval_ms = int(config["storage.alert_interval_h"]) * HOUR_MS
        self._window_ms = int(config["eval.missing_data_retry_max_h"]) * HOUR_MS
        self._clock = clock
        self._ledger = ledger
        self._alerts = alerts
        self._store = store
        self._source = source
        self._open_coins = open_coins
        self._next_hour_ms: int | None = None  # the first UTC hour not yet turned into jobs
        self._jobs: dict[tuple[str, int], _Job] = {}
        self._retry_at_ms = 0  # no fetch before this time (set by an unreachable source)
        self._last_alert_ms: int | None = None
        self._absent: dict[tuple[str, str, int], int] = {}  # a candle the exchange did not have -> ask again after

    def tick(self) -> None:
        """For every UTC hour that has ended and is not yet fetched: for each coin from
        ``open_coins.coins_open_between(hour_start, hour_end)`` fetch that hour's 1m and 1h candles and store them.
        Missing candles and unreachable fetches are retried every ``storage.retry_interval_min`` for up to
        ``eval.missing_data_retry_max_h`` hours after the hour ended, with one ``ALERT_CANDLES_UNREACHABLE`` alert per
        ``storage.alert_interval_h`` while unreachable. Never raises for a source failure."""
        now = self._clock.now_ms()
        self._schedule_ended_hours(now)
        for job in [job for job in self._jobs.values() if now > job.deadline_ms]:
            self._abandon(job, now)
        if now < self._retry_at_ms:
            return
        due = [job for job in self._jobs.values() if now >= job.next_at_ms]
        if not due:
            return
        oldest = min(job.hour_ms for job in due)
        for job in sorted((job for job in due if job.hour_ms == oldest), key=lambda job: job.coin):
            if not self._attempt(job, now):
                break

    def get(self, coin: str, interval: str, start_ms: int, end_ms: int) -> tuple[Candle, ...]:
        """Candles with ``start_ms <= open_ms < end_ms`` for a reader: stored ones as stored, missing ones fetched,
        stored and hashed first. Sorted by ``open_ms``.

        A candle that has not closed yet (only when the range reaches past now) is returned as fetched but not stored.

        Raises:
            ValueError: ``interval`` is not ``"1m"`` or ``"1h"``.
            OSError: a needed candle is missing and the source is unreachable.
        """
        if interval not in _STEP_BY_INTERVAL:
            raise ValueError("interval must be '1m' or '1h'")
        stream, step = _STEP_BY_INTERVAL[interval]
        wanted = range(-(-start_ms // step) * step, end_ms, step)
        found = self._stored(coin, stream, {opened - opened % HOUR_MS for opened in wanted})
        now = self._clock.now_ms()
        missing = [o for o in wanted if o not in found and self._absent.get((coin, interval, o), 0) <= now]
        unstored: dict[int, Candle] = {}
        if missing:
            fetched = self._fetch(coin, interval, missing[0], missing[-1] + step - 1)
            unstored = self._store_closed(coin, interval, fetched, set(missing))
            found.update(self._stored(coin, stream, {opened - opened % HOUR_MS for opened in missing}))
            now = self._clock.now_ms()
            for opened in missing:
                if opened not in found and opened not in unstored:
                    self._absent[(coin, interval, opened)] = now + self._retry_ms
        candles = {**{opened: _to_candle(record) for opened, record in found.items()}, **unstored}
        return tuple(candles[opened] for opened in sorted(candles) if start_ms <= opened < end_ms)

    # --- hourly jobs -----------------------------------------------------------------------------------------------

    def _schedule_ended_hours(self, now: int) -> None:
        if self._next_hour_ms is None:
            self._next_hour_ms = (now - self._window_ms) // HOUR_MS * HOUR_MS
        while self._next_hour_ms + HOUR_MS <= now:
            hour = self._next_hour_ms
            self._next_hour_ms += HOUR_MS
            deadline = hour + HOUR_MS + self._window_ms
            if now <= deadline:
                for coin in sorted(self._open_coins.coins_open_between(hour, hour + HOUR_MS)):
                    self._jobs[(coin, hour)] = _Job(coin, hour, deadline)

    def _attempt(self, job: _Job, now: int) -> bool:
        """Fetch what the store lacks for this job. Returns ``False`` when the source was unreachable."""
        for interval, stream, step in _INTERVALS:
            missing = self._missing_in_hour(job.coin, stream, job.hour_ms, step)
            if not missing:
                continue
            try:
                fetched = self._source.fetch(job.coin, interval, job.hour_ms, job.hour_ms + HOUR_MS - 1)
            except SOURCE_FAILURES as exc:
                _log.warning(
                    "candle fetch failed",
                    extra={"event": "candle_fetch_failed", "error_type": type(exc).__name__},
                )
                self._alert_unreachable(job, interval)
                self._retry_at_ms = now + self._retry_ms
                return False
            self._store_closed(job.coin, interval, fetched, missing)
        if any(self._missing_in_hour(job.coin, stream, job.hour_ms, step) for _, stream, step in _INTERVALS):
            job.next_at_ms = now + self._retry_ms
        else:
            del self._jobs[(job.coin, job.hour_ms)]
        return True

    def _abandon(self, job: _Job, now: int) -> None:
        del self._jobs[(job.coin, job.hour_ms)]
        for interval, stream, step in _INTERVALS:
            missing = self._missing_in_hour(job.coin, stream, job.hour_ms, step)
            if missing:
                self._ledger.append(
                    KIND_CANDLES_ABANDONED,
                    {
                        "coin": job.coin,
                        "interval": interval,
                        "hour_ms": job.hour_ms,
                        "missing": sorted(missing),
                        "abandoned_at_ms": now,
                    },
                )

    def _alert_unreachable(self, job: _Job, interval: str) -> None:
        now = self._clock.now_ms()
        if self._last_alert_ms is not None and now - self._last_alert_ms < self._alert_interval_ms:
            return
        message = (
            f"The candle endpoint is unreachable ({job.coin} {interval}, hour starting {job.hour_ms}); retrying every "
            f"{self._retry_ms // MINUTE_MS} min. Recording of everything else continues."
        )
        try:
            self._alerts.send(Alert(kind=ALERT_CANDLES_UNREACHABLE, message=message))
        except OSError as exc:
            _log.warning(
                "candle alert delivery failed",
                extra={"event": "candle_alert_failed", "error_type": type(exc).__name__},
            )
            return
        self._last_alert_ms = now

    # --- the store -------------------------------------------------------------------------------------------------

    def _stored(self, coin: str, stream: str, hours: Iterable[int]) -> dict[int, Record]:
        """The stored candle records of these hours by candle open time."""
        found: dict[int, Record] = {}
        for hour in sorted(set(hours)):
            for record in self._store.scan_hour(stream, coin, hour):
                if record.exchange_ts_ms is not None:
                    found.setdefault(record.exchange_ts_ms, record)
        return found

    def _missing_in_hour(self, coin: str, stream: str, hour_ms: int, step_ms: int) -> set[int]:
        stored = self._stored(coin, stream, [hour_ms])
        return {opened for opened in range(hour_ms, hour_ms + HOUR_MS, step_ms) if opened not in stored}

    def _fetch(self, coin: str, interval: str, start_ms: int, end_ms: int) -> tuple[Candle, ...]:
        try:
            return tuple(self._source.fetch(coin, interval, start_ms, end_ms))
        except HlError as exc:
            raise OSError("the candle source failed") from exc

    def _store_closed(self, coin: str, interval: str, candles: Iterable[Candle], wanted: set[int]) -> dict[int, Candle]:
        """Store the closed candles among ``candles`` that are ``wanted`` (not stored yet) and close their files.
        Returns the wanted candles that were not stored because they have not closed yet."""
        stream = _STEP_BY_INTERVAL[interval][0]
        now = self._clock.now_ms()
        keys: dict[FileKey, None] = {}
        forming: dict[int, Candle] = {}
        stored: set[int] = set()
        for candle in candles:
            if candle.coin != coin or candle.interval != interval or candle.open_ms not in wanted:
                continue
            if candle.close_ms >= now:
                forming.setdefault(candle.open_ms, candle)
            elif candle.open_ms not in stored:
                stored.add(candle.open_ms)
                keys[self._store.append(_to_record(stream, candle, now))] = None
        self._store.close_files(keys, "normal")
        return forming


def _to_record(stream: str, candle: Candle, fetched_ms: int) -> Record:
    return Record(
        stream=stream,
        coin=candle.coin,
        exchange_ts_ms=candle.open_ms,
        receive_ts_ms=fetched_ms,
        source="rest",
        data={
            "interval": candle.interval,
            "open_ms": candle.open_ms,
            "close_ms": candle.close_ms,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "trades": candle.trades,
        },
    )


def _to_candle(record: Record) -> Candle:
    data = record.data
    if record.coin is None:
        raise RecordingIntegrityError("a stored candle has no coin")
    return Candle(
        open_ms=data["open_ms"],
        close_ms=data["close_ms"],
        coin=record.coin,
        interval=data["interval"],
        open=Price(data["open"]),
        high=Price(data["high"]),
        low=Price(data["low"]),
        close=Price(data["close"]),
        volume=Qty(data["volume"]),
        trades=data["trades"],
    )
