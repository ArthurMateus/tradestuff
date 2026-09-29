"""F1.AC7: the engine path set.

The committed manifest lists src/copytrade/**, the lockfile, the project metadata file, config/**,
data/inputs/** and itself, and never docs/**, research/**, tests/** or the storage directories. At
startup the engine fails closed, naming the file, when an imported engine module or a file opened as
config or data input is outside the manifest.

Spec: 04-spec.md F1.AC7 (Amendment 1: storage.cache_dir), §3.9 eval.engine_path_manifest, EH A2.2.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from copytrade.core.errors import EnginePathError
from copytrade.core.manifest import EnginePathSet, PathGuard
from copytrade.core.startup import startup
from tests.core.helpers import FIXTURE_MANIFEST, REPO_ROOT, ConfigTree, fixture_leaves, make_root, run_cli

COMMITTED_MANIFEST = REPO_ROOT / "engine-path-set.txt"
REQUIRED_ENTRIES = ["src/copytrade/**", "uv.lock", "pyproject.toml", "config/**", "data/inputs/**", "engine-path-set.txt"]
FORBIDDEN_SAMPLES = [
    "docs/sdlc/copytrade-v1/04-spec.md",
    "docs/product/decisions.md",
    "docs/sdlc/copytrade-v1/research/scripts/eval_reference.py",
    "research/data/hl_sample/summary.json",
    "tests/core/test_engine_path_set.py",
    "tests/core/fixtures/config/risk.toml",
    "README.md",
    "CLAUDE.md",
    ".claude/knowledge/trading-invariants.md",
]
STORAGE_DIR_KEYS = ["storage.ledger_dir", "storage.recordings_dir", "storage.cache_dir"]


def _fixture_set() -> EnginePathSet:
    return EnginePathSet.from_file(FIXTURE_MANIFEST)


# --- the committed manifest -------------------------------------------------------------------------------

@pytest.mark.integration
def test_F1_AC7_committed_manifest_exists_at_the_repo_root() -> None:
    assert COMMITTED_MANIFEST.is_file(), "engine-path-set.txt must be committed at the repository root"


@pytest.mark.integration
def test_F1_AC7_committed_manifest_lists_every_required_entry() -> None:
    assert COMMITTED_MANIFEST.is_file()
    patterns = EnginePathSet.from_file(COMMITTED_MANIFEST).patterns
    missing = [e for e in REQUIRED_ENTRIES if e not in patterns]
    assert missing == []


@pytest.mark.integration
def test_F1_AC7_committed_manifest_never_lists_docs_research_tests_or_storage_dirs() -> None:
    assert COMMITTED_MANIFEST.is_file()
    path_set = EnginePathSet.from_file(COMMITTED_MANIFEST)
    for p in path_set.patterns:
        assert not p.startswith(("docs", "research", "tests")), p
    covered = [s for s in FORBIDDEN_SAMPLES if path_set.covers(s)]
    assert covered == []
    leaves = fixture_leaves()
    for key in STORAGE_DIR_KEYS:
        for sample in (leaves[key], f"{leaves[key]}/2026-09-29/l2.jsonl.zst"):
            assert not path_set.covers(sample), f"{key} sample {sample} is covered"


@pytest.mark.integration
def test_F1_AC7_committed_manifest_covers_the_real_engine_files() -> None:
    assert COMMITTED_MANIFEST.is_file()
    path_set = EnginePathSet.from_file(COMMITTED_MANIFEST)
    for p in sorted((REPO_ROOT / "src" / "copytrade").rglob("*.py")):
        assert path_set.covers(p.relative_to(REPO_ROOT)), p
    for name in ("uv.lock", "pyproject.toml", "engine-path-set.txt"):
        assert path_set.covers(name), name


# --- pattern semantics ------------------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "covered"),
    [
        ("src/copytrade/core/config.py", True),
        ("src/copytrade/__init__.py", True),
        ("src/copytrade/a/b/c/deep.py", True),
        ("config/risk.toml", True),
        ("config/sub/area.toml", True),
        ("data/inputs/macro_calendar.csv", True),
        ("uv.lock", True),
        ("pyproject.toml", True),
        ("engine-path-set.txt", True),
        ("src/other/x.py", False),
        ("src/copytrade_evil/x.py", False),  # a sibling whose name merely starts with the package name
        ("data/other.csv", False),
        ("data/inputs_extra/x.csv", False),
        ("configs/risk.toml", False),
        ("uv.lock.bak", False),
        ("../outside/uv.lock", False),
        ("src/copytrade/../../docs/x.md", False),  # escapes through '..'
        ("config/../docs/x.md", False),
        ("", False),
    ]
    + [(s, False) for s in FORBIDDEN_SAMPLES],
)
def test_F1_AC7_manifest_pattern_semantics(path: str, covered: bool) -> None:
    assert _fixture_set().covers(path) is covered


@pytest.mark.unit
def test_F1_AC7_windows_style_paths_are_normalised() -> None:
    path_set = _fixture_set()
    assert path_set.covers(PureWindowsPath("src\\copytrade\\core\\config.py")) is True
    assert path_set.covers(PureWindowsPath("docs\\sdlc\\x.md")) is False
    assert path_set.covers(PurePosixPath("config/risk.toml")) is True


@pytest.mark.unit
def test_F1_AC7_absolute_paths_are_never_covered() -> None:
    assert _fixture_set().covers(REPO_ROOT / "src" / "copytrade" / "core" / "config.py") is False


@pytest.mark.unit
def test_F1_AC7_comments_and_blank_lines_are_ignored() -> None:
    path_set = EnginePathSet.from_lines(["# engine files", "", "src/copytrade/**", "   ", "# end"])
    assert path_set.patterns == ("src/copytrade/**",)


@pytest.mark.unit
def test_F1_AC7_missing_manifest_fails_closed_naming_it(tmp_path: Path) -> None:
    with pytest.raises(EnginePathError) as info:
        EnginePathSet.from_file(tmp_path / "engine-path-set.txt")
    assert "engine-path-set.txt" in str(info.value)


# --- the path guard for config and data inputs --------------------------------------------------------------

@pytest.mark.unit
def test_F1_AC7_path_guard_opens_a_covered_data_input(tmp_path: Path) -> None:
    fake = make_root(tmp_path)
    data = fake.root / "data" / "inputs" / "macro_calendar.csv"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"ts,class\n")
    guard = PathGuard(_fixture_set(), fake.root)
    with guard.open_input(data) as fh:
        assert fh.read() == b"ts,class\n"


@pytest.mark.unit
@pytest.mark.parametrize(
    "relative",
    ["docs/macro_calendar.csv", "research/data/x.csv", "tests/fixtures/x.csv", "data/scratch.csv", "config/../docs/x.csv"],
)
def test_F1_AC7_path_guard_refuses_an_input_outside_the_set_naming_it(tmp_path: Path, relative: str) -> None:
    fake = make_root(tmp_path)
    target = fake.root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")
    guard = PathGuard(_fixture_set(), fake.root)
    with pytest.raises(EnginePathError) as info:
        guard.open_input(target)
    assert Path(relative).name in str(info.value)


@pytest.mark.unit
def test_F1_AC7_path_guard_refuses_a_file_outside_the_root(tmp_path: Path) -> None:
    fake = make_root(tmp_path)
    outside = tmp_path / "elsewhere" / "config" / "risk.toml"  # looks like config, but not under the root
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"")
    with pytest.raises(EnginePathError) as info:
        PathGuard(_fixture_set(), fake.root).check(outside)
    assert "risk.toml" in str(info.value)


# --- at startup ------------------------------------------------------------------------------------------------

@pytest.fixture
def rogue_engine_module(tmp_path: Path) -> Iterator[Path]:
    """A ``copytrade.*`` module whose file lives outside src/copytrade (e.g. shadowed via sys.path)."""
    path = tmp_path / "elsewhere" / "rogue_engine_module.py"
    path.parent.mkdir(parents=True)
    path.write_text("VALUE = 1\n", encoding="utf-8")
    name = "copytrade.rogue_engine_module"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    try:
        yield path
    finally:
        sys.modules.pop(name, None)


@pytest.mark.integration
def test_F1_AC7_startup_passes_with_every_input_inside_the_set(tmp_path: Path, canary_secrets: dict[str, str]) -> None:
    fake = make_root(tmp_path)
    engine_files = [REPO_ROOT / "src" / "copytrade" / "core" / "config.py", REPO_ROOT / "src" / "copytrade" / "__init__.py"]
    result = startup(fake.root, canary_secrets, code_root=REPO_ROOT, engine_module_files=engine_files)
    assert result.path_set.covers("config/risk.toml")


@pytest.mark.integration
def test_F1_AC7_startup_fails_closed_when_the_manifest_is_missing(tmp_path: Path, canary_secrets: dict[str, str]) -> None:
    fake = make_root(tmp_path)
    (fake.root / "engine-path-set.txt").unlink()
    with pytest.raises(EnginePathError) as info:
        startup(fake.root, canary_secrets, code_root=REPO_ROOT, engine_module_files=[])
    assert "engine-path-set.txt" in str(info.value)


@pytest.mark.integration
def test_F1_AC7_startup_fails_closed_when_a_config_file_is_outside_the_set(tmp_path: Path, canary_secrets: dict[str, str]) -> None:
    lines = [e for e in REQUIRED_ENTRIES if e != "config/**"]
    fake = make_root(tmp_path, manifest_lines=lines)
    with pytest.raises(EnginePathError) as info:
        startup(fake.root, canary_secrets, code_root=REPO_ROOT, engine_module_files=[])
    assert ".toml" in str(info.value) and "config" in str(info.value)


@pytest.mark.integration
@pytest.mark.parametrize("calendar_file", ["docs/macro_calendar.csv", "../outside/macro_calendar.csv", "research/macro_calendar.csv"])
def test_F1_AC7_startup_fails_closed_when_a_data_input_is_outside_the_set(
    tmp_path: Path, canary_secrets: dict[str, str], calendar_file: str
) -> None:
    fake = make_root(tmp_path, ConfigTree().set("calendar.file", calendar_file))
    with pytest.raises(EnginePathError) as info:
        startup(fake.root, canary_secrets, code_root=REPO_ROOT, engine_module_files=[])
    assert "macro_calendar.csv" in str(info.value)


@pytest.mark.integration
def test_F1_AC7_startup_fails_closed_when_an_engine_module_is_outside_the_set(
    tmp_path: Path, canary_secrets: dict[str, str], rogue_engine_module: Path
) -> None:
    fake = make_root(tmp_path)
    engine_files = [REPO_ROOT / "src" / "copytrade" / "core" / "config.py", rogue_engine_module]
    with pytest.raises(EnginePathError) as info:
        startup(fake.root, canary_secrets, code_root=REPO_ROOT, engine_module_files=engine_files)
    assert "rogue_engine_module.py" in str(info.value)


@pytest.mark.integration
def test_F1_AC7_cli_start_names_an_imported_engine_module_outside_the_set(tmp_path: Path, rogue_engine_module: Path) -> None:
    fake = make_root(tmp_path)
    result = run_cli(["start", "--root", str(fake.root)])
    assert result.code != 0
    assert "rogue_engine_module.py" in result.stderr
