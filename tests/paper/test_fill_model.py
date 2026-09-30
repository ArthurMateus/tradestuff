# mypy: disable-error-code="union-attr"
"""F11.AC1: the fill model. A market order decided at t fills by walking the book at t + paper.ack_delay_ms
(first snapshot at or after that time, within paper.max_book_age_ms), at the VWAP of the levels used. Depth beyond
5% of mid gives a partial fill (kind ``partial_fill``, A8), the remainder cancelled. Also D1 (no lookahead) and B1
(staleness) for the book, and D3 (half-spread and slippage are paid by crossing the real book).

All expected values are hand-computed from the spec, not derived from an implementation.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from tests.paper.helpers import Env
from collections.abc import Sequence
from typing import Any
from tests.paper.helpers import NewEnv
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.money import Fee, Price, Qty
from tests.paper.helpers import D0, FEE_RATE, fresh_env, make_config

FILL_T = D0 + 1000


def _buy_env(e: Env, asks: Sequence[tuple[str, str]], bids: Sequence[tuple[str, str]] = (("99.9", "5"),), t: int = FILL_T) -> None:
    e.book("SOL", t, list(bids), list(asks))


@pytest.mark.unit
def test_F11_AC1_spec_example_vwap_is_100_05(new_env: NewEnv) -> None:
    e = new_env()
    _buy_env(e, [("100.0", "0.5"), ("100.1", "1.0")])
    assert e.submit(e.order("buy", "1.0")).accepted
    events = e.advance(FILL_T)
    assert [ev.kind for ev in events] == ["fill"]
    fill = events[0].fill
    assert fill.price == Price("100.05")  # (0.5 x 100.0 + 0.5 x 100.1) / 1.0
    assert fill.qty == Qty("1.0")
    assert fill.side == "buy"
    assert fill.fee == Fee("0.0450225")  # 100.05 x 4.5 bps
    assert fill.time == Timestamp(FILL_T, TimeSource.EXCHANGE)
    assert (fill.client_order_id, fill.trade_id, fill.share_id, fill.exit_reason) == ("c1", "T1", "S1", None)


@pytest.mark.unit
def test_F11_AC1_position_and_cash_after_the_fill(new_env: NewEnv) -> None:
    e = new_env()
    _buy_env(e, [("100.0", "0.5"), ("100.1", "1.0")])
    e.submit(e.order("buy", "1.0"))
    e.advance(FILL_T)
    pos = e.broker.position("SOL")
    assert pos.qty == Qty("1.0") and pos.avg_entry_px == Price("100.05")
    assert e.broker.cash_usd() == D("299.9549775")  # 300 - 0.0450225 (margin is posted, not spent)


@pytest.mark.unit
def test_F11_AC1_sell_walks_the_bids(new_env: NewEnv) -> None:
    e = new_env()
    e.book("SOL", FILL_T, [("100.0", "0.5"), ("99.9", "1.0")], [("100.1", "5")])
    e.submit(e.order("sell", "1.0"))
    fill = e.advance(FILL_T)[0].fill
    assert fill.price == Price("99.95")  # (0.5 x 100.0 + 0.5 x 99.9) / 1.0
    assert fill.side == "sell" and fill.fee == Fee("0.0449775")
    assert e.broker.position("SOL").qty == Qty("-1.0")


@pytest.mark.unit
def test_F11_AC1_nothing_fills_before_the_ack_delay_elapses(new_env: NewEnv) -> None:
    e = new_env()
    _buy_env(e, [("100.0", "5")])
    e.submit(e.order("buy", "1.0"))
    assert e.advance(FILL_T - 1) == []  # 999 ms after the decision: still in flight
    assert e.broker.position("SOL") is None
    assert [ev.kind for ev in e.advance(FILL_T)] == ["fill"]  # exactly decided + 1000


@pytest.mark.unit
def test_F11_AC1_snapshots_before_the_fill_time_are_ignored_and_the_first_at_or_after_is_used(new_env: NewEnv) -> None:
    e = new_env()
    e.book("SOL", FILL_T - 1, [("200", "9")], [("200", "9")])  # 1 ms too early
    e.book("SOL", FILL_T, [("100", "9")], [("100", "9")])
    e.book("SOL", FILL_T + 1, [("300", "9")], [("300", "9")])  # later snapshot is not the first
    e.submit(e.order("buy", "1.0"))
    fill = e.advance(FILL_T + 1)[0].fill
    assert fill.price == Price("100")
    assert fill.time.ms == FILL_T


@pytest.mark.unit
def test_F11_AC1_ack_delay_is_data_driven(new_env: NewEnv) -> None:
    e = new_env(config=make_config(paper__ack_delay_ms=2500))
    e.flat_book("SOL", D0 + 1000, "200")
    e.flat_book("SOL", D0 + 2500, "100")
    e.submit(e.order("buy", "1.0"))
    assert e.advance(D0 + 2499) == []
    fill = e.advance(D0 + 2500)[0].fill
    assert fill.price == Price("100") and fill.time.ms == D0 + 2500


@pytest.mark.unit
def test_F11_AC1_no_lookahead_a_recorded_future_book_is_not_used_early(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", FILL_T + 500, "101")  # exists in the recording, but is "in the future" at FILL_T
    e.submit(e.order("buy", "1.0"))
    assert e.advance(FILL_T) == []
    assert e.broker.position("SOL") is None
    fill = e.advance(FILL_T + 500)[0].fill
    assert fill.price == Price("101")


@pytest.mark.unit
def test_F11_AC1_book_age_boundary_exactly_max_book_age_is_usable(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", FILL_T + 5000, "100")  # 5,000 ms after the fill time = paper.max_book_age_ms
    e.submit(e.order("buy", "1.0"))
    assert [ev.kind for ev in e.advance(FILL_T + 5000)] == ["fill"]


@pytest.mark.unit
def test_F11_AC1_book_age_one_ms_over_the_limit_is_refused_no_book(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", FILL_T + 5001, "100")
    e.submit(e.order("buy", "1.0"))
    events = e.advance(FILL_T + 5001)
    assert [(ev.kind, ev.reason) for ev in events] == [("reject", "no_book")]
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_F11_AC1_no_book_yet_at_exactly_the_window_end_keeps_waiting_one_ms_later_rejects(new_env: NewEnv) -> None:
    e = new_env()
    e.submit(e.order("buy", "1.0"))
    assert e.advance(FILL_T + 5000) == []  # a snapshot could still arrive at exactly the last usable ms
    assert [(ev.kind, ev.reason) for ev in e.advance(FILL_T + 5001)] == [("reject", "no_book")]


@pytest.mark.unit
def test_F11_AC1_depth_beyond_5pct_of_mid_gives_a_partial_fill_and_the_remainder_is_cancelled(new_env: NewEnv) -> None:
    e = new_env()
    # mid = (99.9 + 100.1) / 2 = 100.0, so the band is asks <= 105.0; 105.2 is outside it.
    _buy_env(e, [("100.1", "1.0"), ("105.2", "5.0")])
    e.submit(e.order("buy", "3.0"))
    events = e.advance(FILL_T)
    assert [ev.kind for ev in events] == ["partial_fill"]
    fill = events[0].fill
    assert fill.qty == Qty("1.0") and fill.price == Price("100.1")
    assert e.broker.position("SOL").qty == Qty("1.0")
    # remainder cancelled: a later, deeper book does not fill it
    e.flat_book("SOL", FILL_T + 1000, "100")
    assert e.advance(FILL_T + 1000) == []
    assert e.broker.position("SOL").qty == Qty("1.0")
    (rec,) = e.records("partial_fill")
    assert rec.payload["client_order_id"] == "c1"
    assert (rec.payload["requested_qty"], rec.payload["filled_qty"], rec.payload["cancelled_qty"]) == (
        D("3.0"), D("1.0"), D("2.0"),
    )


@pytest.mark.unit
def test_F11_AC1_a_level_exactly_at_5pct_of_mid_is_included(new_env: NewEnv) -> None:
    e = new_env()
    _buy_env(e, [("100.1", "1.0"), ("105.0", "1.0")])
    e.submit(e.order("buy", "2.0"))
    (ev,) = e.advance(FILL_T)
    assert ev.kind == "fill" and ev.fill.price == Price("102.55") and ev.fill.qty == Qty("2.0")  # (100.1+105.0)/2


@pytest.mark.unit
def test_F11_AC1_a_level_one_tick_past_5pct_of_mid_is_excluded(new_env: NewEnv) -> None:
    e = new_env()
    _buy_env(e, [("100.1", "1.0"), ("105.01", "1.0")])
    e.submit(e.order("buy", "2.0"))
    (ev,) = e.advance(FILL_T)
    assert ev.kind == "partial_fill" and ev.fill.qty == Qty("1.0") and ev.fill.price == Price("100.1")


@pytest.mark.unit
def test_F11_AC1_sell_side_band_boundaries(new_env: NewEnv) -> None:
    inside = new_env()
    inside.book("SOL", FILL_T, [("99.9", "1.0"), ("95.0", "1.0")], [("100.1", "5")])  # mid 100.0, floor 95.0
    inside.submit(inside.order("sell", "2.0"))
    (ev,) = inside.advance(FILL_T)
    assert ev.kind == "fill" and ev.fill.price == Price("97.45")  # (99.9 + 95.0) / 2

    outside = new_env()
    outside.book("SOL", FILL_T, [("99.9", "1.0"), ("94.99", "1.0")], [("100.1", "5")])
    outside.submit(outside.order("sell", "2.0"))
    (ev2,) = outside.advance(FILL_T)
    assert ev2.kind == "partial_fill" and ev2.fill.qty == Qty("1.0") and ev2.fill.price == Price("99.9")


@pytest.mark.unit
def test_F11_AC1_no_depth_inside_the_band_rejects_an_open_with_no_depth(new_env: NewEnv) -> None:
    e = new_env()
    e.book("SOL", FILL_T, [("90", "5")], [("110", "5")])  # mid 100, both sides outside 5%
    e.submit(e.order("buy", "1.0"))
    assert [(ev.kind, ev.reason) for ev in e.advance(FILL_T)] == [("reject", "no_depth")]
    assert e.broker.position("SOL") is None


@pytest.mark.unit
@pytest.mark.parametrize("bids,asks", [([("99", "5")], []), ([], [("101", "5")]), ([], [])])
def test_F11_AC1_one_sided_or_empty_book_rejects_an_open_with_no_depth(new_env: NewEnv, bids: Any, asks: Any) -> None:
    e = new_env()
    e.book("SOL", FILL_T, bids, asks)
    e.submit(e.order("buy", "1.0"))
    assert [(ev.kind, ev.reason) for ev in e.advance(FILL_T)] == [("reject", "no_depth")]


@pytest.mark.unit
def test_F11_AC1_half_spread_and_slippage_are_paid_by_crossing_the_real_book(new_env: NewEnv) -> None:
    """D3: buying costs (ask - mid) = half-spread 0.1 plus walking slippage; selling the same size gets the mirror."""
    e = new_env()
    e.book("SOL", FILL_T, [("99.9", "0.5"), ("99.8", "1.0")], [("100.1", "0.5"), ("100.2", "1.0")])
    mid = D("100.0")
    e.submit(e.order("buy", "1.0", coid="b"))
    buy = e.advance(FILL_T)[0].fill
    e.book("SOL", FILL_T + 10_000, [("99.9", "0.5"), ("99.8", "1.0")], [("100.1", "0.5"), ("100.2", "1.0")])
    e.submit(e.order("sell", "1.0", coid="s", decided=D0 + 10_000, action=None))
    sell = e.advance(FILL_T + 10_000)[0].fill
    assert buy.price == Price("100.15")  # (0.5 x 100.1 + 0.5 x 100.2)
    assert sell.price == Price("99.85")  # (0.5 x 99.9 + 0.5 x 99.8)
    assert buy.price - mid == D("0.15") == mid - sell.price  # half-spread 0.1 + slippage 0.05, each side


_ticks = st.integers(min_value=0, max_value=400)  # 0.01 steps above the best ask (<= 4%, inside the 5% band)


@pytest.mark.unit
@settings(max_examples=30)
@given(
    offsets=st.lists(_ticks, min_size=1, max_size=6, unique=True),
    sizes=st.lists(st.integers(min_value=1, max_value=500), min_size=6, max_size=6),
    frac=st.integers(min_value=1, max_value=100),
)
def test_F11_AC1_property_vwap_is_bounded_exact_and_never_overfills(offsets: Any, sizes: Any, frac: Any) -> None:
    offsets = sorted(offsets)
    levels = [(D(10000 + o) / 100, D(s) / 100) for o, s in zip(offsets, sizes, strict=False)]
    total = sum(sz for _, sz in levels)
    qty = (total * frac / 100).quantize(D("0.01"))
    if qty < D("0.10") or qty * levels[0][0] < 10:
        return  # below the minimum order: a different AC
    asks = [(str(px), str(sz)) for px, sz in levels]
    with fresh_env() as e:
        e.book("SOL", FILL_T, [(asks[0][0], "1000")], asks)  # locked at the best ask => mid = best ask
        e.submit(e.order("buy", str(qty)))
        (ev,) = e.advance(FILL_T)
        fill = ev.fill
        assert fill.qty == qty and ev.kind == "fill"
        # independent oracle: cumulative cost of the cheapest levels covering qty
        remaining, cost = qty, D(0)
        for px, sz in levels:
            take = min(remaining, sz)
            cost += take * px
            remaining -= take
        assert remaining == 0
        assert abs(fill.price * fill.qty - cost) < D("1e-15")  # Decimal VWAP, never a float
        assert levels[0][0] <= fill.price <= max(px for px, _ in levels)
        assert abs(fill.fee - cost * FEE_RATE) < D("1e-15")
