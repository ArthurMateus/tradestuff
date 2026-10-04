"""R4.AC3 [integration]: a coin whose candles fail (HTTP 5xx or 4xx) costs the backfill nothing but that coin's bars.

- the failure is cached PER COIN, not per wallet, for ``hl.backoff_max_s`` (existing key): the coin is not requested
  again by any wallet inside the cooldown, and asked again (once, retries included) after it;
- the wallet's backfill still completes, with the coin's bars missing from ``candles_1h``;
- one log line per coin per cooldown, whose MESSAGE TEXT reads ``coin=<name> window=<start>..<end> status=<code>``
  (``start``/``end`` in ms, the requested window inside ``scoring.window_days`` before now);
- a failing coin never blocks or starves other wallets or the screening step.

Both client wirings are covered: ``fail_fast=False`` (the client sleeps between retries) and ``fail_fast=True`` (the
PO's scoring client: its retry sleep raises ``HlBudgetError``, the HTTP status is only the exception's context).

What scoring does with a coin without bars (existing code, NOT changed here): see the plan, section "Escalation".
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from tests.hl.support import T0
from tests.selection.helpers import w
from tests.selection.r1_world import DAY, World, make_world
from tests.selection.r3_world import Tids, good_trips, make_r3, ok_page, row, verdict
from tests.selection.r4_world import WINDOW, candle_calls, drive, install, r3_install

BAD = "kBONK"
A, B, C = w(1), w(2), w(3)
CASES = [(False, 500), (True, 500), (False, 503), (True, 503), (False, 404), (True, 404), (False, 400)]
IDS = [f"{'failfast' if ff else 'sleeping'}-{code}" for ff, code in CASES]


def build(fail_fast: bool, code: int, *, bad_wallets: tuple[str, ...] = (A, B, C), ok_wallets: tuple[str, ...] = ()) -> World:
    world = make_world(fail_fast=fail_fast)
    install(world, {BAD: code})
    for wallet in bad_wallets:
        tids = Tids()
        world.hl.set_fills(wallet, good_trips(T0, 20, tids=tids) + good_trips(T0, 6, tids=tids, coin=BAD))
    for wallet in ok_wallets:
        world.hl.set_fills(wallet, good_trips(T0, 20, tids=Tids()))
    world.backfiller.set_candidates([*bad_wallets, *ok_wallets])
    return world


def coin_lines(caplog: pytest.LogCaptureFixture, coin: str = BAD) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.name.startswith("copytrade.selection") and re.search(rf"coin={re.escape(coin)}\b", r.getMessage())
    ]


@pytest.mark.parametrize(("fail_fast", "code"), CASES, ids=IDS)
def test_R4_AC3_wallets_complete_with_the_failing_coins_bars_missing(fail_fast: bool, code: int) -> None:
    world = build(fail_fast, code)
    drive(world, max_steps=30)
    for wallet in (A, B, C):
        inputs = world.backfiller.inputs(wallet, T0)
        assert inputs is not None
        assert inputs.candles_1h["BTC"]
        assert not inputs.candles_1h.get(BAD)
        assert any(f.coin == BAD for f in inputs.fills)  # the fills are kept: only the bars are missing


@pytest.mark.parametrize(("fail_fast", "code"), CASES, ids=IDS)
def test_R4_AC3_the_failure_is_cached_per_coin_not_per_wallet(fail_fast: bool, code: int) -> None:
    world = build(fail_fast, code)
    drive(world, max_steps=30)
    one_attempt = world.cfg["hl.retry_max"] + 1  # a request and all its retries
    assert 1 <= len(candle_calls(world, BAD)) <= one_attempt  # three wallets, ONE failed request


@pytest.mark.parametrize(("fail_fast", "code"), CASES, ids=IDS)
def test_R4_AC3_the_coin_is_asked_again_only_after_backoff_max_s(fail_fast: bool, code: int) -> None:
    world = build(fail_fast, code)
    drive(world, max_steps=30)
    cooldown_ms = int(world.cfg["hl.backoff_max_s"] * 1000)
    seen = len(candle_calls(world, BAD))
    failed_at = candle_calls(world, BAD)[-1].t_ms
    inside, outside = failed_at + cooldown_ms - 10_000, failed_at + cooldown_ms + 5_000
    assert world.clock.now_ms() < inside
    world.clock.now = inside
    for wallet in (A, B, C):
        world.backfiller.refresh(wallet)  # must neither raise nor ask for the coin
    assert len(candle_calls(world, BAD)) == seen
    world.clock.now = outside
    for wallet in (A, B, C):
        world.backfiller.refresh(wallet)
    new = len(candle_calls(world, BAD)) - seen
    assert 1 <= new <= world.cfg["hl.retry_max"] + 1  # one attempt for the three wallets
    for wallet in (A, B, C):
        assert world.backfiller.inputs(wallet, outside) is not None


@pytest.mark.parametrize(("fail_fast", "code"), CASES, ids=IDS)
def test_R4_AC3_one_log_line_per_coin_per_cooldown_names_coin_window_and_status(
    fail_fast: bool, code: int, caplog: pytest.LogCaptureFixture
) -> None:
    world = build(fail_fast, code)
    with caplog.at_level(logging.INFO):
        drive(world, max_steps=30)
        lines = coin_lines(caplog)
        assert len(lines) == 1  # three wallets, one coin, one cooldown
        match = WINDOW.search(lines[0].getMessage())
        assert match is not None, lines[0].getMessage()
        coin, start, end, status = match.group(1), int(match.group(2)), int(match.group(3)), int(match.group(4))
        assert (coin, status) == (BAD, code)
        window_ms = world.cfg["scoring.window_days"] * DAY
        now = world.clock.now_ms()
        assert now - window_ms - 3_600_000 <= start < end <= now + 1
        failed_at = candle_calls(world, BAD)[-1].t_ms
        cooldown_ms = int(world.cfg["hl.backoff_max_s"] * 1000)
        world.clock.now = failed_at + cooldown_ms - 10_000
        for wallet in (A, B, C):
            world.backfiller.refresh(wallet)
        assert len(coin_lines(caplog)) == 1
        world.clock.now = failed_at + cooldown_ms + 5_000
        for wallet in (A, B, C):
            world.backfiller.refresh(wallet)
        assert len(coin_lines(caplog)) == 2  # the next cooldown: one more line


@pytest.mark.parametrize(("fail_fast", "code"), CASES[:2], ids=IDS[:2])
def test_R4_AC3_other_wallets_are_not_blocked_or_starved(fail_fast: bool, code: int) -> None:
    world = build(fail_fast, code, bad_wallets=(A,), ok_wallets=(B, C))
    steps = drive(world, max_steps=12)  # a few slices, not minutes of cooldown
    assert steps <= 12
    for wallet in (A, B, C):
        assert world.backfiller.inputs(wallet, T0) is not None


def test_R4_AC3_a_wallet_that_trades_only_the_failing_coin_still_completes() -> None:
    world = make_world(fail_fast=True)
    install(world, {BAD: 500})
    world.hl.set_fills(A, good_trips(T0, 20, tids=Tids(), coin=BAD))
    world.backfiller.set_candidates([A])
    drive(world, max_steps=10)
    inputs = world.backfiller.inputs(A, T0)
    assert inputs is not None and not inputs.candles_1h.get(BAD)


@pytest.mark.parametrize("fail_fast", [False, True], ids=["sleeping", "failfast"])
def test_R4_AC3_a_failing_coin_does_not_starve_the_screening_step(
    fail_fast: bool, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = make_r3(tmp_path, fail_fast=fail_fast)
    r3_install(r3, {BAD: 500})
    wallets = [w(i) for i in range(1, 6)]
    for i, wallet in enumerate(wallets):
        r3.serve(wallet, ok_page(T0, coin=BAD if i < 2 else "BTC"))
    r3.set_board([row(wallet) for wallet in wallets])
    with caplog.at_level(logging.INFO):
        r3.cycle()
        assert r3.drive_until_complete(max_ticks=40) <= 40
    for wallet in wallets:
        assert verdict(caplog, wallet)["outcome"] == "ok"
        assert r3.mw.inputs.inputs(wallet, r3.clock.now_ms()) is not None
    assert len(coin_lines(caplog)) == 1
