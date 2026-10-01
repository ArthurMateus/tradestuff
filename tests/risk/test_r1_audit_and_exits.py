"""F10 review round 1, B8: the four test gaps that hand mutants M12, M23, M24 and M33 survived.

These pin behaviour the round-0 code already has; they are expected to PASS now and must keep passing after the fix
round (the plan records that each was checked against its mutant). Failures are injected at the OS boundary
(``os.write`` of a ledger line), never by replacing the Ledger.
"""

from __future__ import annotations

import pytest

from copytrade.ledger.errors import LedgerWriteError
from tests.risk.conftest import NewRisk
from tests.risk.helpers import T0, RiskEnv
from tests.risk.r1_helpers import failing_ledger_writes, mk, sent


def _two_shares(r: RiskEnv, count: int = 3) -> None:
    for i in range(count):
        r.seed("SOL", leader=f"LX{i}", qty="1.0", entry="100", stop="98.5", share=f"S{i}")
    r.book("SOL", "100")


# ---- M12: exits count toward the order-rate window --------------------------------------------------------------------


@pytest.mark.integration
def test_F10_B8_M12_exits_count_toward_the_orders_per_minute_window(new_risk: NewRisk) -> None:
    r = mk(new_risk, risk__max_orders_per_min=2)
    _two_shares(r)
    assert r.gate.check(r.open_req(coin="ETH")).approved  # nothing sent yet
    first = r.gate.submit(r.exit_req(share_id="S0", qty="0.4", close=False, signal_id="e0", tids=(1,)))
    assert first.result is not None and first.result.accepted
    assert r.gate.check(r.open_req(coin="ETH")).approved  # one order in the window of two
    second = r.gate.submit(r.exit_req(share_id="S1", qty="0.4", close=False, signal_id="e1", tids=(2,)))
    assert second.result is not None and second.result.accepted
    blocked = r.gate.check(r.open_req(coin="ETH"))
    assert (blocked.approved, blocked.reason) == (False, "rate_limit")


@pytest.mark.integration
def test_F10_B8_M12_an_exit_is_never_refused_by_the_rate_limit_itself(new_risk: NewRisk) -> None:
    r = mk(new_risk, risk__max_orders_per_min=1)
    _two_shares(r)
    for i in range(3):
        out = r.gate.submit(r.exit_req(share_id=f"S{i}", qty="0.4", close=False, signal_id=f"e{i}", tids=(i,)))
        assert out.decision.approved and out.result is not None and out.result.accepted, (i, out.decision.reason)
    assert r.gate.check(r.open_req(coin="ETH")).reason == "rate_limit"


@pytest.mark.integration
def test_F10_B8_M12_an_exit_leaves_the_window_after_a_minute(new_risk: NewRisk) -> None:
    r = mk(new_risk, risk__max_orders_per_min=1)
    _two_shares(r, 1)
    assert r.gate.submit(r.exit_req(share_id="S0", qty="0.4", close=False)).result is not None
    r.at(T0 + 59_999)
    assert r.gate.check(r.open_req(coin="ETH")).reason == "rate_limit"
    r.at(T0 + 60_000)
    assert r.gate.check(r.open_req(coin="ETH")).approved


# ---- M23: a re-sent exit is a duplicate, refused before any token -----------------------------------------------------


@pytest.mark.integration
def test_F10_B8_M23_a_re_sent_exit_is_refused_duplicate_order_before_a_token_is_issued(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _two_shares(r, 1)
    request = r.exit_req(share_id="S0", qty="0.4", close=False)
    first = r.gate.submit(request)
    assert first.result is not None and first.result.accepted
    assert sent(r) == 1
    again = r.gate.submit(request)
    assert (again.decision.approved, again.decision.reason, again.result) == (False, "duplicate_order", None)
    assert sent(r) == 1  # no second token
    assert r.paper.records("paper_reject") == []  # and the broker never saw it
    assert len(r.paper.records("paper_order")) == 2  # the seed's and the first exit's only


@pytest.mark.integration
def test_F10_B8_M23_a_re_sent_close_is_refused_duplicate_order_too(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _two_shares(r, 1)
    request = r.exit_req(share_id="S0", qty="1.0", close=True)
    assert r.gate.submit(request).result is not None
    again = r.gate.submit(request)
    assert (again.decision.approved, again.decision.reason, again.result) == (False, "duplicate_order", None)
    assert sent(r) == 1


# ---- M24: an entry whose audit record cannot be written is refused ---------------------------------------------------


@pytest.mark.integration
def test_F10_B8_M24_an_entry_whose_risk_decision_cannot_be_written_gets_no_token_and_no_broker_call(
    new_risk: NewRisk,
) -> None:
    r = mk(new_risk)
    r.book("SOL", "100")
    with failing_ledger_writes(b"risk_decision"):
        out = r.gate.submit(r.open_req())
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "ledger_failed", None)
    assert sent(r) == 0
    assert r.paper.records("paper_order") == [] and r.paper.records("paper_reject") == []
    assert r.paper.ledger.failed is True  # the failed append latched the ledger (A2)


@pytest.mark.integration
def test_F10_B8_M24_an_add_whose_risk_decision_cannot_be_written_is_refused_the_same_way(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S10")
    r.book("SOL", "100")
    before = sent(r)
    with failing_ledger_writes(b"risk_decision"):
        out = r.gate.submit(r.add_req(share_id="S10"))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "ledger_failed", None)
    assert sent(r) == before


@pytest.mark.integration
def test_F10_B8_M24_an_exit_is_still_sent_when_its_audit_record_cannot_be_written(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _two_shares(r, 1)
    with failing_ledger_writes(b"risk_decision"), pytest.raises(LedgerWriteError):
        # the audit append fails and latches the ledger; the exit is not blocked by it (it reaches the broker, whose
        # own append then raises). An entry in the same state would have been refused without a token.
        r.gate.submit(r.exit_req(share_id="S0", qty="1.0", close=True))
    assert sent(r) == 1


# ---- M33: an exit whose broker cannot advance propagates -----------------------------------------------------------------


def _pending_entry_about_to_expire(r: RiskEnv) -> None:
    """An accepted entry with no book: its window ends at T0 + 6000, and recording that reject needs a ledger write."""
    first = r.gate.submit(r.open_req(coin="ETH", share_id="SE", trade_id="TE", signal_id="pe", tids=(77,)))
    assert first.result is not None and first.result.accepted
    r.at(T0 + 7000)


@pytest.mark.integration
def test_F10_B8_M33_an_exit_whose_broker_advance_fails_propagates_instead_of_being_refused(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _two_shares(r, 1)
    _pending_entry_about_to_expire(r)
    with failing_ledger_writes(b"paper_reject"), pytest.raises(LedgerWriteError):
        r.gate.submit(r.exit_req(share_id="S0", qty="1.0", close=True))
    assert sent(r) == 1  # only the pending entry's token: the exit never got one


@pytest.mark.integration
def test_F10_B8_M33_an_entry_whose_broker_advance_fails_is_refused_broker_failed(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    _pending_entry_about_to_expire(r)
    with failing_ledger_writes(b"paper_reject"):
        out = r.gate.submit(r.open_req(coin="SOL", share_id="S1", trade_id="T1", signal_id="b", tids=(2,)))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "broker_failed", None)
    assert sent(r) == 1
