"""R2.AC4 (RISK-60) and R2.AC5 (RISK-68): what the reload does with a checkpoint that is OLDER than the broker's ledger
records (kill -9 between a fill and the next checkpoint).

AC4: a share the checkpoint has as PENDING_ENTRY whose fill the broker holds stays PENDING_ENTRY and the reload ends with
a reconcile, so it heals (OPEN, protected) at once: no spurious ``position_without_share`` pause, no valid copy closed as
an orphan 300 s later.

AC5: ``verify_protection`` takes each OPEN share's quantity from the BROKER (``share_qtys``) and the stop from the broker's
stop-loss, not from the stale checkpoint. After an ADD fill a full-size SL survives and an SL whose quantity equals the
broker's share quantity is never cancelled; after a take-profit / reduce the SL is not larger than the position and no
valid share is closed.

Every kill point between the event and the next checkpoint is tried (ledger truncated there, as test_failsafe_restart
does). Real runner, gate, broker, ledger, manager; only Hyperliquid and Telegram are loopback fakes."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from copytrade.positions.types import CLOSED, OPEN
from copytrade.runner import reload as rl
from tests.runner.r2_support import (
    add_to_position,
    cuts_after,
    keep_first,
    ledger_lines,
    live_sls,
    open_copy,
    restart_on_cut,
)
from tests.runner.world import World

D = Decimal


def only_sl_matches_the_broker(run: Any, *, where: str) -> None:
    view = run.broker.position("SOL")
    assert view is not None, f"{where}: a valid share was closed"
    assert not run.broker.pending_exits(), f"{where}: a close is pending for a valid share"
    sls = live_sls(run)
    assert [s.qty for s in sls] == [view.qty], (
        f"{where}: the live stop-losses are {[(s.qty, s.trigger_px) for s in sls]} for a position of {view.qty}"
    )
    assert view.share_qtys == (view.qty,)


# ------------------------------------------------------------------------------------------------ R2.AC4


def entry_cut(new_world: Any) -> tuple[World, list[bytes], int]:
    """The ledger of a copy that was opened, cut right after the entry's fill record: the broker holds the position, the
    share is PENDING_ENTRY in the checkpoint, no stop was recorded yet."""
    world, run1 = open_copy(new_world)
    run1.stop()
    lines = ledger_lines(world)
    cuts = cuts_after(world, lambda r: r.kind == "fill" and not r.payload.get("exit_reason"))
    return world, lines, cuts[0]


def test_R2_AC4_a_pending_share_whose_fill_the_broker_holds_is_not_dropped_and_no_position_without_share_is_flagged(
    new_world: Any,
) -> None:
    world, lines, cut = entry_cut(new_world)
    run2, report = restart_on_cut(world, lines, cut)
    view = run2.broker.position("SOL")
    assert view is not None, "the broker holds the filled entry"
    codes = [u.code for u in report.uncertain]
    assert rl.POSITION_WITHOUT_SHARE not in codes, codes
    state = run2.book.state(view.share_ids[0])
    assert state is not None and state.status != CLOSED, "the share was booked as closed although the broker holds its fill"
    assert not [r for r in world.records("share_state") if r.payload.get("event") == "restart_dropped"]


def test_R2_AC4_the_reload_reconciles_so_the_share_is_open_and_has_its_stop_at_once(new_world: Any) -> None:
    world, lines, cut = entry_cut(new_world)
    run2, _ = restart_on_cut(world, lines, cut)
    world.step(run2, 2, ms=500)  # well inside the 300 s reconcile interval: the heal comes from the reload, not from it
    view = run2.broker.position("SOL")
    assert view is not None
    state = run2.book.state(view.share_ids[0])
    assert state is not None and state.status == OPEN
    only_sl_matches_the_broker(run2, where="entry fill without a recorded stop")
    assert state.qty == view.qty


def test_R2_AC4_the_valid_copy_is_not_closed_as_an_orphan_at_the_first_reconcile(new_world: Any) -> None:
    world, lines, cut = entry_cut(new_world)
    run2, _ = restart_on_cut(world, lines, cut)
    world.step(run2, 4, ms=100_000)  # 400 s: past the first periodic reconcile (300 s)
    assert run2.broker.position("SOL") is not None, "the copy was closed"
    assert not [r for r in world.records("paper_order") if r.payload.get("exit_reason") == "orphan_close"]
    assert "does not know" not in world.alert_kinds_sent()  # 'the broker holds <share> that the book does not know'
    only_sl_matches_the_broker(run2, where="after the first reconcile")


# ------------------------------------------------------------------------------------------------ R2.AC5


def test_R2_AC5_kill_after_an_add_fill_keeps_one_full_size_sl_at_every_kill_point(new_world: Any) -> None:
    world, run1 = open_copy(new_world)
    add_to_position(world, run1)
    full = run1.broker.position("SOL").qty
    assert full == D("1.60")
    run1.stop()
    lines = ledger_lines(world)
    cuts = cuts_after(world, lambda r: r.kind == "fill" and r.payload.get("qty") == D("0.60"))
    assert len(cuts) >= 3, "the add fill, the new SL and the cancel of the old one are separate kill points"
    for cut in cuts:
        run2, _ = restart_on_cut(world, lines, cut)
        world.step(run2, 3, ms=500)
        only_sl_matches_the_broker(run2, where=f"kill after record {cut} of an add")
        assert run2.broker.position("SOL").qty == full
        run2.stop()


def test_R2_AC5_an_sl_whose_quantity_equals_the_brokers_share_quantity_is_never_cancelled(new_world: Any) -> None:
    """The reviewer's case: the full-size SL was recorded and the old one cancelled, then kill -9 before the checkpoint.
    The checkpoint still says 1.00; the broker's SL (1.60) is the correct one and must survive the restart."""
    world, run1 = open_copy(new_world)
    add_to_position(world, run1)
    run1.stop()
    lines = ledger_lines(world)
    cuts = cuts_after(world, lambda r: r.kind == "fill" and r.payload.get("qty") == D("0.60"))
    last = cuts[-1]  # after the cancel of the old SL: the broker holds exactly one SL, the full-size one
    keep_first(world, lines, last)
    from copytrade.ledger.store import read_records

    assert [r.payload["qty"] for r in read_records(world.ledger_dir) if r.kind == "paper_stop" and r.payload["kind"] == "sl"][-1] == D("1.60")
    n = len(world.records())
    run2, _ = world.start()
    world.step(run2, 3, ms=500)
    after = world.records()[n:]
    cancelled = [r for r in after if r.kind == "paper_cancel" and r.payload.get("target") == "stop"]
    # the restore re-registers the survivor under a renewed id (``<id>:rN``) and retires the old one with reason
    # "restart"; any OTHER cancel of a stop-loss means the restart threw a correct protection away
    foreign = [r for r in cancelled if r.payload.get("reason") != "restart"]
    assert not foreign, [(r.payload["client_order_id"], r.payload["reason"]) for r in foreign]
    only_sl_matches_the_broker(run2, where="kill after the full-size SL replaced the old one")


def test_R2_AC5_after_a_take_profit_fill_the_sl_is_not_larger_than_the_position_and_no_valid_share_is_closed(
    new_world: Any,
) -> None:
    world, run1 = open_copy(new_world)
    world.hl.mids["SOL"] = "110"  # the take-profit (0.50 at 103.1) triggers and fills; the SL is re-placed for 0.50
    world.run_until(
        run1,
        lambda: (p := run1.broker.position("SOL")) is not None
        and p.qty == D("0.50")
        and [s.qty for s in live_sls(run1)] == [D("0.50")],
        max_steps=60,
        ms=500,
    )
    run1.stop()
    lines = ledger_lines(world)
    cuts = cuts_after(world, lambda r: r.kind == "fill" and r.payload.get("exit_reason") == "take_profit")
    assert len(cuts) >= 2
    for cut in cuts:
        run2, _ = restart_on_cut(world, lines, cut)
        world.step(run2, 3, ms=500)
        view = run2.broker.position("SOL")
        assert view is not None and view.qty == D("0.50"), f"kill after record {cut}: the position is {view}"
        assert not run2.broker.pending_exits(), "a valid share is being closed"
        for stop in live_sls(run2):
            assert stop.qty <= view.qty, f"kill after record {cut}: an SL of {stop.qty} for a position of {view.qty}"
        only_sl_matches_the_broker(run2, where=f"kill after record {cut} of a take-profit")
        assert "stop_failed" not in world.alert_kinds_sent()
        run2.stop()


def test_R2_AC5_a_stale_checkpoint_stop_never_replaces_a_tighter_broker_stop(new_world: Any) -> None:
    """After a restart the share's current stop comes from the broker's SL: a price pull-back must not let the trailing
    logic swap the tighter broker SL for the looser one the stale checkpoint remembers."""
    world, run1 = open_copy(new_world)
    for px in ("108", "116"):  # two trailing steps: the SL moves up twice
        world.hl.mids["SOL"] = px
        world.step(run1, 6, ms=500)
    top = max(s.trigger_px for s in live_sls(run1))
    assert top > D("100.5")
    run1.stop()
    lines = ledger_lines(world)
    records = world.records()
    assert any(r.kind == "paper_stop" and r.payload["kind"] == "sl" and r.payload["trigger_px"] == top for r in records)
    cuts = cuts_after(world, lambda r: r.kind == "paper_stop" and r.payload["kind"] == "sl" and r.payload["trigger_px"] == top)
    for cut in cuts:
        run2, _ = restart_on_cut(world, lines, cut)
        world.hl.mids["SOL"] = str(top + 1)  # a pull-back that does not touch the stop: a stale trail would loosen it
        world.step(run2, 8, ms=500)
        view = run2.broker.position("SOL")
        assert view is not None
        sls = live_sls(run2)
        assert sls and min(s.trigger_px for s in sls) >= top, (
            f"kill after record {cut}: the SL was loosened to {[s.trigger_px for s in sls]} (was {top})"
        )
        run2.stop()
        world.hl.mids["SOL"] = "116"
