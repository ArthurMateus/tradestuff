"""R0.AC11 (entry-policy stand-in) and R0.AC12 (wiring: one shared gate lock, the bot as AlertSink, poll and flush on
dedicated threads, trade posts on a timer, flatten re-run, exchange-time equity marks, nothing wired before reload)."""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert
from copytrade.runner.runner import FLATTEN_RERUN_INTERVAL_S
from tests.hl.ws_server import wait_for
from tests.positions.helpers import make_signal
from tests.runner.fake_hl import fill_json
from tests.runner.world import ALERTS_CHAT, LEADER, LEADER_B, OWNER, PIN, T0, World

SETTLE_S = 0.3


def settle(seconds: float = SETTLE_S) -> None:
    threading.Event().wait(seconds)  # a bounded real-time wait for a NEGATIVE assertion about another thread


# ------------------------------------------------------------------------------------------------ AC11


def test_R0_AC11_the_stand_in_allows_a_followed_leaders_open_at_multiplier_one(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.step(runner, 3)
    mult = runner.policy.vol_mult(make_signal(1, ActionKind.OPEN, wallet=LEADER, ts=world.exchange_ms()))
    assert mult == Decimal(1) and isinstance(mult, Decimal)


@pytest.mark.parametrize("coin", ["SOL", "BTC", "ETH", "DOGE"])
@pytest.mark.parametrize("is_long", [True, False])
def test_R0_AC11_the_stand_in_never_returns_anything_but_one_or_a_veto(new_world: Any, coin: str, is_long: bool) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.step(runner, 3)
    for wallet in (LEADER, LEADER_B):
        got = runner.policy.vol_mult(make_signal(5, ActionKind.OPEN, wallet=wallet, coin=coin, is_long=is_long))
        assert got is None or got == Decimal(1)


def test_R0_AC11_an_unfollowed_leader_is_vetoed_through_the_follow_manager(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.step(runner, 3)
    assert runner.policy.vol_mult(make_signal(1, ActionKind.OPEN, wallet=LEADER_B)) is None


def test_R0_AC11_a_stale_user_feed_is_vetoed(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.subscribe_ready(runner)
    assert runner.policy.vol_mult(make_signal(1, ActionKind.OPEN, wallet=LEADER)) == Decimal(1)
    world.clock.advance(31_000)  # feed.stale_after_s is 30 and nothing was ticked
    assert runner.policy.vol_mult(make_signal(2, ActionKind.OPEN, wallet=LEADER)) is None


def test_R0_AC11_a_stopping_runner_vetoes_every_entry(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.step(runner, 3)
    runner.request_stop("test")
    assert runner.policy.vol_mult(make_signal(1, ActionKind.OPEN, wallet=LEADER)) is None


def test_R0_AC11_a_leader_open_end_to_end_opens_a_paper_position_with_a_stop(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.leader_open(runner)
    position = runner.broker.position("SOL")
    assert position is not None and position.qty > 0
    assert [s.kind for s in runner.broker.stops()].count("sl") == 1
    assert [d.payload["approved"] for d in world.records("risk_decision")][0] is True


# ------------------------------------------------------------------------------------------------ AC12


def test_R0_AC12_nothing_is_wired_to_the_broker_before_start_and_step_before_start_is_refused(
    new_world: Any, network_guard: Any
) -> None:
    world: World = new_world()
    world.seed_follow()
    first, _ = world.start()
    world.leader_open(first)
    first.stop()
    n_before = len(world.records())
    connects = len(network_guard.all_connects)
    runner = world.build()
    assert runner.broker.positions() == () and runner.broker.stops() == ()  # not restored yet
    assert len(world.records()) == n_before  # the build wrote nothing
    assert len(network_guard.all_connects) == connects  # and opened no connection
    with pytest.raises(RuntimeError):
        runner.step()
    runner.start()
    assert runner.broker.position("SOL") is not None


def test_R0_AC12_one_gate_lock_is_shared_by_the_loop_and_the_bot(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    world.step(runner, 3)
    world.telegram_ready()
    lock = runner.gate_lock
    assert isinstance(lock, type(threading.RLock()))
    with lock:
        world.tg.push_text("/pause")  # the bot's poll thread takes the same lock to pause
        stepper = threading.Thread(target=lambda: world.step(runner, 1))
        before = runner.last_advanced_ms
        stepper.start()
        stepper.join(timeout=SETTLE_S)
        assert stepper.is_alive(), "the trading loop must wait for the shared lock"
        assert runner.last_advanced_ms == before and not runner.gate.paused
    stepper.join(timeout=10)
    wait_for(lambda: runner.gate.paused, what="the /pause command, run under the shared lock")
    assert not stepper.is_alive()


def test_R0_AC12_the_bot_is_the_alert_sink_of_the_components(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.subscribe_ready(runner)
    # F7 (detector): an unparseable fill raises an alert; F1 clock: see the time-base tests; F4: see the disk tests
    world.hl.push_user_fills(
        LEADER,
        [fill_json(9, coin="SOL", side="B", sz="1.0", px="100.0", direction="Open Sideways", time_ms=world.exchange_ms() - 50)],
    )
    world.step(runner, 10, ms=200)
    wait_for(lambda: any("unparseable_fill" in t for t in world.tg.sent(ALERTS_CHAT)), what="the detector alert")


def test_R0_AC12_poll_and_flush_run_on_dedicated_threads_so_a_hanging_telegram_never_stalls_the_loop(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    names = {t.name for t in runner.threads if t.is_alive()}
    assert {"r0-telegram-poll", "r0-telegram-flush", "r0-watchdog"} <= names
    assert threading.current_thread() not in runner.threads
    world.tg.mode = "hang"  # every Telegram call now blocks until its timeout
    runner.bot.send(Alert("probe", "queued while hanging"))
    started = time.monotonic()
    report = world.step(runner, 5)
    assert time.monotonic() - started < 3.0  # api timeout alone is 5 s: the trading thread made no Telegram call
    assert report.skipped is None and runner.last_advanced_ms is not None


def test_R0_AC12_trade_posts_are_synced_on_a_timer_without_any_command(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.leader_open(runner)
    world.step(runner, 5)
    wait_for(lambda: any("SOL" in t for t in world.tg.sent(OWNER)), what="the trade post on the control chat")
    assert world.tg.calls("getUpdates")  # polling ran, but nobody sent a command


def test_R0_AC12_flatten_is_rerun_with_new_run_ids_while_entries_are_in_flight_then_everything_is_closed(
    new_world: Any,
) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.subscribe_ready(runner)
    world.hl.leader_positions[LEADER.lower()] = [("SOL", "5.0", "100.0")]
    world.hl.push_user_fills(
        LEADER,
        [fill_json(1, coin="SOL", side="B", sz="5.0", px="100.0", direction="Open Long", time_ms=world.exchange_ms() - 100)],
    )
    for _ in range(10):  # the entry is accepted but no book can fill it yet: in flight
        world.step(runner, 1, ms=50, pump=False)
        if runner.broker.pending_entries():
            break
    assert runner.broker.pending_entries()
    world.telegram_ready()
    world.tg.push_text(f"/flatten {PIN}")
    wait_for(lambda: runner.flatten_runs, what="the bot's flatten")
    assert runner.gate.paused  # flatten pauses first
    world.step(runner, 2, ms=1000)  # books arrive: the entry fills (a position the first flatten could not close)
    world.run_until(runner, lambda: len(runner.flatten_runs) >= 2, ms=FLATTEN_RERUN_INTERVAL_S * 1000)
    world.run_until(runner, lambda: runner.broker.positions() == (), ms=1000)
    assert len(set(runner.flatten_runs)) == len(runner.flatten_runs)  # a new run id each time
    assert runner.gate.paused
    assert not [r for r in world.records("risk_decision") if r.payload["reason"] == "duplicate_order"]


def test_R0_AC12_equity_marks_keep_entries_allowed_over_a_long_quiet_run(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.step(runner, 12, ms=30_000)  # six minutes of exchange time: eval.mark_interval_s is 60
    world.leader_open(runner)
    reasons = [r.payload["reason"] for r in world.records("risk_decision")]
    assert "equity_mark_stale" not in reasons and "bad_decision_time" not in reasons
    assert runner.broker.position("SOL") is not None


def test_R0_AC12_the_market_feed_is_polled_by_the_recorder_and_books_reach_the_broker(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.step(runner, 5)
    wait_for(lambda: {"SOL"} <= {s.get("coin") for s in world.hl.subscribed("l2Book")}, what="the l2Book subscription")
    assert world.hl.subscribed("allMids")
    assert runner.hub.first_book_at_or_after("SOL", T0) is not None
