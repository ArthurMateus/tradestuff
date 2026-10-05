"""R3.AC7 [integration]: progress visibility of the backfill pass (R2b.AC10 in reviews/R2-r1-batch.md).

The PO's console showed nothing for minutes while a pass worked through 50-200 candidates at about one wallet a minute.
Three kinds of INFO line, each as ``key=value`` text in the MESSAGE (the console prints the message):

- one per wallet when its backfill completes:
  ``backfill of a candidate complete: wallet=<address> fills=<N> pages=<P>`` (pages = fill pages requested, the screen
  page included); exactly once per wallet, later incremental refreshes do not repeat it;
- a progress line at most once per 60 s of the clock while the pass is incomplete:
  ``backfill progress: done=<X> of <Y> candidates, screened=<S>, screen_ok=<K>, screen_rejected=<R>, dropped=<D>,
  cooling=<C>, next retry in <N> s`` (S = K + R; the counters never go down within a pass; N is the seconds until the
  next attempt, > 0 while the pass waits for the rate budget);
- one ``backfill pass complete`` line when the pass finishes, and no progress line after it.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.hl.support import T0
from tests.selection.helpers import w
from tests.selection.r3_world import (
    HOUR,
    R3,
    Tids,
    fill,
    make_r3,
    ok_page,
    page_ok_full,
    page_s2,
    ranked_rows,
    stamped,
)

DONE = r"backfill of a candidate complete: wallet=(\S+) fills=(\d+) pages=(\d+)"
PROGRESS = (
    r"backfill progress: done=(\d+) of (\d+) candidates, screened=(\d+), screen_ok=(\d+), screen_rejected=(\d+), "
    r"dropped=(\d+), cooling=(\d+), next retry in (\d+) s"
)
PASS_DONE = r"backfill pass complete"
GOOD = [w(i) for i in range(1, 13)]
HEAVY = [w(i) for i in range(13, 31)]


def mixed_world(tmp_path: Path) -> R3:
    """12 wallets that pass the screen and 18 too active ones (each screen weighs 120): about 8 minutes of budget."""
    r3 = make_r3(tmp_path)
    for wallet in GOOD:
        r3.serve(wallet, ok_page(T0))
    for wallet in HEAVY:
        r3.serve_at(wallet, lambda t: page_s2(t))
    r3.set_board(ranked_rows(30))
    return r3


def test_R3_AC7_one_line_per_wallet_when_its_backfill_completes(tmp_path: Path) -> None:
    r3 = mixed_world(tmp_path)
    with stamped(r3) as log:
        r3.cycle()
        r3.drive_until_complete(max_ticks=600)
        r3.drive(60)  # incremental refreshes of the finished wallets follow: they are not backfills
        lines = [re.fullmatch(DONE, message) for _t, message in log.lines(r"backfill of a candidate complete")]
    assert all(lines), "the line must read exactly: backfill of a candidate complete: wallet=... fills=N pages=P"
    got = {m.group(1): (int(m.group(2)), int(m.group(3))) for m in lines if m}
    assert len(lines) == len(got) == 12  # once per OK wallet, none for the rejected ones
    assert set(got) == set(GOOD)
    assert set(got.values()) == {(320, 1)}  # the screen page was the whole backfill


def test_R3_AC7_the_line_counts_the_pages_of_a_wallet_with_a_long_history(tmp_path: Path) -> None:
    r3 = make_r3(tmp_path)
    page1 = page_ok_full(T0)
    last = max(r["time"] for r in page1)
    tids = Tids(1_000_000)
    later = [fill("@107", "B", "0.000001", "2000", last + HOUR * (k + 1), "0.0", tids, direction="Buy") for k in range(2_300)]
    r3.serve(w(1), [*page1, *later])
    r3.set_board(ranked_rows(1))
    with stamped(r3) as log:
        r3.cycle()
        r3.drive_until_complete(max_ticks=100)
        lines = log.lines(r"backfill of a candidate complete")
    assert len(lines) == 1
    m = re.fullmatch(DONE, lines[0][1])
    assert m is not None and m.group(1) == w(1)
    assert (int(m.group(2)), int(m.group(3))) == (4300, 3)  # 2 000 + 2 000 + 300 fills in 3 pages


def test_R3_AC7_progress_lines_come_at_most_once_a_minute_while_the_pass_is_incomplete(tmp_path: Path) -> None:
    r3 = mixed_world(tmp_path)
    with stamped(r3) as log:
        r3.cycle()
        r3.drive_until_complete(max_ticks=600)
        finished_ms = r3.clock.now_ms()
        lines = log.lines(r"backfill progress")
    assert finished_ms - T0 >= 5 * 60_000, "the scenario must take minutes"
    assert len(lines) >= 4
    assert all(re.fullmatch(PROGRESS, message) for _t, message in lines), [m for _t, m in lines[:1]]
    times = [t for t, _m in lines]
    assert all(b - a >= 60_000 for a, b in zip(times, times[1:], strict=False)), times  # at most one a minute
    assert times[0] - T0 <= 60_000  # the first one soon after the pass starts


def test_R3_AC7_the_progress_counters_are_consistent_and_never_go_down(tmp_path: Path) -> None:
    r3 = mixed_world(tmp_path)
    with stamped(r3) as log:
        r3.cycle()
        r3.drive_until_complete(max_ticks=600)
        lines = log.lines(r"backfill progress")
    assert lines, 'no progress line at all'
    rows = []
    for _t, message in lines:
        m = re.fullmatch(PROGRESS, message)
        assert m is not None, message
        rows.append(tuple(int(g) for g in m.groups()))
    for done, total, screened, ok, rejected, dropped, cooling, retry in rows:
        assert screened == ok + rejected
        assert 0 <= done <= total and total >= 1
        assert dropped >= 0 and cooling >= 0 and retry >= 0
    for column in range(7):  # done, of, screened, ok, rejected, dropped, cooling: no going down except 'of'/'cooling'
        if column in (1, 6):
            continue
        series = [r[column] for r in rows]
        assert series == sorted(series), (column, series)
    assert rows[-1][4] >= 1  # rejected wallets were counted
    assert max(r[2] for r in rows) <= 30


def test_R3_AC7_the_progress_line_says_how_long_the_pass_waits_for_the_budget(tmp_path: Path) -> None:
    r3 = mixed_world(tmp_path)
    with stamped(r3) as log:
        r3.cycle()
        r3.drive_until_complete(max_ticks=600)
        lines = log.lines(r"backfill progress")
    assert r3.refusals, "the scenario must hit the rate budget"
    waits = [int(re.fullmatch(PROGRESS, m).group(8)) for _t, m in lines if re.fullmatch(PROGRESS, m)]  # type: ignore[union-attr]
    assert any(0 < n <= 60 for n in waits), waits


def test_R3_AC7_one_pass_complete_line_and_no_progress_line_after_it(tmp_path: Path) -> None:
    r3 = mixed_world(tmp_path)
    with stamped(r3) as log:
        r3.cycle()
        r3.drive_until_complete(max_ticks=600)
        r3.drive(60)
        r3.advance_h(1)
        r3.cycle(60)  # the next cycle has nothing new to do
        done_lines = log.lines(PASS_DONE)
        done_t = done_lines[0][0] if done_lines else None
        late = [t for t, _m in log.lines(r"backfill progress") if done_t is not None and t > done_t]
    assert len(done_lines) == 1
    assert late == []
