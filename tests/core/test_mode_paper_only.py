"""F1.AC3: paper only. ``mode`` other than ``paper`` is refused; no Hyperliquid ``/exchange`` request is
ever made in a test run; no module imports an order-signing client.

Spec: 04-spec.md F1.AC3, §3.1 ``mode``, invariant A10, §7 E1, DoD item 12.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import socket
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

import copytrade
from copytrade.core.config import load_config
from copytrade.core.errors import ConfigError, ModeNotPermittedError
from copytrade.core.startup import startup
from tests.core.helpers import REPO_ROOT, ConfigTree, make_root, run_cli

SRC = REPO_ROOT / "src" / "copytrade"
MODE_MESSAGE = "mode not permitted in this build"

# Distributions and modules that can sign Hyperliquid (or any exchange) orders.
FORBIDDEN_MODULES = ("hyperliquid", "eth_account", "eth_keys", "web3", "ccxt", "coincurve")
FORBIDDEN_DISTRIBUTIONS = ("hyperliquid-python-sdk", "eth-account", "eth-keys", "web3", "ccxt", "coincurve")


# --- mode ---------------------------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("mode", ["live", "testnet"])
def test_F1_AC3_live_and_testnet_modes_fail_with_the_exact_message(tmp_path: Path, mode: str) -> None:
    config_dir = ConfigTree().set("mode", mode).write(tmp_path / "config")
    with pytest.raises(ModeNotPermittedError) as info:
        load_config(config_dir)
    assert MODE_MESSAGE in str(info.value)
    assert info.value.key == "mode"


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["Paper", "PAPER", " paper", "paper ", "LIVE", "dry-run", "", "paper​"], ids=repr)
def test_F1_AC3_any_mode_that_is_not_exactly_paper_is_refused(tmp_path: Path, mode: str) -> None:
    config_dir = ConfigTree().set("mode", mode).write(tmp_path / "config")
    with pytest.raises(ConfigError) as info:
        load_config(config_dir)
    assert info.value.key == "mode"


@pytest.mark.unit
def test_F1_AC3_paper_mode_loads(tmp_path: Path) -> None:
    assert load_config(ConfigTree().write(tmp_path / "config"))["mode"] == "paper"


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["live", "testnet"])
def test_F1_AC3_startup_refuses_live_and_testnet(tmp_path: Path, mode: str, canary_secrets: dict[str, str]) -> None:
    fake = make_root(tmp_path, ConfigTree().set("mode", mode))
    with pytest.raises(ModeNotPermittedError) as info:
        startup(fake.root, canary_secrets, code_root=REPO_ROOT, engine_module_files=[])
    assert MODE_MESSAGE in str(info.value)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["live", "testnet"])
def test_F1_AC3_cli_start_exits_nonzero_with_the_exact_message(tmp_path: Path, mode: str, network_guard: Any) -> None:
    fake = make_root(tmp_path, ConfigTree().set("mode", mode))
    before = len(network_guard.all_connects)
    result = run_cli(["start", "--root", str(fake.root)])
    assert result.code != 0
    assert MODE_MESSAGE in result.stderr
    assert network_guard.all_connects[before:] == []


@pytest.mark.integration
@pytest.mark.parametrize("flag", [["--mode", "live"], ["--live"], ["--testnet"]], ids=" ".join)
def test_F1_AC3_no_cli_flag_can_select_live_or_testnet(tmp_path: Path, flag: list[str]) -> None:
    fake = make_root(tmp_path, ConfigTree())
    result = run_cli(["start", "--root", str(fake.root), *flag])
    assert result.code != 0


# --- no /exchange request in any test run ----------------------------------------------------------------

@pytest.mark.integration
def test_F1_AC3_network_guard_blocks_and_records_any_request_to_the_exchange_endpoint(network_guard: Any) -> None:
    # The suite-wide guard (tests/conftest.py) is what makes "0 requests to /exchange" hold for every test:
    # nothing non-loopback can connect, and any attempt fails the test that made it and the session.
    with network_guard.expect_blocked() as seen:
        with pytest.raises(OSError):
            socket.create_connection(("api.hyperliquid.xyz", 443), timeout=1)
        with pytest.raises(OSError):
            socket.create_connection(("203.0.113.7", 443), timeout=1)  # numeric address skips DNS
    assert ("getaddrinfo", "api.hyperliquid.xyz") in seen
    assert any(op == "connect" and "203.0.113.7" in target for op, target in seen)


@pytest.mark.integration
def test_F1_AC3_importing_every_engine_module_makes_no_network_attempt(network_guard: Any) -> None:
    before = len(network_guard.all_connects)
    for info in pkgutil.walk_packages(copytrade.__path__, prefix="copytrade."):
        importlib.import_module(info.name)
    assert network_guard.all_connects[before:] == []


# --- no order-signing client -----------------------------------------------------------------------------

def _source_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _forbidden_references(source: str, filename: str) -> list[str]:
    """Imports of signing clients, dynamic imports of them, and literals naming the /exchange endpoint."""
    tree = ast.parse(source, filename=filename)
    found: list[str] = []

    def bad(module: str) -> bool:
        return any(module == m or module.startswith(m + ".") for m in FORBIDDEN_MODULES)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if bad(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0 and bad(node.module):
            found.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            arg = node.args[0].value
            if name in ("import_module", "__import__") and isinstance(arg, str) and bad(arg):
                found.append(f"{name}({arg!r})")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "/exchange" in node.value:
            found.append(f"literal {node.value!r}")
    return found


@pytest.mark.unit
def test_F1_AC3_static_scan_detects_a_signing_import_in_synthetic_source() -> None:
    # Proves the scanner is not vacuous before trusting its "nothing found" on the real tree.
    synthetic = (
        "import eth_account\n"
        "from hyperliquid.exchange import Exchange\n"
        "import importlib\nimportlib.import_module('web3')\n"
        "URL = 'https://api.hyperliquid.xyz/exchange'\n"
    )
    assert len(_forbidden_references(synthetic, "<synthetic>")) == 4


@pytest.mark.unit
def test_F1_AC3_no_engine_module_imports_an_order_signing_client() -> None:
    files = _source_files()
    assert SRC / "core" / "config.py" in files  # the scan really covers the engine tree
    offenders = {
        str(p.relative_to(REPO_ROOT)): refs
        for p in files
        if (refs := _forbidden_references(p.read_text(encoding="utf-8"), str(p)))
    }
    assert offenders == {}


@pytest.mark.unit
def test_F1_AC3_lockfile_pins_no_order_signing_distribution() -> None:
    lock = REPO_ROOT / "uv.lock"
    assert lock.exists()
    with lock.open("rb") as fh:
        names = {pkg["name"] for pkg in tomllib.load(fh).get("package", [])}
    assert "copytrade" in names  # the lockfile really is this project's
    assert names.isdisjoint(FORBIDDEN_DISTRIBUTIONS)


@pytest.mark.unit
def test_F1_AC3_importing_every_engine_module_loads_no_signing_module() -> None:
    for info in pkgutil.walk_packages(copytrade.__path__, prefix="copytrade."):
        importlib.import_module(info.name)
    loaded = [m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in FORBIDDEN_MODULES)]
    assert loaded == []
