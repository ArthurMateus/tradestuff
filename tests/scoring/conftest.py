from __future__ import annotations

from pathlib import Path

import pytest

from copytrade.core.config import Config
from tests.scoring.helpers import make_cfg
from tests.scoring.wallets import PERMISSIVE_CFG, WINDOW_DAYS


@pytest.fixture(scope="session")
def cfg90(tmp_path_factory: pytest.TempPathFactory) -> Config:
    """The valid fixture config with a 90-day fill window (the ceiling's minimum), so hand-built wallets stay small."""
    return make_cfg(tmp_path_factory.mktemp("cfg90"), **{"scoring.window_days": WINDOW_DAYS})


@pytest.fixture(scope="session")
def cfg_default(tmp_path_factory: pytest.TempPathFactory) -> Config:
    return make_cfg(tmp_path_factory.mktemp("cfgdef"))


@pytest.fixture(scope="session")
def cfg_permissive(tmp_path_factory: pytest.TempPathFactory) -> Config:
    """A 90-day window with the sample-size gates relaxed so the 80-trip ``healthy`` wallets are eligible."""
    return make_cfg(tmp_path_factory.mktemp("cfgperm"), **PERMISSIVE_CFG)


def cfg_with(tmp_path: Path, **overrides: object) -> Config:
    return make_cfg(tmp_path, **overrides)
