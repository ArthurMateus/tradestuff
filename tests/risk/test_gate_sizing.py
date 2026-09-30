"""F10.AC2 (sizing), AC3 (caps) and AC9 (adds) through the REAL risk gate, paper broker, gate authority and F2 ledger.

Equity is $300 unless a test says otherwise. Default request: SOL long, price 100, stop 98.5 (1.5%), the leader holds
$500 of a $1000 account, so mirror = 150 and risk = 100 (the worked example). Open risk of a share is qty x |entry -
stop|; the default caps at $300 equity are: share 3.00, symbol 4.50, leader 4.50, BTC bucket 9.00, total 15.00,
notional 300.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D

import pytest

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.paper.liquidation import liquidation_price
from copytrade.paper.types import OrderIntent
from tests.risk.conftest import NewRisk
from tests.risk.helpers import (
    RiskEnv,
    opposite_returns,
    same_returns,
    uncorrelated_returns,
    wide_returns,
)


def isolate_bucket(r: RiskEnv, *coins: str) -> None:
    """BTC has a known series and every listed coin is uncorrelated with it, so none is in the BTC bucket."""
    r.returns.series["BTC"] = wide_returns()
    for coin in coins:
        r.returns.series[coin] = uncorrelated_returns()


# ---- AC2 sizing ---------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_F10_AC2_worked_example_through_the_gate(new_risk: NewRisk) -> None:
    r = new_risk()
    d = r.gate.check(r.open_req())
    assert d.approved and d.reason is None
    assert d.action is ActionKind.OPEN
    assert d.mirror_notional_usd == D(150)
    assert d.risk_notional_usd == D(100)
    assert d.final_notional_usd == D(100)
    assert d.qty == D("1.00")
    assert d.initial_risk_usd == D("1.5")
    assert (d.leverage, d.leverage_ceiling) == (1, 10)


@pytest.mark.unit
@pytest.mark.parametrize(
    "leader_notional,vol,expected_qty",
    [
        (D(200), D(1), "0.60"),  # mirror 60 is below the risk notional 100
        (D(500), D(2), "1.50"),  # vol_mult 2: risk 200, mirror 150
        (D(500), D("0.5"), "0.50"),  # vol_mult 0.5: risk 50
        (D(333), D(1), "0.99"),  # mirror 99.9 rounds DOWN to the lot
        (D("33.4"), D(1), "0.10"),  # mirror 10.02 -> $10.00
    ],
)
def test_F10_AC2_final_is_the_minimum_of_mirror_and_risk_rounded_down_to_the_lot(
    new_risk: NewRisk, leader_notional: D, vol: D, expected_qty: str
) -> None:
    r = new_risk()
    d = r.gate.check(r.open_req(leader_position_notional_usd=leader_notional, vol_mult=vol))
    assert d.approved
    assert d.qty == D(expected_qty)


@pytest.mark.unit
def test_F10_C2_a_leader_ten_times_larger_with_the_same_fraction_gives_the_same_size(new_risk: NewRisk) -> None:
    r = new_risk()
    small = r.gate.check(r.open_req(leader_position_notional_usd=D(200), leader_account_value_usd=D(1000)))
    big = r.gate.check(r.open_req(leader_position_notional_usd=D(2_000_000), leader_account_value_usd=D(10_000_000)))
    assert small.qty == big.qty == D("0.60")


@pytest.mark.unit
def test_F10_AC2_minimum_order_exactly_10_dollars_is_executable_even_when_the_quotient_does_not_terminate(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    d = r.gate.check(r.open_req(leader_position_notional_usd=D(100), leader_account_value_usd=D(3000)))
    assert d.approved and d.qty == D("0.10") and d.final_notional_usd == D(10)


@pytest.mark.unit
def test_F10_AC2_below_the_minimum_order_is_unexecutable_with_no_order_and_no_trade(new_risk: NewRisk) -> None:
    r = new_risk()
    req = r.open_req(leader_position_notional_usd=D(33))  # mirror 9.90 -> qty 0.09 = $9
    out = r.gate.submit(req)
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "unexecutable", None)
    assert r.authority.issued == []
    assert r.paper.records("paper_order") == [] and r.paper.records("paper_reject") == []
    assert r.paper.broker.position("SOL") is None
    assert r.last_decision_payload()["reason"] == "unexecutable"  # logged (A2, B5)


@pytest.mark.unit
@pytest.mark.parametrize("min_usd,ok", [(D(10), True), (D(11), False)])
def test_F10_AC2_the_minimum_order_is_the_config_value(new_risk: NewRisk, min_usd: D, ok: bool) -> None:
    r = new_risk(sizing__min_order_usd=min_usd)
    d = r.gate.check(r.open_req(leader_position_notional_usd=D("33.4")))  # $10.00
    assert d.approved is ok


@pytest.mark.unit
def test_F10_AC2_per_trade_fraction_comes_from_config(new_risk: NewRisk) -> None:
    r = new_risk(risk__per_trade_fraction=D("0.001"))
    d = r.gate.check(r.open_req())
    assert d.risk_notional_usd == D(20)  # 300 x 0.001 / 0.015
    assert d.qty == D("0.20")


@pytest.mark.unit
def test_F10_AC2_a_short_uses_the_same_sizing_with_the_stop_above(new_risk: NewRisk) -> None:
    r = new_risk()
    d = r.gate.check(r.open_req(is_long=False, stop_px=D("101.5")))
    assert d.approved and d.final_notional_usd == D(100) and d.qty == D("1.00")


@pytest.mark.unit
def test_F10_AC2_a_stop_distance_that_is_zero_or_on_the_wrong_side_is_refused_without_raising(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    for req in (
        r.open_req(stop_px=D(100)),
        r.open_req(stop_px=D("101.5")),  # long with the stop above the price
        r.open_req(is_long=False, stop_px=D("98.5")),  # short with the stop below
    ):
        out = r.gate.submit(req)
        assert out.decision.approved is False and out.result is None
    assert r.authority.issued == []


@pytest.mark.unit
def test_F10_AC2_no_leader_av_when_missing_non_positive_or_unstamped(new_risk: NewRisk) -> None:
    r = new_risk()
    now = r.xtime.now
    for bad in (
        r.open_req(leader_account_value_usd=None),
        r.open_req(leader_account_value_usd=D(0)),
        r.open_req(leader_account_value_usd=D(-5)),
        r.open_req(leader_av_time_ms=None),
    ):
        d = r.gate.check(bad)
        assert (d.approved, d.reason) == (False, "no_leader_av")
    assert r.xtime.now == now


@pytest.mark.unit
@pytest.mark.parametrize("age_ms,ok", [(0, True), (299_999, True), (300_000, True), (300_001, False), (3_600_000, False)])
def test_F10_AC2_leader_av_age_boundary_follow_max_leader_av_age_s(new_risk: NewRisk, age_ms: int, ok: bool) -> None:
    r = new_risk()
    d = r.gate.check(r.open_req(leader_av_time_ms=r.xtime.now - age_ms))
    assert d.approved is ok
    assert d.reason == (None if ok else "no_leader_av")


@pytest.mark.unit
def test_F10_AC2_leader_av_age_limit_is_config(new_risk: NewRisk) -> None:
    r = new_risk(follow__max_leader_av_age_s=60)
    assert r.gate.check(r.open_req(leader_av_time_ms=r.xtime.now - 60_000)).approved
    assert r.gate.check(r.open_req(leader_av_time_ms=r.xtime.now - 60_001)).reason == "no_leader_av"


# ---- AC3 caps: reduce to fit, then re-apply the $10 minimum ----------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "existing_risk,expected",
    [
        ("3.0", "1.00"),  # room 1.5 = exactly this order's risk: full size at the cap
        ("3.01", "0.99"),  # room 1.49 / 0.015 = 99.33 -> 0.99
        ("4.0", "0.33"),  # room 0.5 -> 33.33 -> 0.33
        ("4.35", "0.10"),  # room 0.15 -> exactly $10.00: the minimum re-applied passes at the boundary
        ("4.4", None),  # room 0.1 -> $6.67 -> 0.06 = $6 < $10: unexecutable
        ("4.5", None),  # no room at all
    ],
)
def test_F10_AC3_per_coin_open_risk_cap_reduces_the_size_then_the_minimum_is_reapplied(
    new_risk: NewRisk, existing_risk: str, expected: str | None
) -> None:
    r = new_risk()
    r.seed_risk_only("SOL", leader="LA", risk=existing_risk)
    d = r.gate.check(r.open_req())
    if expected is None:
        assert (d.approved, d.reason) == (False, "unexecutable")
    else:
        assert d.approved and d.qty == D(expected)
        assert d.mirror_notional_usd == D(150) and d.risk_notional_usd == D(100)  # recorded BEFORE the caps


@pytest.mark.unit
def test_F10_AC3_per_coin_cap_is_config(new_risk: NewRisk) -> None:
    r = new_risk(risk__max_symbol_open_risk_fraction=D("0.005"))  # 1.5 room total on the coin
    r.seed_risk_only("SOL", leader="LA", risk="1.0")
    assert r.gate.check(r.open_req()).qty == D("0.33")


@pytest.mark.unit
@pytest.mark.parametrize("existing_total,expected", [("13.5", "1.00"), ("14.5", "0.33"), ("15", None)])
def test_F10_AC3_total_open_risk_cap(new_risk: NewRisk, existing_total: str, expected: str | None) -> None:
    r = new_risk()
    isolate_bucket(r, "SOL", "C1", "C2", "C3", "C4")
    third = D(existing_total) / 3
    for coin, leader in (("C1", "LA"), ("C2", "LB"), ("C3", "LC")):
        r.seed_risk_only(coin, leader=leader, risk=str(third))  # each below its coin and leader caps (4.5 / 4.5)
    d = r.gate.check(r.open_req())
    if expected is None:
        assert (d.approved, d.reason) == (False, "unexecutable")
    else:
        assert d.approved and d.qty == D(expected)


@pytest.mark.unit
@pytest.mark.parametrize("existing,expected", [("3.0", "1.00"), ("4.0", "0.33"), ("4.5", None)])
def test_F10_AC3_per_leader_open_risk_cap(new_risk: NewRisk, existing: str, expected: str | None) -> None:
    r = new_risk()
    isolate_bucket(r, "SOL", "C1", "C2", "C3")
    half = str(D(existing) / 2)
    r.seed_risk_only("C1", leader="L1", risk=half)
    r.seed_risk_only("C2", leader="L1", risk=half)
    r.seed_risk_only("C3", leader="LZ", risk="4.0")  # another leader's risk does not count against L1
    d = r.gate.check(r.open_req())
    if expected is None:
        assert (d.approved, d.reason) == (False, "unexecutable")
    else:
        assert d.approved and d.qty == D(expected)


@pytest.mark.unit
@pytest.mark.parametrize("existing,expected", [("7.5", "1.00"), ("8.5", "0.33"), ("9.0", None)])
def test_F10_AC3_btc_bucket_cap_counts_correlated_coins_in_the_same_direction(
    new_risk: NewRisk, existing: str, expected: str | None
) -> None:
    r = new_risk()
    r.returns.series.update({"BTC": wide_returns(), "ETH": same_returns(), "SOL": same_returns()})
    half = str(D(existing) / 2)
    r.seed_risk_only("BTC", leader="LA", risk=half)
    r.seed_risk_only("ETH", leader="LB", risk=half)
    d = r.gate.check(r.open_req())
    if expected is None:
        assert (d.approved, d.reason) == (False, "unexecutable")
    else:
        assert d.approved and d.qty == D(expected)


@pytest.mark.unit
def test_F10_AC3_btc_bucket_is_per_direction_so_an_opposite_trade_is_not_limited(new_risk: NewRisk) -> None:
    r = new_risk()
    r.returns.series.update({"BTC": wide_returns(), "ETH": same_returns(), "SOL": same_returns()})
    r.seed_risk_only("BTC", leader="LA", risk="4.25")
    r.seed_risk_only("ETH", leader="LB", risk="4.25")
    d = r.gate.check(r.open_req(is_long=False, stop_px=D("101.5")))
    assert d.approved and d.qty == D("1.00")


@pytest.mark.unit
@pytest.mark.parametrize("series", [uncorrelated_returns(), opposite_returns()])
def test_F10_AC3_a_coin_below_the_correlation_threshold_is_not_in_the_bucket(new_risk: NewRisk, series: list[D]) -> None:
    r = new_risk()
    r.returns.series.update({"BTC": wide_returns(), "ETH": same_returns(), "SOL": series})
    r.seed_risk_only("BTC", leader="LA", risk="4.25")
    r.seed_risk_only("ETH", leader="LB", risk="4.25")
    assert r.gate.check(r.open_req()).qty == D("1.00")


@pytest.mark.unit
def test_F10_AC3_the_correlation_window_and_threshold_are_config(new_risk: NewRisk) -> None:
    r = new_risk(risk__btc_bucket_corr_window_days=7)
    r.returns.series.update({"BTC": wide_returns(), "SOL": same_returns()})
    r.gate.check(r.open_req())
    assert ("BTC", 7) in r.returns.calls and ("SOL", 7) in r.returns.calls


@pytest.mark.unit
def test_F10_AC3_unknown_returns_count_the_coin_as_in_the_bucket_never_out_of_it(new_risk: NewRisk) -> None:
    # DECISION NEEDED (logged in the test plan): unknown correlation is treated conservatively, as a member.
    r = new_risk()
    r.returns.series.update({"BTC": wide_returns(), "ETH": same_returns()})  # no series for SOL
    r.seed_risk_only("BTC", leader="LA", risk="4.25")
    r.seed_risk_only("ETH", leader="LB", risk="4.25")
    assert r.gate.check(r.open_req()).qty == D("0.33")


@pytest.mark.unit
@pytest.mark.parametrize("stop,mult,expected_qty", [("99.6", "1.0", "3.00"), ("99.6", "0.5", "1.50")])
def test_F10_AC3_notional_cap_is_a_multiple_of_equity(new_risk: NewRisk, stop: str, mult: str, expected_qty: str) -> None:
    # stop 0.4%: risk notional 300 x 0.005 / 0.004 = 375; the leader at 2x their account gives mirror 600; cap 300 x mult
    r = new_risk(risk__max_position_notional_equity_mult=D(mult))
    d = r.gate.check(
        r.open_req(stop_px=D(stop), leader_position_notional_usd=D(2000), leader_account_value_usd=D(1000))
    )
    assert d.approved
    assert d.risk_notional_usd == D(375) and d.mirror_notional_usd == D(600)
    assert d.qty == D(expected_qty)


@pytest.mark.unit
def test_F10_AC3_notional_cap_applies_to_the_merged_position_on_the_coin(new_risk: NewRisk) -> None:
    r = new_risk()
    isolate_bucket(r, "SOL")
    r.seed("SOL", leader="LA", qty="2.0", entry="100", stop="99.6", leverage=5)  # notional 200, margin 40
    d = r.gate.check(
        r.open_req(stop_px=D("99.6"), leader_position_notional_usd=D(2000), leader_account_value_usd=D(1000))
    )
    assert d.approved and d.qty == D("1.00")  # 300 - 200 = 100 of room


@pytest.mark.unit
@pytest.mark.parametrize("limit,coin,ok", [(2, "BTC", False), (3, "BTC", True), (2, "SOL", True)])
def test_F10_AC3_max_open_positions_counts_merged_positions_not_shares(
    new_risk: NewRisk, limit: int, coin: str, ok: bool
) -> None:
    r = new_risk(risk__max_open_positions=limit)
    isolate_bucket(r, "SOL")
    r.seed_risk_only("SOL", leader="LA", risk="0.1")
    r.seed_risk_only("SOL", leader="LB", risk="0.1")  # two shares, ONE merged position
    r.seed_risk_only("ETH", leader="LC", risk="0.1")
    d = r.gate.check(r.open_req(coin=coin))
    assert d.approved is ok
    assert d.reason == (None if ok else "max_open_positions")


@pytest.mark.unit
def test_F10_AC3_max_open_positions_default_is_ten(new_risk: NewRisk) -> None:
    r = new_risk()
    for i in range(9):
        r.seed_risk_only(f"X{i}", leader=f"L{i}", risk="0.1")
    assert r.gate.check(r.open_req(coin="ETH")).approved  # the 10th position
    r.seed_risk_only("X9", leader="L9", risk="0.1")
    assert r.gate.check(r.open_req(coin="ETH")).reason == "max_open_positions"


@pytest.mark.unit
def test_F10_AC3_orders_per_minute_cap_uses_a_sliding_window_in_exchange_time(new_risk: NewRisk) -> None:
    r = new_risk(risk__max_orders_per_min=2)
    t = r.xtime.now
    sent = []
    for i, dt in enumerate((0, 1000)):
        r.at(t + dt)
        r.book("SOL", "100")
        out = r.gate.submit(r.open_req(tids=(200 + i,), share_id=f"S{i}", signal_id=f"g{i}"))
        assert out.result is not None and out.result.accepted, out
        sent.append(out)
    r.at(t + 59_999)  # the first order is 59.999 s old: still inside the minute
    blocked = r.gate.submit(r.open_req(tids=(300,), share_id="S3", signal_id="g3"))
    assert (blocked.decision.approved, blocked.decision.reason, blocked.result) == (False, "rate_limit", None)
    r.at(t + 60_000)  # the first order leaves the window: one sent in the window, one slot free
    r.book("SOL", "100")
    again = r.gate.submit(r.open_req(tids=(301,), share_id="S4", signal_id="g4"))
    assert again.result is not None and again.result.accepted, again


@pytest.mark.unit
def test_F10_AC3_orders_per_minute_default_is_30(new_risk: NewRisk) -> None:
    r = new_risk()
    t = r.xtime.now
    for i in range(30):
        r.at(t + i)
        r.book("SOL", "100", at=t + i)
        out = r.gate.submit(r.open_req(tids=(400 + i,), share_id=f"S{i}", signal_id=f"g{i}", leader_position_notional_usd=D(40)))
        assert out.result is not None and out.result.accepted, (i, out)
    r.at(t + 31)
    assert r.gate.check(r.open_req(tids=(999,), share_id="S99", leader_position_notional_usd=D(40))).reason == "rate_limit"


# ---- AC4 through the gate --------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_F10_AC4_vector_free_equity_40_eth_100_is_3x(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", qty="52", entry="100", leverage=20, open_risk="0.1")  # margin 5200 / 20 = 260: free = 300 - 260
    d = r.gate.check(r.open_req(coin="ETH"))
    assert d.approved and d.final_notional_usd == D(100)
    assert (d.leverage, d.leverage_ceiling) == (3, 10)


@pytest.mark.unit
def test_F10_AC4_vector_free_equity_15_alt_100_is_insufficient_margin(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", qty="57", entry="100", leverage=20, open_risk="0.1")  # margin 285, free 15
    out = r.gate.submit(r.open_req(coin="DOGE"))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "insufficient_margin", None)
    assert out.decision.leverage_ceiling == 5
    assert r.authority.issued == []


@pytest.mark.unit
def test_F10_AC4_vector_free_equity_12_doge_100_is_insufficient_margin(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", qty="57.6", entry="100", leverage=20, open_risk="0.1")  # margin 288, free 12
    assert r.gate.check(r.open_req(coin="DOGE")).reason == "insufficient_margin"


@pytest.mark.unit
def test_F10_AC4_vector_free_equity_12_sol_100_is_9x_when_the_stop_is_2_8_percent(new_risk: NewRisk) -> None:
    r = new_risk(equity="560")
    r.seed("ETH", qty="137", entry="100", leverage=25, open_risk="0.1")  # margin 13700 / 25 = 548: free 12
    d = r.gate.check(r.open_req(stop_px=D("97.2"), leader_position_notional_usd=D(500), leader_account_value_usd=D(1000)))
    assert d.approved and d.final_notional_usd == D(100)  # 560 x 0.005 / 0.028
    assert (d.leverage, d.leverage_ceiling) == (9, 10)
    assert d.liquidation_px == D("91.389")


@pytest.mark.unit
def test_F10_AC4_vector_stop_2_9_percent_is_refused_liq_too_close(new_risk: NewRisk) -> None:
    r = new_risk(equity="580")
    r.seed("ETH", qty="142", entry="100", leverage=25, open_risk="0.1")  # margin 568: free 12
    out = r.gate.submit(r.open_req(stop_px=D("97.1")))
    assert out.decision.final_notional_usd == D(100)
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "liq_too_close", None)
    assert r.authority.issued == []


@pytest.mark.unit
def test_F10_AC4_size_and_initial_risk_do_not_depend_on_leverage(new_risk: NewRisk) -> None:
    rich, tight = new_risk(), new_risk()
    tight.seed("SOL", qty="52", entry="100", leverage=20, open_risk="0.1")
    a, b = rich.gate.check(rich.open_req(coin="ETH")), tight.gate.check(tight.open_req(coin="ETH"))
    assert a.leverage == 1 and b.leverage == 3
    assert (a.qty, a.initial_risk_usd, a.final_notional_usd) == (b.qty, b.initial_risk_usd, b.final_notional_usd)


@pytest.mark.unit
def test_F10_AC4_decision_record_carries_leverage_ceiling_margin_and_liquidation_price(new_risk: NewRisk) -> None:
    r = new_risk()
    r.seed("SOL", qty="52", entry="100", leverage=20, open_risk="0.1")
    r.gate.check(r.open_req(coin="ETH"))
    p = r.last_decision_payload()
    assert p["leverage"] == 3 and p["leverage_ceiling"] == 10
    assert D(str(p["posted_margin_usd"])) == 0
    assert D(str(p["liquidation_px"])) > 0
    assert D(str(p["final_notional_usd"])) == 100
    assert p["approved"] is True and p["signal_id"] == "sig1"
    assert all({"check", "passed", "detail"} <= set(c) for c in p["checks"]) and p["checks"]


@pytest.mark.integration
def test_F10_AC10_property_7_the_gate_liquidation_price_is_the_brokers_to_the_tick(new_risk: NewRisk) -> None:
    r = new_risk()
    r.book("SOL", "100")
    out = r.gate.submit(r.open_req())
    assert out.result is not None and out.result.accepted
    r.fill()
    pos = r.paper.broker.position("SOL")
    assert pos is not None
    assert pos.leverage == out.decision.leverage == 1
    assert pos.liquidation_px == out.decision.liquidation_px
    assert out.decision.final_notional_usd is not None and out.decision.leverage is not None
    assert pos.margin_usd == out.decision.final_notional_usd / out.decision.leverage


@pytest.mark.unit
def test_F10_AC4_the_high_leverage_list_and_ceilings_are_config(new_risk: NewRisk) -> None:
    r = new_risk(risk__high_leverage_coins=("BTC",), risk__max_leverage_alt=3)
    r.seed("SOL", qty="52", entry="100", leverage=20, open_risk="0.1")  # free 40: needs 3x for $100
    assert r.gate.check(r.open_req(coin="ETH")).leverage_ceiling == 3
    assert r.gate.check(r.open_req(coin="BTC")).leverage_ceiling == 10
    assert r.gate.check(r.open_req(coin="ETH")).leverage == 3


@pytest.mark.unit
def test_F10_AC4_an_add_uses_the_posted_margin_of_the_merged_position(new_risk: NewRisk) -> None:
    r = new_risk()
    isolate_bucket(r, "SOL")
    r.seed("SOL", leader="L1", qty="1.0", entry="100", stop="98.5", leverage=5, share="S1")  # margin 20, free 280
    d = r.gate.check(r.add_req(share_id="S1"))
    assert d.approved and d.qty == D("0.50") and d.action is ActionKind.ADD
    assert d.posted_margin_usd == D(20)
    # Amendment 12: an ADD keeps the position's leverage (5x here), it does not pick one afresh (the fresh choice
    # would have been 1x: 150 <= 20 + 280). The intent of the test (posted margin counts) is unchanged.
    assert d.leverage == 5


# ---- Amendment 12: an ADD keeps the position's leverage; only an OPEN chooses afresh -------------------------------------


def _long_share_at(r: RiskEnv, leverage: int, *, coin: str = "SOL") -> None:
    """One long share S1 (1.0 @ 100, stop 98.5) on the real broker, opened at ``leverage``."""
    isolate_bucket(r, coin)
    r.seed(coin, leader="L1", qty="1.0", entry="100", stop="98.5", leverage=leverage, share="S1")


@pytest.mark.unit
def test_F10_AC4_an_add_on_a_position_opened_at_3x_computes_margin_and_liquidation_at_3x(new_risk: NewRisk) -> None:
    r = new_risk()
    _long_share_at(r, 3)
    before = r.paper.broker.position("SOL")
    assert before is not None and before.leverage == 3
    d = r.gate.check(r.add_req(share_id="S1"))
    assert d.approved and d.action is ActionKind.ADD
    assert d.leverage == 3  # a fresh choice would be 1 (150 <= 33.3 + 266.7)
    assert d.posted_margin_usd == before.margin_usd  # 100 / 3: the margin the broker really holds
    meta = r.paper.meta.meta["SOL"]
    # the merged position is 1.5 @ 100: its liquidation price at 3x (the F11 model, to the tick)
    assert d.liquidation_px == liquidation_price(
        side="long", avg_entry_px=Price("100"), leverage=3, max_leverage=meta.max_leverage, sz_decimals=meta.sz_decimals
    )
    assert r.last_decision_payload()["leverage"] == 3


@pytest.mark.integration
def test_F10_AC4_the_token_of_an_add_binds_the_positions_leverage(new_risk: NewRisk) -> None:
    r = new_risk()
    _long_share_at(r, 3)
    r.book("SOL", "100")
    out = r.gate.submit(r.add_req(share_id="S1"))
    assert out.result is not None and out.result.accepted, out
    (intent, token), = r.authority.issued
    assert isinstance(intent, OrderIntent) and intent.action is ActionKind.ADD
    assert intent.leverage == 3
    assert r.authority.verify(token, intent)
    assert not r.authority.verify(token, replace(intent, leverage=1))
    assert not r.authority.verify(token, replace(intent, leverage=4))


@pytest.mark.integration
def test_F10_AC10_the_leverage_the_broker_holds_after_an_add_fills_is_the_one_the_gate_checked(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    _long_share_at(r, 3)
    r.book("SOL", "102")
    out = r.gate.submit(r.add_req(share_id="S1", decision_px=D("102")))
    assert out.result is not None and out.result.accepted, out
    r.fill()
    pos = r.paper.broker.position("SOL")
    assert out.decision.qty is not None
    assert pos is not None and pos.qty == D(1) + out.decision.qty
    assert pos.leverage == out.decision.leverage == 3
    assert pos.liquidation_px == out.decision.liquidation_px  # merged average entry, same leverage, to the tick
    assert out.decision.final_notional_usd is not None
    assert abs(pos.margin_usd - (D("100") + out.decision.final_notional_usd) / 3) < D("1e-9")  # merged notional / 3


@pytest.mark.unit
@pytest.mark.parametrize("stop,ok", [("97.5", True), ("97.4", False)])
def test_F10_AC4_an_add_is_refused_add_leverage_unsafe_when_the_rule_fails_at_the_positions_leverage(
    new_risk: NewRisk, stop: str, ok: bool
) -> None:
    # at 10x the liquidation distance is 7.5% of the price (1/10 - 1/40): a stop 2.5 away passes (3 x 2.5 = 7.5),
    # 2.6 away does not. At a fresh 1x the distance is 97.5 and every stop would pass.
    r = new_risk()
    _long_share_at(r, 10)
    req = r.add_req(share_id="S1", stop_px=D(stop), current_stop_px=D(stop))
    r.book("SOL", "100")
    orders_before = len(r.paper.records("paper_order"))  # the seed's own order
    out = r.gate.submit(req)
    assert out.decision.approved is ok
    if ok:
        assert out.decision.leverage == 10 and out.result is not None and out.result.accepted
        return
    assert out.decision.reason == "add_leverage_unsafe" and out.result is None
    assert r.authority.issued == []
    assert len(r.paper.records("paper_order")) == orders_before and r.paper.records("paper_reject") == []
    payload = r.last_decision_payload()  # audited (A2, B5)
    assert payload["approved"] is False and payload["reason"] == "add_leverage_unsafe"
    position = r.paper.broker.position("SOL")
    assert position is not None and (position.leverage, position.qty) == (10, D("1.0"))


@pytest.mark.unit
def test_F10_AC4_the_same_add_is_approved_on_a_position_opened_at_a_lower_leverage(new_risk: NewRisk) -> None:
    r = new_risk()
    _long_share_at(r, 5)  # liquidation 82.5: 17.5 away, the stop 2.6 away needs 7.8
    d = r.gate.check(r.add_req(share_id="S1", stop_px=D("97.4"), current_stop_px=D("97.4")))
    assert d.approved and d.leverage == 5


@pytest.mark.unit
@pytest.mark.parametrize("leverage,ok", [(2, False), (3, True)])
def test_F10_AC4_an_add_is_refused_add_leverage_unsafe_when_the_margin_does_not_fit_at_the_positions_leverage(
    new_risk: NewRisk, leverage: int, ok: bool
) -> None:
    # equity 300; ETH holds 235 of margin. S1 (1.0 @ 100) at 2x posts 50, so 50 + 15 free = 65 is available and the
    # merged 150 needs 75 at 2x (refused); at 3x it posts 33.33, 65 is still available and 150 needs 50 (fits).
    # The fresh choice would be 3x in both cases.
    r = new_risk()
    _long_share_at(r, leverage)
    r.seed("ETH", qty="47", entry="100", leverage=20, open_risk="0.1")
    d = r.gate.check(r.add_req(share_id="S1"))
    assert d.approved is ok
    assert d.reason == (None if ok else "add_leverage_unsafe")
    if ok:
        assert d.leverage == leverage


@pytest.mark.unit
@pytest.mark.parametrize("leverage,ok", [(6, False), (5, True)])
def test_F10_AC4_an_add_is_refused_add_leverage_unsafe_when_the_positions_leverage_is_over_the_ceiling(
    new_risk: NewRisk, leverage: int, ok: bool
) -> None:
    # SOL is not on the high-tier list here, so its ceiling is the alt ceiling 5 (config)
    r = new_risk(risk__high_leverage_coins=("BTC",))
    _long_share_at(r, leverage)
    d = r.gate.check(r.add_req(share_id="S1"))
    assert d.approved is ok
    assert d.reason == (None if ok else "add_leverage_unsafe")
    assert d.leverage_ceiling == 5 or not ok


@pytest.mark.unit
def test_F10_AC4_an_open_on_a_coin_without_a_position_still_picks_the_lowest_fitting_leverage(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    _long_share_at(r, 10)  # a position at 10x elsewhere must not leak into the choice
    d = r.gate.check(r.open_req(coin="ETH"))
    assert d.approved and d.leverage == 1  # 100 <= free equity 290


def _leader_a_share_at_10x(r: RiskEnv) -> None:
    """Leader LA holds 1.0 SOL @ 100 at 10x (margin 10) on the real broker."""
    isolate_bucket(r, "SOL")
    r.seed("SOL", leader="LA", qty="1.0", entry="100", stop="98.5", leverage=10, share="SA")


@pytest.mark.unit
def test_F10_AC4_an_open_as_a_new_share_beside_a_10x_position_is_gated_at_10x(new_risk: NewRisk) -> None:
    # Amendment 12 addendum: any entry on a coin that holds a position uses that position's leverage (F11 keeps the
    # first entry's); a fresh choice would be 1x (merged 160 <= 10 + 290)
    r = new_risk()
    _leader_a_share_at_10x(r)
    before = r.paper.broker.position("SOL")
    assert before is not None
    d = r.gate.check(r.open_req(leader="L1", share_id="S10", stop_px=D("97.5")))
    assert d.approved and d.action is ActionKind.OPEN
    assert d.leverage == 10
    assert d.posted_margin_usd == before.margin_usd == D(10)
    meta = r.paper.meta.meta["SOL"]
    assert d.final_notional_usd is not None and d.qty is not None
    merged_avg = (D(100) + d.final_notional_usd) / (1 + d.qty)  # the new share fills at the decision price 100
    assert d.liquidation_px == liquidation_price(
        side="long", avg_entry_px=Price(merged_avg), leverage=10, max_leverage=meta.max_leverage,
        sz_decimals=meta.sz_decimals,
    )


@pytest.mark.integration
@pytest.mark.parametrize("stop,ok", [("97.5", True), ("97.4", False)])
def test_F10_AC4_an_open_beside_a_10x_position_is_refused_add_leverage_unsafe_when_the_rule_fails_at_10x(
    new_risk: NewRisk, stop: str, ok: bool
) -> None:
    # liquidation distance at 10x is 7.5: a stop 2.5 away passes (3 x 2.5), 2.6 away is refused; at a fresh 1x both pass
    r = new_risk()
    _leader_a_share_at_10x(r)
    r.book("SOL", "100")
    orders_before = len(r.paper.records("paper_order"))
    out = r.gate.submit(r.open_req(leader="L1", share_id="S10", stop_px=D(stop)))
    assert out.decision.approved is ok
    if ok:
        assert out.result is not None and out.result.accepted
        (intent, token), = r.authority.issued
        assert isinstance(intent, OrderIntent) and intent.action is ActionKind.OPEN and intent.leverage == 10
        assert r.authority.verify(token, intent) and not r.authority.verify(token, replace(intent, leverage=1))
        return
    assert out.decision.reason == "add_leverage_unsafe" and out.result is None
    assert r.authority.issued == []
    assert len(r.paper.records("paper_order")) == orders_before and r.paper.records("paper_reject") == []
    assert r.last_decision_payload()["reason"] == "add_leverage_unsafe"


@pytest.mark.integration
def test_F10_AC10_the_merged_leverage_the_broker_holds_after_an_open_beside_a_position_fills_is_the_gates(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    _leader_a_share_at_10x(r)
    r.book("SOL", "100")
    out = r.gate.submit(r.open_req(leader="L1", share_id="S10", stop_px=D("97.5")))
    assert out.result is not None and out.result.accepted, out
    r.fill()
    pos = r.paper.broker.position("SOL")
    assert out.decision.qty is not None and out.decision.final_notional_usd is not None
    assert pos is not None and pos.qty == D(1) + out.decision.qty
    assert pos.leverage == out.decision.leverage == 10
    assert pos.liquidation_px == out.decision.liquidation_px
    assert abs(pos.margin_usd - (D(100) + out.decision.final_notional_usd) / 10) < D("1e-9")


@pytest.mark.unit
@pytest.mark.parametrize("leverage,ok", [(2, False), (3, True)])
def test_F10_AC4_an_open_beside_a_position_is_refused_when_the_margin_does_not_fit_at_its_leverage(
    new_risk: NewRisk, leverage: int, ok: bool
) -> None:
    # equity 300; ETH holds 235. LA's 1.0 SOL posts 50 at 2x (65 available, the merged 160 needs 80: refused) or
    # 33.3 at 3x (65 available, 160/3 = 53.3 fits). A fresh choice would be 3x in both cases.
    r = new_risk()
    isolate_bucket(r, "SOL")
    r.seed("SOL", leader="LA", qty="1.0", entry="100", stop="98.5", leverage=leverage, share="SA")
    r.seed("ETH", qty="47", entry="100", leverage=20, open_risk="0.1")
    d = r.gate.check(r.open_req(leader="L1", share_id="S10", stop_px=D("97.5")))
    assert d.approved is ok
    assert d.reason == (None if ok else "add_leverage_unsafe")
    if ok:
        assert d.leverage == leverage


# ---- AC9 adds ---------------------------------------------------------------------------------------------------------


def _long_share(r: RiskEnv, *, is_long: bool = True) -> None:
    isolate_bucket(r, "SOL")
    stop = "98.5" if is_long else "101.5"
    r.seed("SOL", leader="L1", is_long=is_long, qty="1.0", entry="100", stop=stop, share="S1")


@pytest.mark.unit
def test_F10_AC9_add_quantity_is_our_share_times_the_leaders_add_fraction(new_risk: NewRisk) -> None:
    r = new_risk()
    _long_share(r)
    d = r.gate.check(r.add_req(share_id="S1"))  # 1.0 x (0.5 / 1.0)
    assert d.approved and d.qty == D("0.50") and d.final_notional_usd == D(50)
    assert d.leverage == 5  # Amendment 12: the seeded position's leverage, not a fresh choice


@pytest.mark.unit
@pytest.mark.parametrize(
    "leader_add,expected",
    [("1.0", "1.00"), ("2.0", "1.00"), ("1.01", "1.00"), ("0.99", "0.99")],
)
def test_F10_AC9_add_is_capped_so_the_shares_open_risk_stays_within_max_share_risk_fraction(
    new_risk: NewRisk, leader_add: str, expected: str
) -> None:
    # share risk so far 1.5; the cap is 0.01 x 300 = 3.00, so at most 1.5 more = 1.00 SOL at a 1.5 stop distance
    r = new_risk()
    _long_share(r)
    d = r.gate.check(r.add_req(share_id="S1", leader_add_size=Qty(leader_add)))
    assert d.approved and d.qty == D(expected)


@pytest.mark.unit
def test_F10_AC9_share_risk_cap_is_config(new_risk: NewRisk) -> None:
    r = new_risk(risk__max_share_risk_fraction=D("0.005"))  # 1.50 total: no room left on the share
    _long_share(r)
    d = r.gate.check(r.add_req(share_id="S1"))
    assert d.approved is False


@pytest.mark.unit
def test_F10_AC9_add_is_also_held_to_the_ac3_caps(new_risk: NewRisk) -> None:
    r = new_risk()
    _long_share(r)
    r.seed_risk_only("SOL", leader="LA", risk="2.75")  # symbol risk 1.5 + 2.75 = 4.25: 0.25 of room
    d = r.gate.check(r.add_req(share_id="S1", leader_add_size=Qty("1.0")))
    assert d.approved and d.qty == D("0.16")  # 0.25 / 1.5 = 0.1666 -> 0.16 (and 0.16 x 100 = $16 >= $10)


@pytest.mark.unit
@pytest.mark.parametrize("our_qty,ok", [("0.10", True), ("0.09", False), ("0.11", True)])
def test_F10_AC9_an_add_below_the_minimum_order_is_skipped_as_add_below_min(
    new_risk: NewRisk, our_qty: str, ok: bool
) -> None:
    r = new_risk()
    _long_share(r)
    d = r.gate.check(
        r.add_req(share_id="S1", our_share_qty=Qty(our_qty), leader_add_size=Qty("1.0"), leader_pre_add_position=Qty("1.0"))
    )
    assert d.approved is ok
    assert d.reason == (None if ok else "add_below_min")


@pytest.mark.unit
@pytest.mark.parametrize("stop,ok", [("97.9", False), ("98.4", False), ("98.5", True), ("99", True)])
def test_F10_AC9_a_long_add_whose_stop_sits_below_the_current_stop_is_stop_widening(
    new_risk: NewRisk, stop: str, ok: bool
) -> None:
    r = new_risk()
    _long_share(r)
    d = r.gate.check(r.add_req(share_id="S1", stop_px=D(stop), current_stop_px=D("98.5")))
    assert d.approved is ok
    assert d.reason == (None if ok else "stop_widening")


@pytest.mark.unit
@pytest.mark.parametrize("stop,ok", [("102", False), ("101.6", False), ("101.5", True), ("101", True)])
def test_F10_AC9_a_short_add_whose_stop_sits_above_the_current_stop_is_stop_widening(
    new_risk: NewRisk, stop: str, ok: bool
) -> None:
    r = new_risk()
    _long_share(r, is_long=False)
    d = r.gate.check(r.add_req(share_id="S1", is_long=False, stop_px=D(stop), current_stop_px=D("101.5")))
    assert d.approved is ok
    assert d.reason == (None if ok else "stop_widening")


@pytest.mark.unit
def test_F10_AC9_an_add_against_the_direction_of_the_position_is_refused(new_risk: NewRisk) -> None:
    r = new_risk()
    _long_share(r)
    d = r.gate.check(r.add_req(share_id="S1", is_long=False, stop_px=D("101.5"), current_stop_px=D("101.5")))
    assert (d.approved, d.reason) == (False, "opposite_side_entry")


@pytest.mark.unit
def test_F10_AC9_an_add_is_refused_while_paused_like_any_entry(new_risk: NewRisk) -> None:
    r = new_risk()
    _long_share(r)
    r.gate.pause()
    assert r.gate.check(r.add_req(share_id="S1")).reason == "paused"


# ---- opposite side (F11 contract: never send an opposite-side OPEN/ADD) ---------------------------------------------


@pytest.mark.unit
def test_F10_F11_contract_an_open_against_the_position_on_the_coin_is_refused_before_the_broker(
    new_risk: NewRisk,
) -> None:
    r = new_risk()
    r.seed("SOL", leader="LA", is_long=True, qty="1.0", entry="100", stop="98.5")
    out = r.gate.submit(r.open_req(is_long=False, stop_px=D("101.5")))
    assert (out.decision.approved, out.decision.reason, out.result) == (False, "opposite_side_entry", None)
    assert r.authority.issued == []
    assert r.paper.records("paper_reject") == []  # the broker never saw it
