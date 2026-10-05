"""F4.AC6 [simulation]: recording is independent of trading state. Only the disk floor stops it (F4.AC5).

The full simulation (a real ``/pause``, kill switch, loss halt and ``access_degraded`` in a paper run) belongs to
F21 and /qa. What can be proved here: the recorder package has no path to trading state, and ledgered trading-state
records change nothing about what is recorded.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from pathlib import Path

import pytest

import copytrade.recorder as recorder_pkg
from copytrade.recorder.records import STREAM_ASSET_CTX, STREAM_L2, STREAM_LEADERBOARD, STREAM_MIDS
from copytrade.recorder.service import Recorder
from tests.recorder.helpers import DAY, DAY0, SECOND, Rig, book

pytestmark = pytest.mark.integration

FORBIDDEN = ("risk", "paper", "positions", "filters", "selection", "telegram", "signals", "reports", "evaluation")


def test_F4_AC6_the_recorder_package_imports_no_trading_module() -> None:
    root = Path(recorder_pkg.__file__).parent
    offenders = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN:
            if re.search(rf"^\s*(from|import)\s+copytrade\.{name}\b", text, re.M):
                offenders.append((path.name, name))
    assert offenders == []


def test_F4_AC6_the_recorder_takes_no_trading_state_as_an_input() -> None:
    params = set(inspect.signature(Recorder.__init__).parameters)
    assert not {p for p in params if re.search(r"pause|kill|halt|access|risk|trading|mode", p)}


def counts(rig: Rig) -> dict[str, int]:
    rig.recorder.shutdown()
    span = (DAY0, DAY0 + DAY)
    return {
        "l2": len(list(rig.store.scan(STREAM_L2, "BTC", *span))),
        "mids": len(list(rig.store.scan(STREAM_MIDS, None, *span))),
        "ctx": len(list(rig.store.scan(STREAM_ASSET_CTX, "BTC", *span))),
        "board": len(list(rig.store.scan(STREAM_LEADERBOARD, None, *span))),
    }


def drive(rig: Rig, *, trading_state_records: bool) -> dict[str, int]:
    rig.feed.generator = lambda now: [book("BTC", now - 30)] if (now - DAY0) % 2000 == 0 else []
    rig.run(1)
    if trading_state_records:
        for kind in ("pause", "killswitch", "loss_halt", "access_degraded", "leader_paused", "run_aborted"):
            rig.ledger.append(kind, {"active": True})
    rig.run(2 * 3600)
    return counts(rig)


def test_F4_AC6_pause_kill_switch_loss_halt_and_access_degraded_records_change_nothing_about_recording(
    rig_factory: Callable[..., Rig],
) -> None:
    quiet = drive(rig_factory(), trading_state_records=False)
    busy = drive(rig_factory(), trading_state_records=True)
    assert busy == quiet
    assert quiet["l2"] >= 3600 and quiet["ctx"] >= 100 and quiet["board"] >= 2
    assert SECOND == 1000
