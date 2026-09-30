"""Component version record and heartbeat (F4.AC8). Shared with the archive process (F23)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from copytrade.core.clock import Clock
from copytrade.ledger.store import Ledger

KIND_COMPONENT_START = "component_start"
KIND_COMPONENT_HEARTBEAT = "component_heartbeat"


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
    raise NotImplementedError


def installed_packages() -> tuple[tuple[str, str], ...]:
    """``(name, version)`` of every distribution installed in the running interpreter (``importlib.metadata``)."""
    raise NotImplementedError


class SystemIdentitySource:
    """Reads the identity of ``worktree`` with real ``git`` and file reads.

    ``commit``: ``git rev-parse HEAD``. ``dirty``: a tracked file inside the engine path set (``engine-path-set.txt``
    at the worktree root, matched with ``copytrade.core.manifest.EnginePathSet``) differs from HEAD, or an untracked
    file exists inside the set; changes outside the set never count. ``lockfile_sha256``: sha256 of ``uv.lock``.
    ``python_version``: ``platform.python_version()``. ``packages_sha256``: from ``installed_packages``.
    """

    def __init__(
        self, worktree: Path, *, packages: Callable[[], Iterable[tuple[str, str]]] = installed_packages
    ) -> None:
        raise NotImplementedError

    def identity(self) -> ComponentIdentity:
        raise NotImplementedError


class ComponentReporter:
    """Ledgers ``component_start`` once and a ``component_heartbeat`` every ``ledger.heartbeat_interval_s``.

    Both records carry ``component`` (``"recorder"`` or ``"archive"``) plus every ``ComponentIdentity`` field as
    payload keys of the same names.
    """

    def __init__(
        self, *, component: str, source: IdentitySource, ledger: Ledger, clock: Clock, heartbeat_interval_s: int
    ) -> None:
        raise NotImplementedError

    def start(self) -> None:
        """Ledger ``component_start`` (and the first heartbeat is due one interval later)."""
        raise NotImplementedError

    def tick(self) -> None:
        """Ledger a heartbeat when ``heartbeat_interval_s`` has passed since the last record of this component."""
        raise NotImplementedError
