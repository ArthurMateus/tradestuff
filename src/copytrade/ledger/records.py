"""Ledger record types (F2.AC1, AC2, AC4, AC5).

Interface stub written by the test designer. The developer owns the implementation.

Conventions the tests rely on:
- ``LedgerRecord.hash`` is a 64-character lowercase hex sha256. ``h_n = sha256(bytes.fromhex(h_{n-1}) +
  canonical_bytes(record_n))``, with ``h_0 = bytes.fromhex(GENESIS_HASH)``.
- ``canonical_bytes`` covers ``seq``, ``ts``, ``kind`` and ``payload`` (not ``hash``). It is deterministic
  and independent of dict key order.
- Payload values may be ``str``, ``int``, ``bool``, ``None``, finite ``Decimal``, lists and dicts with
  ``str`` keys. Floats, NaN/Infinity, non-str keys and any other type raise (``TypeError`` for a wrong
  type, ``ValueError`` for a bad value). Decimals round-trip exactly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from copytrade.core.clock import Timestamp
from copytrade.core.money import Fee, Funding, Pnl, Price, Qty

GENESIS_HASH = "0" * 64
KIND_DECISION = "decision"
KIND_FILL = "fill"
KIND_TRADE = "trade"

OUTCOMES = frozenset({"taken", "unexecutable", "conflict", "duplicate", "out_of_scope", "pre_existing"})
REJECTED_PREFIX = "rejected:"
TRADE_FLAGS = frozenset(
    {"reconstructed", "unreconstructable", "delisted_force_settle", "liquidated", "marked", "manual_flatten"}
)
FILL_SIDES = frozenset({"buy", "sell"})


@dataclass(frozen=True)
class LedgerRecord:
    """One stored record. ``ts`` is the local receive time (``TimeSource.LOCAL``) from the injected clock."""

    seq: int
    ts: Timestamp
    kind: str
    payload: Mapping[str, Any]
    hash: str


def canonical_bytes(record: LedgerRecord) -> bytes:
    """Deterministic bytes of ``seq``, ``ts``, ``kind`` and ``payload`` (never ``hash``)."""
    raise NotImplementedError


@dataclass(frozen=True)
class RuleResult:
    """One filter rule: the input value it saw, its threshold and whether it passed."""

    rule: str
    input_value: Decimal | str
    threshold: Decimal | str
    passed: bool


@dataclass(frozen=True)
class RiskCheckResult:
    """One risk-gate check result."""

    check: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DecisionRecord:
    """One decision per signal (F2.AC2, B5).

    Construction validates and raises ``ValueError``/``TypeError`` when: any field is ``None``; a text
    field is empty; ``exchange_ts.source`` is not EXCHANGE or ``local_receive_ts.source`` is not LOCAL;
    ``clock_offset_ms`` is not an int; ``latency_ms`` is empty or has a negative or non-int value;
    ``outcome`` is not one of ``OUTCOMES`` or ``"rejected:<reason>"`` with a non-empty reason.
    Sizes are ``Qty`` (0 when no size was computed); ``price_used`` is ``Price``.
    """

    signal_id: str
    leader: str
    coin: str
    event_type: str
    exchange_ts: Timestamp
    local_receive_ts: Timestamp
    clock_offset_ms: int
    filter_results: tuple[RuleResult, ...]
    risk_checks: tuple[RiskCheckResult, ...]
    mirror_size: Qty
    risk_cap_size: Qty
    final_size: Qty
    price_used: Price
    latency_ms: Mapping[str, int]
    outcome: str


@dataclass(frozen=True)
class FillRecord:
    """One paper fill (F2.AC4, E5).

    Validation raises ``ValueError``: ``side`` not in ``FILL_SIDES``; ``qty`` not > 0; empty coin,
    ``client_order_id``, ``trade_id`` or ``share_id``. ``exit_reason`` is ``None`` for entries.
    """

    time: Timestamp
    coin: str
    side: str
    qty: Qty
    price: Price
    fee: Fee
    funding: Funding
    client_order_id: str
    trade_id: str
    share_id: str
    exit_reason: str | None


@dataclass(frozen=True)
class TradeRecord:
    """One closed (or marked) trade with its net USD P&L (F2.AC5).

    ``flags`` must be a subset of ``TRADE_FLAGS`` (else ``ValueError``).
    """

    trade_id: str
    share_id: str
    coin: str
    closed_at: Timestamp
    pnl_usd: Pnl
    flags: frozenset[str]


def decode_decision(record: LedgerRecord) -> DecisionRecord:
    """Rebuild the ``DecisionRecord`` stored in a ``decision`` record. ``ValueError`` for another kind."""
    raise NotImplementedError


def decode_fill(record: LedgerRecord) -> FillRecord:
    """Rebuild the ``FillRecord`` stored in a ``fill`` record. ``ValueError`` for another kind."""
    raise NotImplementedError


def decode_trade(record: LedgerRecord) -> TradeRecord:
    """Rebuild the ``TradeRecord`` stored in a ``trade`` record. ``ValueError`` for another kind."""
    raise NotImplementedError
