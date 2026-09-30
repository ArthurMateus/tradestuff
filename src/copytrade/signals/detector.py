"""The signal detector: a ``FillSink`` for F3's feed (F7.AC1 to AC5)."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from copytrade.core.clock import Clock, ClockSync, TimeSource, Timestamp
from copytrade.core.domain import ActionKind
from copytrade.core.errors import ClockUnsyncedError
from copytrade.core.events import Alert, AlertSink
from copytrade.hl.models import ClearinghouseState, Fill
from copytrade.hl.wallet import normalize_wallet
from copytrade.ledger.store import Ledger
from copytrade.signals.classify import Leg, UnparseableFillError, classify_fill
from copytrade.signals.models import (
    FLAG_CLOCK_ANOMALY,
    FLAG_CLOCK_UNSYNCED,
    KIND_FOLLOW_ENDED,
    KIND_FOLLOW_STARTED,
    KIND_SIGNAL,
    OUT_OF_SCOPE,
    PRE_EXISTING,
    UNPARSEABLE,
    Signal,
    SignalSink,
    WalletNotFollowedError,
)

ALERT_UNPARSEABLE = "unparseable_fill"

CORE_DEX = "core"
_HIP3_SEPARATOR = ":"
_SPOT_PREFIX = "@"
_SPOT_SEPARATOR = "/"
# The ``dir`` texts Hyperliquid gives perp fills. Anything else is a format we do not understand (spec section 5).
_KNOWN_DIRS = frozenset({"Open Long", "Close Long", "Open Short", "Close Short", "Long > Short", "Short > Long"})
_KNOWN_DIR_PREFIXES = ("Liquidated", "Auto-Deleveraging")
_MAX_DIR_CHARS_IN_ALERT = 40
_log = logging.getLogger(__name__)


def _is_out_of_scope(coin: str, allowed_dexes: frozenset[str]) -> bool:
    """HIP-3 (``dex:COIN``) and spot (``@n``, ``A/B``) markets are never in scope. A plain coin is a core perp."""
    if _HIP3_SEPARATOR in coin or coin.startswith(_SPOT_PREFIX) or _SPOT_SEPARATOR in coin:
        return True
    return CORE_DEX not in allowed_dexes


def _dir_is_known(text: str) -> bool:
    return text in _KNOWN_DIRS or text.startswith(_KNOWN_DIR_PREFIXES)


def signal_id(wallet: str, tid: int, leg: int) -> str:
    """Deterministic and injective in ``(wallet, tid, leg)`` (A5): the same fill always gives the same ids."""
    return f"{wallet}:{tid}:{leg}"


def _timestamp_payload(stamp: Timestamp) -> dict[str, Any]:
    return {"ms": stamp.ms, "source": stamp.source.value}


def signal_payload(signal: Signal) -> dict[str, Any]:
    """The ledger ``signal`` payload (keys documented on ``SignalDetector``)."""
    return {
        "signal_id": signal.signal_id,
        "wallet": signal.wallet,
        "coin": signal.coin,
        "tid": signal.tid,
        "leg": signal.leg,
        "from_flip": signal.from_flip,
        "action": None if signal.action is None else signal.action.value,
        "is_long": signal.is_long,
        "size": signal.size,
        "pre_position": signal.pre_position,
        "post_position": signal.post_position,
        "reduce_fraction": signal.reduce_fraction,
        "px": signal.px,
        "exchange_ts": _timestamp_payload(signal.exchange_ts),
        "receive_ts": _timestamp_payload(signal.receive_ts),
        "age_ms": signal.age_ms,
        "s2_ms": signal.s2_ms,
        "outcome": signal.outcome,
        "flags": sorted(signal.flags),
    }


@dataclass(frozen=True)
class _Arrival:
    """What is known about one batch when it arrives: the local receive time and the clock state at that moment."""

    receive_ms: int
    offset_ms: int | None  # exchange minus local; ``None`` while the clock is unsynced


@dataclass
class _Pending:
    """The signals of one fill, classified but not yet ledgered, with the alert the fill raises (if any)."""

    signals: list[Signal] = field(default_factory=list)
    alert: Alert | None = None


class SignalDetector:
    """Implements ``copytrade.hl.ws.FillSink``. For each ``on_fills(wallet, fills)`` call, in fill order:

    1. Drop a fill whose ``(wallet, tid)`` was already processed (any source: WebSocket, snapshot, REST resync,
       an earlier run of the process). Dropped fills create no signal and no ledger record.
    2. Scope: a coin with ``:`` (HIP-3 dex), a spot coin (starts with ``@`` or contains ``/``), or a core perp when
       ``core`` is not in ``markets.allowed_dexes`` gives one signal with outcome ``out_of_scope``.
    3. A ``dir`` that is empty or not one of Hyperliquid's perp values (``Open Long``, ``Close Long``,
       ``Open Short``, ``Close Short``, ``Long > Short``, ``Short > Long``, or a value starting ``Liquidated`` or
       ``Auto-Deleveraging``) gives one signal with outcome ``unparseable`` and an ``unparseable_fill`` alert.
       So does a size that is not positive or a side that is neither ``B`` nor ``A``. ``dir`` is checked for being
       a known value and for nothing else: it never changes the classification.
    4. Otherwise ``classify_fill`` gives one signal per leg. While the wallet's position on the coin is one that
       existed when the wallet was followed, every leg that touches it is ``pre_existing``, up to and including the
       leg that takes the position to zero. The open leg of a flip is a normal signal.
    5. Age (F7.AC5) and ``s2_ms`` are computed while classifying (before any ledger write, so S2 measures
       classification only); every signal is appended to the ledger (kind ``signal``) **before** it is handed
       to ``sink.on_signals``. The batch is delivered once, in fill order. If an append fails part-way, the signals
       already ledgered are still delivered (then the failure propagates); only the signal in flight is lost.

    The ledger ``signal`` record's payload has the keys ``signal_id``, ``wallet``, ``coin``, ``tid``, ``leg``,
    ``from_flip``, ``action`` (the ``ActionKind`` value, or ``None``), ``is_long``, ``size``, ``pre_position``,
    ``post_position``, ``reduce_fraction``, ``px``, ``exchange_ts`` and ``receive_ts`` (each ``{"ms", "source"}``),
    ``age_ms``, ``s2_ms``, ``outcome`` and ``flags`` (a sorted list). ``follow_started`` holds ``wallet``,
    ``followed_at_ms`` and ``held`` (the coins); ``follow_ended`` holds ``wallet``.

    The pre-existing state and the processed ``tid`` set survive a restart: a new detector over the same ledger rebuilds
    them from the ``follow_started``, ``follow_ended`` and ``signal`` records.

    Failure order inside a batch. A fill's tid counts as processed once its first signal is in the ledger, and every
    ledgered signal is delivered even if a later append fails, so the crash window loses at most the signal in flight.
    A flip ledgers and delivers its close before its open, so that window can lose an entry but never an exit (C4).
    The ledger refuses every append after its first failure, so the process stops there.

    Known limit (plan decision 8): F3 does not tell a snapshot fill from a live one, so a snapshot that replays
    history older than the follow time is signalled as it is, with its true (large) ``age_ms``. F9 refuses stale
    entries; exits are never dropped.

    Single-threaded, like the feed that drives it.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        config: Mapping[str, Any],
        clock: Clock,
        sync: ClockSync,
        ledger: Ledger,
        sink: SignalSink,
        alerts: AlertSink,
    ) -> None:
        self._allowed_dexes = frozenset(config["markets.allowed_dexes"])
        self._anomaly_below_ms = -int(config["clock.max_offset_uncertainty_ms"])
        self._clock = clock
        self._sync = sync
        self._ledger = ledger
        self._sink = sink
        self._alerts = alerts
        self._held_at_follow: dict[str, set[str]] = {}  # followed wallet -> coins still on their pre-existing position
        self._processed: set[tuple[str, int]] = set()
        self._rebuild()

    # --- follow state ---------------------------------------------------------------------------------------

    def begin_follow(self, wallet: str, state: ClearinghouseState, followed_at_ms: int) -> None:
        """Start following ``wallet``: remember which coins it holds (non-zero ``szi``) in ``state`` and ledger a
        ``follow_started`` record. A wallet that is already followed is left as it is (no-op).

        Raises:
            HlRequestError: ``wallet`` is not a valid address.
        """
        key = normalize_wallet(wallet)
        if key in self._held_at_follow:
            return
        held = sorted({position.coin for position in state.positions if position.szi != 0})
        self._ledger.append(KIND_FOLLOW_STARTED, {"wallet": key, "followed_at_ms": followed_at_ms, "held": held})
        self._held_at_follow[key] = set(held)

    def end_follow(self, wallet: str) -> None:
        """Forget ``wallet`` (ledger ``follow_ended``); a later ``begin_follow`` starts fresh. Unknown: ignored."""
        key = wallet.lower()
        if key not in self._held_at_follow:
            return
        self._ledger.append(KIND_FOLLOW_ENDED, {"wallet": key})
        del self._held_at_follow[key]

    # --- fills ----------------------------------------------------------------------------------------------

    def on_fills(self, wallet: str, fills: Sequence[Fill]) -> None:
        """See the class docstring.

        Raises:
            HlRequestError: ``wallet`` is not a valid address.
            WalletNotFollowedError: ``wallet`` has no follow state.
            LedgerWriteError: a ledger append failed (after the signals ledgered before it were delivered).
        """
        key = normalize_wallet(wallet)
        if key not in self._held_at_follow:
            raise WalletNotFollowedError("fills arrived for a wallet that is not followed")
        arrival = _Arrival(self._clock.now_ms(), self._current_offset_ms())
        pending = self._classify_batch(key, fills, arrival)
        signals: list[Signal] = []
        alerts: list[Alert] = []
        try:
            for item in pending:
                for signal in item.signals:
                    self._ledger.append(KIND_SIGNAL, signal_payload(signal))
                    self._commit(key, signal)
                    signals.append(signal)
                if item.alert is not None:
                    alerts.append(item.alert)
        finally:
            # Whatever reached the ledger is delivered, even when a later append failed: those tids now count as
            # processed, so after a restart they would be duplicates and never reach the sink.
            for alert in alerts:
                self._send_alert(alert)
            if signals:
                self._sink.on_signals(tuple(signals))

    def _classify_batch(self, wallet: str, fills: Sequence[Fill], arrival: _Arrival) -> list[_Pending]:
        """Classify every new fill of the batch, in order, without touching the ledger or the follow state."""
        pre_existing = set(self._held_at_follow[wallet])  # a working copy: legs of one batch see each other's effect
        seen: set[int] = set()
        pending: list[_Pending] = []
        for fill in fills:
            if fill.tid in seen or (wallet, fill.tid) in self._processed:
                continue
            seen.add(fill.tid)
            pending.append(self._classify_fill(wallet, fill, arrival, pre_existing))
        return pending

    def _classify_fill(self, wallet: str, fill: Fill, arrival: _Arrival, pre_existing: set[str]) -> _Pending:
        item = _Pending()
        if _is_out_of_scope(fill.coin, self._allowed_dexes):
            item.signals.append(self._unclassified(wallet, fill, arrival, OUT_OF_SCOPE))
            return item
        problem: str | None = None
        legs: tuple[Leg, ...] = ()
        if not _dir_is_known(fill.dir):
            problem = f"unknown dir {fill.dir[:_MAX_DIR_CHARS_IN_ALERT]!r}"
        else:
            try:
                legs = classify_fill(fill)
            except UnparseableFillError as exc:
                problem = str(exc)
        if problem is not None:
            item.signals.append(self._unclassified(wallet, fill, arrival, UNPARSEABLE))
            item.alert = Alert(
                kind=ALERT_UNPARSEABLE,
                message=(
                    f"Unparseable fill from {wallet} (tid {fill.tid}, {fill.coin}): {problem}; recorded, never traded"
                ),
            )
            return item
        for leg in legs:
            outcome = None
            if fill.coin in pre_existing:
                outcome = PRE_EXISTING
                if leg.post == 0:
                    pre_existing.discard(fill.coin)
            item.signals.append(self._typed(wallet, fill, leg, arrival, outcome))
        return item

    # --- building signals -----------------------------------------------------------------------------------

    def _age_and_flags(self, fill: Fill, arrival: _Arrival) -> tuple[int | None, frozenset[str]]:
        if arrival.offset_ms is None:
            return None, frozenset({FLAG_CLOCK_UNSYNCED})
        age_ms = arrival.receive_ms + arrival.offset_ms - fill.time_ms
        return age_ms, frozenset({FLAG_CLOCK_ANOMALY}) if age_ms < self._anomaly_below_ms else frozenset()

    def _typed(self, wallet: str, fill: Fill, leg: Leg, arrival: _Arrival, outcome: str | None) -> Signal:
        index = 1 if leg.from_flip and leg.action is ActionKind.OPEN else 0  # the open half of a flip is leg 1
        age_ms, flags = self._age_and_flags(fill, arrival)
        return Signal(
            signal_id=signal_id(wallet, fill.tid, index),
            wallet=wallet,
            coin=fill.coin,
            tid=fill.tid,
            leg=index,
            from_flip=leg.from_flip,
            action=leg.action,
            is_long=leg.is_long,
            size=leg.size,
            pre_position=leg.pre,
            post_position=leg.post,
            reduce_fraction=leg.reduce_fraction,
            px=fill.px,
            exchange_ts=Timestamp(fill.time_ms, TimeSource.EXCHANGE),
            receive_ts=Timestamp(arrival.receive_ms, TimeSource.LOCAL),
            age_ms=age_ms,
            s2_ms=self._s2_ms(arrival),
            outcome=outcome,
            flags=flags,
        )

    def _unclassified(self, wallet: str, fill: Fill, arrival: _Arrival, outcome: str) -> Signal:
        """The single signal of a fill we do not classify: nothing about its position change is inferred."""
        age_ms, flags = self._age_and_flags(fill, arrival)
        return Signal(
            signal_id=signal_id(wallet, fill.tid, 0),
            wallet=wallet,
            coin=fill.coin,
            tid=fill.tid,
            leg=0,
            from_flip=False,
            action=None,
            is_long=None,
            size=fill.sz,
            pre_position=None,
            post_position=None,
            reduce_fraction=None,
            px=fill.px,
            exchange_ts=Timestamp(fill.time_ms, TimeSource.EXCHANGE),
            receive_ts=Timestamp(arrival.receive_ms, TimeSource.LOCAL),
            age_ms=age_ms,
            s2_ms=self._s2_ms(arrival),
            outcome=outcome,
            flags=flags,
        )

    def _s2_ms(self, arrival: _Arrival) -> int:
        return max(0, self._clock.now_ms() - arrival.receive_ms)

    def _current_offset_ms(self) -> int | None:
        """Exchange time minus local time, or ``None`` while the clock sync refuses entries (no estimate, a stale or
        too uncertain one): an age computed from an offset we do not trust would be a guess."""
        if self._sync.refusal_reason(ActionKind.OPEN) is not None:
            return None
        try:
            return self._sync.exchange_now().ms - self._clock.now_ms()
        except ClockUnsyncedError:
            return None

    # --- state ----------------------------------------------------------------------------------------------

    def _commit(self, wallet: str, signal: Signal) -> None:
        """A signal is in the ledger: its tid is processed and its effect on the pre-existing state is real."""
        self._processed.add((wallet, signal.tid))
        self._apply(wallet, signal.coin, signal.outcome, signal.post_position)

    def _apply(self, wallet: str, coin: str, outcome: str | None, post_position: Decimal | None) -> None:
        """A pre-existing leg that leaves the wallet flat on ``coin`` ends the pre-existing position."""
        held = self._held_at_follow.get(wallet)
        if held is not None and outcome == PRE_EXISTING and post_position == 0:
            held.discard(coin)

    def _rebuild(self) -> None:
        """Restore the follow state and the processed tids from the ledger, in the order they were written."""
        for record in self._ledger.records():
            payload = record.payload
            if record.kind == KIND_FOLLOW_STARTED:
                self._held_at_follow[payload["wallet"]] = set(payload["held"])
            elif record.kind == KIND_FOLLOW_ENDED:
                self._held_at_follow.pop(payload["wallet"], None)
            elif record.kind == KIND_SIGNAL:
                wallet = payload["wallet"]
                self._processed.add((wallet, payload["tid"]))
                self._apply(wallet, payload["coin"], payload["outcome"], payload["post_position"])

    def _send_alert(self, alert: Alert) -> None:
        try:
            self._alerts.send(alert)
        except OSError as exc:
            _log.warning(
                "unparseable-fill alert delivery failed",
                extra={"event": "signal_alert_failed", "error_type": type(exc).__name__},
            )
