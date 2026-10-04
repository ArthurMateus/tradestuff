"""R5.AC4 [integration]: a single call that cannot fit even a whole 2.0 s budget does not retry forever in silence.

A server that takes 3 s per candle chunk of BTC (the 2.0 s per-call cap cuts every attempt: ``no answer within 2 s``).
Derived constants, no new config key:
- M, the consecutive timeouts of the SAME call after which the wallet cools down: at most ``hl.retry_max + 1`` (the
  attempts a request gets in a sleeping client: the first and ``retry_max`` retries) and at least 2 (one timeout may be
  chance);
- the cooldown lasts ``hl.backoff_max_s`` (the existing cooldown of a persistent failure; ``R4.AC3`` uses it for a coin);
- the WARNING reads ``coin=<name> window=<start>..<end> status=<code or word>`` and names the call (candles), once per
  cooldown, like the R4.AC3 line of a failing coin.
Other wallets keep progressing, and every loop iteration stays under the 3 s bound.
"""

from __future__ import annotations

import logging
import re

import pytest

from tests.hl.support import Call
from tests.selection.helpers import w
from tests.selection.r5_world import R5World, make_r5

A, B = w(1), w(2)
LINE = re.compile(r"coin=(\S+) window=(\d+)\.\.(\d+) status=(\S+)")
LOOP_BOUND_S = 3.0


def slow_btc(call: Call) -> float:
    return 3.0 if call.body["type"] == "candleSnapshot" and call.body["req"]["coin"] == "BTC" else 0.0


def build() -> R5World:
    r = make_r5(latency=slow_btc)
    r.serve_wallet(A, ["BTC"])
    r.serve_wallet(B, ["ETH"])
    r.backfiller.set_candidates([A, B])
    return r


def lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        rec
        for rec in caplog.records
        if rec.levelno >= logging.WARNING
        and rec.name.startswith("copytrade.selection")
        and LINE.search(rec.getMessage())
    ]


def until_warned(r: R5World, caplog: pytest.LogCaptureFixture, *, max_steps: int = 60) -> tuple[int, list[float]]:
    times: list[float] = []
    for n in range(1, max_steps + 1):
        times.append(r.iteration())
        if lines(caplog):
            return n, times
        r.world.tick(10)
    raise AssertionError(f"no warning naming coin, window and status after {max_steps} iterations")


def test_R5_AC4_after_m_consecutive_timeouts_of_one_call_a_warning_names_coin_window_and_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r = build()
    with caplog.at_level(logging.INFO):
        until_warned(r, caplog)
        found = lines(caplog)
        message = found[0].getMessage()
        match = LINE.search(message)
        assert match is not None
        coin, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        assert coin == "BTC"
        assert "candle" in message.lower()
        assert (coin, start, end) in r.http.candle_windows("BTC")  # the window of a request that was really sent
        timeouts = len(r.http.candle_windows("BTC", outcome="timeout"))
        assert 2 <= timeouts <= r.world.cfg["hl.retry_max"] + 1, f"warned after {timeouts} consecutive timeouts"


def test_R5_AC4_the_wallet_then_cools_down_for_backoff_max_s_with_one_warning_per_cooldown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r = build()
    cooldown_ms = int(r.world.cfg["hl.backoff_max_s"] * 1000)
    with caplog.at_level(logging.INFO):
        until_warned(r, caplog)
        warned_at = r.clock.now_ms()
        asked = len(r.http.candle_windows("BTC"))
        while r.clock.now_ms() < warned_at + cooldown_ms - 10_000:
            r.world.tick(10)
            r.iteration()
        assert len(r.http.candle_windows("BTC")) == asked, "the call was asked again inside the cooldown"
        assert len(lines(caplog)) == 1, "one warning per cooldown, not one per attempt"
        while r.clock.now_ms() < warned_at + cooldown_ms + 5_000:
            r.world.tick(10)
            r.iteration()
        assert len(r.http.candle_windows("BTC")) > asked, "the call is never asked again after its cooldown"


def test_R5_AC4_other_wallets_progress_meanwhile_and_every_iteration_stays_bounded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r = build()
    with caplog.at_level(logging.INFO):
        _steps, times = until_warned(r, caplog)
    assert r.backfiller.inputs(B, 0) is not None, "the wallet without the unfittable call was starved"
    assert all(t < LOOP_BOUND_S for t in times), f"an iteration spent {max(times):.2f} s of REST time"


def test_R5_AC4_one_timeout_that_is_followed_by_an_answer_is_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Guard: a chunk that times out once and then answers is chance, not a call that cannot fit."""
    seen = {"n": 0}

    def once_slow(call: Call) -> float:
        if call.body["type"] == "candleSnapshot" and call.body["req"]["coin"] == "BTC":
            seen["n"] += 1
            return 3.0 if seen["n"] == 1 else 0.0
        return 0.0

    r = make_r5(latency=once_slow)
    r.serve_wallet(A, ["BTC"])
    r.backfiller.set_candidates([A])
    with caplog.at_level(logging.INFO):
        r.run([A], max_steps=40)
    assert not lines(caplog)
    assert len(r.http.candle_windows("BTC", outcome="timeout")) == 1
