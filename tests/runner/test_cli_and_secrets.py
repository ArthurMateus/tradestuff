"""R0.AC1 (one command), R0.AC2 (paper only: refuses live/testnet) and R0.AC3 (secrets only from COPYTRADE_* env,
never logged). Real runner over loopback fakes; see docs/sdlc/copytrade-v1/05-test-plan-R0.md."""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.errors import CopytradeError
from copytrade.runner.app import run_app
from tests.core.helpers import ConfigTree, make_root, run_cli
from tests.runner.world import ALERTS_CHAT, PIN, SECRETS, World, secret_leaks

MODE_MESSAGE = "mode not permitted in this build"


def _root_with_mode(tmp_path: Path, mode: str) -> Path:
    tree = ConfigTree().set("mode", mode)
    tree.set("storage.ledger_dir", str(tmp_path / "data" / "ledger"))
    tree.set("storage.recordings_dir", str(tmp_path / "data" / "recordings"))
    tree.set("storage.cache_dir", str(tmp_path / "data" / "cache"))
    return make_root(tmp_path, tree).root


# ---------------------------------------------------------------------------------------------------- AC2


@pytest.mark.parametrize("mode", ["live", "testnet", "Paper", "paper ", "PAPER"])
def test_R0_AC2_refuses_any_non_paper_mode_with_the_f1_message(tmp_path: Path, network_guard: Any, mode: str) -> None:
    root = _root_with_mode(tmp_path, mode)
    connects, threads = len(network_guard.all_connects), threading.active_count()
    result = run_cli(["run", "--root", str(root)])
    assert result.code != 0
    assert MODE_MESSAGE in result.stderr
    assert result.stderr == run_cli(["start", "--root", str(root)]).stderr  # the very same F1 message
    assert len(network_guard.all_connects) == connects  # not even a loopback connection was tried
    assert threading.active_count() == threads  # no thread was started
    assert not (tmp_path / "data").exists()  # no ledger, recording or state directory was created


def test_R0_AC2_there_is_no_flag_that_selects_a_mode(tmp_path: Path) -> None:
    root = _root_with_mode(tmp_path, "paper")
    assert run_cli(["run", "--help"]).code == 0  # the subcommand exists
    for flag in (["--mode", "live"], ["--live"], ["--testnet"], ["--mode=testnet"]):
        assert run_cli(["run", "--root", str(root), *flag]).code == 2


def test_R0_AC2_run_is_a_registered_subcommand_and_start_still_works(tmp_path: Path) -> None:
    root = _root_with_mode(tmp_path, "paper")
    assert run_cli(["run", "--help"]).code == 0
    assert run_cli(["start", "--root", str(root)]).code == 0


def test_R0_AC2_a_live_config_via_run_app_never_reaches_telegram_or_hyperliquid(new_world: Any) -> None:
    world: World = new_world()
    world.tree.set("mode", "live")
    root = world.write_config()
    err = io.StringIO()
    code = run_app(root, world.env, deps=world.deps(), stop=threading.Event(), out=io.StringIO(), err=err)
    assert code != 0 and MODE_MESSAGE in err.getvalue()
    assert world.tg.request_count() == 0
    assert world.hl.http_requests == [] and world.hl.connections() == []


# ---------------------------------------------------------------------------------------------------- AC1


def test_R0_AC1_run_app_starts_everything_and_stops_cleanly_with_exit_code_zero(new_world: Any) -> None:
    world: World = new_world()
    root = world.write_config()
    stop, out, err = threading.Event(), io.StringIO(), io.StringIO()
    codes: list[int] = []
    thread = threading.Thread(
        target=lambda: codes.append(run_app(root, world.env, deps=world.deps(), stop=stop, out=out, err=err))
    )
    thread.start()
    world.telegram_ready()
    stop.set()
    thread.join(timeout=20)
    assert not thread.is_alive()
    assert codes == [0]
    assert err.getvalue() == ""


def test_R0_AC1_the_runner_wires_every_real_component_and_paper_only(new_world: Any) -> None:
    from copytrade.hl.ws import HlWsFeed
    from copytrade.paper.broker import PaperBroker
    from copytrade.positions.manager import PositionManager
    from copytrade.recorder.service import Recorder
    from copytrade.risk.gate import RiskGate
    from copytrade.selection.manager import FollowManager
    from copytrade.signals.detector import SignalDetector
    from copytrade.telegram.bot import TelegramBot

    world: World = new_world()
    runner, report = world.start()
    assert isinstance(runner.broker, PaperBroker) and isinstance(runner.gate, RiskGate)
    assert isinstance(runner.manager, PositionManager) and isinstance(runner.bot, TelegramBot)
    assert isinstance(runner.recorder, Recorder) and isinstance(runner.follow, FollowManager)
    assert isinstance(runner.detector, SignalDetector) and isinstance(runner.feed, HlWsFeed)
    assert runner.config["mode"] == "paper"
    assert (report.restored_positions, report.restored_stops, report.uncertain) == (0, 0, ())
    assert report.entries_blocked is False


def test_R0_AC1_a_first_start_writes_a_runner_start_record_and_never_posts_to_an_order_endpoint(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    world.step(runner, 5)
    starts = world.records("runner_start")
    assert len(starts) == 1 and starts[0].payload["run_id"] == runner.run_id
    assert world.hl.bad_paths == []  # nothing but /info and the stats GET


# ---------------------------------------------------------------------------------------------------- AC3


def test_R0_AC3_a_missing_telegram_token_refuses_to_start_and_names_the_variable_only(new_world: Any) -> None:
    world: World = new_world()
    root = world.write_config()
    env = {k: v for k, v in world.env.items() if k != "COPYTRADE_TELEGRAM_TOKEN"}
    err = io.StringIO()
    code = run_app(root, env, deps=world.deps(), stop=threading.Event(), out=io.StringIO(), err=err)
    assert code == 1
    assert "COPYTRADE_TELEGRAM_TOKEN" in err.getvalue()
    assert secret_leaks(err.getvalue()) == []
    assert not world.ledger_dir.exists() or world.records() == []


def test_R0_AC3_secrets_come_only_from_the_given_env_never_from_os_environ(new_world: Any) -> None:
    # tests/conftest.py sets canary values for every COPYTRADE_* variable in os.environ for the whole session
    world: World = new_world()
    root = world.write_config()
    err = io.StringIO()
    code = run_app(root, {}, deps=world.deps(), stop=threading.Event(), out=io.StringIO(), err=err)
    assert code == 1  # an empty env is a refusal even though os.environ holds a token


def test_R0_AC3_build_runner_raises_a_copytrade_error_naming_the_variable_not_a_traceback(new_world: Any) -> None:
    from copytrade.runner.wiring import build_runner

    world: World = new_world()
    root = world.write_config()
    with pytest.raises(CopytradeError) as caught:
        build_runner(root, {}, world.deps())
    assert "COPYTRADE_TELEGRAM_TOKEN" in str(caught.value)


def test_R0_AC3_missing_pin_hash_and_salt_still_starts_but_flatten_is_refused(new_world: Any) -> None:
    world: World = new_world()
    env = {"COPYTRADE_TELEGRAM_TOKEN": world.env["COPYTRADE_TELEGRAM_TOKEN"]}
    runner = world.build(env=env)
    runner.start()
    world.telegram_ready()
    world.tg.push_text(f"/flatten {PIN}")
    world.wait_text("no PIN is configured")


def test_R0_AC3_no_secret_reaches_logs_ledger_recordings_telegram_or_the_console(
    new_world: Any, captured_log_text: Any
) -> None:
    world: World = new_world()
    world.seed_follow()
    root = world.write_config()
    stop, out, err = threading.Event(), io.StringIO(), io.StringIO()
    done: list[int] = []
    thread = threading.Thread(
        target=lambda: done.append(run_app(root, world.env, deps=world.deps(), stop=stop, out=out, err=err))
    )
    thread.start()
    world.telegram_ready()
    world.tg.push_text("/status")
    world.tg.push_text(f"/flatten {PIN}")
    world.wait_text("flatten")
    stop.set()
    thread.join(timeout=20)
    assert done == [0]
    recordings = "\n".join(
        p.read_bytes().decode("latin-1") for p in world.recordings_dir.rglob("*") if p.is_file()
    ) if world.recordings_dir.exists() else ""
    sinks = {
        "stdout": out.getvalue(),
        "stderr": err.getvalue(),
        "logs": captured_log_text(),
        "ledger": world.ledger_text(),
        "recordings": recordings,
        "telegram": world.tg.all_outgoing_text().replace(world.env["COPYTRADE_TELEGRAM_TOKEN"], "<path-token>"),
    }
    for name, text in sinks.items():
        assert secret_leaks(text) == [], f"a secret leaked into {name}"
    assert PIN not in world.ledger_text() and PIN not in captured_log_text()


def test_R0_AC3_the_alert_chat_is_the_configured_one(new_world: Any) -> None:
    world: World = new_world()
    runner, _ = world.start()
    runner.bot.send(__import__("copytrade.core.events", fromlist=["Alert"]).Alert("probe", "hello"))
    world.wait_text("probe: hello", chat=ALERTS_CHAT)
    assert SECRETS["token"] not in world.alert_kinds_sent()
