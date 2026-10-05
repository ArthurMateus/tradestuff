"""R5.AC1 and R5.AC2 [integration]: a wallet's backfill is resumable PER CALL, and candles come in small chunks.

AC1: the results of portfolio, clearinghouseState, userRole and each candle chunk (and the fills page) are kept across
steps and failures; a retry never re-requests a call that already succeeded. Observed over the HTTP boundary: requests
per type in the fake server (``LatencyHttp.outcomes``).

AC2: candles are fetched in chunks of at most 30 days (721 bars) so one request is small (derived: a 180-day request is
4 321 bars, hundreds of KB, from Brazil 0.3-1 s; one 30-day chunk is a sixth of it); each chunk is kept, a failed chunk
resumes at that chunk, and candles stay cached per coin per UTC hour across wallets.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from tests.hl.support import T0, Call, status
from tests.selection.helpers import w
from tests.selection.r5_world import HOUR, R5World, expected_opens, make_r5

MAX_CHUNK_BARS = 721  # 30 days of 1h bars plus the bar the closed range includes
A, B = w(1), w(2)


class FailTimes:
    """A server rule: the first ``n`` requests it sees fail (``how``), the rest fall through to the normal answer."""

    def __init__(self, n: int, how: str = "status") -> None:
        self.left, self.how, self.seen = n, how, 0

    def __call__(self, call: Call) -> Any:
        self.seen += 1
        if self.left > 0:
            self.left -= 1
            if self.how == "timeout":
                raise TimeoutError("the server did not answer")
            return status(500)
        return None


def candle_requests_per_window(r: R5World) -> Counter[tuple[str, int, int]]:
    return Counter(r.http.candle_windows())


# --- AC1 -----------------------------------------------------------------------------------------------------------


def test_R5_AC1_a_failing_clearinghouse_does_not_repeat_the_fills_page_or_the_portfolio() -> None:
    r = make_r5()
    r.serve_wallet(A, ["BTC"])
    failing = FailTimes(2)
    r.world.hl.rules[(A, "clearinghouseState")] = failing
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=40)
    assert failing.seen >= 3  # it failed twice and was asked again until it answered
    assert len(r.http.of("portfolio", A)) == 1
    assert len(r.http.of("userFillsByTime", A)) == 1  # one page that is not full is the whole fetch
    assert len(r.http.of("userRole", A)) == 1
    assert len(r.http.of("clearinghouseState", A, outcome="ok")) == 1


def test_R5_AC1_a_failing_role_does_not_repeat_the_portfolio_or_the_clearinghouse_state() -> None:
    r = make_r5()
    r.serve_wallet(A, ["BTC"])
    failing = FailTimes(2)
    r.world.hl.rules[(A, "userRole")] = failing
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=40)
    assert failing.seen >= 3
    assert len(r.http.of("portfolio", A)) == 1
    assert len(r.http.of("clearinghouseState", A)) == 1
    assert len(r.http.of("userFillsByTime", A)) == 1


def test_R5_AC1_a_candle_chunk_that_times_out_does_not_repeat_any_other_call_of_the_wallet() -> None:
    r = make_r5()
    r.serve_wallet(A, ["BTC", "ETH"])
    failing = FailTimes(1, "timeout")
    r.world.hl.rules[("None", "candleSnapshot")] = _chain(failing, r.world.hl.rules[("None", "candleSnapshot")])
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=60)
    for rtype in ("portfolio", "clearinghouseState", "userRole", "userFillsByTime"):
        assert len(r.http.of(rtype, A)) == 1, f"{rtype} was requested again after it had succeeded"


def test_R5_AC1_no_call_that_succeeded_is_ever_requested_again_in_a_backfill_with_failures_everywhere() -> None:
    r = make_r5()
    r.serve_wallet(A, ["BTC", "ETH"])
    for rtype in ("portfolio", "clearinghouseState", "userRole"):
        r.world.hl.rules[(A, rtype)] = FailTimes(1)
    r.world.hl.rules[("None", "candleSnapshot")] = _chain(
        FailTimes(2, "timeout"), r.world.hl.rules[("None", "candleSnapshot")]
    )
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=80)
    done: Counter[tuple[str, str]] = Counter()
    for call, result in r.http.outcomes:
        if result == "ok":
            body = call.body
            key = (body["type"], str(body.get("user") or body.get("req")))
            done[key] += 1
    again = {key: n for key, n in done.items() if n > 1}
    assert not again, f"calls answered more than once: {again}"


# --- AC2 -----------------------------------------------------------------------------------------------------------


def test_R5_AC2_every_candle_request_asks_for_at_most_thirty_days() -> None:
    r = make_r5()
    r.serve_wallet(A, ["BTC", "ETH"])
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=40)
    windows = r.http.candle_windows()
    assert windows
    too_big = [
        (coin, (end - start + 1) // HOUR) for coin, start, end in windows if end - start + 1 > MAX_CHUNK_BARS * HOUR
    ]
    assert not too_big, f"candle requests of more than {MAX_CHUNK_BARS} bars: {too_big}"


def test_R5_AC2_the_chunks_of_a_coin_cover_the_whole_window_and_the_bars_are_complete_and_unique() -> None:
    r = make_r5()
    r.serve_wallet(A, ["BTC"])
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=40)
    windows = sorted(r.http.candle_windows("BTC"), key=lambda win: win[1])
    assert len(windows) >= 6  # 180 days in chunks of at most 30
    for (_c, _s1, e1), (_c2, s2, _e2) in zip(windows, windows[1:], strict=False):
        assert s2 <= e1 + 1, "a gap between two chunks"
    inputs = r.backfiller.inputs(A, T0)
    assert inputs is not None
    assert [b.open_ms for b in inputs.candles_1h["BTC"]] == expected_opens(T0)


def test_R5_AC2_a_chunk_that_fails_is_asked_again_and_the_chunks_before_it_are_kept() -> None:
    r = make_r5()
    r.serve_wallet(A, ["BTC"])
    failing = FailTimes(0, "timeout")  # armed below: the THIRD candle request fails once
    normal = r.world.hl.rules[("None", "candleSnapshot")]
    seen = {"n": 0}

    def rule(call: Call) -> Any:
        seen["n"] += 1
        if seen["n"] == 3:
            failing.seen += 1
            raise TimeoutError("the server did not answer")
        return normal(call)

    r.world.hl.rules[("None", "candleSnapshot")] = rule
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=60)
    assert failing.seen == 1
    per_window = candle_requests_per_window(r)
    asked_twice = [win for win, n in per_window.items() if n > 1]
    assert len(asked_twice) == 1, f"exactly the failed chunk is asked again, got {asked_twice}"
    third = r.http.candle_windows("BTC")[2]
    assert asked_twice[0] == third
    assert per_window[third] == 2
    assert all(n == 1 for win, n in per_window.items() if win != third)
    inputs = r.backfiller.inputs(A, T0)
    assert inputs is not None
    assert [b.open_ms for b in inputs.candles_1h["BTC"]] == expected_opens(T0)


def test_R5_AC2_two_wallets_with_the_same_coins_share_the_candles_of_the_hour() -> None:
    r = make_r5()
    r.serve_wallet(A, ["BTC", "ETH"])
    r.serve_wallet(B, ["BTC", "ETH"])
    r.backfiller.set_candidates([A, B])
    r.run([A, B], max_steps=80)
    per_window = candle_requests_per_window(r)
    assert per_window
    assert max(per_window.values()) == 1, "a chunk of a coin was requested for the second wallet again"
    assert {c for c, _s, _e in per_window} == {"BTC", "ETH"}


def test_R5_AC2_the_next_hour_asks_only_for_the_bars_after_the_last_one_held_in_one_small_request() -> None:
    r = make_r5()
    r.serve_wallet(A, ["BTC"])
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=40)
    before = len(r.http.candle_windows("BTC"))
    last_open = expected_opens(T0)[-1]
    r.world.tick((HOUR - T0 % HOUR) // 1000 + 1)  # the next UTC hour
    r.limit.new_iteration()
    r.backfiller.refresh(A)
    new = r.http.candle_windows("BTC")[before:]
    assert len(new) == 1
    _coin, start, end = new[0]
    assert start >= last_open and end - start + 1 <= MAX_CHUNK_BARS * HOUR


def _chain(first: Any, then: Any) -> Any:
    """A server rule: ``first`` may refuse the request (raise or answer); when it falls through, ``then`` answers."""

    def rule(call: Call) -> Any:
        answer = first(call)
        return answer if answer is not None else then(call)

    return rule
