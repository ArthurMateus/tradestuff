"""R2.AC5 (RISK-68): a kill -9 between a take-profit fill and the re-placed stop-loss, after the stop-loss trailed. The
checkpoint in force remembers the looser (initial) stop; the broker holds the trailed SL for the OLD quantity. The restart
re-places the SL for the broker's share quantity at the broker's (tighter) trigger, never at the stale checkpoint stop.

The checkpoint cadence (a code constant) is stretched after the copy is open so that no checkpoint follows the trail."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from copytrade.runner import runner as runner_module
from tests.runner.r2_support import cuts_after, ledger_lines, live_sls, open_copy, restart_on_cut

D = Decimal


def test_R2_AC5_the_replacement_sl_after_a_take_profit_uses_the_brokers_trailed_trigger(
    new_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, run1 = open_copy(new_world)
    world.step(run1, 3, ms=1_500)  # settled: the checkpoint in force has the initial stop
    monkeypatch.setattr(runner_module, "CHECKPOINT_MIN_INTERVAL_S", 100_000)  # no checkpoint follows what happens next
    world.hl.mids["SOL"] = "110"  # the stop trails and the take-profit (0.50) fills
    world.run_until(
        run1,
        lambda: (
            (p := run1.broker.position("SOL")) is not None
            and p.qty == D("0.50")
            and [s.qty for s in live_sls(run1)] == [D("0.50")]
        ),
        max_steps=60,
        ms=500,
    )
    run1.stop()
    lines = ledger_lines(world)
    cut = cuts_after(world, lambda r: r.kind == "fill" and r.payload.get("exit_reason") == "take_profit")[0]
    records = world.records()[:cut]  # right after the take-profit fill: the broker still holds the SL of 1.00
    held = [r.payload["trigger_px"] for r in records if r.kind == "paper_stop" and r.payload["kind"] == "sl"][-1]
    stale = [r for r in records if r.kind == "runner_checkpoint"][-1].payload["manager"]["state"]["shares"][0]
    assert stale["current_stop_px"] < held, "precondition: the checkpoint in force remembers a looser stop"
    monkeypatch.undo()
    run2, _ = restart_on_cut(world, lines, cut)
    sls = live_sls(run2)  # as the reload left it, before the first iteration can trail the stop again
    assert [s.qty for s in sls] == [D("0.50")], [(s.qty, s.trigger_px) for s in sls]
    assert min(s.trigger_px for s in sls) >= held, f"the SL was re-placed at {[s.trigger_px for s in sls]}, was {held}"
