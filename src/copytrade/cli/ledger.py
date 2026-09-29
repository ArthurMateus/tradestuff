"""``copytrade ledger verify`` and ``copytrade export fills`` (F2.AC1, AC4).

Interface stub written by the test designer. The developer owns the implementation.

- ``copytrade ledger verify --ledger-dir DIR``: prints the record count and returns 0; on failure prints
  the failing seq to stderr and returns non-zero.
- ``copytrade export fills --ledger-dir DIR --from ISO --to ISO [--out FILE]``: ISO-8601 instants with an
  explicit UTC ``Z`` (or offset); writes CSV to FILE, or to stdout when ``--out`` is absent.
"""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``ledger`` and ``export`` subcommands (registry contract of ``cli/main.py``)."""
    raise NotImplementedError
