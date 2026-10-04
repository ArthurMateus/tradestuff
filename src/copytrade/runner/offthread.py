"""Blocking network calls off the trading thread (R2c.AC2).

The leaderboard download (up to 3 x ``hl.rest_timeout_s``) and the WebSocket connects (``hl.ws_connect_timeout_s`` each,
DNS included) are not REST calls under the per-iteration budget: run on the trading thread they hold one loop iteration
for tens of seconds with a protected position unattended. ``OffThread`` runs such a call on a worker thread, ONE AT A
TIME, and hands the outcome over through a slot the loop polls:

* the poll that STARTS a call waits at most ``START_WAIT_S`` of real time, so a healthy peer answers within the same
  iteration; every later poll of a call still running returns at once (a hung call costs the loop nothing);
* an outcome (value or exception) waits in the slot until a poll takes it, and the exception is re-raised on the
  trading thread by ``Settled.unwrap`` exactly as the synchronous call would have raised it;
* a call that hangs is bounded by its own deadline (the HTTP / connect timeout), so at most one thread exists per
  ``OffThread`` and a hung peer never stacks threads;
* ``close`` abandons the call: a late value goes to ``discard`` (a connection is closed, never leaked), and ``join``
  waits (bounded) for the worker so nothing outlives the stop.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from copytrade.hl.ws import ConnectPendingError, WsConnection, WsConnector

START_WAIT_S = 0.25  # the most a poll that starts a call waits for it (real time)

_log = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class Settled(Generic[T]):
    """The outcome of one off-thread call: ``value`` or the ``error`` it raised."""

    value: T | None
    error: Exception | None

    def unwrap(self) -> T:
        """The value, or re-raise the call's exception on the calling thread."""
        if self.error is not None:
            raise self.error
        return self.value  # type: ignore[return-value]  # value is set whenever error is not


class OffThread(Generic[T]):
    """Runs ``work`` on a worker thread, one call in flight, and hands the ``Settled`` outcome to ``poll``."""

    def __init__(
        self,
        work: Callable[[], T],
        *,
        name: str,
        discard: Callable[[T], None] | None = None,
        start_wait_s: float = START_WAIT_S,
    ) -> None:
        self._work = work
        self._name = name
        self._discard = discard
        self._start_wait_s = start_wait_s
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._finished: threading.Event | None = None  # set when the running call has stored its outcome
        self._slot: Settled[T] | None = None
        self._closed = False

    def poll(self) -> Settled[T] | None:
        """Take the outcome of the finished call, else start a call (when none is running) and wait a bounded time for
        it, else ``None`` (the call is still running: poll again later). Never starts a call after ``close``."""
        with self._lock:
            if self._closed:
                return None
            if self._slot is not None:
                return self._take_slot()
            finished = self._finished
            if finished is not None and not finished.is_set():
                return None  # still running: no wait, no second thread
            finished = self._finished = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(finished,), name=f"r0-{self._name}", daemon=True)
            self._thread.start()
        finished.wait(self._start_wait_s)
        with self._lock:
            return self._take_slot()

    def _take_slot(self) -> Settled[T] | None:
        settled, self._slot = self._slot, None
        return settled

    def _run(self, finished: threading.Event) -> None:
        value: T | None = None
        error: Exception | None = None
        try:
            value = self._work()
        except Exception as exc:
            error = exc
        with self._lock:
            if self._closed:
                if error is not None:
                    _log.warning(
                        "an abandoned off-thread call failed",
                        extra={
                            "event": "offthread_abandoned_failed",
                            "call": self._name,
                            "error_type": type(error).__name__,
                        },
                    )
                elif value is not None and self._discard is not None:
                    self._discard_quietly(value)
            else:
                self._slot = Settled(value, error)
        finished.set()

    def _discard_quietly(self, value: T) -> None:
        assert self._discard is not None  # noqa: S101 - narrowed by the caller
        try:
            self._discard(value)
        except Exception:
            _log.exception("discarding an abandoned result failed", extra={"event": "offthread_discard_failed"})

    def close(self) -> None:
        """Abandon the call: no new call starts and an outcome not yet taken is discarded."""
        with self._lock:
            self._closed = True
            settled = self._take_slot()
        if settled is not None and settled.value is not None and self._discard is not None:
            self._discard_quietly(settled.value)

    def join(self, deadline: float) -> None:
        """Wait for the worker until ``deadline`` (``time.monotonic()``) so none runs on after the stop."""
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))


class BackgroundLeaderboard:
    """``recorder.ports.LeaderboardSource`` whose GET runs off the trading thread. ``fetch`` has the synchronous
    contract (bytes, or the ``OSError`` / ``TimeoutError`` of the GET) but never waits more than ``START_WAIT_S``: when
    the GET is still running it raises ``TimeoutError`` and the next call takes the outcome. The follow cycle asks
    ``poll`` first and runs only once an outcome is waiting (``ready``), so a slow download defers the cycle instead of
    reporting an outage; a download that really fails (its own deadline) is an outcome like any other."""

    def __init__(self, source: Callable[[], bytes], *, name: str) -> None:
        self._call: OffThread[bytes] = OffThread(source, name=name)
        self._settled: Settled[bytes] | None = None

    def ready(self) -> bool:
        """Start the download when none runs, and say whether an outcome (bytes or failure) is waiting for ``fetch``."""
        if self._settled is None:
            self._settled = self._call.poll()
        return self._settled is not None

    def fetch(self) -> bytes:
        if not self.ready():
            raise TimeoutError("the leaderboard download is still running")
        settled, self._settled = self._settled, None
        assert settled is not None  # noqa: S101 - ready() was true
        return settled.unwrap()

    def close(self) -> None:
        self._call.close()

    def join(self, deadline: float) -> None:
        self._call.join(deadline)


class BackgroundConnector:
    """``WsConnector`` whose ``connect`` runs off the trading thread. It returns the open connection when the attempt
    finished, raises the attempt's own exception (``OSError`` on a failed connect) when it failed, and raises
    ``ConnectPendingError`` while the attempt is still running: the caller tries again on its next tick, with nothing
    counted as a failure. One attempt at a time, each bounded by the connector's own connect timeout."""

    def __init__(self, connector: WsConnector, *, name: str) -> None:
        self._call: OffThread[WsConnection] = OffThread(connector.connect, name=name, discard=_close_connection)

    def connect(self) -> WsConnection:
        settled = self._call.poll()
        if settled is None:
            raise ConnectPendingError("a websocket connect is running in the background")
        return settled.unwrap()

    def close(self) -> None:
        self._call.close()

    def join(self, deadline: float) -> None:
        self._call.join(deadline)


def _close_connection(connection: WsConnection) -> None:
    try:
        connection.close()
    except OSError as exc:
        _log.debug(
            "closing an abandoned websocket failed",
            extra={"event": "ws_close_failed", "error_type": type(exc).__name__},
        )
