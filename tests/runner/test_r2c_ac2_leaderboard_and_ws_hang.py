"""R2c.AC2 (R2-V2-2, blocking; ``loop_stalled`` not closed): the two trading-thread network calls OUTSIDE the REST budget.

* the follow cycle fetches the leaderboard (``HttpLeaderboardSource.fetch``, 3 x ``hl.rest_timeout_s`` = 30 s in the shipped
  config, reached via ``runner._selection -> follow.run_cycle -> selection/manager.py``);
* ``hub_tap.drain`` and ``feed.tick`` call ``connector.connect()`` (``hl.ws_connect_timeout_s`` = 10 s each).

Worst case about 50 s of one iteration, past the 30 s stall threshold, a position with a triggered stop unattended.

Mechanism-agnostic observable (the developer may move the calls off the thread or bound them under the per-iteration
budget, no new config key): the real duration of ``Runner.step`` stays under 3 s (as R2b.AC3), the stop still fills, no
``loop_stalled`` alert in 60 s of loop time, and ``/flatten`` does not wait on ``gate_lock`` for the hanging calls.

The WebSocket side is a loopback proxy in front of the fake Hyperliquid that can switch to ``hold`` (accepts TCP, never
answers the handshake: the pattern of ``tests/hl/test_w0_connector``). Real sockets, real runner.
"""

from __future__ import annotations

import dataclasses
import socket
import threading
import time
from typing import Any
from urllib.parse import urlparse

import pytest

from tests.runner.r2_support import SleepLog, drive, wait_real
from tests.runner.scenarios import PIN, set_mid_below_stop
from tests.runner.test_dev_e2e import small_leader
from tests.runner.world import World

LOOP_BOUND_S = 3.0
HEARTBEAT_LOOP_S = 60
LEADERBOARD_HANG_S = 60.0  # longer than the client's 30 s deadline: the GET never answers


class SwitchProxy:
    """TCP proxy to the fake exchange's WebSocket port. ``forward`` pipes bytes; ``hold`` accepts the connection and then
    never reads or writes (the handshake never completes). ``held`` counts the connections taken in ``hold`` mode."""

    def __init__(self, upstream_port: int) -> None:
        self._upstream_port = upstream_port
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(16)
        self.url = f"ws://127.0.0.1:{self._listener.getsockname()[1]}/ws"
        self.hold = False
        self.held = 0
        self._socks: list[socket.socket] = []
        self._lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                client, _ = self._listener.accept()
            except OSError:
                return
            with self._lock:
                self._socks.append(client)
                if self.hold:
                    self.held += 1
                    continue
            try:
                upstream = socket.create_connection(("127.0.0.1", self._upstream_port))
            except OSError:
                client.close()
                continue
            with self._lock:
                self._socks.append(upstream)
            for src, dst in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pipe, args=(src, dst), daemon=True).start()

    @staticmethod
    def _pipe(src: socket.socket, dst: socket.socket) -> None:
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        for s in (src, dst):
            try:
                s.close()
            except OSError:
                pass

    def stop(self) -> None:
        self._listener.close()
        with self._lock:
            socks, self._socks = self._socks, []
        for s in socks:
            try:
                s.close()
            except OSError:
                pass


def _user_sides(world: World) -> list[Any]:
    return [s for s in world.hl.connections() if any(x.get("type") == "userFills" for x in world.hl._subscriptions(s))]


def _market_sides(world: World) -> list[Any]:
    return [
        s
        for s in world.hl.connections()
        if any(x.get("type") in ("l2Book", "allMids") for x in world.hl._subscriptions(s))
    ]


def _opened_behind_proxy(new_world: Any, *, leaderboard_hangs: bool = False) -> tuple[World, Any, SleepLog, SwitchProxy]:
    """An open, protected SOL copy in a runner whose WebSocket (hub and leader feed) goes through a ``SwitchProxy``."""
    world: World = new_world()
    small_leader(world)
    world.seed_follow()
    if leaderboard_hangs:
        world.hl.leaderboard_delay_s = LEADERBOARD_HANG_S
    proxy = SwitchProxy(urlparse(world.hl.ws_url).port or 0)
    log = SleepLog(world.clock)
    endpoints = dataclasses.replace(world.endpoints(), ws_url=proxy.url)
    runner, _ = world.start(sleeper=log, endpoints=endpoints)
    world.leader_open(runner)
    world.run_until(runner, lambda: runner.broker.position("SOL") is not None and runner.broker.stops(), max_steps=40)
    world.step(runner, 3, ms=500)
    assert runner.broker.position("SOL") is not None and runner.broker.stops()
    return world, runner, log, proxy


def _alerts(world: World) -> int:
    return sum("loop_stalled" in t for t in world.tg.sent())


def _hang_feed_connect_and_leaderboard(world: World, proxy: SwitchProxy) -> None:
    """The leader feed's socket is cut and every new connection hangs in the handshake; the leaderboard never answers.
    The follow cycle is made due by the hour (``scoring.interval_min`` 60) crossed in the first hanging iteration."""
    proxy.hold = True
    for side in _user_sides(world):
        side.abort()
    world.hl.leaderboard_delay_s = LEADERBOARD_HANG_S


def test_R2c_AC2_leaderboard_and_feed_connect_hanging_one_iteration_is_bounded_and_the_stop_fills(new_world: Any) -> None:
    world, runner, log, proxy = _opened_behind_proxy(new_world)
    try:
        _hang_feed_connect_and_leaderboard(world, proxy)
        set_mid_below_stop(world, runner)
        worst, closed_at = 0.0, None
        # first iteration: 61 minutes later, so the follow cycle (leaderboard GET) and the feed reconnect are both due
        for i, ms in enumerate([3_661_000] + [500] * 14):
            beat = drive(world, runner, ms, log)
            worst = max(worst, beat.real_s)
            assert beat.real_s < LOOP_BOUND_S, f"iteration {i}: one loop iteration blocked for {beat.real_s:.1f} s"
            assert beat.slept_s < LOOP_BOUND_S, f"iteration {i}: the trading thread slept {beat.slept_s:.0f} s"
            if runner.broker.position("SOL") is None and closed_at is None:
                closed_at = i
    finally:
        world.hl.release()
        proxy.stop()
    assert closed_at is not None and closed_at <= 12, f"the stop did not fill promptly (closed at {closed_at})"
    assert worst < LOOP_BOUND_S


def test_R2c_AC2_leaderboard_alone_hanging_one_iteration_is_bounded(new_world: Any) -> None:
    world, runner, log, proxy = _opened_behind_proxy(new_world)
    try:
        world.hl.leaderboard_delay_s = LEADERBOARD_HANG_S
        for i, ms in enumerate([3_661_000, 3_661_000, 500, 500]):  # the follow cycle is due in the first two
            beat = drive(world, runner, ms, log)
            assert beat.real_s < LOOP_BOUND_S, f"iteration {i}: the leaderboard GET blocked the loop for {beat.real_s:.1f} s"
    finally:
        world.hl.release()
        proxy.stop()


def test_R2c_AC2_market_feed_connect_hanging_one_iteration_is_bounded(new_world: Any) -> None:
    """The hub's own reconnect (``hub_tap.drain``): books stop while the connect hangs, but the loop does not."""
    world, runner, log, proxy = _opened_behind_proxy(new_world)
    try:
        proxy.hold = True
        for side in world.hl.connections():
            side.abort()
        for i in range(12):
            beat = drive(world, runner, 11_000, log)  # past the reconnect back-off every time
            assert beat.real_s < LOOP_BOUND_S, f"iteration {i}: the hub reconnect blocked the loop for {beat.real_s:.1f} s"
    finally:
        world.hl.release()
        proxy.stop()


def test_R2c_AC2_no_loop_stalled_heartbeat_in_60_s_of_loop_time_while_both_hang(new_world: Any) -> None:
    """The leaderboard hangs from the start (the follow cycle is due at once after a start), the feed reconnect from the
    moment the position is open; 60 one-second iterations later the stall detector has not raised ``loop_stalled``."""
    world, runner, log, proxy = _opened_behind_proxy(new_world, leaderboard_hangs=True)
    try:
        proxy.hold = True
        for side in _user_sides(world):
            side.abort()
        for i in range(HEARTBEAT_LOOP_S):
            beat = drive(world, runner, 1_000, log)
            assert beat.real_s < LOOP_BOUND_S, f"iteration {i}: blocked for {beat.real_s:.1f} s"
        time.sleep(0.3)  # the detector runs on its own thread against the last completed iteration
        assert _alerts(world) == 0, "a loop_stalled alert was raised while only the network calls hung"
    finally:
        world.hl.release()
        proxy.stop()


def test_R2c_AC2_flatten_does_not_wait_on_gate_lock_for_the_hanging_leaderboard_and_connects(new_world: Any) -> None:
    world, runner, log, proxy = _opened_behind_proxy(new_world)
    try:
        _hang_feed_connect_and_leaderboard(world, proxy)
        world.clock.advance(3_661_000)
        world.pump_market()
        stepper = threading.Thread(target=runner.step, name="r2c-trading-step")
        stepper.start()
        try:
            wait_real(
                lambda: bool(world.hl.requests_of("GET /leaderboard")) or proxy.held > 0 or not stepper.is_alive(),
                seconds=5,
                what="the iteration to reach a hanging call",
            )
            world.telegram_ready()
            world.tg.push_text(f"/flatten {PIN}")
            started = time.monotonic()
            try:
                wait_real(lambda: runner.flatten_runs, seconds=LOOP_BOUND_S + 0.5, what="the flatten run")
            except AssertionError:
                pytest.fail(f"/flatten waited {time.monotonic() - started:.1f} s on gate_lock for a hanging iteration")
        finally:
            world.hl.release()
            proxy.stop()
            stepper.join(timeout=120)
    finally:
        world.hl.release()

