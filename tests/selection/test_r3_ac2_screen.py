"""R3.AC2 [integration]: stage 2, the first-page fills screen S1-S9 (research/candidate-ranking.md section 9, V2-V4).

A loopback fake Hyperliquid serves crafted ``userFillsByTime`` pages; the REAL manager, paced inputs, backfiller, REST
client and rate budget decide. Each crafted wallet fails exactly one rule (or passes at the threshold).

Pinned decisions (the doc leaves the observable open), the same as in 05-test-plan-R3.md:
- every screened wallet gets ONE INFO record, event ``candidate_screened``; its MESSAGE carries ``wallet=<address>``,
  ``outcome=ok|rejected``, ``failed=<ids>`` and ``not_evaluable=<ids>`` (ids ascending, comma separated, ``none`` when
  empty): that is how a rule's verdict is observed here;
- a screen is ONE ``userFillsByTime`` request ``{user, startTime = screen time - scoring.window_days, aggregateByTime}``
  with no ``endTime`` (exactly backfill page 1);
- a failed or malformed response is NOT a screen: no ``candidate_screened`` line, no screen cooldown, the wallet is
  tried again after R1's per-wallet error cooldown;
- thresholds are inclusive as the doc writes them (``>=`` / ``<=``), S6 is strict (``< 10 000``).
"""

from __future__ import annotations

import logging
from decimal import Decimal as D
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.hl.support import ok, status
from tests.selection.helpers import w
from tests.selection.r3_world import (
    DAY,
    HOUR,
    R3,
    Tids,
    fill,
    full_page,
    full_short_page,
    good_trips,
    make_r3,
    non_core,
    page_ok_full,
    page_s1,
    page_s2,
    page_s3,
    page_s4,
    page_s5,
    page_s6,
    page_s7,
    page_s8,
    page_s9,
    row,
    screen_lines,
    trip,
    trips_in,
    verdict,
)

Page = Callable[[int], list[dict[str, Any]]]
ALL_RULES = {f"S{i}" for i in range(1, 10)}


def screen(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    build: Page,
    *,
    rowkw: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    ticks: int = 40,
) -> dict[str, Any]:
    """One wallet, one cycle: the screen verdict from its log line. ``build(t)`` is the wallet's whole history as seen
    by a screen at ``t`` (the HTTP call time)."""
    r3 = make_r3(tmp_path, **(cfg or {}))
    r3.serve_at(w(1), build)
    r3.set_board([row(w(1), **(rowkw or {}))])
    with caplog.at_level(logging.INFO):
        r3.cycle(ticks)
    return verdict(caplog, w(1))


def assert_fails_only(v: dict[str, Any], rule: str) -> None:
    assert v["outcome"] == "rejected" and v["failed"] == {rule}, v


def assert_passes(v: dict[str, Any]) -> None:
    assert v["outcome"] == "ok" and v["failed"] == set(), v


# --- the request ----------------------------------------------------------------------------------------------------


def test_R3_AC2_each_candidate_gets_one_window_start_page_request_in_stage_1_rank_order(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    rows = [row(w(1), bps_m=20, bps_p=20), row(w(2), bps_m=40, bps_p=40), row(w(3), bps_m=30, bps_p=30)]
    r3.set_board(rows)
    r3.cycle(60)
    assert r3.screened_order() == [w(2), w(3), w(1)]
    for wallet in (w(1), w(2), w(3)):
        (call,) = r3.fills_calls(wallet)
        assert set(call.body) == {"type", "user", "startTime", "aggregateByTime"}
        assert call.body["aggregateByTime"] is True
        assert call.body["startTime"] == call.t_ms - 180 * DAY


def test_R3_AC2_a_wallet_that_is_not_a_candidate_is_not_screened(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    r3.set_board([row(w(1)), row(w(2), pnl_month="0")])
    r3.cycle(60)
    assert r3.fills_calls(w(2)) == []


# --- S1, S2 ---------------------------------------------------------------------------------------------------------


def test_R3_AC2_S1_a_page_with_no_fill_is_rejected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    v = screen(tmp_path, caplog, page_s1)
    assert v["outcome"] == "rejected" and "S1" in v["failed"]


def test_R3_AC2_S1_one_fill_is_enough_to_pass_S1(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    v = screen(tmp_path, caplog, lambda t: trip(Tids(), t - 100 * DAY, None))
    assert "S1" not in v["failed"] and "S2" not in v["failed"]
    assert v["outcome"] == "rejected" and "S9" in v["failed"]  # one open trip is nowhere near 150 round trips


def test_R3_AC2_S2_a_full_page_spanning_less_than_a_day_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    v = screen(tmp_path, caplog, lambda t: page_s2(t, DAY - 1))
    assert v["outcome"] == "rejected" and "S2" in v["failed"]


def test_R3_AC2_S2_a_full_page_spanning_exactly_a_day_is_not_an_S2_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    v = screen(tmp_path, caplog, lambda t: page_s2(t, DAY))
    assert "S2" not in v["failed"]  # (it still fails S5/S6: 2 000 fills in a day is far too active)
    assert v["outcome"] == "rejected" and "S6" in v["failed"]


def test_R3_AC2_S2_a_page_of_1999_fills_inside_a_day_is_not_full_so_not_an_S2_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    v = screen(tmp_path, caplog, lambda t: page_s2(t, DAY - 1)[:1999])
    assert "S2" not in v["failed"]


# --- S3 core share --------------------------------------------------------------------------------------------------


def test_R3_AC2_S3_core_share_below_one_half_fails_only_S3(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert_fails_only(screen(tmp_path, caplog, page_s3), "S3")


def test_R3_AC2_S3_core_share_of_exactly_one_half_passes(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert_passes(screen(tmp_path, caplog, lambda t: page_s3(t, 640_000)))


def test_R3_AC2_S3_spot_pairs_and_hip3_names_are_not_core(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    def build(t: int) -> list[dict[str, Any]]:
        tids = Tids()
        rows = good_trips(t, tids=tids)
        for coin in ("@107", "PURR/USDC", "xyz:TSLA"):  # spot index, spot pair, builder-dex perp: 214 000 USD each
            rows.append(non_core(tids, t - 50 * DAY, 214_000, coin=coin))
        return rows

    assert_fails_only(screen(tmp_path, caplog, build), "S3")  # 642 000 outside vs 640 000 core


def test_R3_AC2_S3_an_unusual_core_perp_name_counts_as_core(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    def build(t: int) -> list[dict[str, Any]]:
        tids = Tids()
        rows = good_trips(t, tids=tids, coin="kPEPE")
        rows.append(non_core(tids, t - 50 * DAY, 640_000))
        return rows

    assert_passes(screen(tmp_path, caplog, build))


def test_R3_AC2_S3_and_S4_fail_when_every_fill_is_outside_the_universe(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def build(t: int) -> list[dict[str, Any]]:
        tids = Tids()
        return [non_core(tids, t - 90 * DAY + k * HOUR, 1_000) for k in range(50)]

    v = screen(tmp_path, caplog, build)
    assert v["outcome"] == "rejected" and {"S3", "S4"} <= v["failed"]  # no core notional: S4 fails closed like G13


# --- S4 maker share (G13's definition, on the core fills) -----------------------------------------------------------


def test_R3_AC2_S4_a_maker_share_of_0_703_fails_only_S4(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert_fails_only(screen(tmp_path, caplog, lambda t: page_s4(t, 225)), "S4")


def test_R3_AC2_S4_a_maker_share_of_exactly_0_70_passes(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert_passes(screen(tmp_path, caplog, lambda t: page_s4(t, 224)))


def test_R3_AC2_S4_the_share_is_over_core_fills_only(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    def build(t: int) -> list[dict[str, Any]]:
        # core: 240 of 320 fills are maker (0.75); an equal taker notional outside the universe would dilute an
        # all-fills share to 0.375 and let it through
        tids = Tids()
        rows = good_trips(t, tids=tids, open_crossed=lambda k: False, close_crossed=lambda k: k >= 80)
        rows.append(non_core(tids, t - 50 * DAY, 640_000, crossed=True))
        return rows

    assert_fails_only(screen(tmp_path, caplog, build), "S4")


def test_R3_AC2_S4_repeated_rows_are_counted_once(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    def build(t: int) -> list[dict[str, Any]]:
        base = page_s4(t, 222)  # 0.69375
        makers = [r for r in base if not r["crossed"]][:10]
        return [*base, *[dict(r) for r in makers]]  # counted twice: 232 / 330 = 0.703

    assert_passes(screen(tmp_path, caplog, build))


# --- S5 history length ----------------------------------------------------------------------------------------------


def test_R3_AC2_S5_a_first_core_fill_59_days_back_fails_only_S5(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert_fails_only(screen(tmp_path, caplog, page_s5), "S5")


def test_R3_AC2_S5_exactly_60_days_passes_one_millisecond_less_fails(tmp_path: Path) -> None:
    for ago, expect_pass in ((60 * DAY, True), (60 * DAY - 1, False)):
        r3 = make_r3(tmp_path / str(ago))
        r3.serve_at(w(1), lambda t, ago=ago: good_trips(t, first_ago=ago))
        r3.set_board([row(w(1))])
        r3.cycle(40)
        assert (r3.backfilled() == {w(1)}) is expect_pass  # only a survivor gets the rest of the backfill


def test_R3_AC2_S5_the_first_CORE_fill_counts_not_an_older_spot_fill(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def build(t: int) -> list[dict[str, Any]]:
        tids = Tids()
        rows = good_trips(t, first_ago=59 * DAY, tids=tids)
        rows.append(non_core(tids, t - 170 * DAY, 1))
        return rows

    assert "S5" in screen(tmp_path, caplog, build)["failed"]


# --- S6 rate (full pages only) --------------------------------------------------------------------------------------


def test_R3_AC2_S6_a_full_page_at_12000_fills_a_window_fails_only_S6(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert_fails_only(screen(tmp_path, caplog, page_s6), "S6")


@pytest.mark.parametrize(
    ("span_ms", "passes"),
    [(36 * DAY - 1, False), (36 * DAY, False), (36 * DAY + 1, True)],
    ids=["just under 36 d", "exactly 36 d (10 000: not below the limit)", "just over 36 d"],
)
def test_R3_AC2_S6_the_limit_is_strictly_below_10000_fills_per_window(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, span_ms: int, passes: bool
) -> None:
    v = screen(tmp_path, caplog, lambda t: page_s6(t, span_ms))
    assert ("S6" not in v["failed"]) is passes, v


def test_R3_AC2_S6_a_page_that_is_not_full_is_not_evaluable_never_a_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    v = screen(tmp_path, caplog, lambda t: good_trips(t))
    assert_passes(v)
    assert "S6" in v["not_evaluable"]


def test_R3_AC2_S6_uses_the_scoring_window_from_config(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    def build(t: int) -> list[dict[str, Any]]:
        tids = Tids()
        core = trips_in(t, 40, first_ago=85 * DAY, span_ms=30 * DAY, tids=tids)
        return full_page(t, core, tids, first_ago=85 * DAY, span_ms=30 * DAY)  # 66.7 a day

    assert_fails_only(screen(tmp_path / "a", caplog, build), "S6")  # x 180 d = 12 000
    caplog.clear()
    assert_passes(screen(tmp_path / "b", caplog, build, cfg={"scoring__window_days": 90}))  # x 90 d = 6 000


# --- S7 median hold, S8 executable share, both need >= 30 trips -----------------------------------------------------


def test_R3_AC2_S7_a_median_hold_just_under_15_minutes_fails_only_S7(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert_fails_only(screen(tmp_path, caplog, page_s7), "S7")


def test_R3_AC2_S7_a_median_hold_of_exactly_15_minutes_passes(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert_passes(screen(tmp_path, caplog, lambda t: page_s7(t, 900_000)))


def _open_and_closed(t: int, *, closed: int, still_open: int) -> list[dict[str, Any]]:
    tids = Tids()
    short = trips_in(t, closed, first_ago=100 * DAY, span_ms=50 * DAY, hold_ms=60_000, tids=tids)
    opens: list[dict[str, Any]] = []
    for k in range(still_open):
        opens += trip(tids, t - 60 * DAY + k * HOUR, None, coin=f"OP{k}")
    return full_page(t, [*short, *opens], tids)


def test_R3_AC2_S7_open_trips_count_as_infinite_holds(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # 15 closed 1-minute trips and 16 trips still open at the page end: the median of 31 is an open one
    v = screen(tmp_path, caplog, lambda t: _open_and_closed(t, closed=15, still_open=16))
    assert "S7" not in v["failed"] and "S7" not in v["not_evaluable"], v  # 31 trips: evaluated, and it passes
    assert_passes(v)


def test_R3_AC2_S7_open_trips_do_not_rescue_a_short_median(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # 16 closed 1-minute trips and 15 open: the median of 31 is a closed short one
    v = screen(tmp_path, caplog, lambda t: _open_and_closed(t, closed=16, still_open=15))
    assert_fails_only(v, "S7")


def test_R3_AC2_S8_an_executable_share_just_under_one_half_fails_only_S8(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert_fails_only(screen(tmp_path, caplog, lambda t: page_s8(t, 79)), "S8")


def test_R3_AC2_S8_an_executable_share_of_exactly_one_half_passes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert_passes(screen(tmp_path, caplog, lambda t: page_s8(t, 80)))


@pytest.mark.parametrize(("px", "passes"), [("1000", True), ("999.99", False)], ids=["exactly 10 USD", "9.9999 USD"])
def test_R3_AC2_S8_a_trip_is_executable_when_its_scaled_open_reaches_the_minimum_order(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, px: str, passes: bool
) -> None:
    # AV 30 000, paper wallet 300, minimum order 10: the open must be at least 1 000 USD (1 x px)
    v = screen(
        tmp_path, caplog, lambda t: good_trips(t, open_px=lambda k: px), rowkw={"av": 30_000}
    )
    assert ("S8" not in v["failed"]) is passes, v


def test_R3_AC2_S7_and_S8_are_not_evaluable_below_30_trips_so_never_a_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    v = screen(tmp_path, caplog, lambda t: page_ok_full(t, n_trips=29, hold_ms=60_000))  # 29 trips, all short
    assert_passes(v)
    assert {"S7", "S8"} <= v["not_evaluable"]


def test_R3_AC2_S7_is_evaluated_from_30_trips(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    v = screen(tmp_path, caplog, lambda t: page_ok_full(t, n_trips=30, hold_ms=60_000))
    assert_fails_only(v, "S7")
    assert "S7" not in v["not_evaluable"]


def test_R3_AC2_S7_and_S8_count_open_trips_towards_the_30(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    v = screen(tmp_path, caplog, lambda t: _open_and_closed(t, closed=14, still_open=16))  # 30 trips, 16 open
    assert not ({"S7", "S8"} & v["not_evaluable"]), v


# --- S9 round trips (non-full pages only) ---------------------------------------------------------------------------


def test_R3_AC2_S9_149_closed_round_trips_fail_only_S9(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert_fails_only(screen(tmp_path, caplog, page_s9), "S9")


def test_R3_AC2_S9_150_closed_round_trips_pass(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert_passes(screen(tmp_path, caplog, lambda t: page_s9(t, 150)))


def test_R3_AC2_S9_a_full_page_is_not_evaluable_never_a_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    v = screen(tmp_path, caplog, lambda t: page_ok_full(t))  # 40 closed trips only: below 150, but the page is partial
    assert_passes(v)
    assert "S9" in v["not_evaluable"]


def test_R3_AC2_S9_a_position_open_before_the_page_is_ignored_until_flat(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def build(t: int) -> list[dict[str, Any]]:
        tids = Tids()
        rows = good_trips(t, 149, tids=tids)  # 149 closed trips ...
        rows.append(  # ... plus the close of a position opened before the page: not a round trip of this page
            fill("BTC", "A", "1", "2000", t - 101 * DAY, "1", tids, direction="Close Long", closed_pnl="1.0")
        )
        return rows

    assert_fails_only(screen(tmp_path, caplog, build), "S9")


def test_R3_AC2_S9_a_flip_splits_into_a_close_and_a_new_trip(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    def build(t: int) -> list[dict[str, Any]]:
        tids = Tids()
        rows = good_trips(t, 148, tids=tids)
        at = t - 30 * HOUR
        rows += [
            fill("ETH", "B", "1", "2000", at, "0.0", tids),  # open long 1
            fill("ETH", "A", "2", "2000", at + HOUR, "1", tids, direction="Long > Short", closed_pnl="1.0"),  # flip
            fill("ETH", "B", "1", "2000", at + 2 * HOUR, "-1", tids, direction="Close Short", closed_pnl="1.0"),
        ]
        return rows  # 148 + the long + the short = 150 closed trips

    assert_passes(screen(tmp_path, caplog, build))


# --- a rule is a failure only when evaluated ------------------------------------------------------------------------


def test_R3_AC2_a_page_that_passes_everything_it_can_be_judged_on_is_ok_and_lists_what_it_could_not_judge(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    v = screen(tmp_path, caplog, lambda t: page_ok_full(t, n_trips=10))  # full, only 10 trips
    assert v["outcome"] == "ok" and v["failed"] == set()
    assert v["not_evaluable"] == {"S7", "S8", "S9"}


# --- reused config keys are read from config, not hard-coded --------------------------------------------------------


CONFIG_CASES: list[tuple[str, Page, dict[str, Any], str, str]] = [
    # (rule, page, override, outcome under the default, outcome with the override)
    ("S4 max maker share", lambda t: page_s4(t, 192), {"gate__max_maker_share": D("0.5")}, "ok", "S4"),
    ("S5 min fill span", lambda t: page_s5(t, 80 * DAY), {"gate__min_fill_span_days": 90}, "ok", "S5"),
    ("S7 min median hold", lambda t: page_s7(t, 1_200_000), {"gate__min_median_hold_min": 30}, "ok", "S7"),
    ("S8 min executable share", lambda t: page_s8(t, 80), {"gate__min_executable_share": D("0.9")}, "ok", "S8"),
    ("S8 min order usd", lambda t: good_trips(t), {"sizing__min_order_usd": 20}, "ok", "S8"),
    ("S9 min round trips", lambda t: page_s9(t, 120), {"gate__min_round_trips": 100}, "S9", "ok"),
]


@pytest.mark.parametrize(("label", "page", "override", "default", "changed"), CONFIG_CASES, ids=[c[0] for c in CONFIG_CASES])
def test_R3_AC2_the_reused_thresholds_come_from_config(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, label: str, page: Page, override: dict[str, Any], default: str, changed: str
) -> None:
    v0 = screen(tmp_path / "default", caplog, page)
    assert (v0["failed"] == set()) is (default == "ok"), (label, v0)
    caplog.clear()
    v1 = screen(tmp_path / "override", caplog, page, cfg=override)
    assert (v1["failed"] == set()) is (changed == "ok"), (label, v1)


# --- a failed fetch is not a rejection ------------------------------------------------------------------------------


@pytest.mark.parametrize("failure", ["http 500", "schema"])
def test_R3_AC2_a_fetch_or_schema_error_is_not_a_screen_the_wallet_is_tried_again(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    r3 = make_r3(tmp_path)
    good = good_trips(r3.clock.now_ms())
    r3.serve(w(1), good)
    healthy = r3.world.hl.rules[(w(1), "userFillsByTime")]
    state = {"broken": True}

    def rule(call: Any) -> Any:
        if state["broken"]:
            return status(500) if failure == "http 500" else ok([{"coin": "BTC", "px": "1"}])  # no tid, sz, ...
        return healthy(call)

    r3.world.hl.rules[(w(1), "userFillsByTime")] = rule
    r3.set_board([row(w(1))])
    with caplog.at_level(logging.INFO):
        r3.cycle(12)
        assert screen_lines(caplog) == []  # not judged: neither ok nor rejected
        state["broken"] = False
        r3.drive(40)  # the error cooldown (hl.backoff_base_s doubling, capped at hl.backoff_max_s) runs out
    v = verdict(caplog, w(1))
    assert v["outcome"] == "ok", v  # one screen line, from the later good page, and no 72 h or 168 h cooldown applied


def test_R3_AC2_the_screen_makes_one_request_per_wallet_whatever_the_outcome(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    pages = {w(1): page_s1, w(2): lambda t: page_s2(t), w(3): page_s3, w(4): page_s7, w(5): lambda t: good_trips(t)}
    for i, (wallet, build) in enumerate(pages.items(), start=1):
        r3.serve_at(wallet, build)
    r3.set_board([row(wallet, bps_m=10 + i, bps_p=10 + i) for i, wallet in enumerate(pages, start=1)])
    r3.cycle()
    r3.drive_until_complete()
    # a rejected wallet is asked once; the survivor's one screen page is its backfill page 1 (non-full: complete)
    assert {wallet: len(r3.fills_calls(wallet)) for wallet in pages} == {wallet: 1 for wallet in pages}
