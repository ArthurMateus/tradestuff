"""F2.AC1 and F2.AC4 through the command line: ``copytrade ledger verify`` and ``copytrade export fills``.

The CLI registry (F1) discovers ``copytrade/cli/ledger.py`` at runtime.

Spec: 04-spec.md F2.AC1 ("verified at startup and via CLI"), F2.AC4.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from copytrade.ledger.store import Ledger
from tests.core.helpers import run_cli
from tests.ledger.helpers import T0, FakeClock, flip_byte, line_span, make_fill

pytestmark = pytest.mark.integration


def _build(directory: Path, fills: int = 4) -> None:
    with Ledger.open(directory, clock=FakeClock()) as ledger:
        for i in range(fills):
            ledger.append_fill(make_fill(i, time_ms=T0 + i * 60_000))


def test_F2_AC1_cli_verify_passes_on_an_intact_ledger(tmp_path: Path) -> None:
    directory = tmp_path / "ledger"
    _build(directory, 4)
    result = run_cli(["ledger", "verify", "--ledger-dir", str(directory)])
    assert result.code == 0, result.stderr
    assert "4" in result.stdout


def test_F2_AC1_cli_verify_on_an_empty_or_missing_ledger_is_valid(tmp_path: Path) -> None:
    result = run_cli(["ledger", "verify", "--ledger-dir", str(tmp_path / "nothing-here")])
    assert result.code == 0, result.stderr
    assert "0" in result.stdout


def test_F2_AC1_cli_verify_fails_non_zero_and_names_the_sequence_number(tmp_path: Path) -> None:
    directory = tmp_path / "ledger"
    _build(directory, 5)
    flip_byte(directory, line_span(directory, 4)[0] + 12)
    result = run_cli(["ledger", "verify", "--ledger-dir", str(directory)])
    assert result.code != 0
    assert "4" in result.stderr
    assert "Traceback" not in result.stderr


def test_F2_AC4_cli_export_fills_writes_the_csv_for_the_range_to_a_file(tmp_path: Path) -> None:
    directory = tmp_path / "ledger"
    _build(directory, 4)  # fills at T0, +1min, +2min, +3min  (T0 = 2026-09-21T14:13:20Z)
    out = tmp_path / "fills.csv"
    result = run_cli([
        "export", "fills", "--ledger-dir", str(directory),
        "--from", "2026-09-21T14:14:20Z", "--to", "2026-09-21T14:16:20Z", "--out", str(out),
    ])
    assert result.code == 0, result.stderr
    rows = list(csv.reader(io.StringIO(out.read_text(encoding="utf-8"))))
    assert rows[0][0] == "time" and len(rows) == 3  # header + the fills at +1 min and +2 min
    assert [r[7] for r in rows[1:]] == ["coid-1", "coid-2"]


def test_F2_AC4_cli_export_fills_defaults_to_stdout(tmp_path: Path) -> None:
    directory = tmp_path / "ledger"
    _build(directory, 2)
    result = run_cli(["export", "fills", "--ledger-dir", str(directory), "--from", "2026-01-01T00:00:00Z", "--to", "2027-01-01T00:00:00Z"])
    assert result.code == 0, result.stderr
    assert len(list(csv.reader(io.StringIO(result.stdout)))) == 3


@pytest.mark.parametrize("bad", ["yesterday", "2026-09-21", "2026-09-21T14:13:20", "1790000000000", ""], ids=repr)
def test_F2_AC4_cli_export_rejects_dates_that_are_not_explicit_utc_instants(tmp_path: Path, bad: str) -> None:
    directory = tmp_path / "ledger"
    _build(directory, 1)
    result = run_cli(["export", "fills", "--ledger-dir", str(directory), "--from", bad, "--to", "2027-01-01T00:00:00Z"])
    assert result.code != 0
    assert "Traceback" not in result.stderr


def test_F2_AC4_cli_export_refuses_a_tampered_ledger_and_writes_no_file(tmp_path: Path) -> None:
    directory = tmp_path / "ledger"
    _build(directory, 4)
    flip_byte(directory, line_span(directory, 2)[0] + 9)
    out = tmp_path / "fills.csv"
    result = run_cli(["export", "fills", "--ledger-dir", str(directory), "--from", "2026-01-01T00:00:00Z",
                      "--to", "2027-01-01T00:00:00Z", "--out", str(out)])
    assert result.code != 0
    assert "2" in result.stderr
    assert not out.exists() or out.read_text(encoding="utf-8") == ""
