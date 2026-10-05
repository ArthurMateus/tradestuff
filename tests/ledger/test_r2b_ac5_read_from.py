"""R2b.AC5 (R2-SD2 / RISK-79b, blocking): ``Ledger.read_from`` and a partial or bad line.

* An unterminated last line (a partial append, e.g. a crash mid-write or a reader racing the writer) yields nothing for it
  and the returned offset stays BEFORE it; once the line is completed the next call returns the full record exactly once.
* A line that cannot be decoded is logged and skipped: it is never fatal (a decode error used to block the Telegram posts
  for good) and the records after it are still returned, in order.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from copytrade.ledger.store import LEDGER_FILENAME

pytestmark = pytest.mark.unit


def _seqs(records: list) -> list[int]:  # type: ignore[type-arg]
    return [r.payload["i"] for r in records]


def test_R2b_AC5_an_unterminated_last_line_returns_nothing_and_the_completed_line_exactly_once(ledger) -> None:  # type: ignore[no-untyped-def]
    path: Path = ledger._directory / LEDGER_FILENAME  # noqa: SLF001
    ledger.append("probe", {"i": 1})
    records, offset = ledger.read_from(0)
    assert _seqs([r for r in records if r.kind == "probe"]) == [1]
    ledger.append("probe", {"i": 2})
    full = path.read_bytes()
    start = full.rfind(b"\n", 0, len(full) - 1) + 1  # the start of record 2's line
    cut = start + (len(full) - start) // 2
    path.write_bytes(full[:cut])  # the crash: half of record 2's line is on disk
    partial, same_offset = ledger.read_from(offset)
    assert partial == [], "an unterminated last line must yield nothing"
    assert same_offset == offset, "the offset must stay before the unterminated line"
    path.write_bytes(full)  # the rest of the line arrives
    completed, new_offset = ledger.read_from(same_offset)
    assert _seqs(completed) == [2], "the completed record is returned in full, exactly once"
    again, final_offset = ledger.read_from(new_offset)
    assert again == [] and final_offset == new_offset


def test_R2b_AC5_a_bad_line_is_logged_and_skipped_and_the_records_after_it_are_returned(  # type: ignore[no-untyped-def]
    ledger, caplog: pytest.LogCaptureFixture
) -> None:
    path: Path = ledger._directory / LEDGER_FILENAME  # noqa: SLF001
    ledger.append("probe", {"i": 1})
    _, offset = ledger.read_from(0)
    with path.open("ab") as handle:
        handle.write(b'{"this is not": a record\n')
        handle.write(b"\xff\xfe\x00 undecodable bytes\n")
    ledger.append("probe", {"i": 3})
    with caplog.at_level(logging.WARNING):
        records, new_offset = ledger.read_from(offset)  # must not raise
    assert _seqs([r for r in records if r.kind == "probe"]) == [3]
    assert any(r.levelno >= logging.WARNING for r in caplog.records), "a skipped bad line must be logged"
    assert new_offset == path.stat().st_size, "the offset moves past the bad lines (they are not re-read forever)"
    assert ledger.read_from(new_offset) == ([], new_offset)


def test_R2b_AC5_a_bad_line_with_a_kinds_filter_is_still_skipped_not_fatal(ledger) -> None:  # type: ignore[no-untyped-def]
    path: Path = ledger._directory / LEDGER_FILENAME  # noqa: SLF001
    _, offset = ledger.read_from(0)
    with path.open("ab") as handle:
        handle.write(b'{"kind":"probe", broken\n')
    ledger.append("probe", {"i": 7})
    records, _ = ledger.read_from(offset, kinds=frozenset({"probe"}))
    assert _seqs(records) == [7]
