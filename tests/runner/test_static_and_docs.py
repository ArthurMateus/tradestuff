"""R0.AC14 (Windows README) and R0.AC15 (static guards over src/copytrade/runner and the CLI entry)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.core.helpers import REPO_ROOT

RUNNER_DIR = REPO_ROOT / "src" / "copytrade" / "runner"
README = REPO_ROOT / "README.md"
ORDER_CALLS = {"submit", "place_stop", "cancel_stop", "issue"}
TIME_CALLS = {"advance_to", "on_mark", "on_delist", "flatten"}


def runner_trees() -> dict[Path, ast.AST]:
    files = sorted(RUNNER_DIR.glob("*.py"))
    assert len(files) >= 8, "the runner package is not there yet"
    return {f: ast.parse(f.read_text(encoding="utf-8")) for f in files}


def calls(tree: ast.AST) -> list[tuple[str, str, int]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            out.append((node.func.attr, ast.unparse(node.func.value), node.lineno))
    return out


def test_R0_AC15_the_runner_never_places_orders_itself_a1_chokepoint() -> None:
    all_calls = [c for tree in runner_trees().values() for c in calls(tree)]
    assert any(a == "advance_to" and "manager" in r for a, r, _ in all_calls), "the loop advances through the manager"
    for path, tree in runner_trees().items():
        offenders = [(a, r, n) for a, r, n in calls(tree) if a in ORDER_CALLS]
        assert offenders == [], f"{path.name} reaches the order path directly: {offenders}"


def test_R0_AC15_only_the_manager_moves_broker_time_marks_and_flattens() -> None:
    seen = {a for tree in runner_trees().values() for a, r, _ in calls(tree) if a in TIME_CALLS and "manager" in r}
    assert seen == TIME_CALLS, f"the runner must drive {TIME_CALLS - seen} through the position manager"
    for path, tree in runner_trees().items():
        for attr, receiver, line in calls(tree):
            if attr in TIME_CALLS:
                assert "broker" not in receiver and "gate" not in receiver, f"{path.name}:{line} {receiver}.{attr}"


def test_R0_AC15_the_runner_reads_no_environment_and_no_secret_files() -> None:
    assert "startup(" in (RUNNER_DIR / "wiring.py").read_text(encoding="utf-8")  # the F1 startup checks load the secrets
    for path, tree in runner_trees().items():
        text = ast.unparse(tree)
        assert "os.environ" not in text and "os.getenv" not in text and "getenv(" not in text, path.name
        assert not re.search(r"read_text\(.*(key|secret|token)", text, re.I), path.name


def test_R0_AC15_every_thread_is_named_with_the_r0_prefix_and_is_a_daemon() -> None:
    found = 0
    for path, tree in runner_trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func) in ("threading.Thread", "Thread"):
                kw = {k.arg: k.value for k in node.keywords}
                assert "name" in kw and "r0-" in ast.unparse(kw["name"]), f"{path.name}:{node.lineno} unnamed thread"
                assert "daemon" in kw and ast.unparse(kw["daemon"]) == "True", f"{path.name}:{node.lineno}"
                found += 1
    assert found >= 3


def test_R0_AC15_no_exchange_endpoint_literal_and_only_info_ws_stats_and_telegram_hosts() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in RUNNER_DIR.glob("*.py"))
    assert "/exchange" not in text
    hosts = set(re.findall(r"https?://([A-Za-z0-9.\-]+)", text)) | set(re.findall(r"wss?://([A-Za-z0-9.\-]+)", text))
    assert hosts == {"api.hyperliquid.xyz", "stats-data.hyperliquid.xyz", "api.telegram.org"}


def test_R0_AC15_run_is_the_only_new_cli_module_and_it_has_no_mode_option() -> None:
    cli = (REPO_ROOT / "src" / "copytrade" / "cli" / "run.py").read_text(encoding="utf-8")
    assert "add_parser(\"run\"" in cli or "add_parser('run'" in cli
    assert "--mode" not in cli and "--live" not in cli and "--testnet" not in cli
    assert "os.environ" in cli  # the ONE place the process environment is read


# -------------------------------------------------------------------------------------------- the Windows README


def windows_section() -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"^#{1,3} .*Windows.*$", text, re.M)
    assert match, "README.md needs a Windows section"
    rest = text[match.end() :]
    nxt = re.search(r"^#{1,2} ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def test_R0_AC14_the_windows_readme_has_every_step_the_po_needs() -> None:
    section = windows_section().lower()
    for needle in (
        "python 3.11", "uv", "uv sync", "copytrade run", "ctrl+c", "ledger", "config", "powershell",
        "copytrade_telegram_token", "copytrade_telegram_pin_hash", "copytrade_telegram_pin_salt",
        "/pause", "/resume", "/flatten", "paper", "log",
    ):
        assert needle in section, f"the Windows section does not mention {needle!r}"


def test_R0_AC14_the_readme_says_where_data_lives_and_what_to_watch_in_telegram() -> None:
    section = windows_section().lower()
    assert "copytrade-data" in section or "storage.ledger_dir" in section
    assert "startup_uncertain" in section and "clock_unsynced" in section and "disk_free_low" in section
    assert "never" in section and "live" in section  # never real money / live mode refused


def test_R0_AC14_the_readme_never_shows_a_real_looking_secret() -> None:
    section = windows_section()
    assert "COPYTRADE_TELEGRAM_TOKEN" in section
    assert not re.search(r"\d{6,}:[A-Za-z0-9_-]{20,}", section)  # a bot token shape
    assert not re.search(r"[0-9a-f]{40,}", section)  # a PIN hash shape
