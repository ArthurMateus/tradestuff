# mypy: disable-error-code="union-attr"
"""F11.AC5: liquidation (A8). Maintenance margin = half the initial margin at the asset's max leverage, so the
liquidation price is entry x (1 -/+ (1/L - 1/(2 x maxLeverage))). A position whose mark reaches it is closed at the
BANKRUPTCY price entry x (1 -/+ 1/L) (Amendment 9, PO reading B: the whole posted margin is lost, plus the taker fee),
is flagged ``liquidated`` and alerted; a mark that gaps through both the stop and the liquidation price gives
``liquidated``. F10.AC4 and AC10 reuse ``liquidation_price`` (single model)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from typing import Any
from tests.paper.helpers import NewEnv
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.paper.liquidation import liquidation_price
from tests.paper.helpers import D0, FEE_RATE, fresh_env


@pytest.mark.unit
@pytest.mark.parametrize(
    "side,entry,lev,maxlev,sz,expected",
    [
        ("long", "100", 9, 20, 2, "91.389"),  # 100 x (1 - 1/9 + 1/40) = 91.3888.. -> 5 s.f.
        ("long", "100", 5, 20, 2, "82.5"),  # 100 x (1 - 0.2 + 0.025)
        ("short", "100", 5, 20, 2, "117.5"),  # 100 x (1 + 0.2 - 0.025)
        ("long", "100", 1, 20, 2, "2.5"),  # 100 x (1 - 1 + 0.025)
        ("long", "105", 5, 20, 2, "86.625"),  # merged avg entry 105
        ("long", "1000", 5, 40, 5, "812.5"),  # 1000 x (1 - 0.2 + 0.0125)
    ],
)
def test_F11_AC5_liquidation_price_vectors(
    side: Any, entry: Any, lev: Any, maxlev: Any, sz: Any, expected: Any
) -> None:
    got = liquidation_price(side=side, avg_entry_px=Price(entry), leverage=lev, max_leverage=maxlev, sz_decimals=sz)
    assert got == Price(expected)
    assert isinstance(got, Price)


@pytest.mark.unit
@settings(max_examples=200)
@given(
    entry=st.integers(min_value=1000, max_value=9_999_900),
    maxlev=st.integers(min_value=3, max_value=50),
    data=st.data(),
)
def test_F11_AC5_property_liquidation_price_model(entry: Any, maxlev: Any, data: Any) -> None:
    lev = data.draw(st.integers(min_value=1, max_value=maxlev))
    px = D(entry) / 100
    kw = {"avg_entry_px": Price(px), "max_leverage": maxlev, "sz_decimals": 2}
    long_px = liquidation_price(side="long", leverage=lev, **kw)
    short_px = liquidation_price(side="short", leverage=lev, **kw)
    assert 0 < long_px < px < short_px
    dist = D(1) / lev - D(1) / (2 * maxlev)
    assert abs(long_px - px * (1 - dist)) <= px * D("0.0001")  # rounding to the exchange price grid only
    assert abs(short_px - px * (1 + dist)) <= px * D("0.0001")
    if lev < maxlev:  # more leverage moves liquidation closer to entry (never further)
        higher_long = liquidation_price(side="long", leverage=lev + 1, **kw)
        higher_short = liquidation_price(side="short", leverage=lev + 1, **kw)
        assert higher_long >= long_px and higher_short <= short_px


@pytest.mark.unit
def test_F11_AC5_position_view_reports_margin_and_liquidation_price(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", leverage=5)
    pos = e.broker.position("SOL")
    assert pos.margin_usd == D("20")  # 100 / 5
    assert pos.liquidation_px == Price("82.5")
    assert pos.leverage == 5 and pos.share_ids == ("S1",)


@pytest.mark.unit
def test_F11_AC5_no_liquidation_while_the_mark_is_above_the_liquidation_price(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    assert e.mark("SOL", "82.51", D0 + 20_000) == []
    assert e.broker.position("SOL") is not None
    assert "liquidated" not in e.alerts.kinds()


@pytest.mark.unit
def test_F11_AC5_long_liquidated_when_the_mark_reaches_the_liquidation_price(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    (ev,) = e.mark("SOL", "82.5", D0 + 20_000)
    assert ev.kind == "liquidated" and ev.trade is not None
    fill = ev.fill
    assert fill.price == Price("80") and fill.qty == Qty("1.0") and fill.side == "sell"  # bankruptcy: 100 x (1 - 1/5)
    assert fill.exit_reason == "liquidated"
    assert fill.fee == D("0.036")  # 80 x 4.5 bps: liquidation pays the taker fee too
    assert fill.time == Timestamp(D0 + 20_000, TimeSource.EXCHANGE)
    assert ev.trade.pnl_usd == D("-20.081")  # the whole 20 margin, - 0.045 entry fee - 0.036
    assert ev.trade.flags == frozenset({"liquidated"})
    assert e.broker.position("SOL") is None
    assert e.broker.cash_usd() == D("279.919")  # margin lost: 300 - 20.081
    assert e.alerts.kinds().count("liquidated") == 1
    assert e.trades() == [ev.trade]


@pytest.mark.unit
def test_F11_AC5_short_liquidated_at_the_upper_price(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("sell", "1.0", px="100")
    assert e.mark("SOL", "117.49", D0 + 20_000) == []
    (ev,) = e.mark("SOL", "117.5", D0 + 21_000)
    assert ev.kind == "liquidated" and ev.fill.side == "buy" and ev.fill.price == Price("120")  # 100 x (1 + 1/5)
    assert ev.trade.pnl_usd == D("-20.099")  # the whole 20 margin, - 0.045 - 120 x 0.00045


@pytest.mark.unit
def test_F11_AC5_a_mark_that_gaps_through_both_the_stop_and_the_liquidation_price_is_liquidated(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.stop("sl", "sell", "1.0", "99")
    (ev,) = e.mark("SOL", "80", D0 + 20_000)  # 80 is below the stop (99) and the liquidation price (82.5)
    assert ev.kind == "liquidated" and ev.fill.exit_reason == "liquidated" and ev.fill.price == Price("80")
    e.book("SOL", D0 + 21_000, [("79", "10")], [("79.1", "10")])
    assert e.advance(D0 + 22_000) == []  # the stop does not also fire
    assert len(e.fills()) == 2 and len(e.trades()) == 1
    assert e.trades()[0].flags == frozenset({"liquidated"})


@pytest.mark.unit
def test_F11_AC5_a_stop_hit_above_the_liquidation_price_is_a_normal_stop_not_a_liquidation(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.stop("sl", "sell", "1.0", "99")
    assert e.mark("SOL", "90", D0 + 20_000) == []  # 90 > 82.5
    e.book("SOL", D0 + 21_000, [("89", "10")], [("89.1", "10")])
    (ev,) = e.advance(D0 + 21_000)
    assert ev.kind == "fill" and ev.fill.exit_reason == "stop_loss"
    assert ev.trade.flags == frozenset()
    assert "liquidated" not in e.alerts.kinds()


@pytest.mark.unit
def test_F11_AC5_merged_position_uses_the_average_entry_and_liquidates_every_share(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", coid="o1", share="S1", trade="T1")
    e.open_position(
        "buy", "1.0", px="110", coid="o2", share="S2", trade="T2", decided=D0 + 10_000, action=ActionKind.ADD
    )
    pos = e.broker.position("SOL")
    assert pos.qty == Qty("2.0") and pos.avg_entry_px == Price("105")
    assert pos.margin_usd == D("42")  # 2 x 105 / 5
    assert pos.liquidation_px == Price("86.625")  # 105 x 0.825
    assert e.mark("SOL", "86.63", D0 + 20_000) == []
    events = e.mark("SOL", "86.625", D0 + 21_000)
    assert [ev.kind for ev in events] == ["liquidated", "liquidated"]
    pnl = {ev.trade.share_id: ev.trade.pnl_usd for ev in events}
    # closed at the bankruptcy price 105 x (1 - 1/5) = 84: gross -16 and -26 (together the 42 margin), fees 0.045 /
    # 0.0495 at entry and 84 x 0.00045 = 0.0378 on each liquidation fill
    assert pnl == {"S1": D("-16.0828"), "S2": D("-26.0873")}
    assert {ev.fill.price for ev in events} == {Price("84")}
    for ev in events:
        assert ev.trade.flags == frozenset({"liquidated"})
    assert e.broker.position("SOL") is None
    assert e.alerts.kinds().count("liquidated") >= 1


@pytest.mark.unit
def test_F11_AC5_liquidating_one_coin_leaves_the_others_alone(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", coid="o1")
    e.open_position("buy", "0.1", px="1000", coin="BTC", coid="o2", share="S2", trade="T2", decided=D0 + 10_000)
    e.mark("SOL", "82.5", D0 + 20_000)
    assert e.broker.position("SOL") is None
    assert e.broker.position("BTC") is not None
    assert e.mark("SOL", "50", D0 + 21_000) == []  # nothing left to liquidate on SOL


@pytest.mark.unit
@settings(max_examples=40)
@given(
    lev=st.sampled_from([2, 4, 5, 10, 20]),  # 1/L terminates, so the bankruptcy price is exact on the grid
    tenths=st.integers(min_value=1, max_value=50),
    entry=st.sampled_from([100, 150, 200, 250, 300]),
    side=st.sampled_from(["buy", "sell"]),
)
def test_F11_AC5_property_an_isolated_liquidation_loses_exactly_the_posted_margin_plus_fees(
    lev: Any, tenths: Any, entry: Any, side: Any
) -> None:
    q, px = D(tenths) / 10, D(entry)
    with fresh_env() as e:
        e.open_position(side, str(q), px=str(px), leverage=lev)
        pos = e.broker.position("SOL")
        (ev,) = e.mark("SOL", str(pos.liquidation_px), D0 + 20_000)  # the trigger price itself is unchanged
        assert ev.kind == "liquidated"
        bankruptcy = px * (1 - D(1) / lev) if side == "buy" else px * (1 + D(1) / lev)
        assert ev.fill.price == bankruptcy
        assert ev.fill.fee == ev.fill.qty * ev.fill.price * FEE_RATE
        assert ev.trade.pnl_usd == -(pos.margin_usd + q * px * FEE_RATE + ev.fill.fee)
