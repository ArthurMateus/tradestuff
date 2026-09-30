"""F2.AC1: tamper evidence. Strictly increasing sequence, hash chain h_n = sha256(h_{n-1} || canonical_bytes(record_n)),
no update or delete in the API, and any single altered byte fails verification at that record's sequence
number, makes the engine refuse to start (``Ledger.open`` raises) and writes an alert to the local log.

Spec: 04-spec.md F2.AC1, invariant B5, A2.
"""

from __future__ import annotations

import logging
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.ledger.errors import LedgerCorruptError
from copytrade.ledger.records import GENESIS_HASH, LedgerRecord, canonical_bytes
from copytrade.ledger.store import Ledger, read_records, verify_ledger
from tests.ledger.helpers import (
    T0,
    FakeClock,
    expected_hash,
    flip_byte,
    ledger_file,
    line_span,
    raw_lines,
)

pytestmark = pytest.mark.unit


def _fill(ledger: Ledger, n: int) -> list[LedgerRecord]:
    return [ledger.append("note", {"n": n_i, "text": f"record {n_i}"}) for n_i in range(n)]


# --- chain shape -------------------------------------------------------------------------------------

def test_F2_AC1_sequence_is_strictly_increasing_from_one(ledger: Ledger) -> None:
    records = _fill(ledger, 5)
    assert [r.seq for r in records] == [1, 2, 3, 4, 5]
    assert [r.seq for r in ledger.records()] == [1, 2, 3, 4, 5]
    assert ledger.last_seq == 5


def test_F2_AC1_empty_ledger_is_valid_with_zero_records(ledger: Ledger, ledger_dir: Path) -> None:
    assert ledger.last_seq == 0
    assert list(ledger.records()) == []
    result = verify_ledger(ledger_dir)
    assert result.ok and result.record_count == 0 and result.failed_seq is None


def test_F2_AC1_hash_chain_follows_the_spec_formula(ledger: Ledger) -> None:
    records = _fill(ledger, 6)
    prev = GENESIS_HASH
    for record in records:
        assert len(record.hash) == 64 and record.hash == record.hash.lower()
        assert record.hash == expected_hash(prev, canonical_bytes(record))
        prev = record.hash


def test_F2_AC1_records_read_back_equal_the_records_returned_by_append(ledger: Ledger) -> None:
    written = _fill(ledger, 4)
    assert list(ledger.records()) == written


def test_F2_AC1_timestamp_is_the_injected_local_clock_with_a_local_source(ledger: Ledger, clock: FakeClock) -> None:
    clock.now = T0 + 777
    record = ledger.append("note", {"a": 1})
    assert record.ts == Timestamp(T0 + 777, TimeSource.LOCAL)


def test_F2_AC1_a_backwards_clock_never_breaks_the_sequence(ledger: Ledger, clock: FakeClock, ledger_dir: Path) -> None:
    ledger.append("note", {"a": 1})
    clock.now -= 60_000
    second = ledger.append("note", {"a": 2})
    assert second.seq == 2 and second.ts.ms == T0 - 60_000
    assert verify_ledger(ledger_dir).ok


def test_F2_AC1_the_api_offers_no_update_or_delete() -> None:
    public = {name for name in dir(Ledger) if not name.startswith("_")}
    forbidden = ("update", "delete", "remove", "edit", "modify", "rewrite", "truncate", "overwrite", "pop", "clear", "insert")
    offenders = sorted(n for n in public if any(word in n.lower() for word in forbidden))
    assert offenders == []
    assert {"append", "append_decision", "append_fill", "append_trade"} <= public


def test_F2_AC1_chain_survives_close_and_reopen(ledger_dir: Path, clock: FakeClock) -> None:
    with Ledger.open(ledger_dir, clock=clock) as first:
        before = _fill(first, 3)
    with Ledger.open(ledger_dir, clock=clock) as second:
        assert second.last_seq == 3
        after = second.append("note", {"n": 99})
        assert after.seq == 4
        assert after.hash == expected_hash(before[-1].hash, canonical_bytes(after))
        assert second.verify().ok


def test_F2_AC1_verify_is_read_only_and_idempotent(ledger: Ledger, ledger_dir: Path) -> None:
    _fill(ledger, 3)
    snapshot = ledger_file(ledger_dir).read_bytes()
    assert verify_ledger(ledger_dir) == verify_ledger(ledger_dir) == ledger.verify()
    assert ledger_file(ledger_dir).read_bytes() == snapshot


# --- canonical bytes ---------------------------------------------------------------------------------

def _record(seq: int = 1, kind: str = "note", payload: dict[str, Any] | None = None, ms: int = T0) -> LedgerRecord:
    return LedgerRecord(seq=seq, ts=Timestamp(ms, TimeSource.LOCAL), kind=kind, payload=payload or {"a": 1, "b": 2}, hash="")


def test_F2_AC1_canonical_bytes_ignore_dict_key_order_and_the_hash_field() -> None:
    a = _record(payload={"a": 1, "b": {"x": 1, "y": 2}})
    b = LedgerRecord(seq=1, ts=a.ts, kind="note", payload={"b": {"y": 2, "x": 1}, "a": 1}, hash="ff" * 32)
    assert canonical_bytes(a) == canonical_bytes(b)


@pytest.mark.parametrize(
    "changed",
    [
        _record(seq=2),
        _record(kind="other"),
        _record(payload={"a": 1, "b": 3}),
        _record(payload={"a": 1}),
        _record(ms=T0 + 1),
        LedgerRecord(seq=1, ts=Timestamp(T0, TimeSource.EXCHANGE), kind="note", payload={"a": 1, "b": 2}, hash=""),
    ],
    ids=["seq", "kind", "payload_value", "payload_key", "ts_ms", "ts_source"],
)
def test_F2_AC1_canonical_bytes_change_when_any_covered_field_changes(changed: LedgerRecord) -> None:
    assert canonical_bytes(changed) != canonical_bytes(_record())


def test_F2_AC1_canonical_bytes_distinguish_decimal_from_string_and_int() -> None:
    forms = [{"v": Decimal("1")}, {"v": "1"}, {"v": 1}, {"v": Decimal("1.0")}]
    encoded = {canonical_bytes(_record(payload=p)) for p in forms}
    assert len(encoded) == 4


# --- tamper detection --------------------------------------------------------------------------------

def _tamper_fixture(directory: Path, clock: FakeClock, n: int = 5) -> None:
    with Ledger.open(directory, clock=clock) as ledger:
        _fill(ledger, n)


@pytest.mark.parametrize("target", [1, 3, 5], ids=["first", "middle", "last"])
def test_F2_AC1_every_byte_of_a_record_is_covered(ledger_dir: Path, clock: FakeClock, target: int) -> None:
    _tamper_fixture(ledger_dir, clock)
    pristine = ledger_file(ledger_dir).read_bytes()
    start, end = line_span(ledger_dir, target)
    if target == 5:
        end -= 1  # the final newline of the file is indistinguishable from a torn write; see the test plan
    missed: list[int] = []
    for offset in range(start, end):
        flip_byte(ledger_dir, offset)
        result = verify_ledger(ledger_dir)
        if result.ok or result.failed_seq != target:
            missed.append(offset - start)
        ledger_file(ledger_dir).write_bytes(pristine)
    assert missed == []


def test_F2_AC1_altered_byte_names_the_sequence_number_engine_refuses_to_start_and_logs_an_alert(
    ledger_dir: Path, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    _tamper_fixture(ledger_dir, clock)
    start, _ = line_span(ledger_dir, 3)
    flip_byte(ledger_dir, start + 20)
    result = verify_ledger(ledger_dir)
    assert (result.ok, result.failed_seq) == (False, 3)
    assert result.reason
    with caplog.at_level(logging.DEBUG), pytest.raises(LedgerCorruptError) as caught:
        Ledger.open(ledger_dir, clock=clock)
    assert caught.value.seq == 3
    assert "3" in str(caught.value)
    alerts = [r for r in caplog.records if r.name.startswith("copytrade.ledger") and r.levelno >= logging.ERROR]
    assert alerts and any("3" in r.getMessage() for r in alerts)


def test_F2_AC1_corruption_never_lets_a_writer_append(ledger_dir: Path, clock: FakeClock) -> None:
    _tamper_fixture(ledger_dir, clock)
    flip_byte(ledger_dir, line_span(ledger_dir, 2)[0] + 5)
    damaged = ledger_file(ledger_dir).read_bytes()
    with pytest.raises(LedgerCorruptError):
        Ledger.open(ledger_dir, clock=clock)
    assert ledger_file(ledger_dir).read_bytes() == damaged  # not repaired, not extended


def test_F2_AC1_a_deleted_middle_record_is_detected_at_the_next_record(ledger_dir: Path, clock: FakeClock) -> None:
    _tamper_fixture(ledger_dir, clock)
    lines = raw_lines(ledger_dir)
    ledger_file(ledger_dir).write_bytes(b"".join(lines[:2] + lines[3:]))
    result = verify_ledger(ledger_dir)
    assert (result.ok, result.failed_seq) == (False, 3)


def test_F2_AC1_two_swapped_records_are_detected_at_the_first_of_them(ledger_dir: Path, clock: FakeClock) -> None:
    _tamper_fixture(ledger_dir, clock)
    lines = raw_lines(ledger_dir)
    lines[1], lines[2] = lines[2], lines[1]
    ledger_file(ledger_dir).write_bytes(b"".join(lines))
    assert verify_ledger(ledger_dir).failed_seq == 2


def test_F2_AC1_a_replayed_duplicate_line_is_detected(ledger_dir: Path, clock: FakeClock) -> None:
    _tamper_fixture(ledger_dir, clock)
    lines = raw_lines(ledger_dir)
    ledger_file(ledger_dir).write_bytes(b"".join(lines + [lines[-1]]))
    assert verify_ledger(ledger_dir).failed_seq == 6


def test_F2_AC1_a_terminated_garbage_line_is_corruption_not_a_torn_write(ledger_dir: Path, clock: FakeClock) -> None:
    _tamper_fixture(ledger_dir, clock, 3)
    with ledger_file(ledger_dir).open("ab") as fh:
        fh.write(b"not a record\n")
    assert verify_ledger(ledger_dir).failed_seq == 4
    with pytest.raises(LedgerCorruptError) as caught:
        Ledger.open(ledger_dir, clock=clock)
    assert caught.value.seq == 4


def test_F2_AC1_invalid_utf8_and_binary_noise_fail_verification_without_raising(ledger_dir: Path, clock: FakeClock) -> None:
    _tamper_fixture(ledger_dir, clock, 3)
    start, _ = line_span(ledger_dir, 2)
    path = ledger_file(ledger_dir)
    data = bytearray(path.read_bytes())
    data[start + 10 : start + 12] = b"\xff\xfe"
    path.write_bytes(bytes(data))
    result = verify_ledger(ledger_dir)
    assert (result.ok, result.failed_seq) == (False, 2)


def test_F2_AC1_read_records_stops_at_the_corrupt_record(ledger_dir: Path, clock: FakeClock) -> None:
    _tamper_fixture(ledger_dir, clock)
    flip_byte(ledger_dir, line_span(ledger_dir, 4)[0] + 15)
    seen: list[int] = []
    with pytest.raises(LedgerCorruptError) as caught:
        for record in read_records(ledger_dir):
            seen.append(record.seq)
    assert seen == [1, 2, 3] and caught.value.seq == 4


# --- property tests ----------------------------------------------------------------------------------

_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**30), max_value=10**30),
    st.text(),
    st.decimals(allow_nan=False, allow_infinity=False, places=8),
)
_PAYLOADS = st.dictionaries(st.text(min_size=1, max_size=8), st.recursive(_SCALARS, lambda c: st.lists(c, max_size=3), max_leaves=6), max_size=5)


@settings(max_examples=40)
@given(payloads=st.lists(_PAYLOADS, min_size=1, max_size=8))
def test_F2_AC1_property_any_payload_sequence_chains_verifies_and_round_trips(payloads: list[dict[str, Any]]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "ledger"
        with Ledger.open(directory, clock=FakeClock()) as ledger:
            written = [ledger.append("note", p) for p in payloads]
            prev = GENESIS_HASH
            for rec in written:
                assert rec.hash == expected_hash(prev, canonical_bytes(rec))
                prev = rec.hash
            assert [dict(r.payload) for r in ledger.records()] == payloads
        result = verify_ledger(directory)
        assert result.ok and result.record_count == len(payloads)


@settings(max_examples=40)
@given(payloads=st.lists(_PAYLOADS, min_size=2, max_size=6), data=st.data())
def test_F2_AC1_property_flipping_any_single_byte_fails_at_that_records_sequence_number(
    payloads: list[dict[str, Any]], data: st.DataObject
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "ledger"
        with Ledger.open(directory, clock=FakeClock()) as ledger:
            for p in payloads:
                ledger.append("note", p)
        target = data.draw(st.integers(min_value=1, max_value=len(payloads)))
        start, end = line_span(directory, target)
        if target == len(payloads):
            end -= 1
        offset = data.draw(st.integers(min_value=start, max_value=end - 1))
        flip_byte(directory, offset)
        result = verify_ledger(directory)
        assert not result.ok and result.failed_seq == target
