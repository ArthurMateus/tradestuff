"""F5 DSR (edge-hypothesis 10.2 M7 and 10.7 test 12): literal vectors and monotonicity.

Vectors computed with Phi/PhiInv from the standard library (statistics.NormalDist), gamma = 0.5772.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.scoring.dsr import dsr_prob, sr0

pytestmark = pytest.mark.unit
D = Decimal


@pytest.mark.parametrize(
    ("t_days", "n_trials", "expected"),
    [(90, 15000, 0.41728164658492317), (120, 50, 0.2077965406382264), (60, 2, 0.06709830540431892)],
)
def test_F5_AC1_sr0_matches_emax_over_sqrt_t(t_days: int, n_trials: int, expected: float) -> None:
    assert abs(float(sr0(t_days, n_trials)) - expected) < 1e-9


@pytest.mark.parametrize(
    ("sr", "skew", "kurt", "t_days", "n", "expected"),
    [
        ("0.5", "0", "3", 90, 15000, 0.7690535981935261),
        ("0.6", "-0.5", "4", 120, 1000, 0.9958134292123278),
        ("0.2", "0", "3", 60, 50, 0.2376397937291067),
    ],
)
def test_F5_AC1_dsr_prob_vectors(sr: str, skew: str, kurt: str, t_days: int, n: int, expected: float) -> None:
    got = dsr_prob(sr_d=D(sr), skew=D(skew), kurt=D(kurt), t_days=t_days, n_trials=n)
    assert isinstance(got, Decimal)
    assert abs(float(got) - expected) < 1e-9


@pytest.mark.parametrize("kwargs", [{"t_days": 90, "n_trials": 1}, {"t_days": 1, "n_trials": 100}, {"t_days": 90, "n_trials": 0}])
def test_F5_AC1_dsr_rejects_degenerate_trial_or_day_counts(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        dsr_prob(sr_d=D("0.1"), skew=D(0), kurt=D(3), **kwargs)


def test_F5_AC1_dsr_rejects_a_non_positive_variance_term() -> None:
    with pytest.raises(ValueError):
        dsr_prob(sr_d=D(2), skew=D(10), kurt=D(1), t_days=90, n_trials=100)  # 1 - 20 + 0 < 0


@given(
    sr=st.decimals(min_value="-1", max_value="1", places=3),
    t_days=st.integers(30, 365),
    n_small=st.integers(50, 20_000),
    extra=st.integers(0, 50_000),
)
def test_F5_AC5_dsr_is_non_increasing_in_trials(sr: Decimal, t_days: int, n_small: int, extra: int) -> None:
    lo = dsr_prob(sr_d=sr, skew=D(0), kurt=D(3), t_days=t_days, n_trials=n_small)
    hi = dsr_prob(sr_d=sr, skew=D(0), kurt=D(3), t_days=t_days, n_trials=n_small + extra)
    assert hi <= lo + D("1e-12")


@given(
    a=st.decimals(min_value="-1", max_value="1", places=3),
    b=st.decimals(min_value="-1", max_value="1", places=3),
    t_days=st.integers(30, 365),
    n=st.integers(50, 50_000),
)
def test_F5_AC5_dsr_is_non_decreasing_in_the_sharpe_ratio(a: Decimal, b: Decimal, t_days: int, n: int) -> None:
    low, high = sorted((a, b))
    p_low = dsr_prob(sr_d=low, skew=D(0), kurt=D(3), t_days=t_days, n_trials=n)
    p_high = dsr_prob(sr_d=high, skew=D(0), kurt=D(3), t_days=t_days, n_trials=n)
    assert p_high >= p_low - D("1e-12")


@given(sr=st.decimals(min_value="-1", max_value="1", places=3), t_days=st.integers(30, 365), n=st.integers(50, 50_000))
def test_F5_AC5_dsr_is_a_probability(sr: Decimal, t_days: int, n: int) -> None:
    p = dsr_prob(sr_d=sr, skew=D(0), kurt=D(3), t_days=t_days, n_trials=n)
    assert D(0) <= p <= D(1)
