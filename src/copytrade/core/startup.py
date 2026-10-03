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
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from copytrade.core.config import Config, load_config
from copytrade.core.errors import EnginePathError
from copytrade.core.manifest import MANIFEST_FILE_NAME, EnginePathSet, PathGuard
from copytrade.core.secrets import Secrets, load_secrets

CONFIG_DIR_NAME = "config"
# Config keys that name a data-input file, relative to the root. Each must be inside the engine path set.
DATA_INPUT_KEYS: tuple[str, ...] = ("calendar.file",)


@dataclass(frozen=True)
class StartupResult:
    config: Config
    secrets: Secrets
    path_set: EnginePathSet


def _check_engine_modules(path_set: EnginePathSet, code_root: Path, module_files: Iterable[Path]) -> None:
    root = code_root.resolve()
    for module_file in module_files:
        resolved = module_file.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            raise EnginePathError("engine module outside the code root", path=resolved.as_posix()) from None
        if not path_set.covers(relative):
            raise EnginePathError("engine module outside the engine path set", path=relative.as_posix())


def startup(
    root: Path,
    env: Mapping[str, str],
    *,
    code_root: Path,
    engine_module_files: Iterable[Path],
) -> StartupResult:
    """Run the startup checks. See the module docstring for order and errors."""
    path_set = EnginePathSet.from_file(root / MANIFEST_FILE_NAME)
    guard = PathGuard(path_set, root)
    config = load_config(root / CONFIG_DIR_NAME, guard=guard)
    for key in DATA_INPUT_KEYS:
        guard.check(root / config[key])
    _check_engine_modules(path_set, code_root, engine_module_files)
    return StartupResult(config=config, secrets=load_secrets(env), path_set=path_set)
