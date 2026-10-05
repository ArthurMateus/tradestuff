"""Fixtures for the F2 ledger tests.

Registers the ledger as a secret sink (F1.AC5) from inside the ledger's own test folder, so no shared
file (tests/conftest.py) needs editing: ``SECRET_SINKS`` is the shared dict F1 provided for exactly this.
Every ledger directory a test creates through ``ledger_dir`` is read back at session end and scanned for
canary secret fragments.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from copytrade.ledger.store import Ledger
from tests.conftest import SECRET_SINKS
from tests.ledger.helpers import FakeClock

_USED_DIRS: list[Path] = []


def _ledger_text() -> str:
    chunks: list[str] = []
    for directory in _USED_DIRS:
        if directory.is_dir():
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    chunks.append(path.read_bytes().decode("utf-8", errors="replace"))
    return "\n".join(chunks)


SECRET_SINKS["ledger"] = _ledger_text


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "ledger"
    _USED_DIRS.append(directory)
    return directory


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ledger(ledger_dir: Path, clock: FakeClock) -> Iterator[Ledger]:
    opened = Ledger.open(ledger_dir, clock=clock)
    try:
        yield opened
    finally:
        opened.close()
