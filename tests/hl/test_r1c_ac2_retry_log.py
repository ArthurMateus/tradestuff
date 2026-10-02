"""R1c.AC2: the hl_retry warning names request type, attempt, delay and the failure (HTTP status when there is one,
error text without URL or body) in the MESSAGE; the final failure after ``hl.retry_max`` is logged too.
Real ``HlRestClient`` over the real stdlib transport against the loopback fake server of test_rest.py."""

from __future__ import annotations

import logging
import re
import threading

import pytest

from copytrade.hl.budget import Priority
from copytrade.hl.errors import HlHttpError, HlRateLimitedError, HlTimeoutError
from copytrade.hl.rest import StdlibHttpTransport
from tests.hl.support import WALLET_A, always, make_rig, raising
from tests.hl.test_rest import loopback

pytestmark = pytest.mark.unit
C = Priority.CRITICAL
_LOGGER = "copytrade.hl.rest"


def _retry_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER and "backing off" in r.getMessage()]


def _fills(rig) -> None:  # type: ignore[no-untyped-def]
    rig.client.user_fills_by_time(WALLET_A, 0, None, priority=C)


def test_R1c_AC2_a_429_retry_warning_names_type_attempt_delay_and_status(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    with loopback((429, "slow down")) as (url, _):
        rig = make_rig(url=url, transport=StdlibHttpTransport(), hl__retry_max=2)
        with pytest.raises(HlRateLimitedError):
            _fills(rig)
    msgs = _retry_messages(caplog)
    assert len(msgs) == 2
    first, second = msgs
    assert first.startswith("info request failed, backing off")
    assert "type=userFillsByTime" in first
    assert re.search(r"attempt=\d+", first) and re.search(r"attempt=\d+", second)
    assert re.search(r"attempt=(\d+)", first).group(1) != re.search(r"attempt=(\d+)", second).group(1)  # type: ignore[union-attr]
    for msg, delay in zip(msgs, rig.sleeper.sleeps, strict=False):
        m = re.search(r"delay=([0-9.]+)s", msg)
        assert m is not None and float(m.group(1)) == pytest.approx(delay, abs=0.06)
    assert "status=429" in first and "error=" in first


def test_R1c_AC2_the_warning_never_carries_the_url_or_the_response_body(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    with loopback((429, "SECRET-BODY-TEXT")) as (url, _):
        rig = make_rig(url=url, transport=StdlibHttpTransport(), hl__retry_max=1)
        with pytest.raises(HlRateLimitedError):
            _fills(rig)
    (msg,) = _retry_messages(caplog)
    assert "127.0.0.1" not in msg and "http://" not in msg and "/info" not in msg
    assert "SECRET-BODY-TEXT" not in msg


def test_R1c_AC2_a_timeout_retry_warning_names_the_failure_without_a_status(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    hold = threading.Event()
    with loopback((200, "{}"), hold) as (url, _):
        rig = make_rig(url=url, transport=StdlibHttpTransport(), hl__retry_max=1, hl__rest_timeout_s=0.3)
        with pytest.raises(HlTimeoutError):
            _fills(rig)
    (msg,) = _retry_messages(caplog)
    assert "type=userFillsByTime" in msg and "attempt=" in msg and re.search(r"delay=[0-9.]+s", msg)
    assert "status=" not in msg
    assert "error=" in msg and ("HlTimeoutError" in msg or "no answer within" in msg)


def test_R1c_AC2_a_connection_failure_retry_warning_names_the_failure(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    rig = make_rig(handler=raising(ConnectionResetError("reset")), hl__retry_max=1)
    from copytrade.hl.errors import HlConnectionError

    with pytest.raises(HlConnectionError):
        rig.client.all_mids(priority=C)
    (msg,) = _retry_messages(caplog)
    assert "type=allMids" in msg and "attempt=" in msg and "delay=" in msg
    assert "status=" not in msg and "error=" in msg and "connection failed" in msg


def test_R1c_AC2_a_500_is_not_retried_so_no_backoff_warning_and_the_failure_is_logged_with_its_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    with loopback((500, "oops")) as (url, handler):
        rig = make_rig(url=url, transport=StdlibHttpTransport(), hl__retry_max=3)
        with pytest.raises(HlHttpError):
            _fills(rig)
    assert len(handler.log) == 1
    assert _retry_messages(caplog) == []


def test_R1c_AC2_the_final_failure_after_retry_max_is_logged_once_with_the_same_facts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    rig = make_rig(handler=always(429, "slow"), hl__retry_max=2)
    with pytest.raises(HlRateLimitedError):
        _fills(rig)
    final = [
        r.getMessage()
        for r in caplog.records
        if r.name == _LOGGER and r.levelno >= logging.WARNING and "backing off" not in r.getMessage()
    ]
    assert len(final) == 1
    assert "type=userFillsByTime" in final[0] and "status=429" in final[0] and "attempt=" in final[0]
    assert "slow" not in final[0]
    assert len(_retry_messages(caplog)) == 2  # the retry warnings are unchanged by the final one


def test_R1c_AC2_the_final_timeout_failure_is_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    rig = make_rig(handler=raising(TimeoutError("timed out")), hl__retry_max=1)
    with pytest.raises(HlTimeoutError):
        rig.client.all_mids(priority=C)
    final = [
        r.getMessage()
        for r in caplog.records
        if r.name == _LOGGER and r.levelno >= logging.WARNING and "backing off" not in r.getMessage()
    ]
    assert len(final) == 1 and "type=allMids" in final[0] and "status=" not in final[0]


def test_R1c_AC2_a_success_after_a_retry_logs_the_retry_but_no_final_failure(caplog: pytest.LogCaptureFixture) -> None:
    from tests.hl.support import fixture, ok, status

    caplog.set_level(logging.WARNING, logger=_LOGGER)
    answers = iter([status(429)])
    rig = make_rig(handler=lambda call: next(answers, None) or ok(fixture("allMids")))
    rig.client.all_mids(priority=C)
    assert len(_retry_messages(caplog)) == 1
    assert [r for r in caplog.records if r.name == _LOGGER and "backing off" not in r.getMessage()] == []
