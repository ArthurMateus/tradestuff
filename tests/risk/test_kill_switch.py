"""F10.AC6 kill switch (A4): pause, resume, persistence across restarts, flatten, all with market-data feeds down.

The Telegram ``/pause`` ``/resume`` ``/flatten <PIN>`` commands (F14) and the CLI ``pause`` ``resume`` ``flatten
--pin`` commands are thin callers of ``RiskGate.pause`` / ``resume`` / ``flatten``; their wiring is tested with F14.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from copytrade.core.domain import ActionKind
from copytrade.risk.gate import STATE_FILENAME
from tests.risk.conftest import NewRisk
from tests.risk.helpers import RiskEnv, rebuild_gate


def feeds_down(r: RiskEnv) -> None:
    r.account.raises = True
    r.paper.meta.fail = True
    r.xtime.unsynced = True

    def boom(coin: str, days: int) -> None:
        raise RuntimeError("candles down")

    r.returns.hourly_returns = boom  # type: ignore[method-assign]


@pytest.mark.integration
def test_F10_AC6_pause_refuses_new_opens_and_adds_at_once(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    assert r.gate.paused is False
    assert r.gate.check(r.open_req(coin="ETH")).approved
    r.gate.pause()  # no time passes, no mark: the very next decision is refused
    assert r.gate.paused is True
    for req in (r.open_req(coin="ETH"), r.add_req(share_id="S1")):
        out = r.gate.submit(req)
        assert (out.decision.approved, out.decision.reason, out.result) == (False, "paused", None)
    assert r.authority.issued == []


@pytest.mark.integration
def test_F10_AC6_resume_clears_the_pause(new_risk: NewRisk) -> None:
    r = new_risk()
    r.gate.pause()
    r.gate.resume()
    assert r.gate.paused is False
    assert r.gate.check(r.open_req()).approved


@pytest.mark.integration
def test_F10_AC6_pause_and_resume_are_idempotent(new_risk: NewRisk) -> None:
    r = new_risk()
    r.gate.resume()  # resume while running is harmless
    assert r.gate.paused is False
    r.gate.pause()
    r.gate.pause()
    assert r.gate.paused is True
    r.gate.resume()
    assert r.gate.paused is False


@pytest.mark.integration
def test_F10_AC6_the_pause_persists_across_a_restart_until_resume(new_risk: NewRisk) -> None:
    r = new_risk()
    r.gate.pause()
    assert (r.state_dir / STATE_FILENAME).exists()
    r2 = rebuild_gate(r)
    try:
        assert r2.gate.paused is True
        assert r2.gate.check(r2.open_req()).reason == "paused"
        r2.gate.resume()
    finally:
        r2.paper.ledger.close()
    r3 = rebuild_gate(r2)
    try:
        assert r3.gate.paused is False
        assert r3.gate.check(r3.open_req()).approved
    finally:
        r3.paper.ledger.close()


@pytest.mark.integration
def test_F10_AC6_a_fresh_install_with_no_state_file_starts_running_not_paused(new_risk: NewRisk) -> None:
    r = new_risk()
    assert r.gate.paused is False


@pytest.mark.integration
def test_F10_AC6_pause_resume_and_flatten_work_with_every_market_data_feed_down(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    feeds_down(r)
    r.gate.pause()
    assert r.gate.paused is True
    outs = r.gate.flatten(run_id="run1")
    assert len(outs) == 1 and outs[0].decision.approved and outs[0].result is not None and outs[0].result.accepted
    r.gate.resume()
    assert r.gate.paused is False


def _three_shares(r: RiskEnv) -> None:
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    r.seed("SOL", leader="L2", qty="0.5", entry="100", stop="98.5", share="S2")
    r.seed("DOGE", leader="L3", is_long=False, qty="3", entry="100", stop="101.5", share="D1")
    r.book("SOL", "100")
    r.book("DOGE", "100")


@pytest.mark.integration
def test_F10_AC6_flatten_closes_every_share_through_the_gate(new_risk: NewRisk) -> None:
    r = new_risk()
    _three_shares(r)
    outs = r.gate.flatten(run_id="run1")
    assert len(outs) == 3
    assert all(o.decision.approved and o.decision.action is ActionKind.CLOSE for o in outs)
    assert all(o.result is not None and o.result.accepted for o in outs)
    issued = {i.share_id: (i, t) for i, t in r.authority.issued}  # type: ignore[union-attr]
    assert set(issued) == {"S1", "S2", "D1"}
    assert (issued["S1"][0].side, issued["S1"][0].qty) == ("sell", D("1.0"))
    assert (issued["S2"][0].side, issued["S2"][0].qty) == ("sell", D("0.5"))
    assert (issued["D1"][0].side, issued["D1"][0].qty) == ("buy", D("3"))
    assert {i.exit_reason for i, _ in r.authority.issued} == {"flatten"}  # type: ignore[union-attr]
    r.fill()
    assert r.paper.broker.position("SOL") is None and r.paper.broker.position("DOGE") is None
    assert len(r.paper.trades()) == 3


@pytest.mark.integration
def test_F10_AC6_flatten_works_while_paused_halted_blacked_out_and_blind(new_risk: NewRisk) -> None:
    r = new_risk()
    _three_shares(r)
    r.gate.pause()
    r.calendar.reason = "fomc"
    r.account.equity = None
    outs = r.gate.flatten(run_id="run1")
    assert len(outs) == 3 and all(o.result is not None and o.result.accepted for o in outs)


@pytest.mark.integration
def test_F10_AC6_running_flatten_twice_sends_no_second_order_and_produces_no_extra_fills(new_risk: NewRisk) -> None:
    r = new_risk()
    _three_shares(r)
    r.gate.flatten(run_id="run1")
    again = r.gate.flatten(run_id="run1")
    assert all(o.result is None or not o.result.accepted for o in again)
    assert len(r.paper.records("paper_order")) == 6  # 3 seed orders + 3 flatten orders, none twice
    r.fill()
    assert len(r.paper.trades()) == 3


@pytest.mark.integration
def test_F10_AC6_flatten_with_nothing_open_is_a_no_op(new_risk: NewRisk) -> None:
    r = new_risk()
    assert list(r.gate.flatten(run_id="run1")) == []
