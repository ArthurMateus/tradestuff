"""F3.AC1: REST weight table, sliding 60 s budget, scoring share, priority of exits and reconciliation.

Spec: 04-spec.md F3.AC1, §3.2 hl.rest_weight_budget_per_min / hl.scoring_weight_share / hl.weight_*, invariant B4.
The clock is a fake; there is no sleeping. The 2-hour load is simulated in fake time.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.hl.budget import Priority, QueuedRequest, RateBudget, request_weight
from tests.hl.support import MINUTE, SECOND, FakeClock, make_config, max_window_sum, oracle_weight

pytestmark = pytest.mark.unit

C, S = Priority.CRITICAL, Priority.SCORING


def budget(per_min: int = 900, share: str = "0.5") -> tuple[RateBudget, FakeClock]:
    clock = FakeClock()
    return RateBudget(budget_per_min=per_min, scoring_share=Decimal(share), clock=clock), clock


# --- weights ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("rtype", "items", "expected"),
    [
        ("meta", 0, 20),
        ("l2Book", 0, 2),
        ("allMids", 0, 2),
        ("clearinghouseState", 0, 2),
        ("userFills", 0, 20),
        ("userFills", 19, 20),
        ("userFills", 20, 21),
        ("userFills", 39, 21),
        ("userFills", 40, 22),
        ("userFillsByTime", 2000, 120),
        ("userFunding", 20, 21),
        ("fundingHistory", 100, 25),
        ("candleSnapshot", 0, 20),
        ("candleSnapshot", 59, 20),
        ("candleSnapshot", 60, 21),
        ("candleSnapshot", 5000, 103),
    ],
    ids=repr,
)
def test_F3_AC1_weight_table(rtype: str, items: int, expected: int) -> None:
    assert request_weight(rtype, items, make_config()) == expected == oracle_weight(rtype, items)


def test_F3_AC1_userRole_and_portfolio_weights_come_from_config() -> None:
    cfg = make_config()
    assert request_weight("userRole", 0, cfg) == cfg["hl.weight_userRole"] == 60
    assert request_weight("portfolio", 0, cfg) == cfg["hl.weight_portfolio"] == 20
    cfg2 = make_config(hl__weight_userRole=100, hl__weight_portfolio=45)
    assert request_weight("userRole", 0, cfg2) == 100
    assert request_weight("portfolio", 0, cfg2) == 45


def test_F3_AC1_negative_item_count_is_rejected() -> None:
    with pytest.raises(ValueError):
        request_weight("userFills", -1, make_config())


# --- the window ---------------------------------------------------------------------------------------------

def test_F3_AC1_budget_boundary_exactly_at_one_below_and_one_above() -> None:
    b, _ = budget(100)
    assert all(b.try_acquire(20, C) for _ in range(5))  # exactly at the limit
    assert b.used() == 100
    assert not b.try_acquire(1, C)  # one above
    assert b.used() == 100  # a refusal records nothing


def test_F3_AC1_one_below_the_limit_leaves_room_for_exactly_the_remainder() -> None:
    b, _ = budget(100)
    assert b.try_acquire(99, C)
    assert b.try_acquire(1, C)
    assert not b.try_acquire(1, C)


def test_F3_AC1_an_entry_leaves_the_window_exactly_60_seconds_after_it_was_recorded() -> None:
    b, clock = budget(100)
    for _ in range(5):
        assert b.try_acquire(20, C)
    clock.advance(MINUTE - 1)
    assert not b.try_acquire(20, C)
    clock.advance(1)
    assert b.try_acquire(20, C)


def test_F3_AC1_the_window_slides_it_does_not_reset_on_minute_boundaries() -> None:
    b, clock = budget(100)
    assert b.try_acquire(60, C)  # t0
    clock.advance(30 * SECOND)
    assert b.try_acquire(40, C)  # t0 + 30 s: window is full
    clock.advance(29 * SECOND)  # t0 + 59 s
    assert not b.try_acquire(1, C)
    clock.advance(1 * SECOND)  # t0 + 60 s: the first 60 left, the 40 stays
    assert b.try_acquire(60, C)
    assert not b.try_acquire(1, C)


def test_F3_AC1_weight_larger_than_the_whole_budget_is_refused_and_can_never_succeed() -> None:
    b, _ = budget(100)
    assert not b.try_acquire(101, C)
    assert b.wait_ms(101, C) is None


def test_F3_AC1_wait_ms_counts_down_to_when_the_window_frees() -> None:
    b, clock = budget(100)
    for _ in range(5):
        b.try_acquire(20, C)
    assert b.wait_ms(20, C) == MINUTE
    clock.advance(10 * SECOND)
    assert b.wait_ms(20, C) == 50 * SECOND
    clock.advance(50 * SECOND)
    assert b.wait_ms(20, C) == 0


def test_F3_AC1_charge_records_late_weight_without_raising_even_over_the_limit() -> None:
    b, _ = budget(100)
    assert b.try_acquire(100, C)
    b.charge(6, C)  # items returned, known only after the response
    assert b.used() == 106
    assert not b.try_acquire(1, C)


# --- scoring share -------------------------------------------------------------------------------------------

def test_F3_AC1_scoring_cap_is_floor_of_budget_times_share() -> None:
    assert budget(900, "0.5")[0].scoring_cap == 450
    assert budget(900, "0.33")[0].scoring_cap == 297
    assert budget(1000, "0.333")[0].scoring_cap == 333
    assert budget(100, "0.1")[0].scoring_cap == 10


def test_F3_AC1_scoring_stops_at_its_share_but_critical_may_use_the_rest() -> None:
    b, _ = budget(900, "0.33")
    assert all(b.try_acquire(20, S) for _ in range(14))  # 280 <= 297
    assert not b.try_acquire(20, S)  # 300 > 297
    assert b.try_acquire(17, S)  # exactly 297
    assert not b.try_acquire(1, S)  # one above the cap
    assert b.scoring_used() == 297
    assert b.try_acquire(603, C)  # critical takes the remaining 603: total exactly 900
    assert not b.try_acquire(1, C)
    assert b.used() == 900


def test_F3_AC1_critical_traffic_is_not_limited_by_the_scoring_share() -> None:
    b, _ = budget(900, "0.1")
    assert b.try_acquire(900, C)
    assert b.scoring_used() == 0


def test_F3_AC1_scoring_request_above_its_cap_can_never_be_served() -> None:
    b, _ = budget(100, "0.1")  # scoring cap 10 < the 20 of any info request
    assert not b.try_acquire(20, S)
    assert b.wait_ms(20, S) is None


def test_F3_AC1_full_window_of_critical_traffic_blocks_scoring_until_it_frees() -> None:
    b, clock = budget(900, "0.5")
    assert b.try_acquire(900, C)
    assert not b.try_acquire(20, S)
    assert b.wait_ms(20, S) == MINUTE
    clock.advance(MINUTE)
    assert b.try_acquire(20, S)


# --- priority queue ------------------------------------------------------------------------------------------

def q(tag: str, weight: int, prio: Priority) -> QueuedRequest:
    return QueuedRequest(tag=tag, weight=weight, priority=prio)


def test_F3_AC1_drain_serves_critical_before_scoring_and_is_fifo_within_a_class() -> None:
    b, _ = budget(900)
    for r in (q("s1", 20, S), q("s2", 20, S), q("c1", 20, C), q("s3", 2, S), q("c2", 2, C)):
        b.enqueue(r)
    assert [r.tag for r in b.drain()] == ["c1", "c2", "s1", "s2", "s3"]
    assert b.pending() == 0


def test_F3_AC1_a_waiting_critical_request_blocks_cheaper_scoring_requests_behind_it() -> None:
    b, clock = budget(100)
    assert b.try_acquire(90, C)
    b.enqueue(q("crit", 20, C))  # does not fit (110 > 100)
    b.enqueue(q("score", 2, S))  # would fit, but must not jump the critical request
    assert b.drain() == []
    assert b.pending() == 2
    clock.advance(MINUTE)
    assert [r.tag for r in b.drain()] == ["crit", "score"]


def test_F3_AC1_drain_only_returns_what_fits_and_keeps_the_rest_queued() -> None:
    b, _ = budget(100)
    for i in range(7):
        b.enqueue(q(f"c{i}", 20, C))
    assert [r.tag for r in b.drain()] == ["c0", "c1", "c2", "c3", "c4"]
    assert b.pending() == 2


def test_F3_AC1_two_hour_simulated_load_keeps_every_window_and_the_scoring_share_and_serves_critical_first() -> None:
    per_min, share = 900, Decimal("0.5")
    b, clock = budget(per_min, str(share))
    rng = random.Random(20260929)
    served: list[tuple[int, int, Priority]] = []
    enqueued_at: dict[str, int] = {}
    waiting_critical: set[str] = set()
    critical_waits: list[int] = []
    n = 0
    for _ in range(2 * 3600):
        clock.advance(SECOND)
        for _ in range(2 if rng.random() < 0.3 else 0):
            n += 1
            b.enqueue(q(f"c{n}", rng.choice([2, 20, 22]), C))
            enqueued_at[f"c{n}"] = clock.now_ms()
            waiting_critical.add(f"c{n}")
        for _ in range(5 if b.pending() < 100 else 0):  # scoring always wants more than its share (bounded backlog)
            n += 1
            b.enqueue(q(f"s{n}", rng.choice([20, 21, 22]), S))
        out = b.drain()
        for r in out:
            served.append((clock.now_ms(), r.weight, r.priority))
            if r.priority is C:
                critical_waits.append(clock.now_ms() - enqueued_at[r.tag])
                waiting_critical.discard(r.tag)
        if waiting_critical:  # critical work still waits: no scoring may have been served in this drain
            assert all(r.priority is C for r in out)
    all_ev = [(t, w) for t, w, _ in served]
    scoring_ev = [(t, w) for t, w, p in served if p is S]
    assert max_window_sum(all_ev) <= per_min
    assert max_window_sum(scoring_ev) <= int(per_min * share)
    assert sum(w for _, w in scoring_ev) >= 30_000  # scoring is throttled, not starved
    assert max(critical_waits) <= MINUTE  # critical work is never stuck behind scoring


@given(
    steps=st.lists(
        st.tuples(st.integers(0, 90_000), st.integers(1, 130), st.sampled_from([C, S])), min_size=1, max_size=120
    ),
    per_min=st.integers(100, 1100),
    share=st.sampled_from(["0.1", "0.25", "0.5", "0.8"]),
)
def test_F3_AC1_property_no_window_ever_exceeds_the_budget_or_the_scoring_cap(
    steps: list[tuple[int, int, Priority]], per_min: int, share: str
) -> None:
    b, clock = budget(per_min, share)
    accepted: list[tuple[int, int, Priority]] = []
    for dt, weight, prio in steps:
        clock.advance(dt)
        if b.try_acquire(weight, prio):
            accepted.append((clock.now_ms(), weight, prio))
    assert max_window_sum([(t, w) for t, w, _ in accepted]) <= per_min
    assert max_window_sum([(t, w) for t, w, p in accepted if p is S]) <= int(per_min * Decimal(share))
