"""Subprocess worker for the recorder crash tests (F4.AC7). Not a test module.

``python -m tests.recorder._worker steps BASE N``: opens ledger ``BASE/ledger`` and store ``BASE/recordings`` on a fake
clock that starts at 2026-09-22T00:00:00Z. Each stdin line ``a`` runs one step: ``tick``, append one BTC ``l2`` record
stamped with the current fake time, advance the clock by 1 s, print ``ack``. After the steps it keeps waiting for input
until it is killed.

``python -m tests.recorder._worker random BASE N``: the same, but the clock starts 10 minutes before midnight, each
step appends a BTC and an ETH record and advances 2 s, and every 97th step closes all files.
"""

from __future__ import annotations

import sys
from pathlib import Path

from copytrade.ledger.store import Ledger
from copytrade.recorder.store import RecordingStore
from tests.recorder.helpers import DAY, DAY0, HOUR, SECOND, FakeClock, cfg, l2_record


def main(mode: str, base: Path) -> None:
    clock = FakeClock(DAY0 if mode == "steps" else DAY0 + DAY - 600 * SECOND)
    ledger = Ledger.open(base / "ledger", clock=clock)
    store = RecordingStore(config=cfg(), clock=clock, ledger=ledger, recordings_dir=base / "recordings")
    print("ready", flush=True)
    step = 0
    for _ in sys.stdin:
        step += 1
        store.tick()
        t = clock.now_ms()
        store.append(l2_record("BTC", t, mid=100 + step % 7))
        if mode == "random":
            store.append(l2_record("ETH", t, mid=200 + step % 5))
            if step % 97 == 0:
                store.close_all("shutdown")
        clock.advance(SECOND if mode == "steps" else 2 * SECOND)
        print("ack", flush=True)
    assert HOUR  # keeps the import used


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
