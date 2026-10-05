"""Subprocess workers for the crash-durability tests (F2.AC3, F2.AC6). Not a test module.

``python -m tests.ledger._worker replay DIR TOTAL``: opens the ledger, then for each signal i in range(TOTAL)
that has no ledger record yet, waits for a line on stdin, appends one ``order`` record with client order ID
``co-<i>`` and prints ``ack <i>``. Prints ``ready`` after opening and ``done`` at the end.

``python -m tests.ledger._worker fsize DIR LIMIT_BYTES``: caps the file size the OS allows this process to
write (a real disk-full analogue), appends until the ledger raises, and prints ``appended <k>`` then
``failed <bool>`` and ``refused <bool>``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from copytrade.core.clock import SystemClock
from copytrade.ledger.errors import LedgerWriteError
from copytrade.ledger.store import Ledger


def _replay(directory: Path, total: int) -> None:
    ledger = Ledger.open(directory, clock=SystemClock())
    print("ready", flush=True)
    for i in range(total):
        client_order_id = f"co-{i}"
        if ledger.has_client_order_id(client_order_id):
            continue
        sys.stdin.readline()
        ledger.append("order", {"signal": i}, client_order_id=client_order_id)
        print(f"ack {i}", flush=True)
    print("done", flush=True)


def _fsize(directory: Path, limit: int) -> None:
    import resource
    import signal

    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    ledger = Ledger.open(directory, clock=SystemClock())
    appended = 0
    try:
        while appended < 100_000:
            ledger.append("note", {"n": appended, "pad": "p" * 40})
            appended += 1
    except LedgerWriteError:
        print(f"appended {appended}", flush=True)
        print(f"failed {ledger.failed}", flush=True)
        try:
            ledger.append("note", {"after": "failure"})
        except LedgerWriteError:
            print("refused True", flush=True)
        else:
            print("refused False", flush=True)
    else:
        print("never failed", flush=True)


if __name__ == "__main__":
    mode, folder, number = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
    if mode == "replay":
        _replay(folder, number)
    else:
        _fsize(folder, number)
