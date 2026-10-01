"""The flatten supervisor: the bot's ``/flatten`` goes through it, and the loop re-runs it until all is closed."""

from __future__ import annotations

from collections.abc import Callable

from copytrade.core.events import Alert, AlertSink
from copytrade.positions.manager import PositionManager
from copytrade.risk.types import FlattenReport

ALERT_FLATTEN_INCOMPLETE = "flatten_incomplete"
FLATTEN_RERUN_INTERVAL_S = 5
FLATTEN_RERUN_MAX = 12


class FlattenSupervisor:
    """Owns every call of ``PositionManager.flatten``. The gate refuses a second flatten with the same run id (A5), and
    an entry that was in flight when the first flatten ran fills later and then needs another one, so every call gets
    a NEW run id (``<base>:flatten:<n>``) and, while the last report still lists ``in_flight`` entries or
    ``still_open`` shares, the loop calls ``rerun_if_due`` (every ``FLATTEN_RERUN_INTERVAL_S`` of local time, at most
    ``FLATTEN_RERUN_MAX`` times, then one ``flatten_incomplete`` alert). Every call runs under the caller's gate lock.
    """

    def __init__(self, *, manager: PositionManager, alerts: AlertSink, now_ms: Callable[[], int]) -> None:
        self._manager = manager
        self._alerts = alerts
        self._now_ms = now_ms
        self._runs: list[str] = []
        self._base = ""
        self._unfinished = False
        self._reruns = 0
        self._next_due_ms = 0

    @property
    def runs(self) -> tuple[str, ...]:
        return tuple(self._runs)

    def flatten(self, *, run_id: str) -> FlattenReport:
        """The bot's call (``run_id`` is the base). Starts a new series of re-runs."""
        self._reruns = 0
        return self._run(run_id)

    def rerun_if_due(self) -> None:
        if not self._unfinished or self._now_ms() < self._next_due_ms:
            return
        if self._reruns >= FLATTEN_RERUN_MAX:
            self._unfinished = False
            self._alerts.send(
                Alert(
                    kind=ALERT_FLATTEN_INCOMPLETE,
                    message=f"flatten is still not complete after {FLATTEN_RERUN_MAX} re-runs: check the positions",
                )
            )
            return
        self._reruns += 1
        self._run(self._base)

    def _run(self, base: str) -> FlattenReport:
        self._base = base
        run_id = f"{base}:flatten:{len(self._runs) + 1}"
        self._runs.append(run_id)
        report = self._manager.flatten(run_id=run_id)
        self._unfinished = bool(report.in_flight or report.still_open)
        self._next_due_ms = self._now_ms() + FLATTEN_RERUN_INTERVAL_S * 1000
        return report
