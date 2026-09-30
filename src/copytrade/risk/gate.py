"""The risk gate (F10): the single chokepoint for every order (A1) and the only holder of the ``GateAuthority``."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from copytrade.core.config import Config
from copytrade.core.events import AlertSink
from copytrade.ledger.store import Ledger
from copytrade.paper.broker import PaperBroker
from copytrade.paper.gate import GateAuthority
from copytrade.paper.ports import MetaSource
from copytrade.risk.ports import AccountView, EntryCalendar, ExchangeTime, ReturnsSource, ShareBook
from copytrade.risk.types import Decision, Outcome, Request, StopRequest

STATE_FILENAME = "risk_state.json"


class RiskGate:
    """Sizes entries from our risk budget, enforces every hard limit and sends approved orders to the broker.

    State that must survive a restart (pause flag, daily and weekly opening equity and halts, peak equity and the
    drawdown pause) lives in ``state_dir / STATE_FILENAME``; an unreadable state file refuses entries.

    Refusal reasons (``Decision.reason``): ``paused``, ``drawdown_pause``, ``daily_loss_halt``, ``weekly_loss_halt``,
    ``calendar_blackout``, ``clock_unsynced``, ``equity_unknown``, ``risk_state_unknown``, ``ledger_failed``,
    ``meta_unavailable``, ``unknown_coin``, ``check_error``, ``no_leader_av``, ``opposite_side_entry``,
    ``max_open_positions``, ``rate_limit``, ``unexecutable``, ``insufficient_margin``, ``liq_too_close``,
    ``stop_widening``, ``add_below_min``, and for exits ``exceeds_share``.
    """

    def __init__(  # noqa: PLR0913 - the boundaries are injected
        self,
        *,
        config: Config,
        broker: PaperBroker,
        meta: MetaSource,
        account: AccountView,
        shares: ShareBook,
        returns: ReturnsSource,
        exchange_time: ExchangeTime,
        calendar: EntryCalendar,
        ledger: Ledger,
        alerts: AlertSink,
        authority: GateAuthority,
        state_dir: Path,
    ) -> None:
        raise NotImplementedError

    def check(self, request: Request) -> Decision:
        """Decide without sending. Writes one ``risk_decision`` ledger record (B5). Never raises for an entry: any
        exception inside a check is a ``check_error`` refusal. Exits are never refused for caps, limits, pauses,
        calendar, equity or state problems."""
        raise NotImplementedError

    def submit(self, request: Request) -> Outcome:
        """``broker.advance_to(exchange_now)``, stamp ``decided_at_ms`` with that exchange time, ``check``, and when
        approved issue a FRESH token for exactly the intent and call the broker. A refused request reaches neither
        ``GateAuthority.issue`` nor the broker."""
        raise NotImplementedError

    def place_stop(self, request: StopRequest) -> Outcome:
        """Approve a stop (exit-like, never refused for pauses or limits) and register it with the broker."""
        raise NotImplementedError

    def mark_equity(self, now_ms: int) -> None:
        """Mark-to-market the account (called every ``eval.mark_interval_s``): updates opening equity, the daily and
        weekly halts and the drawdown pause."""
        raise NotImplementedError

    def pause(self) -> None:
        """Kill switch: refuse new opens and adds at once. Persisted."""
        raise NotImplementedError

    def resume(self) -> None:
        """Clear the pause (manual and drawdown). Persisted."""
        raise NotImplementedError

    @property
    def paused(self) -> bool:
        raise NotImplementedError

    def flatten(self, *, run_id: str) -> Sequence[Outcome]:
        """Close every open share in the share book through the gate (full ``CLOSE``, reason ``flatten``, at the
        share's mark), whatever the pause, halt or equity state. Re-running it sends no second order for a share."""
        raise NotImplementedError
