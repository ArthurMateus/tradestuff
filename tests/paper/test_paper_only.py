# mypy: disable-error-code="union-attr"
"""Paper-only, no network, no signing, no floats (F1.AC3 / F1.AC4 keep holding for src/copytrade/paper/**; A6, A10;
config fail-closed per A2/A3)."""

from __future__ import annotations

import ast
from decimal import Decimal as D
from pathlib import Path

import pytest
from typing import Any
from tests.paper.helpers import NewEnv

from copytrade.core.config import Config
from copytrade.core.domain import ActionKind
from copytrade.core.errors import ConfigError, ModeNotPermittedError
from copytrade.core.money import Fee, Funding, Pnl, Price, Qty
from tests.core.helpers import REPO_ROOT
from tests.core.test_mode_paper_only import FORBIDDEN_MODULES
from tests.paper.helpers import BASE, D0, HOUR_MS, build_env, make_config

PAPER_SRC = REPO_ROOT / "src" / "copytrade" / "paper"
NETWORK_MODULES = ("socket", "ssl", "http", "urllib", "requests", "httpx", "aiohttp", "websocket", "websockets",
                   "ftplib", "smtplib", "xmlrpc")
REQUIRED_KEYS = (
    "mode", "paper.wallet_usd", "paper.ack_delay_ms", "paper.max_book_age_ms", "paper.meta_refresh_min",
    "cost.taker_fee_bps", "sizing.min_order_usd", "exits.retry_interval_s", "exits.alert_after_s",
)


def _files() -> list[Path]:
    return sorted(PAPER_SRC.rglob("*.py"))


def _under(module: str, roots: tuple[str, ...]) -> bool:
    return any(module == r or module.startswith(r + ".") for r in roots)


@pytest.mark.unit
def test_F11_paper_package_exists_and_is_scanned() -> None:
    names = {p.name for p in _files()}
    assert {"broker.py", "gate.py", "liquidation.py", "ports.py", "types.py"} <= names


@pytest.mark.unit
def test_F1_AC3_paper_package_imports_no_signing_client_and_no_network_module() -> None:
    offenders: list[str] = []
    for path in _files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            for m in mods:
                if _under(m, FORBIDDEN_MODULES) or _under(m, NETWORK_MODULES):
                    offenders.append(f"{path.name}: {m}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "/exchange" in node.value:
                offenders.append(f"{path.name}: literal {node.value!r}")
    assert offenders == []


@pytest.mark.unit
def test_F1_AC4_paper_package_has_no_float_literal_and_no_float_call() -> None:
    offenders: list[str] = []
    for path in _files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                offenders.append(f"{path.name}:{node.lineno} float literal {node.value!r}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
                offenders.append(f"{path.name}:{node.lineno} float()")
    assert offenders == []


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["live", "testnet", "Paper", "", "paper "])
def test_F1_AC3_broker_refuses_any_mode_but_paper(tmp_path: Path, mode: Any) -> None:
    with pytest.raises(ModeNotPermittedError) as err:
        build_env(tmp_path, config=make_config(mode=mode))
    assert "mode not permitted in this build" in str(err.value)


@pytest.mark.unit
@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_A2_a_missing_config_key_fails_closed_naming_the_key(tmp_path: Path, key: Any) -> None:
    data = dict(make_config())
    del data[key]
    with pytest.raises(ConfigError) as err:
        build_env(tmp_path, config=Config(data))
    assert err.value.key == key


@pytest.mark.unit
@pytest.mark.parametrize(
    "key,bad,good",
    [
        ("cost.taker_fee_bps", D("4.4"), D("4.5")),
        ("cost.taker_fee_bps", D("20.1"), D("20")),
        ("paper.ack_delay_ms", 499, 500),
        ("paper.ack_delay_ms", 5001, 5000),
        ("paper.max_book_age_ms", 999, 1000),
        ("paper.max_book_age_ms", 5001, 5000),
        ("paper.meta_refresh_min", 4, 5),
        ("sizing.min_order_usd", D("9.99"), D("10")),
    ],
)
def test_A3_out_of_range_config_is_refused_at_the_boundary_and_the_limit_itself_loads(tmp_path: Path, key: Any, bad: Any, good: Any) -> None:
    with pytest.raises(ConfigError) as err:
        build_env(tmp_path / "bad", config=make_config(**{key.replace(".", "__"): bad}))
    assert err.value.key == key
    ok = build_env(tmp_path / "good", config=make_config(**{key.replace(".", "__"): good}))
    ok.ledger.close()


@pytest.mark.unit
def test_F1_AC4_a_float_config_value_is_refused(tmp_path: Path) -> None:
    with pytest.raises((TypeError, ConfigError)):
        build_env(tmp_path, config=make_config(cost__taker_fee_bps=4.5))


@pytest.mark.unit
def test_F1_AC4_money_returned_by_the_broker_is_decimal_typed_never_float(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.funding.set("SOL", BASE + HOUR_MS, "0.0001", "100")
    e.advance(BASE + HOUR_MS)
    e.flat_book("SOL", BASE + HOUR_MS + 61_000, "101")
    e.advance(BASE + HOUR_MS + 60_000)  # broker time reaches the exit's decision time (Amendment 10)
    e.submit(e.order("sell", "1.0", coid="x", action=ActionKind.CLOSE, decided=BASE + HOUR_MS + 60_000, px="101"))
    events = e.advance(BASE + HOUR_MS + 61_000)
    fill = events[0].fill
    assert isinstance(fill.price, Price) and isinstance(fill.qty, Qty)
    assert isinstance(fill.fee, Fee) and isinstance(fill.funding, Funding)
    assert isinstance(events[0].trade.pnl_usd, Pnl)
    assert type(e.broker.cash_usd()) is D
    assert isinstance(e.records("paper_funding")[0].payload["amount"], D)


@pytest.mark.unit
def test_F1_AC3_a_full_paper_session_makes_no_network_attempt(new_env: NewEnv, network_guard: Any) -> None:
    before_attempts, before_connects = len(network_guard.attempts), len(network_guard.all_connects)
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.stop("sl", "sell", "1.0", "99")
    e.mark("SOL", "50", D0 + 20_000)
    e.advance(D0 + 3 * HOUR_MS)
    assert len(network_guard.attempts) == before_attempts
    assert len(network_guard.all_connects) == before_connects  # not even loopback
