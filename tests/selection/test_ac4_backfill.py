"""F6.AC4 [integration]: backfill first [PO].

No wallet is followed until the incremental backfill of all ``scoring.candidates_k`` candidates has completed. At
default config against a rate-budget simulator (the real F3 REST client, budget and pacing over a fake transport and
clock) it finishes within ``select.backfill_max_hours``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from copytrade.hl.errors import HlError
from copytrade.hl.models import Candle
from copytrade.core.money import Price, Qty
from copytrade.selection.backfill import Backfiller
from copytrade.selection.models import STATUS_APPLIED, STATUS_BACKFILLING
from copytrade.hl.rest import HttpResponse
from tests.hl.support import T0, Call, FeedRig, fill_json, fixture, make_feed, max_window_sum, oracle_weight, status
from tests.selection.helpers import (
    D,
    HEALTHY_OVERRIDES,
    HEALTHY_START_MS,
    HOUR,
    MINUTE,
    FakeInputs,
    alert_kinds,
    healthy_wallets,
    leaderboard_body,
    make_rig,
    w,
)

DAY = 24 * HOUR
FILLS_IN_FIXTURE = len(fixture("userFillsByTime"))


class FakeCandles:
    """CandleSource (F4 port): three 1h bars inside the requested range. Records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, int]] = []

    def fetch(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Sequence[Candle]:
        self.calls.append((coin, interval, start_ms, end_ms))
        hour = 3_600_000
        first = start_ms - start_ms % hour
        return [
            Candle(first + k * hour, first + (k + 1) * hour - 1, coin, interval, Price("100"), Price("101"),
                   Price("99"), Price("100.5"), Qty("10"), 5)
            for k in range(3)
        ]


def backfiller(**overrides: object) -> tuple[FeedRig, Backfiller, FakeCandles]:
    fr = make_feed(**overrides)
    candles = FakeCandles()
    bf = Backfiller(config=fr.rig.cfg, clock=fr.clock, rest=fr.rig.client, candles=candles)
    return fr, bf, candles


def candidates(n: int = 200) -> list[str]:
    return [w(i) for i in range(1, n + 1)]


# --- pacing ------------------------------------------------------------------------------------------------------


def test_F6_AC4_the_default_backfill_of_200_candidates_finishes_within_backfill_max_hours() -> None:
    fr, bf, _ = backfiller()
    cands = candidates(200)
    assert fr.rig.cfg["scoring.candidates_k"] == 200 and fr.rig.cfg["select.backfill_max_hours"] == 24
    assert bf.complete is False  # nothing has been set yet: fail closed
    bf.set_candidates(cands)
    assert bf.complete is False
    start = fr.clock.now_ms()
    steps = 0
    while not bf.complete:
        assert bf.step() is True
        steps += 1
        assert steps <= 400
    elapsed = fr.clock.now_ms() - start
    assert 10 * MINUTE <= elapsed <= 24 * HOUR  # the budget really paced it, and it fit the deadline
    fills_users = {c.body["user"] for c in fr.rig.http.calls if c.body["type"] == "userFillsByTime"}
    assert fills_users == set(cands)
    assert bf.step() is False  # nothing is left to fetch
    for wallet in cands:
        assert bf.inputs(wallet, fr.clock.now_ms()) is not None


def test_F6_AC4_backfill_traffic_stays_inside_the_scoring_share_of_the_budget() -> None:
    fr, bf, _ = backfiller()
    bf.set_candidates(candidates(60))
    while not bf.complete:
        assert bf.step() is True
    events = [(c.t_ms, oracle_weight(c.body["type"], 0)) for c in fr.rig.http.calls]  # the fake server holds no fills
    cap = int(fr.rig.cfg["hl.rest_weight_budget_per_min"] * D(str(fr.rig.cfg["hl.scoring_weight_share"])))
    assert max_window_sum(events) <= cap  # SCORING priority: never the whole budget


def test_F6_AC4_the_first_fetch_reaches_back_scoring_window_days() -> None:
    fr, bf, _ = backfiller()
    bf.set_candidates([w(1)])
    bf.step()
    first = next(c for c in fr.rig.http.calls if c.body["type"] == "userFillsByTime")
    assert abs(first.body["startTime"] - (T0 - 180 * DAY)) <= HOUR


# --- completion -------------------------------------------------------------------------------------------------


def test_F6_AC4_completion_needs_every_candidate_and_a_failed_wallet_is_retried_after_the_others() -> None:
    fr, bf, _ = backfiller()
    failing = {"on": True}
    bad = w(2)

    def handler(call: Call) -> HttpResponse:
        if failing["on"] and call.body.get("user") == bad:
            return status(500)
        return fr.rig.http.serve_fixtures(call)

    fr.rig.http.handler = handler
    bf.set_candidates([w(1), w(2), w(3)])
    for _ in range(10):
        bf.step()  # never raises
    assert bf.complete is False
    assert bf.inputs(bad, fr.clock.now_ms()) is None
    assert bf.inputs(w(1), fr.clock.now_ms()) is not None and bf.inputs(w(3), fr.clock.now_ms()) is not None
    failing["on"] = False
    fr.clock.advance(61_000)  # past the per-wallet error cooldown (hl.backoff_max_s) before the retry
    for _ in range(5):
        bf.step()
    assert bf.complete is True
    assert bf.inputs(bad, fr.clock.now_ms()) is not None


def test_F6_AC4_completion_is_latched_when_new_candidates_appear_later() -> None:
    fr, bf, _ = backfiller()
    bf.set_candidates([w(1), w(2)])
    while not bf.complete:
        bf.step()
    bf.set_candidates([w(1), w(2), w(3)])
    assert bf.complete is True
    assert bf.inputs(w(3), fr.clock.now_ms()) is None  # not fetched yet: the scorer will call it ineligible
    assert bf.step() is True and bf.inputs(w(3), fr.clock.now_ms()) is not None


# --- what is fetched ---------------------------------------------------------------------------------------------


def test_F6_AC4_fills_portfolio_state_role_and_candles_are_fetched_and_converted() -> None:
    fr, bf, candles = backfiller()
    fr.server_fills.extend(fixture("userFillsByTime"))
    bf.set_candidates([w(1)])
    bf.step()
    got = bf.inputs(w(1), T0)
    assert got is not None and got.address == w(1)
    assert len(got.fills) == FILLS_IN_FIXTURE and len({f.tid for f in got.fills}) == FILLS_IN_FIXTURE
    assert got.role == "user"
    assert len(got.portfolios) == 1 and len(got.portfolios[0].windows) > 0
    assert len(got.clearinghouse) == 1 and isinstance(got.clearinghouse[0].account_value, D)
    assert got.fills_fetched_ms is not None and got.candles_fetched_ms is not None
    assert {c[0] for c in candles.calls} <= {f.coin for f in got.fills}  # candles only for coins the wallet traded
    assert {c[1] for c in candles.calls} == {"1h"} and candles.calls
    wire = {f["tid"]: f for f in fixture("userFillsByTime")}
    for f in got.fills:
        assert f.px == D(wire[f.tid]["px"]) and f.sz == D(wire[f.tid]["sz"])  # exact Decimals, no float


def test_F6_AC4_a_liquidation_fill_is_flagged_for_the_scorer() -> None:
    fr, bf, _ = backfiller()
    fr.server_fills.extend([fill_json(1, dir="Liquidated Cross Long"), fill_json(2)])
    bf.set_candidates([w(1)])
    bf.step()
    got = bf.inputs(w(1), T0)
    assert got is not None
    assert {f.tid: f.liquidation for f in got.fills} == {1: True, 2: False}


def test_F6_AC4_a_later_fetch_is_incremental_and_never_duplicates_fills() -> None:
    fr, bf, _ = backfiller()
    fr.server_fills.extend(fixture("userFillsByTime"))
    bf.set_candidates([w(1)])
    bf.step()
    first_start = next(c for c in fr.rig.http.calls if c.body["type"] == "userFillsByTime").body["startTime"]
    last_fill = max(f["time"] for f in fixture("userFillsByTime"))
    fr.server_fills.append(fill_json(500, time_ms=last_fill + 10_000))
    n_calls = len([c for c in fr.rig.http.calls if c.body["type"] == "userFillsByTime"])
    bf.refresh(w(1))
    later = [c for c in fr.rig.http.calls if c.body["type"] == "userFillsByTime"][n_calls:]
    assert later and first_start < later[0].body["startTime"] <= last_fill + 1  # from the last fill held, not the window
    got = bf.inputs(w(1), T0)
    assert got is not None
    tids = [f.tid for f in got.fills]
    assert len(tids) == len(set(tids)) == FILLS_IN_FIXTURE + 1 and 500 in tids


def test_F6_AC4_a_failed_refresh_keeps_the_old_data_and_raises() -> None:
    fr, bf, _ = backfiller()
    bf.set_candidates([w(1)])
    bf.step()
    before = bf.inputs(w(1), T0)
    fr.rig.http.handler = lambda call: status(500)
    try:
        bf.refresh(w(1))
    except HlError:
        pass
    else:
        raise AssertionError("a failed refresh must not be swallowed")
    assert bf.inputs(w(1), T0) == before


# --- the gate in the manager --------------------------------------------------------------------------------------


def test_F6_AC4_no_wallet_is_followed_until_the_backfill_completes(tmp_path: Path) -> None:
    eight = [w(i) for i in range(1, 9)]
    provider = FakeInputs(healthy_wallets(8), complete=False)
    rig = make_rig(tmp_path, inputs=provider, start_ms=HEALTHY_START_MS, **HEALTHY_OVERRIDES)
    rig.board.outcome = leaderboard_body(1000, first=eight)
    try:
        for _ in range(3):  # eligible wallets are there, and were even scored before, but the backfill is not done
            report = rig.manager.run_cycle(p95_latency_s=D(3))
            assert report.status == STATUS_BACKFILLING and report.followed == ()
        assert rig.manager.followed == frozenset() and rig.spy.log == []
        assert provider.candidates == [w(i) for i in range(1, 9)] + [w(1_000_000 + k) for k in range(192)]
        provider.complete = True
        first = rig.manager.run_cycle(p95_latency_s=D(3))
        assert first.status == STATUS_APPLIED and first.decisions == () and first.eligible_count == 8
        second = rig.manager.run_cycle(p95_latency_s=D(3))
        assert second.followed == tuple(sorted(eight)) and rig.manager.followed == frozenset(eight)
        assert [r["status"] for r in rig.records("select_cycle")] == [STATUS_BACKFILLING] * 3 + [STATUS_APPLIED] * 2
        assert len(rig.store.cycles) == 2  # F5 persisted each applied cycle exactly once
        assert alert_kinds(rig.alerts) == []
    finally:
        rig.ledger.close()
