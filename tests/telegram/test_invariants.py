"""F14 static and invariant tests: chokepoint (A1), no new dependency, visibility lock imports (AC6), secrets."""

from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "src" / "copytrade" / "telegram"
FORBIDDEN_IMPORTS = ("copytrade.evaluation", "copytrade.baselines", "copytrade.reports")
ORDER_APIS = {"submit", "place_stop", "cancel", "open_position", "close_position"}


def _sources() -> list[Path]:
    files = sorted(PKG.glob("*.py"))
    assert files, "src/copytrade/telegram/ does not exist yet"
    return files


def test_F14_AC6_telegram_never_imports_evaluation_baselines_or_reports() -> None:
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(FORBIDDEN_IMPORTS), f"{path.name} imports {name}"


def test_F14_A1_telegram_has_no_path_to_order_apis() -> None:
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute):
                assert node.attr not in ORDER_APIS, f"{path.name}:{node.lineno} touches .{node.attr}"
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("copytrade.hl.exchange"), path.name


def test_F14_deps_only_stdlib_and_copytrade_are_imported() -> None:
    allowed = set(sys.stdlib_module_names) | {"copytrade", "__future__"}
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots = [node.module.split(".")[0]]
            for root in roots:
                assert root in allowed, f"{path.name} imports the third-party module {root}"


def test_F14_A_the_token_and_pin_come_only_from_injected_secrets_not_files_or_literals() -> None:
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        assert "os.environ" not in text and "getenv" not in text, "the runner passes secrets in (core.secrets)"
        assert "api.telegram.org" not in text or path.name == "api.py"


def test_F14_AC5_a_full_session_never_logs_the_token(new_bot, caplog) -> None:  # type: ignore[no-untyped-def]
    from tests.telegram.helpers import PIN, TOKEN

    caplog.set_level(logging.DEBUG)
    env = new_bot()
    env.rig.open_share()
    env.command("/status")
    env.command(f"/flatten {PIN}")
    env.server.mode = "down"
    env.command("/pause")
    assert TOKEN not in caplog.text
