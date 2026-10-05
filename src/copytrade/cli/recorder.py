"""``copytrade recorder gaps`` (F4.AC4).

- ``copytrade recorder gaps --recordings-dir DIR --ledger-dir DIR --from ISO --to ISO``: ISO-8601 instants with an
  explicit UTC ``Z`` or offset. Prints one line per coin: ``<COIN> l2_gap_pct=<x.x> mid_gap_pct=<y.y>`` (percent, one
  decimal). Read-only: it takes no lock and works while the recorder runs. Exit 0; 2 for bad arguments
  (``--to`` not after ``--from``, an instant without an offset); 1 when the ledger or directory is unreadable.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from copytrade.core.errors import CopytradeError
from copytrade.recorder.gaps import gap_stats
from copytrade.recorder.store import RecordingReader

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_PERCENT_PLACES = Decimal("0.1")


def _utc_instant_ms(text: str) -> int:
    """Epoch milliseconds of an ISO-8601 instant that states its zone. Anything else is an argument error."""
    try:
        instant = datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO-8601 instant: {text!r}") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise argparse.ArgumentTypeError(f"{text!r} has no explicit UTC offset (write e.g. 2026-09-21T14:13:20Z)")
    if instant.microsecond % 1000:
        raise argparse.ArgumentTypeError(f"{text!r} is finer than a millisecond")
    try:
        return (instant.astimezone(UTC) - _EPOCH) // timedelta(milliseconds=1)
    except OverflowError as exc:
        raise argparse.ArgumentTypeError(f"{text!r} is outside the supported range of instants") from exc


def _percent(share: Decimal) -> str:
    return str((share * 100).quantize(_PERCENT_PLACES, rounding=ROUND_HALF_UP))


def _run_gaps(args: argparse.Namespace) -> int:
    if args.to_ms <= args.from_ms:
        print("copytrade: --to must be after --from", file=sys.stderr)
        return 2
    for directory in (args.recordings_dir, args.ledger_dir):
        if not directory.is_dir():
            print(f"copytrade: {directory} is not a readable directory", file=sys.stderr)
            return 1
    reader = RecordingReader.from_ledger_dir(args.recordings_dir, args.ledger_dir)
    try:
        stats = gap_stats(reader, args.from_ms, args.to_ms)
    except OSError as exc:
        print(f"copytrade: cannot read the recordings: {exc.strerror or type(exc).__name__}", file=sys.stderr)
        return 1
    except CopytradeError as exc:
        print(f"copytrade: {exc}", file=sys.stderr)
        return 1
    for coin, coin_stats in stats.items():
        print(f"{coin} l2_gap_pct={_percent(coin_stats.l2_gap_share)} mid_gap_pct={_percent(coin_stats.mid_gap_share)}")
    return 0


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    recorder = subparsers.add_parser("recorder", help="recorder tools")
    sub = recorder.add_subparsers(dest="recorder_command", required=True)
    gaps = sub.add_parser("gaps", help="per-coin recording gap statistics")
    gaps.add_argument("--recordings-dir", required=True, type=Path)
    gaps.add_argument("--ledger-dir", required=True, type=Path)
    gaps.add_argument("--from", dest="from_ms", required=True, type=_utc_instant_ms, metavar="ISO")
    gaps.add_argument("--to", dest="to_ms", required=True, type=_utc_instant_ms, metavar="ISO")
    gaps.set_defaults(handler=_run_gaps)
