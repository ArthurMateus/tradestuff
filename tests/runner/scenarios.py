"""Shared scenario steps for the R0 fix-round runner tests (real runner over the loopback fakes)."""

from __future__ import annotations

from typing import Any

from tests.hl.ws_server import wait_for
from tests.runner.test_dev_e2e import opened as opened_position
from tests.runner.world import LEADER, PIN, World

__all__ = [
    "LEADER", "PIN", "count", "enter_jump", "enter_unsynced", "flatten_cmd", "opened_position", "set_mid_below_stop",
]

PHRASE = "managed from projection"  # pinned text of the re-alert while the clock is in doubt with positions open


def count(world: World, needle: str) -> int:
    """How many delivered Telegram messages contain ``needle``."""
    return sum(needle in text for text in world.tg.sent())


def enter_unsynced(world: World, runner: Any) -> Any:
    """The offset estimate cannot be refreshed and is older than clock.max_estimate_age_s (1800 s): unsynced."""
    world.hl.fail_types.add("l2Book")
    report = world.step(runner, 1, ms=1_801_000)
    assert report.skipped == "clock_unsynced"
    return report


def enter_jump(world: World, runner: Any, *, step_ms: int = 5_000) -> Any:
    """The exchange clock moves ``step_ms`` against the local one (a persistent offset step, > the 200 ms allowance)."""
    world.offset_ms += step_ms
    report = world.step(runner, 1, ms=601_000)  # clock.offset_interval_s = 600: this iteration re-estimates
    assert report.skipped == "clock_jump"
    return report


def set_mid_below_stop(world: World, runner: Any) -> None:
    trigger_px = min(s.trigger_px for s in runner.broker.stops() if s.kind == "sl")
    world.hl.mids["SOL"] = str(trigger_px - 1)


def flatten_cmd(world: World, runner: Any) -> None:
    """The PO sends ``/flatten <pin>`` on Telegram (the poll thread calls the supervisor)."""
    world.telegram_ready()
    world.tg.push_text(f"/flatten {PIN}")
    wait_for(lambda: runner.flatten_runs, what="the flatten run")
