# mypy: disable-error-code="union-attr"
"""F11.AC5 under Amendment 9 (PO reading B): a liquidated position closes at the BANKRUPTCY price
entry x (1 -/+ 1/L), so the whole posted margin is lost, plus the taker fee on the liquidation fill. The trigger is
still entry x (1 -/+ (1/L - 1/(2 x maxLeverage))), and a mark that gaps beyond the bankruptcy price does not make the
loss any larger than the margin plus fees (the fill is at the bankruptcy price, not at the mark).
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from tests.paper.helpers import D0, FEE_RATE, NewEnv

from copytrade.core.money import Price, Qty

_CASES = [
    # coin, entry px, qty, side, leverage, trigger (unchanged), bankruptcy price
    ("SOL", "100", "1.0", "buy", 2, "52.5", "50"),
    ("SOL", "100", "1.0", "buy", 4, "77.5", "75"),
    ("SOL", "100", "1.0", "buy", 5, "82.5", "80"),
    ("SOL", "100", "1.0", "buy", 10, "92.5", "90"),
    ("SOL", "100", "1.0", "buy", 20, "97.5", "95"),
    ("SOL", "100", "1.0", "sell", 2, "147.5", "150"),
    ("SOL", "100", "1.0", "sell", 4, "122.5", "125"),
    ("SOL", "100", "1.0", "sell", 5, "117.5", "120"),
    ("SOL", "100", "1.0", "sell", 10, "107.5", "110"),
    ("SOL", "100", "1.0", "sell", 20, "102.5", "105"),
    ("BTC", "1000", "0.1", "buy", 5, "812.5", "800"),  # max leverage 40: maintenance margin 1.25% of notional
    ("BTC", "1000", "0.1", "sell", 40, "1012.5", "1025"),
]
_IDS = [f"{c[0]}-{c[3]}-{c[4]}x" for c in _CASES]


@pytest.mark.unit
@pytest.mark.parametrize(("coin", "entry", "qty", "side", "lev", "trigger", "bankruptcy"), _CASES, ids=_IDS)
def test_R2_AC5_a_liquidation_closes_at_the_bankruptcy_price_and_loses_the_posted_margin_plus_fees(  # noqa: PLR0913
    new_env: NewEnv, coin: str, entry: str, qty: str, side: str, lev: int, trigger: str, bankruptcy: str
) -> None:
    e = new_env()
    e.open_position(side, qty, px=entry, coin=coin, leverage=lev)
    view = e.broker.position(coin)
    margin = view.margin_usd
    assert margin == D(qty) * D(entry) / lev
    assert view.liquidation_px == Price(trigger)
    entry_fee = D(qty) * D(entry) * FEE_RATE
    liquidation_fee = D(qty) * D(bankruptcy) * FEE_RATE
    (ev,) = e.mark(coin, str(view.liquidation_px), D0 + 20_000)
    assert ev.kind == "liquidated"
    assert ev.fill.price == Price(bankruptcy)
    assert ev.fill.qty == Qty(qty) and ev.fill.exit_reason == "liquidated"
    assert ev.fill.side == ("sell" if side == "buy" else "buy")
    assert ev.fill.fee == liquidation_fee  # the taker fee on the liquidation fill, at the bankruptcy notional
    assert ev.trade.pnl_usd == -(margin + entry_fee + liquidation_fee)  # the whole margin, plus both fees
    assert ev.trade.flags == frozenset({"liquidated"})
    assert e.broker.cash_usd() == D(300) - margin - entry_fee - liquidation_fee
    assert e.broker.position(coin) is None
    assert [t.pnl_usd for t in e.trades()] == [ev.trade.pnl_usd]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("side", "mark", "bankruptcy"),
    [
        ("buy", "81", "80"),  # between the trigger 82.5 and the bankruptcy price 80
        ("buy", "80", "80"),  # exactly at it
        ("buy", "50", "80"),  # gapped through it
        ("buy", "0.01", "80"),
        ("sell", "119", "120"),
        ("sell", "120", "120"),
        ("sell", "200", "120"),
        ("sell", "10000", "120"),
    ],
)
def test_R2_AC5_a_mark_that_gaps_through_the_bankruptcy_price_still_closes_at_the_bankruptcy_price(
    new_env: NewEnv, side: str, mark: str, bankruptcy: str
) -> None:
    e = new_env()
    e.open_position(side, "1.0", px="100", leverage=5)
    (ev,) = e.mark("SOL", mark, D0 + 20_000)
    assert ev.kind == "liquidated" and ev.fill.price == Price(bankruptcy)
    expected_loss = D("20.081") if side == "buy" else D("20.099")  # 20 margin + 0.045 entry fee + the closing fee
    assert ev.trade.pnl_usd == -expected_loss
    assert e.broker.cash_usd() == D(300) - expected_loss


@pytest.mark.unit
def test_R2_AC5_a_mark_gapping_through_a_stop_and_the_bankruptcy_price_closes_at_the_bankruptcy_price(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.stop("sl", "sell", "1.0", "99")
    (ev,) = e.mark("SOL", "50", D0 + 20_000)
    assert ev.kind == "liquidated" and ev.fill.price == Price("80")
    e.book("SOL", D0 + 21_000, [("49", "10")], [("49.1", "10")])
    assert e.advance(D0 + 22_000) == []  # the stop does not also fire at the book
    assert len(e.fills()) == 2 and len(e.trades()) == 1


@pytest.mark.unit
def test_R2_AC5_the_trigger_is_unchanged_one_tick_above_it_nothing_happens(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    assert e.mark("SOL", "82.51", D0 + 20_000) == []
    assert e.broker.position("SOL") is not None
    (ev,) = e.mark("SOL", "82.5", D0 + 21_000)
    assert ev.kind == "liquidated" and ev.fill.price == Price("80")


@pytest.mark.unit
def test_R2_AC5_a_merged_short_liquidates_every_share_at_the_bankruptcy_price_of_the_average_entry(
    new_env: NewEnv,
) -> None:
    from copytrade.core.domain import ActionKind  # noqa: PLC0415

    e = new_env()
    e.open_position("sell", "1.0", px="100", coid="o1", share="S1", trade="T1")
    e.open_position(
        "sell", "1.0", px="110", coid="o2", share="S2", trade="T2", decided=D0 + 10_000, action=ActionKind.ADD
    )
    view = e.broker.position("SOL")
    assert view.avg_entry_px == Price("105") and view.margin_usd == D("42")
    assert view.liquidation_px == Price("123.37")  # 105 x 1.175 = 123.375, rounded to the 5-figure grid (ties down)
    events = e.mark("SOL", "123.37", D0 + 20_000)
    assert [ev.kind for ev in events] == ["liquidated", "liquidated"]
    assert {ev.fill.price for ev in events} == {Price("126")}  # 105 x (1 + 1/5)
    pnl = {ev.trade.share_id: ev.trade.pnl_usd for ev in events}
    # gross -26 and -16 (together the 42 margin); fees 0.045 / 0.0495 at entry and 126 x 0.00045 = 0.0567 on each close
    assert pnl == {"S1": D("-26.1017"), "S2": D("-16.1062")}
    assert e.broker.cash_usd() == D(300) - D("42") - D("0.045") - D("0.0495") - 2 * D("0.0567")


@pytest.mark.unit
def test_R2_AC5_the_liquidation_alert_still_fires_once(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.mark("SOL", "82.5", D0 + 20_000)
    assert e.alerts.kinds().count("liquidated") == 1
