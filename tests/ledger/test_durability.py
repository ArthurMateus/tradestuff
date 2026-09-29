"""F2.AC3 crash durability and F2.AC6 failed appends.

AC3: the process is force-killed at 100 seeded points during a replay of 1,000 signals; after each restart
the ledger verifies, has 0 partial records, and each client order ID appears at most once (A5). The kill is a
real ``SIGKILL``/``TerminateProcess`` of a real subprocess writing to a real directory.
AC6: an append that fails raises to the caller and the ledger refuses to continue (the engine's fail-closed
state, §5, is built on ``Ledger.failed`` and ``LedgerWriteError``).

Spec: 04-spec.md F2.AC3, F2.AC6, §5 "Ledger append or verification failure", invariants A2, A5.
"""

from __future__ import annotations

import errno
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from copytrade.ledger.errors import DuplicateClientOrderIdError, LedgerCorruptError, LedgerLockedError, LedgerWriteError
from copytrade.ledger.records import KIND_FILL
from copytrade.ledger.store import Ledger, read_records, verify_ledger
from tests.ledger.helpers import FakeClock, ledger_file, make_fill, raw_lines

REPO_ROOT = Path(__file__).resolve().parents[2]
TOTAL_SIGNALS = 1_000
KILLS = 100


def _spawn(mode: str, directory: Path, number: int) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)])
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "tests.ledger._worker", mode, str(directory), str(number)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )


def _line(proc: subprocess.Popen[str]) -> str:
    assert proc.stdout is not None and proc.stderr is not None
    line = proc.stdout.readline().strip()
    if not line:
        proc.kill()
        proc.wait()
        pytest.fail(f"worker exited without output; stderr:\n{proc.stderr.read()[-2000:]}")
    return line


def _check_recovered(directory: Path) -> int:
    """Restart the ledger and assert the crash left no damage. Returns the record count."""
    with Ledger.open(directory, clock=FakeClock()) as reopened:
        result = reopened.verify()
        assert result.ok, result
        data = ledger_file(directory).read_bytes()
        assert data == b"" or data.endswith(b"\n"), "a partial record was left in the file"
        assert all(line.endswith(b"\n") for line in raw_lines(directory))
        ids = [r.payload["signal"] for r in reopened.records() if r.kind == "order"]
        assert len(ids) == len(set(ids)), "a client order ID appears twice"
        return reopened.last_seq


@pytest.mark.integration
def test_F2_AC3_force_killed_at_100_random_points_during_a_replay_of_1000_signals(tmp_path: Path) -> None:
    directory = tmp_path / "ledger"
    rng = random.Random(20260929)
    kills = 0
    finished = False
    while not finished:
        proc = _spawn("replay", directory, TOTAL_SIGNALS)
        assert proc.stdin is not None
        assert _line(proc) == "ready"
        allowed = rng.randint(1, 12)
        for _ in range(allowed):
            proc.stdin.write("go\n")
            proc.stdin.flush()
            reply = _line(proc)
            if reply == "done":
                finished = True
                break
            assert reply.startswith("ack ")
        if finished or kills >= KILLS:
            if not finished:  # all planned kills done: let this run finish
                while not finished:
                    proc.stdin.write("go\n")
                    proc.stdin.flush()
                    finished = _line(proc) == "done"
            proc.wait(timeout=60)
            break
        proc.stdin.write("go\n")  # release one more append, then kill while it may be mid-write
        proc.stdin.flush()
        proc.kill()
        proc.wait(timeout=60)
        kills += 1
        _check_recovered(directory)
    assert kills == KILLS
    # final state: every signal has exactly one order, in a verifying ledger
    result = verify_ledger(directory)
    assert result.ok
    orders = [r for r in read_records(directory) if r.kind == "order"]
    assert sorted(r.payload["signal"] for r in orders) == list(range(TOTAL_SIGNALS))


@pytest.mark.unit
def test_F2_AC3_torn_final_write_is_dropped_on_restart_and_the_chain_continues(ledger_dir: Path, clock: FakeClock) -> None:
    with Ledger.open(ledger_dir, clock=clock) as first:
        for i in range(3):
            first.append("note", {"i": i})
    intact = ledger_file(ledger_dir).read_bytes()
    with ledger_file(ledger_dir).open("ab") as fh:
        fh.write(b'{"seq":4,"ts":{"ms":17900')  # power lost mid-write: no newline
    assert verify_ledger(ledger_dir).ok  # read-only check ignores the torn tail
    with Ledger.open(ledger_dir, clock=clock) as restarted:
        assert restarted.last_seq == 3
        assert ledger_file(ledger_dir).read_bytes() == intact  # torn bytes removed
        fourth = restarted.append("note", {"i": 3})
        assert fourth.seq == 4
        assert restarted.verify().ok


@pytest.mark.unit
def test_F2_AC3_read_only_readers_ignore_a_torn_tail_without_touching_it(ledger_dir: Path, clock: FakeClock) -> None:
    with Ledger.open(ledger_dir, clock=clock) as first:
        first.append("note", {"i": 0})
    with ledger_file(ledger_dir).open("ab") as fh:
        fh.write(b'{"seq":2')
    before = ledger_file(ledger_dir).read_bytes()
    assert [r.seq for r in read_records(ledger_dir)] == [1]
    assert ledger_file(ledger_dir).read_bytes() == before


@pytest.mark.unit
def test_F2_AC3_every_append_is_fsynced_before_it_returns(ledger: Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = os.fsync

    def spy(fd: int) -> None:
        calls.append(fd)
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    for i in range(3):
        before = len(calls)
        ledger.append("note", {"i": i})
        assert len(calls) > before


@pytest.mark.unit
def test_F2_AC3_client_order_id_is_unique_and_a_duplicate_writes_nothing(ledger: Ledger, ledger_dir: Path) -> None:
    ledger.append("order", {"signal": 1}, client_order_id="co-1")
    assert ledger.has_client_order_id("co-1")
    assert not ledger.has_client_order_id("co-2")
    before = ledger_file(ledger_dir).read_bytes()
    with pytest.raises(DuplicateClientOrderIdError):
        ledger.append("order", {"signal": 1, "retry": True}, client_order_id="co-1")
    assert ledger_file(ledger_dir).read_bytes() == before
    assert ledger.append("order", {"signal": 2}, client_order_id="co-2").seq == 2


@pytest.mark.unit
def test_F2_AC3_client_order_ids_survive_a_restart(ledger_dir: Path, clock: FakeClock) -> None:
    with Ledger.open(ledger_dir, clock=clock) as first:
        first.append("order", {"signal": 1}, client_order_id="co-1")
    with Ledger.open(ledger_dir, clock=clock) as second:
        assert second.has_client_order_id("co-1")
        with pytest.raises(DuplicateClientOrderIdError):
            second.append("order", {"signal": 1}, client_order_id="co-1")


@pytest.mark.unit
def test_F2_AC3_multiple_fills_may_share_one_client_order_id(ledger: Ledger) -> None:
    """Partial fills (A8): fill records do not claim client-order-id uniqueness."""
    ledger.append_fill(make_fill(1))
    ledger.append_fill(make_fill(1))  # same client_order_id
    assert sum(1 for r in ledger.records() if r.kind == KIND_FILL) == 2


@pytest.mark.unit
def test_F2_AC3_client_order_id_check_is_exact_not_normalised(ledger: Ledger) -> None:
    ledger.append("order", {}, client_order_id="CO-1")
    assert not ledger.has_client_order_id("co-1")
    assert not ledger.has_client_order_id("CO-1 ")
    ledger.append("order", {}, client_order_id="co-1")


@pytest.mark.unit
def test_F2_AC3_a_second_live_writer_is_refused(ledger: Ledger, ledger_dir: Path, clock: FakeClock) -> None:
    with pytest.raises(LedgerLockedError):
        Ledger.open(ledger_dir, clock=clock)
    ledger.append("note", {"still": "works"})


@pytest.mark.unit
def test_F2_AC3_the_lock_is_released_on_close_so_restart_works(ledger_dir: Path, clock: FakeClock) -> None:
    first = Ledger.open(ledger_dir, clock=clock)
    first.close()
    first.close()  # idempotent
    with Ledger.open(ledger_dir, clock=clock) as second:
        assert second.last_seq == 0


@pytest.mark.unit
def test_F2_AC3_readers_work_while_the_writer_holds_the_ledger(ledger: Ledger, ledger_dir: Path) -> None:
    ledger.append("note", {"i": 1})
    assert verify_ledger(ledger_dir).ok
    assert [r.seq for r in read_records(ledger_dir)] == [1]


@pytest.mark.unit
def test_F2_AC3_opening_a_corrupt_ledger_does_not_leave_the_lock_held(ledger_dir: Path, clock: FakeClock) -> None:
    with Ledger.open(ledger_dir, clock=clock) as first:
        first.append("note", {"i": 1})
    ledger_file(ledger_dir).write_bytes(b"corrupt\n")
    with pytest.raises(LedgerCorruptError):
        Ledger.open(ledger_dir, clock=clock)
    with pytest.raises(LedgerCorruptError):  # still corrupt (not "locked")
        Ledger.open(ledger_dir, clock=clock)


# --- AC6 ---------------------------------------------------------------------------------------------

@pytest.mark.unit
def test_F2_AC6_an_fsync_failure_raises_to_the_caller_and_the_ledger_refuses_to_continue(
    ledger_dir: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = Ledger.open(ledger_dir, clock=clock)
    good = [ledger.append("note", {"i": i}) for i in range(2)]

    def failing_fsync(fd: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(LedgerWriteError) as caught:
        ledger.append("note", {"i": 2})
    assert isinstance(caught.value.__cause__, OSError)
    assert ledger.failed
    monkeypatch.undo()
    with pytest.raises(LedgerWriteError):  # even though the disk works again: never continue silently
        ledger.append("note", {"i": 3})
    ledger.close()
    with Ledger.open(ledger_dir, clock=clock) as recovered:
        seqs = [r.seq for r in recovered.records()]
        assert seqs in ([1, 2], [1, 2, 3])  # the failed record is wholly there or wholly absent
        assert [r.hash for r in recovered.records()][:2] == [g.hash for g in good]
        assert recovered.verify().ok and not recovered.failed
        assert recovered.append("note", {"i": 9}).seq == len(seqs) + 1


@pytest.mark.unit
def test_F2_AC6_append_never_returns_a_record_for_a_failed_write(
    ledger_dir: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = Ledger.open(ledger_dir, clock=clock)
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(errno.EIO, "I/O error")))
    returned = None
    with pytest.raises(LedgerWriteError):
        returned = ledger.append_fill(make_fill(1))
    assert returned is None
    monkeypatch.undo()
    with pytest.raises(LedgerWriteError):
        ledger.append_fill(make_fill(2))
    ledger.close()


@pytest.mark.integration
def test_F2_AC6_a_real_disk_full_style_write_failure_raises_leaves_no_partial_record_and_recovers(tmp_path: Path) -> None:
    pytest.importorskip("resource")  # POSIX only; the fsync-injection tests above cover Windows
    directory = tmp_path / "ledger"
    proc = _spawn("fsize", directory, 6_000)
    out, err = proc.communicate(timeout=120)
    lines = dict(line.split(" ", 1) for line in out.strip().splitlines())
    assert "never failed" not in out and "appended" in lines, f"stdout={out!r} stderr={err[-1500:]!r}"
    appended = int(lines["appended"])
    assert appended > 5
    assert lines["failed"] == "True" and lines["refused"] == "True"
    with Ledger.open(directory, clock=FakeClock()) as recovered:
        assert recovered.verify().ok
        assert recovered.last_seq == appended  # every acknowledged record survived, no partial one counted
        data = ledger_file(directory).read_bytes()
        assert data.endswith(b"\n")
