"""Config loader (F1.AC1, F1.AC2, F1.AC5).

Contract:
- The config tree is every ``*.toml`` file directly under ``config_dir``, one file per area
  (§10 collision rule 1). Tables with the same name in different files merge; the same leaf key in
  two files is a ``ConfigError`` naming that key.
- Values are parsed with Decimal for TOML floats. No loaded value is ever a binary ``float``.
- Every §3 key must be present (no code defaults). A missing key, a wrong type or a value outside
  the compiled [Min, Max] (``copytrade.core.ceilings``) raises ``ConfigError`` naming the key.
- A key whose name matches ``(?i)(token|secret|api_key|pin)`` with a non-empty value fails to load,
  unless it is a §3 key (the §3 keys ``telegram.pin_*``, ``hl.ws_ping_interval_s`` and
  ``llm.price_usd_per_1k_tokens.*`` are typed numbers, not secrets). The error never echoes the value.
- ``mode`` other than ``"paper"`` raises ``ModeNotPermittedError`` ("mode not permitted in this build").
- Keys are addressed by their dotted path, e.g. ``config["risk.per_trade_fraction"]``.

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any


class Config(Mapping[str, Any]):
    """Immutable, validated config. Maps dotted §3 keys to values (int, Decimal, str, bool, list)."""

    def __getitem__(self, key: str) -> Any:
        raise NotImplementedError

    def __iter__(self) -> Iterator[str]:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError


def load_config(config_dir: Path) -> Config:
    """Load and validate every ``*.toml`` file under ``config_dir``.

    Raises:
        ConfigError: missing, mistyped or out-of-range key; duplicate key; unreadable or malformed file;
            secret-looking key with a value.
        ModeNotPermittedError: ``mode`` is not ``paper``.
    """
    raise NotImplementedError
