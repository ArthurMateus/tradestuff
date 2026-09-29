"""F1.AC4: money is Decimal. Floats are refused; prices and sizes round by the Hyperliquid perp rule.

Price: <= 5 significant figures and <= (6 - szDecimals) decimals; integer prices are always valid.
``round_price`` returns the nearest valid price. Size rounds toward zero to ``szDecimals``.

Spec: 04-spec.md F1.AC4, invariants A6 and A9.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from copytrade.core.money import Fee, Funding, Notional, Pnl, Price, Qty, round_price, round_size

pytestmark = pytest.mark.unit

MONEY_TYPES = [Price, Qty, Notional, Fee, Funding, Pnl]
TYPE_IDS = [t.__name__ for t in MONEY_TYPES]
PERP_SZ_DECIMALS = st.integers(min_value=0, max_value=5)


# --- construction ------------------------------------------------------------------------------------

@pytest.mark.parametrize("money_type", MONEY_TYPES, ids=TYPE_IDS)
@pytest.mark.parametrize("value", [0.1, 1.0, -0.0, 67123.45, float("nan"), float("inf")], ids=repr)
def test_F1_AC4_constructing_money_from_a_binary_float_raises(money_type: type, value: float) -> None:
    with pytest.raises(TypeError):
        money_type(value)


@pytest.mark.parametrize("money_type", MONEY_TYPES, ids=TYPE_IDS)
@given(value=st.floats(allow_nan=True, allow_infinity=True))
def test_F1_AC4_property_no_float_is_ever_accepted(money_type: type, value: float) -> None:
    with pytest.raises(TypeError):
        money_type(value)


@pytest.mark.parametrize("money_type", MONEY_TYPES, ids=TYPE_IDS)
@pytest.mark.parametrize("value", [True, False], ids=repr)
def test_F1_AC4_constructing_money_from_a_bool_raises(money_type: type, value: bool) -> None:
    with pytest.raises(TypeError):
        money_type(value)


@pytest.mark.parametrize("money_type", MONEY_TYPES, ids=TYPE_IDS)
@pytest.mark.parametrize("value", [Decimal("0.1"), "0.1", 1, "67123.45", Decimal("1E-8")], ids=repr)
def test_F1_AC4_money_accepts_decimal_int_and_str_and_is_a_decimal(money_type: type, value: object) -> None:
    m = money_type(value)
    assert isinstance(m, Decimal)
    assert m == Decimal(str(value))


@pytest.mark.parametrize("money_type", [Funding, Pnl], ids=["Funding", "Pnl"])
def test_F1_AC4_signed_money_accepts_negative_values(money_type: type) -> None:
    assert money_type("-12.5") == Decimal("-12.5")


@pytest.mark.parametrize("money_type", MONEY_TYPES, ids=TYPE_IDS)
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), "-Infinity", "nan", "abc", ""], ids=repr)
def test_F1_AC4_non_finite_or_malformed_money_raises(money_type: type, value: object) -> None:
    with pytest.raises((ValueError, InvalidOperation)):
        money_type(value)


@pytest.mark.parametrize("money_type", MONEY_TYPES, ids=TYPE_IDS)
def test_F1_AC4_arithmetic_with_a_float_raises(money_type: type) -> None:
    m = money_type("1.5")
    with pytest.raises(TypeError):
        _ = m * 1.5
    with pytest.raises(TypeError):
        _ = m + 0.1


@given(value=st.decimals(allow_nan=False, allow_infinity=False, min_value=Decimal("-1e12"), max_value=Decimal("1e12"), places=10))
def test_F1_AC4_property_money_round_trips_through_str(value: Decimal) -> None:
    assert Pnl(str(value)) == value
    assert Funding(str(value)) == value
    assert Price(str(abs(value))) == abs(value)


# --- price rounding ---------------------------------------------------------------------------------------

def is_valid_price(p: Decimal, sz_decimals: int) -> bool:
    """The exchange rule, as stated in the spec (test oracle)."""
    if p <= 0:
        return False
    if p == p.to_integral_value():
        return True
    t = p.normalize().as_tuple()
    decimals = -t.exponent if isinstance(t.exponent, int) and t.exponent < 0 else 0
    return len(t.digits) <= 5 and decimals <= 6 - sz_decimals


def nearest_valid_distance(px: Decimal, sz_decimals: int) -> Decimal:
    """Distance from ``px`` to the nearest valid price (test oracle: checks every candidate grid)."""
    quantum = Decimal(1).scaleb(max(px.adjusted() - 4, -(6 - sz_decimals)))
    candidates = {
        px.to_integral_value(ROUND_FLOOR),
        px.to_integral_value(ROUND_CEILING),
        px.quantize(quantum, ROUND_FLOOR),
        px.quantize(quantum, ROUND_CEILING),
    }
    return min(abs(c - px) for c in candidates if is_valid_price(c, sz_decimals))


@pytest.mark.parametrize(
    ("px", "sz", "expected"),
    [
        ("67123.45", 5, "67123"),  # spec vector
        ("0.01234567", 0, "0.012346"),  # spec vector
        ("123456", 0, "123456"),  # integers are always allowed, even with 6 significant figures
        ("123456", 5, "123456"),
        ("1.234567", 0, "1.2346"),  # 5 significant figures
        ("0.00012345678", 0, "0.000123"),  # decimals cap: 6 - 0 = 6
        ("0.5555555", 4, "0.56"),  # decimals cap: 6 - 4 = 2
        ("99999.7", 1, "100000"),  # rounds up across a magnitude boundary
        ("2500", 3, "2500"),
    ],
)
def test_F1_AC4_price_rounding_vectors(px: str, sz: int, expected: str) -> None:
    result = round_price(Decimal(px), sz)
    assert isinstance(result, Price)
    assert result == Decimal(expected)


def test_F1_AC4_price_above_five_significant_figures_uses_the_nearest_integer() -> None:
    # 123456.7: 123457 (integer, valid) is nearer than the 5-significant-figure 123460.
    assert round_price(Decimal("123456.7"), 0) == Decimal("123457")


@given(
    px=st.decimals(min_value=Decimal("0.000001"), max_value=Decimal("5000000"), places=9, allow_nan=False, allow_infinity=False),
    sz=PERP_SZ_DECIMALS,
)
def test_F1_AC4_property_rounded_price_is_valid_and_nearest(px: Decimal, sz: int) -> None:
    assume(px >= Decimal(1).scaleb(-(6 - sz)))  # at least one tick; smaller prices do not exist on perps
    result = round_price(px, sz)
    assert is_valid_price(result, sz), f"{result} is not a valid price at szDecimals={sz}"
    assert abs(result - px) == nearest_valid_distance(px, sz)


@given(
    px=st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("5000000"), places=6, allow_nan=False, allow_infinity=False),
    sz=PERP_SZ_DECIMALS,
)
def test_F1_AC4_property_price_rounding_is_idempotent(px: Decimal, sz: int) -> None:
    assume(px >= Decimal(1).scaleb(-(6 - sz)))
    once = round_price(px, sz)
    assert round_price(Decimal(once), sz) == once


@pytest.mark.parametrize("px", ["0", "-1", "-67123.45"])
def test_F1_AC4_non_positive_price_is_rejected(px: str) -> None:
    with pytest.raises(ValueError):
        round_price(Decimal(px), 2)


@pytest.mark.parametrize("px", [Decimal("NaN"), Decimal("Infinity")], ids=str)
def test_F1_AC4_non_finite_price_is_rejected(px: Decimal) -> None:
    with pytest.raises((ValueError, InvalidOperation)):
        round_price(px, 2)


def test_F1_AC4_price_rounding_refuses_a_float() -> None:
    with pytest.raises(TypeError):
        round_price(67123.45, 5)  # type: ignore[arg-type]


@pytest.mark.parametrize("sz", [-1, 7])
def test_F1_AC4_out_of_range_sz_decimals_is_rejected(sz: int) -> None:
    with pytest.raises(ValueError):
        round_price(Decimal("100.5"), sz)
    with pytest.raises(ValueError):
        round_size(Decimal("1.5"), sz)


# --- size rounding ----------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("qty", "sz", "expected"),
    [
        ("0.123456", 3, "0.123"),  # spec vector
        ("0.1239", 3, "0.123"),  # down, never to nearest
        ("0.9999999", 0, "0"),
        ("5", 2, "5"),
        ("12.34567", 5, "12.34567"),
        ("0.00001", 5, "0.00001"),
        ("0.000009", 5, "0"),
        ("-0.1239", 3, "-0.123"),  # toward zero: magnitude never grows
    ],
)
def test_F1_AC4_size_rounds_down_to_sz_decimals(qty: str, sz: int, expected: str) -> None:
    result = round_size(Decimal(qty), sz)
    assert isinstance(result, Qty)
    assert result == Decimal(expected)


def test_F1_AC4_size_rounding_refuses_a_float() -> None:
    with pytest.raises(TypeError):
        round_size(0.123456, 3)  # type: ignore[arg-type]


@given(
    qty=st.decimals(min_value=Decimal("-1e7"), max_value=Decimal("1e7"), places=10, allow_nan=False, allow_infinity=False),
    sz=PERP_SZ_DECIMALS,
)
def test_F1_AC4_property_size_never_grows_and_loses_less_than_one_step(qty: Decimal, sz: int) -> None:
    step = Decimal(1).scaleb(-sz)
    result = round_size(qty, sz)
    assert abs(result) <= abs(qty)
    assert abs(qty) - abs(result) < step
    assert result == result.quantize(step)  # at most sz decimals
    assert result == 0 or (result > 0) == (qty > 0)  # sign preserved


@given(
    qty=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e7"), places=10, allow_nan=False, allow_infinity=False),
    sz=PERP_SZ_DECIMALS,
)
def test_F1_AC4_property_size_rounding_is_idempotent(qty: Decimal, sz: int) -> None:
    once = round_size(qty, sz)
    assert round_size(Decimal(once), sz) == once


@given(
    a=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e6"), places=8, allow_nan=False, allow_infinity=False),
    b=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e6"), places=8, allow_nan=False, allow_infinity=False),
    sz=PERP_SZ_DECIMALS,
)
def test_F1_AC4_property_size_rounding_is_monotonic(a: Decimal, b: Decimal, sz: int) -> None:
    lo, hi = min(a, b), max(a, b)
    assert round_size(lo, sz) <= round_size(hi, sz)
