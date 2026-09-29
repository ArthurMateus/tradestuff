"""Error types raised by the platform core (F1)."""

from __future__ import annotations

MODE_NOT_PERMITTED_MESSAGE = "mode not permitted in this build"


class CopytradeError(Exception):
    """Base class for every error raised deliberately by copytrade."""


class ConfigError(CopytradeError):
    """The config tree is invalid (F1.AC1, F1.AC2, F1.AC5).

    Attributes:
        key: the dotted §3 key at fault (e.g. ``"risk.per_trade_fraction"``), or ``None`` when the
            fault is not tied to one key (unreadable directory, TOML syntax error).
        file: the config file at fault, when known (relative POSIX path or file name).

    ``str(error)`` names the key (and the file when known). It never contains a config value that
    matched the secret-key pattern.
    """

    def __init__(self, message: str, *, key: str | None = None, file: str | None = None) -> None:
        where = [f"key: {key}"] if key is not None else []
        if file is not None:
            where.append(f"file: {file}")
        super().__init__(f"{message} ({', '.join(where)})" if where else message)
        self.key = key
        self.file = file


class ModeNotPermittedError(ConfigError):
    """``mode`` is anything other than ``paper`` (F1.AC3).

    ``str(error)`` contains the exact phrase ``mode not permitted in this build`` and ``key == "mode"``.
    """

    def __init__(self, *, file: str | None = None) -> None:
        super().__init__(MODE_NOT_PERMITTED_MESSAGE, key="mode", file=file)


class EnginePathError(CopytradeError):
    """A file the engine imports or opens is outside the engine path set (F1.AC7).

    Attributes:
        path: the offending file (relative POSIX path when inside the root, else absolute). Also named
            in ``str(error)``.
    """

    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(f"{message}: {path}")
        self.path = path


class ClockUnsyncedError(CopytradeError):
    """The clock offset has never been estimated, so no exchange-corrected time exists (F1.AC6)."""
