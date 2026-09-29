"""Fill export and honest aggregates (F2.AC4, AC5).

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from copytrade.core.money import Pnl

FILLS_CSV_HEADER = "time,coin,side,qty,price,fee,funding,client_order_id,trade_id,share_id,exit_reason"


@dataclass(frozen=True)
class TradeAggregate:
    """Totals over every trade record."""

    trade_count: int
    total_pnl_usd: Pnl


def export_fills(directory: Path, *, from_ms: int, to_ms: int, out: TextIO) -> int:
    """Write CSV (header ``FILLS_CSV_HEADER``, then one row per ``fill`` record whose fill time is in
    ``[from_ms, to_ms)``, in ledger order) to ``out`` and return the number of rows.

    Time is ISO-8601 UTC ending in ``Z``; Decimals are plain (no exponent) strings that round-trip
    exactly; ``exit_reason`` is empty for entries; fields are quoted by the ``csv`` rules.
    Reads only; works while a writer holds the ledger.

    Raises:
        ValueError: ``from_ms`` > ``to_ms``.
        LedgerCorruptError: the ledger does not verify; nothing is written to ``out``.
    """
    raise NotImplementedError


def aggregate_trades(directory: Path) -> TradeAggregate:
    """Count and sum the USD P&L of every ``trade`` record. There is deliberately no way to exclude any.

    Raises:
        LedgerCorruptError: the ledger does not verify.
    """
    raise NotImplementedError
