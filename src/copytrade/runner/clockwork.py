"""Clock estimates off the trading thread (R2.AC2, RISK-67).

An offset estimate is a retrying ``l2Book`` request: under 429 it sleeps through its back-off for up to a minute and a
hanging connection holds it for its whole timeout, and the clock is in doubt exactly when the exchange answers 429. The
estimates are therefore taken on a short-lived worker thread (one at a time); the trading thread starts one and waits
at most ``ANSWER_WAIT_S`` of real time for it, so a healthy exchange still answers within the same iteration and a
slow or refusing one costs the loop a bounded fraction of a second instead of the back-off. The estimate that arrives
later is used by the next iteration (``ClockSync`` publishes it atomically)."""

from __future__ import annotations

import logging
import threading

from copytrade.core.clock import ClockSync

ANSWER_WAIT_S = 0.25  # the most a loop iteration waits for an offset estimate (real time)

_log = logging.getLogger(__name__)


class BackgroundClock:
    """Takes ``ClockSync`` estimates on a worker thread. ``tick`` replaces ``ClockSync.tick`` in the loop and the
    instance is the time base's ``resample`` hook (``__call__``: ``True`` when a fresh estimate was taken since the
    last call)."""

    def __init__(self, sync: ClockSync, *, answer_wait_s: float = ANSWER_WAIT_S) -> None:
        self._sync = sync
        self._answer_wait_s = answer_wait_s
        self._lock = threading.Lock()
        self._running: threading.Event | None = None  # set when the running estimate has finished
        self._fresh = False  # an estimate was taken and not yet reported through ``__call__``

    def tick(self) -> None:
        """Start the periodic estimate when due (waiting a bounded time for it) and update the unsynced state and its
        alert."""
        if self._sync.estimate_due():
            self._start_and_wait()
        self._sync.check()

    def __call__(self) -> bool:
        """The forced resample of a clock in doubt: start an estimate (unless one is already running), wait a bounded
        time for it, and report whether a fresh one has been taken since the last call."""
        self._start_and_wait()
        with self._lock:
            fresh, self._fresh = self._fresh, False
        return fresh

    def _start_and_wait(self) -> None:
        with self._lock:
            finished = self._running
            if finished is None or finished.is_set():
                finished = self._running = threading.Event()
                threading.Thread(target=self._work, args=(finished,), name="r0-clock-estimate", daemon=True).start()
        finished.wait(self._answer_wait_s)

    def _work(self, finished: threading.Event) -> None:
        taken = False
        try:
            taken = self._sync.resample()
        except Exception:
            _log.exception("a clock estimate failed", extra={"event": "clock_estimate_thread_failed"})
        finally:
            with self._lock:
                self._fresh = self._fresh or taken  # published BEFORE the waiter is released
            finished.set()
