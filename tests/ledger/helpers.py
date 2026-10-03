"""Helpers for the F2 tests: a fake clock, record builders and byte-level tamper tools.

Test utilities only; they never re-implement the unit under test.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.money import Fee, Funding, Pnl, Price, Qty
from copytrade.ledger.records import (
    DecisionRecord,
    FillRecord,
    RiskCheckResult,
    RuleResult,
    TradeRecord,
)
from copytrade.ledger.store import LEDGER_FILENAME

T0 = 1_790_000_000_000  # 2026-09-21T14:13:20Z in epoch ms

OUTCOME_CYCLE = (
    "taken",
    "rejected:slippage",
    "rejected:stale_signal",
    "unexecutable",
    "conflict",
    "duplicate",
    "out_of_scope",
    "pre_existing",
)
REQUIRED_TRADE_FLAGS = (
    "reconstructed",
    "unreconstructable",
    "delisted_force_settle",
    "liquidated",
    "marked",
    "manual_flatten",
)


class FakeClock:
    """The injected local clock (an external boundary)."""

    def __init__(self, now_ms: int = T0) -> None:
        self.now = now_ms

    def now_ms(self) -> int:
        return self.now


def ledger_file(directory: Path) -> Path:
    return directory / LEDGER_FILENAME


def make_decision(i: int, outcome: str | None = None) -> DecisionRecord:
    return DecisionRecord(
        signal_id=f"sig-{i}",
        leader=f"0x{i:040x}",
        coin=("BTC", "ETH", "SOL", "DOGE")[i % 4],
        event_type=("open", "add", "reduce", "close", "flip")[i % 5],
        exchange_ts=Timestamp(T0 + i * 10, TimeSource.EXCHANGE),
        local_receive_ts=Timestamp(T0 + i * 10 + 120, TimeSource.LOCAL),
        clock_offset_ms=-35 + i,
        filter_results=(
            RuleResult("slippage_pct", Decimal("0.12"), Decimal("0.30"), True),
            RuleResult("trend", "up", "up", i % 2 == 0),
        ),
        risk_checks=(RiskCheckResult("max_open_positions", True, "3 of 9"), RiskCheckResult("kill_switch", True, "off")),
        mirror_size=Qty(f"{i + 1}.500"),
        risk_cap_size=Qty("2.25"),
        final_size=Qty("2.25"),
        price_used=Price("67123.4"),
        latency_ms={"S1": 640 + i, "S2": 3, "S3": 17, "S4": 8},
        outcome=outcome if outcome is not None else OUTCOME_CYCLE[i % len(OUTCOME_CYCLE)],
    )


def make_fill(i: int, *, time_ms: int | None = None, exit_reason: str | None = None) -> FillRecord:
    return FillRecord(
        time=Timestamp(T0 + i * 1000 if time_ms is None else time_ms, TimeSource.DERIVED),
        coin=("BTC", "ETH", "SOL")[i % 3],
        side=("buy", "sell")[i % 2],
        qty=Qty(f"0.{i + 1:03d}"),
        price=Price(f"{60000 + i}.5"),
        fee=Fee("0.0125"),
        funding=Funding("-0.0031"),
        client_order_id=f"coid-{i}",
        trade_id=f"trade-{i // 2}",
        share_id=f"share-{i % 3}",
        exit_reason=exit_reason,
    )


def make_trade(i: int, pnl: str, flags: frozenset[str] = frozenset()) -> TradeRecord:
    return TradeRecord(
        trade_id=f"trade-{i}",
        share_id=f"share-{i % 3}",
        coin=("BTC", "ETH", "SOL")[i % 3],
        closed_at=Timestamp(T0 + i * 60_000, TimeSource.DERIVED),
        pnl_usd=Pnl(pnl),
        flags=flags,
    )


def raw_lines(directory: Path) -> list[bytes]:
    """The stored lines, newline kept."""
    return ledger_file(directory).read_bytes().splitlines(keepends=True)


def flip_byte(directory: Path, offset: int) -> None:
    """Alter exactly one byte of the ledger file (XOR 0x01, so it always changes)."""
    path = ledger_file(directory)
    data = bytearray(path.read_bytes())
    data[offset] ^= 0x01
    path.write_bytes(bytes(data))


def line_span(directory: Path, seq: int) -> tuple[int, int]:
    """(start offset, end offset exclusive) of the 1-based line ``seq``, newline included."""
    start = 0
    for n, line in enumerate(raw_lines(directory), start=1):
        if n == seq:
            return start, start + len(line)
        start += len(line)
    raise IndexError(seq)


def expected_hash(prev_hex: str, canonical: bytes) -> str:
    return hashlib.sha256(bytes.fromhex(prev_hex) + canonical).hexdigest()
