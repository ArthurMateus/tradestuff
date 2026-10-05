"""R5.AC3 [integration]: each backfill step performs only the calls that fit the iteration's remaining REST time, so a
wallet converges in bounded steps even when only a part of the 2.0 s iteration budget is left.

Real wiring (``r5_world``): the real ``TradingSleeper`` is the scoring client's call limit (cap 2.0 s per call AND 2.0 s of
REST time per loop iteration, both unchanged: the R2b.AC3 / R2c.AC3 tests keep pinning them), the real fail-fast scoring
sleeper, the real backfiller. The server answers every request after 0.5 s.

Derivation of N. The wallet needs 1 fills page + portfolio + clearinghouseState + userRole + the candle chunks of its two
coins (6 or 7 chunks of at most 30 days each): at most 1 + 3 + 2 x 7 = 18 calls. Even a step that makes ONE call
(the worst the spec accepts: "at most one heavy call per step") finishes in 18 steps; N = 27 is that plus 50 %.
A step that repeats a call that already succeeded never finishes (the PO's live defect), so N is also the proof of AC1.
"""

from __future__ import annotations

import pytest

from copytrade.runner.failfast import LOOP_REST_BUDGET_S, TRADING_CALL_TIMEOUT_S
from tests.hl.support import Call
from tests.selection.helpers import w
from tests.selection.r5_world import make_r5

N = 27
LOOP_BOUND_S = 3.0  # the R2b.AC3 bound of one loop iteration
A = w(1)


def _heavy_candles(call: Call) -> float:
    return 0.9 if call.body["type"] == "candleSnapshot" else 0.2


@pytest.mark.parametrize("spent_s", [0.0, 1.0], ids=["whole_budget", "one_second_left"])
def test_R5_AC3_a_wallet_completes_in_bounded_steps_with_every_response_taking_half_a_second(spent_s: float) -> None:
    r = make_r5(latency=0.5)
    r.serve_wallet(A, ["BTC", "ETH"])
    r.backfiller.set_candidates([A])
    steps, times = r.run([A], max_steps=N, spent_s=spent_s)
    assert steps <= N
    assert all(t < LOOP_BOUND_S for t in times), f"a loop iteration spent {max(times):.2f} s of REST time"


@pytest.mark.parametrize("spent_s", [0.0, 1.0], ids=["whole_budget", "one_second_left"])
def test_R5_AC3_a_step_never_repeats_a_call_that_succeeded_so_the_requests_are_the_wallets_calls_once(
    spent_s: float,
) -> None:
    r = make_r5(latency=0.5)
    r.serve_wallet(A, ["BTC", "ETH"])
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=N, spent_s=spent_s)
    ok = r.http.count_ok()
    assert (ok["portfolio"], ok["clearinghouseState"], ok["userRole"], ok["userFillsByTime"]) == (1, 1, 1, 1)
    windows = r.http.candle_windows(outcome="ok")
    assert len(windows) == len(set(windows))


def test_R5_AC3_a_slow_candle_chunk_that_fits_the_budget_is_taken_in_the_same_step_as_the_light_calls() -> None:
    r = make_r5(latency=_heavy_candles)
    r.serve_wallet(A, ["BTC", "ETH"])
    r.backfiller.set_candidates([A])
    steps, times = r.run([A], max_steps=N)
    assert steps <= N
    assert all(t < LOOP_BOUND_S for t in times)


def test_R5_AC3_the_per_call_cap_and_the_iteration_budget_stay_as_they_are() -> None:
    r = make_r5(latency=0.5)
    r.serve_wallet(A, ["BTC", "ETH"])
    r.backfiller.set_candidates([A])
    _steps, times = r.run([A], max_steps=N)
    assert TRADING_CALL_TIMEOUT_S == 2.0 and LOOP_REST_BUDGET_S == 2.0
    assert all(c.timeout_s <= TRADING_CALL_TIMEOUT_S for c in r.http.calls)
    assert all(t <= LOOP_REST_BUDGET_S + 1e-6 for t in times), "an iteration used more REST time than its budget"


def test_R5_AC3_two_wallets_both_converge_while_sharing_the_iteration_budget() -> None:
    r = make_r5(latency=0.5)
    b = w(2)
    r.serve_wallet(A, ["BTC"])
    r.serve_wallet(b, ["ETH"])
    r.backfiller.set_candidates([A, b])
    steps, times = r.run([A, b], max_steps=2 * N)
    assert steps <= 2 * N
    assert all(t < LOOP_BOUND_S for t in times)
