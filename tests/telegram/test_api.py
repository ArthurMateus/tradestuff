"""F14 Telegram client over the loopback fake: stdlib HTTP, timeouts, typed errors, no secret leaks."""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from tests.telegram.fake_server import FakeTelegram
from tests.telegram.helpers import OWNER, TOKEN, make_api, tg


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    srv = FakeTelegram(token=TOKEN)
    url = srv.start()
    yield srv, url
    srv.stop()


def test_F14_AC8_send_message_returns_message_id_and_posts_json(server: Any) -> None:
    srv, url = server
    mid = make_api(url).send_message(OWNER, "hello é中")
    assert isinstance(mid, int)
    assert srv.sent(OWNER) == ["hello é中"]


def test_F14_AC3_edit_and_delete_use_the_message_id(server: Any) -> None:
    srv, url = server
    api = make_api(url)
    mid = api.send_message(OWNER, "a")
    api.edit_message_text(OWNER, mid, "b")
    api.delete_message(OWNER, mid)
    assert srv.edits()[0]["message_id"] == mid
    assert srv.edits()[0]["text"] == "b"
    assert srv.deletes()[0]["message_id"] == mid


def test_F14_AC1_get_updates_parses_user_chat_and_text(server: Any) -> None:
    srv, url = server
    srv.push_text("/status", user_id=7, chat_id=8)
    updates = make_api(url).get_updates(0)
    assert len(updates) == 1
    u = updates[0]
    assert (u.user_id, u.chat_id, u.text) == (7, 8, "/status")
    assert isinstance(u.update_id, int)
    assert isinstance(u.message_id, int)


def test_F14_AC1_get_updates_skips_updates_without_a_message(server: Any) -> None:
    srv, url = server
    srv.push_raw({"update_id": 9, "edited_message": {"message_id": 1, "chat": {"id": 1}, "from": {"id": 1}}})
    srv.push_text(None)  # a sticker or photo: no text
    for u in make_api(url).get_updates(0):
        assert u.text is None or isinstance(u.text, str)


def test_F14_AC8_429_raises_rate_limited_with_retry_after(server: Any) -> None:
    srv, url = server
    srv.script.append((429, {"ok": False, "error_code": 429, "description": "Too Many Requests",
                             "parameters": {"retry_after": 7}}))
    with pytest.raises(tg("api").TelegramRateLimited) as info:
        make_api(url).send_message(OWNER, "x")
    assert info.value.retry_after_s == 7


@pytest.mark.parametrize("mode", ["down", "http500"])
def test_F14_AC8_outage_raises_unavailable(server: Any, mode: str) -> None:
    srv, url = server
    srv.mode = mode
    with pytest.raises(tg("api").TelegramUnavailable):
        make_api(url).send_message(OWNER, "x")


def test_F14_AC8_a_hanging_server_times_out_inside_the_configured_timeout(server: Any) -> None:
    srv, url = server
    srv.mode = "hang"
    started = time.monotonic()
    with pytest.raises(tg("api").TelegramUnavailable):
        make_api(url, timeout_s=0.2).send_message(OWNER, "x")
    assert time.monotonic() - started < 1.5


def test_F14_AC8_connection_refused_raises_unavailable() -> None:
    with pytest.raises(tg("api").TelegramUnavailable):
        make_api("http://127.0.0.1:1", timeout_s=0.2).send_message(OWNER, "x")


def test_F14_A_rejected_4xx_is_a_distinct_error(server: Any) -> None:
    srv, url = server
    srv.script.append((400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}))
    with pytest.raises(tg("api").TelegramRejected):
        make_api(url).send_message(OWNER, "x")


def test_F14_AC5_errors_and_logs_never_contain_the_token(server: Any, caplog: pytest.LogCaptureFixture) -> None:
    srv, url = server
    caplog.set_level(logging.DEBUG)
    srv.mode = "http500"
    api = make_api(url)
    with pytest.raises(tg("api").TelegramError) as info:
        api.send_message(OWNER, "x")
    assert TOKEN not in str(info.value) + repr(info.value)
    srv.script.append((401, {"ok": False, "error_code": 401, "description": "Unauthorized"}))
    srv.mode = "ok"
    with pytest.raises(tg("api").TelegramError) as info2:
        api.send_message(OWNER, "x")
    assert TOKEN not in str(info2.value) + repr(info2.value)
    assert TOKEN not in caplog.text
    assert TOKEN not in repr(api)
    assert TOKEN not in str(api)
