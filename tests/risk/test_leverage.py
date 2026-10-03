"""F10.AC4 and AC10: automatic isolated leverage and the liquidation-distance rule, on the pure function.

The spec's vectors use a fixture where the liquidation distance is ``1/L - 1/(2 x maxLeverage)`` and the decision
price equals the entry. The property tests restate the rule independently of the implementation, using the F11.AC5
``liquidation_price`` as the single liquidation model (property 7).
"""

from __future__ import annotations

from decimal import Context, Decimal as D
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.money import Price, Qty
from copytrade.paper.liquidation import liquidation_price
from copytrade.risk.leverage import LeveragePlan, leverage_ceiling, plan_leverage

PRECISE = Context(prec=60)
HIGH = frozenset({"BTC", "ETH", "SOL"})


def ceiling(coin: str, exch: int, *, high: int = 10, alt: int = 5, coins: frozenset[str] = HIGH) -> int:
    return leverage_ceiling(
        coin=coin, high_leverage_coins=coins, max_leverage_high_tier=high, max_leverage_alt=alt,
        exchange_max_leverage=exch,
    )


def plan(
    coin: str,
    exch: int,
    *,
    free: str,
    stops: tuple[str, ...] = ("98.5",),
    side: str = "long",
    sz: int = 2,
    px: str = "100",
    qty: str = "1",
    existing_qty: str = "0",
    existing_avg: str | None = None,
    posted: str = "0",
    leverage_min: int = 1,
    mult: str = "3",
    cap: int | None = None,
) -> LeveragePlan:
    return plan_leverage(
        side=side,
        coin_ceiling=ceiling(coin, exch) if cap is None else cap,
        leverage_min=leverage_min,
        exchange_max_leverage=exch,
        sz_decimals=sz,
        decision_px=Price(px),
        order_qty=Qty(qty),
        existing_qty=Qty(existing_qty),
        existing_avg_entry_px=None if existing_avg is None else Price(existing_avg),
        posted_margin_usd=D(posted),
        free_equity_usd=D(free),
        share_stop_pxs=tuple(Price(s) for s in stops),
        min_liq_distance_stop_mult=D(mult),
    )


# ---- ceiling C ---------------------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "coin,exch,expected",
    [("BTC", 40, 10), ("ETH", 25, 10), ("SOL", 20, 10), ("DOGE", 10, 5), ("XRP", 20, 5), ("SOL", 3, 3), ("DOGE", 4, 4),
     ("DOGE", 1, 1), ("BTC", 10, 10), ("BTC", 11, 10)],
)
def test_F10_AC4_ceiling_is_the_tier_ceiling_capped_by_the_exchange_max_leverage(
    coin: str, exch: int, expected: int
) -> None:
    assert ceiling(coin, exch) == expected


@pytest.mark.unit
def test_F10_AC4_a_coin_removed_from_the_high_leverage_list_gets_the_alt_ceiling() -> None:
    assert ceiling("ETH", 25, coins=frozenset({"BTC"})) == 5
    assert ceiling("BTC", 40, coins=frozenset({"BTC"})) == 10
    assert ceiling("BTC", 40, coins=frozenset()) == 5


@pytest.mark.unit
def test_F10_AC4_the_ceilings_come_from_config_values_passed_in() -> None:
    assert ceiling("SOL", 20, high=7) == 7
    assert ceiling("DOGE", 10, alt=2) == 2


# ---- the five spec vectors ------------------------------------------------------------------------------------


@pytest.mark.unit
def test_F10_AC4_vector_equity_300_no_open_positions_btc_100_is_1x() -> None:
    p = plan("BTC", 40, free="300", sz=5)
    assert p.accepted and p.reason is None
    assert p.leverage == 1 and p.ceiling == 10
    assert p.required_margin_usd == D(100)
    assert p.posted_margin_usd == 0
    assert p.liquidation_px == liquidation_price(
        side="long", avg_entry_px=Price("100"), leverage=1, max_leverage=40, sz_decimals=5
    )


@pytest.mark.unit
def test_F10_AC4_vector_free_equity_40_eth_100_is_3x() -> None:
    p = plan("ETH", 25, free="40", sz=4, stops=("99",))
    assert (p.accepted, p.leverage, p.ceiling) == (True, 3, 10)
    assert p.required_margin_usd is not None and abs(p.required_margin_usd - D(100) / 3) < D("1e-20")


@pytest.mark.unit
def test_F10_AC4_vector_free_equity_15_alt_100_needs_20_at_the_5x_ceiling_so_insufficient_margin() -> None:
    p = plan("DOGE", 10, free="15", sz=0)
    assert (p.accepted, p.reason, p.leverage, p.ceiling) == (False, "insufficient_margin", None, 5)
    assert p.liquidation_px is None


@pytest.mark.unit
def test_F10_AC4_vector_free_equity_12_sol_100_is_9x_with_liquidation_distance_8_611_percent() -> None:
    p = plan("SOL", 20, free="12", stops=("97.2",))  # stop 2.8%: 3 x 2.8 = 8.4 <= 8.611
    assert (p.accepted, p.leverage, p.ceiling) == (True, 9, 10)
    assert p.liquidation_px == Price("91.389")  # 100 x (1 - (1/9 - 1/40)) = 91.3888.., on the price grid
    assert p.liquidation_px == liquidation_price(
        side="long", avg_entry_px=Price("100"), leverage=9, max_leverage=20, sz_decimals=2
    )


@pytest.mark.unit
def test_F10_AC4_vector_stop_2_9_percent_is_refused_liq_too_close_at_the_same_9x() -> None:
    p = plan("SOL", 20, free="12", stops=("97.1",))  # 3 x 2.9 = 8.7 > 8.611
    assert (p.accepted, p.reason, p.leverage) == (False, "liq_too_close", 9)


@pytest.mark.unit
def test_F10_AC4_vector_free_equity_12_doge_100_not_high_tier_is_insufficient_margin() -> None:
    p = plan("DOGE", 10, free="12", sz=0)
    assert (p.accepted, p.reason, p.leverage) == (False, "insufficient_margin", None)


# ---- boundaries ---------------------------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("free,leverage", [("20", 5), ("25", 4), ("19.99", None), ("100", 1), ("99.99", 2)])
def test_F10_AC4_margin_boundary_exactly_at_one_below_and_one_above(free: str, leverage: int | None) -> None:
    p = plan("DOGE", 10, free=free, sz=0, stops=("99.9",))
    assert p.leverage == leverage
    assert p.accepted == (leverage is not None)
    if leverage is None:
        assert p.reason == "insufficient_margin"


@pytest.mark.unit
@pytest.mark.parametrize(
    "stop,ok",
    [("95", True), ("95.1", True), ("94.9", False), ("96", True), ("94", False)],
)
def test_F10_AC4_liquidation_distance_boundary_exactly_3x_the_stop_distance_passes(stop: str, ok: bool) -> None:
    # alt, exchange max 10, L = 5: liquidation at 100 x (1 - (1/5 - 1/20)) = 85, distance 15; stop 5% is exactly 15/3
    p = plan("DOGE", 10, free="20", sz=0, stops=(stop,))
    assert p.leverage == 5
    assert p.liquidation_px == Price("85")
    assert p.accepted is ok
    assert p.reason == (None if ok else "liq_too_close")


@pytest.mark.unit
def test_F10_AC4_short_side_liquidates_above_the_entry() -> None:
    ok = plan("SOL", 20, free="12", side="short", stops=("102.8",))
    assert (ok.accepted, ok.leverage) == (True, 9)
    assert ok.liquidation_px == Price("108.61")  # 100 x 1.0861111 on the grid
    bad = plan("SOL", 20, free="12", side="short", stops=("102.9",))
    assert (bad.accepted, bad.reason, bad.leverage) == (False, "liq_too_close", 9)


@pytest.mark.unit
def test_F10_AC4_leverage_min_is_the_lowest_leverage_tried() -> None:
    assert plan("BTC", 40, free="300", sz=5, leverage_min=2).leverage == 2
    assert plan("BTC", 40, free="300", sz=5, leverage_min=3).leverage == 3


@pytest.mark.unit
def test_F10_AC4_no_integer_in_the_range_is_insufficient_margin_even_when_money_is_plentiful() -> None:
    p = plan("DOGE", 2, free="100000", sz=0, leverage_min=3)  # ceiling 2 < leverage_min 3: empty range
    assert (p.accepted, p.reason, p.leverage) == (False, "insufficient_margin", None)


@pytest.mark.unit
def test_F10_AC4_a_lower_exchange_max_leverage_lowers_the_ceiling_and_can_refuse() -> None:
    p = plan("SOL", 3, free="30")  # 100/3 = 33.3 > 30 and the ceiling is 3
    assert (p.accepted, p.reason, p.ceiling) == (False, "insufficient_margin", 3)


# ---- merged positions: posted margin counts, every share is checked ------------------------------------------------


@pytest.mark.unit
def test_F10_AC4_an_add_uses_the_posted_margin_plus_free_equity_and_the_merged_average_entry() -> None:
    # existing 1.0 @ 100 (margin 20), add 1.0 @ 110: post-order notional 220, available 20 + 10 = 30 -> L = 8 (7 needs 31.4)
    p = plan(
        "SOL", 20, free="10", posted="20", px="110", qty="1", existing_qty="1", existing_avg="100",
        stops=("108", "109"),
    )
    assert (p.accepted, p.leverage) == (True, 8)
    assert p.required_margin_usd == D("27.5")
    assert p.posted_margin_usd == D(20)
    # merged average entry 105: liquidation 105 x (1 - (1/8 - 1/40)) = 94.5
    assert p.liquidation_px == Price("94.5")


@pytest.mark.unit
@pytest.mark.parametrize("stops,ok", [(("105",), True), (("104.9",), True), (("104.8",), False), (("108", "104.8"), False)])
def test_F10_AC4_every_share_of_the_merged_position_must_meet_the_rule(stops: tuple[str, ...], ok: bool) -> None:
    # liquidation 94.5 is 15.5 below the decision price 110; a stop at s is refused when 3 x (110 - s) > 15.5
    p = plan(
        "SOL", 20, free="10", posted="20", px="110", qty="1", existing_qty="1", existing_avg="100", stops=stops
    )
    assert p.leverage == 8
    assert p.accepted is ok


# ---- AC10 properties (>= 10,000 generated cases) ---------------------------------------------------------------------

COINS = st.sampled_from(["BTC", "ETH", "SOL", "DOGE", "XRP"])
HIGH_SETS = st.sets(st.sampled_from(["BTC", "ETH", "SOL"])).map(frozenset)


@st.composite
def cases(draw: st.DrawFn) -> dict[str, Any]:
    coin = draw(COINS)
    exch = draw(st.integers(1, 50))
    high_set = draw(HIGH_SETS)
    cap_high = draw(st.integers(1, 10))
    cap_alt = draw(st.integers(1, 5))
    px = D(draw(st.integers(1_000, 500_000))) / 100  # 10.00 .. 5000.00
    qty = D(draw(st.integers(1, 5_000))) / 100
    has_existing = draw(st.booleans())
    existing_qty = D(draw(st.integers(1, 5_000))) / 100 if has_existing else D(0)
    existing_avg = D(draw(st.integers(1_000, 500_000))) / 100 if has_existing else None
    n_shares = draw(st.integers(1, 4))
    side = draw(st.sampled_from(["long", "short"]))
    stops = []
    for _ in range(n_shares):
        off = D(draw(st.integers(1, 2_000))) / 10_000  # 0.01% .. 20%
        stops.append(px * (1 - off) if side == "long" else px * (1 + off))
    return dict(
        coin=coin, exch=exch, high_set=high_set, cap_high=cap_high, cap_alt=cap_alt, px=px, qty=qty,
        existing_qty=existing_qty, existing_avg=existing_avg, side=side,
        stops=tuple(s.quantize(D("0.0001")) for s in stops),
        posted=D(draw(st.integers(0, 20_000))) / 100 if has_existing else D(0),
        free=D(draw(st.integers(0, 200_000))) / 100,
        leverage_min=draw(st.integers(1, 3)),
        mult=D(draw(st.integers(300, 600))) / 100,
        sz=draw(st.integers(0, 3)),
    )


def run(c: dict[str, Any], *, free: D | None = None) -> tuple[LeveragePlan, int]:
    cap = leverage_ceiling(
        coin=c["coin"], high_leverage_coins=c["high_set"], max_leverage_high_tier=c["cap_high"],
        max_leverage_alt=c["cap_alt"], exchange_max_leverage=c["exch"],
    )
    p = plan_leverage(
        side=c["side"], coin_ceiling=cap, leverage_min=c["leverage_min"], exchange_max_leverage=c["exch"],
        sz_decimals=c["sz"], decision_px=Price(c["px"]), order_qty=Qty(c["qty"]), existing_qty=Qty(c["existing_qty"]),
        existing_avg_entry_px=None if c["existing_avg"] is None else Price(c["existing_avg"]),
        posted_margin_usd=c["posted"], free_equity_usd=c["free"] if free is None else free,
        share_stop_pxs=tuple(Price(s) for s in c["stops"]), min_liq_distance_stop_mult=c["mult"],
    )
    return p, cap


def oracle(c: dict[str, Any], cap: int, free: D) -> tuple[str, int | None]:
    """The rule restated with no shared code but the F11 liquidation model: ('ok'|reason, L)."""
    total = c["existing_qty"] + c["qty"]
    notional = PRECISE.multiply(total, c["px"])
    fits = [
        lv for lv in range(c["leverage_min"], cap + 1) if PRECISE.divide(notional, lv) <= c["posted"] + free
    ]
    if not fits:
        return "insufficient_margin", None
    lv = fits[0]
    avg = (
        c["px"]
        if c["existing_qty"] == 0
        else PRECISE.divide(PRECISE.add(PRECISE.multiply(c["existing_qty"], c["existing_avg"]), PRECISE.multiply(c["qty"], c["px"])), total)
    )
    liq = liquidation_price(
        side=c["side"], avg_entry_px=Price(avg), leverage=lv, max_leverage=c["exch"], sz_decimals=c["sz"]
    )
    dist = abs(c["px"] - liq)
    ok = all(dist >= c["mult"] * abs(c["px"] - s) for s in c["stops"])
    return ("ok" if ok else "liq_too_close"), lv


@pytest.mark.unit
@given(cases())
@settings(max_examples=10_000)
def test_F10_AC10_properties_ceiling_minimality_liquidation_exact_refusal_single_model(c: dict[str, Any]) -> None:
    p, cap = run(c)
    status, lv = oracle(c, cap, c["free"])
    # 1. ceiling, whatever the config
    assert cap <= (10 if c["coin"] in c["high_set"] else 5)
    assert cap <= c["exch"]
    if p.leverage is not None:
        assert 1 <= p.leverage <= cap
        # 2. minimality
        assert p.leverage == c["leverage_min"] or (
            PRECISE.divide(PRECISE.multiply(c["existing_qty"] + c["qty"], c["px"]), p.leverage - 1)
            > c["posted"] + c["free"]
        )
    # 6. refusal is exact
    if status == "insufficient_margin":
        assert (p.accepted, p.reason, p.leverage) == (False, "insufficient_margin", None)
        return
    assert p.leverage == lv
    assert p.accepted == (status == "ok")
    assert p.reason == (None if status == "ok" else "liq_too_close")
    # 3. liquidation rule for every share, when accepted
    # 7. one model: the price equals the F11.AC5 liquidation price
    assert p.liquidation_px is not None
    total = c["existing_qty"] + c["qty"]
    avg = (
        c["px"]
        if c["existing_qty"] == 0
        else PRECISE.divide(PRECISE.add(PRECISE.multiply(c["existing_qty"], c["existing_avg"]), PRECISE.multiply(c["qty"], c["px"])), total)
    )
    assert p.liquidation_px == liquidation_price(
        side=c["side"], avg_entry_px=Price(avg), leverage=lv, max_leverage=c["exch"], sz_decimals=c["sz"]
    )
    if p.accepted:
        dist = abs(c["px"] - p.liquidation_px)
        assert all(dist >= c["mult"] * abs(c["px"] - s) for s in c["stops"])


@pytest.mark.unit
@given(cases(), st.integers(0, 100_000))
@settings(max_examples=3_000)
def test_F10_AC10_property_more_free_equity_never_raises_the_leverage_and_never_changes_the_ceiling(
    c: dict[str, Any], extra_cents: int
) -> None:
    lo, cap_lo = run(c)
    hi, cap_hi = run(c, free=c["free"] + D(extra_cents) / 100)
    assert cap_lo == cap_hi
    big = 10**9
    assert (hi.leverage if hi.leverage is not None else big) <= (lo.leverage if lo.leverage is not None else big)
    if lo.leverage is not None:
        assert hi.leverage is not None  # never becomes unfittable


@pytest.mark.unit
@given(cases())
@settings(max_examples=2_000)
def test_F10_AC10_property_the_leverage_choice_does_not_depend_on_anything_but_its_inputs(c: dict[str, Any]) -> None:
    first, _ = run(c)
    second, _ = run(c)
    assert first == second
