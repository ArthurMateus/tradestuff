"""The slice of the ledger (F2) that F3 writes to. F2 supplies the adapter; F3 owns this port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DowntimeRecord:
    """A downtime interval. ``kind`` is ``"data_gap"`` or ``"access_degraded"``.

    ``start_ms`` and ``end_ms`` are UTC epoch milliseconds (start < end). ``wallets`` names the affected
    wallets for ``data_gap`` and is empty for ``access_degraded``.
    """

    kind: str
    start_ms: int
    end_ms: int
    wallets: tuple[str, ...]


class DowntimeSink(Protocol):
    """Where downtime intervals are ledgered. An external boundary (the ledger)."""

    def record_downtime(self, record: DowntimeRecord) -> None: ...
