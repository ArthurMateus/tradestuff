"""Component version record and heartbeat (F4.AC8). Shared with the archive process (F23)."""

from __future__ import annotations

import hashlib
import platform
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Protocol

from copytrade.core.clock import Clock
from copytrade.core.errors import CopytradeError
from copytrade.core.manifest import MANIFEST_FILE_NAME, EnginePathSet
from copytrade.ledger.store import Ledger

KIND_COMPONENT_START = "component_start"
KIND_COMPONENT_HEARTBEAT = "component_heartbeat"

LOCKFILE_NAME = "uv.lock"
_GIT_TIMEOUT_S = 30
_COMMIT = frozenset("0123456789abcdef")
_STATUS_RENAME_FLAGS = "RC"


class IdentityError(CopytradeError):
    """The identity of a worktree cannot be read (not a git worktree, git failed, a file is missing)."""


@dataclass(frozen=True)
class ComponentIdentity:
    """What a process is running. ``commit`` is 40 lower-case hex; ``dirty`` is over the engine path set;
    the hashes are lower-case hex sha256."""

    worktree: str
    commit: str
    dirty: bool
    lockfile_sha256: str
    python_version: str
    packages_sha256: str


class IdentitySource(Protocol):
    def identity(self) -> ComponentIdentity: ...


def packages_sha256(packages: Iterable[tuple[str, str]]) -> str:
    """sha256 of the installed-package list as in F17.AC1: one ``name==version`` line per package, names lower-cased,
    lines sorted, UTF-8, LF line endings, each line (the last included) ending in ``\\n``."""
    lines = sorted(f"{name.lower()}=={version}\n" for name, version in packages)
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def installed_packages() -> tuple[tuple[str, str], ...]:
    """``(name, version)`` of every distribution installed in the running interpreter (``importlib.metadata``)."""
    found: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if name:
            found.setdefault(name.lower(), distribution.version)
    return tuple(sorted(found.items()))


class SystemIdentitySource:
    """Reads the identity of ``worktree`` with real ``git`` and file reads.

    ``commit``: ``git rev-parse HEAD``. ``dirty``: a tracked file inside the engine path set (``engine-path-set.txt``
    at the worktree root, matched with ``copytrade.core.manifest.EnginePathSet``) differs from HEAD, or an untracked
    file exists inside the set; changes outside the set never count. ``lockfile_sha256``: sha256 of ``uv.lock``.
    ``python_version``: ``platform.python_version()``. ``packages_sha256``: from ``installed_packages``.

    Raises ``IdentityError`` (or ``EnginePathError`` for a missing or malformed manifest) from ``identity``.
    """

    def __init__(
        self, worktree: Path, *, packages: Callable[[], Iterable[tuple[str, str]]] = installed_packages
    ) -> None:
        self._worktree = worktree.resolve()
        self._packages = packages

    def identity(self) -> ComponentIdentity:
        toplevel = Path(self._git("rev-parse", "--show-toplevel").strip()).resolve()
        if toplevel != self._worktree:
            raise IdentityError(f"{self._worktree} is not the top of a git worktree")
        commit = self._git("rev-parse", "HEAD").strip()
        if len(commit) != 40 or not set(commit) <= _COMMIT:
            raise IdentityError("git did not return a 40-hex commit")
        try:
            lockfile = (self._worktree / LOCKFILE_NAME).read_bytes()
        except OSError as exc:
            raise IdentityError(f"{LOCKFILE_NAME} cannot be read ({type(exc).__name__})") from exc
        return ComponentIdentity(
            worktree=str(self._worktree),
            commit=commit,
            dirty=self._dirty(),
            lockfile_sha256=hashlib.sha256(lockfile).hexdigest(),
            python_version=platform.python_version(),
            packages_sha256=packages_sha256(self._packages()),
        )

    def _dirty(self) -> bool:
        engine_files = EnginePathSet.from_file(self._worktree / MANIFEST_FILE_NAME)
        return any(engine_files.covers(path) for path in self._changed_paths())

    def _changed_paths(self) -> Iterable[str]:
        """Every path ``git status`` reports as changed or untracked (both names of a rename or copy)."""
        entries = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4:
                continue
            yield entry[3:]
            if entry[0] in _STATUS_RENAME_FLAGS or entry[1] in _STATUS_RENAME_FLAGS:
                if index < len(entries):
                    yield entries[index]  # the original name follows as its own NUL-terminated field
                index += 1

    def _git(self, *args: str) -> str:
        try:
            done = subprocess.run(  # noqa: S603 - fixed argument vector, no shell
                ["git", *args],  # noqa: S607 - git is resolved on PATH, as everywhere else in this project
                cwd=self._worktree,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_GIT_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise IdentityError(f"git could not be run ({type(exc).__name__})") from exc
        if done.returncode != 0:
            raise IdentityError(f"git {args[0]} failed in {self._worktree} (exit {done.returncode})")
        return done.stdout


class ComponentReporter:
    """Ledgers ``component_start`` once and a ``component_heartbeat`` every ``ledger.heartbeat_interval_s``.

    Both records carry ``component`` (``"recorder"`` or ``"archive"``) plus every ``ComponentIdentity`` field as
    payload keys of the same names. The identity is read once, at ``start``: it says what this process loaded, so a
    heartbeat repeats it instead of reading the worktree again.
    """

    def __init__(
        self, *, component: str, source: IdentitySource, ledger: Ledger, clock: Clock, heartbeat_interval_s: int
    ) -> None:
        if type(heartbeat_interval_s) is not int or heartbeat_interval_s <= 0:
            raise ValueError("heartbeat_interval_s must be a positive int")
        self._component = component
        self._source = source
        self._ledger = ledger
        self._clock = clock
        self._interval_ms = heartbeat_interval_s * 1000
        self._payload: dict[str, object] | None = None
        self._last_ms = 0

    def start(self) -> None:
        """Ledger ``component_start`` (and the first heartbeat is due one interval later)."""
        identity = self._source.identity()
        self._payload = {
            "component": self._component,
            "worktree": identity.worktree,
            "commit": identity.commit,
            "dirty": identity.dirty,
            "lockfile_sha256": identity.lockfile_sha256,
            "python_version": identity.python_version,
            "packages_sha256": identity.packages_sha256,
        }
        self._ledger.append(KIND_COMPONENT_START, self._payload)
        self._last_ms = self._clock.now_ms()

    def tick(self) -> None:
        """Ledger a heartbeat when ``heartbeat_interval_s`` has passed since the last record of this component."""
        if self._payload is None:
            raise CopytradeError("the component reporter was ticked before start")
        now = self._clock.now_ms()
        elapsed = now - self._last_ms
        if elapsed >= self._interval_ms or elapsed < 0:  # a clock that stepped back must not silence the heartbeat
            self._ledger.append(KIND_COMPONENT_HEARTBEAT, self._payload)
            self._last_ms = now
