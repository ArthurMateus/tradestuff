"""The sleeper of the REST client the trading thread uses (R2.AC2)."""

from __future__ import annotations

from copytrade.hl.budget import Sleeper
from copytrade.hl.errors import HlBudgetError


class TradingSleeper:
    """Sleeper of the REST client the trading thread uses. While the runner starts it sleeps like the injected one (a
    start-up request may wait out a 429 back-off); from ``fail_fast`` on it never sleeps: a request that would wait
    (a retry back-off, a rate-budget wait) fails at once and the caller tries again at its own cadence, so no REST
    call blocks the loop (R2.AC2)."""

    def __init__(self, patient: Sleeper) -> None:
        self._patient = patient
        self._fail_fast = False

    def fail_fast(self) -> None:
        self._fail_fast = True

    def sleep(self, seconds: float) -> None:
        if self._fail_fast:
            raise HlBudgetError(
                f"the rate budget has no room for this request now (would wait {seconds:.1f} s)", wait_s=seconds
            )
        self._patient.sleep(seconds)
