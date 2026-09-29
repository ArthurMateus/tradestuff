"""F2.AC4 fill export (E5) and F2.AC5 honest aggregates.

AC4: ``export fills --from --to`` writes CSV with one row per paper fill: ISO-8601 UTC time, coin, side, qty,
price, fee, funding, client order ID, trade ID, share ID and exit reason; the row count equals the number of
fill records and Decimal strings round-trip exactly.
AC5: no aggregate API has a parameter that excludes records by outcome or flag; over a fixture with losers and
every flagged kind the totals equal the hand-computed sums over all of them.

Spec: 04-spec.md F2.AC4, F2.AC5, invariants E5, A6, D2.
"""

from __future__ import annotations

import csv
import inspect
import io
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.money import Fee, Funding, Pnl, Price, Qty
from copytrade.ledger.errors import LedgerCorruptError
from copytrade.ledger.export import FILLS_CSV_HEADER, TradeAggregate, aggregate_trades, export_fills
from copytrade.ledger.records import FillRecord
from copytrade.ledger.store import Ledger
from tests.ledger.helpers import (
    REQUIRED_TRADE_FLAGS,
    T0,
    FakeClock,
    flip_byte,
    line_span,
    make_decision,
    make_fill,
    make_trade,
)

pytestmark = pytest.mark.unit

HEADER = ["time", "coin", "side", "qty", "price", "fee", "funding", "client_order_id", "trade_id", "share_id", "exit_reason"]
WIDE = (0, 2**62)


def _export(directory: Path, lo: int = WIDE[0], hi: int = WIDE[1]) -> tuple[int, list[list[str]], str]:
    out = io.StringIO()
    count = export_fills(directory, from_ms=lo, to_ms=hi, out=out)
    return count, list(csv.reader(io.StringIO(out.getvalue()))), out.getvalue()


def _write_fills(ledger: Ledger, fills: list[FillRecord]) -> None:
    for fill in fills:
        ledger.append_fill(fill)


# --- AC4 ---------------------------------------------------------------------------------------------

def test_F2_AC4_header_is_exactly_the_specified_columns_in_order(ledger: Ledger, ledger_dir: Path) -> None:
    assert FILLS_CSV_HEADER.split(",") == HEADER
    count, rows, _ = _export(ledger_dir)
    assert count == 0 and rows == [HEADER]


def test_F2_AC4_row_count_equals_the_number_of_fill_records_and_other_kinds_are_ignored(ledger: Ledger, ledger_dir: Path) -> None:
    _write_fills(ledger, [make_fill(i) for i in range(7)])
    ledger.append_decision(make_decision(1))
    ledger.append("note", {"a": 1})
    ledger.append_trade(make_trade(1, "5"))
    count, rows, _ = _export(ledger_dir)
    assert count == 7 and len(rows) == 8


def test_F2_AC4_each_row_carries_the_fill_fields(ledger: Ledger, ledger_dir: Path) -> None:
    fills = [make_fill(0), make_fill(1, exit_reason="stop_loss")]
    _write_fills(ledger, fills)
    _, rows, _ = _export(ledger_dir)
    for fill, row in zip(fills, rows[1:], strict=True):
        cells = dict(zip(HEADER, row, strict=True))
        assert cells["coin"] == fill.coin and cells["side"] == fill.side
        assert cells["client_order_id"] == fill.client_order_id
        assert cells["trade_id"] == fill.trade_id and cells["share_id"] == fill.share_id
        assert cells["exit_reason"] == (fill.exit_reason or "")
    assert rows[1][-1] == "" and rows[2][-1] == "stop_loss"


def test_F2_AC4_time_is_iso_8601_utc_and_matches_the_fill_time_to_the_millisecond(ledger: Ledger, ledger_dir: Path) -> None:
    ms = T0 + 123  # not a whole second
    _write_fills(ledger, [make_fill(1, time_ms=ms)])
    _, rows, _ = _export(ledger_dir)
    cell = rows[1][0]
    assert cell.endswith("Z")
    parsed = datetime.fromisoformat(cell)
    assert parsed.utcoffset() == timedelta(0)
    assert round(parsed.timestamp() * 1000) == ms


def test_F2_AC4_decimal_strings_round_trip_exactly_and_are_never_scientific(ledger: Ledger, ledger_dir: Path) -> None:
    fill = FillRecord(
        time=Timestamp(T0, TimeSource.DERIVED),
        coin="PEPE",
        side="sell",
        qty=Qty("1E+3"),
        price=Price("0.00000123"),
        fee=Fee("0.000000010"),
        funding=Funding("-1E-8"),
        client_order_id="c",
        trade_id="t",
        share_id="s",
        exit_reason=None,
    )
    _write_fills(ledger, [fill])
    _, rows, text = _export(ledger_dir)
    cells = dict(zip(HEADER, rows[1], strict=True))
    assert (Decimal(cells["qty"]), Decimal(cells["price"]), Decimal(cells["fee"]), Decimal(cells["funding"])) == (
        fill.qty, fill.price, fill.fee, fill.funding
    )
    for key in ("qty", "price", "fee", "funding"):
        assert "e" not in cells[key].lower(), f"{key} is scientific: {cells[key]}"


def test_F2_AC4_range_is_from_inclusive_to_exclusive_on_the_fill_time(ledger: Ledger, ledger_dir: Path) -> None:
    lo, hi = T0, T0 + 10_000
    times = [lo - 1, lo, lo + 1, hi - 1, hi, hi + 1]
    _write_fills(ledger, [make_fill(i, time_ms=t) for i, t in enumerate(times)])
    count, rows, _ = _export(ledger_dir, lo, hi)
    assert count == 3
    assert [r[7] for r in rows[1:]] == ["coid-1", "coid-2", "coid-3"]


def test_F2_AC4_the_range_uses_fill_time_not_the_time_the_record_was_appended(ledger: Ledger, ledger_dir: Path, clock: FakeClock) -> None:
    clock.now = T0 + 10**9  # appended much later than the fill happened
    _write_fills(ledger, [make_fill(1, time_ms=T0)])
    assert _export(ledger_dir, T0, T0 + 1)[0] == 1


def test_F2_AC4_out_of_order_fills_are_all_exported_in_ledger_order(ledger: Ledger, ledger_dir: Path) -> None:
    _write_fills(ledger, [make_fill(i, time_ms=t) for i, t in enumerate([T0 + 500, T0 + 100, T0 + 300])])
    _, rows, _ = _export(ledger_dir)
    assert [r[7] for r in rows[1:]] == ["coid-0", "coid-1", "coid-2"]


def test_F2_AC4_a_duplicate_fill_record_is_exported_twice_never_silently_merged(ledger: Ledger, ledger_dir: Path) -> None:
    _write_fills(ledger, [make_fill(1), make_fill(1)])
    assert _export(ledger_dir)[0] == 2


def test_F2_AC4_awkward_text_is_quoted_and_round_trips_through_a_csv_reader(ledger: Ledger, ledger_dir: Path) -> None:
    fill = FillRecord(
        time=Timestamp(T0, TimeSource.DERIVED),
        coin='k"PEPE,×',
        side="buy",
        qty=Qty("1"),
        price=Price("2"),
        fee=Fee("0"),
        funding=Funding("0"),
        client_order_id="c,1\nline2",
        trade_id='t"1"',
        share_id="sç",
        exit_reason="tp, then “sl”",
    )
    _write_fills(ledger, [fill])
    _, rows, _ = _export(ledger_dir)
    cells = dict(zip(HEADER, rows[1], strict=True))
    assert cells["coin"] == fill.coin and cells["client_order_id"] == fill.client_order_id
    assert cells["trade_id"] == fill.trade_id and cells["share_id"] == fill.share_id
    assert cells["exit_reason"] == fill.exit_reason


def test_F2_AC4_empty_and_inverted_ranges(ledger: Ledger, ledger_dir: Path) -> None:
    _write_fills(ledger, [make_fill(1, time_ms=T0)])
    assert _export(ledger_dir, T0, T0)[0] == 0  # empty half-open range
    with pytest.raises(ValueError):
        export_fills(ledger_dir, from_ms=T0 + 1, to_ms=T0, out=io.StringIO())


def test_F2_AC4_export_works_while_the_engine_holds_the_ledger(ledger: Ledger, ledger_dir: Path) -> None:
    _write_fills(ledger, [make_fill(1)])
    assert _export(ledger_dir)[0] == 1
    _write_fills(ledger, [make_fill(2)])  # the writer is unaffected
    assert _export(ledger_dir)[0] == 2


def test_F2_AC4_a_tampered_ledger_is_never_exported(tmp_path: Path) -> None:
    directory = tmp_path / "tampered"
    with Ledger.open(directory, clock=FakeClock()) as ledger:
        _write_fills(ledger, [make_fill(i) for i in range(4)])
    flip_byte(directory, line_span(directory, 3)[0] + 30)
    out = io.StringIO()
    with pytest.raises(LedgerCorruptError) as caught:
        export_fills(directory, from_ms=0, to_ms=2**62, out=out)
    assert caught.value.seq == 3
    assert out.getvalue() == ""


_DEC = st.decimals(min_value=Decimal("-1000000"), max_value=Decimal("1000000"), places=8, allow_nan=False, allow_infinity=False)


@settings(max_examples=30)
@given(
    rows=st.lists(
        st.tuples(_DEC.filter(lambda d: d > 0), _DEC.filter(lambda d: d >= 0), _DEC.filter(lambda d: d >= 0), _DEC),
        min_size=1,
        max_size=6,
    )
)
def test_F2_AC4_property_every_decimal_in_every_row_round_trips_exactly(rows: list[tuple[Decimal, Decimal, Decimal, Decimal]]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "ledger"
        fills = [
            FillRecord(
                time=Timestamp(T0 + i, TimeSource.DERIVED), coin="BTC", side="buy", qty=Qty(q), price=Price(p),
                fee=Fee(f), funding=Funding(fu), client_order_id=f"c{i}", trade_id="t", share_id="s", exit_reason=None,
            )
            for i, (q, p, f, fu) in enumerate(rows)
        ]
        with Ledger.open(directory, clock=FakeClock()) as ledger:
            _write_fills(ledger, fills)
        count, table, _ = _export(directory)
        assert count == len(fills)
        for fill, row in zip(fills, table[1:], strict=True):
            cells = dict(zip(HEADER, row, strict=True))
            assert (Decimal(cells["qty"]), Decimal(cells["price"]), Decimal(cells["fee"]), Decimal(cells["funding"])) == (
                fill.qty, fill.price, fill.fee, fill.funding
            )
            assert not any("e" in cells[k].lower() for k in ("qty", "price", "fee", "funding"))


def test_F2_AC4_fill_validation() -> None:
    good = make_fill(1)
    from dataclasses import replace

    for change in ({"side": "long"}, {"side": ""}, {"qty": Qty("0")}, {"qty": Qty("-1")}, {"coin": ""}, {"client_order_id": ""},
                   {"trade_id": ""}, {"share_id": ""}):
        with pytest.raises(ValueError):
            replace(good, **change)


# --- AC5 ---------------------------------------------------------------------------------------------

def test_F2_AC5_aggregate_signature_has_no_parameter_that_could_exclude_records() -> None:
    params = list(inspect.signature(aggregate_trades).parameters)
    assert params == ["directory"]


def test_F2_AC5_totals_include_losers_and_every_flagged_kind(ledger: Ledger, ledger_dir: Path) -> None:
    pnls = ["125.50", "-310.25", "0", "-0.01", "42.10", "-1000", "0.005", "7", "-3.333"]
    flagsets = [frozenset(), frozenset(), frozenset(), frozenset({"reconstructed"}), frozenset({"unreconstructable"}),
                frozenset({"delisted_force_settle"}), frozenset({"liquidated"}), frozenset({"marked", "manual_flatten"}),
                frozenset(REQUIRED_TRADE_FLAGS)]
    for i, (pnl, flags) in enumerate(zip(pnls, flagsets, strict=True)):
        ledger.append_trade(make_trade(i, pnl, flags))
    hand_total = Decimal("125.50") + Decimal("-310.25") + Decimal("0") + Decimal("-0.01") + Decimal("42.10") \
        + Decimal("-1000") + Decimal("0.005") + Decimal("7") + Decimal("-3.333")
    assert hand_total == Decimal("-1138.988")
    aggregate = aggregate_trades(ledger_dir)
    assert aggregate == TradeAggregate(trade_count=9, total_pnl_usd=Pnl("-1138.988"))
    assert isinstance(aggregate.total_pnl_usd, Decimal)


@pytest.mark.parametrize("flag", REQUIRED_TRADE_FLAGS)
def test_F2_AC5_each_flag_alone_is_counted(ledger: Ledger, ledger_dir: Path, flag: str) -> None:
    ledger.append_trade(make_trade(1, "-5", frozenset({flag})))
    ledger.append_trade(make_trade(2, "8"))
    assert aggregate_trades(ledger_dir) == TradeAggregate(2, Pnl("3"))


def test_F2_AC5_empty_ledger_aggregates_to_zero(ledger: Ledger, ledger_dir: Path) -> None:
    ledger.append("note", {"a": 1})
    assert aggregate_trades(ledger_dir) == TradeAggregate(0, Pnl("0"))


def test_F2_AC5_only_trade_records_are_aggregated(ledger: Ledger, ledger_dir: Path) -> None:
    ledger.append_trade(make_trade(1, "10"))
    ledger.append_fill(make_fill(1))
    ledger.append_decision(make_decision(1))
    ledger.append("trade_note", {"pnl_usd": Decimal("999")})
    assert aggregate_trades(ledger_dir) == TradeAggregate(1, Pnl("10"))


def test_F2_AC5_aggregate_is_exact_where_binary_float_would_drift(ledger: Ledger, ledger_dir: Path) -> None:
    for i in range(10):
        ledger.append_trade(make_trade(i, "0.1"))
    assert aggregate_trades(ledger_dir).total_pnl_usd == Decimal("1.0")


def test_F2_AC5_unknown_flag_is_refused_rather_than_creating_a_hidden_category() -> None:
    with pytest.raises(ValueError):
        make_trade(1, "1", frozenset({"cherry_picked"}))


def test_F2_AC5_aggregating_a_tampered_ledger_raises(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    with Ledger.open(directory, clock=FakeClock()) as ledger:
        for i in range(3):
            ledger.append_trade(make_trade(i, "1"))
    flip_byte(directory, line_span(directory, 2)[0] + 25)
    with pytest.raises(LedgerCorruptError):
        aggregate_trades(directory)


@settings(max_examples=40)
@given(
    trades=st.lists(
        st.tuples(
            st.decimals(min_value=Decimal("-100000"), max_value=Decimal("100000"), places=6, allow_nan=False, allow_infinity=False),
            st.sets(st.sampled_from(REQUIRED_TRADE_FLAGS)),
        ),
        max_size=12,
    )
)
def test_F2_AC5_property_aggregate_equals_the_plain_sum_over_all_trades_whatever_their_flags(
    trades: list[tuple[Decimal, set[str]]],
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "ledger"
        with Ledger.open(directory, clock=FakeClock()) as ledger:
            for i, (pnl, flags) in enumerate(trades):
                ledger.append_trade(make_trade(i, str(pnl), frozenset(flags)))
        aggregate = aggregate_trades(directory)
        assert aggregate.trade_count == len(trades)
        assert aggregate.total_pnl_usd == sum((p for p, _ in trades), Decimal(0))
