"""R2c.AC3 (R2-V2-4): a PARTLY spent per-iteration REST budget, and the per-call cap, pinned one mutant at a time.

``TradingSleeper.timeout_s`` is ``min(min(configured, 2.0), remaining)``. Within a fresh iteration the two minimums give
the same answer (remaining starts at 2.0), so the R2b.AC3 tests mask each mutant with the other one. Distinguishing them:

* ``loopbudget`` (``min(timeout, remaining)`` removed): a partly spent budget (1.5 s gone) must cut a hanging call to the
  0.5 s that is left, and a spent one refuse it;
* ``restbound`` (``min(configured, 2.0)`` removed): a call must be capped at 2.0 s when ``hl.rest_timeout_s`` is 10 on a
  thread whose budget is not the iteration's (the Telegram / flatten threads: no budget, still 2.0 s per call), and on the
  trading thread with the first call of an iteration.

The real class over an injected monotonic clock and a recording sleeper (the only fakes: time).
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from copytrade.hl.errors import HlBudgetError
from copytrade.runner.failfast import LOOP_REST_BUDGET_S, TRADING_CALL_TIMEOUT_S, TradingSleeper


class _Mono:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _NoSleep:
    def sleep(self, seconds: float) -> None:
        raise AssertionError("a fail-fast sleeper never sleeps through the patient one")


def _sleeper() -> tuple[TradingSleeper, _Mono]:
    mono = _Mono()
    sleeper = TradingSleeper(_NoSleep(), monotonic=mono)  # type: ignore[arg-type]
    sleeper.fail_fast()
    sleeper.new_iteration()  # the calling (test) thread is the trading thread
    return sleeper, mono


def _call(sleeper: TradingSleeper, mono: _Mono, configured: float, took: float) -> float:
    """One request: the timeout it is given, then ``took`` seconds pass, then it is finished."""
    timeout = sleeper.timeout_s(configured)
    mono.now += took
    sleeper.finished()
    return timeout


def test_R2c_AC3_constants_are_the_two_second_cap_and_two_second_budget() -> None:
    assert TRADING_CALL_TIMEOUT_S == 2.0
    assert LOOP_REST_BUDGET_S == 2.0


def test_R2c_AC3_a_hanging_call_with_1_5_s_already_spent_may_block_at_most_the_remaining_half_second() -> None:
    sleeper, mono = _sleeper()
    _call(sleeper, mono, 10.0, 1.5)  # an earlier call of the iteration took 1.5 s
    timeout = sleeper.timeout_s(10.0)
    assert timeout == pytest.approx(0.5), f"a call got {timeout} s with 0.5 s of the iteration budget left"


@pytest.mark.parametrize("spent", [0.25, 1.0, 1.5, 1.9])
def test_R2c_AC3_the_timeout_never_exceeds_what_is_left_of_the_budget(spent: float) -> None:
    sleeper, mono = _sleeper()
    _call(sleeper, mono, 2.0, spent)
    assert sleeper.timeout_s(2.0) == pytest.approx(LOOP_REST_BUDGET_S - spent)


def test_R2c_AC3_a_spent_budget_refuses_the_next_call_without_sending_it() -> None:
    sleeper, mono = _sleeper()
    _call(sleeper, mono, 10.0, 2.0)
    with pytest.raises(HlBudgetError):
        sleeper.timeout_s(10.0)


def test_R2c_AC3_a_new_iteration_restores_the_whole_budget() -> None:
    sleeper, mono = _sleeper()
    _call(sleeper, mono, 10.0, 1.9)
    sleeper.new_iteration()
    assert sleeper.timeout_s(10.0) == pytest.approx(2.0)


def test_R2c_AC3_a_single_call_is_capped_at_2_s_when_rest_timeout_is_10_on_another_thread() -> None:
    """The Telegram / ``/flatten`` threads have no iteration budget: only the per-call cap bounds them."""
    sleeper, _ = _sleeper()
    seen: list[float] = []
    thread = threading.Thread(target=lambda: seen.append(sleeper.timeout_s(10.0)))
    thread.start()
    thread.join(timeout=5)
    assert seen == [2.0], f"a non-trading thread's call got {seen} s of a 10 s configured timeout"


@pytest.mark.parametrize("configured", [2.0, 5.0, 10.0, 30.0])
def test_R2c_AC3_no_thread_waits_longer_than_2_s_per_call_whatever_the_config(configured: float) -> None:
    sleeper, _ = _sleeper()
    seen: list[float] = []
    thread = threading.Thread(target=lambda: seen.append(sleeper.timeout_s(configured)))
    thread.start()
    thread.join(timeout=5)
    assert seen and seen[0] <= 2.0
    assert sleeper.timeout_s(configured) <= 2.0


def test_R2c_AC3_a_configured_timeout_below_the_cap_is_kept_on_another_thread() -> None:
    sleeper, _ = _sleeper()
    seen: list[Any] = []
    thread = threading.Thread(target=lambda: seen.append(sleeper.timeout_s(1.0)))
    thread.start()
    thread.join(timeout=5)
    assert seen == [1.0]


def test_R2c_AC3_before_fail_fast_start_up_requests_keep_the_configured_timeout() -> None:
    mono = _Mono()
    sleeper = TradingSleeper(_NoSleep(), monotonic=mono)  # type: ignore[arg-type]
    sleeper.new_iteration()
    assert sleeper.timeout_s(10.0) == 10.0
