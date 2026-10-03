"""R1.AC8 [integration]: any HL error other than 429 cools the wallet down; skipped refreshes are visible once.

R1-SD3: an ``HlError`` that is not a 429 (HTTP 5xx, timeout, budget refusal) puts that wallet on a short per-wallet
cooldown of ``hl.backoff_base_s`` (existing key, injected clock, measured from the failure); nothing is requested for it
meanwhile, ``backfill_failed`` is logged at most once per cooldown per wallet (not once per step), and the other wallets
keep progressing.

R1-SD4: when a ``refresh`` is skipped because the wallet is cooling down, ONE info-level record
``backfill_refresh_skipped`` (``wallet``, ``reason`` in ``too_active | rate_limited | error_cooldown``, ``until_ms``)
is logged per cooldown, however many refreshes are skipped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pytest

from copytrade.hl.budget import Priority
from copytrade.hl.errors import HlError
from tests.hl.support import T0, Call, status
from tests.selection.helpers import w
from tests.selection.r1_logs import BACKFILL_LOGGER, attr, events
from tests.selection.r1_world import DAY, HL_FILLS_LIMIT, World, make_world, spread_fills, synth_fills

BAD, B, C = w(1), w(2), w(3)
Rule = Callable[[Call], Any]


def timeout(call: Call) -> None:
    raise TimeoutError("slow")


FAILURES: list[tuple[str, Rule]] = [("http500", lambda call: status(500)), ("timeout", timeout)]


def build(rule: Rule | None = None, *, fail_fast: bool = False) -> World:
    world = make_world(fail_fast=fail_fast)
    for wallet, tid0 in ((BAD, 1), (B, 500_000), (C, 600_000)):
        world.hl.set_fills(wallet, synth_fills(5, tid0=tid0))
    if rule is not None:
        world.hl.rules[(BAD, "userFillsByTime")] = rule
    world.backfiller.set_candidates([BAD, B, C])
    return world


def base_ms(world: World) -> int:
    return int(world.cfg["hl.backoff_base_s"] * 1000)


@pytest.mark.parametrize("rule", [r for _, r in FAILURES], ids=[n for n, _ in FAILURES])
def test_R1_AC8_a_failing_wallet_is_asked_again_only_after_the_cooldown_and_logged_once_per_cooldown(
    rule: Rule, caplog: pytest.LogCaptureFixture
) -> None:
    world = build(rule)
    with caplog.at_level(logging.INFO, logger=BACKFILL_LOGGER):
        for _ in range(3):
            world.backfiller.step()
        failed_at = world.clock.now_ms()
        seen = len(world.fills_calls(BAD))
        for _ in range(10):  # nothing else is left; the clock has not moved
            world.backfiller.step()
        assert len(world.fills_calls(BAD)) == seen
        assert len(events(caplog, "backfill_failed")) == 1
        world.clock.now = failed_at + base_ms(world) - 1  # still inside the cooldown
        for _ in range(3):
            world.backfiller.step()
        assert len(world.fills_calls(BAD)) == seen
        assert len(events(caplog, "backfill_failed")) == 1
        world.clock.now = failed_at + base_ms(world) + 1  # cooldown over: exactly one new attempt, one new record
        world.backfiller.step()
        assert len(world.fills_calls(BAD)) > seen
        assert len(events(caplog, "backfill_failed")) == 2


def test_R1_AC8_the_cooldown_doubles_from_backoff_base_and_is_capped_at_backoff_max() -> None:
    world = build(lambda call: status(500))
    base, cap = base_ms(world), int(world.cfg["hl.backoff_max_s"] * 1000)
    world.backfiller.step()  # first failure of BAD (B and C complete on later steps)
    for _ in range(3):
        world.backfiller.step()
    expected = base
    for _ in range(12):  # long enough to hit the cap
        seen = len(world.fills_calls(BAD))
        world.clock.advance(expected - 1)
        for _ in range(3):
            world.backfiller.step()
        assert len(world.fills_calls(BAD)) == seen  # inside the cooldown: no request for the wallet
        world.clock.advance(1)
        world.backfiller.step()
        assert len(world.fills_calls(BAD)) > seen  # cooldown over: asked again, and it failed again
        expected = min(expected * 2, cap)
    assert expected == cap and cap > base


@pytest.mark.parametrize("rule", [r for _, r in FAILURES], ids=[n for n, _ in FAILURES])
def test_R1_AC8_the_other_wallets_progress_while_one_keeps_failing(rule: Rule) -> None:
    world = build(rule)
    for _ in range(4):
        world.backfiller.step()
    assert world.backfiller.inputs(B, T0) is not None and world.backfiller.inputs(C, T0) is not None
    assert world.backfiller.inputs(BAD, T0) is None
    assert world.backfiller.complete is False


def test_R1_AC8_a_wallet_that_always_500s_is_not_hammered_every_step_while_the_clock_stands_still() -> None:
    world = build(lambda call: status(500))
    for _ in range(40):
        world.backfiller.step()
    assert len(world.fills_calls(BAD)) <= 8  # the client's own retries of ONE attempt, not 40 attempts


def test_R1_AC8_a_budget_refusal_is_logged_once_per_cooldown(caplog: pytest.LogCaptureFixture) -> None:
    world = build(fail_fast=True)
    for _ in range(6):  # exhaust the scoring share so the next request does not fit
        world.client.user_role(w(9), priority=Priority.SCORING)
    with caplog.at_level(logging.INFO, logger=BACKFILL_LOGGER):
        for _ in range(10):
            world.backfiller.step()  # the clock does not move
    assert len(events(caplog, "backfill_failed")) == 1


# --- R1-SD4: one info record per cooldown when a refresh is skipped ----------------------------------------------


def make_cooling(reason: str) -> tuple[World, int]:
    """A world where BAD is cooling down for ``reason``; returns it with the earliest legal ``until_ms`` bound (the
    longest the cooldown may last from now)."""
    if reason == "too_active":
        world = make_world(fills_limit=HL_FILLS_LIMIT)
        world.hl.set_fills(BAD, spread_fills(20_000))
        world.backfiller.set_candidates([BAD])
        for _ in range(10):
            world.backfiller.step()
        return world, DAY
    world = build(lambda call: status(429) if reason == "rate_limited" else status(500))
    for _ in range(3):
        world.backfiller.step()
    if reason == "rate_limited":
        return world, int(world.cfg["hl.backoff_max_s"] * 1000)
    return world, base_ms(world)


def skip_refresh(world: World) -> None:
    try:
        world.backfiller.refresh(BAD)
    except HlError:
        pass


@pytest.mark.parametrize("reason", ["too_active", "rate_limited", "error_cooldown"])
def test_R1_AC8_skipped_refreshes_log_one_info_record_per_cooldown(
    reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    world, longest = make_cooling(reason)
    now = world.clock.now_ms()
    with caplog.at_level(logging.INFO, logger=BACKFILL_LOGGER):
        for _ in range(6):
            skip_refresh(world)
    (rec,) = events(caplog, "backfill_refresh_skipped")
    assert rec.levelno == logging.INFO
    assert attr(rec, "wallet") == BAD
    assert attr(rec, "reason") == reason
    assert now < attr(rec, "until_ms") <= now + longest


@pytest.mark.parametrize("reason", ["rate_limited", "error_cooldown"])
def test_R1_AC8_a_new_cooldown_gets_a_new_skipped_record(reason: str, caplog: pytest.LogCaptureFixture) -> None:
    world, longest = make_cooling(reason)
    with caplog.at_level(logging.INFO, logger=BACKFILL_LOGGER):
        skip_refresh(world)
        world.clock.advance(longest + 1_000)  # over: this refresh really goes out, fails again, cools down again
        skip_refresh(world)  # the real attempt (raises: HL still answers 429 / 500)
        skip_refresh(world)  # skipped
        skip_refresh(world)  # skipped
    assert len(events(caplog, "backfill_refresh_skipped")) == 2


def test_R1_AC8_a_refresh_that_is_not_skipped_logs_no_skipped_record(caplog: pytest.LogCaptureFixture) -> None:
    world = build()
    world.backfiller.step()
    with caplog.at_level(logging.INFO, logger=BACKFILL_LOGGER):
        world.backfiller.refresh(BAD)
    assert events(caplog, "backfill_refresh_skipped") == []
