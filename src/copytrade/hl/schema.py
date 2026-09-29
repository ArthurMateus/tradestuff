"""Whole-response validation of Hyperliquid payloads (F3.AC6).

Numbers arrive as JSON strings and become exact ``Decimal`` money types; ids and times must be JSON integers.
A JSON float anywhere a number is expected is a schema failure, never silently converted (invariant A6).
Errors name the endpoint and the field path, never a payload value (which may be attacker controlled).
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from decimal import Decimal
from typing import Any, NoReturn, TypeVar

from copytrade.core.clock import Clock
from copytrade.core.events import Alert, AlertSink
from copytrade.core.money import Notional, Price, Qty
from copytrade.hl.errors import HlSchemaError
from copytrade.hl.models import BookLevel, Candle, ClearinghouseState, Fill, L2Book, LeaderPosition, PortfolioWindow

SCHEMA_FAILURE_ALERT = "schema_failure"
WS_FILLS_ENDPOINT = "ws:userFills"
ALERT_FAILURES = 3
ALERT_WINDOW_MS = 10 * 60_000
_MAX_MAGNITUDE_EXPONENT = 40  # values at or beyond 1e41 (or below 1e-41) are corrupt, and would overflow later maths
_SIDES = frozenset({"B", "A"})
_log = logging.getLogger(__name__)
_T = TypeVar("_T")
_D = TypeVar("_D", bound=Decimal)


def _key(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _idx(path: str, index: int) -> str:
    return f"{path}[{index}]"


class _Reader:
    """Typed accessors over decoded JSON that raise ``HlSchemaError`` for the first violation found."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def fail(self, path: str, expected: str) -> NoReturn:
        raise HlSchemaError(f"expected {expected}", endpoint=self.endpoint, field=path)

    def obj(self, value: Any, path: str) -> dict[str, Any]:
        if type(value) is not dict:
            self.fail(path, "a JSON object")
        return value

    def arr(self, value: Any, path: str) -> list[Any]:
        if type(value) is not list:
            self.fail(path, "a JSON array")
        return value

    def member(self, container: dict[str, Any], key: str, path: str) -> Any:
        if key not in container:
            self.fail(_key(path, key), "a required field")
        return container[key]

    def text(self, value: Any, path: str) -> str:
        if type(value) is not str:
            self.fail(path, "a string")
        return value

    def uint(self, value: Any, path: str) -> int:
        if type(value) is not int or value < 0:
            self.fail(path, "a non-negative JSON integer")
        return value

    def flag(self, value: Any, path: str) -> bool:
        if type(value) is not bool:
            self.fail(path, "a boolean")
        return value

    def decimal(self, value: Any, path: str, build: Callable[[str], _D], *, non_negative: bool = False) -> _D:
        if type(value) is not str:
            self.fail(path, "a decimal string")
        try:
            number = build(value)
        except (ValueError, TypeError, ArithmeticError):
            self.fail(path, "a finite decimal string")
        if not number.is_zero() and not -_MAX_MAGNITUDE_EXPONENT <= number.adjusted() <= _MAX_MAGNITUDE_EXPONENT:
            self.fail(path, "a decimal of plausible magnitude")
        if non_negative and number < 0:
            self.fail(path, "a non-negative decimal string")
        return number

    def price(self, value: Any, path: str) -> Price:
        return self.decimal(value, path, Price)

    def qty(self, value: Any, path: str, *, non_negative: bool = False) -> Qty:
        return self.decimal(value, path, Qty, non_negative=non_negative)

    def notional(self, value: Any, path: str) -> Notional:
        return self.decimal(value, path, Notional)

    def price_field(self, container: dict[str, Any], key: str, path: str) -> Price:
        return self.price(self.member(container, key, path), _key(path, key))

    def qty_field(self, container: dict[str, Any], key: str, path: str, *, non_negative: bool = False) -> Qty:
        return self.qty(self.member(container, key, path), _key(path, key), non_negative=non_negative)

    def text_field(self, container: dict[str, Any], key: str, path: str) -> str:
        return self.text(self.member(container, key, path), _key(path, key))

    def uint_field(self, container: dict[str, Any], key: str, path: str) -> int:
        return self.uint(self.member(container, key, path), _key(path, key))

    def fill(self, value: Any, path: str) -> Fill:
        raw = self.obj(value, path)
        side = self.text_field(raw, "side", path)
        if side not in _SIDES:
            self.fail(_key(path, "side"), "'B' or 'A'")
        return Fill(
            coin=self.text_field(raw, "coin", path),
            px=self.price_field(raw, "px", path),
            sz=self.qty_field(raw, "sz", path, non_negative=True),
            side=side,
            time_ms=self.uint_field(raw, "time", path),
            start_position=self.qty_field(raw, "startPosition", path),
            dir=self.text_field(raw, "dir", path),
            closed_pnl=self.qty_field(raw, "closedPnl", path),
            fee=self.qty_field(raw, "fee", path),
            crossed=self.flag(self.member(raw, "crossed", path), _key(path, "crossed")),
            oid=self.uint_field(raw, "oid", path),
            tid=self.uint_field(raw, "tid", path),
            hash=self.text_field(raw, "hash", path),
        )

    def fills(self, value: Any, path: str) -> tuple[Fill, ...]:
        return tuple(self.fill(item, _idx(path, i)) for i, item in enumerate(self.arr(value, path)))

    def book_level(self, value: Any, path: str) -> BookLevel:
        raw = self.obj(value, path)
        return BookLevel(
            px=self.price_field(raw, "px", path),
            sz=self.qty_field(raw, "sz", path, non_negative=True),
            n=self.uint_field(raw, "n", path),
        )

    def book_side(self, value: Any, path: str) -> tuple[BookLevel, ...]:
        return tuple(self.book_level(item, _idx(path, i)) for i, item in enumerate(self.arr(value, path)))

    def l2_book(self, payload: Any) -> L2Book:
        raw = self.obj(payload, "")
        levels = self.arr(self.member(raw, "levels", ""), "levels")
        if len(levels) != 2:
            self.fail("levels", "exactly two sides (bids, asks)")
        return L2Book(
            coin=self.text_field(raw, "coin", ""),
            time_ms=self.uint_field(raw, "time", ""),
            bids=self.book_side(levels[0], "levels[0]"),
            asks=self.book_side(levels[1], "levels[1]"),
        )

    def position(self, value: Any, path: str) -> LeaderPosition:
        wrapper = self.obj(value, path)
        raw_path = _key(path, "position")
        raw = self.obj(self.member(wrapper, "position", path), raw_path)
        entry = raw.get("entryPx")
        return LeaderPosition(
            coin=self.text_field(raw, "coin", raw_path),
            szi=self.qty_field(raw, "szi", raw_path),
            entry_px=None if entry is None else self.price(entry, _key(raw_path, "entryPx")),
        )

    def clearinghouse_state(self, payload: Any) -> ClearinghouseState:
        raw = self.obj(payload, "")
        summary = self.obj(self.member(raw, "marginSummary", ""), "marginSummary")
        positions = self.arr(self.member(raw, "assetPositions", ""), "assetPositions")
        return ClearinghouseState(
            account_value=self.notional(
                self.member(summary, "accountValue", "marginSummary"), "marginSummary.accountValue"
            ),
            positions=tuple(self.position(item, _idx("assetPositions", i)) for i, item in enumerate(positions)),
            time_ms=self.uint_field(raw, "time", ""),
        )

    def all_mids(self, payload: Any) -> dict[str, Price]:
        raw = self.obj(payload, "")
        return {coin: self.price(value, _key("", coin)) for coin, value in raw.items()}

    def candles(self, payload: Any) -> tuple[Candle, ...]:
        out: list[Candle] = []
        for i, item in enumerate(self.arr(payload, "")):
            path = _idx("", i)
            raw = self.obj(item, path)
            out.append(
                Candle(
                    open_ms=self.uint_field(raw, "t", path),
                    close_ms=self.uint_field(raw, "T", path),
                    coin=self.text_field(raw, "s", path),
                    interval=self.text_field(raw, "i", path),
                    open=self.price_field(raw, "o", path),
                    high=self.price_field(raw, "h", path),
                    low=self.price_field(raw, "l", path),
                    close=self.price_field(raw, "c", path),
                    volume=self.qty_field(raw, "v", path, non_negative=True),
                    trades=self.uint_field(raw, "n", path),
                )
            )
        return tuple(out)

    def user_role(self, payload: Any) -> str:
        return self.text_field(self.obj(payload, ""), "role", "")

    def series(self, value: Any, path: str, build: Callable[[Any, str], _T]) -> tuple[tuple[int, _T], ...]:
        out: list[tuple[int, _T]] = []
        for i, item in enumerate(self.arr(value, path)):
            pair_path = _idx(path, i)
            pair = self.arr(item, pair_path)
            if len(pair) != 2:
                self.fail(pair_path, "a [timestamp, value] pair")
            out.append((self.uint(pair[0], _idx(pair_path, 0)), build(pair[1], _idx(pair_path, 1))))
        return tuple(out)

    def portfolio(self, payload: Any) -> dict[str, PortfolioWindow]:
        windows: dict[str, PortfolioWindow] = {}
        for i, item in enumerate(self.arr(payload, "")):
            path = _idx("", i)
            pair = self.arr(item, path)
            if len(pair) != 2:
                self.fail(path, "a [window name, window] pair")
            name = self.text(pair[0], _idx(path, 0))
            if name in windows:
                self.fail(_idx(path, 0), "a unique window name")
            body_path = _idx(path, 1)
            body = self.obj(pair[1], body_path)
            windows[name] = PortfolioWindow(
                account_value_history=self.series(
                    self.member(body, "accountValueHistory", body_path),
                    _key(body_path, "accountValueHistory"),
                    self.notional,
                ),
                pnl_history=self.series(
                    self.member(body, "pnlHistory", body_path), _key(body_path, "pnlHistory"), self.qty
                ),
                volume=self.qty_field(body, "vlm", body_path, non_negative=True),
            )
        return windows


_PARSERS: dict[str, Callable[[_Reader, Any], Any]] = {
    "allMids": _Reader.all_mids,
    "l2Book": _Reader.l2_book,
    "clearinghouseState": _Reader.clearinghouse_state,
    "userFills": lambda reader, payload: reader.fills(payload, ""),
    "userFillsByTime": lambda reader, payload: reader.fills(payload, ""),
    "candleSnapshot": _Reader.candles,
    "userRole": _Reader.user_role,
    "portfolio": _Reader.portfolio,
}


def parse_response(request_type: str, payload: Any) -> Any:
    """Validate and convert the decoded JSON ``payload`` of info request ``request_type``.

    Returns: ``allMids`` -> ``dict[str, Price]``; ``l2Book`` -> ``L2Book``; ``clearinghouseState`` ->
    ``ClearinghouseState``; ``userFills`` / ``userFillsByTime`` -> ``tuple[Fill, ...]``; ``candleSnapshot`` ->
    ``tuple[Candle, ...]``; ``userRole`` -> ``str``; ``portfolio`` -> ``dict[str, PortfolioWindow]``.

    Raises:
        HlSchemaError: any missing field, wrong type (numbers must be JSON strings, ids and times JSON ints,
            JSON floats are wrong), non-finite or negative price, or unknown request type. Nothing is returned
            partially.
    """
    reader = _Reader(request_type)
    parser = _PARSERS.get(request_type)
    if parser is None:
        reader.fail("", "a known info request type")
    return parser(reader, payload)


def parse_ws_fills(message: Any) -> tuple[str, bool, tuple[Any, ...]]:
    """Validate a WS ``userFills`` channel message; return ``(user, is_snapshot, fills)``.

    Raises:
        HlSchemaError: endpoint ``"ws:userFills"``; the whole message is rejected.
    """
    reader = _Reader(WS_FILLS_ENDPOINT)
    raw = reader.obj(message, "")
    if reader.text_field(raw, "channel", "") != "userFills":
        reader.fail("channel", "the userFills channel")
    data = reader.obj(reader.member(raw, "data", ""), "data")
    user = reader.text_field(data, "user", "data")
    snapshot = data.get("isSnapshot", False)
    is_snapshot = reader.flag(snapshot, "data.isSnapshot")
    fills = reader.fills(reader.member(data, "fills", "data"), "data.fills")
    return user, is_snapshot, fills


class SchemaFailureMonitor:
    """Counts schema failures per endpoint; the 3rd within 10 minutes on one endpoint sends one alert
    (kind ``schema_failure``, message naming the endpoint). Further failures in the same episode send none.

    An episode ends when the endpoint's failures in the trailing window drop below the threshold, so a
    sustained failure raises one alert, and a later, separate burst raises another.
    """

    def __init__(self, *, clock: Clock, alerts: AlertSink) -> None:
        self._clock = clock
        self._alerts = alerts
        self._failures: dict[str, deque[int]] = {}
        self._alerted: set[str] = set()

    def record_failure(self, endpoint: str) -> None:
        now = self._clock.now_ms()
        failures = self._failures.setdefault(endpoint, deque())
        while failures and now - failures[0] >= ALERT_WINDOW_MS:
            failures.popleft()
        if len(failures) < ALERT_FAILURES:
            self._alerted.discard(endpoint)
        failures.append(now)
        if len(failures) >= ALERT_FAILURES and endpoint not in self._alerted:
            self._send_alert(endpoint, len(failures))

    def _send_alert(self, endpoint: str, count: int) -> None:
        message = f"{count} schema failures within 10 minutes on {endpoint}: responses are being rejected"
        try:
            self._alerts.send(Alert(kind=SCHEMA_FAILURE_ALERT, message=message))
        except OSError as exc:
            _log.warning(
                "schema failure alert delivery failed; retrying on the next failure",
                extra={"event": "schema_alert_failed", "endpoint": endpoint, "error_type": type(exc).__name__},
            )
            return
        self._alerted.add(endpoint)
