"""The signal detector: a ``FillSink`` for F3's feed (F7.AC1 to AC5)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from copytrade.core.clock import Clock, ClockSync
from copytrade.core.events import AlertSink
from copytrade.hl.models import ClearinghouseState, Fill
from copytrade.ledger.store import Ledger
from copytrade.signals.models import SignalSink

ALERT_UNPARSEABLE = "unparseable_fill"


class SignalDetector:
    """Implements ``copytrade.hl.ws.FillSink``. For each ``on_fills(wallet, fills)`` call, in fill order:

    1. Drop a fill whose ``(wallet, tid)`` was already processed (any source: WebSocket, snapshot, REST resync,
       an earlier run of the process). Dropped fills create no signal and no ledger record.
    2. Scope: a coin with ``:`` (HIP-3 dex), a spot coin (starts with ``@`` or contains ``/``), or a dex not in
       ``markets.allowed_dexes`` gives one signal with outcome ``out_of_scope``.
    3. A ``dir`` that is empty or not one of Hyperliquid's perp values (``Open Long``, ``Close Long``,
       ``Open Short``, ``Close Short``, ``Long > Short``, ``Short > Long``, or a value starting ``Liquidated`` or
       ``Auto-Deleveraging``) gives one signal with outcome ``unparseable`` and an ``unparseable_fill`` alert.
       So does a size that is not positive.
    4. Otherwise ``classify_fill`` gives one signal per leg. While the wallet's position on the coin is one that
       existed when the wallet was followed, every leg that touches it is ``pre_existing``, up to and including the
       leg that takes the position to zero. The open leg of a flip is a normal signal.
    5. Age (F7.AC5) and ``s2_ms`` are computed; every signal is appended to the ledger (kind ``signal``) **before** the
       batch is handed to ``sink.on_signals``; a ledger failure propagates and nothing is delivered.

    The ledger ``signal`` record's payload has the keys ``signal_id``, ``wallet``, ``coin``, ``tid``, ``leg``,
    ``from_flip``, ``action`` (the ``ActionKind`` value, or ``None``), ``is_long``, ``size``, ``pre_position``,
    ``post_position``, ``reduce_fraction``, ``px``, ``exchange_ts`` and ``receive_ts`` (each ``{"ms", "source"}``),
    ``age_ms``, ``s2_ms``, ``outcome`` and ``flags`` (a sorted list). ``follow_started`` holds ``wallet``,
    ``followed_at_ms`` and ``held`` (the coins); ``follow_ended`` holds ``wallet``.

    The pre-existing state and the processed ``tid`` set survive a restart: a new detector over the same ledger rebuilds
    them from the ``follow_started``, ``follow_ended`` and ``signal`` records.
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
        raise NotImplementedError

    def begin_follow(self, wallet: str, state: ClearinghouseState, followed_at_ms: int) -> None:
        """Start following ``wallet``: remember which coins it holds (non-zero ``szi``) in ``state`` and ledger a
        ``follow_started`` record. A wallet that is already followed is left as it is (no-op).

        Raises:
            HlRequestError: ``wallet`` is not a valid address.
        """
        raise NotImplementedError

    def end_follow(self, wallet: str) -> None:
        """Forget ``wallet`` (ledger ``follow_ended``); a later ``begin_follow`` starts fresh. Unknown: ignored."""
        raise NotImplementedError

    def on_fills(self, wallet: str, fills: Sequence[Fill]) -> None:
        """See the class docstring.

        Raises:
            WalletNotFollowedError: ``wallet`` has no follow state.
            LedgerWriteError: a ledger append failed.
        """
        raise NotImplementedError
