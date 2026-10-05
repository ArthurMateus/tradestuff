"""R4.AC3 [integration]: a candle failure that reaches the backfill as ``HlBudgetError`` raised from the retry sleep.

The fail-fast scoring client replaces the HTTP error it was about to retry with ``HlBudgetError``; the status is then only
on the exception's ``__context__``. The coin is still cached as failing with that status in the log, and that error
must not become the global (all wallets) cooldown.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import pytest

from copytrade.hl.errors import HlBudgetError, HlHttpError
from tests.hl.support import T0
from tests.selection.helpers import w
from tests.selection.r1_world import World, make_world
from tests.selection.r3_world import Tids, good_trips
from tests.selection.r4_world import WINDOW, drive

BAD = "kBONK"
A, B = w(1), w(2)


def chained(status: int) -> HlBudgetError:
    try:
        try:
            raise HlHttpError(f"candleSnapshot: HTTP {status}", status=status)
        except HlHttpError:
            raise HlBudgetError("the rate budget has no room for this request now (would wait 5.0 s)") from None
    except HlBudgetError as exc:
        return exc


def build(error: Exception) -> tuple[World, list[str]]:
    world = make_world(fail_fast=True)
    asked: list[str] = []
    real = world.candles.fetch

    def fetch(coin: str, interval: str, start_ms: int, end_ms: int) -> Sequence[Any]:
        asked.append(coin)
        if coin == BAD:
            raise error
        return real(coin, interval, start_ms, end_ms)

    world.candles.fetch = fetch  # type: ignore[method-assign]
    for wallet in (A, B):
        tids = Tids()
        world.hl.set_fills(wallet, good_trips(T0, 20, tids=tids) + good_trips(T0, 6, tids=tids, coin=BAD))
    world.backfiller.set_candidates([A, B])
    return world, asked


@pytest.mark.parametrize("status", [500, 503, 404])
def test_R4_AC3_the_status_behind_a_budget_error_is_logged_and_the_coin_cached(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    world, asked = build(chained(status))
    with caplog.at_level(logging.INFO):
        steps = drive(world, max_steps=6)
    assert steps <= 6  # no global cooldown: both wallets complete within a few slices, without waiting minutes
    assert asked.count(BAD) == 1  # two wallets, one request
    lines = [r.getMessage() for r in caplog.records if f"coin={BAD}" in r.getMessage()]
    assert len(lines) == 1
    match = WINDOW.search(lines[0])
    assert match is not None and int(match.group(4)) == status
    for wallet in (A, B):
        inputs = world.backfiller.inputs(wallet, T0)
        assert inputs is not None and not inputs.candles_1h.get(BAD) and inputs.candles_1h["BTC"]


def test_R4_AC3_a_budget_error_without_a_status_is_not_a_coin_failure() -> None:
    error = HlBudgetError("the rate budget has no room for this request now (would wait 5.0 s)")
    world, asked = build(error)
    world.backfiller.step()
    assert world.backfiller.inputs(A, T0) is None  # the wallet waits and is retried later, as before
    assert not world.backfiller.complete


def test_R4_AC3_a_rate_limit_behind_a_budget_error_is_not_a_coin_failure(caplog: pytest.LogCaptureFixture) -> None:
    world, asked = build(chained(429))
    with caplog.at_level(logging.INFO):
        world.backfiller.step()
    assert world.backfiller.inputs(A, T0) is None
    assert not [r for r in caplog.records if f"coin={BAD}" in r.getMessage()]
