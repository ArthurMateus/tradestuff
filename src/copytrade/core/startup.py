"""Engine startup checks (F1.AC1, F1.AC3, F1.AC5, F1.AC7). Fail closed; no network.

``startup`` runs, in this order, and opens no network connection at any step:

1. Read ``<root>/engine-path-set.txt`` (missing or unreadable -> ``EnginePathError`` naming it).
2. Load ``<root>/config`` through the path guard: every config file opened must be covered by the
   manifest (else ``EnginePathError`` naming the file), then validate it (``ConfigError`` naming the key;
   ``ModeNotPermittedError`` for any mode other than ``paper``).
3. Check the data-input paths named in config (``calendar.file``, relative to ``root``) are covered by
   the manifest (else ``EnginePathError`` naming it). Existence is not checked here (F8 owns the file).
4. Check every engine module file (``copytrade`` and ``copytrade.*`` modules) is covered, relative
   to ``code_root`` (else ``EnginePathError`` naming the module file).
5. Load secrets from ``env`` only.

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from copytrade.core.config import Config
from copytrade.core.manifest import EnginePathSet
from copytrade.core.secrets import Secrets


@dataclass(frozen=True)
class StartupResult:
    config: Config
    secrets: Secrets
    path_set: EnginePathSet


def startup(
    root: Path,
    env: Mapping[str, str],
    *,
    code_root: Path,
    engine_module_files: Iterable[Path],
) -> StartupResult:
    """Run the startup checks. See the module docstring for order and errors."""
    raise NotImplementedError
