"""Engine path set (F1.AC7, edge-hypothesis A2.2).

Manifest format (``engine-path-set.txt`` at the repository root): one pattern per line, relative
POSIX paths; blank lines and lines starting with ``#`` are ignored. ``dir/**`` covers every file
below ``dir`` at any depth; a plain path covers exactly that file.

Paths are always compared as normalised relative POSIX paths, so Windows paths
(``PureWindowsPath("src\\\\copytrade\\\\x.py")``) behave like their POSIX form. A path that is absolute,
or that escapes the root through ``..`` after normalisation, is never covered.

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePath
from typing import BinaryIO

MANIFEST_FILE_NAME = "engine-path-set.txt"


class EnginePathSet:
    """The parsed manifest."""

    @classmethod
    def from_file(cls, path: Path) -> EnginePathSet:
        """Parse a manifest file.

        Raises:
            EnginePathError: the file is missing or unreadable (names the file).
        """
        raise NotImplementedError

    @classmethod
    def from_lines(cls, lines: Iterable[str]) -> EnginePathSet:
        raise NotImplementedError

    @property
    def patterns(self) -> tuple[str, ...]:
        """The patterns in file order, comments and blank lines removed."""
        raise NotImplementedError

    def covers(self, relpath: str | PurePath) -> bool:
        """True when ``relpath`` (relative to the repository root) is inside the path set."""
        raise NotImplementedError


class PathGuard:
    """Checks and opens engine inputs (config and data-input files) against the path set."""

    def __init__(self, path_set: EnginePathSet, root: Path) -> None:
        raise NotImplementedError

    def check(self, path: Path) -> None:
        """Raise ``EnginePathError`` naming ``path`` unless it resolves inside ``root`` and is covered."""
        raise NotImplementedError

    def open_input(self, path: Path) -> BinaryIO:
        """``check(path)`` and then open it for binary reading."""
        raise NotImplementedError
