"""F6.AC3 [integration]: WebSocket slots, with the real feed (F3), the real signal detector (F7) and the real ledger (F2).

Distinct subscribed users stay <= 10: followed wallets, plus dropped wallets that still have open shares, plus an
incoming wallet. A join or swap without a free slot is deferred and logged ``no_ws_slot``. A dropped wallet keeps
its subscription until its last share closes and releases it <= 60 s later. F7 contract: ``begin_follow`` (with the
wallet's ``clearinghouseState`` and the follow time) before the wallet is subscribed, ``end_follow`` after it is
unsubscribed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from copytrade.hl.errors import WsUserLimitError  # noqa: F401
from copytrade.scoring.models import CycleResult
from copytrade.selection.models import DECISION_DEFERRED, DECISION_SWAP, REASON_NO_WS_SLOT
from tests.selection.helpers import (
    D,
    HOUR,
    MINUTE,
    NOW,
    SECOND,
    Rig,
    cycle,
    join_all,
    rig_in_tmp,
    score,
    w,
)

EQUITY = D(10_000)
NINE = tuple(range(1, 10))
WIDE = {"select__join_rank": 9}  # nine wallets can hold rank <= join_rank, so nine can be followed


def nine_followed(rig: Rig) -> int:
    t = join_all(rig, NINE)
    assert rig.manager.followed == frozenset(w(i) for i in NINE)
    return t


def swap_cycle(cand: int, weakest: int, others: Sequence[int], t: int, *, extra: Sequence[int] = ()) -> CycleResult:
    """``cand`` at rank 1 (0.95), ``others`` ranked 2.. (0.88 down), ``weakest`` at the end (0.50); ``extra`` are
    eligible wallets outside the join line, below the weakest."""
    scores = [score(cand, 1, "0.95")]
    scores += [score(i, r, str(D("0.90") - D("0.01") * r)) for r, i in enumerate(others, start=2)]
    scores.append(score(weakest, len(others) + 2, "0.50"))
    scores += [score(i, len(others) + 3 + n, "0.40") for n, i in enumerate(extra)]
    return cycle(scores, t)


def do_swap(rig: Rig, cand: int, weakest: int, others: Sequence[int], t: int, *, extra: Sequence[int] = ()) -> int:
    """Two applied cycles so that ``cand`` confirms; returns the time of the second."""
    for k in range(2):
        rig.manager.apply_cycle(swap_cycle(cand, weakest, others, t + k * MINUTE, extra=extra), now_ms=t + k * MINUTE)
    return t + MINUTE


# --- the F7 contract ---------------------------------------------------------------------------------------------


def test_F6_AC3_begin_follow_comes_before_subscribe_and_carries_the_fetched_state(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.states.held[w(1)] = {"BTC": "1.5", "ETH": "-2"}
    t = join_all(rig, (1, 2))
    assert rig.spy.index("begin_follow", w(1)) < rig.spy.index("subscribe", w(1))
    assert rig.spy.index("begin_follow", w(2)) < rig.spy.index("subscribe", w(2))
    started = {r["wallet"]: r for r in rig.records("follow_started")}
    assert started[w(1)]["held"] == ["BTC", "ETH"]  # the detector saw the state we fetched: pre-existing positions
    assert started[w(1)]["followed_at_ms"] == t
    assert started[w(2)]["held"] == []
    assert w(1) in rig.states.calls


def test_F6_AC3_unsubscribe_comes_before_end_follow(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    join_all(rig, (1, 2, 3))
    for _ in range(5):
        rig.manager.on_copy_closed(w(1), pnl_usd=D(-1), equity_usd=EQUITY)
    rig.manager.tick()
    assert rig.spy.index("unsubscribe", w(1)) < rig.spy.index("end_follow", w(1))
    assert [r["wallet"] for r in rig.records("follow_ended")] == [w(1)]
    assert w(1) not in rig.manager.subscribed
    assert rig.manager.subscribed == frozenset({w(2), w(3)})


def test_F6_AC3_the_detector_follows_exactly_the_followed_wallets(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    join_all(rig, (1, 2, 3))
    assert sorted(r["wallet"] for r in rig.records("follow_started")) == [w(1), w(2), w(3)]
    assert rig.records("follow_ended") == []


def test_F6_AC3_a_wallet_whose_state_cannot_be_fetched_is_not_followed_at_all(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.states.fail = {w(1)}
    join_all(rig, (1, 2, 3))
    assert rig.manager.followed == frozenset({w(2), w(3)})
    assert w(1) not in rig.spy.calls("begin_follow") and w(1) not in rig.spy.calls("subscribe")
    rig.states.fail = set()  # the source recovers: the next qualifying cycle follows it
    rig.manager.apply_cycle(cycle([score(1, 1), score(2, 2), score(3, 3)], NOW + 5 * MINUTE), now_ms=NOW + 5 * MINUTE)
    assert w(1) in rig.manager.followed
    assert rig.spy.index("begin_follow", w(1)) < rig.spy.index("subscribe", w(1))


# --- holding a dropped wallet -------------------------------------------------------------------------------------


def trip(rig: Rig, wallet: int) -> None:
    for _ in range(5):
        rig.manager.on_copy_closed(w(wallet), pnl_usd=D(-1), equity_usd=EQUITY)


def test_F6_AC3_a_dropped_wallet_keeps_its_subscription_until_its_last_share_closes(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    join_all(rig, (1, 2, 3))
    rig.shares.open = {w(1)}
    trip(rig, 1)
    assert w(1) not in rig.manager.followed
    for _ in range(600):  # ten minutes of one-second ticks
        rig.advance(SECOND)
        rig.manager.tick()
    assert w(1) in rig.manager.subscribed
    assert w(1) not in rig.spy.calls("unsubscribe") and w(1) not in rig.spy.calls("end_follow")
    assert rig.records("follow_ended") == []  # the detector still classifies its fills (C4: exits are mirrored)


def test_F6_AC3_the_slot_is_released_within_sixty_seconds_of_the_last_share_closing(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    join_all(rig, (1, 2, 3))
    rig.shares.open = {w(1)}
    trip(rig, 1)
    rig.advance(5 * MINUTE)
    rig.manager.tick()
    assert w(1) in rig.manager.subscribed
    rig.shares.open = set()  # the last share closes now
    released_after = None
    for second in range(1, 61):
        rig.advance(SECOND)
        rig.manager.tick()
        if w(1) not in rig.manager.subscribed:
            released_after = second
            break
    assert released_after is not None and released_after <= 60
    assert rig.spy.index("unsubscribe", w(1)) < rig.spy.index("end_follow", w(1))
    assert w(1) not in rig.spy.subscribed


def test_F6_AC3_a_dropped_wallet_with_no_open_share_is_released_within_a_minute(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    join_all(rig, (1, 2, 3))
    trip(rig, 1)
    for _ in range(60):
        rig.advance(SECOND)
        rig.manager.tick()
    assert w(1) not in rig.manager.subscribed
    assert w(1) in rig.spy.calls("unsubscribe")


# --- the tenth slot ----------------------------------------------------------------------------------------------


def test_F6_AC3_a_swap_uses_the_tenth_slot_for_the_handover(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(**WIDE)
    t = nine_followed(rig)
    do_swap(rig, 20, 9, range(1, 9), t + 25 * HOUR)
    assert rig.manager.followed == frozenset({*(w(i) for i in range(1, 9)), w(20)})
    assert rig.spy.index("begin_follow", w(20)) < rig.spy.index("subscribe", w(20)) < rig.spy.index("unsubscribe", w(9))
    assert rig.spy.index("unsubscribe", w(9)) < rig.spy.index("end_follow", w(9))
    assert rig.spy.max_subscribed == 10  # the incoming wallet was subscribed while the outgoing one still was
    assert rig.spy.limit_errors == 0
    assert len(rig.manager.subscribed) == 9


def test_F6_AC3_a_swapped_out_wallet_with_open_shares_keeps_the_tenth_slot(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(**WIDE)
    t = nine_followed(rig)
    rig.shares.open = {w(9)}
    do_swap(rig, 20, 9, range(1, 9), t + 25 * HOUR)
    assert len(rig.manager.followed) == 9 and w(9) not in rig.manager.followed
    assert rig.manager.subscribed == frozenset({*(w(i) for i in range(1, 9)), w(20), w(9)})
    assert w(9) not in rig.spy.calls("unsubscribe")
    assert rig.spy.limit_errors == 0


def test_F6_AC3_a_swap_without_a_free_slot_is_deferred_and_logged_no_ws_slot(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(**WIDE)
    t = nine_followed(rig)
    rig.shares.open = {w(9)}
    t = do_swap(rig, 20, 9, range(1, 9), t + 25 * HOUR)  # 9 followed + w9 held = 10 subscribed
    followed_before = rig.manager.followed
    t += 25 * HOUR
    for k in range(2):  # w21 confirms; w8 (the weakest) is old enough; but there is no eleventh slot
        report = rig.manager.apply_cycle(
            swap_cycle(21, 8, [20, 1, 2, 3, 4, 5, 6, 7], t + k * MINUTE, extra=[9]), now_ms=t + k * MINUTE
        )
    assert rig.manager.followed == followed_before
    assert [(d.kind, d.wallet, d.reason) for d in report.decisions if d.kind == DECISION_DEFERRED] == [
        (DECISION_DEFERRED, w(21), REASON_NO_WS_SLOT)
    ]
    assert not [d for d in report.decisions if d.kind == DECISION_SWAP]
    deferred = rig.records("follow_deferred")
    assert deferred and all(r["wallet"] == w(21) and r["reason"] == "no_ws_slot" for r in deferred)
    assert w(21) not in rig.spy.calls("subscribe") and w(21) not in rig.spy.calls("begin_follow")
    assert rig.spy.limit_errors == 0 and rig.spy.max_subscribed <= 10
    # the held wallet's last share closes; once released the deferred swap goes through on the next cycle
    rig.shares.open = set()
    for _ in range(60):
        rig.advance(SECOND)
        rig.manager.tick()
    t += 2 * MINUTE
    rig.manager.apply_cycle(swap_cycle(21, 8, [20, 1, 2, 3, 4, 5, 6, 7], t, extra=[9]), now_ms=t)
    assert w(21) in rig.manager.followed and w(8) not in rig.manager.followed
    assert rig.spy.max_subscribed <= 10


def test_F6_AC3_a_plain_join_without_a_free_slot_is_deferred_and_the_best_ranked_gets_the_last_slot(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory(**WIDE)
    t = nine_followed(rig)
    rig.shares.open = {w(1), w(2)}
    trip(rig, 1)
    trip(rig, 2)  # followed 7, held 2: nine subscribed, one slot free, two seats free
    assert len(rig.manager.followed) == 7 and len(rig.manager.subscribed) == 9
    t += MINUTE
    scores = [score(20, 1, "0.95"), score(21, 2, "0.94")]
    scores += [score(i, i, str(D("0.89") - D("0.01") * i)) for i in range(3, 10)]
    for k in range(2):
        report = rig.manager.apply_cycle(cycle(scores, t + k * MINUTE), now_ms=t + k * MINUTE)
    assert w(20) in rig.manager.followed and w(21) not in rig.manager.followed
    assert [d.wallet for d in report.decisions if d.kind == DECISION_DEFERRED] == [w(21)]
    assert len(rig.manager.subscribed) == 10 and rig.spy.limit_errors == 0
    assert any(r["wallet"] == w(21) and r["reason"] == "no_ws_slot" for r in rig.records("follow_deferred"))


# --- property: the slot limit and the call order hold whatever happens ---------------------------------------------

_EVENT = re.compile(r"(begin_follow subscribe (unsubscribe end_follow )?)*")


@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    steps=st.lists(
        st.tuples(
            st.permutations(list(range(1, 15))),  # the rank order of fourteen eligible wallets
            st.frozensets(st.integers(1, 14), max_size=6),  # wallets with an open share
            st.integers(0, 30 * HOUR),
            st.frozensets(st.integers(1, 14), max_size=2),  # wallets that trip the leader pause this step
        ),
        min_size=2,
        max_size=10,
    )
)
def test_F6_AC3_property_at_most_ten_users_and_the_call_order_holds(
    steps: list[tuple[list[int], frozenset[int], int, frozenset[int]]],
) -> None:
    with rig_in_tmp(**WIDE) as rig:
        now = NOW
        for order, open_shares, dt, tripped in steps:
            now += dt + MINUTE
            rig.shares.open = {w(i) for i in open_shares}
            scores = [score(i, r, str(D("0.95") - D("0.01") * r)) for r, i in enumerate(order, start=1)]
            rig.manager.apply_cycle(cycle(scores, now), now_ms=now)
            for i in tripped:
                trip(rig, i)
            rig.advance(60 * SECOND)
            rig.manager.tick()
            assert rig.spy.limit_errors == 0 and rig.spy.max_subscribed <= 10
            assert len(rig.manager.followed) <= 9
            assert rig.manager.subscribed == frozenset(rig.spy.subscribed)
            assert rig.manager.subscribed - rig.manager.followed <= rig.shares.open  # held only for open shares
        for wallet in {w(i) for i in range(1, 15)}:  # begin -> subscribe -> (unsubscribe -> end)*, per wallet
            events = " ".join(call for call, who in rig.spy.log if who == wallet)
            assert _EVENT.fullmatch(events + " " if events else ""), events
