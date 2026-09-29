"""Fill export and honest aggregates (F2.AC4, AC5).

Both read the ledger without taking the writer lock and only after the whole chain verified: a tampered
ledger produces no output and no total.
"""

from __future__ import annotations

import csv
import tempfile
from dataclasses import dataclass
from decimal import Context, Decimal, Inexact, Rounded
from pathlib import Path
from typing import TextIO

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.money import Pnl
from copytrade.ledger.records import KIND_FILL, KIND_TRADE, FillRecord, decode_fill, decode_trade
from copytrade.ledger.store import read_records

_SPOOL_BYTES = 8 * 1024 * 1024
# Exact addition: 1000 digits is far beyond any stored amount, and rounding would raise instead of drifting.
_EXACT = Context(prec=1000, traps=[Inexact, Rounded])
FILLS_CSV_HEADER = "time,coin,side,qty,price,fee,funding,client_order_id,trade_id,share_id,exit_reason"


@dataclass(frozen=True)
class TradeAggregate:
    """Totals over every trade record."""

    trade_count: int
    total_pnl_usd: Pnl


def _plain(value: Decimal) -> str:
    """Positional notation (never ``1E+3``) with the exact digits and scale of ``value``."""
    return format(value, "f")


def _iso_utc(ms: int) -> str:
    return (
        Timestamp(ms, TimeSource.DERIVED).to_datetime().isoformat(timespec="milliseconds").removesuffix("+00:00") + "Z"
    )


def _row(fill: FillRecord) -> list[str]:
    return [
        _iso_utc(fill.time.ms),
        fill.coin,
        fill.side,
        _plain(fill.qty),
        _plain(fill.price),
        _plain(fill.fee),
        _plain(fill.funding),
        fill.client_order_id,
        fill.trade_id,
        fill.share_id,
        fill.exit_reason or "",
    ]


def export_fills(directory: Path, *, from_ms: int, to_ms: int, out: TextIO) -> int:
    """Write CSV (header ``FILLS_CSV_HEADER``, then one row per ``fill`` record whose fill time is in
    ``[from_ms, to_ms)``, in ledger order) to ``out`` and return the number of rows.

    Time is ISO-8601 UTC ending in ``Z``; Decimals are plain (no exponent) strings that round-trip
    exactly; ``exit_reason`` is empty for entries; fields are quoted by the ``csv`` rules and rows end in
    ``\\n``. Reads only; works while a writer holds the ledger. Rows are staged while the chain is verified,
    so ``out`` receives nothing unless the whole ledger verifies.

    Raises:
        ValueError: ``from_ms`` > ``to_ms``.
        LedgerCorruptError: the ledger does not verify; nothing is written to ``out``.
    """
    if from_ms > to_ms:
        raise ValueError("from_ms must not be after to_ms")
    count = 0
    with tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES, mode="w+", encoding="utf-8", newline="") as staged:
        writer = csv.writer(staged, lineterminator="\n")
        writer.writerow(FILLS_CSV_HEADER.split(","))
        for record in read_records(directory):
            if record.kind != KIND_FILL:
                continue
            fill = decode_fill(record)
            if from_ms <= fill.time.ms < to_ms:
                writer.writerow(_row(fill))
                count += 1
        staged.seek(0)
        while chunk := staged.read(1 << 16):
            out.write(chunk)
    return count


def aggregate_trades(directory: Path) -> TradeAggregate:
    """Count and sum the USD P&L of every ``trade`` record. There is deliberately no way to exclude any.

    Raises:
        LedgerCorruptError: the ledger does not verify.
    """
    count = 0
    total = Decimal(0)
    for record in read_records(directory):
        if record.kind == KIND_TRADE:
            total = _EXACT.add(total, decode_trade(record).pnl_usd)
            count += 1
    return TradeAggregate(trade_count=count, total_pnl_usd=Pnl(total))
