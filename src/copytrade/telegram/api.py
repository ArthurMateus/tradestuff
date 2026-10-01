"""A minimal Telegram Bot API client over the standard library (F14).

No retries here (the bot's queue owns backoff). Every request has a timeout. The token is only used to build the
request path: it is never in an exception message, a ``repr`` or a log line, and any text echoed from a server
reply is scrubbed of it.
"""

from __future__ import annotations

import http.client
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from copytrade.core.errors import CopytradeError
from copytrade.core.secrets import SecretValue

_log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 5.0
_MAX_BODY_BYTES = 4 * 1024 * 1024
_DEFAULT_RETRY_AFTER_S = 1
_DESCRIPTION_CAP = 200


class TelegramError(CopytradeError):
    """Any failed Telegram call."""


class TelegramUnavailable(TelegramError):  # noqa: N818 - names pinned by the F14 plan
    """Network failure, timeout or a 5xx: retry later."""


class TelegramRateLimited(TelegramError):  # noqa: N818 - names pinned by the F14 plan
    """HTTP 429: wait ``retry_after_s`` seconds."""

    def __init__(self, message: str, *, retry_after_s: int) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class TelegramRejected(TelegramError):  # noqa: N818 - names pinned by the F14 plan
    """Any other 4xx (bad chat, bad token, bad request): retrying the same call cannot help."""


@dataclass(frozen=True)
class Update:
    """One incoming text-capable message. ``text`` is ``None`` for a message without text (sticker, photo)."""

    update_id: int
    user_id: int
    chat_id: int
    message_id: int
    text: str | None


class TelegramApi:
    def __init__(self, base_url: str, token: SecretValue, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must be an http(s) URL")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout_s = timeout_s

    def __repr__(self) -> str:
        return f"TelegramApi(base_url={self._base!r}, token=<redacted>)"

    __str__ = __repr__

    def redact(self, text: str) -> str:
        """``text`` with the bot token removed."""
        return text.replace(self._token.reveal(), "<redacted>")

    # ------------------------------------------------------------------------------------------------ methods

    def send_message(self, chat_id: int, text: str) -> int:
        result = self._call("sendMessage", {"chat_id": chat_id, "text": text})
        try:
            return int(result["message_id"])
        except (KeyError, TypeError, ValueError):
            raise TelegramRejected("telegram reply carried no message_id") from None

    def edit_message_text(self, chat_id: int, message_id: int, text: str) -> None:
        self._call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})

    def delete_message(self, chat_id: int, message_id: int) -> None:
        self._call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    def get_updates(self, offset: int, *, timeout_s: int = 0) -> list[Update]:
        payload = {"offset": offset, "timeout": timeout_s, "allowed_updates": ["message"]}
        result = self._call("getUpdates", payload, http_timeout_s=self._timeout_s + timeout_s)
        if not isinstance(result, list):
            raise TelegramRejected("telegram getUpdates reply is not a list")
        updates = []
        for raw in result:
            update = _parse_update(raw)
            if update is not None:
                updates.append(update)
        return updates

    # ------------------------------------------------------------------------------------------------ transport

    def _call(self, method: str, payload: dict[str, Any], *, http_timeout_s: float | None = None) -> Any:
        url = f"{self._base}/bot{self._token.reveal()}/{method}"
        request = urllib.request.Request(  # noqa: S310 - the scheme is validated in the constructor
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = self._timeout_s if http_timeout_s is None else http_timeout_s
        try:
            status, body = self._post(request, timeout)
        except (OSError, http.client.HTTPException) as exc:
            # ``from None``: the chained error carries the URL (and so the token).
            raise TelegramUnavailable(f"telegram {method} unreachable ({type(exc).__name__})") from None
        return self._interpret(method, status, body)

    @staticmethod
    def _post(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.status, response.read(_MAX_BODY_BYTES)
        except urllib.error.HTTPError as err:
            try:
                return err.code, err.read(_MAX_BODY_BYTES)
            finally:
                err.close()

    def _interpret(self, method: str, status: int, body: bytes) -> Any:
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            data = {}
        if status == 200 and data.get("ok") is True:
            return data.get("result")
        description = self.redact(str(data.get("description", "")))[:_DESCRIPTION_CAP]
        if status == 429:
            raise TelegramRateLimited(f"telegram {method} rate limited", retry_after_s=_retry_after(data))
        if status >= 500 or (status == 200 and not data):
            raise TelegramUnavailable(f"telegram {method} failed with HTTP {status}")
        raise TelegramRejected(f"telegram {method} rejected (HTTP {status}): {description}")


def _retry_after(data: dict[str, Any]) -> int:
    parameters = data.get("parameters")
    value = parameters.get("retry_after") if isinstance(parameters, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return _DEFAULT_RETRY_AFTER_S


def _parse_update(raw: Any) -> Update | None:
    """The update as an ``Update``, or ``None`` for anything that is not a plain message from a user."""
    if not isinstance(raw, dict):
        return None
    message = raw.get("message")
    if not isinstance(message, dict):
        return None
    sender, chat = message.get("from"), message.get("chat")
    update_id, message_id = raw.get("update_id"), message.get("message_id")
    user_id = sender.get("id") if isinstance(sender, dict) else None
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    if not (
        isinstance(update_id, int)
        and isinstance(user_id, int)
        and isinstance(chat_id, int)
        and isinstance(message_id, int)
    ):
        return None
    text = message.get("text")
    return Update(update_id, user_id, chat_id, message_id, text if isinstance(text, str) else None)
