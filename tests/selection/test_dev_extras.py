"""Developer tests for behaviour the designer's suite leaves open (F6 implementation decisions).

Real code throughout; only the boundaries are faked, as in the rest of ``tests/selection``.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import Any

from copytrade.core.domain import ActionKind
from copytrade.hl.errors import HlSchemaError
from copytrade.hl.schema import parse_response
from copytrade.selection.models import (
    DECISION_DEFERRED,
    REASON_STATE_UNAVAILABLE,
    STATUS_APPLIED,
    STATUS_LEADERBOARD_OUTAGE,
)
from tests.hl.support import T0, fill_json, fixture
from tests.selection.helpers import (
    D,
    HOUR,
    MINUTE,
    NOW,
    cycle,
    established,
    join_all,
    make_rig,
    ranked,
    score,
    w,
)
from tests.selection.test_ac4_backfill import backfiller, one_fill

# --- F3 extension: the exchange's unrealised P&L reaches the position ---------------------------------------------


def test_F6_clearinghouse_positions_carry_the_reported_unrealized_pnl() -> None:
    state = parse_response("clearinghouseState", fixture("clearinghouseState"))
    assert [p.unrealized_pnl for p in state.positions] == [D("-61.75")]


def test_F6_a_position_without_unrealized_pnl_parses_with_none() -> None:
    payload = copy.deepcopy(fixture("clearinghouseState"))
    del payload["assetPositions"][0]["position"]["unrealizedPnl"]
    assert parse_response("clearinghouseState", payload).positions[0].unrealized_pnl is None


# --- Backfiller ----------------------------------------------------------------------------------------------------


def test_F6_backfill_carries_the_unrealized_pnl_of_open_positions_into_the_scoring_state() -> None:
    fr, bf, _ = backfiller()
    one_fill(fr)  # R3: a wallet without a fill in the window is dropped after one request
    bf.set_candidates([w(1)])
    bf.step()
    got = bf.inputs(w(1), T0)
    assert got is not None
    assert [(p.coin, p.unrealized_pnl) for p in got.clearinghouse[0].positions] == [("BTC", D("-61.75"))]
    assert got.clearinghouse[0].account_value == D("125000.55")


def test_F6_backfill_refuses_a_state_with_an_unknown_unrealized_pnl_and_leaves_the_wallet_undone() -> None:
    fr, bf, _ = backfiller()
    one_fill(fr)  # R3: a wallet without a fill in the window is dropped after one request
    payload = copy.deepcopy(fixture("clearinghouseState"))
    del payload["assetPositions"][0]["position"]["unrealizedPnl"]
    fr.rig.http.overrides["clearinghouseState"] = lambda call: payload
    bf.set_candidates([w(1)])
    assert bf.step() is True
    assert bf.complete is False and bf.inputs(w(1), T0) is None
    fr.clock.advance(61_000)  # past the per-wallet error cooldown (hl.backoff_max_s): the refresh really asks again
    try:
        bf.refresh(w(1))
    except HlSchemaError:
        pass
    else:
        raise AssertionError("a state without unrealizedPnl must be refused, not guessed")
    assert bf.complete is False


def test_F6_backfill_pages_userFillsByTime_until_the_present() -> None:
    fr, bf, _ = backfiller()
    base = T0 - 10 * 24 * HOUR
    # one a minute: page 1 spans more than a day (R3 first-page exit)
    fr.server_fills.extend(fill_json(i, time_ms=base + i * 60_000) for i in range(1, 4501))
    pages: list[int] = []

    def capped(call: Any) -> Any:
        lo = call.body["startTime"]
        page = sorted((f for f in fr.server_fills if f["time"] >= lo), key=lambda f: f["time"])[:2000]
        pages.append(len(page))
        return page

    fr.rig.http.overrides["userFillsByTime"] = capped
    bf.set_candidates([w(1)])
    bf.step()
    got = bf.inputs(w(1), T0)
    assert got is not None and len(got.fills) == 4500
    assert pages == [2000, 2000, 502]  # the cursor repeats the last millisecond: the boundary fill comes twice
    assert got.fills_fetched_ms is not None


def test_F6_backfill_that_cannot_reach_the_present_leaves_the_wallet_stale() -> None:
    fr, bf, _ = backfiller()
    same_ms = T0 - HOUR
    # R3: page 1 must span more than a day (else the first-page exit drops the wallet): one old fill + 2 000 in one ms
    fr.server_fills.append(fill_json(1, time_ms=T0 - 2 * 24 * HOUR))
    fr.server_fills.extend(fill_json(i, time_ms=same_ms) for i in range(2, 2002))
    fr.rig.http.overrides["userFillsByTime"] = lambda call: [f for f in fr.server_fills if f["time"] >= call.body["startTime"]]
    bf.set_candidates([w(1)])
    bf.step()
    got = bf.inputs(w(1), T0)
    assert got is not None and len(got.fills) == 2001  # 2 000 + the old one
    assert got.fills_fetched_ms is None  # the scorer will call it stale_input: never scored on a partial history


def test_F6_candles_are_fetched_once_per_coin_and_hour_and_shared_between_wallets() -> None:
    fr, bf, candles = backfiller()
    fr.server_fills.extend(fixture("userFillsByTime"))
    bf.set_candidates([w(1), w(2)])
    bf.step()
    calls_after_first = len(candles.calls)
    bf.step()
    assert calls_after_first > 0 and len(candles.calls) == calls_after_first  # the second wallet reused the bars
    first, second = bf.inputs(w(1), T0), bf.inputs(w(2), T0)
    assert first is not None and second is not None and first.candles_1h == second.candles_1h
    fr.clock.advance(HOUR)
    bf.refresh(w(1))
    assert len(candles.calls) > calls_after_first  # a new UTC hour: the bars are fetched again
    refreshed = bf.inputs(w(1), T0)
    assert refreshed is not None and refreshed.candles_fetched_ms == fr.clock.now_ms()


def test_F6_the_role_is_requested_once_per_wallet() -> None:
    fr, bf, _ = backfiller()
    one_fill(fr)  # R3: a wallet without a fill in the window is dropped after one request
    bf.set_candidates([w(1)])
    bf.step()
    bf.refresh(w(1))
    roles = [c for c in fr.rig.http.calls if c.body["type"] == "userRole"]
    assert len(roles) == 1


# --- FollowManager -------------------------------------------------------------------------------------------------


def test_F6_a_state_that_cannot_be_fetched_is_ledgered_as_a_deferral(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    try:
        rig.states.fail = {w(1)}
        reports = [rig.manager.apply_cycle(cycle(ranked(1, 2), NOW + i * MINUTE), now_ms=NOW + i * MINUTE) for i in range(2)]
        deferred = [d for d in reports[1].decisions if d.kind == DECISION_DEFERRED]
        assert [(d.wallet, d.reason) for d in deferred] == [(w(1), REASON_STATE_UNAVAILABLE)]
        assert [(r["wallet"], r["reason"]) for r in rig.records("follow_deferred")] == [(w(1), REASON_STATE_UNAVAILABLE)]
        assert rig.manager.followed == frozenset({w(2)})
    finally:
        rig.ledger.close()


def test_F6_a_paused_wallet_stays_held_for_its_shares_and_is_ledgered(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    try:
        t = join_all(rig, (1, 2, 3))
        rig.shares.open = {w(1)}
        for _ in range(5):
            rig.manager.on_copy_closed(w(1), pnl_usd=D(-1), equity_usd=D(10_000))
        assert w(1) in rig.manager.subscribed and w(1) not in rig.manager.followed
        assert [r["wallet"] for r in rig.records("leader_paused")] == [w(1)]
        for k in (1, 2):
            rig.manager.apply_cycle(cycle(ranked(1, 2, 3), t + k * MINUTE), now_ms=t + k * MINUTE)
        assert w(1) not in rig.manager.followed and w(1) in rig.manager.subscribed
    finally:
        rig.ledger.close()


def test_F6_a_rank_dropped_wallet_held_for_its_shares_rejoins_without_new_feed_calls(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    try:
        t = join_all(rig, (1, 2, 3)) + 30 * HOUR
        rig.shares.open = {w(1)}
        for k in range(2):
            rig.manager.apply_cycle(cycle([score(2, 1), score(3, 2), score(1, 16)], t + k * MINUTE), now_ms=t + k * MINUTE)
        assert w(1) not in rig.manager.followed and w(1) in rig.manager.subscribed
        calls = [c for c in rig.spy.log if c[1] == w(1)]
        for k in (2, 3):
            rig.manager.apply_cycle(cycle(ranked(1, 2, 3), t + k * MINUTE), now_ms=t + k * MINUTE)
        assert w(1) in rig.manager.followed
        assert [c for c in rig.spy.log if c[1] == w(1)] == calls
        assert rig.manager.refusal_reason(w(1), ActionKind.OPEN) is None
    finally:
        rig.ledger.close()


def test_F6_a_refresh_failure_scores_the_wallet_on_what_is_held_and_the_cycle_goes_on(tmp_path: Path) -> None:
    rig = established(tmp_path, n=3)
    try:
        failing = w(2)
        original = rig.inputs.refresh

        def refresh(wallet: str) -> None:
            if wallet == failing:
                raise OSError("fetch failed")
            original(wallet)

        rig.inputs.refresh = refresh  # type: ignore[method-assign]
        rig.store.cycles.clear()
        report = rig.manager.run_cycle(p95_latency_s=D(3))
        assert report.status == STATUS_APPLIED and report.eligible_count == 3
        assert {s.address for s in rig.store.cycles[0].scores} >= {w(1), w(2), w(3)}
    finally:
        rig.ledger.close()


def test_F6_a_blowup_flag_still_drops_a_followed_wallet_during_a_leaderboard_outage(tmp_path: Path) -> None:
    rig = established(tmp_path, n=3)
    try:
        liquidated = rig.inputs.wallets[w(1)]
        fills = (*liquidated.fills[:-1], replace(liquidated.fills[-1], liquidation=True))  # BU6
        rig.inputs.wallets[w(1)] = replace(liquidated, fills=fills)
        rig.board.outcome = OSError("down")
        report = rig.manager.run_cycle(p95_latency_s=D(3))
        assert report.status == STATUS_LEADERBOARD_OUTAGE
        assert [(d.kind, d.wallet) for d in report.decisions] == [("safety_drop", w(1))]
        assert rig.manager.followed == frozenset({w(2), w(3)})
        assert rig.manager.refusal_reason(w(1), ActionKind.OPEN) == "leader_paused"
        assert w(1) not in rig.manager.subscribed
    finally:
        rig.ledger.close()


def test_F6_a_bare_cycle_with_no_data_drops_nobody_early_and_follows_nobody(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    try:
        t = join_all(rig, (1, 2, 3))
        report = rig.manager.apply_cycle(cycle([score(9, 1)], t + MINUTE), now_ms=t + MINUTE)
        assert report.decisions == () and rig.manager.followed == frozenset({w(1), w(2), w(3)})
    finally:
        rig.ledger.close()
