"""The risk state that must survive a restart (A4, F10.AC5, F10.AC6), and its file.

The file is one small JSON object written atomically (temp file, fsync, rename, directory fsync), so a crash leaves
either the old state or the new one, never a torn mix. Money is stored as decimal text. Anything that does not parse
into exactly the expected shape is ``RiskStateError``: a state that cannot be trusted is never guessed at.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from copytrade.risk.errors import RiskStateError

MS_PER_DAY = 86_400_000
DAYS_PER_WEEK = 7
_EPOCH_WEEKDAY = 3  # 1970-01-01 was a Thursday; Monday is 0
_VERSION = 1
_O_BINARY = getattr(os, "O_BINARY", 0)
_FIELDS = frozenset(
    {
        "version",
        "manual_pause",
        "drawdown_pause",
        "peak_equity_usd",
        "day_start_ms",
        "day_open_equity_usd",
        "daily_halt_until_ms",
        "week_start_ms",
        "week_open_equity_usd",
        "weekly_halt_until_ms",
    }
)


def utc_day_start_ms(time_ms: int) -> int:
    """00:00 UTC of the day holding ``time_ms`` (epoch milliseconds)."""
    return time_ms - time_ms % MS_PER_DAY


def utc_week_start_ms(time_ms: int) -> int:
    """Monday 00:00 UTC of the week holding ``time_ms``."""
    day = time_ms // MS_PER_DAY
    return (day - (day + _EPOCH_WEEKDAY) % DAYS_PER_WEEK) * MS_PER_DAY


@dataclass(frozen=True)
class RiskState:
    """Pause flags, peak equity and the opening equity and halt of the current UTC day and week.

    A halt is active while exchange time is before its ``*_halt_until_ms``; it expires by time, never by a mark.
    """

    manual_pause: bool = False
    drawdown_pause: bool = False
    peak_equity_usd: Decimal | None = None
    day_start_ms: int | None = None
    day_open_equity_usd: Decimal | None = None
    daily_halt_until_ms: int | None = None
    week_start_ms: int | None = None
    week_open_equity_usd: Decimal | None = None
    weekly_halt_until_ms: int | None = None

    @property
    def paused(self) -> bool:
        """Whether the kill switch (manual) or the drawdown pause is on."""
        return self.manual_pause or self.drawdown_pause

    def daily_halt_active(self, now_ms: int) -> bool:
        return self.daily_halt_until_ms is not None and now_ms < self.daily_halt_until_ms

    def weekly_halt_active(self, now_ms: int) -> bool:
        return self.weekly_halt_until_ms is not None and now_ms < self.weekly_halt_until_ms


def load_state(path: Path) -> RiskState:
    """The stored state, or a fresh running state when there is no file (a first start).

    Raises:
        RiskStateError: the file exists but cannot be read or is not a valid state.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return RiskState()
    except OSError as exc:
        raise RiskStateError("the risk state file cannot be read") from exc
    try:
        return _decode(json.loads(raw.decode("utf-8"), parse_float=_reject, parse_constant=_reject))
    except (UnicodeDecodeError, ValueError, TypeError, InvalidOperation) as exc:
        raise RiskStateError("the risk state file is not a valid state") from exc


def save_state(path: Path, state: RiskState) -> None:
    """Write ``state`` atomically and durably.

    Raises:
        RiskStateError: the write failed (the old file is then untouched).
    """
    data = json.dumps(_encode(state), sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    temp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_BINARY, 0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise RiskStateError("the risk state file cannot be written") from exc


def _fsync_directory(directory: Path) -> None:
    if sys.platform == "win32":  # pragma: no cover - a directory cannot be opened for fsync on Windows
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _reject(_: str) -> Any:
    raise ValueError("the state holds no floats or non-finite numbers")


def _money_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _encode(state: RiskState) -> dict[str, Any]:
    return {
        "version": _VERSION,
        "manual_pause": state.manual_pause,
        "drawdown_pause": state.drawdown_pause,
        "peak_equity_usd": _money_text(state.peak_equity_usd),
        "day_start_ms": state.day_start_ms,
        "day_open_equity_usd": _money_text(state.day_open_equity_usd),
        "daily_halt_until_ms": state.daily_halt_until_ms,
        "week_start_ms": state.week_start_ms,
        "week_open_equity_usd": _money_text(state.week_open_equity_usd),
        "weekly_halt_until_ms": state.weekly_halt_until_ms,
    }


def _flag(raw: dict[str, Any], key: str) -> bool:
    value = raw[key]
    if type(value) is not bool:
        raise ValueError(f"{key} must be a boolean")
    return value


def _millis(raw: dict[str, Any], key: str) -> int | None:
    value = raw[key]
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{key} must be a non-negative integer or null")
    return value


def _equity(raw: dict[str, Any], key: str) -> Decimal | None:
    value = raw[key]
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"{key} must be decimal text or null")
    amount = Decimal(value)
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{key} must be a positive finite amount")
    return amount


def _decode(raw: object) -> RiskState:
    if not isinstance(raw, dict) or raw.keys() != _FIELDS or raw["version"] != _VERSION:
        raise ValueError("the state does not have the expected fields")
    state = RiskState(
        manual_pause=_flag(raw, "manual_pause"),
        drawdown_pause=_flag(raw, "drawdown_pause"),
        peak_equity_usd=_equity(raw, "peak_equity_usd"),
        day_start_ms=_millis(raw, "day_start_ms"),
        day_open_equity_usd=_equity(raw, "day_open_equity_usd"),
        daily_halt_until_ms=_millis(raw, "daily_halt_until_ms"),
        week_start_ms=_millis(raw, "week_start_ms"),
        week_open_equity_usd=_equity(raw, "week_open_equity_usd"),
        weekly_halt_until_ms=_millis(raw, "weekly_halt_until_ms"),
    )
    if (state.day_start_ms is None) != (state.day_open_equity_usd is None):
        raise ValueError("the day start and the day's opening equity go together")
    if (state.week_start_ms is None) != (state.week_open_equity_usd is None):
        raise ValueError("the week start and the week's opening equity go together")
    return state
