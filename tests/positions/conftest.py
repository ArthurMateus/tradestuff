"""Fixtures for the F12 tests (own file): a factory that builds the rig inside the test body and closes ledgers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.positions.helpers import Rig, build_rig

NewRig = Callable[..., Rig]


@pytest.fixture
def new_rig(tmp_path: Path, request: pytest.FixtureRequest) -> NewRig:
    built: list[Rig] = []

    def factory(**kwargs: Any) -> Rig:
        sub = tmp_path / f"rig{len(built)}"
        sub.mkdir()
        rig = build_rig(sub, **kwargs)
        built.append(rig)
        return rig

    def close_all() -> None:
        for rig in built:
            rig.env.ledger.close()

    request.addfinalizer(close_all)
    return factory
