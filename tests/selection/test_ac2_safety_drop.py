"""F6.AC2 [unit]: the immediate safety drop and the leader pause.

Triggers: any BU flag, a G15 failure, a copy drawdown >= leader_pause.max_copy_dd x risk.leader_allocation_fraction x
equity, or leader_pause.max_consec_losses consecutive copy losses. From the next signal (within 1 s) the wallet's
opens and adds are refused with ``leader_paused``, whatever its follow time. Exits are never refused (C4).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from copytrade.core.domain import ActionKind
from copytrade.selection.manager import FollowManager  # noqa: F401  (the public entry point under test)
from copytrade.selection.models import REASON_LEADER_PAUSED, REASON_NOT_FOLLOWED
from copytrade.selection.pause import LeaderPauseTracker
from tests.selection.helpers import (
    D,
    ENTRY_ACTIONS,
    EXIT_ACTIONS,
    HOUR,
    MINUTE,
    NOW,
    SECOND,
    Rig,
    cfg,
    cycle,
    join_all,
    ranked,
    score,
    w,
)

EQUITY = D(10_000)  # 0.10 x 0.30 x 10 000 = 300 USD drawdown threshold at the default config


def tracker(**overrides: object) -> LeaderPauseTracker:
    return LeaderPauseTracker(cfg(**overrides))


# --- the tracker: drawdown trigger -------------------------------------------------------------------------------


def test_F6_AC2_drawdown_exactly_at_the_threshold_pauses() -> None:
    t = tracker()
    for _ in range(2):
        assert t.record_copy_result(w(1), pnl_usd=D(-100), equity_usd=EQUITY) is False
    assert t.is_paused(w(1)) is False
    assert t.record_copy_result(w(1), pnl_usd=D(-100), equity_usd=EQUITY) is True  # 300 = 0.10 x 0.30 x 10 000
    assert t.is_paused(w(1)) is True


def test_F6_AC2_drawdown_one_cent_below_the_threshold_does_not_pause() -> None:
    t = tracker()
    t.record_copy_result(w(1), pnl_usd=D(-100), equity_usd=EQUITY)
    t.record_copy_result(w(1), pnl_usd=D(-100), equity_usd=EQUITY)
    assert t.record_copy_result(w(1), pnl_usd=D("-99.99"), equity_usd=EQUITY) is False
    assert t.is_paused(w(1)) is False
    assert t.record_copy_result(w(1), pnl_usd=D("-0.01"), equity_usd=EQUITY) is True  # now exactly 300


def test_F6_AC2_drawdown_is_measured_from_the_running_peak_not_from_zero() -> None:
    t = tracker()
    t.record_copy_result(w(1), pnl_usd=D(500), equity_usd=EQUITY)  # peak +500
    assert t.record_copy_result(w(1), pnl_usd=D(-299), equity_usd=EQUITY) is False  # drawdown 299, still +201 overall
    assert t.is_paused(w(1)) is False
    assert t.record_copy_result(w(1), pnl_usd=D(-1), equity_usd=EQUITY) is True  # drawdown 300
    assert t.is_paused(w(1)) is True


def test_F6_AC2_a_new_peak_moves_the_drawdown_base_up() -> None:
    t = tracker()
    t.record_copy_result(w(1), pnl_usd=D(100), equity_usd=EQUITY)
    t.record_copy_result(w(1), pnl_usd=D(-250), equity_usd=EQUITY)  # dd 250 from peak 100
    t.record_copy_result(w(1), pnl_usd=D(400), equity_usd=EQUITY)  # cumulative 250 -> new peak 250
    assert t.record_copy_result(w(1), pnl_usd=D(-299), equity_usd=EQUITY) is False
    assert t.record_copy_result(w(1), pnl_usd=D(-1), equity_usd=EQUITY) is True


@pytest.mark.parametrize("equity,threshold", [(10_000, "300"), (20_000, "600"), (5_000, "150")])
def test_F6_AC2_the_threshold_scales_with_the_equity_passed_in(equity: int, threshold: str) -> None:
    t = tracker()
    assert t.record_copy_result(w(1), pnl_usd=-D(threshold) + 1, equity_usd=D(equity)) is False
    assert t.record_copy_result(w(1), pnl_usd=D(-1), equity_usd=D(equity)) is True


def test_F6_AC2_the_threshold_follows_the_config_keys() -> None:
    t = tracker(leader_pause__max_copy_dd="0.20", risk__leader_allocation_fraction="0.50")  # 0.2 x 0.5 x 10 000 = 1000
    assert t.record_copy_result(w(1), pnl_usd=D(-999), equity_usd=EQUITY) is False
    assert t.record_copy_result(w(1), pnl_usd=D(-1), equity_usd=EQUITY) is True


# --- the tracker: consecutive losses ------------------------------------------------------------------------------


def test_F6_AC2_five_consecutive_losses_pause_and_four_do_not() -> None:
    t = tracker()
    for _ in range(4):
        assert t.record_copy_result(w(1), pnl_usd=D(-1), equity_usd=EQUITY) is False
    assert t.is_paused(w(1)) is False
    assert t.record_copy_result(w(1), pnl_usd=D(-1), equity_usd=EQUITY) is True


def test_F6_AC2_a_winning_copy_resets_the_loss_run() -> None:
    t = tracker()
    for _ in range(4):
        t.record_copy_result(w(1), pnl_usd=D(-1), equity_usd=EQUITY)
    t.record_copy_result(w(1), pnl_usd=D(1), equity_usd=EQUITY)
    for _ in range(4):
        assert t.record_copy_result(w(1), pnl_usd=D(-1), equity_usd=EQUITY) is False
    assert t.is_paused(w(1)) is False


@pytest.mark.parametrize("limit", [2, 3, 20])
def test_F6_AC2_the_loss_run_limit_is_read_from_config(limit: int) -> None:
    t = tracker(leader_pause__max_consec_losses=limit)
    for _ in range(limit - 1):
        assert t.record_copy_result(w(1), pnl_usd=D("-0.01"), equity_usd=EQUITY) is False
    assert t.record_copy_result(w(1), pnl_usd=D("-0.01"), equity_usd=EQUITY) is True


def test_F6_AC2_a_pause_persists_after_later_wins() -> None:
    t = tracker()
    for _ in range(5):
        t.record_copy_result(w(1), pnl_usd=D(-1), equity_usd=EQUITY)
    for _ in range(10):
        t.record_copy_result(w(1), pnl_usd=D(50), equity_usd=EQUITY)
    assert t.is_paused(w(1)) is True
    assert t.paused() == frozenset({w(1)})


def test_F6_AC2_wallets_are_tracked_independently_and_case_insensitively() -> None:
    t = tracker()
    for _ in range(5):
        t.record_copy_result(w(1).upper().replace("0X", "0x"), pnl_usd=D(-1), equity_usd=EQUITY)
    assert t.is_paused(w(1)) is True
    assert t.is_paused(w(2)) is False
    assert t.paused() == frozenset({w(1)})


def test_F6_AC2_no_results_means_nobody_is_paused() -> None:
    assert tracker().paused() == frozenset()
    assert tracker().is_paused(w(1)) is False


# --- the manager: refusals and immediacy --------------------------------------------------------------------------


def followed_rig(rig_factory: Callable[..., Rig], ids: tuple[int, ...] = (1, 2, 3), **kw: object) -> tuple[Rig, int]:
    rig = rig_factory(**kw)
    t = join_all(rig, ids, now_ms=NOW)
    assert rig.manager.followed == frozenset(w(i) for i in ids)
    return rig, t


def test_F6_AC2_a_followed_wallet_accepts_entries_until_something_trips(rig_factory: Callable[..., Rig]) -> None:
    rig, _ = followed_rig(rig_factory)
    for action in ENTRY_ACTIONS + EXIT_ACTIONS:
        assert rig.manager.refusal_reason(w(1), action) is None


def test_F6_AC2_consecutive_copy_losses_refuse_entries_at_once_but_never_exits(rig_factory: Callable[..., Rig]) -> None:
    rig, _ = followed_rig(rig_factory)
    for _ in range(5):
        rig.manager.on_copy_closed(w(1), pnl_usd=D(-1), equity_usd=EQUITY)
    for action in ENTRY_ACTIONS:
        assert rig.manager.refusal_reason(w(1), action) == REASON_LEADER_PAUSED
    for action in EXIT_ACTIONS:
        assert rig.manager.refusal_reason(w(1), action) is None  # C4: exits are never blocked
    assert w(1) not in rig.manager.followed
    assert rig.manager.refusal_reason(w(2), ActionKind.OPEN) is None  # the others are untouched


def test_F6_AC2_a_drawdown_trip_drops_a_wallet_followed_for_only_a_minute(rig_factory: Callable[..., Rig]) -> None:
    rig, _ = followed_rig(rig_factory)  # followed_at is at most a minute old, far below min_follow_hours
    rig.manager.on_copy_closed(w(2), pnl_usd=D(-300), equity_usd=EQUITY)
    assert rig.manager.refusal_reason(w(2), ActionKind.OPEN) == REASON_LEADER_PAUSED
    assert w(2) not in rig.manager.followed


def test_F6_AC2_the_refusal_holds_within_one_second_and_later(rig_factory: Callable[..., Rig]) -> None:
    rig, _ = followed_rig(rig_factory)
    rig.manager.on_copy_closed(w(1), pnl_usd=D(-300), equity_usd=EQUITY)
    for ms in (0, 999, 1 * SECOND, 10 * MINUTE, 30 * HOUR):
        rig.advance(ms)
        assert rig.manager.refusal_reason(w(1), ActionKind.ADD) == REASON_LEADER_PAUSED


@pytest.mark.parametrize(
    "kind,kwargs",
    [("blowup", {"flags": ("BU3",)}), ("g15", {"reasons": ("G15",)})],
    ids=["BU-flag", "G15"],
)
def test_F6_AC2_a_scoring_safety_trigger_refuses_entries_from_the_cycle_that_saw_it(
    rig_factory: Callable[..., Rig], kind: str, kwargs: dict[str, object]
) -> None:
    rig, t = followed_rig(rig_factory)
    bad = score(1, None, eligible=False, **kwargs)
    report = rig.manager.apply_cycle(cycle([bad, score(2, 1), score(3, 2)], t + MINUTE), now_ms=t + MINUTE)
    assert w(1) not in rig.manager.followed
    assert [d.kind for d in report.decisions if d.wallet == w(1)] == ["safety_drop"]
    assert rig.manager.refusal_reason(w(1), ActionKind.OPEN) == REASON_LEADER_PAUSED
    assert rig.manager.refusal_reason(w(1), ActionKind.ADD) == REASON_LEADER_PAUSED
    assert rig.manager.refusal_reason(w(1), ActionKind.CLOSE) is None


def test_F6_AC2_a_rank_dropped_wallet_is_refused_as_not_followed_not_as_paused(rig_factory: Callable[..., Rig]) -> None:
    rig, t = followed_rig(rig_factory)
    later = t + 30 * HOUR
    for i in range(2):
        rig.manager.apply_cycle(cycle([score(2, 1), score(3, 2), score(1, 16)], later + i * MINUTE), now_ms=later + i * MINUTE)
    assert w(1) not in rig.manager.followed
    assert rig.manager.refusal_reason(w(1), ActionKind.OPEN) == REASON_NOT_FOLLOWED
    assert rig.manager.refusal_reason(w(1), ActionKind.CLOSE) is None


def test_F6_AC2_a_wallet_we_never_followed_is_refused_entries(rig_factory: Callable[..., Rig]) -> None:
    rig, _ = followed_rig(rig_factory)
    assert rig.manager.refusal_reason(w(99), ActionKind.OPEN) == REASON_NOT_FOLLOWED
    assert rig.manager.refusal_reason(w(99), ActionKind.CLOSE) is None


def test_F6_AC2_a_paused_wallet_with_a_good_score_is_not_rejoined(rig_factory: Callable[..., Rig]) -> None:
    rig, t = followed_rig(rig_factory)
    for _ in range(5):
        rig.manager.on_copy_closed(w(1), pnl_usd=D(-1), equity_usd=EQUITY)
    for i in range(4):  # rank 1 and eligible in every cycle
        rig.manager.apply_cycle(cycle(ranked(1, 2, 3), t + (i + 1) * MINUTE), now_ms=t + (i + 1) * MINUTE)
    assert w(1) not in rig.manager.followed
    assert rig.manager.refusal_reason(w(1), ActionKind.OPEN) == REASON_LEADER_PAUSED


def test_F6_AC2_a_safety_drop_is_ledgered_in_the_cycle_record(rig_factory: Callable[..., Rig]) -> None:
    rig, t = followed_rig(rig_factory)
    bad = score(1, None, eligible=False, flags=("BU6",))
    rig.manager.apply_cycle(cycle([bad, score(2, 1), score(3, 2)], t + MINUTE), now_ms=t + MINUTE)
    last = rig.records("select_cycle")[-1]
    decisions = [d for d in last["decisions"] if d["wallet"] == w(1)]
    assert [d["kind"] for d in decisions] == ["safety_drop"]
