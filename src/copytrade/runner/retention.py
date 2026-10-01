"""Local recording-retention cap (the recorder itself never deletes: F4.AC2)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from copytrade.ledger.store import Ledger

KIND_RECORDING_PRUNED = "recording_pruned"


def prune_recordings(
    config: Mapping[str, Any], *, recordings_dir: Path, ledger: Ledger, now_ms: int
) -> tuple[str, ...]:
    """Delete the closed recording files of every UTC day older than ``storage.local_retention_days`` (relative to
    ``now_ms``) and return their paths (relative to ``recordings_dir``, POSIX, sorted). For each file one ledger
    record of kind ``recording_pruned`` with ``path``, ``sha256`` and ``bytes`` is appended BEFORE the file is
    deleted. Never touches the current or a newer day, the wallet registry, the ledger or any other directory."""
    raise NotImplementedError
