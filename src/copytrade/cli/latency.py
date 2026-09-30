"""``copytrade latency measure`` (F7.AC6).

``copytrade latency measure --hours N --wallets A,B,... --ledger-dir DIR [--root PATH]``: loads the config under
``--root`` (default: this checkout), builds the real boundaries with ``build_boundaries(config)`` (a module-level
factory the tests replace), runs ``copytrade.signals.latency.measure_latency`` into a ledger in ``--ledger-dir`` (a
separate ledger, never the engine's) and prints ``S1 n=<count> p50=<ms> p95=<ms> p99=<ms>``, the same for ``S2``,
``signals=<count>`` and ``enough_samples=true|false``. Exit 0; 2 for bad arguments (``--hours`` not a positive integer,
no wallet, an invalid address, more distinct wallets than ``hl.ws_max_unique_users``); 1 for any ``CopytradeError``.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from copytrade.signals.latency import LatencyBoundaries


def build_boundaries(config: Mapping[str, Any]) -> LatencyBoundaries:
    """The real boundaries (system clock, real sleeping, network transport and WebSocket connector)."""
    raise NotImplementedError


def _run_measure(args: argparse.Namespace) -> int:
    raise NotImplementedError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    latency = subparsers.add_parser("latency", help="latency tools")
    sub = latency.add_subparsers(dest="latency_command", required=True)
    measure = sub.add_parser("measure", help="record signal latency stages S1 and S2 without trading")
    measure.add_argument("--hours", required=True)
    measure.add_argument("--wallets", required=True)
    measure.add_argument("--ledger-dir", required=True)
    measure.add_argument("--root", default=None)
    measure.set_defaults(handler=_run_measure)
