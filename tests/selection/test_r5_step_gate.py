"""R5.AC3 [integration]: a step does not use the whole REST time of its iteration (the rest is for the loop's own calls),
and an iteration whose REST time is already spent is no failure of the wallet (no warning, no cooldown)."""

from __future__ import annotations

import logging

import pytest

from tests.selection.helpers import w
from tests.selection.r5_world import make_r5

A = w(1)
LEFT_FOR_THE_LOOP_S = 0.5  # of the 2.0 s iteration, with half-second answers


def test_R5_AC3_a_step_leaves_part_of_the_iterations_rest_time_unused() -> None:
    r = make_r5(latency=0.5)
    r.serve_wallet(A, ["BTC", "ETH"])
    r.backfiller.set_candidates([A])
    _steps, times = r.run([A], max_steps=27)
    assert all(t <= 2.0 - LEFT_FOR_THE_LOOP_S for t in times), f"a step used {max(times):.2f} s of the 2.0 s"


def test_R5_AC3_an_iteration_with_no_rest_time_left_is_no_failure_and_starts_no_cooldown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r = make_r5(latency=0.5)
    r.serve_wallet(A, ["BTC"])
    r.backfiller.set_candidates([A])
    with caplog.at_level(logging.INFO):
        r.iteration(spent_s=2.0)
        asked = len(r.http.calls)
        r.iteration()  # the clock has not moved: a cooldown would keep the wallet waiting
    assert asked == 0
    assert len(r.http.calls) > 0
    assert not [rec for rec in caplog.records if rec.levelno >= logging.WARNING]
