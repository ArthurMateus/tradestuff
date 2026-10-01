"""The real DiskProbe and the start-up disk check (PO's ~100 GB disk, conservative defaults live in config/)."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.errors import CopytradeError
from copytrade.recorder.ports import DiskProbe


class DiskSpaceError(CopytradeError):
    """Free space is below ``recording.disk_floor_free_gb + recording.disk_resume_margin_gb``: refuse to start."""


class SystemDiskProbe:
    """``DiskProbe`` over ``shutil.disk_usage``: free GB (1 GB = 10**9 bytes) of the volume holding ``path``; a path
    that does not exist yet is probed through its nearest existing parent; ``OSError`` propagates."""

    def free_gb(self, path: Path) -> Decimal:
        raise NotImplementedError


def check_start_disk(config: Mapping[str, Any], probe: DiskProbe, paths: tuple[Path, ...]) -> Decimal:
    """Smallest free space over ``paths`` in GB. Raises ``DiskSpaceError`` (message names the free and required GB)
    when below floor + resume margin, and also when a probe fails (A2: unknown space counts as none)."""
    raise NotImplementedError
