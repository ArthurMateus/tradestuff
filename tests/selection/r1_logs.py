"""Log-record helpers for the R1 tests (the backfiller reports through the standard logging ``extra`` fields)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

BACKFILL_LOGGER = "copytrade.selection.backfill"


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == event]


def attr(record: logging.LogRecord, name: str) -> Any:
    return getattr(record, name, None)
