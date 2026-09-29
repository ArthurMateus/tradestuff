"""F5.AC2: round-trip reconstruction matches ``research/scripts/hl_sample.py::reconstruct`` (self-test 1).

Spec: 04-spec.md F5.AC2; edge-hypothesis 10.1. Vectors: hl_sample.py selftest section 1, in Decimal.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.scoring.models import Fill
from copytrade.scoring.reconstruct import reconstruct
from tests.scoring.helpers import DAY, M, fill, funding

pytestmark = pytest.mark.unit
D = Decimal


def reference_fills() -> list[Fill]:
    """hl_sample.py selftest 1, verbatim (times in minutes)."""
    return [
        fill(0, "ETH", "B", 1, 100, 1),  # pre-existing long: ignored
        fill(1 * M, "ETH", "A", 2, 101, 2, pnl=2),  # closes it -> flat
        fill(2 * M, "BTC", "B", 1, 100, 0),  # open long 1
        fill(3 * M, "BTC", "B", 1, 98, 1),  # add while losing
        fill(4 * M, "BTC", "A", "0.8", 102, 2, pnl="3.2"),  # reduce 40%
        fill(10 * M, "BTC", "A", "3.2", 103, "1.2", pnl="3.6"),  # flip: close 1.2, open short 2.0
        fill(20 * M, "BTC", "B", 2, 104, -2, pnl=-2),  # close short
        fill(30 * M, "SOL", "A", 5, 20, 0),  # open short, still open
        fill(31 * M, "xyz:TSLA", "B", 1, 300, 0),  # HIP-3: skipped
        fill(32 * M, "@107", "B", 1, 30, 0),  # spot: skipped
    ]


def test_F5_AC2_reference_selftest_closed_trips() -> None:
    r = reconstruct(reference_fills(), [])
    assert [(t.coin, t.direction) for t in r.closed] == [("BTC", 1), ("BTC", -1)]
    first, second = r.closed
    assert first.adds == 1 and first.adds_while_losing == 1
    assert first.reduces == (D("0.4"),)
    assert [e.kind for e in first.events] == ["add", "reduce"]
    assert first.close_ms == 10 * M and second.open_ms == 10 * M
    assert first.net_pnl == D("6.8") and second.net_pnl == D("-2.0")


def test_F5_AC2_reference_selftest_open_trip_left_open() -> None:
    r = reconstruct(reference_fills(), [])
    assert [(t.coin, t.direction, t.close_ms) for t in r.open] == [("SOL", -1, None)]


def test_F5_AC2_a_flip_splits_into_a_close_and_an_open() -> None:
    r = reconstruct(reference_fills(), [])
    first, second = r.closed
    assert first.close_ms == second.open_ms
    assert second.direction == -1 and second.open_sz == D("2.0") and second.open_px == D(103)
    # the flip fill's P&L belongs to the closing trip only; the new trip starts clean
    assert first.gross_pnl == D("6.8") and second.gross_pnl == D("-2.0")


def test_F5_AC2_position_open_at_first_fill_is_ignored_until_flat() -> None:
    fills = [
        fill(0, "ETH", "B", 1, 100, 1, pnl=5, fee=1),
        fill(1 * M, "ETH", "A", 2, 101, 2, pnl=2),
        fill(2 * M, "ETH", "B", 1, 100, 0),  # the next open is a normal one
        fill(3 * M, "ETH", "A", 1, 101, 1, pnl=1),
    ]
    r = reconstruct(fills, [])
    assert len(r.closed) == 1 and r.closed[0].open_ms == 2 * M and r.closed[0].net_pnl == D(1)


def test_F5_AC2_flip_out_of_an_ignored_position_is_a_fresh_open() -> None:
    fills = [
        fill(0, "ETH", "B", 1, 100, 2),  # pre-existing long 2 -> 3
        fill(1 * M, "ETH", "A", 5, 101, 3, pnl=3),  # flips to short 2: a fresh open
        fill(2 * M, "ETH", "B", 2, 99, -2, pnl=4),
    ]
    r = reconstruct(fills, [])
    assert len(r.closed) == 1
    assert r.closed[0].direction == -1 and r.closed[0].open_ms == 1 * M and r.closed[0].open_sz == D(2)
    assert r.closed[0].net_pnl == D(4)


@pytest.mark.parametrize("coin", ["@107", "PURR/USDC", "xyz:TSLA", "abc:BTC"])
def test_F5_AC2_spot_and_dex_prefixed_fills_are_skipped(coin: str) -> None:
    fills = [fill(0, coin, "B", 1, 100, 0), fill(M, coin, "A", 1, 110, 1, pnl=10)]
    r = reconstruct(fills, [])
    assert r.closed == () and r.open == ()


def test_F5_AC2_peak_notional_and_average_entry_after_adds() -> None:
    fills = [
        fill(0, "BTC", "B", 10, 100, 0),
        fill(M, "BTC", "B", 10, 98, 10),
        fill(2 * M, "BTC", "A", 8, 101, 20, pnl=16),
        fill(3 * M, "BTC", "A", 12, 103, 12, pnl=48),
    ]
    trip = reconstruct(fills, []).closed[0]
    assert trip.avg_px == D(99) and trip.max_abs_sz == D(20) and trip.peak_notional == D(1980)
    assert trip.open_px == D(100) and trip.open_sz == D(10)


def test_F5_AC2_liquidation_fill_flags_the_trip() -> None:
    fills = [fill(0, "BTC", "B", 1, 100, 0), fill(M, "BTC", "A", 1, 80, 1, pnl=-20, liq=True)]
    assert reconstruct(fills, []).closed[0].liquidated is True
    assert reconstruct(fills[:1] + [fill(M, "BTC", "A", 1, 80, 1, pnl=-20)], []).closed[0].liquidated is False


def test_F5_AC2_net_pnl_is_closed_pnl_minus_fees_minus_funding_paid_inside_the_trip() -> None:
    fills = [
        fill(0, "BTC", "B", 1, 100, 0, fee="0.5"),
        fill(10 * M, "BTC", "A", 1, 110, 1, pnl=10, fee="0.5"),
    ]
    pay = [
        funding(5 * M, "BTC", "0.25"),  # inside: a cost
        funding(6 * M, "BTC", "-0.05"),  # inside: received
        funding(6 * M, "ETH", 99),  # another coin
        funding(11 * M, "BTC", 99),  # after the close
        funding(-M, "BTC", 99),  # before the open
    ]
    trip = reconstruct(fills, pay).closed[0]
    assert trip.gross_pnl == D(10)
    assert trip.net_pnl == D("10") - D("1.0") - D("0.20")


def test_F5_AC2_input_order_does_not_matter_and_ties_break_by_tid() -> None:
    base = reference_fills()
    expected = reconstruct(base, [])
    shuffled = base[:]
    random.Random(7).shuffle(shuffled)
    assert reconstruct(shuffled, []) == expected


def test_F5_AC2_a_repeated_tid_is_counted_once() -> None:
    fills = [fill(0, "BTC", "B", 1, 100, 0, tid=1), fill(M, "BTC", "A", 1, 101, 1, pnl=1, tid=2)]
    once = reconstruct(fills, [])
    twice = reconstruct([*fills, fills[0], fills[1], fills[1]], [])
    assert twice == once


def test_F5_AC2_empty_input_gives_empty_reconstruction() -> None:
    r = reconstruct([], [])
    assert r.closed == () and r.open == ()


def test_F5_AC2_open_at_one_ms_apart_keeps_millisecond_times() -> None:
    fills = [fill(1_700_000_000_001, "BTC", "B", 1, 100, 0), fill(1_700_000_000_002, "BTC", "A", 1, 100, 1)]
    t = reconstruct(fills, []).closed[0]
    assert (t.open_ms, t.close_ms) == (1_700_000_000_001, 1_700_000_000_002)


_steps = st.lists(
    st.tuples(st.sampled_from(["BTC", "ETH"]), st.integers(-4, 4).filter(bool), st.integers(-50, 50), st.integers(0, 3)),
    min_size=0,
    max_size=40,
)


def _walk(steps: list[tuple[str, int, int, int]]) -> list[Fill]:
    pos = {"BTC": 0, "ETH": 0}
    fills = []
    for i, (coin, delta, pnl, fee) in enumerate(steps):
        fills.append(
            fill(i * M, coin, "B" if delta > 0 else "A", abs(delta), 100, pos[coin], pnl=pnl, fee=fee, tid=i + 1)
        )
        pos[coin] += delta
    return fills


@given(_steps, st.randoms(use_true_random=False))
@settings(max_examples=150)
def test_F5_AC2_property_conserves_pnl_and_is_order_independent(steps: list[tuple[str, int, int, int]], rnd: random.Random) -> None:
    """From flat, every fill's closedPnl - fee lands in exactly one trip; shuffling the input changes nothing."""
    fills = _walk(steps)
    r = reconstruct(fills, [])
    total = sum((f.closed_pnl - f.fee for f in fills), D(0))
    # the very first fill of a coin that opens from flat is never "pre-existing", so nothing is ignored here
    # except the P&L of an opening fill with no open trip (there is none: opens carry closedPnl = fee = 0 in HL,
    # but this generator gives them values, and those belong to the opened trip)
    assert sum((t.net_pnl for t in (*r.closed, *r.open)), D(0)) == total
    shuffled = fills[:]
    rnd.shuffle(shuffled)
    assert reconstruct(shuffled, []) == r
    for t in r.closed:
        assert t.close_ms is not None and t.close_ms >= t.open_ms


def test_F5_AC2_days_are_utc_ms_not_seconds() -> None:
    fills = [fill(200 * DAY, "BTC", "B", 1, 100, 0), fill(200 * DAY + 5 * M, "BTC", "A", 1, 101, 1, pnl=1)]
    assert reconstruct(fills, []).closed[0].open_ms == 200 * DAY
