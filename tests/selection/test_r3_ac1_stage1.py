"""R3.AC1 [integration]: stage 1 of the candidate screen (research/candidate-ranking.md sections 2 and 9, rules P1-P8,
K1, L1, L4): leaderboard rows are filtered and ranked from the row alone, with no fetch.

Observation: who receives a ``userFillsByTime`` request (the stage-2 screen) and in which order. Every wallet here has
no served fills (an empty page), so each is screened once, cheaply, and the order of the first requests IS the stage-1
list (L1, in K1 order). Thresholds are inclusive as written in the research doc.

Pinned decisions (the doc leaves them open):
- the new numbers (P4..P8, K1 cap 50, S3, S-min-trips, cooldowns, 100 screens) are CODE CONSTANTS: no ``prefilter.*``
  config key exists (PO decision 2026-10-03);
- per cycle ONE INFO record, event ``candidate_prefilter``, with ``rows=<leaderboard rows>`` and ``ranked=<L1 size>``
  in the message text (L5);
- NaN / Infinity / unparsable text in a figure of P1 counts as "missing": the row is unrankable (L4), not rejected.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any

import pytest

from copytrade.selection.models import STATUS_LEADERBOARD_OUTAGE
from tests.hl.support import make_config
from tests.selection.helpers import w
from tests.selection.r3_world import (
    K,
    PREFILTER_EVENT,
    R3,
    board,
    make_r3,
    records,
    row,
    tokens,
)

EXCLUDED = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"


def stage1(tmp_path: Path, rows: list[dict[str, Any]], *, ticks: int = 150, k: int = K) -> tuple[R3, list[str]]:
    r3 = make_r3(tmp_path, k=k)
    r3.set_board(rows)
    r3.cycle(ticks)
    return r3, r3.screened_order()


def check_group(tmp_path: Path, cases: list[tuple[str, dict[str, Any], bool]]) -> None:
    """One board with one row per case (served in the order given); exactly the ``True`` cases are candidates."""
    rows = [row(w(i), **kw) for i, (_label, kw, _passes) in enumerate(cases, start=1)]
    _, order = stage1(tmp_path, rows)
    expected = {w(i) for i, (_l, _kw, passes) in enumerate(cases, start=1) if passes}
    got = set(order)
    labels = {w(i): label for i, (label, _kw, _p) in enumerate(cases, start=1)}
    assert got == expected, {
        "wrongly kept": sorted(labels[a] for a in got - expected if a in labels),
        "wrongly dropped": sorted(labels[a] for a in expected - got),
        "filler fetched": len([a for a in got if a not in labels]),
    }


# --- no fetch, no new key, one log line -----------------------------------------------------------------------------


def test_R3_AC1_stage_1_makes_no_request_of_any_kind(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    r3.set_board([row(w(i)) for i in range(1, 6)])
    r3.mw.manager.run_cycle(p95_latency_s=None)
    assert r3.world.http.calls == []  # the ranking needs only the row


def test_R3_AC1_the_new_numbers_are_code_constants_not_config_keys() -> None:
    cfg = make_config()
    assert [key for key in cfg if key.startswith("prefilter")] == []


def test_R3_AC1_one_info_line_per_cycle_with_the_row_and_ranked_counts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = make_r3(tmp_path)
    r3.set_board([row(w(i)) for i in range(1, 8)] + [row(w(20), pnl_month="0")])
    with caplog.at_level(logging.INFO):
        r3.mw.manager.run_cycle(p95_latency_s=None)
        r3.world.tick(3600)
        r3.mw.manager.run_cycle(p95_latency_s=None)
    lines = records(caplog, PREFILTER_EVENT)
    assert len(lines) == 2
    assert all(rec.levelno >= logging.INFO for rec in lines)
    assert tokens(lines[0])["rows"] == "1000" and tokens(lines[0])["ranked"] == "7"


# --- P1-P8 filters, each at its threshold ---------------------------------------------------------------------------


def test_R3_AC1_a_row_that_passes_every_rule_is_the_only_candidate_among_failing_filler(tmp_path: Path) -> None:
    _, order = stage1(tmp_path, [row(w(1))])
    assert order == [w(1)]  # the 999 filler rows (month volume 0.8 x account value) are never screened


def test_R3_AC1_P2_an_excluded_address_is_never_a_candidate_whatever_its_case(tmp_path: Path) -> None:
    upper = "0x" + EXCLUDED[2:].upper()
    cases = [("excluded lower", EXCLUDED), ("excluded upper", upper), ("other", w(3))]
    rows = [row(addr) for _label, addr in cases]
    _, order = stage1(tmp_path, rows)
    assert order == [w(3)]


def test_R3_AC1_P3_account_value_at_the_minimum_is_kept_one_cent_below_is_dropped(tmp_path: Path) -> None:
    check_group(
        tmp_path,
        [
            ("av 9999.99", {"av": "9999.99"}, False),
            ("av 10000", {"av": "10000"}, True),
            ("av 10000.01", {"av": "10000.01"}, True),
            ("av 0 (no division by zero)", {"av": "0", "vlm_month": "400000"}, False),
            ("av negative", {"av": "-5", "vlm_month": "400000"}, False),
        ],
    )


def test_R3_AC1_P4_the_week_volume_must_be_positive(tmp_path: Path) -> None:
    check_group(
        tmp_path,
        [
            ("week 0", {"vlm_week": "0"}, False),
            ("week 0.01", {"vlm_week": "0.01"}, True),
            ("week negative", {"vlm_week": "-1"}, False),
        ],
    )


def test_R3_AC1_P4_the_month_turnover_must_be_at_least_2(tmp_path: Path) -> None:
    check_group(
        tmp_path,
        [
            ("turn 1.99999998", {"vlm_month": "99999.99"}, False),
            ("turn 2.0", {"vlm_month": "100000"}, True),
            ("turn 2.00000002", {"vlm_month": "100000.01"}, True),
            ("month volume 0 (no division by zero)", {"vlm_month": "0"}, False),
        ],
    )


def test_R3_AC1_P5_the_month_turnover_must_be_at_most_500(tmp_path: Path) -> None:
    low = {"bps_m": 10}  # keeps the month return (P8) at 50% so only the turnover decides
    check_group(
        tmp_path,
        [
            ("turn 500", {**low, "vlm_month": "25000000"}, True),
            ("turn 500.0000002", {**low, "vlm_month": "25000000.01"}, False),
            ("turn 499", {**low, "vlm_month": "24950000"}, True),
        ],
    )


def test_R3_AC1_P5_the_day_turnover_must_be_at_most_50(tmp_path: Path) -> None:
    check_group(
        tmp_path,
        [
            ("day turn 50", {"vlm_day": "2500000"}, True),
            ("day turn 50.0000002", {"vlm_day": "2500000.01"}, False),
            ("day turn 0", {"vlm_day": "0"}, True),
        ],
    )


def test_R3_AC1_P6_profit_is_needed_in_the_last_month_and_before_it(tmp_path: Path) -> None:
    check_group(
        tmp_path,
        [
            ("month pnl 0", {"pnl_month": "0"}, False),
            ("month pnl negative", {"pnl_month": "-5"}, False),
            ("prior pnl 0", {"pnl_prior": "0"}, False),
            ("prior pnl negative", {"pnl_prior": "-5"}, False),
            ("both positive", {}, True),
        ],
    )


def test_R3_AC1_P7_edge_per_traded_dollar_is_at_least_10_bps_in_both_periods(tmp_path: Path) -> None:
    check_group(
        tmp_path,
        [
            ("bps_m 9.99", {"bps_m": "9.99"}, False),
            ("bps_m 10", {"bps_m": "10"}, True),
            ("bps_m 10.01", {"bps_m": "10.01"}, True),
            ("bps_p 9.99", {"bps_p": "9.99"}, False),
            ("bps_p 10", {"bps_p": "10"}, True),
            ("bps_p 10.01", {"bps_p": "10.01"}, True),
            ("prior volume 0 (no division by zero)", {"vlm_prior": "0"}, False),
            ("prior volume negative", {"vlm_prior": "-5"}, False),
        ],
    )


def test_R3_AC1_P8_the_month_return_may_not_exceed_100_percent_of_account_value(tmp_path: Path) -> None:
    check_group(
        tmp_path,
        [
            ("return 1.0", {"pnl_month": "50000"}, True),
            ("return 1.0000002", {"pnl_month": "50000.01"}, False),
            ("return 0.99999998", {"pnl_month": "49999.99"}, True),
        ],
    )


def test_R3_AC1_the_roi_field_is_not_used(tmp_path: Path) -> None:
    check_group(
        tmp_path,
        [
            ("roi junk everywhere", {"set_raw": {f"{n}.roi": "banana" for n in ("day", "week", "month", "allTime")}}, True),
            ("roi missing everywhere", {"drop": [f"{n}.roi" for n in ("day", "week", "month", "allTime")]}, True),
        ],
    )


def test_R3_AC1_a_row_that_fails_P4_to_P8_is_not_appended_even_when_few_rows_are_ranked(tmp_path: Path) -> None:
    rows = [row(w(1)), row(w(2), pnl_month="0"), row(w(3), vlm_month="99999.99"), row(w(4), bps_m="9")]
    _, order = stage1(tmp_path, rows)
    assert order == [w(1)]  # L4 appends unrankable rows only, never a readable row that failed a rule


# --- P1 unrankable rows and L4 --------------------------------------------------------------------------------------


def _unrankable() -> list[tuple[str, dict[str, Any]]]:
    no_perf = row(w(15))
    no_perf.pop("windowPerformances")
    return [
        ("month vlm missing", row(w(11), drop=["month.vlm"])),
        ("account value missing", row(w(12), av=None)),
        ("week pnl unparsable", row(w(13), set_raw={"week.pnl": "n/a"})),
        ("allTime vlm NaN", row(w(14), set_raw={"allTime.vlm": "NaN"})),
        ("no windowPerformances", no_perf),
        ("day pnl Infinity", row(w(16), set_raw={"day.pnl": "Infinity"})),
        ("day pnl missing", row(w(17), drop=["day.pnl"])),
    ]


def test_R3_AC1_unrankable_rows_are_appended_in_served_order_after_the_ranked_ones_when_few_are_ranked(
    tmp_path: Path,
) -> None:
    unrankable = _unrankable()
    low, high = row(w(1), bps_m=20, bps_p=20), row(w(2), bps_m=50, bps_p=50)
    rows = [unrankable[0][1], low, *[r for _l, r in unrankable[1:4]], high, *[r for _l, r in unrankable[4:]]]
    _, order = stage1(tmp_path, rows)
    assert order == [w(2), w(1), *[r["ethAddress"] for _l, r in unrankable]]


def test_R3_AC1_unrankable_rows_that_violate_P2_or_P3_or_have_no_address_are_never_appended(tmp_path: Path) -> None:
    small = row(w(21), av="9999", drop=["month.vlm"])  # P3 violated and a field missing
    excluded = row(EXCLUDED, drop=["month.vlm"])  # P2 violated and a field missing
    bad_address = row("0x123", drop=["month.vlm"])
    no_address = row(w(23))
    no_address.pop("ethAddress")
    rows = [small, excluded, bad_address, no_address, row(w(1))]
    _, order = stage1(tmp_path, rows)
    assert order == [w(1)]


def test_R3_AC1_when_candidates_k_rows_are_ranked_no_unrankable_row_is_appended(tmp_path: Path) -> None:
    ranked = [row(w(100 + i), bps_m=10 + i % 40, bps_p=10 + i % 40) for i in range(1, K + 1)]
    unrankable = [r for _l, r in _unrankable()]
    r3, order = stage1(tmp_path, [*unrankable, *ranked], ticks=400)
    assert set(order) == {r["ethAddress"] for r in ranked}  # all K ranked rows were screened, nobody else
    assert not (set(order) & {r["ethAddress"] for r in unrankable})


# --- K1 ranking and determinism -------------------------------------------------------------------------------------


def _ranking_rows() -> tuple[list[dict[str, Any]], list[str]]:
    upper_ab = "0x" + "AB" + "0" * 38
    upper_aa = "0x" + "AA" + "0" * 38
    rows = {
        "a": row(w(2), bps_m=50, bps_p=50),  # K1 50, all-time pnl 10 000
        "b": row(w(3), bps_m=80, bps_p=60, vlm_prior="3200000"),  # K1 50 (capped), all-time pnl 21 200: before a and c
        "c": row(w(1), bps_m=50, bps_p=50),  # same as a, lower address: before a
        "d": row(w(4), bps_m="49.99", bps_p=90),  # K1 49.99: below every capped row
        "e": row(w(5), bps_m=90, bps_p=30),  # K1 30: the weaker period decides
        "f": row(w(6), bps_m=12, bps_p=25),  # K1 12
        "g": row(w(7), bps_m=10, bps_p=10),  # K1 10: exactly at P7
        "h1": row(upper_ab, bps_m=40, bps_p=40),  # same K1 and pnl as h2, mixed case: compared in lower case
        "h2": row(upper_aa, bps_m=40, bps_p=40),
    }
    expected = ["b", "c", "a", "d", "h2", "h1", "e", "f", "g"]
    return list(rows.values()), [rows[name]["ethAddress"].lower() for name in expected]


def test_R3_AC1_K1_ranking_caps_the_edge_at_50_then_all_time_pnl_then_lower_case_address(tmp_path: Path) -> None:
    rows, expected = _ranking_rows()
    _, order = stage1(tmp_path, rows)
    assert order == expected


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_R3_AC1_the_list_does_not_depend_on_the_order_the_rows_are_served(tmp_path: Path, seed: int) -> None:
    rows, expected = _ranking_rows()
    random.Random(seed).shuffle(rows)
    _, order = stage1(tmp_path, rows)
    assert order == expected


def test_R3_AC1_K1_decides_before_all_time_pnl(tmp_path: Path) -> None:
    # a much richer wallet with K1 20 ranks below a poorer one with K1 21: the key is min(bps, 50) first
    rich = row(w(1), bps_m=20, bps_p=20, vlm_prior="50000000")
    poor = row(w(2), bps_m=21, bps_p=21)
    _, order = stage1(tmp_path, [rich, poor])
    assert order == [w(2), w(1)]


def test_R3_AC1_a_board_where_no_row_passes_makes_no_request_and_does_not_crash(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    r3.set_board([row(w(1), pnl_month="0"), row(w(2), av="1")])
    report = r3.cycle(60)
    assert report is not None
    assert r3.world.http.calls == []


def test_R3_AC1_stage_1_leaves_the_leaderboard_outage_rule_alone(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    r3.mw.board.outcome = board([row(w(1))], total=10)  # fewer than 1 000 rows: an outage, nobody is added
    report = r3.mw.manager.run_cycle(p95_latency_s=None)
    assert report.status == STATUS_LEADERBOARD_OUTAGE
    assert r3.world.http.calls == []


def test_R3_AC1_K1_a_huge_edge_ranks_exactly_like_50_bps_and_is_tie_broken_by_all_time_pnl(tmp_path: Path) -> None:
    # R3-SD2: pins the 50 bps cap of the K1 key. Small account (AV 10 000) rows have small all-time pnl; the lowest
    # address belongs to the huge-edge row so neither the address nor an uncapped edge may explain the order.
    huge = row(w(1), av=10_000, vlm_prior=80_000, bps_m=200, bps_p=200)  # K1 capped to 50, all-time pnl 3 200
    at_cap = row(w(2), av=10_000, vlm_prior=80_000, bps_m=50, bps_p=50)  # K1 50, all-time pnl 800
    rich = row(w(3), bps_m=50, bps_p=50)  # K1 50, all-time pnl 10 000: the pnl tie-break puts it before both
    just_below = row(w(4), bps_m="49.99", bps_p="49.99")  # K1 49.99 < cap: after every capped row despite pnl ~ 10 000
    _, order = stage1(tmp_path, [just_below, at_cap, huge, rich])
    assert order == [w(3), w(1), w(2), w(4)]
