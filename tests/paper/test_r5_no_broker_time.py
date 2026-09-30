# mypy: disable-error-code="union-attr"
"""F11 round 5, RISK-26: no entry without broker time.

Before the first ``advance_to`` (and after every restart) the broker's time is 0, so it has nothing to judge an
entry's decision time against: the stale and too-far-ahead checks never fire. An OPEN or ADD is therefore refused
``no_broker_time`` until ``advance_to`` has been called. Exits, stops, marks and delistings are unaffected.
"""

from __future__ import annotations

from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.paper.types import GateToken, MarkUpdate, OrderIntent
from tests.paper.helpers import D0, HOUR_MS, NewEnv, restart

TOL = 5000  # filter.max_signal_age_ms in the fixture config
ACK = 1000
ENTRIES = [ActionKind.OPEN, ActionKind.ADD]
# what the reproduction showed: decided a day ago (a backdated trade), an hour ahead (a made-up price), and at 0 itself
DECIDED = [
    pytest.param(D0 - 24 * HOUR_MS, id="24h_ago"),
    pytest.param(D0 + HOUR_MS, id="1h_ahead"),
    pytest.param(0, id="exactly_time_zero"),
    pytest.param(D0, id="now_by_the_local_clock"),
]


def _kinds(e: Any, kind: str) -> list[Any]:
    return [r.payload for r in e.records(kind)]


# ---------------------------------------------------------------------------------- refused at time 0


@pytest.mark.unit
@pytest.mark.parametrize("action", ENTRIES)
@pytest.mark.parametrize("decided", DECIDED)
def test_R5_RISK26_an_entry_is_refused_no_broker_time_at_broker_time_zero(
    new_env: NewEnv, action: ActionKind, decided: int
) -> None:
    e = new_env()
    e.flat_book("SOL", decided + ACK, "100")
    result = e.submit(e.order("buy", "1.0", coid="e1", action=action, decided=decided))
    assert (result.accepted, result.reason) == (False, "no_broker_time")


@pytest.mark.unit
@pytest.mark.parametrize("action", ENTRIES)
@pytest.mark.parametrize("decided", DECIDED)
def test_R5_RISK26_a_refused_entry_writes_no_order_creates_no_state_and_does_not_latch(
    new_env: NewEnv, action: ActionKind, decided: int
) -> None:
    e = new_env()
    e.flat_book("SOL", decided + ACK, "100")
    cash = e.broker.cash_usd()
    assert e.submit(e.order("buy", "1.0", coid="e1", action=action, decided=decided)).reason == "no_broker_time"
    assert _kinds(e, "paper_order") == []  # nothing accepted, nothing in flight
    assert [p["reason"] for p in _kinds(e, "paper_reject")] == ["no_broker_time"]  # logged like any refusal
    assert e.broker._pending == {}  # noqa: SLF001 - no order was queued
    assert e.broker.position("SOL") is None and e.broker.cash_usd() == cash
    assert e.advance(D0 + 100 * HOUR_MS) == []  # nothing fills later, at any book, and no funding is charged
    assert e.fills() == [] and e.records("paper_funding") == []
    assert e.broker.position("SOL") is None and e.broker.cash_usd() == cash
    # not latched (A2): a later valid entry is still served
    e.flat_book("SOL", D0 + 100 * HOUR_MS + ACK, "100")
    later = e.submit(e.order("buy", "1.0", coid="e2", decided=D0 + 100 * HOUR_MS))
    assert (later.accepted, later.reason) == (True, None)


@pytest.mark.unit
def test_R5_RISK26_the_refused_entry_consumes_its_token_as_any_refused_order_does(new_env: NewEnv) -> None:
    e = new_env()
    intent = e.order("buy", "1.0", coid="e1", decided=D0)
    token = e.token(intent)
    assert e.broker.submit(intent, token).reason == "no_broker_time"
    again = e.broker.submit(intent, token)
    assert (again.accepted, again.reason) == (False, "gate_token_reused")
    e.advance(D0)  # the same token stays spent after broker time exists
    assert e.broker.submit(intent, token).reason == "gate_token_reused"


@pytest.mark.unit
def test_R5_RISK26_an_invalid_token_is_still_invalid_gate_token_and_is_not_consumed(new_env: NewEnv) -> None:
    """The token check comes first: a forged token learns nothing about broker time, and leaves the real one unspent."""
    e = new_env()
    intent = e.order("buy", "1.0", coid="e1", decided=D0)
    forged = GateToken(token_id="forged-1", intent_digest="0" * 64, mac="0" * 64)
    assert e.broker.submit(intent, forged).reason == "invalid_gate_token"
    real = e.token(intent)
    assert e.broker.submit(intent, real).reason == "no_broker_time"  # the real token is still unspent (and now spent)


@pytest.mark.unit
def test_R5_RISK26_a_duplicate_client_order_id_is_still_reported_as_a_duplicate(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", coid="dup")  # broker time D0 from here
    e2 = restart(e)  # broker time 0 again, the ledger remembers "dup"
    try:
        result = e2.submit(e2.order("buy", "1.0", coid="dup", decided=D0 + 60_000))
        assert (result.accepted, result.reason) == (False, "duplicate_client_order_id")
    finally:
        e2.ledger.close()


@pytest.mark.unit
def test_R5_RISK26_advance_to_zero_gives_no_broker_time(new_env: NewEnv) -> None:
    e = new_env()
    e.advance(0)
    e.flat_book("SOL", D0 + ACK, "100")
    assert e.submit(e.order("buy", "1.0", coid="e1", decided=D0)).reason == "no_broker_time"


# ------------------------------------------------------------------------ accepted once broker time exists


@pytest.mark.unit
@pytest.mark.parametrize("action", ENTRIES)
def test_R5_RISK26_after_the_first_advance_to_the_same_entry_is_accepted_and_fills_at_its_own_time(
    new_env: NewEnv, action: ActionKind
) -> None:
    e = new_env()
    e.flat_book("SOL", D0 + ACK, "100")
    e.flat_book("SOL", D0 - 24 * HOUR_MS + ACK, "70")  # a day-old book must never be used
    intent = e.order("buy", "1.0", coid="e1", action=action, decided=D0)
    assert e.broker.submit(intent, e.token(intent)).reason == "no_broker_time"
    e.advance(D0)
    fresh = e.broker.submit(intent, e.token(intent))  # same entry, a fresh token
    assert (fresh.accepted, fresh.reason) == (True, None)
    (event,) = e.advance(D0 + ACK)
    assert event.fill.time.ms == D0 + ACK and event.fill.price == Price("100")
    assert e.broker.position("SOL").qty == event.fill.qty


@pytest.mark.unit
@pytest.mark.parametrize(
    ("offset", "reason"),
    [
        (-1, "stale_decision"),
        (0, None),  # decided exactly at broker time
        (TOL, None),  # exactly at the tolerance
        (TOL + 1, "bad_decision_time"),
    ],
)
def test_R5_RISK26_once_broker_time_exists_the_stale_and_ahead_checks_apply_at_their_boundaries(
    new_env: NewEnv, offset: int, reason: str | None
) -> None:
    e = new_env()
    e.advance(D0)
    e.flat_book("SOL", D0 + offset + ACK, "100")
    result = e.submit(e.order("buy", "1.0", coid="e1", decided=D0 + offset))
    assert (result.accepted, result.reason) == (reason is None, reason)


@pytest.mark.unit
def test_R5_RISK26_a_24h_old_entry_after_the_first_advance_is_stale_not_no_broker_time(new_env: NewEnv) -> None:
    e = new_env()
    e.advance(D0)
    assert e.submit(e.order("buy", "1.0", coid="e1", decided=D0 - 24 * HOUR_MS)).reason == "stale_decision"


# ---------------------------------------------------- everything else is not touched by the rule


@pytest.mark.unit
@pytest.mark.parametrize("action", [ActionKind.CLOSE, ActionKind.REDUCE])
@pytest.mark.parametrize("decided", DECIDED)
def test_R5_RISK26_an_exit_at_time_zero_is_not_refused_by_the_rule(
    new_env: NewEnv, action: ActionKind, decided: int
) -> None:
    e = new_env()
    result = e.submit(e.order("sell", "1.0", coid="x1", action=action, decided=decided))
    # there is no position to exit yet, so the ordinary rule answers; the point is that it is not no_broker_time
    assert (result.accepted, result.reason) == (False, "exceeds_position")


@pytest.mark.unit
def test_R5_RISK26_a_stop_at_time_zero_is_not_refused_by_the_rule(new_env: NewEnv) -> None:
    e = new_env()
    result = e.stop("sl", "sell", "1.0", "90")
    assert (result.accepted, result.reason) == (False, "exceeds_position")


@pytest.mark.unit
def test_R5_RISK26_a_mark_at_time_zero_is_processed_not_dropped_or_latched(new_env: NewEnv) -> None:
    e = new_env()
    assert list(e.broker.on_mark(MarkUpdate("SOL", Price("80"), D0))) == []
    assert list(e.broker.on_mark(MarkUpdate("SOL", Price("80"), D0 + 30 * 24 * HOUR_MS))) == []
    assert e.broker.submit(*_entry_and_token(e)).reason == "no_broker_time"  # still served, and still no broker time
    assert e.advance(D0) == []  # a mark never moved broker time, never latched


def _entry_and_token(e: Any) -> tuple[OrderIntent, GateToken]:
    intent = e.order("buy", "1.0", coid="m1", decided=D0)
    return intent, e.token(intent)


@pytest.mark.unit
def test_R5_RISK26_a_delisting_at_time_zero_is_recorded_not_dropped(new_env: NewEnv) -> None:
    e = new_env()
    assert list(e.broker.on_delist("SOL", Price("95"), D0)) == []
    e.advance(D0)
    e.flat_book("SOL", D0 + ACK, "100")
    result = e.submit(e.order("buy", "1.0", coid="e1", decided=D0))
    assert (result.accepted, result.reason) == (False, "delisted")  # the coin is delisted; broker time is not 0 now


@pytest.mark.unit
def test_R5_RISK26_a_mark_and_a_delisting_still_protect_an_open_position_after_the_first_advance(
    new_env: NewEnv,
) -> None:
    """The rule is about entries only: protection (liquidation by a mark, force-settle by a delisting) is unchanged."""
    e = new_env()
    e.open_position("buy", "1.0", px="100", leverage=20)
    (event,) = e.broker.on_mark(MarkUpdate("SOL", Price("50"), D0 + 2000))
    assert event.kind == "liquidated"
    e2 = new_env()
    e2.open_position("buy", "1.0", px="100")
    (settled,) = e2.broker.on_delist("SOL", Price("95"), D0 + 30_000)
    assert settled.kind == "delisted_force_settle"


# ---------------------------------------------------------------------------------------------- restart


@pytest.mark.unit
@pytest.mark.parametrize("action", ENTRIES)
def test_R5_RISK26_a_restarted_broker_over_a_non_empty_ledger_refuses_entries_until_advance_to(
    new_env: NewEnv, action: ActionKind
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", coid="before")
    assert e.records("paper_order")  # the ledger is not empty
    later = D0 + 10 * HOUR_MS
    e2 = restart(e)
    try:
        e2.flat_book("SOL", later + ACK, "100")
        assert e2.broker._now_ms == 0  # noqa: SLF001 - restarts at time 0, whatever the clock says
        for decided in (D0 - 24 * HOUR_MS, later, later + HOUR_MS):
            result = e2.submit(e2.order("buy", "1.0", coid=f"r-{decided}", action=action, decided=decided))
            assert (result.accepted, result.reason) == (False, "no_broker_time")
        e2.advance(later)
        ok = e2.submit(e2.order("buy", "1.0", coid="r-ok", action=action, decided=later))
        assert (ok.accepted, ok.reason) == (True, None)
        (event,) = e2.advance(later + ACK)
        assert event.fill.time.ms == later + ACK
    finally:
        e2.ledger.close()
