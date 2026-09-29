"""Engine path set (F1.AC7, edge-hypothesis A2.2).

Manifest format (``engine-path-set.txt`` at the repository root): one pattern per line, relative
POSIX paths; blank lines and lines starting with ``#`` are ignored. ``dir/**`` covers every file
below ``dir`` at any depth; a plain path covers exactly that file.

Paths are always compared as normalised relative POSIX paths, so Windows paths
(``PureWindowsPath("src\\\\copytrade\\\\x.py")``) behave like their POSIX form. A path that is absolute,
or that escapes the root through ``..`` after normalisation, is never covered.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePath
from typing import BinaryIO

from copytrade.core.errors import EnginePathError

MANIFEST_FILE_NAME = "engine-path-set.txt"
_RECURSIVE_SUFFIX = "/**"


def _normalise(path: str | PurePath) -> tuple[str, ...] | None:
    """Split ``path`` into normalised relative parts, or ``None`` if it is absolute, empty or escapes the root."""
    text = path.as_posix() if isinstance(path, PurePath) else path
    text = text.replace("\\", "/")
    if text.startswith("/") or (len(text) >= 2 and text[1] == ":" and text[0].isalpha()):
        return None
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return tuple(parts) or None


class EnginePathSet:
    """The parsed manifest."""

    def __init__(
        self, patterns: tuple[str, ...], exact: frozenset[tuple[str, ...]], trees: tuple[tuple[str, ...], ...]
    ) -> None:
        self._patterns = patterns
        self._exact = exact
        self._trees = trees

    @classmethod
    def from_file(cls, path: Path) -> EnginePathSet:
        """Parse a manifest file.

        Raises:
            EnginePathError: the file is missing or unreadable (names the file), or a pattern is malformed.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise EnginePathError(f"engine path set unreadable ({type(exc).__name__})", path=path.as_posix()) from exc
        return cls.from_lines(text.splitlines())

    @classmethod
    def from_lines(cls, lines: Iterable[str]) -> EnginePathSet:
        """Parse manifest lines.

        Raises:
            EnginePathError: a pattern is absolute, escapes the root, or is ``**`` without a directory.
        """
        patterns: list[str] = []
        exact: set[tuple[str, ...]] = set()
        trees: list[tuple[str, ...]] = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            recursive = line.endswith(_RECURSIVE_SUFFIX)
            parts = _normalise(line[: -len(_RECURSIVE_SUFFIX)] if recursive else line)
            if parts is None or "**" in parts:
                raise EnginePathError("malformed engine path set pattern", path=MANIFEST_FILE_NAME)
            patterns.append(line)
            if recursive:
                trees.append(parts)
            else:
                exact.add(parts)
        return cls(tuple(patterns), frozenset(exact), tuple(trees))

    @property
    def patterns(self) -> tuple[str, ...]:
        """The patterns in file order, comments and blank lines removed."""
        return self._patterns

    def covers(self, relpath: str | PurePath) -> bool:
        """True when ``relpath`` (relative to the repository root) is inside the path set."""
        parts = _normalise(relpath)
        if parts is None:
            return False
        if parts in self._exact:
            return True
        return any(len(parts) > len(tree) and parts[: len(tree)] == tree for tree in self._trees)


class PathGuard:
    """Checks and opens engine inputs (config and data-input files) against the path set."""

    def __init__(self, path_set: EnginePathSet, root: Path) -> None:
        self._path_set = path_set
        self._root = root.resolve()

    def check(self, path: Path) -> Path:
        """Return the resolved ``path``, or raise ``EnginePathError`` naming it unless it resolves
        inside ``root`` and is covered by the path set. Symbolic links are followed first."""
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self._root)
        except ValueError:
            raise EnginePathError("input outside the engine root", path=resolved.as_posix()) from None
        if not self._path_set.covers(relative):
            raise EnginePathError("input outside the engine path set", path=relative.as_posix())
        return resolved

    def open_input(self, path: Path) -> BinaryIO:
        """``check(path)`` and then open it for binary reading."""
        return self.check(path).open("rb")
