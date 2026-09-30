# mypy: disable-error-code="union-attr"
"""F11.AC4: exchange rules. Orders below sizing.min_order_usd are refused ``below_min_notional`` (a reduce-only full
close is exempt); tick/lot/leverage rules come from ``meta`` refreshed every paper.meta_refresh_min; a coin missing
from ``meta`` is refused ``unknown_coin``. Every refusal is logged (``paper_reject``) and creates no fill."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D

import pytest
from tests.paper.helpers import Env
from typing import Any
from tests.paper.helpers import NewEnv

from copytrade.core.domain import ActionKind
from copytrade.core.money import Qty
from copytrade.paper.types import CoinMeta
from tests.paper.helpers import D0, FakeMeta, make_config

MIN = 60_000


def _reject_records(e: Env) -> list[Any]:
    return [r.payload for r in e.records("paper_reject")]


@pytest.mark.unit
@pytest.mark.parametrize(
    "qty,px,accepted",
    [
        ("0.10", "100", True),  # exactly $10.00
        ("0.10", "99.99", False),  # $9.999
        ("0.09", "111.12", True),  # $10.0008
        ("0.09", "111.11", False),  # $9.9999
    ],
)
def test_F11_AC4_minimum_notional_boundary(new_env: NewEnv, qty: Any, px: Any, accepted: Any) -> None:
    e = new_env()
    result = e.submit(e.order("buy", qty, px=px))
    assert result.accepted is accepted
    assert result.reason == (None if accepted else "below_min_notional")
    if not accepted:
        assert e.broker.position("SOL") is None
        assert _reject_records(e)[-1]["reason"] == "below_min_notional"
        assert _reject_records(e)[-1]["client_order_id"] == "c1"


@pytest.mark.unit
def test_F11_AC4_minimum_is_data_driven(new_env: NewEnv) -> None:
    e = new_env(config=make_config(sizing__min_order_usd=D("25")))
    assert e.submit(e.order("buy", "0.24", px="100", coid="a")).reason == "below_min_notional"  # $24
    assert e.submit(e.order("buy", "0.25", px="100", coid="b")).accepted  # $25


@pytest.mark.unit
def test_F11_AC4_reduce_only_full_close_below_the_minimum_is_allowed(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "0.1", px="100")  # $10.00, accepted
    e.flat_book("SOL", D0 + 61_000, "90")
    result = e.submit(e.order("sell", "0.10", coid="x", action=ActionKind.CLOSE, decided=D0 + 60_000, px="90"))
    assert result.accepted  # $9.00 but a full close
    e.advance(D0 + 61_000)
    assert e.broker.position("SOL") is None
    assert len(e.trades()) == 1


@pytest.mark.unit
def test_F11_AC4_a_partial_reduce_below_the_minimum_is_refused(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "0.1", px="100")
    result = e.submit(e.order("sell", "0.05", coid="x", action=ActionKind.REDUCE, decided=D0 + 60_000, px="90"))
    assert (result.accepted, result.reason) == (False, "below_min_notional")  # $4.50, not the whole position


@pytest.mark.unit
def test_F11_AC4_unknown_coin_is_refused_and_logged(new_env: NewEnv) -> None:
    e = new_env()
    result = e.submit(e.order("buy", "1.0", coin="NOPE"))
    assert (result.accepted, result.reason) == (False, "unknown_coin")
    assert _reject_records(e)[-1]["reason"] == "unknown_coin" and _reject_records(e)[-1]["coin"] == "NOPE"
    assert e.records("fill") == []


@pytest.mark.unit
def test_F11_AC4_size_is_rounded_down_to_the_lot(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", D0 + 1000, "100")
    assert e.submit(e.order("buy", "1.005")).accepted  # SOL szDecimals = 2
    fill = e.advance(D0 + 1000)[0].fill
    assert fill.qty == Qty("1.00")  # never rounded up (exposure never grows)


@pytest.mark.unit
def test_F11_AC4_a_size_that_rounds_to_zero_is_refused_below_minimum(new_env: NewEnv) -> None:
    e = new_env()
    assert e.submit(e.order("buy", "0.004", px="10000")).reason == "below_min_notional"


@pytest.mark.unit
def test_F11_AC4_leverage_above_the_coin_max_is_refused_and_equal_is_accepted(new_env: NewEnv) -> None:
    e = new_env()  # DOGE max leverage 10
    assert e.submit(e.order("buy", "100", coin="DOGE", px="0.1", leverage=11, coid="a")).reason == "leverage_exceeds_max"
    assert e.submit(e.order("buy", "100", coin="DOGE", px="0.1", leverage=10, coid="b")).accepted


@pytest.mark.unit
def test_F11_AC4_an_entry_without_leverage_is_refused(new_env: NewEnv) -> None:
    e = new_env()
    intent = replace(e.order("buy", "1.0"), leverage=None)
    assert e.submit(intent).reason == "leverage_missing"


@pytest.mark.unit
def test_F11_AC4_a_reduce_or_close_larger_than_the_share_is_refused(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    too_big = e.order("sell", "1.01", coid="x", action=ActionKind.CLOSE, decided=D0 + 60_000)
    assert e.submit(too_big).reason == "exceeds_position"
    no_share = e.order("sell", "1.0", coid="y", action=ActionKind.CLOSE, decided=D0 + 60_000, share="NOPE")
    assert e.submit(no_share).reason == "exceeds_position"


@pytest.mark.unit
def test_F11_AC4_meta_is_refreshed_every_paper_meta_refresh_min_and_not_before(new_env: NewEnv) -> None:
    e = new_env()
    e.submit(e.order("buy", "1.0", coid="a"))
    first = e.meta.fetches
    assert first >= 1
    e.clock.now = D0 + 60 * MIN - 1
    e.submit(e.order("buy", "1.0", coid="b"))
    assert e.meta.fetches == first  # 59 min 59.999 s: not yet
    e.clock.now = D0 + 60 * MIN
    e.submit(e.order("buy", "1.0", coid="c"))
    assert e.meta.fetches == first + 1  # exactly 60 min


@pytest.mark.unit
def test_F11_AC4_a_coin_listed_after_the_refresh_becomes_tradable(new_env: NewEnv) -> None:
    e = new_env(config=make_config(paper__meta_refresh_min=5))
    assert e.submit(e.order("buy", "1.0", coin="AVAX", coid="a")).reason == "unknown_coin"
    e.meta.meta["AVAX"] = CoinMeta(sz_decimals=2, max_leverage=10)
    e.clock.now = D0 + 5 * MIN
    assert e.submit(e.order("buy", "1.0", coin="AVAX", coid="b")).accepted


@pytest.mark.unit
def test_F11_AC4_meta_unavailable_at_first_use_fails_closed_and_recovers(new_env: NewEnv) -> None:
    meta = FakeMeta()
    meta.fail = True
    e = new_env(meta=meta)
    result = e.submit(e.order("buy", "1.0"))
    assert (result.accepted, result.reason) == (False, "meta_unavailable")
    assert e.records("fill") == []
    meta.fail = False
    assert e.submit(e.order("buy", "1.0", coid="c2")).accepted


@pytest.mark.unit
def test_F11_AC4_pinned_a_failed_refresh_keeps_the_last_known_meta_and_retries_next_call(new_env: NewEnv) -> None:
    e = new_env()
    assert e.submit(e.order("buy", "1.0", coid="a")).accepted
    e.meta.fail = True
    e.clock.now = D0 + 60 * MIN
    assert e.submit(e.order("buy", "1.0", coid="b")).accepted  # cached meta still serves
    before = e.meta.fetches
    e.submit(e.order("buy", "1.0", coid="c"))
    assert e.meta.fetches == before + 1  # retried on the next call, not only after another hour


@pytest.mark.unit
def test_F11_AC4_fill_prices_stay_exact_decimals_not_rounded_to_a_tick(new_env: NewEnv) -> None:
    e = new_env()
    e.book("SOL", D0 + 1000, [("99.9", "5")], [("100.0", "1"), ("100.1", "2")])
    e.submit(e.order("buy", "3.0"))
    fill = e.advance(D0 + 1000)[0].fill
    assert abs(fill.price - D("300.2") / 3) < D("1e-15")  # (100.0 + 2 x 100.1) / 3, not snapped to 100.07
