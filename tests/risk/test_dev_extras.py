"""Developer tests for behaviour the designer's suite leaves open: the state file, the loss-limit clock guards, the
meta snapshot, persistence failures, stop idempotency, adds whose share or position is missing, and the share cap on
an open. Real gate, broker and ledger throughout (nothing of ours is mocked)."""

from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from copytrade.core.money import Qty
from copytrade.paper.types import OrderIntent
from copytrade.risk.errors import RiskStateError
from copytrade.risk.gate import STATE_FILENAME
from copytrade.risk.limits import apply_mark
from copytrade.risk.settings import RiskSettings
from copytrade.risk.sizing import add_qty
from copytrade.risk.state import (
    MS_PER_DAY,
    RiskState,
    load_state,
    save_state,
    utc_day_start_ms,
    utc_week_start_ms,
)
from tests.paper.helpers import make_config
from tests.risk.conftest import NewRisk
from tests.risk.helpers import RiskEnv, rebuild_gate, uncorrelated_returns, wide_returns

M0 = 1_789_948_800_000  # Monday 2026-09-21 00:00:00 UTC
HOUR = 3_600_000


def isolate(r: RiskEnv) -> None:
    r.returns.series["BTC"] = wide_returns()
    r.returns.series["SOL"] = uncorrelated_returns()


# ---- the state file ----------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_F10_AC6_the_state_file_round_trips_every_field(tmp_path: Path) -> None:
    state = RiskState(
        manual_pause=True,
        drawdown_pause=True,
        peak_equity_usd=D("330.12"),
        day_start_ms=M0,
        day_open_equity_usd=D("300"),
        daily_halt_until_ms=M0 + MS_PER_DAY,
        week_start_ms=M0,
        week_open_equity_usd=D("301.5"),
        weekly_halt_until_ms=M0 + 7 * MS_PER_DAY,
    )
    path = tmp_path / STATE_FILENAME
    save_state(path, state)
    assert load_state(path) == state
    assert not (tmp_path / (STATE_FILENAME + ".tmp")).exists()  # the temp file was renamed away


@pytest.mark.unit
def test_F10_AC6_no_state_file_is_a_fresh_running_state(tmp_path: Path) -> None:
    assert load_state(tmp_path / STATE_FILENAME) == RiskState()


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '{"version": 1}',  # fields missing
        '{"version": 2, "manual_pause": false}',
        # a float, a string for a flag, a negative equity, a bool where an integer is required, an unpaired day
        '{"version":1,"manual_pause":false,"drawdown_pause":false,"peak_equity_usd":1.5,"day_start_ms":null,'
        '"day_open_equity_usd":null,"daily_halt_until_ms":null,"week_start_ms":null,"week_open_equity_usd":null,'
        '"weekly_halt_until_ms":null}',
        '{"version":1,"manual_pause":"no","drawdown_pause":false,"peak_equity_usd":null,"day_start_ms":null,'
        '"day_open_equity_usd":null,"daily_halt_until_ms":null,"week_start_ms":null,"week_open_equity_usd":null,'
        '"weekly_halt_until_ms":null}',
        '{"version":1,"manual_pause":false,"drawdown_pause":false,"peak_equity_usd":"-1","day_start_ms":null,'
        '"day_open_equity_usd":null,"daily_halt_until_ms":null,"week_start_ms":null,"week_open_equity_usd":null,'
        '"weekly_halt_until_ms":null}',
        '{"version":1,"manual_pause":false,"drawdown_pause":false,"peak_equity_usd":"NaN","day_start_ms":null,'
        '"day_open_equity_usd":null,"daily_halt_until_ms":null,"week_start_ms":null,"week_open_equity_usd":null,'
        '"weekly_halt_until_ms":null}',
        '{"version":1,"manual_pause":false,"drawdown_pause":false,"peak_equity_usd":null,"day_start_ms":true,'
        '"day_open_equity_usd":"1","daily_halt_until_ms":null,"week_start_ms":null,"week_open_equity_usd":null,'
        '"weekly_halt_until_ms":null}',
        '{"version":1,"manual_pause":false,"drawdown_pause":false,"peak_equity_usd":null,"day_start_ms":5,'
        '"day_open_equity_usd":null,"daily_halt_until_ms":null,"week_start_ms":null,"week_open_equity_usd":null,'
        '"weekly_halt_until_ms":null}',
    ],
)
def test_F10_AC7_a_state_file_that_is_not_exactly_a_valid_state_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / STATE_FILENAME
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RiskStateError):
        load_state(path)


@pytest.mark.unit
def test_F10_AC7_a_state_file_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    path = tmp_path / STATE_FILENAME
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(RiskStateError):
        load_state(path)


@pytest.mark.unit
def test_F10_AC7_saving_into_a_missing_directory_is_a_typed_error(tmp_path: Path) -> None:
    with pytest.raises(RiskStateError):
        save_state(tmp_path / "missing" / STATE_FILENAME, RiskState())


@pytest.mark.unit
@pytest.mark.parametrize(
    "offset_ms,day_start,week_start",
    [
        (0, M0, M0),  # Monday 00:00:00.000
        (MS_PER_DAY - 1, M0, M0),  # Monday 23:59:59.999
        (MS_PER_DAY, M0 + MS_PER_DAY, M0),  # Tuesday 00:00
        (6 * MS_PER_DAY + 5 * HOUR, M0 + 6 * MS_PER_DAY, M0),  # Sunday
        (7 * MS_PER_DAY, M0 + 7 * MS_PER_DAY, M0 + 7 * MS_PER_DAY),  # the next Monday
        (-1, M0 - 1 - (MS_PER_DAY - 1), M0 - 7 * MS_PER_DAY),  # Sunday 23:59:59.999 of the week before
    ],
)
def test_F10_AC5_utc_day_and_monday_week_boundaries(offset_ms: int, day_start: int, week_start: int) -> None:
    assert utc_day_start_ms(M0 + offset_ms) == day_start
    assert utc_week_start_ms(M0 + offset_ms) == week_start


# ---- loss limits: clock guards ---------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_F10_AC5_a_mark_stamped_before_the_current_day_never_clears_a_halt_or_moves_the_opening_equity() -> None:
    settings = RiskSettings.from_config(make_config())
    state, _ = apply_mark(RiskState(), now_ms=M0 + HOUR, equity_usd=D(300), settings=settings)
    state, halts = apply_mark(state, now_ms=M0 + 10 * HOUR, equity_usd=D(294), settings=settings)
    assert [h.reason for h in halts] == ["daily_loss"]
    halted_until = state.daily_halt_until_ms
    assert halted_until == M0 + MS_PER_DAY
    back, more = apply_mark(state, now_ms=M0 - HOUR, equity_usd=D(400), settings=settings)  # a clock that stepped back
    assert more == ()
    assert (back.day_start_ms, back.day_open_equity_usd, back.daily_halt_until_ms) == (
        M0,
        D(300),
        halted_until,
    )
    assert back.week_start_ms == M0 and back.week_open_equity_usd == D(300)


@pytest.mark.unit
def test_F10_AC5_each_limit_fires_once_and_the_first_mark_of_a_period_is_its_opening_equity() -> None:
    settings = RiskSettings.from_config(make_config())
    state, halts = apply_mark(RiskState(), now_ms=M0 + 5 * HOUR, equity_usd=D(300), settings=settings)
    assert halts == () and state.day_open_equity_usd == D(300) and state.peak_equity_usd == D(300)
    state, halts = apply_mark(state, now_ms=M0 + 6 * HOUR, equity_usd=D(250), settings=settings)
    assert sorted(h.reason for h in halts) == ["daily_loss", "drawdown", "weekly_loss"]
    _, again = apply_mark(state, now_ms=M0 + 7 * HOUR, equity_usd=D(240), settings=settings)
    assert again == ()  # already halted and paused: nothing fires twice


# ---- sizing helper ----------------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_F10_AC9_the_add_quantity_is_rounded_down_never_up() -> None:
    qty = add_qty(our_share_qty=Qty(1), leader_add_size=Qty(1), leader_pre_add_position=Qty(3))
    assert 0 < qty and qty * 3 <= 1
    assert add_qty(our_share_qty=Qty("2"), leader_add_size=Qty("0.5"), leader_pre_add_position=Qty("4")) == D("0.25")
    with pytest.raises(ValueError):
        add_qty(our_share_qty=Qty(1), leader_add_size=Qty(1), leader_pre_add_position=Qty(0))


# ---- persistence failures --------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_AC6_a_pause_that_cannot_be_saved_is_still_in_force_and_entries_stay_refused_until_a_save_works(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    r.account.equity = D(300)
    r.gate.mark_equity(M0)  # the marks below change nothing in the state: only the failed save can trigger a write
    blocker = r.state_dir / (STATE_FILENAME + ".tmp")
    blocker.mkdir()  # the temp file cannot be created: a real write failure
    with pytest.raises(RiskStateError):
        r.gate.pause()
    assert r.gate.paused is True
    assert r.gate.check(r.open_req()).reason == "risk_state_unknown"  # and the pause is not lost meanwhile
    blocker.rmdir()
    r.gate.mark_equity(M0)  # the next mark saves the state again
    assert r.gate.check(r.open_req()).reason == "paused"
    assert load_state(r.state_dir / STATE_FILENAME).manual_pause is True


@pytest.mark.integration
def test_F10_AC6_a_resume_that_cannot_be_saved_leaves_the_gate_paused(new_risk: NewRisk) -> None:
    r = new_risk()
    r.gate.pause()
    (r.state_dir / (STATE_FILENAME + ".tmp")).mkdir()
    with pytest.raises(RiskStateError):
        r.gate.resume()
    assert r.gate.paused is True


@pytest.mark.integration
def test_F10_AC7_with_an_unreadable_state_the_gate_reports_paused_keeps_a_pause_and_will_not_resume(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    r.paper.ledger.close()
    (r.state_dir / STATE_FILENAME).write_bytes(b"garbage")
    r2 = rebuild_gate(r)
    try:
        assert r2.gate.paused is True
        r2.gate.pause()  # in memory, and the broken file is left for the operator
        assert (r2.state_dir / STATE_FILENAME).read_bytes() == b"garbage"
        with pytest.raises(RiskStateError):
            r2.gate.resume()
        r2.account.equity = D(250)
        r2.gate.mark_equity(M0)  # a mark can not touch an unknown state
        assert (r2.state_dir / STATE_FILENAME).read_bytes() == b"garbage"
    finally:
        r2.paper.ledger.close()


# ---- the coin-rules snapshot -------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_F10_AC7_coin_rules_are_fetched_once_per_refresh_interval_and_a_failed_refresh_refuses_entries(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    ttl_ms = r.config["paper.meta_refresh_min"] * 60_000
    assert r.gate.check(r.open_req()).approved
    fetches = r.paper.meta.fetches
    assert r.gate.check(r.open_req(tids=(555,))).approved
    assert r.paper.meta.fetches == fetches  # served from the snapshot
    r.at(r.xtime.now + ttl_ms - 1)
    r.gate.check(r.open_req(tids=(556,)))
    assert r.paper.meta.fetches == fetches
    r.at(r.xtime.now + 1)  # the snapshot is now too old
    r.paper.meta.fail = True
    assert r.gate.check(r.open_req(tids=(557,), leader_av_time_ms=r.xtime.now)).reason == "meta_unavailable"
    r.paper.meta.fail = False
    assert r.gate.check(r.open_req(tids=(558,), leader_av_time_ms=r.xtime.now)).approved  # retried and recovered


# ---- broker events, exit stamping ---------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_F11_contract_the_fills_the_gates_own_advance_produces_are_handed_to_the_caller(new_risk: NewRisk) -> None:
    r = new_risk()
    r.book("SOL", "100")
    first = r.gate.submit(r.open_req())
    assert first.result is not None and first.result.accepted and first.broker_events == ()
    r.xtime.now += 5000
    r.book("SOL", "100")
    second = r.gate.submit(r.open_req(tids=(556,), share_id="S11"))
    assert [e.kind for e in second.broker_events] == ["fill"]
    assert second.broker_events[0].client_order_id == first.decision.client_order_id


@pytest.mark.integration
def test_F10_F11_contract_an_exit_with_an_unsynced_clock_is_stamped_with_the_last_exchange_time_seen(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    seen = r.xtime.now
    r.gate.check(r.open_req(coin="ETH"))  # reads the clock
    r.xtime.now += 9_999
    r.xtime.unsynced = True
    out = r.gate.submit(r.exit_req(share_id="S1"))
    assert out.result is not None and out.result.accepted
    intent = r.authority.issued[0][0]
    assert isinstance(intent, OrderIntent) and intent.decided_at_ms == seen


# ---- stops: idempotency ---------------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_F10_AC8_a_replayed_stop_signal_is_a_duplicate_and_a_new_signal_is_a_new_stop(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    first = r.gate.place_stop(r.stop_req(share_id="S1", signal_id="trail1", trigger_px="98.5"))
    assert first.result is not None and first.result.accepted
    replay = r.gate.place_stop(r.stop_req(share_id="S1", signal_id="trail1", trigger_px="98.5"))
    assert (replay.decision.approved, replay.decision.reason, replay.result) == (False, "duplicate_order", None)
    trailed = r.gate.place_stop(r.stop_req(share_id="S1", signal_id="trail2", trigger_px="99"))
    assert trailed.result is not None and trailed.result.accepted
    assert len(r.authority.issued) == 2
    assert first.decision.client_order_id != trailed.decision.client_order_id


@pytest.mark.unit
@pytest.mark.parametrize("kwargs", [{"kind": "xx"}, {"qty": "0"}, {"trigger_px": "0"}])
def test_F10_AC7_a_malformed_stop_is_refused_at_the_gate(new_risk: NewRisk, kwargs: dict[str, str]) -> None:
    r = new_risk()
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    out = r.gate.place_stop(r.stop_req(share_id="S1", **kwargs))
    assert out.decision.approved is False and out.result is None
    assert r.authority.issued == []


# ---- adds whose share or position is missing; the share cap on an open ---------------------------------------------------------


@pytest.mark.unit
def test_F10_AC9_an_add_to_a_share_the_book_does_not_list_is_refused(new_risk: NewRisk) -> None:
    r = new_risk()
    isolate(r)
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", share="S1")
    assert r.gate.check(r.add_req(share_id="NOPE")).reason == "unknown_share"


@pytest.mark.unit
def test_F10_AC9_an_add_when_the_broker_holds_no_position_is_refused(new_risk: NewRisk) -> None:
    r = new_risk()
    isolate(r)
    r.seed_risk_only("SOL", leader="L1", risk="1.5")
    share_id = r.shares.shares[0].share_id
    assert r.gate.check(r.add_req(share_id=share_id)).reason == "position_unknown"


@pytest.mark.unit
def test_F10_AC3_the_share_risk_cap_also_limits_a_new_share(new_risk: NewRisk) -> None:
    # vol_mult 3 and a leader at 100% of their account: risk notional and mirror are both 300, but one share may not
    # carry more than 1% of equity (3.00) at risk: 3.00 / 0.015 = 200 -> 2.00 SOL
    r = new_risk()
    d = r.gate.check(
        r.open_req(vol_mult=D(3), leader_position_notional_usd=D(1000), leader_account_value_usd=D(1000))
    )
    assert d.approved and d.qty == D("2.00") and d.initial_risk_usd == D("3.00")
    assert d.risk_notional_usd == D(300) and d.mirror_notional_usd == D(300)


@pytest.mark.unit
@pytest.mark.parametrize("age_ms,ok", [(-300_000, True), (-300_001, False)])
def test_F10_AC2_a_leader_account_value_stamped_in_the_future_is_not_trusted_beyond_the_age_limit(
    new_risk: NewRisk, age_ms: int, ok: bool
) -> None:
    r = new_risk()
    d = r.gate.check(r.open_req(leader_av_time_ms=r.xtime.now - age_ms))
    assert d.approved is ok
    assert d.reason == (None if ok else "no_leader_av")


@pytest.mark.unit
def test_F10_AC7_a_decision_record_names_the_refusal_check_and_the_equity_it_used(new_risk: NewRisk) -> None:
    r = new_risk()
    r.gate.check(r.open_req(leader_account_value_usd=None))
    payload = r.last_decision_payload()
    assert payload["reason"] == "no_leader_av" and payload["action"] == "open"
    assert D(str(payload["equity_usd"])) == 300
    assert payload["checks"][-1] == {
        "check": "no_leader_av",
        "passed": False,
        "detail": "the leader's account value is missing or not positive",
    }


# ---- BTC bucket boundary, opposite side from either source, duplicates, non-finite equity -----------------------------------


def _sixty_percent_pair() -> tuple[list[D], list[D]]:
    """Two series whose Pearson correlation is exactly 0.6 (x, and 0.6 x + 0.8 z with z orthogonal to x)."""
    x = [D(1), D(-1), D(1), D(-1)] * 6
    y = [D("1.4"), D("0.2"), D("-0.2"), D("-1.4")] * 6
    return x, y


@pytest.mark.unit
@pytest.mark.parametrize("threshold,in_bucket", [("0.6", True), ("0.61", False)])
def test_F10_AC3_a_coin_exactly_at_the_correlation_threshold_is_in_the_bucket(
    new_risk: NewRisk, threshold: str, in_bucket: bool
) -> None:
    x, y = _sixty_percent_pair()
    r = new_risk(risk__btc_bucket_corr_threshold=D(threshold))
    r.returns.series.update({"BTC": x, "SOL": y})
    r.seed_risk_only("BTC", leader="LA", risk="8.5")  # bucket cap 9.00 leaves 0.50 for a bucket member
    assert r.gate.check(r.open_req()).qty == (D("0.33") if in_bucket else D("1.00"))


@pytest.mark.unit
@pytest.mark.parametrize("held_long", [True, False])
def test_F10_F11_contract_an_opposite_side_entry_is_refused_on_the_brokers_position_alone(
    new_risk: NewRisk, held_long: bool
) -> None:
    r = new_risk()
    isolate(r)
    stop = "98.5" if held_long else "101.5"
    r.seed("SOL", leader="LA", is_long=held_long, qty="1.0", entry="100", stop=stop)
    r.shares.shares.clear()  # the share book does not know the position; the broker does
    other = r.open_req(is_long=not held_long, stop_px=D("101.5" if held_long else "98.5"))
    assert r.gate.check(other).reason == "opposite_side_entry"


@pytest.mark.unit
@pytest.mark.parametrize("booked_long", [True, False])
def test_F10_F11_contract_an_opposite_side_entry_is_refused_on_the_share_book_alone(
    new_risk: NewRisk, booked_long: bool
) -> None:
    r = new_risk()
    isolate(r)
    r.seed_risk_only("SOL", leader="LA", risk="0.1", is_long=booked_long)
    other = r.open_req(is_long=not booked_long, stop_px=D("101.5" if booked_long else "98.5"))
    assert r.gate.check(other).reason == "opposite_side_entry"


@pytest.mark.integration
def test_F10_AC8_a_signal_already_sent_is_refused_by_the_gate_before_any_token_is_issued(new_risk: NewRisk) -> None:
    r = new_risk()
    r.book("SOL", "100")
    first = r.gate.submit(r.open_req())
    again = r.gate.submit(r.open_req())
    assert first.result is not None and first.result.accepted
    assert (again.decision.approved, again.decision.reason, again.result) == (False, "duplicate_order", None)
    assert len(r.authority.issued) == 1
    assert r.paper.records("paper_reject") == []  # the broker never saw the second attempt


@pytest.mark.unit
@pytest.mark.parametrize("equity", [D("NaN"), D("Infinity"), D("-Infinity")])
def test_F10_AC7_a_non_finite_equity_is_unknown_equity(new_risk: NewRisk, equity: D) -> None:
    r = new_risk()
    r.account.equity = equity
    assert r.gate.check(r.open_req()).reason == "equity_unknown"
    r.gate.mark_equity(M0)  # and a mark with it changes nothing
    assert load_state(r.state_dir / STATE_FILENAME) == RiskState()


@pytest.mark.unit
def test_F10_AC5_a_new_day_and_a_new_week_replace_the_opening_equity_and_clear_the_old_halt() -> None:
    settings = RiskSettings.from_config(make_config())
    state, _ = apply_mark(RiskState(), now_ms=M0 + HOUR, equity_usd=D(300), settings=settings)
    state, _ = apply_mark(state, now_ms=M0 + 2 * HOUR, equity_usd=D(290), settings=settings)
    assert state.daily_halt_until_ms == M0 + MS_PER_DAY
    next_day, halts = apply_mark(state, now_ms=M0 + MS_PER_DAY + HOUR, equity_usd=D(290), settings=settings)
    assert halts == ()
    assert (next_day.day_start_ms, next_day.day_open_equity_usd, next_day.daily_halt_until_ms) == (
        M0 + MS_PER_DAY,
        D(290),
        None,
    )
    assert next_day.week_open_equity_usd == D(300)  # still the same week
    next_week, _ = apply_mark(next_day, now_ms=M0 + 7 * MS_PER_DAY + HOUR, equity_usd=D(289), settings=settings)
    assert (next_week.week_start_ms, next_week.week_open_equity_usd) == (M0 + 7 * MS_PER_DAY, D(289))


@pytest.mark.unit
@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), D("-Infinity"), D(0), D(-1)])
def test_F10_AC7_a_vol_mult_that_is_not_a_finite_positive_number_is_an_invalid_request(
    new_risk: NewRisk, bad: D
) -> None:
    r = new_risk()
    assert r.gate.check(r.open_req(vol_mult=bad)).reason == "invalid_request"
