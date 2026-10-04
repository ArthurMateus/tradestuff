"""R5 round-1 pins (docs/sdlc/copytrade-v1/05-test-plan-R5.md): tests that kill the real surviving mutants of
``selection/backfill.py`` found by the senior developer's hand-mutation round.

- (a) a UTC hour rolls over in the middle of a coin's candle fetch;
- (b1)/(b2) the consecutive-timeout counter counts only timeouts of the SAME call in a row;
- (c) the stall cooldown is part of the wallet's own cooldown (the "next retry" of the progress line);
- (SD3) advisory: after the cooldown of M timeouts the counter starts again at zero.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

import pytest

from tests.hl.support import T0, Call, status
from tests.selection.helpers import w
from tests.selection.r5_world import HOUR, R5World, expected_opens, make_r5

A = w(1)
STALL = "kept timing out"
PROGRESS = re.compile(r"cooling=(\d+), next retry in (\d+) s")


class Script:
    """A server rule: the first requests it sees fail as listed ("timeout" or "500"), the rest fall through."""

    def __init__(self, *outcomes: str) -> None:
        self.left = list(outcomes)

    def __call__(self, call: Call) -> Any:
        if not self.left:
            return None
        how = self.left.pop(0)
        if how == "timeout":
            raise TimeoutError("the server did not answer")
        return status(500)


def stall_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING and STALL in r.getMessage()]


def to_seconds_before_next_hour(r: R5World, seconds: int) -> int:
    """Move the fake time to ``seconds`` before a UTC hour boundary; returns the boundary (epoch ms)."""
    boundary = (r.clock.now_ms() // HOUR + 1) * HOUR
    r.world.tick((boundary - seconds * 1000 - r.clock.now_ms()) // 1000)
    return boundary


def chain_candles(r: R5World, first: Any) -> None:
    normal = r.world.hl.rules[("None", "candleSnapshot")]

    def rule(call: Call) -> Any:
        answer = first(call)
        return answer if answer is not None else normal(call)

    r.world.hl.rules[("None", "candleSnapshot")] = rule


# --- (a) hour rollover in the middle of a coin's candle fetch --------------------------------------------------------


def test_R5_r1_a_a_fetch_that_spans_an_hour_boundary_restarts_for_the_new_hour_and_ends_with_the_new_hours_bar() -> None:
    r = make_r5(latency=lambda c: 0.6 if c.body["type"] == "candleSnapshot" else 0.0)
    r.serve_wallet(A, ["BTC"])
    r.backfiller.set_candidates([A])
    boundary = to_seconds_before_next_hour(r, 15)
    crossed_at: int | None = None
    for _ in range(40):
        if crossed_at is None and r.clock.now_ms() >= boundary:
            crossed_at = len(r.http.candle_windows("BTC"))  # the requests of the iterations before the rollover
        r.iteration()
        if r.backfiller.inputs(A, T0) is not None:
            break
        r.world.tick(10)
    inputs = r.backfiller.inputs(A, T0)
    assert inputs is not None
    assert crossed_at is not None
    windows = r.http.candle_windows("BTC")
    before_roll, after_roll = windows[:crossed_at], windows[crossed_at:]
    assert before_roll and after_roll, "the fetch did not span the hour boundary: the test setup is off"
    # the new hour's fetch asks for the new window, up to a time in the new hour ...
    assert after_roll[-1][2] >= boundary, f"no request after the rollover reaches the new hour: {after_roll}"
    # ... and re-asks the last bar held (it may have been partial) instead of going on after the old chunk
    assert after_roll[0][1] <= before_roll[-1][2], "the new hour's fetch continued after the old chunk, not at its bars"
    opens = [b.open_ms for b in inputs.candles_1h["BTC"]]
    assert opens[-1] == boundary, "the bars end with the old hour's bar: the new hour was never fetched"
    assert opens == list(range(opens[0], boundary + 1, HOUR)), "a gap or a duplicate in the bars"
    assert len(opens) >= len(expected_opens(boundary)) - 1  # the whole window, to the hour


# --- (b1) timeouts of different calls are not consecutive timeouts of one call ---------------------------------------


def test_R5_r1_b1_timeouts_of_different_calls_in_a_row_do_not_cool_the_wallet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """M - 1 timeouts of the first candle chunk of the old hour, the hour rolls over (the chunk is asked with another
    window: another call) and one more timeout: M timeouts in a row, but of two calls. No cooldown, no warning."""
    r = make_r5()
    m = r.world.cfg["hl.retry_max"] + 1
    r.serve_wallet(A, ["BTC"])
    chain_candles(r, Script(*["timeout"] * m))
    r.backfiller.set_candidates([A])
    to_seconds_before_next_hour(r, 20 * (m - 1) - 10)  # the first M - 1 attempts before it, the M-th after it
    with caplog.at_level(logging.INFO):
        for _ in range(m):
            r.iteration()
            r.world.tick(20)
        assert len(r.http.candle_windows("BTC", outcome="error")) == m
        windows = r.http.candle_windows("BTC", outcome="error")
        assert len(set(windows)) == 2, "the setup did not make two different calls time out"
        r.run([A], max_steps=40, tick_s=20)
        assert not stall_warnings(caplog), "M timeouts of different calls were taken for one call that keeps timing out"


# --- (b2) a different outcome of the call resets the counter ---------------------------------------------------------


def test_R5_r1_b2_an_http_error_between_timeouts_of_a_call_restarts_the_count(caplog: pytest.LogCaptureFixture) -> None:
    """The portfolio times out M - 1 times, answers with a 500 (an error that is not a timeout), then times out once:
    the count restarted at the 500, so there is no cooldown."""
    r = make_r5()
    m = r.world.cfg["hl.retry_max"] + 1
    r.serve_wallet(A, ["BTC"])
    r.world.hl.rules[(A, "portfolio")] = Script(*["timeout"] * (m - 1), "500", "timeout")
    r.backfiller.set_candidates([A])
    with caplog.at_level(logging.INFO):
        for _ in range(m + 1):
            r.iteration()
            r.world.tick(70)  # past the error backoff of the wallet
        assert len(r.http.of("portfolio", A)) == m + 1
        r.run([A], max_steps=20, tick_s=70)
        assert not stall_warnings(caplog)


def test_R5_r1_b2_m_timeouts_of_the_same_call_in_a_row_still_cool_the_wallet(caplog: pytest.LogCaptureFixture) -> None:
    """Guard of the two tests above: the same script without the 500 cools the wallet at the M-th timeout."""
    r = make_r5()
    m = r.world.cfg["hl.retry_max"] + 1
    r.serve_wallet(A, ["BTC"])
    r.world.hl.rules[(A, "portfolio")] = Script(*["timeout"] * m)
    r.backfiller.set_candidates([A])
    with caplog.at_level(logging.INFO):
        for _ in range(m):
            r.iteration()
            r.world.tick(70)
        assert len(stall_warnings(caplog)) == 1


# --- (c) the stall cooldown feeds the wallet's own cooldown ----------------------------------------------------------


def test_R5_r1_c_the_progress_line_waits_for_the_end_of_the_stall_cooldown(caplog: pytest.LogCaptureFixture) -> None:
    """Every iteration is 70 s apart (past the error backoff, a progress line each); the M-th timeout starts the stall
    cooldown of ``hl.backoff_max_s``. The next line, 60 s later, is inside it: the wallet is cooling down and the
    pass retries when the cooldown ends."""
    r = make_r5(latency=lambda c: 3.0 if c.body["type"] == "candleSnapshot" else 0.0)
    m = r.world.cfg["hl.retry_max"] + 1
    r.serve_wallet(A, ["BTC"])
    r.backfiller.set_candidates([A])
    with caplog.at_level(logging.INFO):
        for _ in range(m - 1):
            r.iteration()
            r.world.tick(70)
        started = r.clock.now_ms()  # the M-th timeout is in this iteration, which also writes a progress line
        r.iteration()
        (stall,) = stall_warnings(caplog)
        until = stall.cooldown_until_ms  # type: ignore[attr-defined]
        caplog.clear()
        r.world.tick((started + 60_000 - r.clock.now_ms()) // 1000)  # a progress line is due again, inside the cooldown
        now = r.clock.now_ms()
        assert now < until, "the setup is off: the cooldown is already over"
        r.iteration()
        lines = [PROGRESS.search(rec.getMessage()) for rec in caplog.records if "backfill progress" in rec.getMessage()]
        found = [x for x in lines if x is not None]
        assert found, "no progress line"
        cooling, retry_s = int(found[0].group(1)), int(found[0].group(2))
        assert cooling == 1
        assert retry_s == math.ceil((until - now) / 1000)


# --- SD3 (advisory) --------------------------------------------------------------------------------------------------


def test_R5_r1_SD3_after_a_cooldown_one_more_timeout_does_not_cool_the_wallet_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ADVISORY (R5-SD3): after the M-th timeout and its cooldown the count starts at zero, so one further timeout of
    the call is one timeout, not the (M+1)-th."""
    r = make_r5()
    m = r.world.cfg["hl.retry_max"] + 1
    r.serve_wallet(A, ["BTC"])
    r.world.hl.rules[(A, "portfolio")] = Script(*["timeout"] * (m + 1))
    r.backfiller.set_candidates([A])
    with caplog.at_level(logging.INFO):
        for _ in range(m):
            r.iteration()
            r.world.tick(70)
        assert len(stall_warnings(caplog)) == 1
        r.world.tick(70)  # the cooldown is over
        r.iteration()  # one more timeout
        assert len(r.http.of("portfolio", A, outcome="error")) == m + 1
        assert len(stall_warnings(caplog)) == 1, "one timeout after the cooldown cooled the wallet again"
