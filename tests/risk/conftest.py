"""Fixtures for the F10 tests (own file; shared conftest files are untouched)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.risk.helpers import RiskEnv, build_risk_env

NewRisk = Callable[..., RiskEnv]


@pytest.fixture
def new_risk(tmp_path: Path, request: pytest.FixtureRequest) -> NewRisk:
    """Factory: ``new_risk(equity="300", risk__max_orders_per_min=2, ...)`` builds the real gate inside the test body,
    so a stub that raises NotImplementedError fails the test itself. Ledgers are closed at teardown."""
    built: list[RiskEnv] = []

    def factory(**kwargs: Any) -> RiskEnv:
        sub = tmp_path / f"risk{len(built)}"
        sub.mkdir()
        env = build_risk_env(sub, **kwargs)
        built.append(env)
        return env

    def close_all() -> None:
        for env in built:
            env.paper.ledger.close()

    request.addfinalizer(close_all)
    return factory
