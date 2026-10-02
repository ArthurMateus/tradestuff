"""R1b.AC2 [integration]: ``copytrade run`` configures logging once (console at INFO + a rotating file under the data
root), idempotently, with no secret in it, and the non-paper refusal is unchanged. Real runner over loopback fakes."""

from __future__ import annotations

import io
import logging
import logging.handlers
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.secrets import SecretValue
from copytrade.runner.app import run_app
from tests.runner.world import PIN, SECRETS, World, secret_leaks

_LOGGERS = ("", "copytrade")


def _handlers() -> list[logging.Handler]:
    seen: list[logging.Handler] = []
    for name in _LOGGERS:
        for handler in logging.getLogger(name).handlers:
            if type(handler).__module__.startswith(("_pytest", "tests")):
                continue  # pytest's own capture handlers are not ours
            if handler not in seen:
                seen.append(handler)
    return seen


def _files(handlers: list[logging.Handler]) -> list[logging.handlers.RotatingFileHandler]:
    return [h for h in handlers if isinstance(h, logging.handlers.RotatingFileHandler)]


def _consoles(handlers: list[logging.Handler]) -> list[logging.StreamHandler[Any]]:
    return [h for h in handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Our own test hygiene: the process-wide logging config is put back after each test (not a mock)."""
    saved = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).level) for n in _LOGGERS}
    yield
    for name, (handlers, level) in saved.items():
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            if handler not in handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(level)


def _run(world: World, root: Path) -> tuple[int, str, str]:
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
    return codes[0], out.getvalue(), err.getvalue()


def _flush() -> None:
    for handler in _handlers():
        handler.flush()


def test_R1b_AC2_run_app_installs_one_info_console_handler_and_one_rotating_file_handler(new_world: Any) -> None:
    world: World = new_world()
    code, _, _ = _run(world, world.write_config())
    assert code == 0
    handlers = _handlers()
    assert len(_files(handlers)) == 1
    assert len(_consoles(handlers)) >= 1
    effective = logging.getLogger("copytrade.selection.backfill").getEffectiveLevel()
    assert effective <= logging.INFO  # an INFO record of any copytrade module gets through
    assert logging.getLogger("copytrade.selection.backfill").isEnabledFor(logging.INFO)


def test_R1b_AC2_the_log_file_lives_under_the_data_root_logs_directory(new_world: Any) -> None:
    world: World = new_world()
    _run(world, world.write_config())
    (handler,) = _files(_handlers())
    assert Path(handler.baseFilename) == (world.data("logs") / "copytrade.log").resolve()


def test_R1b_AC2_the_file_rotates_with_a_small_fixed_size_and_backup_count(new_world: Any) -> None:
    world: World = new_world()
    _run(world, world.write_config())
    (handler,) = _files(_handlers())
    assert 0 < handler.maxBytes <= 50 * 1024 * 1024
    assert 1 <= handler.backupCount <= 10


def test_R1b_AC2_a_record_reaches_the_file_with_timestamp_level_logger_name_and_message(new_world: Any) -> None:
    world: World = new_world()
    _run(world, world.write_config())
    logging.getLogger("copytrade.selection.backfill").warning("backfill probe wallet=0xabc status=500")
    _flush()
    text = (world.data("logs") / "copytrade.log").read_text(encoding="utf-8")
    (line,) = [ln for ln in text.splitlines() if "backfill probe" in ln]
    assert re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", line)
    assert "WARNING" in line and "copytrade.selection.backfill" in line and "status=500" in line


def test_R1b_AC2_the_console_handler_prints_info_with_the_same_fields_and_skips_debug(new_world: Any) -> None:
    world: World = new_world()
    _run(world, world.write_config())
    consoles = _consoles(_handlers())
    assert consoles
    record = logging.LogRecord("copytrade.x", logging.INFO, __file__, 1, "console probe", None, None)
    formatted = [h.format(record) for h in consoles]
    assert any(
        "INFO" in f and "copytrade.x" in f and "console probe" in f and re.search(r"\d{4}-\d{2}-\d{2}", f)
        for f in formatted
    )
    assert all(h.level == logging.INFO or h.level == logging.NOTSET for h in consoles)
    debug = logging.LogRecord("copytrade.x", logging.DEBUG, __file__, 1, "dbg", None, None)
    assert not any(h.level <= logging.DEBUG and h.level != logging.NOTSET for h in consoles)
    assert not logging.getLogger("copytrade.x").isEnabledFor(debug.levelno) or all(
        h.level >= logging.INFO for h in consoles
    )


def test_R1b_AC2_calling_run_app_twice_does_not_duplicate_handlers(new_world: Any) -> None:
    world: World = new_world()
    root = world.write_config()
    _run(world, root)
    first = _handlers()
    first_count = (len(_files(first)), len(_consoles(first)))
    _run(world, root)
    second = _handlers()
    assert (len(_files(second)), len(_consoles(second))) == first_count
    logging.getLogger("copytrade.selection.backfill").warning("dup probe")
    _flush()
    text = (world.data("logs") / "copytrade.log").read_text(encoding="utf-8")
    assert text.count("dup probe") == 1  # one line, not one per call


def test_R1b_AC2_a_non_paper_start_still_refuses_with_the_f1_message_and_installs_no_handler(
    new_world: Any,
) -> None:
    world: World = new_world()
    world.tree.set("mode", "live")
    root = world.write_config()
    before = len(_handlers())
    err = io.StringIO()
    code = run_app(root, world.env, deps=world.deps(), stop=threading.Event(), out=io.StringIO(), err=err)
    assert code != 0 and "mode not permitted in this build" in err.getvalue()
    assert len(_handlers()) == before
    assert not (world.data("logs")).exists()


def test_R1b_AC2_no_secret_reaches_the_file_after_a_run_and_a_secretvalue_logs_redacted(new_world: Any) -> None:
    world: World = new_world()
    _run(world, world.write_config())
    secret = SecretValue(SECRETS["token"])
    logging.getLogger("copytrade.runner").warning("token is %s and %r", secret, secret)
    _flush()
    text = (world.data("logs") / "copytrade.log").read_text(encoding="utf-8")
    assert "redacted" in text  # the record was written, through the real redaction of SecretValue
    assert secret_leaks(text) == []
    assert PIN not in text
    for name in ("COPYTRADE_TELEGRAM_TOKEN", "COPYTRADE_TELEGRAM_PIN_HASH", "COPYTRADE_TELEGRAM_PIN_SALT"):
        assert world.env[name] not in text


def test_R1b_AC2_the_handler_setup_logs_no_environment_value(new_world: Any) -> None:
    world: World = new_world()
    _run(world, world.write_config())
    text = (world.data("logs") / "copytrade.log").read_text(encoding="utf-8")
    assert text != ""  # something is logged on start (the file is live), but never a value of the environment
    for value in world.env.values():
        if len(value) >= 8:
            assert value not in text
