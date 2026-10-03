"""The sleeper and the call limit of the REST clients the trading thread uses (R2.AC2, R2b.AC3)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from copytrade.hl.budget import Sleeper
from copytrade.hl.errors import HlBudgetError

TRADING_CALL_TIMEOUT_S = 2.0  # the longest one trading-thread request may take (a code constant, not a config key)
LOOP_REST_BUDGET_S = 2.0  # the REST time one loop iteration may spend in all; the rest of the work is asked again later
MIN_CALL_S = 0.05  # less time than this is no use to a request: it is refused instead of sent


def _real_monotonic() -> float:
    return time.monotonic()


class TradingSleeper:
    """Sleeper and ``CallLimit`` of the REST clients the trading thread uses.

    Sleeping: while the runner starts it sleeps like the injected one (a start-up request may wait out a 429
    back-off); from ``fail_fast`` on it never sleeps: a request that would wait (a retry back-off, a rate-budget wait)
    fails at once and the caller tries again at its own cadence, so no REST call blocks the loop (R2.AC2).

    Timeouts (R2b.AC3, RISK-75): from ``fail_fast`` on no request waits longer than ``TRADING_CALL_TIMEOUT_S``, and the
    thread that calls ``new_iteration`` (the trading thread) may spend ``LOOP_REST_BUDGET_S`` of request time per
    iteration in all: a hanging exchange costs one iteration that much, never the sum of its calls under ``gate_lock``.
    A request that finds the budget spent raises ``HlBudgetError`` (``wait_s=0``) without being sent."""

    def __init__(self, patient: Sleeper, *, monotonic: Callable[[], float] = _real_monotonic) -> None:
        self._patient = patient
        self._mono = monotonic
        self._fail_fast = False
        self._owner: int | None = None
        self._spent_s = 0.0
        self._call_started = 0.0

    def fail_fast(self) -> None:
        self._fail_fast = True

    def new_iteration(self) -> None:
        """The calling thread's REST time starts again from ``LOOP_REST_BUDGET_S``."""
        self._owner = threading.get_ident()
        self._spent_s = 0.0

    def timeout_s(self, configured_s: float) -> float:
        if not self._fail_fast:
            return configured_s
        timeout = min(configured_s, TRADING_CALL_TIMEOUT_S)
        if threading.get_ident() != self._owner:
            return timeout
        remaining = LOOP_REST_BUDGET_S - self._spent_s
        if remaining < MIN_CALL_S:
            raise HlBudgetError("the REST time of this loop iteration is spent", wait_s=0.0)
        self._call_started = self._mono()
        return min(timeout, remaining)

    def finished(self) -> None:
        if self._fail_fast and threading.get_ident() == self._owner:
            self._spent_s += max(0.0, self._mono() - self._call_started)

    def sleep(self, seconds: float) -> None:
        if self._fail_fast:
            raise HlBudgetError(
                f"the rate budget has no room for this request now (would wait {seconds:.1f} s)", wait_s=seconds
            )
        self._patient.sleep(seconds)
