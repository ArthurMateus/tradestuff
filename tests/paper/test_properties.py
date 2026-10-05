# mypy: disable-error-code="union-attr"
"""Property tests over money maths (F11.AC1, AC2, AC3, AC5; A6): cash conservation and exact round-trip costs."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from typing import Any
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.domain import ActionKind
from copytrade.ledger.export import aggregate_trades
from tests.paper.helpers import D0, FEE_RATE, fresh_env

_trade = st.tuples(
    st.sampled_from(["buy", "sell"]),  # entry side: buy = long, sell = short
    st.integers(min_value=100, max_value=2000),  # qty in 0.01 units (1.00 .. 20.00)
    st.integers(min_value=5000, max_value=20000),  # entry px in 0.01 (50.00 .. 200.00)
    st.integers(min_value=5000, max_value=20000),  # exit px in 0.01
)


@pytest.mark.unit
@settings(max_examples=25)
@given(trades=st.lists(_trade, min_size=1, max_size=4))
def test_F11_property_cash_equals_wallet_plus_sum_of_trade_pnl_and_each_trade_pnl_is_exact(trades: Any) -> None:
    with fresh_env() as e:
        expected_total = D(0)
        for i, (side, q100, p_in, p_out) in enumerate(trades):
            q, entry, exit_px = D(q100) / 100, D(p_in) / 100, D(p_out) / 100
            t0 = D0 + i * 20_000
            e.open_position(side, str(q), px=str(entry), decided=t0, coid=f"o{i}", share=f"S{i}", trade=f"T{i}")
            e.flat_book("SOL", t0 + 11_000, str(exit_px))
            close_side = "sell" if side == "buy" else "buy"
            e.submit(e.order(close_side, str(q), coid=f"c{i}", action=ActionKind.CLOSE, decided=t0 + 10_000,
                             px=str(exit_px), share=f"S{i}", trade=f"T{i}"))
            e.advance(t0 + 11_000)
            direction = 1 if side == "buy" else -1
            expected = direction * (exit_px - entry) * q - q * entry * FEE_RATE - q * exit_px * FEE_RATE
            trade = e.trades()[i]
            assert trade.pnl_usd == expected  # hand formula: gross - both taker fees, exact
            expected_total += expected
        assert e.broker.cash_usd() == 300 + expected_total
        agg = aggregate_trades(e.ledger_dir)
        assert agg.trade_count == len(trades) and agg.total_pnl_usd == expected_total
        assert e.broker.position("SOL") is None


@pytest.mark.unit
@settings(max_examples=20)
@given(q100=st.integers(min_value=100, max_value=2000), px100=st.integers(min_value=5000, max_value=20000),
       side=st.sampled_from(["buy", "sell"]))
def test_F11_property_a_flat_round_trip_costs_exactly_two_taker_fees(q100: Any, px100: Any, side: Any) -> None:
    q, px = D(q100) / 100, D(px100) / 100
    with fresh_env() as e:
        e.open_position(side, str(q), px=str(px))
        e.flat_book("SOL", D0 + 11_000, str(px))
        e.submit(e.order("sell" if side == "buy" else "buy", str(q), coid="c", action=ActionKind.CLOSE,
                         decided=D0 + 10_000, px=str(px)))
        e.advance(D0 + 11_000)
        assert e.trades()[0].pnl_usd == -2 * q * px * FEE_RATE
