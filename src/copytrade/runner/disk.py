"""The real DiskProbe and the start-up disk check (PO's ~100 GB disk, conservative defaults live in config/)."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.errors import CopytradeError
from copytrade.recorder.ports import DiskProbe

_BYTES_PER_GB = Decimal(10**9)


class DiskSpaceError(CopytradeError):
    """Free space is below ``recording.disk_floor_free_gb + recording.disk_resume_margin_gb``: refuse to start."""


class SystemDiskProbe:
    """``DiskProbe`` over ``shutil.disk_usage``: free GB (1 GB = 10**9 bytes) of the volume holding ``path``; a path
    that does not exist yet is probed through its nearest existing parent; ``OSError`` propagates."""

    def free_gb(self, path: Path) -> Decimal:
        probe = path
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        return Decimal(shutil.disk_usage(probe).free) / _BYTES_PER_GB


def check_start_disk(config: Mapping[str, Any], probe: DiskProbe, paths: tuple[Path, ...]) -> Decimal:
    """Smallest free space over ``paths`` in GB. Raises ``DiskSpaceError`` (message names the free and required GB)
    when below floor + resume margin, and also when a probe fails (A2: unknown space counts as none)."""
    required = Decimal(config["recording.disk_floor_free_gb"]) + Decimal(config["recording.disk_resume_margin_gb"])
    free_values: list[Decimal] = []
    for path in paths:
        try:
            free_values.append(probe.free_gb(path))
        except OSError as exc:
            raise DiskSpaceError(f"cannot read the free disk space ({type(exc).__name__}); refusing to start") from exc
    smallest = min(free_values)
    if smallest < required:
        raise DiskSpaceError(
            f"only {smallest:f} GB free on the smallest data volume, {required:f} GB are required "
            "(recording.disk_floor_free_gb + recording.disk_resume_margin_gb); free space and start again"
        )
    return smallest
