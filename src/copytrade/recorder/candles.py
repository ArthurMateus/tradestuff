"""Hourly candle store (F4.AC9): 1m and 1h candles of every coin with an open share, shadow or mirror."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.events import AlertSink
from copytrade.hl.models import Candle
from copytrade.ledger.store import Ledger
from copytrade.recorder.ports import CandleSource, OpenCoinsSource
from copytrade.recorder.store import RecordingStore

HOUR_MS = 3_600_000
ALERT_CANDLES_UNREACHABLE = "candles_unreachable"


class CandleStore:
    """Fetches, stores (through ``RecordingStore``, streams ``candle_1m`` and ``candle_1h``) and serves candles.

    Candle record: ``exchange_ts_ms`` = candle open time, ``receive_ts_ms`` = fetch time, ``source`` = ``"rest"``,
    ``data`` keys ``interval``, ``open_ms``, ``close_ms``, ``open``, ``high``, ``low``, ``close``, ``volume``,
    ``trades``. Files are per coin, interval and UTC hour (each closed with its own ``recording_file_closed``).
    A stored candle (same coin, interval, ``open_ms``) is never replaced or duplicated.
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
        raise NotImplementedError

    def tick(self) -> None:
        """For every UTC hour that has ended and is not yet fetched: for each coin from
        ``open_coins.coins_open_between(hour_start, hour_end)`` fetch that hour's 1m and 1h candles and store them.
        Missing candles and unreachable fetches are retried every ``storage.retry_interval_min`` for up to
        ``eval.missing_data_retry_max_h`` hours after the hour ended, with one ``ALERT_CANDLES_UNREACHABLE`` alert per
        ``storage.alert_interval_h`` while unreachable. Never raises for a source failure."""
        raise NotImplementedError

    def get(self, coin: str, interval: str, start_ms: int, end_ms: int) -> tuple[Candle, ...]:
        """Candles with ``start_ms <= open_ms < end_ms`` for a reader: stored ones as stored, missing ones fetched,
        stored and hashed first. Sorted by ``open_ms``.

        Raises:
            OSError: a needed candle is missing and the source is unreachable.
        """
        raise NotImplementedError
