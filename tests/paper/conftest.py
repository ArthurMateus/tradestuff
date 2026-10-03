"""Fixtures for the F11 tests. Registers the paper ledgers as a secret sink (F1.AC5) without touching shared files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import SECRET_SINKS
from tests.paper.helpers import Env, build_env

_USED: list[Path] = []


def _paper_ledger_text() -> str:
    chunks: list[str] = []
    for directory in _USED:
        if directory.is_dir():
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    chunks.append(path.read_bytes().decode("utf-8", errors="replace"))
    return "\n".join(chunks)


SECRET_SINKS["paper_ledger"] = _paper_ledger_text


@pytest.fixture
def new_env(tmp_path: Path, request: pytest.FixtureRequest) -> Callable[..., Env]:
    """Factory: ``new_env(config=..., meta=...)`` builds the real broker inside the test body, so a stub that
    raises NotImplementedError fails the test itself. Ledgers are closed at teardown."""
    built: list[Env] = []

    def factory(**kwargs: Any) -> Env:
        sub = tmp_path / f"run{len(built)}"
        sub.mkdir()
        _USED.append(sub / "ledger")
        env = build_env(sub, **kwargs)
        built.append(env)
        return env

    def close_all() -> None:
        for e in built:
            e.ledger.close()

    request.addfinalizer(close_all)
    return factory
