"""Round 2: exact aggregates, domain errors for pathological Decimals, rollback of a failed append, the
BaseException latch, a zero-byte ``os.write`` and out-of-range CLI instants.

Spec: 04-spec.md F2.AC3, F2.AC4, F2.AC5, F2.AC6, invariants A2, A5, A6.
"""

from __future__ import annotations

import csv
import errno
import io
import os
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.money import Qty
from copytrade.ledger.errors import LedgerError, LedgerWriteError
from copytrade.ledger.export import aggregate_trades, export_fills
from copytrade.ledger.store import Ledger, read_records, verify_ledger
from tests.core.helpers import run_cli
from tests.ledger.helpers import T0, FakeClock, ledger_file, make_fill, make_trade

# ---- aggregate exactness (F2.AC5, A6) ---------------------------------------------------------------------


def _trades_dir(directory: Path, values: list[Decimal]) -> None:
    with Ledger.open(directory, clock=FakeClock()) as ledger:
        for i, value in enumerate(values):
            ledger.append_trade(make_trade(i, str(value)))


def test_F2_AC5_a_sum_needing_more_than_28_significant_digits_is_exact(ledger_dir: Path) -> None:
    values = [Decimal("9999999999999999999999999999999999"), Decimal("1"), Decimal("0.0000000000000000000000000001")]
    _trades_dir(ledger_dir, values)
    total = aggregate_trades(ledger_dir).total_pnl_usd
    assert Fraction(total) == sum(Fraction(v) for v in values)
    assert total == Decimal("10000000000000000000000000000000000.0000000000000000000000000001")


def test_F2_AC5_a_tiny_loss_next_to_a_huge_gain_is_not_rounded_away(ledger_dir: Path) -> None:
    values = [Decimal("1E+40"), Decimal("-0.5"), Decimal("-1E+40"), Decimal("0.25")]
    _trades_dir(ledger_dir, values)
    assert aggregate_trades(ledger_dir).total_pnl_usd == Decimal("-0.25")


@settings(max_examples=40, deadline=None)
@given(st.lists(st.tuples(st.integers(-(10**40), 10**40), st.integers(0, 35)), min_size=1, max_size=8))
def test_F2_AC5_property_the_total_equals_the_exact_rational_sum(pairs: list[tuple[int, int]]) -> None:
    import tempfile

    values = [Decimal(n).scaleb(-scale) for n, scale in pairs]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "ledger"
        _trades_dir(directory, values)
        aggregate = aggregate_trades(directory)
    assert aggregate.trade_count == len(values)
    assert Fraction(aggregate.total_pnl_usd) == sum(Fraction(v) for v in values)


@pytest.mark.parametrize(
    "values",
    [
        [Decimal("1E+2000"), Decimal("1")],
        [Decimal("-1E+2000"), Decimal("1")],
        [Decimal("1E-2000"), Decimal("1E+2000")],
        [Decimal("9E+999999"), Decimal("9E+999999")],
        [Decimal("1E+999999"), Decimal("1E-999999")],
    ],
    ids=["huge+1", "-huge+1", "tiny+huge", "overflow", "span-wider-than-precision"],
)
def test_F2_AC5_pathological_decimals_give_a_domain_error_not_a_raw_decimal_exception(
    ledger_dir: Path, values: list[Decimal]
) -> None:
    _trades_dir(ledger_dir, values)
    try:
        result = aggregate_trades(ledger_dir)
    except LedgerError:
        return
    except ArithmeticError as exc:
        pytest.fail(f"a raw decimal exception leaked: {type(exc).__name__}")
    # A correct exact sum is also acceptable when it is representable.
    assert Fraction(result.total_pnl_usd) == sum(Fraction(v) for v in values)


@pytest.mark.parametrize("qty", ["1E+2000", "1E-2000", "123456789012345678901234567890.123456789012345678901234567890"])
def test_F2_AC4_export_of_a_pathological_decimal_is_exact_or_a_domain_error(ledger_dir: Path, qty: str) -> None:
    with Ledger.open(ledger_dir, clock=FakeClock()) as ledger:
        ledger.append_fill(replace(make_fill(0), qty=Qty(qty)))
    out = io.StringIO()
    try:
        export_fills(ledger_dir, from_ms=0, to_ms=T0 * 2, out=out)
    except LedgerError:
        assert out.getvalue() == ""
        return
    except ArithmeticError as exc:
        pytest.fail(f"a raw decimal exception leaked: {type(exc).__name__}")
    (row,) = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert Fraction(row["qty"]) == Fraction(Decimal(qty))


# ---- rollback of a failed append (F2.AC6, A5) ------------------------------------------------------------


def _fsync_failing(calls_to_fail: int, real: object = os.fsync):  # type: ignore[no-untyped-def]
    state = {"n": 0}

    def fsync(fd: int) -> None:
        state["n"] += 1
        if state["n"] <= calls_to_fail:
            raise OSError(errno.EIO, "I/O error")
        real(fd)  # type: ignore[operator]

    return fsync


@pytest.mark.parametrize("failing_calls", [1, 1000], ids=["rollback_fsync_ok", "rollback_fsync_also_fails"])
def test_F2_AC6_a_failed_append_is_rolled_back_so_a_reopen_sees_the_pre_failure_ledger(
    ledger_dir: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch, failing_calls: int
) -> None:
    ledger = Ledger.open(ledger_dir, clock=clock)
    ledger.append("order", {"n": 1}, client_order_id="keep-1")
    ledger.append("order", {"n": 2}, client_order_id="keep-2")
    before_size = ledger_file(ledger_dir).stat().st_size
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", _fsync_failing(failing_calls))
        with pytest.raises(LedgerWriteError):
            ledger.append("order", {"n": 3}, client_order_id="lost-3")
    assert ledger.failed
    assert not ledger.has_client_order_id("lost-3")
    ledger.close()

    assert ledger_file(ledger_dir).stat().st_size == before_size, "the failed line was left in the file"
    with Ledger.open(ledger_dir, clock=clock) as fresh:
        assert fresh.last_seq == 2
        assert fresh.has_client_order_id("keep-2")
        assert not fresh.has_client_order_id("lost-3")
        assert [r.client_order_id for r in fresh.records()] == ["keep-1", "keep-2"]
        again = fresh.append("order", {"n": 3}, client_order_id="lost-3")
        assert again.seq == 3
        assert fresh.verify().ok
    assert verify_ledger(ledger_dir).record_count == 3


def test_F2_AC6_a_partial_write_is_rolled_back(
    ledger_dir: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = Ledger.open(ledger_dir, clock=clock)
    ledger.append("order", {"n": 1}, client_order_id="keep-1")
    before_size = ledger_file(ledger_dir).stat().st_size
    real_write = os.write

    def half_then_fail(fd: int, data: bytes | memoryview) -> int:
        real_write(fd, bytes(data)[: len(data) // 2])
        raise OSError(errno.ENOSPC, "No space left on device")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", half_then_fail)
        with pytest.raises(LedgerWriteError):
            ledger.append("order", {"n": 2}, client_order_id="lost-2")
    ledger.close()
    assert ledger_file(ledger_dir).stat().st_size == before_size
    with Ledger.open(ledger_dir, clock=clock) as fresh:
        assert fresh.last_seq == 1
        fresh.append("order", {"n": 2}, client_order_id="lost-2")
        assert fresh.verify().ok


# ---- BaseException latch and zero-byte write -------------------------------------------------------------


@pytest.mark.parametrize("target", ["fsync", "write"])
def test_F2_AC6_a_base_exception_during_an_append_latches_the_ledger_failed(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    ledger.append("note", {"n": 1})

    def interrupted(*_: object) -> int:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(os, target, interrupted)
        with pytest.raises(KeyboardInterrupt):
            ledger.append("note", {"n": 2})
    assert ledger.failed
    with pytest.raises(LedgerWriteError):
        ledger.append("note", {"n": 3})
    with pytest.raises(LedgerWriteError):
        ledger.append_fill(make_fill(0))


def test_F2_AC6_a_zero_byte_write_is_an_error_not_an_endless_loop(
    ledger_dir: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = Ledger.open(ledger_dir, clock=clock)
    ledger.append("note", {"n": 1})
    before_size = ledger_file(ledger_dir).stat().st_size
    calls = {"n": 0}

    def stuck_write(fd: int, data: bytes | memoryview) -> int:
        calls["n"] += 1
        if calls["n"] > 100:  # a correct writer gives up long before this
            raise AssertionError("the writer keeps retrying a write that makes no progress")
        return 0

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", stuck_write)
        with pytest.raises(LedgerWriteError) as caught:
            ledger.append("note", {"n": 2})
    assert isinstance(caught.value.__cause__, OSError)
    assert ledger.failed
    ledger.close()
    assert ledger_file(ledger_dir).stat().st_size == before_size
    assert verify_ledger(ledger_dir).record_count == 1
    assert len(list(read_records(ledger_dir))) == 1


# ---- CLI: instants outside the representable range -------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    "flag,value",
    [
        ("--from", "0001-01-01T00:00:00+05:00"),
        ("--to", "0001-01-01T00:00:00+05:00"),
        ("--to", "9999-12-31T23:59:59-05:00"),
    ],
)
def test_F2_AC4_cli_export_with_an_out_of_range_instant_is_a_clean_argument_error(
    tmp_path: Path, flag: str, value: str
) -> None:
    directory = tmp_path / "ledger"
    with Ledger.open(directory, clock=FakeClock()) as ledger:
        ledger.append_fill(make_fill(0))
    other = ("--to", "2030-01-01T00:00:00Z") if flag == "--from" else ("--from", "2020-01-01T00:00:00Z")
    try:
        result = run_cli(["export", "fills", "--ledger-dir", str(directory), flag, value, *other])
    except Exception as exc:  # noqa: BLE001 - the point is that nothing but a clean exit may come out
        pytest.fail(f"the CLI raised {type(exc).__name__} instead of exiting with an argument error")
    assert result.code == 2
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
    assert "usage" in result.stderr.lower() or "error" in result.stderr.lower()


@pytest.mark.integration
def test_F2_AC4_cli_export_accepts_the_earliest_utc_instant(tmp_path: Path) -> None:
    directory = tmp_path / "ledger"
    with Ledger.open(directory, clock=FakeClock()) as ledger:
        ledger.append_fill(make_fill(0))
    result = run_cli(
        ["export", "fills", "--ledger-dir", str(directory), "--from", "0001-01-01T00:00:00Z", "--to", "2030-01-01T00:00:00Z"]
    )
    assert result.code == 0, result.stderr
    assert "coid-0" in result.stdout
