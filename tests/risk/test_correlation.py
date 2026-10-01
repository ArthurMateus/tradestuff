"""Pearson correlation for the BTC bucket (F10.AC3)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.risk.correlation import pearson
from tests.risk.helpers import opposite_returns, same_returns, uncorrelated_returns, wide_returns

EPS = D("1e-20")


@pytest.mark.unit
def test_F10_AC3_a_series_is_perfectly_correlated_with_a_positive_multiple_of_itself() -> None:
    r = pearson(wide_returns(), same_returns())
    assert r is not None and abs(r - 1) <= EPS


@pytest.mark.unit
def test_F10_AC3_a_negated_series_has_correlation_minus_one() -> None:
    r = pearson(wide_returns(), opposite_returns())
    assert r is not None and abs(r + 1) <= EPS


@pytest.mark.unit
def test_F10_AC3_orthogonal_zero_mean_series_have_correlation_zero() -> None:
    r = pearson(wide_returns(), uncorrelated_returns())
    assert r is not None and abs(r) <= EPS


@pytest.mark.unit
def test_F10_AC3_a_hand_computed_value() -> None:
    # x = 1,2,3,4,5 and y = 2,4,5,4,5: cov = 6, var_x = 10, var_y = 6, r = 6 / sqrt(60)
    xs = [D(1), D(2), D(3), D(4), D(5)]
    ys = [D(2), D(4), D(5), D(4), D(5)]
    r = pearson(xs, ys)
    assert r is not None and abs(r - D(6) / D(60).sqrt()) <= EPS


@pytest.mark.unit
def test_F10_AC3_zero_variance_or_too_few_points_is_unknown_not_a_number() -> None:
    assert pearson([D(1)] * 5, [D(1), D(2), D(3), D(4), D(5)]) is None
    assert pearson([D(1), D(2), D(3), D(4), D(5)], [D(2)] * 5) is None
    assert pearson([D(1)], [D(2)]) is None
    assert pearson([], []) is None


@pytest.mark.unit
def test_F10_AC3_series_of_different_length_are_refused() -> None:
    with pytest.raises(ValueError):
        pearson([D(1), D(2), D(3)], [D(1), D(2)])


@pytest.mark.unit
@given(
    xs=st.lists(st.decimals(min_value=D("-0.5"), max_value=D("0.5"), places=4), min_size=3, max_size=40),
    data=st.data(),
)
@settings(max_examples=300)
def test_F10_AC3_property_correlation_is_symmetric_and_within_minus_one_and_one(xs: list[D], data: st.DataObject) -> None:
    ys = data.draw(
        st.lists(st.decimals(min_value=D("-0.5"), max_value=D("0.5"), places=4), min_size=len(xs), max_size=len(xs))
    )
    a, b = pearson(xs, ys), pearson(ys, xs)
    assert (a is None) == (b is None)
    if a is not None and b is not None:
        assert abs(a - b) <= EPS
        assert -1 - EPS <= a <= 1 + EPS
