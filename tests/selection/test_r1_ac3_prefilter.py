"""R1.AC3 [integration]: candidates are prefiltered on leaderboard row data before any backfill request.

What the existing gates can decide from a leaderboard row alone (see the test plan): G11 ``gate.min_account_value_usd``
(row ``accountValue``) and the address half of G13 (``gate.exclude_addresses``). Everything else (G1-G10, G12, G14,
G15, the role half of G13) needs fills, portfolio, state or ``userRole`` and cannot run here: not pinned, no new rule.

Pinned decisions: the prefilter applies to ALL leaderboard rows in the order served and ``scoring.candidates_k`` then
takes the first k survivors (so prefiltered rows do not shrink the candidate set); a row whose ``accountValue`` is
missing or unreadable is KEPT (the row cannot decide, the scorer's own gate will); the threshold is inclusive like
G11 (exactly the minimum is kept). A prefiltered wallet receives no request of any kind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.selection.helpers import w
from tests.selection.r1_world import board_body, make_manager_world

EXCLUDED = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"
K = 50  # scoring.candidates_k floor


def run(tmp_path: Path, rows: list[tuple[str, str | None]], **overrides: object) -> tuple[set[str], set[str], Any]:
    mw = make_manager_world(tmp_path, fail_fast=False, **overrides)
    mw.board.outcome = board_body(rows)
    mw.manager.run_cycle(p95_latency_s=None)
    mw.work_until_complete(max_ticks=400)
    users = {c.body["user"] for c in mw.world.http.calls if "user" in c.body}
    fetched = {c.body["user"] for c in mw.world.fills_calls()}
    return users, fetched, mw


def filler(n: int) -> list[str]:
    return [w(1_000_000 + i) for i in range(n)]


def test_R1_AC3_wallets_below_the_minimum_account_value_get_no_request(tmp_path: Path) -> None:
    small, poor2 = w(1), w(2)
    users, fetched, mw = run(tmp_path, [(small, "120.5"), (poor2, "0"), (w(3), "50000.0")])
    assert mw.world.cfg["gate.min_account_value_usd"] == 10000
    assert small not in users and poor2 not in users
    assert w(3) in fetched


def test_R1_AC3_the_minimum_is_inclusive_one_cent_below_is_dropped_one_above_kept(tmp_path: Path) -> None:
    below, exact, above = w(1), w(2), w(3)
    users, fetched, _ = run(tmp_path, [(below, "9999.99"), (exact, "10000.00"), (above, "10000.01")])
    assert below not in users
    assert exact in fetched and above in fetched


def test_R1_AC3_the_threshold_is_read_from_config(tmp_path: Path) -> None:
    mid = w(1)
    users, _, _ = run(tmp_path, [(mid, "20000.0")], gate__min_account_value_usd=50000)
    assert mid not in users
    _, fetched2, _ = run(tmp_path / "b", [(mid, "20000.0")], gate__min_account_value_usd=15000)
    assert mid in fetched2


def test_R1_AC3_an_excluded_address_gets_no_request(tmp_path: Path) -> None:
    users, _, mw = run(tmp_path, [(EXCLUDED, "90000.0"), (w(3), "50000.0")])
    assert EXCLUDED in mw.world.cfg["gate.exclude_addresses"]
    assert EXCLUDED not in users


def test_R1_AC3_a_row_without_a_readable_account_value_is_kept(tmp_path: Path) -> None:
    no_field, junk, empty = w(1), w(2), w(3)
    users, fetched, _ = run(tmp_path, [(no_field, None), (junk, "n/a"), (empty, "")])
    assert {no_field, junk, empty} <= fetched  # cannot decide from the row: the scorer decides


def test_R1_AC3_candidates_k_takes_the_first_k_survivors_in_served_order(tmp_path: Path) -> None:
    rows = [(w(1), "5.0"), (EXCLUDED, "90000.0"), (w(3), "9999.99"), (w(4), "10000.0"), (w(5), None)]
    expected = [w(4), w(5), *filler(K - 2)]
    _, fetched, mw = run(tmp_path, rows, scoring__candidates_k=K)
    assert mw.world.cfg["scoring.candidates_k"] == K
    assert fetched == set(expected)  # exactly K wallets, the filtered rows did not eat into K


def test_R1_AC3_nobody_prefiltered_ever_reaches_the_follow_set(tmp_path: Path) -> None:
    _, _, mw = run(tmp_path, [(w(1), "5.0"), (w(2), "50000.0")])
    for _ in range(3):
        report = mw.manager.run_cycle(p95_latency_s=None)
        assert w(1) not in report.followed
