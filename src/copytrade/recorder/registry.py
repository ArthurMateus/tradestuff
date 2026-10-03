"""Local wallet registry (F4.AC2, D2): every wallet ever seen stays. There is no removal API."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

REGISTRY_FILENAME = "wallets.txt"
_WALLET = re.compile(r"0x[0-9a-fA-F]{40}")
_O_BINARY = getattr(os, "O_BINARY", 0)


def _fsync_directory(directory: Path) -> None:
    """Make a newly created file's directory entry durable (POSIX; Windows has no directory fsync)."""
    if sys.platform == "win32":  # pragma: no cover
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class WalletRegistry:
    """Persistent set of lower-case wallet addresses under ``directory`` (created if needed).

    ``add`` ignores anything that is not a 0x + 40-hex address. State survives a new instance over the same directory.

    Storage: one file, one address per line, only ever appended to and fsynced before ``add`` returns. A line torn by a
    crash is ignored on load and never merged with the next append. Single writer.
    """

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._path = directory / REGISTRY_FILENAME
        self._wallets: set[str] = set()
        self._needs_newline = False
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            raw = b""
        for line in raw.decode("utf-8", errors="replace").split("\n"):
            if _WALLET.fullmatch(line):
                self._wallets.add(line.lower())
        self._needs_newline = bool(raw) and not raw.endswith(b"\n")

    def add(self, wallets: Iterable[str]) -> int:
        """Add wallets; return how many were new. Durable before returning."""
        fresh: dict[str, None] = {}
        for wallet in wallets:
            if type(wallet) is str and _WALLET.fullmatch(wallet):
                key = wallet.lower()
                if key not in self._wallets:
                    fresh[key] = None
        if not fresh:
            return 0
        text = ("\n" if self._needs_newline else "") + "".join(f"{wallet}\n" for wallet in fresh)
        is_new = not self._path.exists()
        fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_BINARY, 0o600)
        try:
            data = memoryview(text.encode("ascii"))
            while data:
                data = data[os.write(fd, data) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        if is_new:
            _fsync_directory(self._path.parent)
        self._needs_newline = False
        self._wallets.update(fresh)
        return len(fresh)

    def wallets(self) -> frozenset[str]:
        return frozenset(self._wallets)


@dataclass(frozen=True)
class WindowFigures:
    """The ``pnl`` and ``vlm`` of one ``windowPerformances`` entry (``None`` when missing, unparsable or not finite)."""

    pnl: Decimal | None
    vlm: Decimal | None


@dataclass(frozen=True)
class LeaderboardRow:
    """What a leaderboard row offers a prefilter: the lower-cased address, the self-reported ``accountValue`` and the
    ``pnl`` / ``vlm`` of each performance window by name (``day``, ``week``, ``month``, ``allTime``). A figure is
    ``None`` when it is missing or unreadable. The row only saves a fetch; it never scores or admits a wallet. The
    ``roi`` field is never read (its denominator is undocumented)."""

    address: str
    account_value: Decimal | None
    windows: Mapping[str, WindowFigures] = field(default_factory=dict)


def _finite_decimal(raw: object) -> Decimal | None:
    if not isinstance(raw, str):
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _windows(raw: object) -> dict[str, WindowFigures]:
    """``windowPerformances`` is a list of ``[name, {pnl, roi, vlm}]`` pairs; anything else yields no window."""
    if not isinstance(raw, list):
        return {}
    out: dict[str, WindowFigures] = {}
    for item in raw:
        if isinstance(item, list | tuple) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], dict):
            out[item[0]] = WindowFigures(_finite_decimal(item[1].get("pnl")), _finite_decimal(item[1].get("vlm")))
    return out


def rows_in_leaderboard(body: bytes) -> tuple[LeaderboardRow, ...]:
    """Every row of ``leaderboardRows`` that has an ``ethAddress``, in order.

    Raises:
        ValueError: ``body`` is not JSON or has no ``leaderboardRows`` list.
    """
    try:
        document = json.loads(body)
    except (ValueError, RecursionError) as exc:  # UnicodeDecodeError is a ValueError
        raise ValueError("the leaderboard body is not JSON") from exc
    rows = document.get("leaderboardRows") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise ValueError("the leaderboard body has no leaderboardRows list")  # noqa: TRY004 - ValueError is the contract
    return tuple(
        LeaderboardRow(
            row["ethAddress"].lower(),
            _finite_decimal(row.get("accountValue")),
            _windows(row.get("windowPerformances")),
        )
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("ethAddress"), str)
    )


def wallets_in_leaderboard(body: bytes) -> tuple[str, ...]:
    """The ``ethAddress`` of every row of ``leaderboardRows`` in a leaderboard JSON body, lower-cased, in order.

    Raises:
        ValueError: ``body`` is not JSON or has no ``leaderboardRows`` list.
    """
    return tuple(row.address for row in rows_in_leaderboard(body))
