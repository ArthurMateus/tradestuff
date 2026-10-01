"""The composition root."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from copytrade.runner.deps import RunnerDeps
from copytrade.runner.runner import Runner


def build_runner(root: Path, env: Mapping[str, str], deps: RunnerDeps) -> Runner:
    """Run the F1 startup checks (``core.startup.startup``: path set, config, mode, secrets from ``env`` only), open
    the ledger (``LedgerCorruptError`` propagates: start refused), check the disk (``DiskSpaceError``), build every
    component with ONE shared ``gate_lock`` and a per-process ``GateAuthority`` key, wire the bot as the AlertSink of
    every component. Opens no network connection. Raises ``CopytradeError`` subclasses only."""
    raise NotImplementedError
