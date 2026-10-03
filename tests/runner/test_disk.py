"""R0.AC8: the disk-space guard with the real DiskProbe and conservative defaults for the PO's ~100 GB disk. Refuse to
start below floor + resume margin, alert before the floor, stop recording safely at the floor, exits never blocked."""

from __future__ import annotations

import io
import shutil
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.config import load_config
from copytrade.runner.app import run_app
from copytrade.runner.disk import DiskSpaceError, SystemDiskProbe, check_start_disk
from copytrade.runner.wiring import build_runner
from tests.core.helpers import REPO_ROOT
from tests.hl.ws_server import wait_for
from tests.recorder.helpers import FakeDisk, cfg
from tests.runner.fake_hl import fill_json
from tests.runner.world import LEADER, World

D = Decimal
REQUIRED = D("10")  # recording.disk_floor_free_gb 8 + recording.disk_resume_margin_gb 2 in the fixture config


# ------------------------------------------------------------------------------------------- the real probe


def test_R0_AC8_system_probe_reports_free_gb_of_the_volume(tmp_path: Path) -> None:
    free = SystemDiskProbe().free_gb(tmp_path)
    expected = D(shutil.disk_usage(tmp_path).free) / D(10**9)
    assert isinstance(free, Decimal) and abs(free - expected) < D("0.5")


def test_R0_AC8_a_path_that_does_not_exist_yet_is_probed_through_its_nearest_existing_parent(tmp_path: Path) -> None:
    deep = tmp_path / "not" / "yet" / "there"
    assert abs(SystemDiskProbe().free_gb(deep) - SystemDiskProbe().free_gb(tmp_path)) < D("0.5")
    assert not (tmp_path / "not").exists()  # probing creates nothing


def test_R0_AC8_one_gb_is_ten_to_the_ninth_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(10**12, 5 * 10**11, 50 * 10**9))
    assert SystemDiskProbe().free_gb(tmp_path) == D("50")


def test_R0_AC8_an_unreadable_volume_raises_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_p: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(shutil, "disk_usage", boom)
    with pytest.raises(OSError, match="denied"):
        SystemDiskProbe().free_gb(tmp_path)


# ------------------------------------------------------------------------------------ check_start_disk


@pytest.mark.parametrize(("free", "ok"), [("10.01", True), ("10", True), ("9.99", False), ("0", False), ("8", False)])
def test_R0_AC8_start_check_boundary_is_floor_plus_resume_margin(free: str, ok: bool, tmp_path: Path) -> None:
    probe = FakeDisk(free)
    paths = (tmp_path / "ledger", tmp_path / "recordings", tmp_path / "cache")
    if ok:
        assert check_start_disk(cfg(), probe, paths) == D(free)
    else:
        with pytest.raises(DiskSpaceError) as caught:
            check_start_disk(cfg(), probe, paths)
        assert free in str(caught.value) and "10" in str(caught.value)


def test_R0_AC8_the_smallest_volume_decides(tmp_path: Path) -> None:
    probe = FakeDisk("500")
    paths = (tmp_path / "ledger", tmp_path / "recordings", tmp_path / "cache")
    probe.set(paths[1], "9")
    with pytest.raises(DiskSpaceError):
        check_start_disk(cfg(), probe, paths)


def test_R0_AC8_an_unreadable_probe_counts_as_no_space_a2(tmp_path: Path) -> None:
    class Broken:
        def free_gb(self, path: Path) -> Decimal:
            raise OSError("cannot read")

    with pytest.raises(DiskSpaceError):
        check_start_disk(cfg(), Broken(), (tmp_path,))


# --------------------------------------------------------------------------------------------- the runner


def test_R0_AC8_below_the_floor_the_runner_refuses_to_start_before_touching_anything(
    new_world: Any, network_guard: Any
) -> None:
    world: World = new_world()
    world.disk.set(None, "9.5")
    root = world.write_config()
    connects, threads = len(network_guard.all_connects), threading.active_count()
    err = io.StringIO()
    code = run_app(root, world.env, deps=world.deps(), stop=threading.Event(), out=io.StringIO(), err=err)
    assert code == 1 and "9.5" in err.getvalue() and "GB" in err.getvalue()
    with pytest.raises(DiskSpaceError):
        build_runner(root, world.env, world.deps())
    assert len(network_guard.all_connects) == connects and threading.active_count() == threads
    assert not world.ledger_dir.exists()  # not even the ledger was created
    assert world.tg.request_count() == 0


def test_R0_AC8_exactly_at_the_requirement_it_starts(new_world: Any) -> None:
    world: World = new_world()
    world.disk.set(None, "10")
    runner, _ = world.start()
    assert runner.recorder.recording


def test_R0_AC8_between_floor_and_alert_level_it_starts_and_alerts_before_the_floor(new_world: Any) -> None:
    world: World = new_world()
    world.disk.set(None, "15")  # recording.disk_alert_free_gb is 20
    runner, _ = world.start()
    world.step(runner, 2, ms=61_000)  # recording.disk_check_interval_s is 60
    wait_for(lambda: any("disk_free_low" in t for t in world.tg.sent()), what="the low-disk alert")
    assert runner.recorder.recording  # still recording: this is the early warning


def test_R0_AC8_at_the_floor_recording_stops_entries_are_refused_and_exits_still_work(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    runner, _ = world.start()
    world.leader_open(runner)
    world.step(runner, 3 * 7, ms=10_000)  # 3 x 70 s in steps below feed.stale_after_s (30), so the feed is not dropped as silent
    assert runner.recorder.recording
    world.disk.set(None, "7")  # below recording.disk_floor_free_gb (8)
    world.step(runner, 2 * 7, ms=10_000)
    assert not runner.recorder.recording
    wait_for(lambda: any("disk_floor_stopped" in t for t in world.tg.sent()), what="the floor alert")
    files_before = sorted(p.name for p in world.recordings_dir.rglob("*") if p.is_file())
    # a new entry is refused (the stand-in policy vetoes it) ...
    world.hl.leader_positions[next(iter(world.hl.leader_fills))] = [("SOL", "5.0", "100.0"), ("ETH", "1.0", "3400.0")]
    world.hl.push_user_fills(
        LEADER,
        [fill_json(70, coin="ETH", side="B", sz="1.0", px="3400.0", direction="Open Long", time_ms=world.exchange_ms() - 100)],
    )
    world.pump_market(("SOL", "ETH"))
    world.run_until(runner, lambda: world.records("signal_skip"), max_steps=2000, ms=0)  # no fake time passes: the fill stays fresh
    assert runner.broker.position("ETH") is None
    assert "policy_veto" in [r.payload["reason"] for r in world.records("signal_skip")]
    # ... but the exit of the position we hold is NOT blocked
    world.leader_close()
    world.run_until(runner, lambda: runner.broker.position("SOL") is None)
    assert sorted(p.name for p in world.recordings_dir.rglob("*") if p.is_file()) == files_before  # nothing new written


class SwitchDisk(FakeDisk):
    """A probe that works until ``broken`` is set (a volume that goes away while running)."""

    broken = False

    def free_gb(self, path: Path) -> Decimal:
        if self.broken:
            raise OSError("volume gone")
        return super().free_gb(path)


def test_R0_AC8_an_unreadable_disk_while_running_stops_recording_and_blocks_no_exit(new_world: Any) -> None:
    world: World = new_world()
    world.seed_follow()
    probe = SwitchDisk("500")
    runner, _ = world.start(disk=probe)
    try:
        world.leader_open(runner)
        probe.broken = True
        world.step(runner, 2 * 7, ms=10_000)
        assert not runner.recorder.recording  # unknown free space counts as none (A2)
        world.leader_close()
        world.run_until(runner, lambda: runner.broker.position("SOL") is None, max_steps=500)
    finally:
        runner.stop()


# ------------------------------------------------------------------------------- committed defaults (config/)


def test_R0_AC8_the_committed_config_exists_loads_and_is_paper_with_conservative_disk_defaults() -> None:
    config = load_config(REPO_ROOT / "config")
    assert config["mode"] == "paper"
    floor, alert, margin = (config[f"recording.disk_{k}"] for k in ("floor_free_gb", "alert_free_gb", "resume_margin_gb"))
    assert floor >= 8 and alert >= 20 and alert > floor and margin >= 2  # a ~100 GB disk: stop well before it is full
    # the retention cap alone can never walk the disk down to the alert level
    assert config["recording.max_gb_per_day"] * config["storage.local_retention_days"] <= 25
    assert config["storage.local_retention_days"] <= 7
