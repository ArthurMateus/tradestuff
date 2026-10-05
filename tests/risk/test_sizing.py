"""F10.AC2 sizing maths: mirror notional, risk notional, lot rounding. Hand-computed vectors and properties."""

from __future__ import annotations

from decimal import Context, Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.money import Price, Qty
from copytrade.risk.sizing import lot_qty_down, mirror_notional_usd, risk_notional_usd, stop_distance_fraction

PRECISE = Context(prec=60)


@pytest.mark.unit
def test_F10_AC2_worked_example_mirror_is_150_risk_is_100() -> None:
    mirror = mirror_notional_usd(
        leader_position_notional_usd=D(500), leader_account_value_usd=D(1000), equity_usd=D(300)
    )
    frac = stop_distance_fraction(decision_px=Price("100"), stop_px=Price("98.5"))
    risk = risk_notional_usd(
        equity_usd=D(300), per_trade_fraction=D("0.005"), vol_mult=D(1), stop_distance_fraction=frac
    )
    assert mirror == D(150)
    assert frac == D("0.015")
    assert risk == D(100)
    assert min(mirror, risk) == D(100)


@pytest.mark.unit
def test_F10_AC2_mirror_is_exact_when_the_quotient_does_not_terminate() -> None:
    # 100 / 3000 x 300 is exactly 10: a divide-then-multiply order gives 9.99..9 and loses the $10 minimum (A6).
    mirror = mirror_notional_usd(
        leader_position_notional_usd=D(100), leader_account_value_usd=D(3000), equity_usd=D(300)
    )
    assert mirror == D(10)


@pytest.mark.unit
def test_F10_AC2_risk_notional_scales_with_vol_mult() -> None:
    kw = dict(equity_usd=D(300), per_trade_fraction=D("0.005"), stop_distance_fraction=D("0.015"))
    assert risk_notional_usd(vol_mult=D(2), **kw) == D(200)
    assert risk_notional_usd(vol_mult=D("0.5"), **kw) == D(50)


@pytest.mark.unit
@pytest.mark.parametrize("stop_px,expected", [("98.5", "0.015"), ("101.5", "0.015"), ("100", "0"), ("90", "0.1")])
def test_F10_AC2_stop_distance_fraction_is_absolute_and_relative_to_the_decision_price(
    stop_px: str, expected: str
) -> None:
    assert stop_distance_fraction(decision_px=Price("100"), stop_px=Price(stop_px)) == D(expected)


@pytest.mark.unit
@pytest.mark.parametrize("frac", [D(0), D("-0.01")])
def test_F10_AC2_a_non_positive_stop_distance_is_refused_not_divided(frac: D) -> None:
    with pytest.raises(ValueError):
        risk_notional_usd(equity_usd=D(300), per_trade_fraction=D("0.005"), vol_mult=D(1), stop_distance_fraction=frac)


@pytest.mark.unit
@pytest.mark.parametrize(
    "notional,px,dec,expected",
    [
        ("100", "100", 2, "1.00"),
        ("99.99", "100", 2, "0.99"),
        ("99.999999", "100", 2, "0.99"),
        ("10", "3", 0, "3"),
        ("10", "100", 2, "0.10"),
        ("9.99", "100", 2, "0.09"),
        ("0", "100", 2, "0.00"),
        ("33.333333", "100", 4, "0.3333"),
    ],
)
def test_F10_AC2_lot_rounding_is_always_down(notional: str, px: str, dec: int, expected: str) -> None:
    q = lot_qty_down(notional_usd=D(notional), px=Price(px), sz_decimals=dec)
    assert q == D(expected)
    assert isinstance(q, Qty)


@pytest.mark.unit
@given(
    notional=st.decimals(min_value=D(0), max_value=D(10**7), places=6),
    px=st.decimals(min_value=D("0.01"), max_value=D(10**5), places=4),
    dec=st.integers(min_value=0, max_value=6),
)
@settings(max_examples=500)
def test_F10_AC2_property_lot_rounding_never_exceeds_the_notional_and_loses_under_one_lot(
    notional: D, px: D, dec: int
) -> None:
    q = lot_qty_down(notional_usd=notional, px=Price(px), sz_decimals=dec)
    lot = D(1).scaleb(-dec)
    assert q >= 0
    assert PRECISE.multiply(q, px) <= notional
    assert PRECISE.multiply(q + lot, px) > notional
    assert q == q.quantize(lot)


@pytest.mark.unit
@given(
    lead_n=st.decimals(min_value=D("0.01"), max_value=D(10**6), places=2),
    lead_av=st.decimals(min_value=D("1"), max_value=D(10**7), places=2),
    eq=st.decimals(min_value=D("1"), max_value=D(10**6), places=2),
    k=st.integers(min_value=2, max_value=50),
)
@settings(max_examples=300)
def test_F10_AC2_property_mirror_is_proportional_to_equity_and_to_the_leader_fraction(
    lead_n: D, lead_av: D, eq: D, k: int
) -> None:
    base = mirror_notional_usd(leader_position_notional_usd=lead_n, leader_account_value_usd=lead_av, equity_usd=eq)
    scaled = mirror_notional_usd(
        leader_position_notional_usd=lead_n, leader_account_value_usd=lead_av, equity_usd=eq * k
    )
    assert abs(scaled - PRECISE.multiply(base, k)) <= D("1e-40") * max(scaled, D(1))
    assert base >= 0
    # C2: the leader's own size never matters, only the fraction of THEIR account
    same_fraction = mirror_notional_usd(
        leader_position_notional_usd=lead_n * k, leader_account_value_usd=lead_av * k, equity_usd=eq
    )
    assert abs(same_fraction - base) <= D("1e-40") * max(base, D(1))


@pytest.mark.unit
@given(
    eq=st.decimals(min_value=D("1"), max_value=D(10**6), places=2),
    frac=st.decimals(min_value=D("0.001"), max_value=D("0.01"), places=3),
    vol=st.decimals(min_value=D("0.1"), max_value=D(3), places=1),
    stop=st.decimals(min_value=D("0.001"), max_value=D("0.5"), places=3),
)
@settings(max_examples=300)
def test_F10_AC2_property_loss_at_the_stop_equals_the_risk_budget_and_grows_with_equity(
    eq: D, frac: D, vol: D, stop: D
) -> None:
    n = risk_notional_usd(equity_usd=eq, per_trade_fraction=frac, vol_mult=vol, stop_distance_fraction=stop)
    assert abs(PRECISE.multiply(n, stop) - PRECISE.multiply(PRECISE.multiply(eq, frac), vol)) <= D("1e-40")
    bigger = risk_notional_usd(equity_usd=eq + 1, per_trade_fraction=frac, vol_mult=vol, stop_distance_fraction=stop)
    assert bigger > n
