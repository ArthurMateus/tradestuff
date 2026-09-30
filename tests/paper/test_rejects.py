# mypy: disable-error-code="union-attr"
"""F11.AC8: rejects (A8, failure case). With no book within paper.max_book_age_ms an open is refused ``no_book`` and
never retried. An exit is retried every exits.retry_interval_s until it fills, with ONE alert after
exits.alert_after_s (counted from the decision; pinned)."""

from __future__ import annotations

import pytest
from tests.paper.helpers import Env
from tests.paper.helpers import NewEnv

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from tests.paper.helpers import D0, make_config

FILL_T = D0 + 1000


@pytest.mark.unit
def test_F11_AC8_open_with_no_book_is_refused_no_book_logged_and_never_retried(new_env: NewEnv) -> None:
    e = new_env()
    e.submit(e.order("buy", "1.0"))
    events = e.advance(FILL_T + 5001)
    assert [(ev.kind, ev.reason, ev.client_order_id) for ev in events] == [("reject", "no_book", "c1")]
    (rec,) = e.records("paper_reject")
    assert rec.payload["reason"] == "no_book" and rec.payload["client_order_id"] == "c1"
    e.flat_book("SOL", FILL_T + 7000, "100")  # a book shows up later: the open is NOT retried
    assert e.advance(FILL_T + 8000) == []
    assert e.broker.position("SOL") is None and e.records("fill") == []
    assert len(e.records("paper_reject")) == 1


@pytest.mark.unit
def test_F11_AC8_an_add_with_no_book_is_also_refused_not_retried(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(D0 + 60_000)  # Amendment 11 (RISK-23): broker time only moves through advance_to
    e.submit(e.order("buy", "1.0", coid="add1", action=ActionKind.ADD, decided=D0 + 60_000, share="S2", trade="T2"))
    events = e.advance(D0 + 60_000 + 1000 + 5001)
    assert [(ev.kind, ev.reason) for ev in events] == [("reject", "no_book")]
    assert e.broker.position("SOL").qty == Qty("1.0")


def _close_without_book(e: Env, decided: int = D0 + 10_000) -> int:
    e.open_position("buy", "1.0", px="100")
    e.advance(decided)  # broker time reaches the exit's decision time (Amendment 10)
    e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=decided, px="95", reason="manual"))
    return decided


@pytest.mark.unit
def test_F11_AC8_an_exit_is_never_rejected_for_lack_of_a_book_it_keeps_retrying(new_env: NewEnv) -> None:
    e = new_env()
    decided = _close_without_book(e)
    for t in range(decided + 1000, decided + 60_000, 1000):
        events = e.advance(t)
        assert all(ev.kind != "reject" for ev in events)
    assert e.broker.position("SOL") is not None and len(e.fills()) == 1  # only the entry


@pytest.mark.unit
def test_F11_AC8_one_alert_after_alert_after_s_boundary_exact_and_only_one(new_env: NewEnv) -> None:
    e = new_env()
    decided = _close_without_book(e)  # exits.alert_after_s = 10
    assert e.advance(decided + 9999) == []
    assert "exit_unfilled" not in e.alerts.kinds()
    events = e.advance(decided + 10_000)
    assert [ev.kind for ev in events] == ["exit_unfilled_alert"]
    assert e.alerts.kinds().count("exit_unfilled") == 1
    for t in range(decided + 11_000, decided + 40_000, 1000):
        e.advance(t)
    assert e.alerts.kinds().count("exit_unfilled") == 1


@pytest.mark.unit
def test_F11_AC8_alert_delay_is_data_driven(new_env: NewEnv) -> None:
    e = new_env(config=make_config(exits__alert_after_s=5))
    decided = _close_without_book(e)
    e.advance(decided + 4999)
    assert "exit_unfilled" not in e.alerts.kinds()
    e.advance(decided + 5000)
    assert e.alerts.kinds().count("exit_unfilled") == 1


@pytest.mark.unit
def test_F11_AC8_the_exit_fills_as_soon_as_a_book_appears_after_the_retries(new_env: NewEnv) -> None:
    e = new_env()
    decided = _close_without_book(e)  # fill time = decided + 1000; attempts every 1 s after it
    for t in range(decided + 1000, decided + 20_000, 1000):
        e.advance(t)
    e.flat_book("SOL", decided + 20_000, "95")
    (ev,) = e.advance(decided + 20_000)
    assert ev.kind == "fill" and ev.fill.price == Price("95") and ev.fill.exit_reason == "manual"
    assert ev.trade is not None
    assert e.broker.position("SOL") is None
    assert e.alerts.kinds().count("exit_unfilled") == 1


@pytest.mark.unit
def test_F11_AC8_an_exit_that_fills_promptly_raises_no_alert(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.flat_book("SOL", D0 + 11_000, "95")
    e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=D0 + 10_000, px="95"))
    e.advance(D0 + 11_000)
    e.advance(D0 + 60_000)
    assert "exit_unfilled" not in e.alerts.kinds()
