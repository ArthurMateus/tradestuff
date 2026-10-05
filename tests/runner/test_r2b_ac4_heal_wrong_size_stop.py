"""R2b.AC4 (R2-SD1, blocking): after a heal (``heal_pending_entries``) a standing stop of a DIFFERENT quantity than the
share is not accepted as its protection.

A kill -9 right after the entry's fill leaves the share PENDING_ENTRY in the checkpoint and the position at the broker.
If the broker also holds a stop-loss of the same share for another quantity (here 0.40 of the 1.00: a stale partial stop),
``_place_protection`` must not take it as "already protected": it has to place (or replace with) a stop for the share's
full quantity, so that the whole position is protected and exactly one stop-loss of the right size stands.
The ``s.qty == share.qty`` comparison in ``positions/manager.py`` has to be killed by this test.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from copytrade.ledger.store import Ledger
from tests.runner.r2_support import cuts_after, keep_first, ledger_lines, live_sls, open_copy

D = Decimal


def _killed_with_a_stale_stop(new_world: Any, stale_qty: str) -> Any:
    world, run1 = open_copy(new_world)
    run1.stop()
    lines = ledger_lines(world)
    cut = cuts_after(world, lambda r: r.kind == "fill" and not r.payload.get("exit_reason"))[0]
    real = next(r for r in world.records() if r.kind == "paper_stop" and r.payload["kind"] == "sl")
    keep_first(world, lines, cut)  # right after the entry fill: no stop was recorded yet
    ledger = Ledger.open(world.ledger_dir, clock=world.clock)
    try:
        payload = dict(real.payload)
        payload["qty"] = D(stale_qty)
        ledger.append("paper_stop", payload, client_order_id="stale-partial-stop-" + stale_qty)
    finally:
        ledger.close()
    run2, _ = world.start()
    return world, run2


@pytest.mark.parametrize("stale_qty", ["0.40", "1.50"])
def test_R2b_AC4_a_standing_stop_of_another_quantity_is_replaced_by_one_for_the_share_quantity(
    new_world: Any, stale_qty: str
) -> None:
    world, run2 = _killed_with_a_stale_stop(new_world, stale_qty)
    view = run2.broker.position("SOL")
    assert view is not None and view.qty == D("1.00")
    sls = live_sls(run2)  # as the reload left it, before the first iteration
    assert [s.qty for s in sls] == [D("1.00")], f"stop-losses standing: {[(s.qty, s.trigger_px) for s in sls]}"


def test_R2b_AC4_a_standing_stop_of_the_right_quantity_is_still_taken_not_duplicated(new_world: Any) -> None:
    world, run2 = _killed_with_a_stale_stop(new_world, "1.00")
    sls = live_sls(run2)
    assert [s.qty for s in sls] == [D("1.00")], f"stop-losses standing: {[(s.qty, s.trigger_px) for s in sls]}"
