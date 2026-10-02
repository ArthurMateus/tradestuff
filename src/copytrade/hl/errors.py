"""Errors raised by the Hyperliquid client (F3)."""

from __future__ import annotations

from copytrade.core.errors import CopytradeError


class HlError(CopytradeError):
    """Base class for every error raised by ``copytrade.hl``."""


class HlRequestError(HlError):
    """The request was refused locally and never sent (unknown or non-info request type, bad base URL)."""


class HlHttpError(HlError):
    """The server answered with a non-success HTTP status that is not retried (for example 403, 451, 500).

    Attributes:
        status: the HTTP status code.
    """

    status: int

    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


class HlRateLimitedError(HlError):
    """HTTP 429 persisted after ``hl.retry_max`` retries.

    Attributes:
        status: always 429 (so a log line can carry the status of any HTTP failure the same way).
    """

    status: int = 429


class HlTimeoutError(HlError):
    """The request timed out on the first attempt and on every one of ``hl.retry_max`` retries."""


class HlConnectionError(HlError):
    """The connection failed (not a timeout) on the first attempt and on every one of ``hl.retry_max`` retries."""


class HlBudgetError(HlError):
    """The request can never fit the rate budget of its priority class (for example scoring weight above its share)."""


class HlSchemaError(HlError):
    """The response is missing a field or has a wrong type; the whole response is rejected.

    Attributes:
        endpoint: the info request type (or ``"ws:<channel>"``).
        field: dotted path of the first offending field, e.g. ``"[3].tid"``.
    """

    endpoint: str
    field: str

    def __init__(self, message: str, *, endpoint: str, field: str) -> None:
        super().__init__(f"{endpoint}: {message}" + (f" (field: {field})" if field else ""))
        self.endpoint = endpoint
        self.field = field


class WsUserLimitError(HlError):
    """Subscribing one more distinct user would exceed ``hl.ws_max_unique_users``; nothing was sent."""
