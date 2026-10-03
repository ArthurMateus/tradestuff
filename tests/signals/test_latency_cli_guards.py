"""F7.AC6 developer additions: the ``latency measure`` command refuses the engine ledger directory (test-plan S4) and
says so plainly when the real boundaries cannot be built (S1: no WebSocket connector exists yet)."""

from __future__ import annotations

from pathlib import Path

import pytest

import copytrade.cli.latency as latency_cli
from tests.core.helpers import make_root, run_cli
from tests.signals.helpers import WALLET_A

pytestmark = pytest.mark.integration


def test_F7_AC6_the_engine_ledger_directory_is_refused_as_a_measurement_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_root(tmp_path / "root").root

    def build(config: object) -> object:
        raise AssertionError("boundaries must not be built when the ledger directory is refused")

    monkeypatch.setattr(latency_cli, "build_boundaries", build)
    engine_ledger = (root / "../copytrade-data/ledger").resolve()  # the fixture's storage.ledger_dir
    result = run_cli(
        [
            "latency",
            "measure",
            "--root",
            str(root),
            "--ledger-dir",
            str(engine_ledger),
            "--hours",
            "1",
            "--wallets",
            WALLET_A,
        ]
    )
    assert result.code == 2 and "engine ledger" in result.stderr
    assert not engine_ledger.exists()


def test_F7_AC6_without_a_real_connector_the_command_exits_1_and_creates_no_ledger(tmp_path: Path) -> None:
    root = make_root(tmp_path / "root").root
    ledger_dir = tmp_path / "lat"
    result = run_cli(
        [
            "latency",
            "measure",
            "--root",
            str(root),
            "--ledger-dir",
            str(ledger_dir),
            "--hours",
            "1",
            "--wallets",
            WALLET_A,
        ]
    )
    assert result.code == 1 and "WebSocket connector" in result.stderr
    assert not ledger_dir.exists()
