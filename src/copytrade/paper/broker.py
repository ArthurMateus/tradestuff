"""The paper broker (F11). Paper only: it never touches a network, an exchange endpoint or a signing client."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from copytrade.core.clock import Clock
from copytrade.core.config import Config
from copytrade.core.events import AlertSink
from copytrade.core.money import Price
from copytrade.ledger.store import Ledger
from copytrade.paper.gate import GateAuthority
from copytrade.paper.ports import BookSource, FundingSource, MetaSource
from copytrade.paper.types import (
    BrokerEvent,
    GateToken,
    MarkUpdate,
    OrderIntent,
    PositionView,
    StopIntent,
    SubmitResult,
)


class PaperBroker:
    """Simulated account (``paper.wallet_usd``), isolated margin, one merged position per coin, shares tracked by ID.

    Time is explicit: ``submit`` and ``place_stop`` answer at once; everything that needs a book, a mark or the
    clock happens in ``advance_to``, ``on_mark`` and ``on_delist``, each returning the events it caused (also
    appended to the ledger). Ledger append errors propagate to the caller (F2.AC6).

    Raises ``ConfigError`` at construction for a missing or out-of-range key, ``mode`` other than ``paper``.
    """

    def __init__(  # noqa: PLR0913 - the boundaries are injected
        self,
        *,
        config: Config,
        books: BookSource,
        meta: MetaSource,
        funding: FundingSource,
        ledger: Ledger,
        clock: Clock,
        alerts: AlertSink,
        authority: GateAuthority,
    ) -> None:
        raise NotImplementedError

    def submit(self, intent: OrderIntent, token: GateToken) -> SubmitResult:
        """Accept a gate-approved market order. See ``SubmitResult`` for the refusal reasons."""
        raise NotImplementedError

    def place_stop(self, intent: StopIntent, token: GateToken) -> SubmitResult:
        """Register a gate-approved SL or TP."""
        raise NotImplementedError

    def cancel_stop(self, client_order_id: str) -> bool:
        """Cancel a registered stop; ``True`` if one was removed."""
        raise NotImplementedError

    def advance_to(self, now_ms: int) -> Sequence[BrokerEvent]:
        """Resolve pending orders whose fill time has come, and accrue funding for every UTC hour boundary passed."""
        raise NotImplementedError

    def on_mark(self, update: MarkUpdate) -> Sequence[BrokerEvent]:
        """Trigger stops and liquidate positions whose liquidation price the mark reached."""
        raise NotImplementedError

    def on_delist(self, coin: str, settlement_px: Price, time_ms: int) -> Sequence[BrokerEvent]:
        """Force-settle every share on ``coin`` at ``settlement_px`` ."""
        raise NotImplementedError

    def position(self, coin: str) -> PositionView | None:
        raise NotImplementedError

    def cash_usd(self) -> Decimal:
        """Wallet cash (a ``Decimal``): ``paper.wallet_usd`` plus realised P&L, minus fees, plus funding."""
        raise NotImplementedError
