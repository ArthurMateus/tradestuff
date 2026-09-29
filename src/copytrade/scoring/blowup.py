"""Blow-up detectors BU1-BU8 (F5.AC4). Interface stub; the developer owns the implementation."""


from __future__ import annotations

from collections.abc import Sequence

from copytrade.core.config import Config
from copytrade.scoring.models import Metrics, TripRecord


def detect_blowups(records: Sequence[TripRecord], m: Metrics, *, cfg: Config) -> tuple[str, ...]:
    """Return the sorted ids (``"BU1"``..``"BU8"``) of every detector that fires, at the section 10.5 boundaries.

    A detector never fires below its minimum sample. Trips are taken in ``open_ms`` order.
    """
    raise NotImplementedError
