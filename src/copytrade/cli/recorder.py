"""``copytrade recorder gaps`` (F4.AC4).

- ``copytrade recorder gaps --recordings-dir DIR --ledger-dir DIR --from ISO --to ISO``: ISO-8601 instants with an
  explicit UTC ``Z`` or offset. Prints one line per coin: ``<COIN> l2_gap_pct=<x.x> mid_gap_pct=<y.y>`` (percent, one
  decimal). Read-only: it takes no lock and works while the recorder runs. Exit 0; 2 for bad arguments
  (``--to`` not after ``--from``, an instant without an offset); 1 when the ledger or directory is unreadable.
"""

from __future__ import annotations

import argparse


def _run_gaps(args: argparse.Namespace) -> int:
    raise NotImplementedError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    recorder = subparsers.add_parser("recorder", help="recorder tools")
    sub = recorder.add_subparsers(dest="recorder_command", required=True)
    gaps = sub.add_parser("gaps", help="per-coin recording gap statistics")
    gaps.add_argument("--recordings-dir", required=True)
    gaps.add_argument("--ledger-dir", required=True)
    gaps.add_argument("--from", dest="from_iso", required=True)
    gaps.add_argument("--to", dest="to_iso", required=True)
    gaps.set_defaults(handler=_run_gaps)
