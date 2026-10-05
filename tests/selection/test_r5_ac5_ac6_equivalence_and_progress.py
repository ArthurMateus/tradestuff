"""R5.AC5 and R5.AC6 [integration].

AC5, equivalence guard: a wallet backfilled with fast responses ends with EXACTLY the WalletInputs of today's single-step
result. The expectation is built here, independently of the backfiller: fills / portfolio / clearinghouse / role are
what the real REST client parses from the fake server, converted by the documented mapping; the candles are every 1h
bar of the window the fake exchange holds (the open of the first bar at or after ``now - scoring.window_days``, to the
bar of the current hour), each with the figures the server serves. A backfill that is resumed over many steps, with a
failure in the middle, ends with the same data (only the fetch stamps may differ: they say when).

AC6, progress line accuracy: ``backfill progress`` counts a wallet as done only when ALL its calls are complete, i.e. when
its inputs exist. Two wallets, every response 0.5 s, a progress line before each step (the clock moves 61 s between steps).
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal

import pytest

from copytrade.hl.budget import Priority
from copytrade.scoring import models as sc
from tests.hl.support import T0, status
from tests.selection.helpers import w
from tests.selection.r5_world import DAY, HOUR, R5World, expected_opens, make_r5

A, B = w(1), w(2)
PROGRESS = re.compile(r"backfill progress: done=(\d+) of (\d+) candidates")
PASS_DONE = re.compile(r"backfill pass complete: done=(\d+) of (\d+) candidates")


def expected_inputs(r: R5World, wallet: str, coins: list[str], *, stamp: int) -> sc.WalletInputs:
    cfg = r.world.cfg
    window_ms = cfg["scoring.window_days"] * DAY
    client = r.world.client
    raw_fills = client.user_fills_by_time(wallet, stamp - window_ms, None, priority=Priority.SCORING)
    fills = tuple(
        sorted(
            (
                sc.Fill(
                    tid=f.tid, time=f.time_ms, coin=f.coin, side=f.side, sz=Decimal(f.sz), px=Decimal(f.px),
                    start_position=Decimal(f.start_position), closed_pnl=Decimal(f.closed_pnl), fee=Decimal(f.fee),
                    crossed=f.crossed, liquidation=f.liquidation or "iquidat" in f.dir,
                )
                for f in raw_fills
                if f.time_ms >= stamp - window_ms
            ),
            key=lambda f: (f.time, f.tid),
        )
    )  # fmt: skip
    portfolio = sc.PortfolioSnapshot(
        fetched_ms=stamp,
        windows={
            name: sc.PortfolioWindow(
                account_value_history=tuple((ms, Decimal(v)) for ms, v in win.account_value_history),
                pnl_history=tuple((ms, Decimal(v)) for ms, v in win.pnl_history),
            )
            for name, win in client.portfolio(wallet, priority=Priority.SCORING).items()
        },
    )
    state = client.clearinghouse_state(wallet, priority=Priority.SCORING)
    clearinghouse = sc.ClearinghouseState(
        fetched_ms=stamp,
        account_value=Decimal(state.account_value),
        positions=tuple(
            sc.OpenPosition(coin=p.coin, unrealized_pnl=Decimal(p.unrealized_pnl or "0")) for p in state.positions
        ),
    )
    bars = tuple(
        sc.Candle(
            open_ms=t, close_ms=t + HOUR - 1, o=Decimal("100.0"), hi=Decimal("101.0"), lo=Decimal("99.0"),
            c=Decimal("100.5"),
        )
        for t in expected_opens(stamp, cfg["scoring.window_days"])
    )  # fmt: skip
    return sc.WalletInputs(
        address=wallet, fills=fills, fills_fetched_ms=stamp, funding=(), portfolios=(portfolio,),
        clearinghouse=(clearinghouse,), own_snapshots=(), candles_1h={coin: bars for coin in sorted(coins)},
        candles_fetched_ms=stamp, role=client.user_role(wallet, priority=Priority.SCORING), leaderboard_row=None,
    )  # fmt: skip


def test_R5_AC5_a_wallet_backfilled_with_fast_responses_ends_with_the_single_step_golden_inputs() -> None:
    r = make_r5(latency=0.0)
    r.serve_wallet(A, ["BTC", "ETH"])
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=40)
    got = r.backfiller.inputs(A, T0)
    assert got is not None
    assert got == expected_inputs(r, A, ["BTC", "ETH"], stamp=T0)


def test_R5_AC5_a_small_wallet_has_every_bar_once_and_every_fill_once() -> None:
    r = make_r5(latency=0.0)
    r.serve_wallet(A, ["BTC"], trips=5)
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=40)
    got = r.backfiller.inputs(A, T0)
    assert got is not None
    assert [b.open_ms for b in got.candles_1h["BTC"]] == expected_opens(T0)
    assert len({f.tid for f in got.fills}) == len(got.fills) == 10


def test_R5_AC5_a_resumed_backfill_with_a_failure_in_the_middle_ends_with_the_same_data() -> None:
    r = make_r5(latency=0.5)
    r.serve_wallet(A, ["BTC", "ETH"])
    failures = {"n": 0}

    def flaky(call):  # type: ignore[no-untyped-def]
        failures["n"] += 1
        return status(500) if failures["n"] == 1 else None

    r.world.hl.rules[(A, "clearinghouseState")] = flaky
    r.backfiller.set_candidates([A])
    r.run([A], max_steps=60)
    got = r.backfiller.inputs(A, T0)
    assert got is not None
    r.http.latency = lambda _call: 0.0  # the reference reads need no time
    want = expected_inputs(r, A, ["BTC", "ETH"], stamp=r.clock.now_ms())
    assert got.fills == want.fills
    assert got.role == want.role
    assert dict(got.candles_1h) == dict(want.candles_1h)
    (portfolio,), (state,) = got.portfolios, got.clearinghouse
    assert portfolio.windows == want.portfolios[0].windows
    assert (state.account_value, state.positions) == (
        want.clearinghouse[0].account_value,
        want.clearinghouse[0].positions,
    )
    assert got.funding == () and got.own_snapshots == () and got.leaderboard_row is None


def progress_lines(caplog: pytest.LogCaptureFixture, since: int) -> list[tuple[int, int]]:
    out = []
    for rec in caplog.records[since:]:
        match = PROGRESS.search(rec.getMessage())
        if match is not None:
            out.append((int(match.group(1)), int(match.group(2))))
    return out


def test_R5_AC6_a_wallet_counts_as_done_only_when_all_its_calls_are_complete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r = make_r5(latency=0.5)
    r.serve_wallet(A, ["BTC", "ETH"])
    r.serve_wallet(B, ["BTC"])
    r.backfiller.set_candidates([A, B])
    partial_seen = False
    with caplog.at_level(logging.INFO):
        for _ in range(60):
            held = sum(r.backfiller.inputs(wallet, T0) is not None for wallet in (A, B))
            began = {wallet: bool(r.http.of("portfolio", wallet, outcome="ok")) for wallet in (A, B)}
            partial_seen |= any(began[wallet] and r.backfiller.inputs(wallet, T0) is None for wallet in (A, B))
            mark = len(caplog.records)
            r.iteration()
            for done, total in progress_lines(caplog, mark):
                assert done == held, f"the line says done={done} while {held} wallets have all their calls complete"
                assert total == 2
            if held == 2 or all(r.backfiller.inputs(wallet, T0) is not None for wallet in (A, B)):
                break
            r.world.tick(61)
        else:
            raise AssertionError("the two wallets did not complete in 60 steps")
    assert partial_seen, "the scenario must show a wallet with some calls done and others pending"
    closing = [PASS_DONE.search(rec.getMessage()) for rec in caplog.records]
    assert any(m is not None and (m.group(1), m.group(2)) == ("2", "2") for m in closing)
