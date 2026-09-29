"""``copytrade ledger verify`` and ``copytrade export fills`` (F2.AC1, AC4).

- ``copytrade ledger verify --ledger-dir DIR``: prints the record count and returns 0; on failure prints
  the failing seq to stderr and returns non-zero.
- ``copytrade export fills --ledger-dir DIR --from ISO --to ISO [--out FILE]``: ISO-8601 instants with an
  explicit UTC ``Z`` (or offset); writes CSV to FILE, or to stdout when ``--out`` is absent. The range is
  half-open, ``[from, to)``, on each fill's own time. FILE only appears once the export succeeded.

Both commands only read: they take no lock and work while the engine runs. The ledger directory is a flag
here; defaulting it from ``storage.ledger_dir`` is done where the engine is wired (F21).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from copytrade.ledger.export import export_fills
from copytrade.ledger.store import verify_ledger

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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
    except OverflowError as exc:  # the UTC instant falls outside years 1..9999
        raise argparse.ArgumentTypeError(f"{text!r} is outside the supported range of instants") from exc


def _run_verify(args: argparse.Namespace) -> int:
    try:
        result = verify_ledger(args.ledger_dir)
    except OSError as exc:
        print(f"copytrade: cannot read the ledger: {exc.strerror or type(exc).__name__}", file=sys.stderr)
        return 1
    if result.ok:
        print(f"ledger OK: {result.record_count} records verified")
        return 0
    print(f"copytrade: ledger corrupt at seq {result.failed_seq}: {result.reason}", file=sys.stderr)
    return 1


def _run_export_fills(args: argparse.Namespace) -> int:
    try:
        if args.out is None:
            staged = io.StringIO()
            count = export_fills(args.ledger_dir, from_ms=args.from_ms, to_ms=args.to_ms, out=staged)
            sys.stdout.write(staged.getvalue())
        else:
            count = _export_to_file(args)
    except ValueError as exc:
        print(f"copytrade: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"copytrade: cannot export: {exc.strerror or type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"exported {count} fills", file=sys.stderr)
    return 0


def _export_to_file(args: argparse.Namespace) -> int:
    """Export to a temporary file next to ``--out`` and move it into place only when complete."""
    target: Path = args.out
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            count = export_fills(args.ledger_dir, from_ms=args.from_ms, to_ms=args.to_ms, out=handle)
        os.replace(temporary, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    return count


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``ledger`` and ``export`` subcommands (registry contract of ``cli/main.py``)."""
    ledger = subparsers.add_parser("ledger", help="inspect the append-only ledger")
    ledger_commands = ledger.add_subparsers(dest="ledger_command", required=True, metavar="ACTION")
    verify = ledger_commands.add_parser("verify", help="verify the hash chain; non-zero exit names the failing seq")
    verify.add_argument("--ledger-dir", type=Path, required=True, help="directory holding the ledger")
    verify.set_defaults(handler=_run_verify)

    export = subparsers.add_parser("export", help="export records for tax and audit")
    export_commands = export.add_subparsers(dest="export_command", required=True, metavar="WHAT")
    fills = export_commands.add_parser("fills", help="CSV of paper fills in [--from, --to)")
    fills.add_argument("--ledger-dir", type=Path, required=True, help="directory holding the ledger")
    fills.add_argument(
        "--from",
        dest="from_ms",
        type=_utc_instant_ms,
        required=True,
        metavar="ISO",
        help="inclusive, e.g. 2026-01-01T00:00:00Z",
    )
    fills.add_argument("--to", dest="to_ms", type=_utc_instant_ms, required=True, metavar="ISO", help="exclusive")
    fills.add_argument("--out", type=Path, default=None, help="file to write (default: stdout)")
    fills.set_defaults(handler=_run_export_fills)
