"""Error types raised by the platform core (F1).

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations


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
        raise NotImplementedError


class ModeNotPermittedError(ConfigError):
    """``mode`` is anything other than ``paper`` (F1.AC3).

    ``str(error)`` contains the exact phrase ``mode not permitted in this build`` and ``key == "mode"``.
    """


class EnginePathError(CopytradeError):
    """A file the engine imports or opens is outside the engine path set (F1.AC7).

    Attributes:
        path: the offending file (relative POSIX path when inside the root, else absolute). Also named
            in ``str(error)``.
    """

    def __init__(self, message: str, *, path: str) -> None:
        raise NotImplementedError
