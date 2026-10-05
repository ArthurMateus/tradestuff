"""R5.AC8 (R4-SD1): the empty coin name is not a core perp, in both places the predicate is exposed."""

from __future__ import annotations

from copytrade.core.coins import is_core_perp
from copytrade.scoring.reconstruct import is_core_perp as scoring_is_core_perp


def test_R5_AC8_the_empty_coin_name_is_not_a_core_perp() -> None:
    assert is_core_perp("") is False
    assert scoring_is_core_perp("") is False
