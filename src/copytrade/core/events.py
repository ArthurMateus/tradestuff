"""Alerts and events shared across features (F1).

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Alert:
    """An operator alert. ``kind`` is a stable machine-readable code, e.g. ``"clock_unsynced"``."""

    kind: str
    message: str


class AlertSink(Protocol):
    """Where alerts go (Telegram in F14, the local log before that). An external boundary."""

    def send(self, alert: Alert) -> None: ...
