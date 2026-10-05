"""R2b.AC6 (RISK-77): the reload reconciles the broker with the book at its end (or rebuilds the shares it does not know
from the ``share_state`` records written after the last checkpoint).

The checkpoint is written at most once per second (and not at all after a failed write), so a kill -9 can fall after a
share was opened and filled, or after its stop-loss filled, with no checkpoint that knows it:

* a share opened and filled inside the checkpoint gap is in the broker but in no checkpoint: it must NOT be closed as an
  orphan at the first periodic reconcile (300 s later): it is a valid copy and keeps one stop-loss of its full quantity;
* an OPEN share whose stop-loss filled after the checkpoint (the broker is flat) must not stay a ghost for 300 s: after
  the start the book has no OPEN share for it.

Checkpoints are stretched (code constants) after the run start so none follows the event. Real runner, gate, broker,
ledger, manager; only Hyperliquid and Telegram are loopback fakes. The R0 behaviour (ghost shares are dropped before they
are flagged: ``test_R0_AC6``) is unchanged and is covered by its own test.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from copytrade.runner import runner as runner_module
from tests.runner.r2_support import cuts_after, ledger_lines, live_sls, open_copy, restart_on_cut
from tests.runner.scenarios import set_mid_below_stop

D = Decimal


@pytest.fixture
def no_checkpoints(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr(runner_module, "CHECKPOINT_MIN_INTERVAL_S", 100_000)
    monkeypatch.setattr(runner_module, "CHECKPOINT_FORCE_INTERVAL_S", 100_000)
    return monkeypatch


def test_R2b_AC6_a_share_opened_and_filled_inside_the_checkpoint_gap_is_not_closed_as_an_orphan(
    new_world: Any, no_checkpoints: pytest.MonkeyPatch
) -> None:
    world, run1 = open_copy(new_world)
    run1.stop()
    lines = ledger_lines(world)
    cuts = cuts_after(world, lambda r: r.kind == "share_state" and r.payload.get("event") == "opened")
    cut = cuts[-1]  # the stop-loss is recorded too; the checkpoint in force still does not know the share
    no_checkpoints.undo()
    run2, _ = restart_on_cut(world, lines, cut)
    assert run2.broker.position("SOL") is not None
    world.step(run2, 3, ms=151_000)  # past the 300 s periodic reconcile
    view = run2.broker.position("SOL")
    assert view is not None and view.qty == D("1.00"), "the valid copy was closed (as an orphan)"
    assert not run2.broker.pending_exits(), "a close is pending for a valid share"
    assert [s.qty for s in live_sls(run2)] == [D("1.00")], [(s.qty, s.trigger_px) for s in live_sls(run2)]
    assert [s.status for s in run2.book.states()] == ["open"], (
        "the share the checkpoint did not know is not in the book"
    )


def test_R2b_AC6_the_unknown_share_is_known_and_protected_right_after_the_start(
    new_world: Any, no_checkpoints: pytest.MonkeyPatch
) -> None:
    world, run1 = open_copy(new_world)
    run1.stop()
    lines = ledger_lines(world)
    cut = cuts_after(world, lambda r: r.kind == "share_state" and r.payload.get("event") == "opened")[-1]
    no_checkpoints.undo()
    run2, _ = restart_on_cut(world, lines, cut)  # no iteration yet: the reload itself has to settle it
    assert [s.status for s in run2.book.states()] == ["open"]
    assert [s.qty for s in live_sls(run2)] == [D("1.00")]


def test_R2b_AC6_an_open_share_whose_stop_filled_after_the_checkpoint_is_not_a_ghost_after_the_start(
    new_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, run1 = open_copy(new_world)
    world.step(run1, 4, ms=1_500)  # a checkpoint that has the share OPEN is written
    monkeypatch.setattr(runner_module, "CHECKPOINT_MIN_INTERVAL_S", 100_000)
    monkeypatch.setattr(runner_module, "CHECKPOINT_FORCE_INTERVAL_S", 100_000)
    set_mid_below_stop(world, run1)
    world.run_until(run1, lambda: run1.broker.position("SOL") is None, max_steps=60, ms=500)
    run1.stop()
    lines = ledger_lines(world)
    cut = cuts_after(world, lambda r: r.kind == "fill" and bool(r.payload.get("exit_reason")))[0]
    monkeypatch.undo()
    run2, _ = restart_on_cut(world, lines, cut)  # the broker is flat; the checkpoint still has the share OPEN
    assert run2.broker.position("SOL") is None
    assert not [s for s in run2.book.states() if s.status == "open"], (
        "an OPEN ghost share is left until the next reconcile"
    )
