"""F10.AC7 fail closed (A2) and the broker-facing contracts: every doubt refuses entries (with the reason logged),
exits are never refused for caps, limits, pauses, calendar or missing data."""

from __future__ import annotations

import errno
import logging
import os
from decimal import Decimal as D

import pytest

from copytrade.ledger.errors import LedgerWriteError
from copytrade.risk.ports import AlwaysAllowCalendar
from copytrade.risk.settings import RiskSettings
from copytrade.risk.gate import STATE_FILENAME
from tests.risk.conftest import NewRisk
from tests.risk.helpers import RiskEnv


def _fsync_failing(real: object = os.fsync):  # type: ignore[no-untyped-def]
    def fsync(fd: int) -> None:
        raise OSError(errno.EIO, "I/O error")

    return fsync


def _refused(r: RiskEnv, reason: str | None = None) -> None:
    before = len(r.authority.issued)
    out = r.gate.submit(r.open_req())
    assert out.decision.approved is False
    if reason is not None:
        assert out.decision.reason == reason
    assert out.result is None
    assert len(r.authority.issued) == before
    assert r.paper.records("paper_order") == []


@pytest.mark.unit
def test_F10_AC7_unknown_equity_refuses_entries(new_risk: NewRisk) -> None:
    r = new_risk(equity=None)
    _refused(r, "equity_unknown")


@pytest.mark.unit
@pytest.mark.parametrize("equity", ["0", "-5"])
def test_F10_AC7_zero_or_negative_equity_refuses_entries(new_risk: NewRisk, equity: str) -> None:
    r = new_risk(equity=equity)
    _refused(r, "equity_unknown")


@pytest.mark.unit
def test_F10_AC7_an_exception_in_the_equity_source_is_a_refusal_never_a_raise(new_risk: NewRisk) -> None:
    r = new_risk()
    r.account.raises = True
    _refused(r, "check_error")


@pytest.mark.unit
def test_F10_AC7_an_exception_in_the_share_book_is_a_refusal(new_risk: NewRisk) -> None:
    r = new_risk()
    r.shares.raises = True
    _refused(r, "check_error")


@pytest.mark.unit
def test_F10_AC7_malformed_request_values_are_a_refusal_not_an_exception(new_risk: NewRisk) -> None:
    r = new_risk()
    for bad in (D("NaN"), D("Infinity"), D(-1), D(0)):
        out = r.gate.submit(r.open_req(vol_mult=bad))
        assert out.decision.approved is False and out.result is None
    assert r.authority.issued == []


@pytest.mark.unit
def test_F10_AC7_no_market_meta_refuses_entries_as_meta_unavailable(new_risk: NewRisk) -> None:
    r = new_risk()
    r.paper.meta.fail = True
    _refused(r, "meta_unavailable")


@pytest.mark.unit
def test_F10_AC7_an_unknown_coin_is_refused(new_risk: NewRisk) -> None:
    r = new_risk()
    out = r.gate.submit(r.open_req(coin="NOSUCH"))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "unknown_coin", None)


@pytest.mark.unit
def test_F10_AC7_an_unsynced_clock_refuses_entries(new_risk: NewRisk) -> None:
    r = new_risk()
    r.xtime.unsynced = True
    _refused(r, "clock_unsynced")


@pytest.mark.unit
def test_F10_AC7_an_unverified_ledger_refuses_entries_and_never_raises(
    new_risk: NewRisk, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = new_risk()
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", _fsync_failing())
        with pytest.raises(LedgerWriteError):
            r.paper.ledger.append("probe", {"n": 1})
    assert r.paper.ledger.failed
    out = r.gate.submit(r.open_req())
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "ledger_failed", None)
    assert r.authority.issued == []


@pytest.mark.unit
def test_F10_AC7_an_unreadable_risk_state_file_refuses_entries_until_fixed(new_risk: NewRisk) -> None:
    from tests.risk.helpers import rebuild_gate

    r = new_risk()
    r.gate.pause()
    assert (r.state_dir / STATE_FILENAME).exists()
    r.paper.ledger.close()
    (r.state_dir / STATE_FILENAME).write_bytes(b"\x00not json{")
    r2 = rebuild_gate(r)
    try:
        d = r2.gate.check(r2.open_req())
        assert (d.approved, d.reason) == (False, "risk_state_unknown")
    finally:
        r2.paper.ledger.close()


@pytest.mark.unit
def test_F10_AC7_the_refusal_reason_is_logged(new_risk: NewRisk, caplog: pytest.LogCaptureFixture) -> None:
    r = new_risk(equity=None)
    with caplog.at_level(logging.INFO):
        r.gate.check(r.open_req())
    assert any("equity_unknown" in rec.getMessage() or "equity_unknown" in str(rec.__dict__) for rec in caplog.records)
    assert r.last_decision_payload()["reason"] == "equity_unknown"


@pytest.mark.unit
def test_F10_AC7_every_check_is_audited_with_its_inputs_and_each_risk_check_result(new_risk: NewRisk) -> None:
    r = new_risk()
    r.gate.check(r.open_req())
    r.gate.check(r.open_req(leader_account_value_usd=None))
    first, second = (rec.payload for rec in r.decisions())
    assert first["approved"] is True and second["approved"] is False
    assert second["reason"] == "no_leader_av"
    assert second["checks"] and any(c["passed"] is False for c in second["checks"])


# ---- exits are never refused ---------------------------------------------------------------------------------------


def _with_share(r: RiskEnv) -> None:
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")


def _make_paused(r: RiskEnv) -> None:
    r.gate.pause()


def _make_no_equity(r: RiskEnv) -> None:
    r.account.equity = None


def _make_equity_raises(r: RiskEnv) -> None:
    r.account.raises = True


def _make_shares_raise(r: RiskEnv) -> None:
    r.shares.raises = True


def _make_blackout(r: RiskEnv) -> None:
    r.calendar.reason = "fomc"


def _make_unsynced(r: RiskEnv) -> None:
    r.xtime.unsynced = True


def _make_meta_down(r: RiskEnv) -> None:
    r.paper.meta.fail = True


def _make_returns_raise(r: RiskEnv) -> None:
    def boom(coin: str, days: int) -> None:
        raise RuntimeError("candles down")

    r.returns.hourly_returns = boom  # type: ignore[method-assign]


def _make_zero_equity(r: RiskEnv) -> None:
    r.account.equity = D(0)


BREAKERS = [
    _make_paused, _make_no_equity, _make_equity_raises, _make_shares_raise, _make_blackout, _make_unsynced,
    _make_meta_down, _make_returns_raise, _make_zero_equity,
]


@pytest.mark.unit
@pytest.mark.parametrize("breaker", BREAKERS, ids=lambda f: f.__name__[6:])
@pytest.mark.parametrize("close", [True, False])
def test_F10_AC7_an_exit_is_never_refused_by_a_pause_a_blackout_or_missing_data(
    new_risk: NewRisk, breaker: object, close: bool
) -> None:
    r = new_risk()
    _with_share(r)
    breaker(r)  # type: ignore[operator]
    d = r.gate.check(r.exit_req(share_id="S1", close=close, qty="1.0" if close else "0.4"))
    assert (d.approved, d.reason) == (True, None)


@pytest.mark.unit
def test_F10_AC7_an_exit_is_sent_and_fills_while_everything_else_is_broken(new_risk: NewRisk) -> None:
    r = new_risk()
    _with_share(r)
    r.gate.pause()
    r.account.equity = None
    r.calendar.reason = "fomc"
    r.paper.meta.fail = True
    r.book("SOL", "100")
    out = r.gate.submit(r.exit_req(share_id="S1"))
    assert out.decision.approved and out.result is not None and out.result.accepted
    r.fill()
    assert r.paper.broker.position("SOL") is None


@pytest.mark.unit
def test_F10_AC7_an_exit_is_never_refused_for_margin_leverage_or_liquidation_distance(new_risk: NewRisk) -> None:
    r = new_risk(equity="1")  # no free equity at all
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1", leverage=20)
    d = r.gate.check(r.exit_req(share_id="S1"))
    assert d.approved
    assert d.leverage is None  # exits carry no leverage


@pytest.mark.unit
def test_F10_AC7_a_reduce_only_quantity_above_the_share_is_refused_at_the_gate(new_risk: NewRisk) -> None:
    r = new_risk()
    _with_share(r)
    over = r.gate.submit(r.exit_req(share_id="S1", qty="1.01"))
    assert (over.decision.approved, over.decision.reason, over.result) == (False, "exceeds_share", None)
    assert r.authority.issued == []
    exact = r.gate.check(r.exit_req(share_id="S1", qty="1.0"))
    assert exact.approved
    below = r.gate.check(r.exit_req(share_id="S1", qty="0.99", close=False))
    assert below.approved


@pytest.mark.unit
def test_F10_AC7_a_non_positive_exit_quantity_is_refused(new_risk: NewRisk) -> None:
    r = new_risk()
    _with_share(r)
    for q in ("0", "-1"):
        d = r.gate.check(r.exit_req(share_id="S1", qty=q))
        assert d.approved is False


# ---- F8 is on hold: the calendar port is named and always allows -----------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("now_ms", [0, 1, 1_789_999_800_000, 2**62])
def test_F10_v0_the_default_calendar_port_never_blocks_an_entry(now_ms: int) -> None:
    assert AlwaysAllowCalendar().blocks_entries(now_ms) is None


@pytest.mark.unit
def test_F10_v0_a_calendar_blackout_blocks_entries_but_never_exits(new_risk: NewRisk) -> None:
    r = new_risk()
    _with_share(r)
    r.calendar.reason = "fomc"
    assert r.gate.check(r.open_req()).reason == "calendar_blackout"
    assert r.gate.check(r.exit_req(share_id="S1")).approved


@pytest.mark.unit
def test_F10_AC3_settings_expose_no_calendar_keys() -> None:
    s = RiskSettings.__dataclass_fields__
    assert not any("calendar" in name or "blackout" in name for name in s)
