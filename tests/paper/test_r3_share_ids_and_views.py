# mypy: disable-error-code="union-attr"
"""F11 round 3: RISK-13 (a share id is only unique within its coin) and RISK-15 (an unrepresentable liquidation
view must not break queries or the liquidation trigger), plus the pinned leverage-1 bankruptcy at price 0.

RISK-13: closing SOL share ``S1`` (by a fill, a liquidation or a delisting) must not cancel or drop the stop or the
pending exit of ETH share ``S1``. A share is identified by ``(share_id, coin)``.

RISK-15 (defined here): when the merged average entry makes the liquidation price fall off the exchange grid (1x long
on a coin with tick 0.1: shares at 10 and 7, the share at 10 closed, liquidation price 7 / 80 = 0.0875 < 0.1),
``position()`` still returns the view (qty, average entry, margin, share ids; the liquidation price is a representable
fallback, finite and positive), ``on_mark`` never raises, and the position still liquidates on a mark that reaches its
liquidation price, still triggers stops and still closes.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from tests.paper.helpers import DEFAULT_META, D0, Env, FakeMeta, NewEnv

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.paper.types import CoinMeta

T = D0 + 10_000


# ------------------------------------------------------------------------------------------------- RISK-13


def _two_coins_same_share_id(e: Env) -> None:
    e.open_position("buy", "1.0", px="100", coin="SOL", coid="o-sol", share="S1", trade="T1", leverage=5)
    e.open_position("buy", "1.0", px="2000", coin="ETH", coid="o-eth", share="S1", trade="T2", leverage=5,
                    decided=D0 + 2000)
    e.advance(T)


def _close_sol_s1(e: Env, how: str) -> None:
    """Close SOL share S1 at broker time T + 1000 (the SOL and ETH positions are both still 1.0 before)."""
    if how == "close_fill":
        e.flat_book("SOL", T + 1000, "100")
        assert e.submit(e.order("sell", "1.0", coid="sol-x", coin="SOL", action=ActionKind.CLOSE, decided=T,
                                share="S1", trade="T1")).accepted
        (event,) = e.advance(T + 1000)
        assert event.kind == "fill" and event.coin == "SOL"
    elif how == "liquidation":
        (event,) = e.mark("SOL", "80", T + 1000)  # 5x long at 100: trigger 82.5
        assert event.kind == "liquidated" and event.coin == "SOL"
    else:
        (event,) = e.broker.on_delist("SOL", Price("90"), T + 1000)
        assert event.kind == "delisted_force_settle" and event.coin == "SOL"
    assert e.broker.position("SOL") is None
    assert e.broker.position("ETH").qty == D("1.0")


HOWS = ["close_fill", "liquidation", "delisting"]


@pytest.mark.unit
@pytest.mark.parametrize("how", HOWS)
def test_R3_RISK13_closing_sol_s1_does_not_drop_the_stop_of_eth_s1(new_env: NewEnv, how: str) -> None:
    e = new_env()
    _two_coins_same_share_id(e)
    assert e.stop("sl", "sell", "1.0", "1800", coid="eth-sl", coin="ETH", share="S1", trade="T2").accepted
    _close_sol_s1(e, how)
    assert not any(r.payload.get("client_order_id") == "eth-sl" for r in e.records("paper_cancel"))
    e.flat_book("ETH", T + 3000, "1690")
    assert e.mark("ETH", "1700", T + 2000) == []  # the ETH stop triggers at its level (liquidation is at 1640)
    (event,) = e.advance(T + 3000)
    assert event.kind == "fill" and event.coin == "ETH" and event.client_order_id == "eth-sl"
    assert event.fill.exit_reason == "stop_loss" and event.fill.price == Price("1690")
    assert e.broker.position("ETH") is None


@pytest.mark.unit
@pytest.mark.parametrize("how", HOWS)
def test_R3_RISK13_closing_sol_s1_does_not_cancel_the_pending_exit_of_eth_s1(new_env: NewEnv, how: str) -> None:
    e = new_env()
    _two_coins_same_share_id(e)
    # an ETH close waiting for its book (the first ETH snapshot is at T + 3000, inside the book-age window)
    assert e.submit(e.order("sell", "1.0", coid="eth-x", coin="ETH", action=ActionKind.CLOSE, decided=T, share="S1",
                            trade="T2", px="2000")).accepted
    e.flat_book("ETH", T + 3000, "2010")
    _close_sol_s1(e, how)
    assert not any(r.payload.get("client_order_id") == "eth-x" for r in e.records("paper_cancel"))
    (event,) = e.advance(T + 3000)
    assert event.kind == "fill" and event.coin == "ETH" and event.client_order_id == "eth-x"
    assert event.fill.price == Price("2010") and event.fill.time.ms == T + 3000
    assert e.broker.position("ETH") is None


@pytest.mark.unit
def test_R3_RISK13_closing_a_share_still_retires_its_own_stops_and_exits(new_env: NewEnv) -> None:
    """Control: the same coin's stop and pending exit of the closed share are still retired."""
    e = new_env()
    _two_coins_same_share_id(e)
    assert e.stop("sl", "sell", "1.0", "90", coid="sol-sl", coin="SOL", share="S1", trade="T1").accepted
    _close_sol_s1(e, "liquidation")
    cancelled = {r.payload["client_order_id"] for r in e.records("paper_cancel")}
    assert "sol-sl" in cancelled


# ------------------------------------------------------------------------------------------------- RISK-15

XX_META = FakeMeta({**DEFAULT_META, "XX": CoinMeta(sz_decimals=5, max_leverage=40)})  # tick 0.1, max leverage 40


def _unrepresentable(e: Env) -> None:
    """1x long on XX: share A at 10 and share B at 7 (merged avg 8.5, liquidation 0.1), then A closes: B alone has
    a liquidation price of 7 / 80 = 0.0875, below the smallest tick."""
    e.open_position("buy", "2", px="10", coin="XX", coid="a", share="A", trade="T1", leverage=1)
    e.open_position("buy", "2", px="7", coin="XX", coid="b", share="B", trade="T2", leverage=1, decided=D0 + 2000)
    e.advance(T)
    assert e.broker.position("XX").avg_entry_px == D("8.5")
    e.flat_book("XX", T + 1000, "10")
    assert e.submit(e.order("sell", "2", coid="ca", coin="XX", action=ActionKind.CLOSE, decided=T, share="A",
                            trade="T1", px="10")).accepted
    (event,) = e.advance(T + 1000)
    assert event.kind == "fill" and event.client_order_id == "ca"


@pytest.mark.unit
def test_R3_RISK15_position_stays_queryable_when_the_liquidation_price_is_off_the_grid(new_env: NewEnv) -> None:
    e = new_env(meta=FakeMeta(dict(XX_META.meta)))
    _unrepresentable(e)
    view = e.broker.position("XX")  # must not raise ValueError
    assert view is not None
    assert view.qty == D("2") and view.avg_entry_px == D("7") and view.margin_usd == D("14")
    assert view.share_ids == ("B",) and view.leverage == 1
    assert view.liquidation_px.is_finite() and 0 < view.liquidation_px < view.avg_entry_px  # a fallback, long side
    assert e.broker.cash_usd() > 0  # and the rest of the broker is unharmed


@pytest.mark.unit
def test_R3_RISK15_the_liquidation_trigger_still_fires_when_the_view_is_off_the_grid(new_env: NewEnv) -> None:
    e = new_env(meta=FakeMeta(dict(XX_META.meta)))
    _unrepresentable(e)
    assert e.mark("XX", "0.5", T + 2000) == []  # far above the liquidation price 0.0875: nothing
    assert e.broker.position("XX") is not None
    (event,) = e.mark("XX", "0.01", T + 3000)  # below it: liquidated (must not raise, must not be swallowed)
    assert event.kind == "liquidated" and event.coin == "XX" and event.client_order_id == "liquidated:B"
    assert event.fill.price == Price("0") and event.trade.flags == frozenset({"liquidated"})  # bankruptcy: 7 x (1 - 1)
    assert event.trade.pnl_usd == D("-14.0063")  # the whole margin 14 and the entry fee 0.0063
    assert e.broker.position("XX") is None


@pytest.mark.unit
def test_R3_RISK15_a_stop_still_triggers_and_a_close_still_fills_when_the_view_is_off_the_grid(
    new_env: NewEnv,
) -> None:
    e = new_env(meta=FakeMeta(dict(XX_META.meta)))
    _unrepresentable(e)
    assert e.stop("sl", "sell", "2", "5", coid="xx-sl", coin="XX", share="B", trade="T2").accepted
    e.flat_book("XX", T + 3500, "4.8")
    assert e.mark("XX", "4.9", T + 2500) == []
    (event,) = e.advance(T + 3500)
    assert event.kind == "fill" and event.fill.exit_reason == "stop_loss" and event.fill.price == Price("4.8")
    assert e.broker.position("XX") is None


@pytest.mark.unit
def test_R3_RISK15_a_close_still_fills_when_the_view_is_off_the_grid(new_env: NewEnv) -> None:
    e = new_env(meta=FakeMeta(dict(XX_META.meta)))
    _unrepresentable(e)
    e.flat_book("XX", T + 3000, "8")
    assert e.submit(e.order("sell", "2", coid="cb", coin="XX", action=ActionKind.CLOSE, decided=T + 2000, share="B",
                            trade="T2", px="8")).accepted
    (event,) = e.advance(T + 3000)
    assert event.kind == "fill" and event.fill.price == Price("8")
    assert e.broker.position("XX") is None


@pytest.mark.unit
def test_R3_RISK15_the_fallback_view_keeps_the_positions_leverage_and_it_still_liquidates_at_its_bankruptcy_price(
    new_env: NewEnv,
) -> None:
    """2x on a 0.15 coin: after the 0.4 share closes, 0.15 x (1 - (1/2 - 1/80)) = 0.0769 is below the tick 0.1."""
    e = new_env(meta=FakeMeta(dict(XX_META.meta)))
    e.open_position("buy", "100", px="0.4", coin="XX", coid="a", share="A", trade="T1", leverage=2)
    e.open_position("buy", "100", px="0.15", coin="XX", coid="b", share="B", trade="T2", leverage=2, decided=D0 + 2000)
    e.advance(T)
    assert e.broker.position("XX").avg_entry_px == D("0.275")  # representable while both shares are open
    e.flat_book("XX", T + 1000, "0.4")
    assert e.submit(e.order("sell", "100", coid="ca", coin="XX", action=ActionKind.CLOSE, decided=T, share="A",
                            trade="T1", px="0.4")).accepted
    e.advance(T + 1000)
    view = e.broker.position("XX")
    assert view.leverage == 2 and view.qty == D("100") and view.avg_entry_px == D("0.15")
    assert view.margin_usd == D("7.5") and view.share_ids == ("B",)
    assert 0 < view.liquidation_px < D("0.15")
    assert e.mark("XX", "0.1", T + 2000) == []  # above the unrounded trigger 0.0769
    (event,) = e.mark("XX", "0.05", T + 3000)
    assert event.kind == "liquidated" and event.fill.price == Price("0.075")  # 0.15 x (1 - 1/2)
    assert event.trade.pnl_usd == D("-7.510125")  # margin 7.5 + entry fee 0.00675 + liquidation fee 0.003375


# ------------------------------------------------------------------- bankruptcy price 0 (leverage 1 long)


@pytest.mark.unit
def test_R3_pin_a_1x_long_liquidates_at_the_bankruptcy_price_zero_and_loses_the_whole_margin_plus_the_fee(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", leverage=1)
    e.advance(T)
    assert e.broker.position("SOL").liquidation_px == D("2.5")  # 100 x (1 - (1 - 1/40))
    assert e.mark("SOL", "2.6", T + 1000) == []
    (event,) = e.mark("SOL", "2.5", T + 2000)
    assert event.kind == "liquidated"
    assert event.fill.price == Price("0") and event.fill.fee == D("0")  # no crash at price 0
    assert event.trade.pnl_usd == D("-100.045")  # margin 100 + entry fee 0.045 + fee on the fill at 0
    assert e.broker.cash_usd() == D("199.955")
    assert e.broker.position("SOL") is None
