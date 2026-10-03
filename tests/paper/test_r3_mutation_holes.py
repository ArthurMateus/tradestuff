# mypy: disable-error-code="union-attr"
"""F11 round 3: the mutation holes senior-dev found in round 2. These pass on the current code and pin behaviour:

(a) ``on_delist`` refuses a settlement price that is not a positive finite price, changes nothing and does not latch;
(b) the funding-rate cap is 0.04 per hour, both signs, inclusive;
(c) an entry fill whose merged liquidation price is unrepresentable is rejected ``liquidation_unrepresentable``;
(d) an ADD refreshes the position's stored ``max_leverage`` and ``sz_decimals``, and the check uses the position's
    leverage, not the order's;
(e) a stop with a used client order id is refused ``duplicate_client_order_id``.
"""

from __future__ import annotations

from decimal import Decimal as D
from typing import cast

import pytest
from tests.paper.helpers import BASE, D0, DEFAULT_META, HOUR_MS, Env, FakeMeta, NewEnv

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.paper.types import CoinMeta

T = D0 + 10_000
MIN = 60_000
B1 = BASE + HOUR_MS


# ------------------------------------------------------------------------------------- (a) on_delist price


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    ["0", "NaN", "Infinity", "-Infinity", "-1", "sNaN"],
    ids=["zero", "nan", "inf", "minus_inf", "negative", "signalling_nan"],
)
def test_R3_hole_a_on_delist_refuses_a_settlement_price_that_is_not_a_positive_finite_price(
    new_env: NewEnv, bad: str
) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    before = (e.broker.cash_usd(), len(e.records()), e.broker.position("SOL"), list(e.alerts.sent))
    with pytest.raises(ValueError, match="settlement_px"):
        e.broker.on_delist("SOL", cast("Price", D(bad)) if bad != "0" else Price("0"), T + 1000)
    assert (e.broker.cash_usd(), len(e.records()), e.broker.position("SOL"), list(e.alerts.sent)) == before
    # not latched: the caller passed bad data, the books are fine
    e.flat_book("BTC", T + 1000, "60000")
    assert e.submit(e.order("buy", "0.001", coid="btc1", coin="BTC", decided=T, px="60000", share="S9",
                            trade="T9")).accepted
    settled = [ev for ev in e.broker.on_delist("SOL", Price("90"), T + 1000) if ev.kind == "delisted_force_settle"]
    assert len(settled) == 1 and settled[0].fill.price == Price("90")
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_R3_hole_a_the_smallest_positive_settlement_price_is_accepted(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    (event,) = e.broker.on_delist("SOL", Price("0.0001"), T + 1000)
    assert event.kind == "delisted_force_settle" and event.fill.price == Price("0.0001")


# ------------------------------------------------------------------------------------ (b) funding-rate cap


def _funding_run(e: Env, rate: str) -> None:
    e.open_position("buy", "2.0", px="100")  # cash 299.91
    e.funding.set("SOL", B1, rate, "100")
    e.advance(B1 + 1000)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("rate", "cash"),
    [
        ("0.04", "291.91"),
        ("-0.04", "307.91"),
        ("0.03", "293.91"),
        ("0.0299", "293.93"),
        ("-0.0299", "305.89"),
        ("0", "299.91"),
    ],
)
def test_R3_hole_b_a_funding_rate_up_to_the_cap_is_accepted(new_env: NewEnv, rate: str, cash: str) -> None:
    e = new_env()
    _funding_run(e, rate)
    assert [r.payload["hour_ms"] for r in e.records("paper_funding")] == [B1]
    assert e.broker.cash_usd() == D(cash)
    assert "funding_missing" not in e.alerts.kinds()


@pytest.mark.unit
@pytest.mark.parametrize("rate", ["0.0401", "-0.0401", "0.05", "-0.05", "1"])
def test_R3_hole_b_a_funding_rate_beyond_the_cap_is_not_a_rate_alerted_and_retried(
    new_env: NewEnv, rate: str
) -> None:
    e = new_env()
    _funding_run(e, rate)
    e.advance(B1 + 2000)
    assert e.records("paper_funding") == []
    assert e.broker.cash_usd() == D("299.91")
    assert e.alerts.kinds().count("funding_missing") == 1
    e.funding.set("SOL", B1, "0.0001", "100")  # the real rate arrives: settled late
    e.advance(B1 + 3000)
    assert [r.payload["hour_ms"] for r in e.records("paper_funding")] == [B1]
    assert e.broker.cash_usd() == D("299.89")


# ------------------------------------------------------------------ (c) liquidation_unrepresentable


def _reject_reasons(events: list[object]) -> list[str | None]:
    return [getattr(ev, "reason", None) for ev in events if getattr(ev, "kind", "") == "reject"]


@pytest.mark.unit
@pytest.mark.parametrize("order_leverage", [1, 2, 3], ids=["1x", "2x", "3x"])
def test_R3_hole_c_an_add_is_rejected_when_a_meta_refresh_lowers_max_leverage_below_the_positions_leverage(
    new_env: NewEnv, order_leverage: int
) -> None:
    """Position leverage 5, new max 3. The order's own leverage (<= 3) would be representable; the position's is not."""
    e = new_env()
    e.open_position("buy", "1.0", px="100", leverage=5)
    e.advance(T)
    cash, fills, view = e.broker.cash_usd(), len(e.fills()), e.broker.position("SOL")
    e.meta.meta["SOL"] = CoinMeta(sz_decimals=2, max_leverage=3)
    e.clock.now = D0 + 61 * MIN  # paper.meta_refresh_min (60) has passed
    e.flat_book("SOL", T + 1000, "100")
    intent = e.order("buy", "1.0", coid="add1", action=ActionKind.ADD, decided=T, share="S2", trade="T2",
                     leverage=order_leverage)
    assert e.submit(intent).accepted
    events = e.advance(T + 1000)
    assert _reject_reasons(list(events)) == ["liquidation_unrepresentable"]
    assert (e.broker.cash_usd(), len(e.fills()), e.broker.position("SOL")) == (cash, fills, view)
    assert e.records("paper_reject")[-1].payload["reason"] == "liquidation_unrepresentable"


@pytest.mark.unit
def test_R3_hole_c_an_add_that_pulls_the_average_entry_off_the_grid_is_rejected_without_state_change(
    new_env: NewEnv,
) -> None:
    e = new_env(meta=FakeMeta({**DEFAULT_META, "XX": CoinMeta(sz_decimals=5, max_leverage=40)}))
    e.open_position("buy", "2", px="10", coin="XX", coid="a", share="A", trade="T1", leverage=1)
    e.advance(T)
    cash, fills, view = e.broker.cash_usd(), len(e.fills()), e.broker.position("XX")
    e.flat_book("XX", T + 1000, "0.5", depth="100000")
    # 100 more at 0.5: average 0.686, liquidation price 0.686 / 80 = 0.0086, below the tick 0.1
    assert e.submit(e.order("buy", "100", coid="b", coin="XX", action=ActionKind.ADD, decided=T, px="0.5", share="B",
                            trade="T2", leverage=1)).accepted
    events = e.advance(T + 1000)
    assert _reject_reasons(list(events)) == ["liquidation_unrepresentable"]
    assert (e.broker.cash_usd(), len(e.fills()), e.broker.position("XX")) == (cash, fills, view)


@pytest.mark.unit
def test_R3_hole_c_control_the_same_add_fills_when_the_liquidation_price_is_representable(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", leverage=5)
    e.advance(T)
    e.flat_book("SOL", T + 1000, "100")
    assert e.submit(e.order("buy", "1.0", coid="add1", action=ActionKind.ADD, decided=T, share="S2", trade="T2",
                            leverage=5)).accepted
    (event,) = e.advance(T + 1000)
    assert event.kind == "fill" and e.broker.position("SOL").qty == D("2.0")


# -------------------------------------------------------------- (d) an ADD refreshes the stored rules


@pytest.mark.unit
def test_R3_hole_d_an_add_refreshes_the_positions_max_leverage_and_sz_decimals_and_a_later_exit_uses_them(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100", leverage=5)  # SOL rules 2 decimals, max leverage 20
    e.advance(T)
    assert e.broker.position("SOL").liquidation_px == D("82.5")  # 100 x (1 - (1/5 - 1/40))
    e.meta.meta["SOL"] = CoinMeta(sz_decimals=1, max_leverage=10)
    e.clock.now = D0 + 61 * MIN
    e.flat_book("SOL", T + 1000, "100")
    assert e.submit(e.order("buy", "1.0", coid="add1", action=ActionKind.ADD, decided=T, share="S2", trade="T2",
                            leverage=5)).accepted
    (event,) = e.advance(T + 1000)
    assert event.kind == "fill"
    view = e.broker.position("SOL")
    assert view.leverage == 5 and view.qty == D("3.0")
    assert view.liquidation_px == D("85")  # the new max leverage 10: 100 x (1 - (1/5 - 1/20)); the stale one gives 82.5
    # the coin is dropped from meta: the exit uses what the ADD stored (1 size decimal), never meta
    del e.meta.meta["SOL"]
    e.clock.now = D0 + 130 * MIN
    e.flat_book("SOL", T + 3000, "100")
    assert e.submit(e.order("sell", "0.55", coid="red1", action=ActionKind.REDUCE, decided=T + 2000, share="S1",
                            trade="T1")).accepted
    (reduce_event,) = e.advance(T + 3000)
    assert reduce_event.kind in ("fill", "partial_fill")
    assert reduce_event.fill.qty == D("0.5")  # 0.55 cut to one decimal; two decimals would fill 0.55
    assert e.broker.position("SOL").qty == D("2.5")


# ---------------------------------------------------------------------- (e) duplicate place_stop id


@pytest.mark.unit
def test_R3_hole_e_a_stop_with_a_used_client_order_id_is_refused_duplicate_client_order_id(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(T)
    assert e.stop("sl", "sell", "1.0", "90", coid="stop1").accepted
    again = e.stop("sl", "sell", "1.0", "85", coid="stop1")  # a fresh token, the same client order id
    assert (again.accepted, again.reason) == (False, "duplicate_client_order_id")
    assert list(e.broker._stops) == ["stop1"]  # noqa: SLF001 - and the first stop was not replaced
    assert e.broker._stops["stop1"].trigger_px == D("90")  # noqa: SLF001
    assert len([r for r in e.records("paper_stop")]) == 1


@pytest.mark.unit
def test_R3_hole_e_a_stop_reusing_an_order_client_order_id_is_refused(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", coid="open1")
    e.advance(T)
    result = e.stop("sl", "sell", "1.0", "90", coid="open1")
    assert (result.accepted, result.reason) == (False, "duplicate_client_order_id")
    assert list(e.broker._stops) == []  # noqa: SLF001
