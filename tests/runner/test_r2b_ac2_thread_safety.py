"""R2b.AC2 (RISK-74, blocking): the REST budget, the access monitor and the schema-failure monitor are shared by the trading
thread and the clock worker (``rest_clock``), so they must be safe under concurrent use: no exception ('deque mutated
during iteration', ``IndexError`` from a double ``popleft``), consistent counters, one alert per episode. And an unexpected
(non-``HlError``) exception inside the delisting check does not escape ``Runner.step`` (a ``_section``: logged, one
throttled alert, the loop and the stops go on).

The hammer tests run the real classes from several threads with a tiny interpreter switch interval so a missing lock shows
up reliably; the clock is a thread-safe fake (a counter), the alert sink a thread-safe list.
"""

from __future__ import annotations

import itertools
import sys
import threading
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest

from copytrade.core.events import Alert
from copytrade.hl.access import AccessMonitor
from copytrade.hl.budget import Priority, RateBudget
from copytrade.hl.schema import SchemaFailureMonitor
from tests.hl.support import RecordingLedger, make_config
from tests.runner.scenarios import count, opened_position, set_mid_below_stop
from tests.runner.world import World

C, S = Priority.CRITICAL, Priority.SCORING
THREADS = 4


class TickingClock:
    """A thread-safe fake clock that moves ``step_ms`` on every read (``itertools.count`` is atomic)."""

    def __init__(self, step_ms: int = 0, start_ms: int = 1_790_000_000_000) -> None:
        self._ticks = itertools.count()
        self._step = step_ms
        self._start = start_ms

    def now_ms(self) -> int:
        return self._start + next(self._ticks) * self._step


class SafeAlerts:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.sent: list[Alert] = []

    def send(self, alert: Alert) -> None:
        with self._lock:
            self.sent.append(alert)


@pytest.fixture(autouse=True)
def tiny_switch_interval() -> Iterator[None]:
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(old)


def hammer(workers: list[Callable[[], None]]) -> list[BaseException]:
    """Run every worker on its own thread, released together; return what escaped."""
    errors: list[BaseException] = []
    start = threading.Barrier(len(workers))

    def run(work: Callable[[], None]) -> None:
        try:
            start.wait()
            work()
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever escaped
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(w,), name=f"r2b-hammer-{i}") for i, w in enumerate(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
        assert not t.is_alive(), "a hammer thread hung"
    return errors


# ------------------------------------------------------------------------------------------------------ RateBudget


def test_R2b_AC2_rate_budget_wait_ms_while_another_thread_records_weight_raises_nothing() -> None:
    budget = RateBudget(budget_per_min=100, scoring_share=Decimal("0.5"), clock=TickingClock(0))
    budget.charge(100, C)  # full: wait_ms has to walk the window while the writers grow it

    def reader() -> None:
        for _ in range(3_000):
            budget.wait_ms(1, C)

    def writer() -> None:
        for _ in range(3_000):
            budget.charge(1, C)

    errors = hammer([reader, reader, writer, writer])
    assert not errors, f"concurrent use raised {errors[0]!r}"


def test_R2b_AC2_rate_budget_expiry_from_several_threads_raises_nothing_and_leaves_the_counters_exact() -> None:
    clock = TickingClock(step_ms=1)
    budget = RateBudget(budget_per_min=1_000_000, scoring_share=Decimal("0.5"), clock=clock)
    for i in range(30_000):  # a big window of entries, 1 ms apart ...
        budget.charge(1, S if i % 2 else C)
    clock._start += 60_000  # noqa: SLF001 - ... that all expires at once: every thread walks the same popleft loop

    def worker() -> None:
        for _ in range(50):
            budget.used()
            budget.scoring_used()

    errors = hammer([worker] * THREADS)
    assert not errors, f"concurrent use raised {errors[0]!r}"
    clock._start += 10_000_000  # noqa: SLF001
    assert budget.used() == 0, f"the total drifted to {budget.used()}"
    assert budget.scoring_used() == 0, f"the scoring total drifted to {budget.scoring_used()}"


def test_R2b_AC2_rate_budget_concurrent_acquires_never_exceed_the_limit_and_the_total_is_exact() -> None:
    budget = RateBudget(budget_per_min=1_000, scoring_share=Decimal("0.5"), clock=TickingClock(0))
    granted = [0] * THREADS

    def worker(index: int) -> Callable[[], None]:
        def run() -> None:
            for _ in range(1_000):
                if budget.try_acquire(1, C):
                    granted[index] += 1

        return run

    errors = hammer([worker(i) for i in range(THREADS)])
    assert not errors, f"concurrent use raised {errors[0]!r}"
    assert sum(granted) == 1_000, (
        f"{sum(granted)} granted against a budget of 1000 (a race over-granted or lost weight)"
    )
    assert budget.used() == 1_000


# ------------------------------------------------------------------------------------------------------ AccessMonitor


def _access(clock: TickingClock) -> tuple[AccessMonitor, SafeAlerts]:
    alerts = SafeAlerts()
    return AccessMonitor(config=make_config(), clock=clock, alerts=alerts, ledger=RecordingLedger()), alerts


def test_R2b_AC2_access_monitor_expiry_from_several_threads_raises_nothing_and_keeps_counts_consistent() -> None:
    clock = TickingClock(step_ms=1)
    monitor, _ = _access(clock)
    for _ in range(30_000):
        monitor.record_response(200)
    clock._start += 3_600_000  # noqa: SLF001 - the whole window expires at once, under every recording thread

    def recorder() -> None:
        for _ in range(200):
            monitor.record_response(200)

    def ticker() -> None:
        for _ in range(200):
            monitor.tick()

    errors = hammer([recorder, recorder, recorder, ticker])
    assert not errors, f"concurrent use raised {errors[0]!r}"
    assert not monitor.degraded, "a stream of HTTP 200s must never trip the monitor"
    assert monitor._successes == sum(1 for _, ok in monitor._outcomes if ok) == len(monitor._outcomes)  # noqa: SLF001


def test_R2b_AC2_access_monitor_trips_exactly_once_and_alerts_once_under_concurrent_errors() -> None:
    monitor, alerts = _access(TickingClock(0))

    def failing() -> None:
        for _ in range(500):
            monitor.record_response(403)
            monitor.tick()

    errors = hammer([failing] * THREADS)
    assert not errors, f"concurrent use raised {errors[0]!r}"
    assert monitor.degraded
    assert len([a for a in alerts.sent if a.kind == "access_degraded"]) == 1


# ------------------------------------------------------------------------------------------------ SchemaFailureMonitor


def test_R2b_AC2_schema_monitor_sends_one_alert_per_endpoint_episode_under_concurrent_failures() -> None:
    alerts = SafeAlerts()
    monitor = SchemaFailureMonitor(clock=TickingClock(0), alerts=alerts)
    endpoints = [f"endpoint{i}" for i in range(300)]

    def worker() -> None:
        for endpoint in endpoints:
            monitor.record_failure(endpoint)  # 4 threads x 1 = 4 failures per endpoint: one episode, one alert

    errors = hammer([worker] * THREADS)
    assert not errors, f"concurrent use raised {errors[0]!r}"
    assert len(alerts.sent) == len(endpoints), (
        f"{len(alerts.sent)} alerts for {len(endpoints)} endpoints (one episode each)"
    )


def test_R2b_AC2_schema_monitor_expiry_under_concurrent_failures_raises_nothing() -> None:
    monitor = SchemaFailureMonitor(clock=TickingClock(step_ms=700), alerts=SafeAlerts())

    def worker() -> None:
        for _ in range(4_000):
            monitor.record_failure("shared")

    errors = hammer([worker] * THREADS)
    assert not errors, f"concurrent use raised {errors[0]!r}"


# ------------------------------------------------------------------------------------------------------ the loop


def test_R2b_AC2_an_unexpected_exception_in_the_delisting_check_does_not_escape_step(new_world: Any) -> None:
    """The delisting check runs at the end of every iteration; a non-``HlError`` out of it (the race above surfaced as
    ``RuntimeError``) used to end the loop (``runner_crashed``) with positions unmanaged. Fault injected at the meta source."""
    world, runner = opened_position(new_world)

    def boom() -> frozenset[str]:
        raise RuntimeError("injected: deque mutated during iteration")

    runner._parts.meta.delisted = boom  # type: ignore[method-assign]  # noqa: SLF001
    set_mid_below_stop(world, runner)
    try:
        world.step(runner, 1, ms=3_700_000)  # past paper.meta_refresh_min (60 min): the check is due
        world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=60, ms=500)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"an unexpected exception in the delisting check escaped step(): {type(exc).__name__}: {exc}")
    assert runner.broker.position("SOL") is None, "the stop was not processed after the failing check"
    world.step(runner, 2, ms=3_700_000)  # due again (the failing call is retried later), and again it must not escape
    from tests.hl.ws_server import wait_for

    wait_for(lambda: count(world, "runner_section_failed") >= 1, what="a section_failed alert for the delisting check")
    assert count(world, "runner_section_failed") <= 3, "the alert is throttled, not one per failure"


def test_R2b_AC2_the_fixture_world_is_a_world(new_world: Any) -> None:
    """Guards the import of ``World`` (kept for the type of the helper above)."""
    assert isinstance(new_world(), World)
