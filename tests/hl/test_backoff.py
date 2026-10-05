"""F3.AC2 / F3.AC3: exponential backoff with jitter. Spec: 04-spec.md F3.AC2, hl.backoff_base_s / hl.backoff_max_s."""

from __future__ import annotations

import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.hl.backoff import backoff_delay_s

pytestmark = pytest.mark.unit


@given(
    attempt=st.integers(min_value=0, max_value=30),
    base=st.integers(min_value=1, max_value=10),
    max_s=st.integers(min_value=10, max_value=300),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_F3_AC2_backoff_delay_is_between_the_exponential_floor_and_the_maximum(
    attempt: int, base: int, max_s: int, seed: int
) -> None:
    d = backoff_delay_s(attempt, base_s=base, max_s=max_s, rng=random.Random(seed))
    floor = min(max_s, base * 2**attempt)
    assert floor <= d <= max_s
    assert d <= 2 * floor  # jitter never more than doubles the un-jittered value


def test_F3_AC2_backoff_has_jitter_and_is_reproducible_from_the_seed() -> None:
    draws = {backoff_delay_s(3, base_s=1, max_s=300, rng=random.Random(s)) for s in range(50)}
    assert len(draws) > 10  # not constant
    assert backoff_delay_s(3, base_s=1, max_s=300, rng=random.Random(7)) == backoff_delay_s(
        3, base_s=1, max_s=300, rng=random.Random(7)
    )


def test_F3_AC2_backoff_is_capped_at_max_for_huge_attempt_numbers() -> None:
    assert backoff_delay_s(10_000, base_s=1, max_s=60, rng=random.Random(1)) == 60


@pytest.mark.parametrize(
    ("attempt", "base", "max_s"), [(-1, 1, 60), (0, 0, 60), (0, -1, 60), (0, 10, 5)], ids=repr
)
def test_F3_AC2_backoff_rejects_invalid_arguments(attempt: int, base: int, max_s: int) -> None:
    with pytest.raises(ValueError):
        backoff_delay_s(attempt, base_s=base, max_s=max_s, rng=random.Random(1))
