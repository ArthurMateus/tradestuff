"""Ledger record types (F2.AC1, AC2, AC4, AC5).

- ``LedgerRecord.hash`` is a 64-character lowercase hex sha256. ``h_n = sha256(bytes.fromhex(h_{n-1}) +
  canonical_bytes(record_n))``, with ``h_0 = bytes.fromhex(GENESIS_HASH)``.
- ``canonical_bytes`` covers ``seq``, ``ts``, ``kind``, ``client_order_id`` and ``payload`` (not ``hash``). It is
  deterministic and independent of dict key order. The stored line of a record is the same canonical JSON with
  the ``hash`` added, so every byte of a line is either hashed or is the hash itself.
- Payload values may be ``str``, ``int``, ``bool``, ``None``, finite ``Decimal``, lists and dicts with ``str``
  keys (see ``copytrade.ledger.codec``). Floats, NaN/Infinity, non-str keys and any other type raise
  (``TypeError`` for a wrong type, ``ValueError`` for a bad value). Decimals round-trip exactly.
- The typed records below validate at construction, so an invalid record can never reach the ledger.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypeVar

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.money import Fee, Funding, Pnl, Price, Qty
from copytrade.ledger.codec import decode_value, dumps, encode_value

GENESIS_HASH = "0" * 64
KIND_DECISION = "decision"
KIND_FILL = "fill"
KIND_TRADE = "trade"
RESERVED_KINDS = frozenset({KIND_DECISION, KIND_FILL, KIND_TRADE})

OUTCOMES = frozenset({"taken", "unexecutable", "conflict", "duplicate", "out_of_scope", "pre_existing"})
REJECTED_PREFIX = "rejected:"
TRADE_FLAGS = frozenset(
    {"reconstructed", "unreconstructable", "delisted_force_settle", "liquidated", "marked", "manual_flatten"}
)
FILL_SIDES = frozenset({"buy", "sell"})

_LINE_KEYS = frozenset({"client_order_id", "hash", "kind", "payload", "seq", "ts"})
_TS_KEYS = frozenset({"ms", "source"})
_MONEY = TypeVar("_MONEY", bound=Decimal)
_ITEM = TypeVar("_ITEM")


@dataclass(frozen=True)
class LedgerRecord:
    """One stored record. ``ts`` is the local receive time (``TimeSource.LOCAL``) from the injected clock.

    ``client_order_id`` is set only on records appended as orders (A5); it is covered by the hash.
    """

    seq: int
    ts: Timestamp
    kind: str
    payload: Mapping[str, Any]
    hash: str
    client_order_id: str | None = None


def _envelope(record: LedgerRecord) -> dict[str, Any]:
    if not isinstance(record.payload, Mapping):
        raise TypeError("a record payload must be a mapping")
    return {
        "client_order_id": record.client_order_id,
        "kind": record.kind,
        "payload": encode_value(record.payload),
        "seq": record.seq,
        "ts": {"ms": record.ts.ms, "source": record.ts.source.value},
    }


def canonical_bytes(record: LedgerRecord) -> bytes:
    """Deterministic bytes of ``seq``, ``ts``, ``kind``, ``client_order_id`` and ``payload`` (never ``hash``)."""
    return dumps(_envelope(record))


def encode_line(record: LedgerRecord) -> bytes:
    """The stored form of ``record``: canonical JSON including ``hash``, then ``\\n``."""
    envelope = _envelope(record)
    envelope["hash"] = record.hash
    return dumps(envelope) + b"\n"


def decode_line(line: bytes) -> LedgerRecord:
    """Parse one stored line (without its newline) into a record. Never trusts it: the caller verifies hash,
    sequence and that ``encode_line`` reproduces the same bytes.

    Raises:
        ValueError: the line is not a well-formed stored record.
    """
    try:
        parsed = json.loads(line.decode("ascii"), parse_float=_reject_number, parse_constant=_reject_number)
        return _record_from_json(parsed)
    except (TypeError, KeyError, RecursionError) as exc:
        raise ValueError("line is not a well-formed record") from exc


def _reject_number(_: str) -> Any:
    raise ValueError("stored records hold no floats or non-finite numbers")


def _record_from_json(parsed: object) -> LedgerRecord:
    if not isinstance(parsed, dict) or parsed.keys() != _LINE_KEYS:
        raise ValueError("record fields are not exactly the stored set")
    seq, kind, digest, coid = parsed["seq"], parsed["kind"], parsed["hash"], parsed["client_order_id"]
    ts, payload = parsed["ts"], parsed["payload"]
    if type(seq) is not int or type(kind) is not str or type(digest) is not str:
        raise ValueError("record field has the wrong type")
    if coid is not None and type(coid) is not str:
        raise ValueError("client_order_id has the wrong type")
    if not isinstance(ts, dict) or ts.keys() != _TS_KEYS or type(ts["source"]) is not str:
        raise ValueError("record timestamp is malformed")
    if not isinstance(payload, dict):
        raise TypeError("record payload is not an object")
    return LedgerRecord(
        seq=seq,
        ts=Timestamp(ts["ms"], TimeSource(ts["source"])),
        kind=kind,
        payload=decode_value(payload),
        hash=digest,
        client_order_id=coid,
    )


# --- field validation --------------------------------------------------------------------------------


def _text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str")
    if not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value


def _int(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an int")
    return value


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool")
    return value


def _timestamp(value: object, name: str, source: TimeSource | None = None) -> Timestamp:
    if not isinstance(value, Timestamp):
        raise TypeError(f"{name} must be a Timestamp")
    if source is not None and value.source is not source:
        raise ValueError(f"{name} must have source {source.value}")
    return value


def _money(value: object, kind: type[_MONEY], name: str) -> _MONEY:
    if not isinstance(value, kind):
        raise TypeError(f"{name} must be a {kind.__name__}")
    return value


def _rule_operand(value: object, name: str) -> Decimal | str:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{name} must be finite")
        return value
    if isinstance(value, str):
        return value
    raise TypeError(f"{name} must be a Decimal or str")


def _tuple_of(items: object, kind: type[_ITEM], name: str) -> tuple[_ITEM, ...]:
    if not isinstance(items, (tuple, list)):
        raise TypeError(f"{name} must be a tuple")
    if not all(isinstance(item, kind) for item in items):
        raise TypeError(f"{name} must hold only {kind.__name__}")
    return tuple(items)


def _timestamp_payload(value: Timestamp) -> dict[str, Any]:
    return {"ms": value.ms, "source": value.source.value}


# --- typed records -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleResult:
    """One filter rule: the input value it saw, its threshold and whether it passed."""

    rule: str
    input_value: Decimal | str
    threshold: Decimal | str
    passed: bool

    def __post_init__(self) -> None:
        _text(self.rule, "rule")
        _rule_operand(self.input_value, "input_value")
        _rule_operand(self.threshold, "threshold")
        _bool(self.passed, "passed")


@dataclass(frozen=True)
class RiskCheckResult:
    """One risk-gate check result."""

    check: str
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        _text(self.check, "check")
        _bool(self.passed, "passed")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a str")


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

    def __post_init__(self) -> None:
        for name in ("signal_id", "leader", "coin", "event_type"):
            _text(getattr(self, name), name)
        _timestamp(self.exchange_ts, "exchange_ts", TimeSource.EXCHANGE)
        _timestamp(self.local_receive_ts, "local_receive_ts", TimeSource.LOCAL)
        _int(self.clock_offset_ms, "clock_offset_ms")
        object.__setattr__(self, "filter_results", _tuple_of(self.filter_results, RuleResult, "filter_results"))
        object.__setattr__(self, "risk_checks", _tuple_of(self.risk_checks, RiskCheckResult, "risk_checks"))
        for name in ("mirror_size", "risk_cap_size", "final_size"):
            _money(getattr(self, name), Qty, name)
        _money(self.price_used, Price, "price_used")
        object.__setattr__(self, "latency_ms", _latency(self.latency_ms))
        _outcome(self.outcome)

    def to_payload(self) -> dict[str, Any]:
        """The ledger payload of this decision."""
        return {
            "signal_id": self.signal_id,
            "leader": self.leader,
            "coin": self.coin,
            "event_type": self.event_type,
            "exchange_ts": _timestamp_payload(self.exchange_ts),
            "local_receive_ts": _timestamp_payload(self.local_receive_ts),
            "clock_offset_ms": self.clock_offset_ms,
            "filter_results": [
                {"rule": r.rule, "input_value": r.input_value, "threshold": r.threshold, "passed": r.passed}
                for r in self.filter_results
            ],
            "risk_checks": [{"check": c.check, "passed": c.passed, "detail": c.detail} for c in self.risk_checks],
            "mirror_size": self.mirror_size,
            "risk_cap_size": self.risk_cap_size,
            "final_size": self.final_size,
            "price_used": self.price_used,
            "latency_ms": dict(self.latency_ms),
            "outcome": self.outcome,
        }


def _latency(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise TypeError("latency_ms must be a mapping of stage to milliseconds")
    if not value:
        raise ValueError("latency_ms must name at least one stage")
    stages: dict[str, int] = {}
    for stage, ms in value.items():
        _text(stage, "latency stage")
        if _int(ms, "latency value") < 0:
            raise ValueError("latency values must not be negative")
        stages[stage] = ms
    return stages


def _outcome(value: object) -> None:
    text = _text(value, "outcome")
    if text in OUTCOMES:
        return
    if text.startswith(REJECTED_PREFIX) and text[len(REJECTED_PREFIX) :].strip():
        return
    raise ValueError("outcome is not a known outcome or 'rejected:<reason>'")


@dataclass(frozen=True)
class FillRecord:
    """One paper fill (F2.AC4, E5).

    Validation raises ``ValueError``: ``side`` not in ``FILL_SIDES``; ``qty`` not > 0; empty coin,
    ``client_order_id``, ``trade_id`` or ``share_id``; ``exit_reason`` empty when given; a ``time`` outside
    the years 1 to 9999. ``exit_reason`` is ``None`` for entries.
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

    def __post_init__(self) -> None:
        _timestamp(self.time, "time")
        try:
            self.time.to_datetime()
        except OverflowError as exc:
            raise ValueError("time is outside the representable range") from exc
        for name in ("coin", "client_order_id", "trade_id", "share_id"):
            _text(getattr(self, name), name)
        if self.side not in FILL_SIDES:
            raise ValueError("side must be 'buy' or 'sell'")
        if _money(self.qty, Qty, "qty") <= 0:
            raise ValueError("qty must be positive (the side carries the direction)")
        _money(self.price, Price, "price")
        _money(self.fee, Fee, "fee")
        _money(self.funding, Funding, "funding")
        if self.exit_reason is not None:
            _text(self.exit_reason, "exit_reason")

    def to_payload(self) -> dict[str, Any]:
        """The ledger payload of this fill."""
        return {
            "time": _timestamp_payload(self.time),
            "coin": self.coin,
            "side": self.side,
            "qty": self.qty,
            "price": self.price,
            "fee": self.fee,
            "funding": self.funding,
            "client_order_id": self.client_order_id,
            "trade_id": self.trade_id,
            "share_id": self.share_id,
            "exit_reason": self.exit_reason,
        }


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

    def __post_init__(self) -> None:
        for name in ("trade_id", "share_id", "coin"):
            _text(getattr(self, name), name)
        _timestamp(self.closed_at, "closed_at")
        _money(self.pnl_usd, Pnl, "pnl_usd")
        given: object = self.flags
        if isinstance(given, str) or not isinstance(given, Iterable):
            raise TypeError("flags must be a collection of flag names")
        flags = frozenset(given)
        unknown = flags - TRADE_FLAGS
        if unknown:
            raise ValueError("unknown trade flag")
        object.__setattr__(self, "flags", flags)

    def to_payload(self) -> dict[str, Any]:
        """The ledger payload of this trade."""
        return {
            "trade_id": self.trade_id,
            "share_id": self.share_id,
            "coin": self.coin,
            "closed_at": _timestamp_payload(self.closed_at),
            "pnl_usd": self.pnl_usd,
            "flags": sorted(self.flags),
        }


# --- decoding ----------------------------------------------------------------------------------------

_R = TypeVar("_R")


def _decode(record: LedgerRecord, kind: str, build: Callable[[Mapping[str, Any]], _R]) -> _R:
    if record.kind != kind:
        raise ValueError(f"record {record.seq} is a {record.kind!r} record, not {kind!r}")
    try:
        return build(record.payload)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"record {record.seq} does not hold a valid {kind}") from exc


def _stored_timestamp(value: Mapping[str, Any]) -> Timestamp:
    return Timestamp(value["ms"], TimeSource(value["source"]))


def _stored_decimal(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("stored amount is not a Decimal")
    return value


def _build_decision(p: Mapping[str, Any]) -> DecisionRecord:
    return DecisionRecord(
        signal_id=p["signal_id"],
        leader=p["leader"],
        coin=p["coin"],
        event_type=p["event_type"],
        exchange_ts=_stored_timestamp(p["exchange_ts"]),
        local_receive_ts=_stored_timestamp(p["local_receive_ts"]),
        clock_offset_ms=p["clock_offset_ms"],
        filter_results=tuple(
            RuleResult(r["rule"], r["input_value"], r["threshold"], r["passed"]) for r in p["filter_results"]
        ),
        risk_checks=tuple(RiskCheckResult(c["check"], c["passed"], c["detail"]) for c in p["risk_checks"]),
        mirror_size=Qty(_stored_decimal(p["mirror_size"])),
        risk_cap_size=Qty(_stored_decimal(p["risk_cap_size"])),
        final_size=Qty(_stored_decimal(p["final_size"])),
        price_used=Price(_stored_decimal(p["price_used"])),
        latency_ms=p["latency_ms"],
        outcome=p["outcome"],
    )


def _build_fill(p: Mapping[str, Any]) -> FillRecord:
    return FillRecord(
        time=_stored_timestamp(p["time"]),
        coin=p["coin"],
        side=p["side"],
        qty=Qty(_stored_decimal(p["qty"])),
        price=Price(_stored_decimal(p["price"])),
        fee=Fee(_stored_decimal(p["fee"])),
        funding=Funding(_stored_decimal(p["funding"])),
        client_order_id=p["client_order_id"],
        trade_id=p["trade_id"],
        share_id=p["share_id"],
        exit_reason=p["exit_reason"],
    )


def _build_trade(p: Mapping[str, Any]) -> TradeRecord:
    return TradeRecord(
        trade_id=p["trade_id"],
        share_id=p["share_id"],
        coin=p["coin"],
        closed_at=_stored_timestamp(p["closed_at"]),
        pnl_usd=Pnl(_stored_decimal(p["pnl_usd"])),
        flags=frozenset(p["flags"]),
    )


def decode_decision(record: LedgerRecord) -> DecisionRecord:
    """Rebuild the ``DecisionRecord`` stored in a ``decision`` record. ``ValueError`` for another kind."""
    return _decode(record, KIND_DECISION, _build_decision)


def decode_fill(record: LedgerRecord) -> FillRecord:
    """Rebuild the ``FillRecord`` stored in a ``fill`` record. ``ValueError`` for another kind."""
    return _decode(record, KIND_FILL, _build_fill)


def decode_trade(record: LedgerRecord) -> TradeRecord:
    """Rebuild the ``TradeRecord`` stored in a ``trade`` record. ``ValueError`` for another kind."""
    return _decode(record, KIND_TRADE, _build_trade)
