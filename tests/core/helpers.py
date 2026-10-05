"""Helpers for the F1 tests: an editable copy of the valid config fixture, fake roots, CLI runner.

These are test utilities only; they never re-implement the unit under test.
"""

from __future__ import annotations

import copy
import io
import shutil
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import tomli_w

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
FIXTURE_CONFIG_DIR = HERE / "fixtures" / "config"
FIXTURE_MANIFEST = HERE / "fixtures" / "engine-path-set.txt"

_MISSING = object()


def _load_fixture_files() -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(FIXTURE_CONFIG_DIR.glob("*.toml")):
        with path.open("rb") as fh:
            files[path.name] = tomllib.load(fh, parse_float=Decimal)
    return files


_FIXTURE_FILES = _load_fixture_files()


def _walk(table: dict[str, Any], prefix: str) -> Iterator[tuple[str, Any]]:
    for k, v in table.items():
        dotted = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            yield from _walk(v, dotted)
        else:
            yield dotted, v


def fixture_leaves() -> dict[str, Any]:
    """Every leaf key of the valid fixture with its value (dotted key -> value)."""
    out: dict[str, Any] = {}
    for table in _FIXTURE_FILES.values():
        for k, v in _walk(table, ""):
            out[k] = v
    return out


class ConfigTree:
    """An in-memory, editable copy of the valid config fixture, written out on demand."""

    def __init__(self) -> None:
        self.files: dict[str, dict[str, Any]] = copy.deepcopy(_FIXTURE_FILES)

    def _locate(self, key: str) -> tuple[str, dict[str, Any], str] | None:
        parts = key.split(".")
        for name, table in self.files.items():
            node: Any = table
            for part in parts[:-1]:
                if not isinstance(node, dict) or part not in node:
                    node = _MISSING
                    break
                node = node[part]
            if isinstance(node, dict) and parts[-1] in node and not isinstance(node[parts[-1]], dict):
                return name, node, parts[-1]
        return None

    def get(self, key: str) -> Any:
        found = self._locate(key)
        if found is None:
            raise KeyError(key)
        _, node, leaf = found
        return node[leaf]

    def set(self, key: str, value: Any, *, file: str | None = None) -> ConfigTree:
        """Set ``key``. An existing key is changed where it lives; a new key goes to ``file`` (default ``extra.toml``)."""
        found = self._locate(key) if file is None else None
        if found is not None:
            _, node, leaf = found
            node[leaf] = value
            return self
        parts = key.split(".")
        node = self.files.setdefault(file or "extra.toml", {})
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        return self

    def delete(self, key: str) -> ConfigTree:
        found = self._locate(key)
        if found is None:
            raise KeyError(key)
        _, node, leaf = found
        del node[leaf]
        return self

    def write(self, config_dir: Path) -> Path:
        config_dir.mkdir(parents=True, exist_ok=True)
        for name, table in self.files.items():
            (config_dir / name).write_text(tomli_w.dumps(table), encoding="utf-8")
        return config_dir


def same_kind(template: Any, value: Any) -> Any:
    """Express ``value`` with the TOML type the fixture uses for that key (Decimal stays Decimal, int stays int)."""
    if isinstance(template, bool):
        return value
    if isinstance(template, Decimal):
        return Decimal(str(value))
    if isinstance(template, int) and isinstance(value, (int, str)):
        return int(value)
    return value


@dataclass
class FakeRoot:
    """A repository-like root: ``<root>/engine-path-set.txt`` and ``<root>/config/*.toml``."""

    root: Path
    config_dir: Path


def make_root(base: Path, tree: ConfigTree | None = None, *, manifest_lines: Sequence[str] | None = None) -> FakeRoot:
    root = base / "repo"
    root.mkdir(parents=True, exist_ok=True)
    if manifest_lines is None:
        shutil.copyfile(FIXTURE_MANIFEST, root / "engine-path-set.txt")
    else:
        (root / "engine-path-set.txt").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    config_dir = (tree or ConfigTree()).write(root / "config")
    return FakeRoot(root=root, config_dir=config_dir)


@dataclass
class CliResult:
    code: int
    stdout: str
    stderr: str


def run_cli(argv: Sequence[str]) -> CliResult:
    """Run ``copytrade.cli.main.main`` in-process, capturing output and ``SystemExit``."""
    from copytrade.cli.main import main

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:  # argparse errors
            code = exc.code if isinstance(exc.code, int) else 1
    return CliResult(code=int(code if code is not None else 0), stdout=out.getvalue(), stderr=err.getvalue())
