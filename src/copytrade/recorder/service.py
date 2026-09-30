"""The recorder process loop (F4.AC1, AC2, AC5, AC6, AC8, AC9)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.domain import ActionKind
from copytrade.core.events import AlertSink
from copytrade.ledger.store import Ledger
from copytrade.recorder.candles import CandleStore
from copytrade.recorder.identity import IdentitySource
from copytrade.recorder.ports import (
    BacklogSource,
    DiskProbe,
    LeaderboardSource,
    MarketFeed,
    MarketSource,
    UniverseSource,
)
from copytrade.recorder.registry import WalletRegistry
from copytrade.recorder.store import RecordingStore

DISK_LOW = "disk_low"
ALERT_DISK_FREE_LOW = "disk_free_low"
ALERT_DISK_FLOOR = "disk_floor_stopped"
ALERT_LEADERBOARD_MISSING = "leaderboard_missing"
KIND_DOWNTIME = "downtime"
LEADERBOARD_RETRIES = 3


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
      the body's UTF-8 bytes).
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
        raise NotImplementedError

    def start(self) -> None:
        """Ledger ``component_start`` (component ``"recorder"``), choose the universe (``select_universe`` with
        ``recording.max_coins``), and subscribe the feed to it."""
        raise NotImplementedError

    def tick(self) -> None:
        raise NotImplementedError

    @property
    def recording(self) -> bool:
        """False while stopped at the disk floor."""
        raise NotImplementedError

    def refusal_reason(self, action: ActionKind) -> str | None:
        """``"disk_low"`` for OPEN and ADD while stopped at the disk floor; ``None`` otherwise (exits never)."""
        raise NotImplementedError

    def shutdown(self) -> None:
        """Close every open file with reason ``shutdown``."""
        raise NotImplementedError
