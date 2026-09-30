"""F6.AC6 [unit]: few eligible.

With fewer than ``select.min_followed`` eligible, all eligible wallets are followed, and the list is never padded with
ineligible ones. With 0 eligible, opens are refused with ``no_eligible_leaders`` and one alert is sent.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from copytrade.core.domain import ActionKind
from copytrade.selection.models import ALERT_NO_ELIGIBLE, REASON_NO_ELIGIBLE, PolicyOutcome, SelectionState
from copytrade.selection.policy import apply_cycle
from tests.scoring.helpers import wallet as bare_wallet
from tests.selection.helpers import (
    D,
    ENTRY_ACTIONS,
    EXIT_ACTIONS,
    HEALTHY_OVERRIDES,
    HEALTHY_START_MS,
    NOW,
    Rig,
    FakeInputs,
    cfg,
    cycle,
    established,
    healthy_wallets,
    leaderboard_body,
    make_rig,
    score,
    w,
)


def make_stale(rig: Rig) -> None:
    """Every wallet's fills fetch is unknown: F5 lists ``stale_input`` (its metrics still compute, so no G15)."""
    rig.inputs.wallets = {a: replace(x, fills_fetched_ms=None) for a, x in rig.inputs.wallets.items()}


def policy(n_eligible: int, **overrides: object) -> PolicyOutcome:
    c = cfg(**overrides)
    scores = [score(i, i) for i in range(1, n_eligible + 1)]
    scores += [score(100 + i, None, eligible=False, reasons=("G6",)) for i in range(5)]
    return apply_cycle(c, SelectionState(followed={}, join_streaks={}), cycle(scores), now_ms=NOW, paused=frozenset())


@pytest.mark.parametrize(
    "eligible,few,none", [(0, True, True), (1, True, False), (4, True, False), (5, False, False), (6, False, False)]
)
def test_F6_AC6_few_eligible_means_fewer_than_min_followed_and_none_means_zero(eligible: int, few: bool, none: bool) -> None:
    out = policy(eligible)
    assert (out.eligible_count, out.few_eligible, out.no_eligible) == (eligible, few, none)


def test_F6_AC6_the_boundary_follows_the_min_followed_key() -> None:
    assert policy(3, select__min_followed=3).few_eligible is False
    assert policy(3, select__min_followed=4).few_eligible is True


def test_F6_AC6_with_fewer_eligible_than_min_followed_all_of_them_are_followed_and_never_padded(tmp_path: Path) -> None:
    ineligible = [bare_wallet(w(i)) for i in range(11, 21)]  # ten wallets with no data: they fail every gate
    provider = FakeInputs([*healthy_wallets(3), *ineligible], complete=True)
    rig = make_rig(tmp_path, inputs=provider, start_ms=HEALTHY_START_MS, **HEALTHY_OVERRIDES)
    rig.board.outcome = leaderboard_body(1000, first=[w(i) for i in (*range(1, 4), *range(11, 21))])
    try:
        for _ in range(4):
            report = rig.manager.run_cycle(p95_latency_s=D(3))
        assert report.eligible_count == 3
        assert rig.manager.followed == frozenset({w(1), w(2), w(3)})  # 3 < min_followed (5), not padded to 5
        assert rig.spy.calls("subscribe") and set(rig.spy.calls("subscribe")) == {w(1), w(2), w(3)}
    finally:
        rig.ledger.close()


def test_F6_AC6_zero_eligible_refuses_opens_with_no_eligible_leaders_and_alerts_once(tmp_path: Path) -> None:
    rig = established(tmp_path, n=3)
    try:
        assert rig.manager.refusal_reason(w(1), ActionKind.OPEN) is None
        make_stale(rig)  # nobody has a usable fills fetch any more: every wallet is ineligible (stale_input)
        for _ in range(3):
            report = rig.manager.run_cycle(p95_latency_s=D(3))
            assert report.eligible_count == 0
        for action in ENTRY_ACTIONS:
            assert rig.manager.refusal_reason(w(1), action) == REASON_NO_ELIGIBLE
        for action in EXIT_ACTIONS:
            assert rig.manager.refusal_reason(w(1), action) is None
        assert [a.kind for a in rig.alerts.sent].count(ALERT_NO_ELIGIBLE) == 1
    finally:
        rig.ledger.close()


def test_F6_AC6_a_second_episode_of_zero_eligible_alerts_again(tmp_path: Path) -> None:
    rig = established(tmp_path, n=3)
    try:
        saved = dict(rig.inputs.wallets)
        make_stale(rig)
        rig.manager.run_cycle(p95_latency_s=D(3))
        rig.inputs.wallets.update(saved)  # eligible wallets are back
        rig.manager.run_cycle(p95_latency_s=D(3))
        assert rig.manager.refusal_reason(w(1), ActionKind.OPEN) is None
        make_stale(rig)
        rig.manager.run_cycle(p95_latency_s=D(3))
        assert [a.kind for a in rig.alerts.sent].count(ALERT_NO_ELIGIBLE) == 2
    finally:
        rig.ledger.close()


def test_F6_AC6_with_eligible_wallets_there_is_no_alert(tmp_path: Path) -> None:
    rig = established(tmp_path, n=3)
    try:
        for _ in range(3):
            rig.manager.run_cycle(p95_latency_s=D(3))
        assert [a.kind for a in rig.alerts.sent].count(ALERT_NO_ELIGIBLE) == 0
    finally:
        rig.ledger.close()
