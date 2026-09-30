"""F10.AC5 loss limits and drawdown. The gate is fed equity marks (``mark_equity``, every ``eval.mark_interval_s`` in
production) and exchange time. 2026-09-21 00:00:00 UTC is a Monday, so ``M0`` is a day start AND a week start.

Marks are spaced so neither a "first mark of the day" nor a "last mark of the previous day" reading of the opening
equity changes the verdict (every day-to-day move in the slides is well inside the daily limit)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from tests.risk.conftest import NewRisk
from tests.risk.helpers import RiskEnv, rebuild_gate

M0 = 1_789_948_800_000  # Monday 2026-09-21 00:00:00 UTC
HOUR = 3_600_000
DAY = 24 * HOUR
WEEK = 7 * DAY


def mark(r: RiskEnv, now_ms: int, equity: str | D) -> None:
    r.at(now_ms)
    r.account.equity = D(equity)
    r.gate.mark_equity(now_ms)


def slide(r: RiskEnv, start_ms: int, e0: str | D, e1: str | D, days: int) -> int:
    """One mark a day (at 00:10 UTC) from ``e0`` to exactly ``e1`` over ``days`` days; returns the last mark's time."""
    a, b = D(e0), D(e1)
    last = start_ms
    for i in range(days + 1):
        last = start_ms + i * DAY
        mark(r, last, a + (b - a) * i / days)
    return last


# ---- daily ---------------------------------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "equity,halted",
    [("294.03", False), ("294.01", False), ("294.00", True), ("293.99", True), ("290", True), ("300", False), ("320", False)],
)
def test_F10_AC5_daily_loss_halts_at_exactly_minus_2_percent_of_the_days_opening_equity(
    new_risk: NewRisk, equity: str, halted: bool
) -> None:
    r = new_risk()
    mark(r, M0 + HOUR, "300")  # the day's opening equity
    mark(r, M0 + 10 * HOUR, equity)
    d = r.gate.check(r.open_req())
    assert d.approved is not halted
    assert d.reason == ("daily_loss_halt" if halted else None)


@pytest.mark.unit
def test_F10_AC5_daily_halt_limit_is_config(new_risk: NewRisk) -> None:
    ok = new_risk(risk__daily_loss_limit=D("0.05"), risk__weekly_loss_limit=D("0.10"))
    mark(ok, M0 + HOUR, "300")
    mark(ok, M0 + 10 * HOUR, "285.01")
    assert ok.gate.check(ok.open_req()).approved
    mark(ok, M0 + 11 * HOUR, "285.00")
    assert ok.gate.check(ok.open_req()).reason == "daily_loss_halt"


@pytest.mark.unit
def test_F10_AC5_the_daily_halt_holds_until_the_next_00_00_utc_even_if_equity_recovers(new_risk: NewRisk) -> None:
    r = new_risk()
    mark(r, M0 + HOUR, "300")
    mark(r, M0 + 10 * HOUR, "294.00")
    mark(r, M0 + 12 * HOUR, "300")  # recovered: still halted
    assert r.gate.check(r.open_req()).reason == "daily_loss_halt"
    mark(r, M0 + DAY - 60_000, "300")  # marks keep coming (B4: entries need a fresh mark); none after the boundary
    r.at(M0 + DAY - 1)
    assert r.gate.check(r.open_req()).reason == "daily_loss_halt"
    r.at(M0 + DAY)
    assert r.gate.check(r.open_req()).approved


@pytest.mark.unit
def test_F10_AC5_a_new_day_measures_from_its_own_opening_equity(new_risk: NewRisk) -> None:
    r = new_risk()
    mark(r, M0 + HOUR, "300")
    mark(r, M0 + 10 * HOUR, "294.00")  # halted Monday
    mark(r, M0 + DAY + HOUR, "294.00")  # Tuesday opens at 294
    mark(r, M0 + DAY + 10 * HOUR, "288.13")  # -1.99% of 294
    assert r.gate.check(r.open_req()).approved
    mark(r, M0 + DAY + 11 * HOUR, "288.12")  # -2.00% of 294 (5.88)
    assert r.gate.check(r.open_req()).reason == "daily_loss_halt"


@pytest.mark.unit
def test_F10_AC5_the_daily_halt_survives_a_restart(new_risk: NewRisk) -> None:
    r = new_risk()
    mark(r, M0 + HOUR, "300")
    mark(r, M0 + 10 * HOUR, "294.00")
    r2 = rebuild_gate(r)
    try:
        assert r2.gate.check(r2.open_req()).reason == "daily_loss_halt"
    finally:
        r2.paper.ledger.close()


@pytest.mark.unit
def test_F10_AC5_loss_halts_never_block_exits_and_are_not_a_pause(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    mark(r, M0 + HOUR, "300")
    mark(r, M0 + 10 * HOUR, "290")  # -3.3%: over the daily limit, far from the drawdown limit
    assert r.gate.check(r.open_req()).reason == "daily_loss_halt"
    assert r.gate.check(r.exit_req(share_id="S1")).approved
    assert r.gate.paused is False  # rule-based halt, not the kill switch (and not downtime)


@pytest.mark.unit
def test_F10_AC5_a_mark_with_unknown_equity_changes_nothing_and_never_raises(new_risk: NewRisk) -> None:
    r = new_risk()
    mark(r, M0 + HOUR, "300")
    r.account.equity = None
    r.gate.mark_equity(M0 + 2 * HOUR)
    r.account.raises = True
    r.gate.mark_equity(M0 + 3 * HOUR)
    r.account.raises = False
    mark(r, M0 + 10 * HOUR, "294.03")
    assert r.gate.check(r.open_req()).approved  # the opening equity is still 300


# ---- weekly --------------------------------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("final,halted", [("285.01", False), ("285.00", True), ("284.99", True)])
def test_F10_AC5_weekly_loss_halts_at_exactly_minus_5_percent_of_the_weeks_opening_equity(
    new_risk: NewRisk, final: str, halted: bool
) -> None:
    r = new_risk()
    last = slide(r, M0 + 10 * 60_000, "300", final, 4)  # Monday 00:10 to Friday 00:10, about -1% a day
    d = r.gate.check(r.open_req())
    assert r.xtime.now == last
    assert d.approved is not halted
    assert d.reason == ("weekly_loss_halt" if halted else None)


@pytest.mark.unit
def test_F10_AC5_the_weekly_halt_lasts_until_the_next_monday_00_00_utc(new_risk: NewRisk) -> None:
    r = new_risk()
    slide(r, M0 + 10 * 60_000, "300", "285.00", 4)
    mark(r, M0 + WEEK - 60_000, "285.00")  # marks keep coming (B4: entries need a fresh mark); none after the boundary
    r.at(M0 + WEEK - 1)
    assert r.gate.check(r.open_req()).reason == "weekly_loss_halt"
    r.at(M0 + WEEK)
    assert r.gate.check(r.open_req()).approved


@pytest.mark.unit
def test_F10_AC5_the_weekly_halt_survives_a_restart_and_never_blocks_exits(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    slide(r, M0 + 10 * 60_000, "300", "285.00", 4)
    r2 = rebuild_gate(r)
    try:
        assert r2.gate.check(r2.open_req()).reason == "weekly_loss_halt"
        assert r2.gate.check(r2.exit_req(share_id="S1")).approved
    finally:
        r2.paper.ledger.close()


@pytest.mark.unit
def test_F10_AC5_the_weekly_limit_is_config(new_risk: NewRisk) -> None:
    r = new_risk(risk__weekly_loss_limit=D("0.10"))
    slide(r, M0 + 10 * 60_000, "300", "270.01", 6)  # -9.997% over the week, about -1.7% a day
    assert r.gate.check(r.open_req()).approved


# ---- drawdown -------------------------------------------------------------------------------------------------------


def drawdown_run(r: RiskEnv, peak: str, final: str) -> None:
    """Mark 300, jump to ``peak``, then slide down to ``final`` over 28 days (about -0.5% a day, about -3.8% a week,
    so no daily or weekly halt interferes)."""
    mark(r, M0 + 10 * 60_000, "300")
    if D(peak) != 300:
        mark(r, M0 + DAY + 10 * 60_000, peak)
    slide(r, M0 + DAY + 10 * 60_000, peak, final, 28)


@pytest.mark.unit
@pytest.mark.parametrize(
    "peak,final,paused",
    [
        ("300", "255.01", False),  # -14.997%
        ("300", "255.00", True),  # exactly -15%
        ("300", "254.99", True),
        ("330", "280.51", False),  # drawdown is from the PEAK, not from the start
        ("330", "280.50", True),
    ],
)
def test_F10_AC5_drawdown_from_peak_at_15_percent_pauses_until_resume(
    new_risk: NewRisk, peak: str, final: str, paused: bool
) -> None:
    r = new_risk()
    drawdown_run(r, peak, final)
    assert r.gate.paused is paused
    d = r.gate.check(r.open_req())
    assert d.approved is not paused
    if paused:
        assert d.reason == "drawdown_pause"
    else:
        assert r.paper.records("risk_halt") == [] and r.paper.alerts.kinds() == []


@pytest.mark.integration
def test_F10_AC5_drawdown_writes_an_event_alerts_persists_across_restart_and_resume_clears_it(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    drawdown_run(r, "300", "255.00")
    halts = r.paper.records("risk_halt")
    assert len(halts) == 1 and halts[0].payload["reason"] == "drawdown"
    assert r.paper.alerts.kinds().count("drawdown_pause") == 1
    r.at(r.xtime.now + 60_000)
    r.gate.mark_equity(r.xtime.now)  # further marks while paused neither re-alert nor re-write
    assert len(r.paper.records("risk_halt")) == 1 and r.paper.alerts.kinds().count("drawdown_pause") == 1

    r2 = rebuild_gate(r)
    try:
        assert r2.gate.paused is True
        assert r2.gate.check(r2.open_req()).reason == "drawdown_pause"
        r2.gate.resume()
        assert r2.gate.paused is False
        assert r2.gate.check(r2.open_req()).approved
    finally:
        r2.paper.ledger.close()
    r3 = rebuild_gate(r2, marked=False)  # a mark at the still-breached equity would (correctly) pause it again
    try:
        assert r3.gate.paused is False  # the resume persisted too
    finally:
        r3.paper.ledger.close()


@pytest.mark.unit
def test_F10_AC5_drawdown_limit_is_the_frozen_eval_max_dd_and_marks_follow_eval_mark_interval_s() -> None:
    from copytrade.risk.settings import RiskSettings
    from tests.paper.helpers import make_config

    s = RiskSettings.from_config(make_config())
    assert s.max_drawdown == D("0.15")
    assert s.mark_interval_s == 60


@pytest.mark.unit
def test_F10_AC5_exits_are_never_blocked_by_a_drawdown_pause(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    drawdown_run(r, "300", "255.00")
    assert r.gate.paused
    assert r.gate.check(r.exit_req(share_id="S1")).approved
