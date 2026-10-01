"""Incremental reader of the ledger file: the records appended since the last call."""

from __future__ import annotations

from pathlib import Path

from copytrade.ledger.records import LedgerRecord, decode_line
from copytrade.ledger.store import LEDGER_FILENAME


class LedgerTail:
    """Reads the complete lines appended to ``<directory>/ledger.jsonl`` after ``offset`` bytes. The ledger is written
    by this process only (it holds the writer lock), so the lines are not verified again; an unterminated last line is
    left for the next call."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / LEDGER_FILENAME
        self._offset = self._path.stat().st_size if self._path.exists() else 0

    def poll(self) -> list[LedgerRecord]:
        try:
            with self._path.open("rb") as handle:
                handle.seek(self._offset)
                data = handle.read()
        except FileNotFoundError:
            return []
        complete = data[: data.rfind(b"\n") + 1]
        self._offset += len(complete)
        return [decode_line(line) for line in complete.splitlines()]
