"""``copytrade latency measure`` (F7.AC6).

``copytrade latency measure --hours N --wallets A,B,... --ledger-dir DIR [--root PATH]``: loads the config under
``--root`` (default: this checkout), builds the real boundaries with ``build_boundaries(config)`` (a module-level
factory the tests replace), runs ``copytrade.signals.latency.measure_latency`` into a ledger in ``--ledger-dir`` (a
separate ledger: the engine's own ``storage.ledger_dir`` is refused, because measurement signals written there would
make the same fills duplicates in a real run) and prints ``S1 n=<count> p50=<ms> p95=<ms> p99=<ms>``, the same for
``S2``, ``signals=<count>`` and ``enough_samples=true|false``. Exit 0; 2 for bad arguments (``--hours`` not a
positive integer, no wallet, an invalid address, more distinct wallets than ``hl.ws_max_unique_users``, ``--ledger-dir`` is the engine
ledger); 1 for any ``CopytradeError`` or a ledger directory that cannot be opened.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import copytrade
from copytrade.core.config import load_config
from copytrade.core.errors import CopytradeError
from copytrade.core.events import Alert
from copytrade.hl.errors import HlRequestError
from copytrade.hl.wallet import normalize_wallet
from copytrade.ledger.store import Ledger
from copytrade.signals.latency import LatencyBoundaries, StageSummary, measure_latency

# copytrade/__init__.py -> copytrade -> src -> repository root (the default ``--root``, as for ``copytrade start``)
_CODE_ROOT = Path(copytrade.__file__ or "").resolve().parents[2]
_CONFIG_DIR_NAME = "config"
_POSITIVE_INT = re.compile(r"[0-9]+")


class BoundariesUnavailableError(CopytradeError):
    """The real network boundaries of a measurement run cannot be built yet."""


def build_boundaries(config: Mapping[str, Any]) -> LatencyBoundaries:  # noqa: ARG001 - the seam's signature
    """The real boundaries (system clock, real sleeping, network transport and WebSocket connector).

    Not available yet: F3 defines the ``WsConnector`` port but no concrete connector, and no source of clock-offset
    estimates exists. Which WebSocket library to depend on is an open decision (F21), so this factory refuses
    instead of guessing. It is the only place a real connector will be added; tests replace it.

    Raises:
        BoundariesUnavailableError: always.
    """
    raise BoundariesUnavailableError(
        "the latency measurement cannot reach Hyperliquid yet: no WebSocket connector or clock-offset source "
        "is implemented (open decision, F21)"
    )


def _hours(text: str) -> int:
    if _POSITIVE_INT.fullmatch(text) is None or int(text) == 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive whole number of hours")
    return int(text)


def _wallets(text: str) -> tuple[str, ...]:
    try:
        return tuple(normalize_wallet(part) for part in text.split(","))
    except HlRequestError:
        raise argparse.ArgumentTypeError(
            "every wallet must be 0x followed by 40 hex digits, separated by commas"
        ) from None


def _same_directory(left: Path, right: Path) -> bool:
    return os.path.normcase(left.resolve()) == os.path.normcase(right.resolve())


def _stage_line(name: str, summary: StageSummary | None) -> str:
    if summary is None:
        return f"{name} n=0"
    return f"{name} n={summary.count} p50={summary.p50_ms} p95={summary.p95_ms} p99={summary.p99_ms}"


class _StderrAlerts:
    """Alerts of a measurement run go to the terminal (Telegram, F14, is not part of a measurement)."""

    def send(self, alert: Alert) -> None:
        print(f"copytrade: alert [{alert.kind}] {alert.message}", file=sys.stderr)


def _run_measure(args: argparse.Namespace) -> int:
    root: Path = args.root if args.root is not None else _CODE_ROOT
    config = load_config(root / _CONFIG_DIR_NAME)
    wallets = tuple(dict.fromkeys(args.wallets))
    if len(wallets) > config["hl.ws_max_unique_users"]:
        print(
            f"copytrade: at most {config['hl.ws_max_unique_users']} distinct wallets (hl.ws_max_unique_users)",
            file=sys.stderr,
        )
        return 2
    if _same_directory(args.ledger_dir, root / config["storage.ledger_dir"]):
        print(
            "copytrade: --ledger-dir is the engine ledger (storage.ledger_dir); measurement signals would make the "
            "same fills duplicates in a real run. Use a separate directory.",
            file=sys.stderr,
        )
        return 2
    boundaries = build_boundaries(config)
    try:
        ledger = Ledger.open(args.ledger_dir, clock=boundaries.clock)
    except OSError as exc:
        print(f"copytrade: cannot open the measurement ledger: {exc.strerror or type(exc).__name__}", file=sys.stderr)
        return 1
    try:
        report = measure_latency(
            hours=args.hours,
            wallets=wallets,
            config=config,
            boundaries=boundaries,
            ledger=ledger,
            alerts=_StderrAlerts(),
        )
    finally:
        ledger.close()
    print(_stage_line("S1", report.s1))
    print(_stage_line("S2", report.s2))
    print(f"signals={report.signals}")
    print(f"enough_samples={'true' if report.enough_samples else 'false'}")
    return 0


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    latency = subparsers.add_parser("latency", help="latency tools")
    sub = latency.add_subparsers(dest="latency_command", required=True)
    measure = sub.add_parser("measure", help="record signal latency stages S1 and S2 without trading")
    measure.add_argument("--hours", required=True, type=_hours, help="run length in whole hours")
    measure.add_argument("--wallets", required=True, type=_wallets, help="comma-separated 0x wallet addresses")
    measure.add_argument("--ledger-dir", required=True, type=Path, help="a separate ledger for the measurement")
    measure.add_argument("--root", type=Path, default=None, help="repository root (default: this checkout)")
    measure.set_defaults(handler=_run_measure)
