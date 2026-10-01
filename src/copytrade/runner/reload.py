"""Startup reload (the minimal slice of F13): rebuild state from the ledger and flag anything uncertain.

The ledger is the source of truth (A7). The broker's books are replayed from it record by record
(``paper.restore.replay_broker``); the position manager's, the gate's and the follow manager's memory comes from the
latest ``runner_checkpoint`` record plus the ledger records of the F6/F7 follow state. Whatever the two sources
disagree on, or cannot prove, becomes an ``Uncertainty``: one ``startup_uncertain`` alert each, the persisted pause
(``RiskGate.pause``) and ``entries_blocked`` until the PO acknowledges with ``/resume``. Positions, stops and exits are
never dropped or blocked because of an uncertainty.
"""

from __future__ import annotations

import contextlib
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copytrade.core.errors import CopytradeError
from copytrade.core.events import Alert, AlertSink
from copytrade.ledger.records import LedgerRecord
from copytrade.ledger.store import Ledger
from copytrade.paper.broker import PaperBroker
from copytrade.paper.restore import BROKER_STATE_KINDS, BrokerSnapshot, replay_broker
from copytrade.paper.settings import PaperSettings
from copytrade.paper.types import CoinMeta
from copytrade.positions.book import PositionBook
from copytrade.positions.manager import PositionManager
from copytrade.positions.types import CLOSED, OPEN
from copytrade.risk.errors import RiskStateError
from copytrade.risk.gate import RiskGate
from copytrade.selection.manager import FollowManager
from copytrade.selection.models import Follow

# Uncertain-state codes (``Uncertainty.code``). Each one raises a Telegram alert of kind ``startup_uncertain`` and
# pauses new entries (``RiskGate.pause``, persisted) until the PO acknowledges with ``/resume``.
POSITION_WITHOUT_SHARE = "position_without_share"
SHARE_WITHOUT_POSITION = "share_without_position"
UNKNOWN_COIN = "unknown_coin"
EXIT_STATE_UNPROVEN = "exit_state_unproven"
MISSING_RISK_STATE_FILE = "missing_risk_state_file"
CHECKPOINT_BEHIND_LEDGER = "checkpoint_behind_ledger"
ALERT_STARTUP_UNCERTAIN = "startup_uncertain"
KIND_CHECKPOINT = "runner_checkpoint"
KIND_RUNNER_START = "runner_start"
KIND_RUNNER_STOP = "runner_stop"

TID_WINDOW_MS = 72 * 3_600_000  # leader fills older than this are never re-read by a reconciliation or audit
ORDER_WINDOW_MS = 120_000  # recent paper orders handed to the gate (its window is one minute)
_ORDER_TIMES_KEPT = 1_000
_STATE_KINDS = BROKER_STATE_KINDS | {"share_state"}


@dataclass(frozen=True)
class Uncertainty:
    """One thing the reload could not prove. ``detail`` names the coin / share id / client order id, never a secret."""

    code: str
    detail: str


@dataclass(frozen=True)
class Requeued:
    """A pending exit re-queued under a NEW client order id (the old id stays in the ledger, so reusing it would be
    refused ``duplicate_client_order_id``)."""

    old_client_order_id: str
    new_client_order_id: str
    share_id: str


@dataclass
class LedgerScan:
    """Everything one pass over the ledger yields. ``tail_state_records`` counts the broker/manager state records
    written after the last checkpoint (the checkpoint is behind the ledger when that is not zero)."""

    snapshot: BrokerSnapshot | None = None
    checkpoint: Mapping[str, Any] | None = None
    tail_state_records: int = 0
    had_previous_run: bool = False
    followed: tuple[str, ...] = ()
    follow_started: dict[str, int] = field(default_factory=dict)
    paused: set[str] = field(default_factory=set)
    order_times: deque[int] = field(default_factory=lambda: deque(maxlen=_ORDER_TIMES_KEPT))
    signal_tids: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))
    last_seq: int = 0

    def observe(self, record: LedgerRecord, *, tid_floor_ms: int) -> None:
        kind, payload = record.kind, record.payload
        self.last_seq = record.seq
        if kind == KIND_CHECKPOINT:
            self.checkpoint, self.tail_state_records = payload, 0
        elif kind in _STATE_KINDS:
            self.tail_state_records += 1
        if kind == KIND_RUNNER_START:
            self.had_previous_run = True
        elif kind == "paper_order":
            self.order_times.append(int(payload["decided_at_ms"]))
        elif kind == "signal" and record.ts.ms >= tid_floor_ms:
            self.signal_tids[payload["wallet"].lower()].add(int(payload["tid"]))
        elif kind == "follow_started":
            self.follow_started[payload["wallet"].lower()] = int(payload["followed_at_ms"])
        elif kind == "follow_ended":
            self.follow_started.pop(payload["wallet"].lower(), None)
        elif kind == "select_cycle":
            self.followed = tuple(w.lower() for w in payload["followed"])
        elif kind == "leader_paused":
            self.paused.add(payload["wallet"].lower())


def scan_ledger(ledger: Ledger, settings: PaperSettings, *, now_ms: int) -> LedgerScan:
    """One verified pass over the whole ledger: the broker replay and the rest of ``LedgerScan``."""
    scan = LedgerScan()

    def watched() -> Iterator[LedgerRecord]:
        for record in ledger.records():
            scan.observe(record, tid_floor_ms=now_ms - TID_WINDOW_MS)
            yield record

    scan.snapshot = replay_broker(watched(), settings)
    return scan


def checkpoint_payload(
    *,
    run_id: str,
    last_advanced_ms: int | None,
    risk_state_expected: bool,
    manager: Mapping[str, Any],
    gate_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """The ledger payload of a ``runner_checkpoint`` record (see ``Runner``)."""
    return {
        "run_id": run_id,
        "last_advanced_ms": last_advanced_ms,
        "risk_state_expected": risk_state_expected,
        "manager": manager,
        "gate_entries": gate_entries,
    }


@dataclass(frozen=True)
class ReloadResult:
    restored_positions: int
    restored_stops: int
    requeued_exits: tuple[Requeued, ...]
    uncertain: tuple[Uncertainty, ...]


@dataclass(frozen=True)
class ReloadParts:
    """The components ``reload`` loads state into (all fresh) and what it reads."""

    broker: PaperBroker
    gate: RiskGate
    manager: PositionManager
    follow: FollowManager
    book: PositionBook
    state_file: Path
    send_alert: AlertSink
    fetch_rules: Callable[[], Mapping[str, CoinMeta]]


class ReloadError(CopytradeError):
    """The reload cannot continue safely (the start is refused, nothing is traded)."""


def reload_state(parts: ReloadParts, scan: LedgerScan, *, now_ms: int) -> ReloadResult:
    """Load the scanned state into the fresh components, then flag everything uncertain.

    Order: the broker first (its time is set before anything else), then the gate, the manager and the follow manager.
    Raises:
        ReloadError: positions or orders must be restored but the exchange rules cannot be fetched.
    """
    snapshot = scan.snapshot
    assert snapshot is not None  # noqa: S101 - scan_ledger always sets it
    checkpoint = scan.checkpoint
    restore_ms = max(now_ms, snapshot.last_time_ms, int(checkpoint["last_advanced_ms"] or 0) if checkpoint else 0)
    needs_rules = bool(snapshot.positions or snapshot.stops or snapshot.exits)
    try:
        rules = dict(parts.fetch_rules())
    except OSError as exc:
        if needs_rules:
            raise ReloadError(
                "the exchange rules cannot be fetched, so the open positions cannot be restored; "
                f"start again when the exchange is reachable ({type(exc).__name__})"
            ) from exc
        rules = {}
    result = parts.broker.restore(snapshot, now_ms=restore_ms, rules=rules)
    parts.gate.restore(
        entries=checkpoint["gate_entries"] if checkpoint else (),
        order_times_ms=[t for t in scan.order_times if t > restore_ms - ORDER_WINDOW_MS],
        last_exchange_ms=restore_ms,
    )
    cid_map = {r.old_client_order_id: r.new_client_order_id for r in (*result.stops, *result.exits)}
    if checkpoint:
        parts.manager.restore_state(checkpoint["manager"], cid_map=cid_map, tids_done=scan.signal_tids)
    _restore_follow(parts, scan)
    uncertain = _uncertainties(parts, scan, result_unknown=result.unknown_coins, dropped=result.dropped_exits)
    return ReloadResult(
        restored_positions=len(snapshot.positions),
        restored_stops=len(result.stops),
        requeued_exits=tuple(Requeued(r.old_client_order_id, r.new_client_order_id, r.share_id) for r in result.exits),
        uncertain=uncertain,
    )


def _restore_follow(parts: ReloadParts, scan: LedgerScan) -> None:
    """The followed set is the last cycle's, minus wallets paused since and wallets the detector no longer follows;
    fills stay subscribed for those plus every wallet we still hold a share of."""
    followed = {
        wallet: Follow(followed_at_ms=scan.follow_started[wallet], drop_streak=0)
        for wallet in scan.followed
        if wallet in scan.follow_started and wallet not in scan.paused
    }
    held = {s.leader.lower() for s in parts.book.states() if s.status != CLOSED}
    parts.follow.restore(followed, subscribed=set(followed) | held, paused=scan.paused)


def _uncertainties(
    parts: ReloadParts, scan: LedgerScan, *, result_unknown: Iterable[str], dropped: Iterable[str]
) -> tuple[Uncertainty, ...]:
    found: list[Uncertainty] = []
    found.extend(Uncertainty(UNKNOWN_COIN, f"the exchange no longer lists {coin}") for coin in result_unknown)
    found.extend(
        Uncertainty(EXIT_STATE_UNPROVEN, f"exit order {cid} has no matching share and was cancelled") for cid in dropped
    )
    held = {(view.coin, share_id) for view in parts.broker.positions() for share_id in view.share_ids}
    booked = {(s.coin, s.share_id) for s in parts.book.states() if s.status == OPEN}
    found.extend(
        Uncertainty(POSITION_WITHOUT_SHARE, f"{coin} share {share_id} is held but the share book has no such share")
        for coin, share_id in sorted(held - booked)
    )
    found.extend(
        Uncertainty(SHARE_WITHOUT_POSITION, f"{coin} share {share_id} is booked open but the broker holds nothing")
        for coin, share_id in sorted(booked - held)
    )
    if scan.checkpoint is not None and scan.checkpoint["risk_state_expected"] and not parts.state_file.exists():
        found.append(Uncertainty(MISSING_RISK_STATE_FILE, "the risk state file (pause, drawdown peak) is missing"))
    if scan.tail_state_records:
        found.append(
            Uncertainty(
                CHECKPOINT_BEHIND_LEDGER,
                f"{scan.tail_state_records} broker records were written after the last checkpoint",
            )
        )
    return tuple(found)


def announce_and_pause(parts: ReloadParts, uncertain: Iterable[Uncertainty]) -> None:
    """One alert per uncertainty and, if there is any, the persisted pause (the PO acknowledges with ``/resume``)."""
    items = tuple(uncertain)
    for item in items:
        parts.send_alert.send(
            Alert(kind=ALERT_STARTUP_UNCERTAIN, message=f"{item.code}: {item.detail}. New entries are paused: /resume")
        )
    if items:
        with contextlib.suppress(RiskStateError):  # in force in memory anyway; the gate logged the failed save
            parts.gate.pause()
