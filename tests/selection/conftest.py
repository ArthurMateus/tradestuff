"""Fixtures for the F6 tests. Rigs are built inside test bodies so that a not-yet-built stub fails the test itself."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.selection.helpers import Rig, make_rig


@pytest.fixture
def rig_factory(tmp_path: Path) -> Iterator[Callable[..., Rig]]:
    made: list[Rig] = []
    counter = 0

    def build(**kwargs: Any) -> Rig:
        nonlocal counter
        counter += 1
        base = tmp_path / f"rig{counter}"
        base.mkdir()
        rig = make_rig(base, **kwargs)
        made.append(rig)
        return rig

    yield build
    for rig in made:
        rig.ledger.close()
