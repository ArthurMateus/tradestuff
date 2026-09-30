"""Value types of the risk gate (F10). Data only; every amount is Decimal-based (A6), units are in the names (A9).

Interface stubs written by the test designer: the developer owns them from here on.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.ledger.records import RiskCheckResult
from copytrade.paper.types import SubmitResult


@dataclass(frozen=True)
class ShareExposure:
    """One open share as the position manager (F12) reports it to the gate.

    ``qty`` is positive coin units, ``is_long`` its direction. ``stop_px`` is the share's current stop,
    ``mark_px`` the latest mark, ``open_risk_usd`` the USD the share loses if its stop fills at the stop price.
    """

    share_id: str
    trade_id: str
    coin: str
    leader: str
    is_long: bool
    qty: Qty
    entry_px: Price
    stop_px: Price
    mark_px: Price
    open_risk_usd: Decimal


@dataclass(frozen=True)
class OpenRequest:
    """A new share on a coin (``ActionKind.OPEN``), sized from our risk budget (C2).

    ``leader_position_notional_usd`` is the leader's post-fill position notional, ``leader_account_value_usd`` and
    ``leader_av_time_ms`` (exchange time) the account value at or before the fill; ``None`` means unknown.
    ``stop_px`` is the initial ATR stop, ``vol_mult`` the volatility multiplier of the risk notional.
    """

    run_id: str
    signal_id: str
    leader: str
    coin: str
    is_long: bool
    tids: tuple[int, ...]
    trade_id: str
    share_id: str
    decision_px: Price
    stop_px: Price
    vol_mult: Decimal
    leader_position_notional_usd: Decimal
    leader_account_value_usd: Decimal | None
    leader_av_time_ms: int | None


@dataclass(frozen=True)
class AddRequest:
    """An add to an existing share (``ActionKind.ADD``): quantity = ``our_share_qty`` x (``leader_add_size`` /
    ``leader_pre_add_position``), then capped. ``stop_px`` is the add's own ATR stop, ``current_stop_px`` the
    share's current stop (the share's stop after the add)."""

    run_id: str
    signal_id: str
    leader: str
    coin: str
    is_long: bool
    tids: tuple[int, ...]
    trade_id: str
    share_id: str
    decision_px: Price
    stop_px: Price
    current_stop_px: Price
    our_share_qty: Qty
    leader_add_size: Qty
    leader_pre_add_position: Qty


@dataclass(frozen=True)
class ExitRequest:
    """A reduce or close (reduce-only) of ``qty`` on a share. ``is_long`` is the direction of the position being
    closed. ``reason`` is e.g. ``leader_close``, ``flatten``, ``dropped_leader``, ``reconstruction_settlement``."""

    run_id: str
    signal_id: str
    leader: str
    coin: str
    is_long: bool
    tids: tuple[int, ...]
    trade_id: str
    share_id: str
    qty: Qty
    close: bool
    decision_px: Price
    reason: str


@dataclass(frozen=True)
class StopRequest:
    """Place a stop-loss (``kind == "sl"``) or take-profit (``"tp"``) on a share. ``is_long`` is the direction of
    the position the stop protects."""

    run_id: str
    signal_id: str
    leader: str
    coin: str
    kind: str
    is_long: bool
    qty: Qty
    trigger_px: Price
    trade_id: str
    share_id: str


Request = OpenRequest | AddRequest | ExitRequest | StopRequest


@dataclass(frozen=True)
class Decision:
    """What the gate decided. ``reason`` is ``None`` when approved, else the refusal code. Sizing, leverage and
    margin fields are ``None`` when they were not reached or do not apply (exits)."""

    approved: bool
    reason: str | None
    action: ActionKind | None
    client_order_id: str | None
    mirror_notional_usd: Decimal | None
    risk_notional_usd: Decimal | None
    final_notional_usd: Decimal | None
    qty: Qty | None
    initial_risk_usd: Decimal | None
    leverage: int | None
    leverage_ceiling: int | None
    posted_margin_usd: Decimal | None
    liquidation_px: Price | None
    checks: tuple[RiskCheckResult, ...]


@dataclass(frozen=True)
class Outcome:
    """``decision`` and the broker's synchronous answer (``None`` when the gate refused and nothing was sent)."""

    decision: Decision
    result: SubmitResult | None
