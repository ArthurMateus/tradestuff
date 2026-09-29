"""CLI entry point and subcommand registry (F1).

Built-in subcommand:
    ``copytrade start [--root PATH]``: run ``copytrade.core.startup.startup`` with ``os.environ``,
    ``code_root`` = the repository that contains the imported ``copytrade`` package, and the files of
    every loaded ``copytrade``/``copytrade.*`` module. ``--root`` defaults to that same repository.
    Any ``CopytradeError`` prints one line naming the key or file to stderr and returns a non-zero exit
    code. There is no flag that selects a trading mode.

Other areas add subcommands through ``copytrade/cli/<area>.py`` modules discovered at runtime
(§10 collision rule 3), so they never edit this file. A module (any ``.py`` file in this package whose
name does not start with ``_``) exposes ``register(subparsers)``: it adds its parser with
``subparsers.add_parser(...)`` and sets the handler with ``parser.set_defaults(handler=fn)``, where
``fn(args: argparse.Namespace) -> int`` returns the exit code. A module that fails to import or register
is reported on stderr and skipped, so one broken area never disables the others (the kill switch must
keep working).
"""

from __future__ import annotations

import argparse
import importlib
import os
import pkgutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import copytrade
import copytrade.cli
from copytrade.core.errors import CopytradeError
from copytrade.core.startup import startup

Handler = Callable[[argparse.Namespace], int]

# copytrade/__init__.py -> copytrade -> src -> repository root
_CODE_ROOT = Path(copytrade.__file__ or "").resolve().parents[2]


def _engine_module_files() -> list[Path]:
    """The source file of every loaded ``copytrade`` / ``copytrade.*`` module."""
    files: list[Path] = []
    for name, module in list(sys.modules.items()):
        if name == "copytrade" or name.startswith("copytrade."):
            source = getattr(module, "__file__", None)
            if source:
                files.append(Path(source))
    return sorted(files)


def _run_start(args: argparse.Namespace) -> int:
    root: Path = args.root
    result = startup(root, os.environ, code_root=_CODE_ROOT, engine_module_files=_engine_module_files())
    print(f"copytrade: startup checks passed (mode={result.config['mode']}, {len(result.config)} config keys)")
    return 0


def _register_start(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("start", help="validate config, mode, secrets and the engine path set, then start")
    parser.add_argument(
        "--root", type=Path, default=_CODE_ROOT, help="repository root (default: the repository of this checkout)"
    )
    parser.set_defaults(handler=_run_start)


def _register_area_modules(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    for info in sorted(pkgutil.iter_modules(copytrade.cli.__path__), key=lambda module: module.name):
        if info.name == "main" or info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"copytrade.cli.{info.name}")
            module.register(subparsers)
        except Exception as exc:
            print(f"copytrade: cli module {info.name!r} skipped ({type(exc).__name__}: {exc})", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="copytrade", description="AI-filtered copy-trading bot (paper mode only).")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    _register_start(subparsers)
    _register_area_modules(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` (default ``sys.argv[1:]``), dispatch, and return the process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_request:
        return exit_request.code if isinstance(exit_request.code, int) else 1
    handler: Handler = args.handler
    try:
        return handler(args)
    except CopytradeError as error:
        print(f"copytrade: {error}", file=sys.stderr)
        return 1
