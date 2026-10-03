"""R1b.AC3 [integration]: while the exchange clock has never been estimated the position manager logs ONE short line
without a traceback (not the alarming ``ClockUnsyncedError`` traceback of every read), once per distinct reason until
it clears, and nothing else changes: entries stay refused and the loop carries on (no exception reaches the caller).
Any OTHER clock failure keeps its traceback (the diagnostic is not weakened). Real manager over the F12 rig."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from copytrade.core.errors import ClockUnsyncedError
from tests.positions.conftest import NewRig

MANAGER_LOGGER = "copytrade.positions.manager"


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == MANAGER_LOGGER and r.levelno >= logging.INFO]


def _clock_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in _records(caplog) if "clock" in r.getMessage().lower() or "time" in r.getMessage().lower()]


def test_R1b_AC3_an_unsynced_clock_logs_one_line_without_a_traceback(
    new_rig: NewRig, caplog: pytest.LogCaptureFixture
) -> None:
    rig: Any = new_rig()
    rig.xtime.unsynced = True
    with caplog.at_level(logging.INFO, logger=MANAGER_LOGGER):
        rig.mgr.reconcile()  # must not raise
    (rec,) = _clock_lines(caplog)
    assert rec.levelno in (logging.INFO, logging.WARNING)
    assert rec.exc_info is None and not rec.exc_text
    assert "not available yet" in rec.getMessage() and "entries refused" in rec.getMessage()
    assert "Traceback" not in rec.getMessage()


def test_R1b_AC3_the_same_reason_is_not_repeated_on_every_read(new_rig: NewRig, caplog: pytest.LogCaptureFixture) -> None:
    rig: Any = new_rig()
    rig.xtime.unsynced = True
    with caplog.at_level(logging.INFO, logger=MANAGER_LOGGER):
        for _ in range(25):
            rig.mgr.reconcile()
    assert len(_clock_lines(caplog)) == 1
    assert not [r for r in caplog.records if r.exc_info]  # no traceback anywhere meanwhile


def test_R1b_AC3_the_line_comes_back_after_the_clock_cleared_and_failed_again(
    new_rig: NewRig, caplog: pytest.LogCaptureFixture
) -> None:
    rig: Any = new_rig()
    with caplog.at_level(logging.INFO, logger=MANAGER_LOGGER):
        rig.xtime.unsynced = True
        rig.mgr.reconcile()
        rig.mgr.reconcile()
        rig.xtime.unsynced = False
        rig.mgr.reconcile()  # the clock works again: clears
        rig.xtime.unsynced = True
        rig.mgr.reconcile()
        rig.mgr.reconcile()
    assert len(_clock_lines(caplog)) == 2


def test_R1b_AC3_a_different_unsync_reason_is_logged_once_more(new_rig: NewRig, caplog: pytest.LogCaptureFixture) -> None:
    rig: Any = new_rig()
    reasons = ["the exchange clock is unsynced", "the guarded exchange clock is not available"]
    state = {"i": 0}

    def exchange_now() -> Any:
        raise ClockUnsyncedError(reasons[state["i"]])

    rig.xtime.exchange_now = exchange_now
    with caplog.at_level(logging.INFO, logger=MANAGER_LOGGER):
        rig.mgr.reconcile()
        rig.mgr.reconcile()
        state["i"] = 1
        rig.mgr.reconcile()
        rig.mgr.reconcile()
    lines = _clock_lines(caplog)
    assert len(lines) == 2
    assert all(r.exc_info is None for r in lines)


def test_R1b_AC3_the_loop_still_runs_and_exits_are_unaffected_while_unsynced(new_rig: NewRig) -> None:
    rig: Any = new_rig()
    rig.xtime.unsynced = True
    rig.mgr.reconcile()
    # entries are refused by the gate (existing behaviour): the unsynced gate gives no exchange time
    assert rig.gate._read_exchange_ms() is None


def test_R1b_AC3_any_other_clock_failure_keeps_its_traceback(new_rig: NewRig, caplog: pytest.LogCaptureFixture) -> None:
    rig: Any = new_rig()

    def exchange_now() -> Any:
        raise RuntimeError("boom")

    rig.xtime.exchange_now = exchange_now
    with caplog.at_level(logging.INFO, logger=MANAGER_LOGGER):
        rig.mgr.reconcile()
    failures = [r for r in caplog.records if r.name == MANAGER_LOGGER and r.exc_info]
    assert failures
    exc_info = failures[0].exc_info
    assert exc_info is not None and exc_info[0] is RuntimeError
