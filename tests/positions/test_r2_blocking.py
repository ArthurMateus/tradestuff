"""F12 round 2: RISK-43 (flip leg fired by our own exit) and RISK-44 (heal on a coin shared with another leader).

Real gate, real PaperBroker, real ledger. Tests marked GUARD pass today and pin behaviour the fix must keep.
"""

from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

from copytrade.core.domain import ActionKind
from tests.positions.helpers import SEC, WALLET_A, WALLET_B, Rig, build_rig, make_signal

MIN = 60 * SEC


def _skip_reasons(rig: Rig) -> list[str]:
    return [str(r["reason"]) for r in rig.records("signal_skip")]


def _exit_reasons(rig: Rig) -> list[str]:
    return [str(o.get("exit_reason")) for o in rig.orders()]


def _flip_while_our_sl_fires(rig: Rig) -> int:
    """Our long share is open; the leader flips short (leg waits); our SL fills first. Returns t0."""
    rig.open_share(1)
    now = int(rig.xtime.now)
    rig.book_at("SOL", "98", now + 1000)
    rig.mark("SOL", "98")  # SL 98.5 triggers, fills at now + 1000
    rig.at(now + 500)
    rig.feed(
        make_signal(2, ActionKind.CLOSE, size="5", from_flip=True, ts=now + 400),
        make_signal(2, ActionKind.OPEN, is_long=False, size="5", leg=1, from_flip=True, ts=now + 400, px="98"),
    )
    rig.book_at("SOL", "98", now + 2000)
    rig.step(now + 1000)  # our SL fills, the long closes, the leg fires
    rig.step(now + 2000)  # the short fills
    return now


def test_F12_R2_RISK43_flip_leg_fired_by_our_own_sl_opens_the_short_and_clears_ours_won(tmp_path: Path) -> None:
    """RED. The leg is the leader's new OPEN: (leader, coin) must not stay in _ours_won."""
    rig = build_rig(tmp_path, exits__tp_enabled=False)
    _flip_while_our_sl_fires(rig)
    short = rig.share_of(WALLET_A, "SOL")
    assert short is not None and not short.is_long and short.status == "open"
    assert (WALLET_A, "SOL") not in rig.mgr._ours_won


def test_F12_R2_RISK43_leader_close_of_the_flipped_short_is_mirrored_within_one_ack(tmp_path: Path) -> None:
    """RED. The leader's later CLOSE was skipped first_exit_won: unmirrored short until the 300 s reconcile."""
    rig = build_rig(tmp_path, exits__tp_enabled=False)
    now = _flip_while_our_sl_fires(rig)
    rig.at(now + 3000)
    rig.book_at("SOL", "98", now + 4000)
    rig.feed(make_signal(3, ActionKind.CLOSE, is_long=False, size="5", ts=now + 2900, px="98"))
    rig.leader_state.positions[WALLET_A] = {}
    rig.step(now + 4000)  # one ack later
    assert "first_exit_won" not in _skip_reasons(rig)
    assert rig.share_of(WALLET_A, "SOL") is None, "the short share must be closed within one ack"
    assert rig.env.broker.position("SOL") is None


def test_F12_R2_RISK43_GUARD_no_flip_our_sl_closes_and_the_leaders_later_close_is_skipped_first_exit_won(
    tmp_path: Path,
) -> None:
    """GUARD (passes today). Without a flip our exit wins: the leader's later close stays skipped and sends no order."""
    rig = build_rig(tmp_path, exits__tp_enabled=False)
    rig.open_share(1)
    now = int(rig.xtime.now)
    rig.book_at("SOL", "98", now + 1000)
    rig.mark("SOL", "98")
    rig.step(now + 1000)
    assert rig.share_of(WALLET_A, "SOL") is None
    orders_before = len(rig.orders())
    rig.at(now + 2000)
    rig.feed(make_signal(2, ActionKind.CLOSE, size="5", ts=now + 1900, px="98"))
    rig.leader_state.positions[WALLET_A] = {}
    rig.step(now + 3000)
    assert "first_exit_won" in _skip_reasons(rig)
    assert len(rig.orders()) == orders_before


def _lost_fill_on_shared_coin(rig: Rig, other_px: str, our_px: str) -> int:
    """Leader B holds a share at other_px; leader A's entry fills at our_px but the fill event is lost."""
    now = int(rig.xtime.now)
    rig.book_at("SOL", other_px, now + SEC)
    rig.feed(make_signal(7, ActionKind.OPEN, wallet=WALLET_B, size="5", ts=now - 100, px=other_px))
    rig.step(now + SEC)
    assert rig.share_of(WALLET_B, "SOL") is not None
    t = now + 2 * SEC
    rig.book_at("SOL", our_px, t + 1000)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=t - 100, px=our_px))
    rig.at(t + 1000)
    rig.env.broker.advance_to(t + 1000)  # the entry fill is consumed and dropped
    rig.leader_state.positions[WALLET_A] = {"SOL": "5"}
    rig.leader_state.positions[WALLET_B] = {"SOL": "5"}
    return t + 1000


def test_F12_R2_RISK44_heal_with_another_leaders_share_uses_the_shares_own_entry(tmp_path: Path) -> None:
    """RED. B at 100, A's lost fill at 110: A's entry is 110 (not the merged 105), stop 108.5, risk on 110."""
    rig = build_rig(tmp_path, exits__tp_enabled=False, equity="3000")
    _lost_fill_on_shared_coin(rig, "100", "110")
    rig.mgr.reconcile()
    share = rig.share_of(WALLET_A, "SOL")
    assert share is not None and share.status == "open"
    assert share.entry_px == D("110")
    assert share.current_stop_px == D("108.5") and share.initial_stop_px == D("108.5")
    assert share.initial_risk_usd == share.qty * D("1.5")
    (stop,) = rig.active_stops(share.share_id)
    assert D(str(stop["trigger_px"])) == D("108.5")


def test_F12_R2_RISK44_heal_when_the_other_share_entered_above_ours_never_leaves_a_stop_that_triggers_at_once(
    tmp_path: Path,
) -> None:
    """RED. B long at 120, A long lost at 100, mark 100: the merged average put the stop at 108.5 (above the mark)."""
    rig = build_rig(tmp_path, exits__tp_enabled=False, equity="3000")
    _lost_fill_on_shared_coin(rig, "120", "100")
    rig.mark("SOL", "100")
    rig.mgr.reconcile()
    share = rig.share_of(WALLET_A, "SOL")
    if share is None:
        assert "invalid_stop" in _exit_reasons(rig)
    else:
        assert share.entry_px == D("100") and share.current_stop_px == D("98.5")
    for stop in rig.active_stops():
        if stop["kind"] == "sl":
            assert D(str(stop["trigger_px"])) <= D("100"), "a long stop above the mark triggers at once"


def test_F12_R2_RISK44_heal_closes_for_cause_when_the_stop_on_the_own_entry_is_already_through_the_mark(
    tmp_path: Path,
) -> None:
    """RED. A's own entry 100 puts the stop at 98.5, but the mark has fallen to 98: invalid_stop, no live stop."""
    rig = build_rig(tmp_path, exits__tp_enabled=False, equity="3000")
    t = _lost_fill_on_shared_coin(rig, "120", "100")
    rig.book_at("SOL", "98", t + 5 * SEC)
    rig.at(t + SEC)
    rig.mark("SOL", "98")
    rig.mgr.reconcile()
    for stop in rig.active_stops(rig.share_of(WALLET_A, "SOL").share_id if rig.share_of(WALLET_A, "SOL") else None):
        assert not (stop["kind"] == "sl" and D(str(stop["trigger_px"])) >= D("98"))
    assert "invalid_stop" in _exit_reasons(rig), "closed for cause invalid_stop"


def test_F12_R2_RISK44_GUARD_single_share_on_the_coin_still_heals_with_the_brokers_average_entry(
    tmp_path: Path,
) -> None:
    """GUARD (passes today). One share on the coin: entry is the broker's average (the real fill), stop 1.5 below."""
    rig = build_rig(tmp_path, exits__tp_enabled=False)
    now = int(rig.xtime.now)
    rig.book_at("SOL", "100.2", now + SEC)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100, px="100"))
    rig.at(now + SEC)
    rig.env.broker.advance_to(now + SEC)
    rig.leader_state.positions[WALLET_A] = {"SOL": "5"}
    rig.mgr.reconcile()
    share = rig.share_of(WALLET_A, "SOL")
    assert share is not None and share.status == "open"
    assert share.entry_px == rig.held("SOL").avg_entry_px
    assert share.current_stop_px == share.entry_px - D("1.5")
