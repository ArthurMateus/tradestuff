"""R3.AC8 [integration]: screen results are logged, one line per screened wallet, readable on the console.

Pinned format (the doc leaves it open; see the test plan): an INFO record (event ``candidate_screened``) whose MESSAGE
is key=value text: ``wallet=<address> outcome=ok|rejected failed=<ids ascending, comma separated | none>
not_evaluable=<ids | none>``. All nine rules are computed and logged even after the first failure (V5).
A cooled-down wallet is not screened, so it is not logged; a re-screen after its cooldown is a new line.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from copytrade.runner.logsetup import configure_logging
from tests.selection.helpers import w
from tests.selection.r3_world import (
    DAY,
    Tids,
    good_trips,
    make_r3,
    non_core,
    page_s1,
    page_s2,
    page_s3,
    page_s7,
    row,
    screen_lines,
    tokens,
    records,
    SCREEN_EVENT,
    verdict,
)


def combined_failures(t: int) -> list[dict[str, Any]]:
    """Fails S3 (core share 0.499), S4 (maker share 0.703) and S5 (first core fill 59 days back) at once."""
    tids = Tids()
    rows = good_trips(t, first_ago=59 * DAY, tids=tids, open_crossed=lambda k: False, close_crossed=lambda k: k >= 65)
    rows.append(non_core(tids, t - 40 * DAY, 642_000))
    return rows


def test_R3_AC8_every_screened_wallet_gets_one_line_with_its_failed_rules(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = make_r3(tmp_path)
    pages = {
        w(1): lambda t: good_trips(t),  # ok
        w(2): page_s1,  # S1
        w(3): lambda t: page_s2(t),  # S2 (and more)
        w(4): page_s3,  # S3 only
        w(5): page_s7,  # S7 only
        w(6): combined_failures,  # S3, S4, S5
    }
    for wallet, build in pages.items():
        r3.serve_at(wallet, build)
    r3.set_board([row(wallet, bps_m=10 + i, bps_p=10 + i) for i, wallet in enumerate(pages, start=1)])
    with caplog.at_level(logging.INFO):
        r3.cycle(80)
    lines = screen_lines(caplog)
    assert sorted(line["wallet"] for line in lines) == sorted(pages)  # exactly one per wallet
    by = {w_: verdict(caplog, w_) for w_ in pages}
    assert by[w(1)] == {"outcome": "ok", "failed": set(), "not_evaluable": {"S6"}}
    assert "S1" in by[w(2)]["failed"] and by[w(2)]["outcome"] == "rejected"
    assert "S2" in by[w(3)]["failed"]
    assert by[w(4)]["failed"] == {"S3"} and by[w(5)]["failed"] == {"S7"}
    assert by[w(6)]["failed"] == {"S3", "S4", "S5"}  # every failing rule, not only the first


def raw(caplog: pytest.LogCaptureFixture, wallet: str) -> dict[str, str]:
    lines = screen_lines(caplog, wallet)
    assert len(lines) == 1, f"expected one screen line for {wallet}, got {len(lines)}"
    return lines[0]


def test_R3_AC8_the_ids_are_written_ascending_comma_separated_and_none_when_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(w(1), combined_failures)
    r3.serve_at(w(2), lambda t: good_trips(t))
    r3.set_board([row(w(1), bps_m=20, bps_p=20), row(w(2), bps_m=30, bps_p=30)])
    with caplog.at_level(logging.INFO):
        r3.cycle(40)
    assert raw(caplog, w(1))["failed"] == "S3,S4,S5"
    assert raw(caplog, w(2))["failed"] == "none"
    assert raw(caplog, w(2))["not_evaluable"] == "S6"


def test_R3_AC8_the_line_is_at_info_or_above_and_has_the_event_name(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(w(1), page_s1)
    r3.set_board([row(w(1))])
    with caplog.at_level(logging.INFO):
        r3.cycle(20)
    recs = records(caplog, SCREEN_EVENT)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.levelno >= logging.INFO
    assert tokens(rec)["wallet"] == w(1)


def test_R3_AC8_a_wallet_in_cooldown_is_not_logged_again_and_a_rescreen_is(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(w(1), lambda t: page_s2(t))  # 24 h cooldown
    r3.set_board([row(w(1))])
    with caplog.at_level(logging.INFO):
        r3.cycle(20)
        r3.advance_h(2)
        r3.cycle(20)
        assert len(screen_lines(caplog, w(1))) == 1
        r3.advance_h(25)
        r3.cycle(20)
        assert len(screen_lines(caplog, w(1))) == 2


@pytest.fixture
def console_logging(tmp_path: Path) -> Iterator[Path]:
    """The runner's real console + file logging on the ``copytrade`` logger, put back after the test."""
    logger = logging.getLogger("copytrade")
    saved = (list(logger.handlers), logger.level)
    path = configure_logging(tmp_path / "logs")
    yield path
    for handler in list(logger.handlers):
        if handler not in saved[0]:
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(saved[1])


def test_R3_AC8_the_line_reads_on_the_console_with_the_failed_rules(tmp_path: Path, console_logging: Path) -> None:
    r3 = make_r3(tmp_path)
    r3.serve_at(w(1), combined_failures)
    r3.set_board([row(w(1))])
    r3.cycle(30)
    for handler in logging.getLogger("copytrade").handlers:
        handler.flush()
    text = console_logging.read_text(encoding="utf-8")
    mine = [line for line in text.splitlines() if f"wallet={w(1)}" in line and "failed=S3,S4,S5" in line]
    assert len(mine) == 1, text[-2000:]
    assert "outcome=rejected" in mine[0]
