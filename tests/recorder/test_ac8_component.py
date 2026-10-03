"""F4.AC8: component version record (the recorder is engine code, edge-hypothesis A3.4) and heartbeat.

Spec: 04-spec.md F4.AC8, F17.AC1 (package-list hash), §3.1 ``ledger.heartbeat_interval_s``.
Real ``git`` runs in temporary repositories (a local tool, no network); the real ledger records the results.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from copytrade.core.errors import CopytradeError
from copytrade.ledger.store import Ledger
from copytrade.recorder.identity import (
    KIND_COMPONENT_HEARTBEAT,
    KIND_COMPONENT_START,
    ComponentReporter,
    SystemIdentitySource,
    installed_packages,
    packages_sha256,
)
from tests.recorder.helpers import DAY0, SECOND, FakeClock, FakeIdentity, Rig, make_identity

pytestmark = pytest.mark.integration

IDENTITY_FIELDS = ("worktree", "commit", "dirty", "lockfile_sha256", "python_version", "packages_sha256")
SET = "src/**\nuv.lock\nengine-path-set.txt\n"


def git(cwd: Path, *args: str) -> str:
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_TERMINAL_PROMPT="0")
    out = subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],  # noqa: S607
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def make_repo(base: Path) -> Path:
    repo = base / "main"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "src").mkdir()
    (repo / "docs").mkdir()
    (repo / "src" / "a.py").write_text("A = 1\n")
    (repo / "docs" / "notes.md").write_text("notes\n")
    (repo / "uv.lock").write_text("lock v1\n")
    (repo / "engine-path-set.txt").write_text(SET)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "one")
    return repo


# --- package list hash -----------------------------------------------------------------------------------------------------------


def test_F4_AC8_the_package_hash_is_over_sorted_lowercase_name_equals_version_lines_with_lf() -> None:
    expect = hashlib.sha256(b"alpha==1.0\nbeta==2.1\nzeta==0.3\n").hexdigest()
    assert packages_sha256([("Zeta", "0.3"), ("alpha", "1.0"), ("BETA", "2.1")]) == expect


def test_F4_AC8_the_package_hash_ignores_input_order_and_changes_with_a_version() -> None:
    a = packages_sha256([("a", "1"), ("b", "2")])
    assert a == packages_sha256([("b", "2"), ("a", "1")])
    assert a != packages_sha256([("a", "1"), ("b", "3")])
    assert a != packages_sha256([("a", "1")])


def test_F4_AC8_the_package_hash_of_no_packages_is_the_hash_of_nothing() -> None:
    assert packages_sha256([]) == hashlib.sha256(b"").hexdigest()


def test_F4_AC8_installed_packages_lists_this_interpreters_distributions() -> None:
    pkgs = dict(installed_packages())
    assert "pytest" in pkgs and "hypothesis" in pkgs
    assert all(name == name.lower() and version for name, version in pkgs.items())


# --- the identity read from a real worktree ------------------------------------------------------------------------------------------


def test_F4_AC8_the_identity_of_a_clean_worktree_has_the_real_commit_lockfile_hash_and_python_version(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    ident = SystemIdentitySource(repo, packages=lambda: [("a", "1")]).identity()
    assert ident.commit == git(repo, "rev-parse", "HEAD") and len(ident.commit) == 40
    assert ident.dirty is False
    assert ident.lockfile_sha256 == hashlib.sha256(b"lock v1\n").hexdigest()
    assert ident.python_version == platform.python_version()
    assert ident.packages_sha256 == packages_sha256([("a", "1")])
    assert Path(ident.worktree).resolve() == repo.resolve()


def test_F4_AC8_the_default_package_hash_is_the_hash_of_the_installed_packages(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    assert SystemIdentitySource(repo).identity().packages_sha256 == packages_sha256(installed_packages())


@pytest.mark.parametrize(
    ("edit", "dirty"),
    [
        (lambda r: (r / "src" / "a.py").write_text("A = 2\n"), True),  # tracked engine file changed
        (lambda r: (r / "src" / "new.py").write_text("B = 1\n"), True),  # untracked file inside the set
        (lambda r: (r / "uv.lock").write_text("lock v2\n"), True),  # the lockfile is in the set
        (lambda r: (r / "docs" / "notes.md").write_text("changed\n"), False),  # tracked, outside the set
        (lambda r: (r / "scratch.txt").write_text("x\n"), False),  # untracked, outside the set
        (lambda r: None, False),
    ],
)
def test_F4_AC8_dirty_is_judged_over_the_engine_path_set_only(tmp_path: Path, edit: Callable[[Path], object], dirty: bool) -> None:
    repo = make_repo(tmp_path)
    edit(repo)
    assert SystemIdentitySource(repo, packages=lambda: []).identity().dirty is dirty


def test_F4_AC8_a_directory_that_is_not_a_git_worktree_is_an_error_not_a_made_up_identity(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    with pytest.raises((OSError, ValueError, CopytradeError)):
        SystemIdentitySource(tmp_path / "plain", packages=lambda: []).identity()


# --- ledgered start record and heartbeat ---------------------------------------------------------------------------------------------------


def make_reporter(base: Path, ident: FakeIdentity, clock: FakeClock, component: str = "recorder", interval: int = 10) -> tuple[Ledger, ComponentReporter]:
    ledger = Ledger.open(base, clock=clock)
    return ledger, ComponentReporter(component=component, source=ident, ledger=ledger, clock=clock, heartbeat_interval_s=interval)


def test_F4_AC8_start_ledgers_one_component_start_with_the_full_identity(tmp_path: Path) -> None:
    clock = FakeClock(DAY0)
    ident = FakeIdentity(make_identity(worktree="/wt/run", commit="ab" * 20, dirty=True))
    ledger, reporter = make_reporter(tmp_path / "l", ident, clock)
    with ledger:
        reporter.start()
        (rec,) = [r for r in ledger.records() if r.kind == KIND_COMPONENT_START]
    assert KIND_COMPONENT_START == "component_start"
    assert rec.payload == {"component": "recorder", **{f: getattr(ident.ident, f) for f in IDENTITY_FIELDS}}


def test_F4_AC8_the_archive_process_uses_the_same_record_with_its_own_component_name(tmp_path: Path) -> None:
    clock = FakeClock(DAY0)
    ledger, reporter = make_reporter(tmp_path / "l", FakeIdentity(make_identity()), clock, component="archive")
    with ledger:
        reporter.start()
        (rec,) = [r for r in ledger.records() if r.kind == KIND_COMPONENT_START]
    assert rec.payload["component"] == "archive"


def test_F4_AC8_a_heartbeat_with_the_same_identity_is_ledgered_every_interval_and_not_before(tmp_path: Path) -> None:
    clock = FakeClock(DAY0)
    ident = FakeIdentity(make_identity())
    ledger, reporter = make_reporter(tmp_path / "l", ident, clock, interval=10)
    with ledger:
        reporter.start()
        for _ in range(9):
            clock.advance(SECOND)
            reporter.tick()
        assert [r for r in ledger.records() if r.kind == KIND_COMPONENT_HEARTBEAT] == []  # 9 s: not yet
        for _ in range(26):
            clock.advance(SECOND)
            reporter.tick()
        beats = [r for r in ledger.records() if r.kind == KIND_COMPONENT_HEARTBEAT]
    assert KIND_COMPONENT_HEARTBEAT == "component_heartbeat"
    assert [b.ts.ms for b in beats] == [DAY0 + 10_000, DAY0 + 20_000, DAY0 + 30_000]
    for b in beats:
        assert b.payload == {"component": "recorder", **{f: getattr(ident.ident, f) for f in IDENTITY_FIELDS}}


def test_F4_AC8_the_heartbeat_interval_follows_config_at_its_minimum(tmp_path: Path) -> None:
    clock = FakeClock(DAY0)
    ledger, reporter = make_reporter(tmp_path / "l", FakeIdentity(make_identity()), clock, interval=1)
    with ledger:
        reporter.start()
        for _ in range(5):
            clock.advance(SECOND)
            reporter.tick()
        assert len([r for r in ledger.records() if r.kind == KIND_COMPONENT_HEARTBEAT]) == 5


def test_F4_AC8_a_long_pause_yields_one_heartbeat_not_a_burst_of_catch_up_records(tmp_path: Path) -> None:
    clock = FakeClock(DAY0)
    ledger, reporter = make_reporter(tmp_path / "l", FakeIdentity(make_identity()), clock, interval=10)
    with ledger:
        reporter.start()
        clock.advance(3600 * SECOND)  # the PC slept
        reporter.tick()
        reporter.tick()
        assert len([r for r in ledger.records() if r.kind == KIND_COMPONENT_HEARTBEAT]) == 1


def test_F4_AC8_the_recorder_ledgers_its_component_start_when_it_starts(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(started=False)
    assert rig.ledger_of(KIND_COMPONENT_START) == []
    rig.recorder.start()
    (rec,) = rig.ledger_of(KIND_COMPONENT_START)
    assert rec.payload["component"] == "recorder" and rec.payload["commit"] == "a" * 40
    rig.run(35)
    beats = rig.ledger_of(KIND_COMPONENT_HEARTBEAT)
    assert len(beats) == 3 and all(b.payload["commit"] == "a" * 40 for b in beats)


# --- two worktrees at different commits ------------------------------------------------------------------------------------------------------------


def test_F4_AC8_two_worktrees_at_different_commits_give_two_records_that_differ_exactly_in_commit_and_path(tmp_path: Path) -> None:
    main = make_repo(tmp_path)
    first = git(main, "rev-parse", "HEAD")
    (main / "src" / "a.py").write_text("A = 2\n")
    git(main, "commit", "-q", "-am", "two")
    second = git(main, "rev-parse", "HEAD")
    other = tmp_path / "run-worktree"
    git(main, "worktree", "add", "-q", "--detach", str(other), first)
    assert first != second

    records = []
    for i, tree in enumerate((main, other)):
        clock = FakeClock(DAY0)
        ledger = Ledger.open(tmp_path / f"ledger{i}", clock=clock)
        with ledger:
            reporter = ComponentReporter(
                component="recorder",
                source=SystemIdentitySource(tree, packages=lambda: [("a", "1")]),
                ledger=ledger,
                clock=clock,
                heartbeat_interval_s=10,
            )
            reporter.start()
            (rec,) = [r for r in ledger.records() if r.kind == KIND_COMPONENT_START]
            records.append(dict(rec.payload))
    a, b = records
    assert {k for k in a if a[k] != b[k]} == {"commit", "worktree"}
    assert (a["commit"], b["commit"]) == (second, first)
    assert Path(a["worktree"]).resolve() == main.resolve() and Path(b["worktree"]).resolve() == other.resolve()
