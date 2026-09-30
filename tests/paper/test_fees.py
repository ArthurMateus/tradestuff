# mypy: disable-error-code="union-attr"
"""F11.AC2: every fill pays cost.taker_fee_bps of its notional, including stop-loss, take-profit and liquidation
fills (and force-settlement, pinned as a fill). No maker fills, no rebates."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from typing import Any
from tests.paper.helpers import NewEnv
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.domain import ActionKind
from copytrade.core.money import Fee, Price
from tests.paper.helpers import D0, FEE_RATE, fresh_env, make_config


@pytest.mark.unit
def test_F11_AC2_entry_and_manual_close_each_pay_4_5_bps_and_the_trade_nets_them(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    entry = e.fills()[0]
    assert entry.fee == Fee("0.045")  # 1.0 x 100 x 0.00045
    e.flat_book("SOL", D0 + 61_000, "110")
    e.submit(e.order("sell", "1.0", coid="close1", action=ActionKind.CLOSE, decided=D0 + 60_000, px="110"))
    e.advance(D0 + 61_000)
    exit_fill = e.fills()[1]
    assert exit_fill.fee == Fee("0.0495")  # 1.0 x 110 x 0.00045
    (trade,) = e.trades()
    assert trade.pnl_usd == D("9.9055")  # +10 gross - 0.045 - 0.0495
    assert e.broker.cash_usd() == D("309.9055")


@pytest.mark.unit
def test_F11_AC2_fee_rate_is_data_driven(new_env: NewEnv) -> None:
    e = new_env(config=make_config(cost__taker_fee_bps=D("6")))
    e.open_position("buy", "1.0", px="100")
    assert e.fills()[0].fee == Fee("0.06")  # 100 x 6 bps


@pytest.mark.unit
def test_F11_AC2_the_maker_fee_key_is_ignored_no_maker_fills_or_rebates(new_env: NewEnv) -> None:
    e = new_env(config=make_config(cost__maker_fee_bps=D("20")))
    e.open_position("buy", "1.0", px="100")
    assert e.fills()[0].fee == Fee("0.045")


@pytest.mark.unit
def test_F11_AC2_every_fill_kind_pays_the_taker_fee_stop_tp_liquidation_delist(new_env: NewEnv) -> None:
    e = new_env()
    # SOL long, stop-loss
    e.open_position("buy", "1.0", px="100", coin="SOL", coid="o1", share="S1", trade="T1")
    e.stop("sl", "sell", "1.0", "99", coid="sl1")
    e.mark("SOL", "98", D0 + 20_000)
    e.book("SOL", D0 + 21_000, [("97", "10")], [("97.1", "10")])
    e.advance(D0 + 21_000)
    # ETH short, take-profit
    e.open_position("sell", "0.1", px="2000", coin="ETH", coid="o2", share="S2", trade="T2", decided=D0 + 30_000)
    e.stop("tp", "buy", "0.1", "1800", coid="tp1", coin="ETH", share="S2", trade="T2")
    e.mark("ETH", "1799", D0 + 40_000)
    e.book("ETH", D0 + 41_000, [("1800", "5")], [("1800", "5")])
    e.advance(D0 + 41_000)
    # BTC long, liquidated (L=5, max 40: liq = 1000 x (1 - 0.2 + 0.0125) = 812.5)
    e.open_position("buy", "0.1", px="1000", coin="BTC", coid="o3", share="S3", trade="T3", decided=D0 + 50_000)
    e.mark("BTC", "812.5", D0 + 60_000)
    # DOGE long, delisted
    e.open_position("buy", "100", px="0.1", coin="DOGE", coid="o4", share="S4", trade="T4", decided=D0 + 70_000)
    e.broker.on_delist("DOGE", Price("0.09"), D0 + 80_000)
    fills = e.fills()
    reasons = sorted(f.exit_reason for f in fills if f.exit_reason)
    assert reasons == ["delisted_force_settle", "liquidated", "stop_loss", "take_profit"]
    assert len(fills) == 8
    for f in fills:
        assert f.fee == f.qty * f.price * FEE_RATE  # exact, every fill, no exceptions
        assert f.fee > 0


@pytest.mark.unit
@settings(max_examples=25)
@given(
    qty=st.integers(min_value=10, max_value=5000),
    px=st.integers(min_value=1000, max_value=99999),
    bps=st.integers(min_value=45, max_value=200),
    side=st.sampled_from(["buy", "sell"]),
)
def test_F11_AC2_property_fee_is_exactly_notional_times_bps_and_never_negative(qty: Any, px: Any, bps: Any, side: Any) -> None:
    q, price, rate = D(qty) / 100, D(px) / 100, D(bps) / 10
    if q * price < 10:
        return
    with fresh_env(config=make_config(cost__taker_fee_bps=rate)) as e:
        e.open_position(side, str(q), px=str(price))
        (fill,) = e.fills()
        assert fill.fee == q * price * rate / 10000
        assert fill.fee >= 0
