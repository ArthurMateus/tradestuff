"""Local recording-retention cap (the recorder itself never deletes: F4.AC2)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from copytrade.ledger.store import Ledger
from copytrade.recorder.store import PART_SUFFIX, ClosedFile, RecordingReader

KIND_RECORDING_PRUNED = "recording_pruned"
_HASH_CHUNK_BYTES = 1 << 20


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def prune_recordings(  # noqa: PLR0913 - one retention pass
    config: Mapping[str, Any],
    *,
    recordings_dir: Path,
    ledger: Ledger,
    now_ms: int,
    closed_files: Callable[[], Sequence[ClosedFile]] | None = None,
    already: set[str] | None = None,
) -> tuple[str, ...]:
    """Delete the closed recording files of every UTC day older than ``storage.local_retention_days`` (relative to
    ``now_ms``) and return their paths (relative to ``recordings_dir``, POSIX, sorted). For each file one ledger
    record of kind ``recording_pruned`` with ``path``, ``sha256`` and ``bytes`` is appended BEFORE the file is
    deleted. Never touches the current or a newer day, the wallet registry, the ledger or any other directory.

    Without ``closed_files`` and ``already`` the closed files and the already pruned paths are read from the ledger
    (two whole-ledger walks: start-up only). A caller that keeps them in memory (the recorder's live index and the set
    of paths it has pruned, which this function extends) passes them and the pass reads nothing from the ledger."""
    today = datetime.fromtimestamp(now_ms / 1000, UTC).date()
    oldest_kept = (today - timedelta(days=int(config["storage.local_retention_days"]))).isoformat()
    if already is None:
        already = {r.payload["path"] for r in ledger.records() if r.kind == KIND_RECORDING_PRUNED}
    closed_now = closed_files() if closed_files is not None else RecordingReader(recordings_dir, ledger.records).files()
    pruned: list[str] = []
    for closed in closed_now:
        if closed.day >= oldest_kept or closed.path in already:
            continue
        final = recordings_dir / closed.path
        target = final if final.exists() else final.with_name(final.name + PART_SUFFIX)
        if not target.is_file():
            continue
        sha256, size = _sha256_and_size(target)
        ledger.append(KIND_RECORDING_PRUNED, {"path": closed.path, "sha256": sha256, "bytes": size})
        already.add(closed.path)
        target.unlink()
        pruned.append(closed.path)
    return tuple(sorted(pruned))
