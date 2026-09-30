"""F5.AC5 / AC6 / AC7 through the cycle entry points: point-in-time, order independence, verified fills only, persistence.

Spec: 04-spec.md F5.AC5-AC7; edge-hypothesis 10.1, 10.6 step 9, 10.7 tests 3-5, 14, 15; invariant B5.
Wallets ``healthy`` are eligible under the permissive fixture config (window 90, sample-size gates relaxed).
"""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal

import pytest

from copytrade.core.config import Config
from copytrade.scoring.cycle import input_hashes, run_cycle, score_cycle, score_wallet
from copytrade.scoring.models import Candle, DsrResolution, LeaderboardRow, WalletInputs
from tests.scoring import wallets as W
from tests.scoring.helpers import DAY, H, PAPER_COSTS, MemoryStore, clearinghouse, fill, flat_candles, portfolio, window

pytestmark = pytest.mark.unit
D = Decimal
A = "0xaaa0000000000000000000000000000000000001"
B = "0xbbb0000000000000000000000000000000000002"
C = "0xccc0000000000000000000000000000000000003"
HEX64 = re.compile(r"[0-9a-f]{64}")


def one(cfg: Config, w: WalletInputs):  # type: ignore[no-untyped-def]
    return score_wallet(w, cfg=cfg, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)


def cycle(cfg: Config, ws: list[WalletInputs]):  # type: ignore[no-untyped-def]
    return score_cycle(ws, cfg=cfg, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)


def test_F5_AC5_a_healthy_wallet_is_eligible_with_a_score_between_zero_and_one(cfg_permissive: Config) -> None:
    s = one(cfg_permissive, W.healthy(A))
    assert s.eligible and s.reasons == () and s.blowup_flags == ()
    assert s.score is not None and D(0) < s.score <= D(1)
    assert s.metrics is not None and s.metrics.n_rt == 80 and s.metrics.t_days == 90
    assert s.components is not None and s.components.score == s.score


def test_F5_AC5_a_wallets_score_does_not_depend_on_other_wallets_or_input_order(cfg_permissive: Config) -> None:
    a, b, c = W.healthy(A), W.healthy(B, pnls=(12, 10, -8, 14, 8)), W.healthy(C, pnls=(6, 5, -2, 7, 4))
    alone = one(cfg_permissive, a)
    together = {s.address: s for s in cycle(cfg_permissive, [a, b, c]).scores}
    reordered = {s.address: s for s in cycle(cfg_permissive, [c, a, b]).scores}
    for addr in (A, B, C):
        assert together[addr] == reordered[addr]
    assert replace(together[A], rank=None) == alone
    assert alone.eligible


def test_F5_AC5_ranks_are_one_based_by_score_and_ineligible_wallets_have_none(cfg_permissive: Config) -> None:
    a, b = W.healthy(A), W.healthy(B, pnls=(12, 10, -8, 14, 8))
    stale = replace(W.healthy(C), fills_fetched_ms=None)
    result = cycle(cfg_permissive, [stale, b, a])
    assert result.t_ms == W.T
    eligible = [s for s in result.scores if s.eligible]
    assert [s.rank for s in eligible] == list(range(1, len(eligible) + 1))
    assert all(s.rank is None and s.score is None for s in result.scores if not s.eligible)
    scores = [s.score for s in eligible]
    assert scores == sorted(scores, reverse=True)  # type: ignore[type-var]
    assert result.scores[: len(eligible)] == tuple(eligible)  # eligible first, in rank order
    assert "stale_input" in next(s for s in result.scores if s.address == C).reasons


def test_F5_AC5_results_are_deterministic(cfg_permissive: Config) -> None:
    ws = [W.healthy(A), W.healthy(B, pnls=(12, 10, -8, 14, 8))]
    assert cycle(cfg_permissive, ws) == cycle(cfg_permissive, ws)


def test_F5_AC5_identical_wallets_tie_break_by_address_ascending(cfg_permissive: Config) -> None:
    twin_hi = replace(W.healthy(B), address=B)
    twin_lo = replace(W.healthy(A), address=A)
    scores = cycle(cfg_permissive, [twin_hi, twin_lo]).scores
    assert [s.address for s in scores] == [A, B] and [s.rank for s in scores] == [1, 2]


def test_F5_AC5_addresses_are_lowercased_in_results(cfg_permissive: Config) -> None:
    s = one(cfg_permissive, replace(W.healthy(A), address=A.upper().replace("0X", "0x")))
    assert s.address == A


# --- point in time ---------------------------------------------------------------------------------------------------
def _future_noise(w: WalletInputs) -> WalletInputs:
    fut = W.T + H
    late_fills = (
        fill(fut, "BTC", "B", 1000, 100, 0),
        fill(fut + H, "BTC", "A", 1000, 1, 1000, pnl=-99_000, liq=True),
    )
    late_candles = flat_candles("BTC", 1, W.T, W.T + 5 * H, spread="0.9")
    return replace(
        w,
        fills=(*w.fills, *late_fills),
        candles_1h={**w.candles_1h, "BTC": (*w.candles_1h["BTC"], *late_candles)},
        portfolios=(
            *w.portfolios,
            portfolio(W.T + 1, perpAllTime=window([(100 * DAY, 1)], [(100 * DAY, -10**6)])),
        ),
        clearinghouse=(*w.clearinghouse, clearinghouse(W.T + 1, 1, [("BTC", -10**6)])),
    )


def test_F5_AC5_fills_candles_and_snapshots_after_t_never_change_the_score_at_t(cfg_permissive: Config) -> None:
    w = W.healthy(A)
    assert one(cfg_permissive, _future_noise(w)) == one(cfg_permissive, w)


def test_F5_AC5_point_in_time_holds_for_the_metrics_of_h1(cfg90: Config) -> None:
    w = W.h1()
    assert one(cfg90, _future_noise(w)) == one(cfg90, w)


def test_F5_AC5_the_latest_snapshot_at_or_before_t_wins(cfg_permissive: Config) -> None:
    w = W.healthy(A)
    older = replace(w.clearinghouse[0], fetched_ms=W.T - 30 * 60_000, account_value=D(1))  # an old, tiny AV
    newer_first = replace(w, clearinghouse=(w.clearinghouse[0], older))  # order in the tuple must not matter
    assert one(cfg_permissive, newer_first) == one(cfg_permissive, w)
    assert one(cfg_permissive, newer_first).metrics.account_value == D(20_000)  # type: ignore[union-attr]


def test_F5_AC5_dsr_resolution_matches_t_and_perp_alltime_points_do_not_change_it(cfg_permissive: Config) -> None:
    w = W.healthy(A)
    base = one(cfg_permissive, w)
    assert base.dsr_resolution == DsrResolution(own_hourly_days=0, perp_month_days=0, fill_days=90)
    noisy = replace(
        w,
        portfolios=(portfolio(W.FETCHED, perpAllTime=window([(100 * DAY, 10_000)], [(100 * DAY, 0), (233 * DAY + 5, 77), (250 * DAY, -1234), (299 * DAY, 500)])),),
    )
    s = one(cfg_permissive, noisy)
    assert s.dsr_resolution == base.dsr_resolution
    assert s.metrics.sr_d == base.metrics.sr_d and s.metrics.t_days == base.metrics.t_days  # type: ignore[union-attr]


def test_F5_AC5_a_wallet_with_too_few_daily_resolution_days_is_ineligible_under_G7(cfg_permissive: Config) -> None:
    w = W.healthy(A)
    # first account-value point on day 260: days 261..299 have a previous-day AV, so T = 39 < 60
    young_av = replace(w, portfolios=(portfolio(W.FETCHED, perpAllTime=window([(int(260.5 * DAY), 10_000)], [(int(260.5 * DAY), 0)])),))
    s = one(cfg_permissive, young_av)
    assert s.metrics is not None and s.metrics.t_days == 39
    assert "G7" in s.reasons and s.eligible is False and s.score is None


# --- AC6: verified fills only ----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "row",
    [
        LeaderboardRow(pnl=D(10**12), roi=D(999), account_value=D(10**12)),
        LeaderboardRow(pnl=D(-5), roi=D("-0.99"), account_value=D(0)),
        LeaderboardRow(pnl=D(0), roi=D(0), account_value=D("0.01")),
    ],
)
def test_F5_AC6_leaderboard_fields_never_change_a_metric_or_the_score(cfg_permissive: Config, row: LeaderboardRow) -> None:
    w = W.healthy(A)
    assert one(cfg_permissive, replace(w, leaderboard_row=row)) == one(cfg_permissive, replace(w, leaderboard_row=None))


def test_F5_AC6_leaderboard_fields_never_change_an_ineligible_wallet_either(cfg90: Config) -> None:
    w = W.h1()
    liar = replace(w, leaderboard_row=LeaderboardRow(pnl=D(10**9), roi=D(50), account_value=D(10**9)))
    assert one(cfg90, liar) == one(cfg90, w)
    assert one(cfg90, liar).eligible is False


def test_F5_AC6_input_hashes_do_not_cover_the_leaderboard_row(cfg90: Config) -> None:
    w = W.h1()
    liar = replace(w, leaderboard_row=LeaderboardRow(pnl=D(1), roi=D(1), account_value=D(1)))
    assert input_hashes(liar, t_ms=W.T) == input_hashes(w, t_ms=W.T)


# --- AC7: persistence ------------------------------------------------------------------------------------------------
def test_F5_AC7_every_cycle_persists_one_record_with_every_wallet(cfg_permissive: Config) -> None:
    store = MemoryStore()
    ws = [W.healthy(A), W.healthy(B, pnls=(12, 10, -8, 14, 8)), replace(W.healthy(C), fills_fetched_ms=None)]
    result = run_cycle(store, ws, cfg=cfg_permissive, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert len(store.cycles) == 1 and store.cycles[0] == result
    assert {s.address for s in store.cycles[0].scores} == {A, B, C}


def test_F5_AC7_persisted_wallet_has_hashes_metrics_components_score_rank_and_resolution(cfg_permissive: Config) -> None:
    store = MemoryStore()
    run_cycle(store, [W.healthy(A)], cfg=cfg_permissive, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    s = store.cycles[0].scores[0]
    assert set(s.input_hashes) == {"fills", "funding", "portfolio", "clearinghouse", "own_snapshots", "candles"}
    assert all(HEX64.fullmatch(v) for v in s.input_hashes.values())
    assert s.metrics is not None and s.components is not None and set(s.components.u) == {
        "dsr_excess", "copy_mean_r", "pos_blocks", "max_dd", "recent_sr", "executable",
    }
    assert s.score is not None and s.rank == 1
    assert s.dsr_resolution is not None and (
        s.dsr_resolution.own_hourly_days + s.dsr_resolution.perp_month_days + s.dsr_resolution.fill_days == s.metrics.t_days
    )


def test_F5_AC7_ineligible_wallets_persist_their_reasons_and_the_hashes_of_what_they_had(cfg90: Config) -> None:
    store = MemoryStore()
    stale = replace(W.h1(), candles_fetched_ms=None)
    run_cycle(store, [W.h1(), stale], cfg=cfg90, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    by_stale = {("stale_input" in s.reasons): s for s in store.cycles[0].scores}
    assert by_stale[False].reasons and by_stale[False].score is None and by_stale[False].rank is None
    assert by_stale[True].input_hashes["fills"] and HEX64.fullmatch(by_stale[True].input_hashes["fills"])


def test_F5_AC7_input_hashes_are_stable_and_change_only_with_their_input(cfg90: Config) -> None:
    w = W.h1()
    base = dict(input_hashes(w, t_ms=W.T))
    assert dict(input_hashes(w, t_ms=W.T)) == base  # stable
    shuffled = replace(w, fills=tuple(reversed(w.fills)))
    assert dict(input_hashes(shuffled, t_ms=W.T)) == base  # input order does not matter
    changed = replace(w, fills=(*w.fills[:-1], replace(w.fills[-1], px=w.fills[-1].px + 1)))
    got = dict(input_hashes(changed, t_ms=W.T))
    assert got["fills"] != base["fills"]
    assert {k: v for k, v in got.items() if k != "fills"} == {k: v for k, v in base.items() if k != "fills"}


def test_F5_AC7_a_future_fill_does_not_change_the_persisted_fills_hash() -> None:
    w = W.h1()
    assert dict(input_hashes(_future_noise(w), t_ms=W.T)) == dict(input_hashes(w, t_ms=W.T))


def test_F5_AC7_a_store_failure_propagates_and_nothing_is_swallowed(cfg_permissive: Config) -> None:
    store = MemoryStore(fail=OSError("disk full"))
    with pytest.raises(OSError, match="disk full"):
        run_cycle(store, [W.healthy(A)], cfg=cfg_permissive, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert store.cycles == []


def test_F5_AC7_an_empty_cycle_is_persisted_as_an_empty_record(cfg_permissive: Config) -> None:
    store = MemoryStore()
    run_cycle(store, [], cfg=cfg_permissive, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert len(store.cycles) == 1 and store.cycles[0].scores == ()


def test_F5_AC7_rerunning_the_same_cycle_persists_identical_records(cfg_permissive: Config) -> None:
    store = MemoryStore()
    for _ in range(2):
        run_cycle(store, [W.healthy(A)], cfg=cfg_permissive, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)
    assert store.cycles[0] == store.cycles[1]


def test_F5_AC5_candle_bars_with_close_after_t_are_not_part_of_the_candles_hash() -> None:
    w = W.h1()
    bar = Candle(open_ms=W.T - 1, close_ms=W.T + H, o=D(1), hi=D(1), lo=D(1), c=D(1))  # opens before t, closes after
    more = replace(w, candles_1h={**w.candles_1h, "BTC": (*w.candles_1h["BTC"], bar)})
    assert dict(input_hashes(more, t_ms=W.T)) == dict(input_hashes(w, t_ms=W.T))
