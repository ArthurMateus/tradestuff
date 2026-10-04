"""R4.AC2 [integration]: a wallet whose fills include ``#N`` coins is backfilled without a single candle request for
them, the screen rules ignore them (S3 core share and S4 maker share are over real core perps only; also S5's first core
fill) and the scorer ignores them.

Pinned decision: "ignore" means a ``#N`` fill is neither in the numerator nor in the denominator of the S3 share (it is
not spot either): a page of good BTC trips plus a huge ``#N`` notional still passes S3, and a page whose real core share
is below the minimum still fails it whatever ``#N`` adds.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import pytest

from copytrade.scoring.cycle import score_wallet
from copytrade.scoring.models import Fill
from tests.hl.support import T0, make_config
from tests.scoring.helpers import ZERO_COSTS, clearinghouse, portfolio, round_trip_fills, wallet
from tests.selection.helpers import w
from tests.selection.r1_world import DAY, make_world
from tests.selection.r3_world import R3, HOUR, Tids, good_trips, make_r3, ok_page, page_s3, page_s5, row, verdict
from tests.selection.r4_world import (
    HASH_COINS,
    candle_calls,
    candle_coins,
    drive,
    hash_fill,
    install,
    r3_install,
    trips_of,
)

A, B = w(1), w(2)


def test_R4_AC2_a_backfill_never_requests_candles_for_hash_coins() -> None:
    world = make_world()
    install(world)
    tids = Tids()
    rows = good_trips(T0, 20, tids=tids) + trips_of(list(HASH_COINS), T0, n=5, tids=tids)
    world.hl.set_fills(A, rows)
    world.backfiller.set_candidates([A])
    drive(world)
    for coin in HASH_COINS:
        assert candle_calls(world, coin) == []
    assert candle_coins(world) == {"BTC"}


def test_R4_AC2_the_wallet_is_complete_with_bars_for_real_perps_only() -> None:
    world = make_world(fail_fast=True)  # the PO's wiring: a failing request must not end in a cooldown for the wallet
    install(world)
    tids = Tids()
    world.hl.set_fills(A, good_trips(T0, 20, tids=tids) + trips_of(list(HASH_COINS), T0, n=5, tids=tids))
    world.backfiller.set_candidates([A])
    drive(world, max_steps=10)
    inputs = world.backfiller.inputs(A, T0)
    assert inputs is not None
    assert set(inputs.candles_1h) == {"BTC"} and inputs.candles_1h["BTC"]


def test_R4_AC2_hash_coins_do_not_stall_other_wallets() -> None:
    world = make_world(fail_fast=True)
    install(world)
    world.hl.set_fills(A, trips_of(["BTC", *HASH_COINS], T0, n=5, tids=Tids()))
    world.hl.set_fills(B, good_trips(T0, 20, tids=Tids()))
    world.backfiller.set_candidates([A, B])
    assert drive(world, max_steps=15) <= 15
    assert world.backfiller.inputs(A, T0) is not None and world.backfiller.inputs(B, T0) is not None


def test_R4_AC2_a_screened_wallet_with_hash_fills_is_admitted_and_backfilled_without_their_candles(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    r3_install(r3)
    tids = Tids()
    page = good_trips(T0, 160, tids=tids) + trips_of(["#140", "#7521"], T0, n=5, tids=tids)
    r3.serve(A, page)
    r3.set_board([row(A)])
    r3.cycle()
    r3.drive_until_complete()
    assert r3.mw.inputs.inputs(A, r3.clock.now_ms()) is not None
    assert candle_coins(r3.world) == {"BTC"}


def screened(tmp_path: Path, rows: list, caplog: pytest.LogCaptureFixture) -> dict:  # type: ignore[type-arg]
    r3: R3 = make_r3(tmp_path)
    r3_install(r3)
    r3.serve(A, rows)
    r3.set_board([row(A)])
    with caplog.at_level(logging.INFO):
        r3.cycle()
        r3.drive(3)
    return verdict(caplog, A)


def test_R4_AC2_S4_maker_share_ignores_hash_coin_maker_fills(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    tids = Tids(10_000)
    rows = ok_page(T0)
    rows += [hash_fill(tids, T0 - 30 * DAY + k * HOUR, 75_000, crossed=False) for k in range(40)]  # 3 000 000 USD maker
    v = screened(tmp_path, rows, caplog)
    assert "S4" not in v["failed"] and v["outcome"] == "ok"


def test_R4_AC2_S3_core_share_is_over_real_perps_hash_notional_cannot_rescue_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tids = Tids(10_000)
    rows = page_s3(T0)  # real core share 0.4992: fails S3
    rows.append(hash_fill(tids, T0 - 40 * DAY, 5_000_000))
    v = screened(tmp_path, rows, caplog)
    assert "S3" in v["failed"]


def test_R4_AC2_S3_hash_notional_does_not_count_against_a_wallet_of_real_perps(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tids = Tids(10_000)
    rows = ok_page(T0)
    rows.append(hash_fill(tids, T0 - 40 * DAY, 10_000_000))
    v = screened(tmp_path, rows, caplog)
    assert "S3" not in v["failed"] and v["outcome"] == "ok"


def test_R4_AC2_S5_history_span_counts_real_core_fills_only(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    tids = Tids(10_000)
    rows = page_s5(T0)  # first real core fill 59 days ago: fails S5
    rows.append(hash_fill(tids, T0 - 150 * DAY, 2_000))
    v = screened(tmp_path, rows, caplog)
    assert "S5" in v["failed"]


def test_R4_AC2_scoring_ignores_hash_coin_fills(tmp_path: Path) -> None:
    cfg = make_config()
    t = T0
    base = []
    for k in range(30):
        base += round_trip_fills(t - (60 - k) * DAY, HOUR, coin="BTC", px=100, exit_px=101)
    extra = []
    for k, coin in enumerate(HASH_COINS):
        for j in range(4):
            extra += round_trip_fills(t - (50 - 3 * j - k) * DAY, HOUR, coin=coin, px=100, exit_px=90)

    def score(fills: list[Fill]):  # type: ignore[no-untyped-def]
        inputs = wallet(
            fills=fills, fills_fetched_ms=t, portfolios=[portfolio(t)], clearinghouse=[clearinghouse(t, 10_000)],
            candles_fetched_ms=t,
        )
        return score_wallet(inputs, cfg=cfg, t_ms=t, costs=ZERO_COSTS, p95_latency_s=None)

    clean, noisy = score(base), score(base + extra)
    assert noisy.metrics.n_rt == clean.metrics.n_rt == 30
    assert noisy.metrics == clean.metrics
    assert noisy.input_hashes == clean.input_hashes
    assert noisy.reasons == clean.reasons
