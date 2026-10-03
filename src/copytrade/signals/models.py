"""Signal value types and the ports around the detector (F7.AC1 to AC5)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from copytrade.core.clock import Timestamp
from copytrade.core.domain import ActionKind
from copytrade.core.errors import CopytradeError
from copytrade.core.money import Price, Qty

OUT_OF_SCOPE = "out_of_scope"
PRE_EXISTING = "pre_existing"
UNPARSEABLE = "unparseable"
FLAG_CLOCK_ANOMALY = "clock_anomaly"
FLAG_CLOCK_UNSYNCED = "clock_unsynced"

_ENTRY_ACTIONS = frozenset({ActionKind.OPEN, ActionKind.ADD})

KIND_SIGNAL = "signal"
KIND_FOLLOW_STARTED = "follow_started"
KIND_FOLLOW_ENDED = "follow_ended"
KIND_LATENCY_SAMPLE = "latency_sample"


class WalletNotFollowedError(CopytradeError):
    """Fills arrived for a wallet with no follow state (``begin_follow`` never called, or ``end_follow`` was)."""


@dataclass(frozen=True)
class Signal:
    """One typed leader event.

    - ``signal_id``: deterministic from the wallet, the fill's ``tid`` and the leg (A5); the same fill always gives the
      same ids, distinct legs and distinct fills give distinct ids.
    - ``leg``: 0 for a fill's only or first signal, 1 for the open half of a flip (its close half is leg 0).
    - ``action`` / ``is_long`` / ``pre_position`` / ``post_position`` / ``reduce_fraction``: from
      ``startPosition``, ``sz`` and ``side`` (F7.AC1). ``is_long`` is the direction of the position being opened,
      added to, reduced or closed. ``reduce_fraction`` is set for a reduce only. All five are ``None`` when
      ``outcome`` is ``out_of_scope`` or ``unparseable`` (nothing is inferred for those).
    - ``size``: coin units of this leg (positive).
    - ``outcome``: ``None`` for a normal signal, else ``"out_of_scope"``, ``"pre_existing"`` or ``"unparseable"``.
    - ``age_ms``: ``(receive_ts + clock offset) - exchange_ts`` (F7.AC5); ``None`` while the clock is unsynced.
    - ``s2_ms``: receive to classified, in ms of the injected clock (latency stage S2).
    - ``flags``: ``"clock_anomaly"`` (age below minus ``clock.max_offset_uncertainty_ms``), ``"clock_unsynced"``.
    """

    signal_id: str
    wallet: str
    coin: str
    tid: int
    leg: int
    from_flip: bool
    action: ActionKind | None
    is_long: bool | None
    size: Qty
    pre_position: Qty | None
    post_position: Qty | None
    reduce_fraction: Decimal | None
    px: Price
    exchange_ts: Timestamp
    receive_ts: Timestamp
    age_ms: int | None
    s2_ms: int
    outcome: str | None
    flags: frozenset[str]

    def refusal_reason(self) -> str | None:
        """For OPEN and ADD only: ``"clock_anomaly"`` or ``"clock_unsynced"`` when that flag is set, else ``None``.
        Reduces, closes and signals with an outcome are never refused here."""
        if self.outcome is not None or self.action not in _ENTRY_ACTIONS:
            return None
        if FLAG_CLOCK_ANOMALY in self.flags:
            return FLAG_CLOCK_ANOMALY
        if FLAG_CLOCK_UNSYNCED in self.flags:
            return FLAG_CLOCK_UNSYNCED
        return None


class SignalSink(Protocol):
    """Receives every signal (with an outcome or not), in order, after it has been ledgered. F9 implements it."""

    def on_signals(self, signals: Sequence[Signal]) -> None: ...
