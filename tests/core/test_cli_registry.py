"""F1 CLI registry (spec §10 collision rule 3): subcommands in ``copytrade/cli/<area>.py`` are discovered at
runtime, and one broken area never disables the others.

Added by the developer, not the test designer.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import copytrade.cli
from tests.core.helpers import run_cli

pytestmark = pytest.mark.integration

WORKING_AREA = '''
def register(subparsers):
    parser = subparsers.add_parser("zzdemo")
    parser.add_argument("--n", type=int, default=1)
    parser.set_defaults(handler=lambda args: 40 + args.n)
'''
BROKEN_AREA = "raise RuntimeError('this area is broken')\n"
NO_REGISTER_AREA = "VALUE = 1\n"
HELPER = "def register(subparsers):\n    raise AssertionError('helper modules must not be registered')\n"


@pytest.fixture
def extra_cli_modules(tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "cli_extra"
    folder.mkdir()
    (folder / "zz_working.py").write_text(WORKING_AREA, encoding="utf-8")
    (folder / "zz_broken.py").write_text(BROKEN_AREA, encoding="utf-8")
    (folder / "zz_no_register.py").write_text(NO_REGISTER_AREA, encoding="utf-8")
    (folder / "_helper.py").write_text(HELPER, encoding="utf-8")
    copytrade.cli.__path__.append(str(folder))
    importlib.invalidate_caches()
    try:
        yield folder
    finally:
        copytrade.cli.__path__.remove(str(folder))
        for name in [n for n in sys.modules if n.startswith("copytrade.cli.zz") or n == "copytrade.cli._helper"]:
            del sys.modules[name]
        importlib.invalidate_caches()


def test_F1_registry_a_discovered_area_module_adds_a_subcommand_without_editing_main(extra_cli_modules: Path) -> None:
    result = run_cli(["zzdemo", "--n", "2"])
    assert result.code == 42


def test_F1_registry_a_broken_area_is_reported_and_skipped_and_the_others_still_work(extra_cli_modules: Path) -> None:
    result = run_cli(["zzdemo"])
    assert result.code == 41
    assert "zz_broken" in result.stderr and "RuntimeError" in result.stderr
    assert "zz_no_register" in result.stderr
    assert "_helper" not in result.stderr


def test_F1_registry_an_unknown_subcommand_and_a_missing_subcommand_exit_non_zero() -> None:
    assert run_cli(["no-such-command"]).code != 0
    assert run_cli([]).code != 0


def test_F1_registry_help_exits_zero_and_lists_start() -> None:
    result = run_cli(["--help"])
    assert result.code == 0
    assert "start" in result.stdout
