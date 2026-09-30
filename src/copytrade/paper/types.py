"""Value types of the paper broker (F11). Data only; every amount is Decimal-based (A6), units are in the names (A9)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.ledger.records import FillRecord, TradeRecord


@dataclass(frozen=True)
class CoinMeta:
    """One coin's exchange rules: ``sz_decimals`` (lot) and ``max_leverage`` (integer x)."""

    sz_decimals: int
    max_leverage: int


@dataclass(frozen=True)
class FundingSnapshot:
    """Funding for the hour starting at ``hour_ms``: hourly ``rate`` (fraction, 0.0001 = 1 bp; positive means
    longs pay) and the ``oracle_px`` used for it."""

    coin: str
    hour_ms: int
    rate: Decimal
    oracle_px: Price


@dataclass(frozen=True)
class MarkUpdate:
    """A mark price observation for ``coin`` at exchange time ``time_ms``."""

    coin: str
    mark: Price
    time_ms: int


@dataclass(frozen=True)
class OrderIntent:
    """A market order the risk gate (F10) has approved. ``side`` is ``"buy"`` or ``"sell"``.

    ``qty`` is positive coin units. ``action`` OPEN/ADD are entries, REDUCE/CLOSE are reduce-only exits.
    ``decided_at_ms`` is the decision time; the fill is at ``decided_at_ms + paper.ack_delay_ms``.
    ``decision_px`` is the price the notional checks use. ``leverage`` (integer x) is required for OPEN/ADD and
    ``None`` for exits. ``exit_reason`` is ``None`` for entries.
    """

    client_order_id: str
    coin: str
    side: str
    qty: Qty
    action: ActionKind
    decided_at_ms: int
    decision_px: Price
    trade_id: str
    share_id: str
    leverage: int | None
    exit_reason: str | None


@dataclass(frozen=True)
class StopIntent:
    """A stop-loss (``kind == "sl"``) or take-profit (``"tp"``) order on a share, triggered on the mark.

    ``side`` is the closing side. The order is placed through the gate; the later trigger fill needs no new token.
    """

    client_order_id: str
    coin: str
    kind: str
    side: str
    qty: Qty
    trigger_px: Price
    trade_id: str
    share_id: str


@dataclass(frozen=True)
class GateToken:
    """Proof that the risk gate approved one specific intent. Issued only by ``GateAuthority`` (F10 holds it).

    Fields are opaque to callers: ``token_id`` is unique, ``intent_digest`` binds the token to the exact intent
    (coin, side, qty, action, client order ID, ids, leverage), and ``mac`` authenticates both under the
    authority's secret key. A token is single-use.
    """

    token_id: str
    intent_digest: str
    mac: str


@dataclass(frozen=True)
class SubmitResult:
    """Synchronous answer of ``submit`` / ``place_stop``. ``reason`` is ``None`` when accepted, else one of
    ``invalid_gate_token``, ``gate_token_reused``, ``duplicate_client_order_id``, ``unknown_coin``, ``delisted``,
    ``meta_unavailable``, ``below_min_notional``, ``exceeds_position``, ``leverage_exceeds_max``, ``leverage_missing``,
    and, for input that is malformed rather than merely refused by an exchange rule, ``invalid_side``,
    ``invalid_qty``, ``leverage_invalid``, ``invalid_stop_kind`` and ``invalid_trigger``. ``exceeds_position`` also
    covers an exit or stop with no share of ours to reduce in that direction. Every refusal is logged
    (``paper_reject``); a validated gate token is consumed by any refusal after ``invalid_gate_token``.
    """

    client_order_id: str
    accepted: bool
    reason: str | None


@dataclass(frozen=True)
class BrokerEvent:
    """Something that happened, also written to the ledger (A8: each kind is explicit, never "error").

    ``kind`` is one of ``fill``, ``partial_fill``, ``reject``, ``liquidated``, ``delisted_force_settle``,
    ``exit_unfilled_alert``. ``reason`` is set for ``reject`` (``no_book``, ``no_depth``, ``delisted``, and at fill time
    ``exceeds_position`` and ``liquidation_unrepresentable``, the two ways an order accepted earlier can turn out
    unfillable because the position changed or its liquidation price is off the exchange grid).
    ``fill`` is set for fills, partial fills, liquidations and settlements; ``trade`` when the fill closed a share.
    """

    kind: str
    time_ms: int
    coin: str
    client_order_id: str | None
    reason: str | None
    fill: FillRecord | None
    trade: TradeRecord | None


@dataclass(frozen=True)
class PositionView:
    """The merged isolated position on one coin. ``qty`` is signed (long > 0). ``avg_entry_px`` is the
    qty-weighted entry price, ``margin_usd`` is ``qty * avg_entry_px / leverage``."""

    coin: str
    qty: Qty
    avg_entry_px: Price
    leverage: int
    margin_usd: Decimal
    liquidation_px: Price
    share_ids: tuple[str, ...]
