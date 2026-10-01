"""F10 review round 1, B4: loss limits must not fail open when equity marks stop, and a caller's ``now_ms`` is not trusted.

Pinned:

* An entry is refused ``equity_mark_stale`` before the first accepted equity mark, and when the last accepted mark is
  more than ``2 x eval.mark_interval_s`` old (exactly 2x is still fresh; one ms more is stale). Age is the decision's
  exchange time minus the ``now_ms`` the mark was accepted with. Exits and stops are never refused for it (AC7).
* ``mark_equity(now_ms)`` reads the exchange clock itself. A ``now_ms`` more than ``filter.max_signal_age_ms`` (the same
  skew tolerance F11 uses, default 5000 ms) ahead of the gate's exchange time is ignored: nothing changes, nothing is
  saved, it does not count as a mark, it cannot roll the day or week and cannot clear an active halt. Exactly at the
  tolerance is accepted. It never raises.
* A mark whose equity is unknown or whose source raises is not a mark (it does not refresh the age).
* The stale check comes after the equity read, so a gate with no known equity still says ``equity_unknown``.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from tests.risk.conftest import NewRisk
from tests.risk.helpers import T0, RiskEnv
from tests.risk.r1_helpers import mk, sent

DAY = 86_400_000
SKEW = 5000  # filter.max_signal_age_ms in the fixture config


def _state_bytes(r: RiskEnv) -> bytes:
    from copytrade.risk.gate import STATE_FILENAME

    path = r.state_dir / STATE_FILENAME
    return path.read_bytes() if path.exists() else b""


# ---- before the first mark ---------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_B4_an_entry_is_refused_before_the_first_equity_mark(new_risk: NewRisk) -> None:
    r = mk(new_risk, marked=False)
    r.book("SOL", "100")
    d = r.gate.check(r.open_req())
    assert (d.approved, d.reason) == (False, "equity_mark_stale")
    out = r.gate.submit(r.open_req())
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "equity_mark_stale", None)
    assert sent(r) == 0


@pytest.mark.integration
def test_F10_B4_an_add_is_refused_before_the_first_equity_mark(new_risk: NewRisk) -> None:
    r = mk(new_risk, marked=False)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S10")
    r.book("SOL", "100")
    out = r.gate.submit(r.add_req(share_id="S10"))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "equity_mark_stale", None)


@pytest.mark.integration
def test_F10_B4_the_first_accepted_mark_opens_entries(new_risk: NewRisk) -> None:
    r = mk(new_risk, marked=False)
    assert r.gate.check(r.open_req()).reason == "equity_mark_stale"
    r.gate.mark_equity(T0)
    assert r.gate.check(r.open_req()).approved


@pytest.mark.integration
def test_F10_B4_a_mark_with_unknown_equity_is_not_a_mark(new_risk: NewRisk) -> None:
    r = mk(new_risk, marked=False)
    r.account.equity = None
    r.gate.mark_equity(T0)
    r.account.equity = D(300)
    assert r.gate.check(r.open_req()).reason == "equity_mark_stale"


@pytest.mark.integration
def test_F10_B4_a_mark_whose_source_raises_is_not_a_mark(new_risk: NewRisk) -> None:
    r = mk(new_risk, marked=False)
    r.account.raises = True
    r.gate.mark_equity(T0)  # never raises
    r.account.raises = False
    assert r.gate.check(r.open_req()).reason == "equity_mark_stale"


@pytest.mark.unit
def test_F10_B4_unknown_equity_still_reports_equity_unknown_not_stale(new_risk: NewRisk) -> None:
    r = mk(new_risk, marked=False)
    r.account.equity = None
    assert r.gate.check(r.open_req()).reason == "equity_unknown"


# ---- staleness boundary ------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_B4_an_entry_is_fresh_up_to_exactly_twice_the_mark_interval(new_risk: NewRisk) -> None:
    r = mk(new_risk)  # eval.mark_interval_s is fixed at 60 by the compiled ceilings
    limit = 2 * 60 * 1000
    for age, expected_stale in ((0, False), (limit - 1, False), (limit, False), (limit + 1, True), (limit * 10, True)):
        r.at(T0 + age)
        d = r.gate.check(r.open_req())
        assert (d.reason == "equity_mark_stale") is expected_stale, (age, d.reason)
        if not expected_stale:
            assert d.approved, (age, d.reason)


@pytest.mark.integration
def test_F10_B4_a_stale_entry_reaches_neither_a_token_nor_the_broker(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.at(T0 + 120_001)
    r.book("SOL", "100")
    out = r.gate.submit(r.open_req())
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "equity_mark_stale", None)
    assert sent(r) == 0 and r.paper.records("paper_order") == []


@pytest.mark.integration
def test_F10_B4_a_fresh_mark_makes_a_stale_gate_trade_again(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.at(T0 + 130_000)
    assert r.gate.check(r.open_req()).reason == "equity_mark_stale"
    r.gate.mark_equity(T0 + 130_000)
    assert r.gate.check(r.open_req()).approved
    r.at(T0 + 130_000 + 120_000)
    assert r.gate.check(r.open_req()).approved
    r.at(T0 + 130_000 + 120_001)
    assert r.gate.check(r.open_req()).reason == "equity_mark_stale"


@pytest.mark.integration
def test_F10_B4_marks_that_fail_do_not_keep_the_gate_fresh(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.at(T0 + 100_000)
    r.account.equity = None
    r.gate.mark_equity(T0 + 100_000)  # equity unknown: not a mark
    r.account.raises = True
    r.gate.mark_equity(T0 + 100_000)  # source down: not a mark
    r.account.raises = False
    r.account.equity = D(300)
    r.at(T0 + 120_001)
    assert r.gate.check(r.open_req()).reason == "equity_mark_stale"


@pytest.mark.integration
def test_F10_B4_exits_and_stops_are_never_refused_for_a_stale_or_missing_mark(new_risk: NewRisk) -> None:
    r = mk(new_risk, marked=False)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S10")
    r.at(T0 + 10 * 60_000)
    r.book("SOL", "100")
    assert r.gate.check(r.exit_req(share_id="S10", close=False, qty="0.5")).approved
    stop = r.gate.place_stop(r.stop_req(share_id="S10", qty="1.0"))
    assert stop.decision.approved and stop.result is not None and stop.result.accepted
    closed = r.gate.submit(r.exit_req(share_id="S10", qty="1.0"))
    assert closed.decision.approved and closed.result is not None and closed.result.accepted


# ---- a caller's now_ms is not trusted ------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("ahead_ms, accepted", [(0, True), (SKEW - 1, True), (SKEW, True), (SKEW + 1, False), (DAY, False)])
def test_F10_B4_a_mark_beyond_the_skew_tolerance_ahead_of_exchange_time_is_ignored(
    new_risk: NewRisk, ahead_ms: int, accepted: bool
) -> None:
    r = mk(new_risk, marked=False)
    r.gate.mark_equity(T0 + ahead_ms)  # exchange time is T0
    assert (r.gate.check(r.open_req()).reason != "equity_mark_stale") is accepted


@pytest.mark.integration
def test_F10_B4_the_skew_tolerance_is_the_configured_filter_max_signal_age(new_risk: NewRisk) -> None:
    r = mk(new_risk, marked=False, filter__max_signal_age_ms=2000)
    r.gate.mark_equity(T0 + 2001)
    assert r.gate.check(r.open_req()).reason == "equity_mark_stale"
    r.gate.mark_equity(T0 + 2000)
    assert r.gate.check(r.open_req()).approved


@pytest.mark.integration
def test_F10_B4_a_future_mark_does_not_clear_an_active_daily_halt_or_roll_the_day(new_risk: NewRisk) -> None:
    r = mk(new_risk)  # marked at T0 with equity 300: the day's opening equity
    r.account.equity = D(293)  # -2.33 %: the 2 % daily limit
    r.at(T0 + 1000)
    r.gate.mark_equity(T0 + 1000)
    r.book("SOL", "100")
    assert r.gate.check(r.open_req()).reason == "daily_loss_halt"
    halted_state = _state_bytes(r)
    r.account.equity = D(300)  # recovered (or a bad equity source)
    r.gate.mark_equity(T0 + DAY + 5000)  # a bad timestamp from the caller, a day ahead
    assert _state_bytes(r) == halted_state  # nothing rolled, nothing saved
    assert r.gate.check(r.open_req()).reason == "daily_loss_halt"
    r.account.equity = D(293)
    r.at(T0 + 2000)
    r.gate.mark_equity(T0 + 2000)  # real time again: the halt is still the original one
    assert r.gate.check(r.open_req()).reason == "daily_loss_halt"


@pytest.mark.integration
def test_F10_B4_a_future_mark_does_not_roll_the_week(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.account.equity = D(280)  # -6.7 %: the 5 % weekly limit (and the daily one)
    r.at(T0 + 1000)
    r.gate.mark_equity(T0 + 1000)
    before = _state_bytes(r)
    r.account.equity = D(300)
    r.gate.mark_equity(T0 + 8 * DAY)
    assert _state_bytes(r) == before
    assert r.gate.check(r.open_req()).reason in ("daily_loss_halt", "weekly_loss_halt")


@pytest.mark.integration
def test_F10_B4_a_future_mark_does_not_clear_a_drawdown_pause(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.account.equity = D(250)  # -16.7 %: past the 15 % drawdown
    r.at(T0 + 1000)
    r.gate.mark_equity(T0 + 1000)
    assert r.gate.paused is True
    r.account.equity = D(300)
    r.gate.mark_equity(T0 + 3 * DAY)
    assert r.gate.paused is True


@pytest.mark.integration
def test_F10_B4_marks_stamped_in_the_past_never_raise_and_never_make_a_fresh_gate_stale(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.gate.mark_equity(T0 + 10 * DAY)
    r.gate.mark_equity(-1)
    r.gate.mark_equity(0)
    r.at(T0 + 10)
    assert r.gate.check(r.open_req()).approved  # the round-0 mark at T0 is still the fresh one


@pytest.mark.integration
def test_F10_B4_an_ignored_future_mark_does_not_refresh_a_stale_gate(new_risk: NewRisk) -> None:
    r = mk(new_risk)
    r.at(T0 + 130_000)
    r.gate.mark_equity(T0 + 130_000 + SKEW + 1)
    assert r.gate.check(r.open_req()).reason == "equity_mark_stale"
