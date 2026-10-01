"""``copytrade run [--root PATH]``: start the paper-trading runner (paper only; there is no mode flag)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import copytrade
from copytrade.runner.app import run_app

_CODE_ROOT = Path(copytrade.__file__ or "").resolve().parents[2]


def _run(args: argparse.Namespace) -> int:
    root: Path = args.root
    # The ONE place the process environment is read: the COPYTRADE_* variables carry the secrets.
    return run_app(root, os.environ, deps=None, stop=None, out=sys.stdout, err=sys.stderr)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("run", help="run the copy-trading bot in paper mode (there is no mode option)")
    parser.add_argument(
        "--root", type=Path, default=_CODE_ROOT, help="repository root (default: the repository of this checkout)"
    )
    parser.set_defaults(handler=_run)
