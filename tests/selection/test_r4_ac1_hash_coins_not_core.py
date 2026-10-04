"""R4.AC1 [unit]: ``#N`` pseudo-coins are not core perps, and there is ONE definition of "core perp".

Hyperliquid fills carry pseudo-coins named ``#0``, ``#10``, ``#140``, ``#1020``, ``#7521`` (candleSnapshot answers
HTTP 500 for each, none is in the meta perp universe). ``is_core_perp`` and the recorder universe must both exclude
them; the recorder's own copy of the predicate must not be able to disagree (checked through the public
``select_universe``, so a shared implementation or two equal ones both pass).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.recorder.universe import ALWAYS_RECORDED, select_universe
from copytrade.scoring.reconstruct import is_core_perp

HASH = ["#0", "#10", "#140", "#1020", "#7521", "#", "#abc", "#-1"]
CORE = ["BTC", "ETH", "kPEPE", "PURR", "SOL", "kBONK", "1000PEPE", "A#B"]
EXCLUDED = ["@107", "@0", "PURR/USDC", "xyz:GOLD", "flx:TSLA"]


def recorded(coin: str) -> bool:
    out = select_universe(traded_coins=[coin], hip3_markets=[], volume_24h_usd={}, max_coins=10**6)
    return coin in out


@pytest.mark.parametrize("coin", HASH)
def test_R4_AC1_hash_names_are_not_core_perps(coin: str) -> None:
    assert is_core_perp(coin) is False


@pytest.mark.parametrize("coin", HASH)
def test_R4_AC1_the_recorder_universe_drops_hash_names(coin: str) -> None:
    assert recorded(coin) is False


@pytest.mark.parametrize("coin", CORE)
def test_R4_AC1_real_core_perps_stay_core_in_both(coin: str) -> None:
    assert is_core_perp(coin) is True
    assert recorded(coin) is True


@pytest.mark.parametrize("coin", EXCLUDED)
def test_R4_AC1_spot_pairs_and_hip3_stay_excluded_in_both(coin: str) -> None:
    assert is_core_perp(coin) is False
    assert recorded(coin) is False


@settings(max_examples=300, deadline=None)
@given(
    st.one_of(
        st.text(alphabet="#@/:ABCxyz0129k", min_size=1, max_size=6),
        st.builds(lambda tail: "#" + tail, st.text(alphabet="#@/:ABCxyz0129k", max_size=5)),
    ).filter(lambda c: c not in ALWAYS_RECORDED)
)
def test_R4_AC1_the_two_predicates_cannot_disagree(coin: str) -> None:
    assert recorded(coin) is is_core_perp(coin)


@settings(max_examples=200, deadline=None)
@given(st.text(alphabet="0123456789abc@/:", max_size=6))
def test_R4_AC1_any_name_starting_with_hash_is_excluded(tail: str) -> None:
    assert is_core_perp("#" + tail) is False
    assert recorded("#" + tail) is False
