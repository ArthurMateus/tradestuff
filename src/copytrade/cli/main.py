"""CLI entry point and subcommand registry (F1).

Built-in subcommand:
    ``copytrade start [--root PATH]``: run ``copytrade.core.startup.startup`` with ``os.environ``,
    ``code_root`` = the repository that contains the imported ``copytrade`` package, and the files of
    every loaded ``copytrade``/``copytrade.*`` module. ``--root`` defaults to that same repository.
    Any ``CopytradeError`` prints one line naming the key or file to stderr and returns a non-zero exit
    code. There is no flag that selects a trading mode.

Other areas add subcommands through ``copytrade/cli/<area>.py`` modules discovered at runtime
(§10 collision rule 3), so they never edit this file.

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` (default ``sys.argv[1:]``), dispatch, and return the process exit code."""
    raise NotImplementedError
