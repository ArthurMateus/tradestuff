# mypy: disable-error-code="union-attr"
"""F11 round 2: admission rules and port handling that the first round left open (mutation holes).

An exit or stop must reduce a share of ours in the opposite direction and fit inside it; the liquidation model rejects
leverage above the coin's maximum; a port that answers with a book from before the time it was asked about is ignored;
delisting cancels the coin's stops (and only that coin's).
"""

from __future__ import annotations

import pytest
from tests.paper.helpers import D0, NewEnv, make_book
from tests.paper.r2_helpers import StuckBooks, custom_env

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.paper.liquidation import liquidation_price

# ------------------------------------------------------------------------------------- same-side exits and stops


@pytest.mark.unit
@pytest.mark.parametrize("action", [ActionKind.CLOSE, ActionKind.REDUCE])
@pytest.mark.parametrize(("held", "wrong_side"), [("buy", "buy"), ("sell", "sell")])
def test_R2_AC4_an_exit_on_the_same_side_as_its_share_is_refused(
    new_env: NewEnv, action: ActionKind, held: str, wrong_side: str
) -> None:
    e = new_env()
    e.open_position(held, "2.0", px="100")
    result = e.submit(e.order(wrong_side, "1.0", coid="x1", action=action, decided=D0 + 10_000))
    assert (result.accepted, result.reason) == (False, "exceeds_position")
    e.flat_book("SOL", D0 + 11_000, "100")
    assert e.advance(D0 + 11_000) == []
    assert abs(e.broker.position("SOL").qty) == 2  # exposure did not grow


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["sl", "tp"])
@pytest.mark.parametrize(("held", "wrong_side"), [("buy", "buy"), ("sell", "sell")])
def test_R2_AC7_a_stop_on_the_same_side_as_its_share_is_refused(
    new_env: NewEnv, kind: str, held: str, wrong_side: str
) -> None:
    e = new_env()
    e.open_position(held, "2.0", px="100")
    result = e.stop(kind, wrong_side, "1.0", "95")
    assert (result.accepted, result.reason) == (False, "exceeds_position")
    assert e.broker.cancel_stop("stop1") is False  # nothing was registered


@pytest.mark.unit
@pytest.mark.parametrize(
    ("coin", "px", "qty", "over", "lot_edge", "low", "high"),
    [
        ("SOL", "100", "1.0", "1.01", "1.005", "90", "110"),  # 2 decimals: one lot above the share; rounds down to it
        ("DOGE", "0.1", "100", "101", "100.9", "0.09", "0.11"),  # 0 decimals
        ("BTC", "1000", "0.1", "0.10001", "0.100009", "900", "1100"),  # 5 decimals
    ],
)
def test_R2_AC7_a_stop_one_lot_above_its_share_is_refused_and_one_that_rounds_down_to_it_is_accepted(  # noqa: PLR0913
    new_env: NewEnv, coin: str, px: str, qty: str, over: str, lot_edge: str, low: str, high: str
) -> None:
    e = new_env()
    e.open_position("buy", qty, px=px, coin=coin)
    refused = e.stop("sl", "sell", over, low, coin=coin, coid="too-big")
    assert (refused.accepted, refused.reason) == (False, "exceeds_position")
    exact = e.stop("sl", "sell", qty, low, coin=coin, coid="exact")
    assert (exact.accepted, exact.reason) == (True, None)
    rounded = e.stop("tp", "sell", lot_edge, high, coin=coin, coid="rounded")
    assert (rounded.accepted, rounded.reason) == (True, None)
    stored = {r.client_order_id: r.payload["qty"] for r in e.records("paper_stop")}
    assert stored["rounded"] == stored["exact"]  # the size is stored at the lot, equal to the share


@pytest.mark.unit
def test_R2_AC7_a_stop_on_a_share_that_does_not_exist_or_on_another_coin_is_refused(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    assert e.stop("sl", "sell", "1.0", "95", share="S9", coid="a").reason == "exceeds_position"
    assert e.stop("sl", "sell", "1.0", "95", coin="BTC", coid="b").reason == "exceeds_position"


# ------------------------------------------------------------------------------------------------ liquidation model


@pytest.mark.unit
@pytest.mark.parametrize("max_leverage", [1, 3, 10, 20, 40])
@pytest.mark.parametrize("side", ["long", "short"])
def test_R2_AC5_liquidation_price_rejects_leverage_one_above_the_coin_maximum_and_takes_the_maximum(
    max_leverage: int, side: str
) -> None:
    kwargs = {"side": side, "avg_entry_px": Price("100"), "max_leverage": max_leverage, "sz_decimals": 2}
    liquidation_price(leverage=max_leverage, **kwargs)  # type: ignore[arg-type]  # the maximum itself is fine
    with pytest.raises(ValueError, match="leverage"):
        liquidation_price(leverage=max_leverage + 1, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="leverage"):
        liquidation_price(leverage=0, **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------- a misbehaving book port


@pytest.mark.unit
def test_R2_AC1_a_book_from_before_the_time_asked_about_is_ignored_for_an_entry() -> None:
    early = make_book("SOL", D0 + 500, [("100", "1000")], [("100", "1000")])  # the fill is due at D0 + 1000
    with custom_env(books=StuckBooks(early)) as e:
        assert e.submit(e.order("buy", "1.0")).accepted
        events = e.advance(D0 + 7000)
        assert [(ev.kind, ev.reason) for ev in events] == [("reject", "no_book")]
        assert e.broker.position("SOL") is None and e.fills() == []


@pytest.mark.unit
def test_R2_AC1_a_book_of_another_coin_is_ignored() -> None:
    other = make_book("BTC", D0 + 1000, [("100", "1000")], [("100", "1000")])
    with custom_env(books=StuckBooks(other)) as e:
        assert e.submit(e.order("buy", "1.0")).accepted
        events = e.advance(D0 + 7000)
        assert [(ev.kind, ev.reason) for ev in events] == [("reject", "no_book")]
        assert e.fills() == []


@pytest.mark.unit
def test_R2_AC8_a_book_from_before_the_attempt_never_fills_an_exit() -> None:
    good = make_book("SOL", D0 + 1000, [("100", "1000")], [("100", "1000")])
    books = StuckBooks(good)
    with custom_env(books=books) as e:
        assert e.submit(e.order("buy", "1.0")).accepted
        assert [ev.kind for ev in e.advance(D0 + 1000)] == ["fill"]
        books.book = make_book("SOL", D0 + 15_000, [("100", "1000")], [("100", "1000")])  # older than the attempt
        assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=D0 + 20_000)).accepted
        events = e.advance(D0 + 40_000)
        assert [ev.kind for ev in events] == ["exit_unfilled_alert"]
        assert e.broker.position("SOL") is not None and len(e.fills()) == 1


@pytest.mark.unit
def test_R2_AC8_a_book_of_another_coin_never_fills_an_exit() -> None:
    good = make_book("SOL", D0 + 1000, [("100", "1000")], [("100", "1000")])
    books = StuckBooks(good)
    with custom_env(books=books) as e:
        assert e.submit(e.order("buy", "1.0")).accepted
        assert [ev.kind for ev in e.advance(D0 + 1000)] == ["fill"]
        books.book = make_book("BTC", D0 + 21_000, [("100", "1000")], [("100", "1000")])
        assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=D0 + 20_000)).accepted
        events = e.advance(D0 + 40_000)
        assert [ev.kind for ev in events] == ["exit_unfilled_alert"]
        assert e.broker.position("SOL") is not None and len(e.fills()) == 1


# ------------------------------------------------------------------------------------------------ delisting stops


@pytest.mark.unit
def test_R2_AC6_delisting_cancels_the_coins_stops_with_the_reason_delisted_and_leaves_other_coins_alone(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.open_position("buy", "0.1", px="1000", coin="BTC", coid="o2", share="S2", trade="T2", decided=D0 + 1000)
    assert e.stop("sl", "sell", "2.0", "90", coid="sol-sl").accepted
    assert e.stop("tp", "sell", "2.0", "120", coid="sol-tp").accepted
    assert e.stop("sl", "sell", "0.1", "900", coin="BTC", coid="btc-sl", share="S2", trade="T2").accepted
    e.broker.on_delist("SOL", Price("90"), D0 + 20_000)
    cancels = {r.payload["client_order_id"]: r.payload for r in e.records("paper_cancel")}
    assert {c: cancels[c]["reason"] for c in ("sol-sl", "sol-tp")} == {"sol-sl": "delisted", "sol-tp": "delisted"}
    assert all(cancels[c]["target"] == "stop" for c in ("sol-sl", "sol-tp"))
    assert "btc-sl" not in cancels
    assert e.broker.cancel_stop("sol-sl") is False and e.broker.cancel_stop("sol-tp") is False
    assert e.broker.cancel_stop("btc-sl") is True
