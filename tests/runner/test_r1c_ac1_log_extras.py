"""R1c.AC1: the shared formatter of ``configure_logging`` appends a record's ``extra`` fields as `` key=value`` after
the message (console and file), capped, single-line, never raising, secrets stay redacted, no duplicates."""

from __future__ import annotations

import logging
import logging.handlers
from collections.abc import Iterator
from pathlib import Path

import pytest

from copytrade.core.secrets import SecretValue
from copytrade.runner.logsetup import configure_logging

_OURS = "_copytrade_run_handler"
_CAP = 200


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    logger = logging.getLogger("copytrade")
    saved, level = list(logger.handlers), logger.level
    yield
    for handler in list(logger.handlers):
        if handler not in saved:
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(level)


def _handlers(tmp_path: Path) -> tuple[logging.Handler, logging.Handler, Path]:
    path = configure_logging(tmp_path / "logs")
    ours = [h for h in logging.getLogger("copytrade").handlers if getattr(h, _OURS, False)]
    file = next(h for h in ours if isinstance(h, logging.handlers.RotatingFileHandler))
    console = next(h for h in ours if h is not file)
    return console, file, path


def _record(msg: str = "something happened", **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("copytrade.x", logging.WARNING, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_R1c_AC1_extras_are_appended_as_key_value_pairs_after_the_message_on_console_and_file(tmp_path: Path) -> None:
    console, file, _ = _handlers(tmp_path)
    for handler in (console, file):
        line = handler.format(_record(status=429, request_type="userFills"))
        assert "something happened status=429" in line or "something happened request_type=userFills" in line
        assert line.index("something happened") < line.index("status=429")
        assert " request_type=userFills" in line


def test_R1c_AC1_extras_reach_the_log_file_through_a_real_logger_call(tmp_path: Path) -> None:
    _, _, path = _handlers(tmp_path)
    logging.getLogger("copytrade.hl.rest").warning("probe", extra={"event": "hl_retry", "delay_s": 3.1})
    for handler in logging.getLogger("copytrade").handlers:
        handler.flush()
    (line,) = [ln for ln in path.read_text(encoding="utf-8").splitlines() if "probe" in ln]
    assert " event=hl_retry" in line and " delay_s=3.1" in line


def test_R1c_AC1_a_record_without_extras_is_unchanged(tmp_path: Path) -> None:
    console, file, _ = _handlers(tmp_path)
    plain = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    record = _record()
    for handler in (console, file):
        assert handler.format(record) == plain.format(record)
        assert handler.format(record).endswith("something happened")


def test_R1c_AC1_standard_logrecord_attributes_are_never_rendered_as_extras(tmp_path: Path) -> None:
    console, _, _ = _handlers(tmp_path)
    line = console.format(_record(status=1))
    for std in ("levelno=", "pathname=", "lineno=", "funcName=", "process=", "thread=", "msecs=", "module="):
        assert std not in line
    assert line.count(" name=") == 0 and "message=" not in line and "asctime=" not in line


def test_R1c_AC1_a_long_value_is_capped(tmp_path: Path) -> None:
    console, _, _ = _handlers(tmp_path)
    line = console.format(_record(error="x" * 5000))
    assert "x" * _CAP in line
    assert "x" * (_CAP + 50) not in line
    assert len(line) < 1000


def test_R1c_AC1_value_exactly_at_the_cap_is_kept_whole_and_one_over_is_cut(tmp_path: Path) -> None:
    console, _, _ = _handlers(tmp_path)
    assert "a" * _CAP in console.format(_record(error="a" * _CAP))
    assert "b" * (_CAP + 1) not in console.format(_record(error="b" * (_CAP + 1)))


def test_R1c_AC1_newlines_in_a_value_are_collapsed_so_the_record_stays_one_line(tmp_path: Path) -> None:
    console, file, _ = _handlers(tmp_path)
    for handler in (console, file):
        line = handler.format(_record(error="first\nsecond\r\nthird"))
        assert "\n" not in line and "\r" not in line
        assert "first" in line and "second" in line and "third" in line


@pytest.mark.parametrize(
    "value",
    [None, float("nan"), float("inf"), -0.0, b"\xff\xfe", "ünï😀", object(), [1, {"a": 2}], {"k": "v"}, ("t",), 10**400],
)
def test_R1c_AC1_odd_values_never_raise(tmp_path: Path, value: object) -> None:
    console, file, _ = _handlers(tmp_path)
    for handler in (console, file):
        line = handler.format(_record(odd=value))
        assert " odd=" in line


def test_R1c_AC1_a_value_whose_str_raises_never_raises(tmp_path: Path) -> None:
    class Bad:
        def __str__(self) -> str:
            raise RuntimeError("boom")

        __repr__ = __str__

    console, _, _ = _handlers(tmp_path)
    line = console.format(_record(bad=Bad(), ok="fine"))
    assert " ok=fine" in line


def test_R1c_AC1_a_secretvalue_extra_stays_redacted(tmp_path: Path) -> None:
    console, file, _ = _handlers(tmp_path)
    secret = SecretValue("123456:ABC-supersecret-token-value")
    for handler in (console, file):
        line = handler.format(_record(token=secret))
        assert "<redacted>" in line
        assert "supersecret" not in line and "123456:ABC" not in line


def test_R1c_AC1_the_formatter_does_not_invent_secret_bearing_fields(tmp_path: Path) -> None:
    console, _, _ = _handlers(tmp_path)
    line = console.format(_record(status=429))
    assert "api.telegram.org" not in line and "bot" not in line.split("something happened", 1)[1]


def test_R1c_AC1_an_extra_already_in_the_message_text_is_not_repeated(tmp_path: Path) -> None:
    console, file, _ = _handlers(tmp_path)
    msg = "backfill failed wallet=0xabc status=500 error=boom"
    for handler in (console, file):
        line = handler.format(_record(msg, wallet="0xabc", status=500, error="boom", attempt=2))
        assert line.count("wallet=0xabc") == 1
        assert line.count("status=500") == 1
        assert line.count("error=boom") == 1
        assert line.count(" attempt=2") == 1  # a new fact is still appended


def test_R1c_AC1_an_extra_with_the_same_key_but_a_different_value_is_still_shown(tmp_path: Path) -> None:
    console, _, _ = _handlers(tmp_path)
    line = console.format(_record("retry status=429", status=500))
    assert "status=429" in line and "status=500" in line


def test_R1c_AC1_a_message_with_percent_args_still_formats(tmp_path: Path) -> None:
    console, _, _ = _handlers(tmp_path)
    record = logging.LogRecord("copytrade.x", logging.WARNING, __file__, 1, "n=%d", (7,), None)
    record.status = 429
    line = console.format(record)
    assert "n=7" in line and " status=429" in line


def test_R1c_AC1_extras_are_rendered_in_a_stable_order(tmp_path: Path) -> None:
    console, _, _ = _handlers(tmp_path)
    a = console.format(_record(zeta=1, alpha=2)).split("something happened", 1)[1]
    b = console.format(_record(alpha=2, zeta=1)).split("something happened", 1)[1]
    assert a == b


def test_R1c_AC1_the_same_formatter_instance_class_serves_console_and_file(tmp_path: Path) -> None:
    console, file, _ = _handlers(tmp_path)
    record = _record(status=429)
    assert type(console.formatter) is type(file.formatter)
    assert console.format(record) == file.format(record)
