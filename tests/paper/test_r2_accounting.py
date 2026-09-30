# mypy: disable-error-code="union-attr"
"""F11 round 2: partial exits followed by a final close (F11.AC1, AC2, A6 money is exact).

A share keeps a cost basis for the open quantity, so each partial close realises proceeds minus its share of the basis
and the last close takes whatever basis is left: the closes' bases sum to exactly what was paid, however the earlier
ones divided it. The trade P&L (written once, at the final close) is gross P&L minus every fee, entry included.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.paper.helpers import D0, Env, NewEnv, fresh_env

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty

FEE = D("0.00045")
TOL = D("1e-20")  # a 1/3 basis is not exact in any finite decimal; the test's own oracle works to 28 digits


def _exit(e: Env, side: str, qty: str, px: str, n: int, *, final: bool = False) -> list:  # type: ignore[type-arg]
    decided = D0 + 10_000 * n
    e.flat_book("SOL", decided + 1000, px)
    action = ActionKind.CLOSE if final else ActionKind.REDUCE
    result = e.submit(e.order(side, qty, coid=f"x{n}", action=action, decided=decided, px=px))
    assert result.accepted, result
    return e.advance(decided + 1000)


@pytest.mark.unit
def test_R2_AC1_long_two_sold_one_at_110_then_one_at_120_nets_29_8065(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")  # cost 200, fee 0.09
    (first,) = _exit(e, "sell", "1.0", "110", 1)
    assert first.kind == "fill" and first.trade is None
    assert first.fill.fee == D("0.0495")
    assert e.broker.cash_usd() == D("309.8605")  # 300 - 0.09 + (110 - 100) - 0.0495
    view = e.broker.position("SOL")
    assert (view.qty, view.avg_entry_px, view.margin_usd) == (Qty("1.0"), Price("100"), D("20"))
    assert e.trades() == []
    (last,) = _exit(e, "sell", "1.0", "120", 2, final=True)
    assert last.trade.pnl_usd == D("29.8065")  # 10 + 20 gross, less 0.09 + 0.0495 + 0.054
    assert e.broker.cash_usd() == D("329.8065")
    assert [t.pnl_usd for t in e.trades()] == [D("29.8065")]
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_R2_AC1_short_two_bought_back_one_at_90_then_one_at_80_nets_29_8335(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("sell", "2.0", px="100")
    (first,) = _exit(e, "buy", "1.0", "90", 1)
    assert first.trade is None and first.fill.fee == D("0.0405")
    assert e.broker.cash_usd() == D("309.8695")  # 300 - 0.09 + (100 - 90) - 0.0405
    assert e.broker.position("SOL").qty == Qty("-1.0")
    (last,) = _exit(e, "buy", "1.0", "80", 2, final=True)
    assert last.trade.pnl_usd == D("29.8335")
    assert e.broker.cash_usd() == D("329.8335")


@pytest.mark.unit
def test_R2_AC1_a_losing_partial_then_a_winning_close_keeps_each_leg_signed_correctly(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    _exit(e, "sell", "1.0", "90", 1)  # -10 gross, fee 0.0405
    assert e.broker.cash_usd() == D("289.8695")
    (last,) = _exit(e, "sell", "1.0", "130", 2, final=True)  # +30 gross, fee 0.0585
    assert last.trade.pnl_usd == D("19.811")  # 20 gross less 0.09 + 0.0405 + 0.0585 = 0.189
    assert e.broker.cash_usd() == D("319.811")


def _near(actual: D, expected: D) -> bool:
    return abs(actual - expected) < TOL


@pytest.mark.unit
@pytest.mark.parametrize("side", ["buy", "sell"])
def test_R2_AC1_three_partial_closes_of_an_inexact_third_basis_sum_to_exactly_what_was_paid(
    new_env: NewEnv, side: str
) -> None:
    """The entry walks three levels, so its cost is 300.4 (100.1333... a unit): a third of it is not representable.
    The closes must still add up: gross = proceeds - 300.4 (long), or 300.4 - proceeds (short)."""
    e = new_env()
    if side == "buy":
        e.book("SOL", D0 + 1000, [("100", "1000")], [("100", "1"), ("100.1", "1"), ("100.3", "1")])
    else:
        e.book("SOL", D0 + 1000, [("100.3", "1"), ("100.1", "1"), ("100", "1")], [("100.3", "1000")])
    assert e.submit(e.order(side, "3.0", coid="o1")).accepted
    (entry,) = e.advance(D0 + 1000)
    assert entry.fill.price * 3 == D("300.4") or _near(entry.fill.price * 3, D("300.4"))
    closing = "sell" if side == "buy" else "buy"
    prices = ("101", "102", "103") if side == "buy" else ("99", "98", "97")
    sign = 1 if side == "buy" else -1
    cash = D(300) - D("300.4") * FEE
    for n, px in enumerate(prices, start=1):
        _exit(e, closing, "1.0", px, n, final=n == 3)
        if n < 3:  # a partial close realises a third of the basis: 100.1333... a unit
            cash += sign * (D(px) - D("300.4") / 3) - D(px) * FEE
            assert _near(e.broker.cash_usd(), cash)
    proceeds = sum(D(p) for p in prices)
    fees = FEE * (D("300.4") + proceeds)
    gross = proceeds - D("300.4") if side == "buy" else D("300.4") - proceeds
    (trade,) = e.trades()
    assert _near(trade.pnl_usd, gross - fees)
    assert _near(e.broker.cash_usd(), D(300) + gross - fees)
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_R2_AC1_four_partial_closes_with_a_seventh_basis_sum_to_exactly_what_was_paid(new_env: NewEnv) -> None:
    e = new_env()
    e.book("SOL", D0 + 1000, [("100", "1000")], [("100", "3.5"), ("100.13", "3.5")])
    assert e.submit(e.order("buy", "7.0", coid="o1")).accepted
    e.advance(D0 + 1000)
    cost = D("100") * D("3.5") + D("100.13") * D("3.5")
    prices = ("101", "99", "102", "98")
    sizes = ("2.0", "2.0", "2.0", "1.0")
    cash = D(300) - cost * FEE
    for n, (qty, px) in enumerate(zip(sizes, prices, strict=True), start=1):
        _exit(e, "sell", qty, px, n, final=n == 4)
        if n < 4:  # each partial close takes its quantity's share of the 7-unit basis (a seventh a unit)
            cash += D(qty) * (D(px) - cost / 7) - D(qty) * D(px) * FEE
            assert _near(e.broker.cash_usd(), cash)
    proceeds = sum(D(q) * D(p) for q, p in zip(sizes, prices, strict=True))
    (trade,) = e.trades()
    assert _near(trade.pnl_usd, proceeds - cost - FEE * (cost + proceeds))


_TENTHS = st.integers(min_value=1000, max_value=3000)  # prices 100.0 .. 300.0, so 0.1 units are worth >= $10


@pytest.mark.unit
@settings(max_examples=40, deadline=None)
@given(
    side=st.sampled_from(["buy", "sell"]),
    entry_tenths=_TENTHS,
    legs=st.lists(st.tuples(st.integers(min_value=1, max_value=20), _TENTHS), min_size=2, max_size=5),
)
def test_R2_AC1_property_any_partition_of_a_close_realises_exactly_proceeds_minus_cost_minus_fees(
    side: str, entry_tenths: int, legs: list[tuple[int, int]]
) -> None:
    entry_px = D(entry_tenths) / 10
    qty = D(sum(units for units, _ in legs)) / 10
    closing = "sell" if side == "buy" else "buy"
    with fresh_env() as e:
        e.open_position(side, str(qty), px=str(entry_px))
        sign = 1 if side == "buy" else -1
        cash = D(300) - qty * entry_px * FEE
        for n, (units, tenths) in enumerate(legs, start=1):
            leg_qty, leg_px = D(units) / 10, D(tenths) / 10
            _exit(e, closing, str(leg_qty), str(leg_px), n, final=n == len(legs))
            assert len(e.trades()) == (1 if n == len(legs) else 0)  # one trade, at the final close only
            # each leg realises its own quantity's share of the basis (the entry price, at zero spread) at once
            cash += sign * leg_qty * (leg_px - entry_px) - leg_qty * leg_px * FEE
            assert _near(e.broker.cash_usd(), cash)
        cost = qty * entry_px
        proceeds = sum(D(units) / 10 * D(tenths) / 10 for units, tenths in legs)
        gross = proceeds - cost if side == "buy" else cost - proceeds
        expected = gross - FEE * (cost + proceeds)
        (trade,) = e.trades()
        assert _near(trade.pnl_usd, expected)
        assert _near(e.broker.cash_usd(), D(300) + expected)
