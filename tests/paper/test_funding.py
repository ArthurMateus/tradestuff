# mypy: disable-error-code="union-attr"
"""F11.AC3: at each UTC hour boundary each open share pays or receives qty x oracle_px x hourly rate, signed by side,
at that hour's actual rate. A share closed before the boundary, or opened after it, pays nothing for that hour.

Conventions pinned here (see the test plan, spec issues): a longs-pay positive rate; funding amounts are cash flows
to us (paid is negative); a fill at exactly the boundary millisecond counts as not holding the position over it;
a missing funding snapshot is never skipped: it is retried and alerted once (``funding_missing``).
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from tests.paper.helpers import Env
from typing import Any
from tests.paper.helpers import NewEnv
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.domain import ActionKind
from copytrade.core.money import Funding
from tests.paper.helpers import BASE, D0, HOUR_MS, fresh_env

B1 = BASE + HOUR_MS
B2 = BASE + 2 * HOUR_MS


def _funding_records(e: Env) -> list[Any]:
    return e.records("paper_funding")


def _close(e: Env, decided: int, px: str = "100", qty: str = "2.0", coid: str = "close1", share: str = "S1") -> list[Any]:
    e.flat_book("SOL", decided + 1000, px)
    e.submit(e.order("sell", qty, coid=coid, action=ActionKind.CLOSE, decided=decided, px=px, share=share))
    return e.advance(decided + 1000)


@pytest.mark.unit
def test_F11_AC3_long_pays_positive_rate_at_the_boundary(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B1)
    (rec,) = _funding_records(e)
    assert rec.payload["amount"] == D("-0.02")  # 2.0 x 100 x 0.0001, paid
    assert (rec.payload["coin"], rec.payload["share_id"], rec.payload["hour_ms"]) == ("SOL", "S1", B1)
    assert (rec.payload["rate"], rec.payload["oracle_px"]) == (D("0.0001"), D("100"))
    assert e.broker.cash_usd() == D("299.89")  # 300 - 0.09 entry fee - 0.02 funding


@pytest.mark.unit
def test_F11_AC3_short_receives_positive_rate(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("sell", "2.0", px="100")
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B1)
    assert _funding_records(e)[0].payload["amount"] == D("0.02")
    assert e.broker.cash_usd() == D("299.93")  # 300 - 0.09 + 0.02


@pytest.mark.unit
def test_F11_AC3_negative_rate_flips_the_sign(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B1, "-0.0001", "100")
    e.advance(B1)
    assert _funding_records(e)[0].payload["amount"] == D("0.02")


@pytest.mark.unit
def test_F11_AC3_nothing_accrues_one_ms_before_the_boundary(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B1 - 1)
    assert _funding_records(e) == []


@pytest.mark.unit
def test_F11_AC3_each_hour_uses_its_own_actual_rate_and_oracle_price_over_a_multi_hour_jump(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B1, "0.0001", "100")
    e.funding.set("SOL", B2, "0.00005", "110")
    e.advance(B2 + 1)  # one call crosses two boundaries
    recs = _funding_records(e)
    assert [r.payload["hour_ms"] for r in recs] == [B1, B2]
    assert [r.payload["amount"] for r in recs] == [D("-0.02"), D("-0.011")]  # 2x100x0.0001 ; 2x110x0.00005
    assert e.broker.cash_usd() == D("299.879")  # 300 - 0.09 - 0.02 - 0.011


@pytest.mark.unit
def test_F11_AC3_advancing_again_never_accrues_an_hour_twice(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B1)
    e.advance(B1)
    e.advance(B1 + 30 * 60_000)
    assert len(_funding_records(e)) == 1
    assert e.broker.cash_usd() == D("299.89")


@pytest.mark.unit
def test_F11_AC3_closing_fill_carries_the_accrued_funding_and_the_trade_nets_it(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B1)
    _close(e, B1 + 600_000)
    entry, exit_fill = e.fills()
    assert entry.funding == Funding("0")
    assert exit_fill.funding == Funding("-0.02")
    (trade,) = e.trades()
    assert trade.pnl_usd == D("-0.20")  # 0 gross - 0.09 - 0.09 fees - 0.02 funding
    assert e.broker.cash_usd() == D("299.80")


@pytest.mark.unit
def test_F11_AC3_a_share_closed_before_the_boundary_pays_nothing(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    _close(e, D0 + 60_000)
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B1 + 1)
    assert _funding_records(e) == []
    assert e.fills()[1].funding == Funding("0")


@pytest.mark.unit
def test_F11_AC3_a_share_opened_after_the_boundary_pays_only_from_the_next_hour(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100", decided=B1 + 600_000)
    e.funding.set("SOL", B1, "0.0001", "100")
    e.funding.set("SOL", B2, "0.0001", "100")
    e.advance(B2)
    assert [r.payload["hour_ms"] for r in _funding_records(e)] == [B2]


@pytest.mark.unit
def test_F11_AC3_pinned_a_fill_at_exactly_the_boundary_ms_does_not_hold_the_position_over_it(new_env: NewEnv) -> None:
    opened = new_env()
    opened.open_position("buy", "2.0", px="100", decided=B1 - 1000)  # fills at exactly B1
    opened.funding.set("SOL", B1, "0.0001", "100")
    opened.advance(B1)
    assert _funding_records(opened) == []

    closed = new_env()
    closed.open_position("buy", "2.0", px="100")
    closed.funding.set("SOL", B1, "0.0001", "100")
    _close(closed, B1 - 1000)  # closing fill at exactly B1
    closed.advance(B1)
    assert _funding_records(closed) == []


@pytest.mark.unit
def test_F11_AC3_a_fill_one_ms_either_side_of_the_boundary_is_decided_by_strict_order(new_env: NewEnv) -> None:
    before = new_env()
    before.open_position("buy", "2.0", px="100", decided=B1 - 1001)  # fills at B1 - 1: held over B1
    before.funding.set("SOL", B1, "0.0001", "100")
    before.advance(B1)
    assert len(_funding_records(before)) == 1


@pytest.mark.unit
def test_F11_AC3_two_shares_on_one_coin_each_pay_their_own_funding(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", coid="o1", share="S1", trade="T1")
    e.open_position("buy", "1.0", px="100", coid="o2", share="S2", trade="T2", decided=D0 + 10_000,
                    action=ActionKind.ADD)
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B1)
    recs = _funding_records(e)
    assert sorted((r.payload["share_id"], r.payload["amount"]) for r in recs) == [
        ("S1", D("-0.01")), ("S2", D("-0.01")),
    ]


@pytest.mark.unit
def test_F11_AC3_missing_funding_data_is_not_skipped_it_is_alerted_once_then_accrued_when_it_arrives(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.advance(B1 + 1)
    e.advance(B1 + 2)
    assert _funding_records(e) == []
    assert e.alerts.kinds().count("funding_missing") == 1
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B1 + 3)
    (rec,) = _funding_records(e)
    assert rec.payload["hour_ms"] == B1 and rec.payload["amount"] == D("-0.02")


@pytest.mark.unit
def test_F11_AC3_funding_only_touches_open_positions(new_env: NewEnv) -> None:
    e = new_env()
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B2)
    assert _funding_records(e) == []
    assert e.broker.cash_usd() == D("300")


@pytest.mark.unit
@settings(max_examples=20)
@given(
    qty=st.integers(min_value=100, max_value=10_000),
    oracle=st.integers(min_value=1000, max_value=50_000),
    rate=st.integers(min_value=-1000, max_value=1000),
)
def test_F11_AC3_property_long_and_short_funding_are_exact_opposites(qty: Any, oracle: Any, rate: Any) -> None:
    q, px, r = D(qty) / 100, D(oracle) / 100, D(rate) / 1_000_000
    amounts = []
    for side in ("buy", "sell"):
        with fresh_env() as e:
            e.open_position(side, str(q), px=str(px))
            e.funding.set("SOL", B1, str(r), str(px))
            e.advance(B1)
            amounts.append(_funding_records(e)[0].payload["amount"] if _funding_records(e) else D(0))
    long_amt, short_amt = amounts
    assert long_amt == -(q * px * r)  # long pays when the rate is positive
    assert short_amt == q * px * r
    assert long_amt == -short_amt
