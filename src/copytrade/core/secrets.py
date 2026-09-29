"""Secrets from the environment only (F1.AC5, invariant E2).

The environment variables (and nothing else: no config file, no ``.env`` file) are:

==================================  ==========================
``COPYTRADE_TELEGRAM_TOKEN``        Telegram bot token
``COPYTRADE_TELEGRAM_PIN_HASH``     ``/flatten`` PIN hash
``COPYTRADE_TELEGRAM_PIN_SALT``     ``/flatten`` PIN salt
``COPYTRADE_LLM_API_KEY``           LLM API key
``COPYTRADE_STORAGE_ENDPOINT``      object-storage endpoint
``COPYTRADE_STORAGE_BUCKET``        object-storage bucket
``COPYTRADE_STORAGE_KEY_ID``        object-storage key ID
``COPYTRADE_STORAGE_SECRET_KEY``    object-storage secret key
``COPYTRADE_BACKUP_ENCRYPTION_KEY`` ledger-backup encryption key
==================================  ==========================

A missing or empty variable yields ``None``. Secret values are wrapped in ``SecretValue``, whose
``repr``/``str``/``format`` never contain the value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import NoReturn, Self

_REDACTED = "SecretValue(<redacted>)"


class SecretValue:
    """A secret string that never reveals itself except through ``reveal()``.

    It cannot be pickled, and copying returns the same immutable object.
    """

    __slots__ = ("_value",)
    _value: str

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("a secret must be a str")
        if not value:
            raise ValueError("a secret must not be empty")
        object.__setattr__(self, "_value", value)

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("SecretValue is immutable")

    def reveal(self) -> str:
        """Return the secret. Call it only where the value is actually used (never to log or format)."""
        return self._value

    def __repr__(self) -> str:
        return _REDACTED

    def __str__(self) -> str:
        return _REDACTED

    def __format__(self, format_spec: str) -> str:
        return format(_REDACTED, format_spec)

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        return self

    def __reduce__(self) -> NoReturn:
        raise TypeError("SecretValue cannot be pickled")


@dataclass(frozen=True, slots=True, repr=False)
class Secrets:
    """All secrets the engine uses. Each attribute is a ``SecretValue`` or ``None`` when unset."""

    telegram_token: SecretValue | None = None
    telegram_pin_hash: SecretValue | None = None
    telegram_pin_salt: SecretValue | None = None
    llm_api_key: SecretValue | None = None
    storage_endpoint: SecretValue | None = None
    storage_bucket: SecretValue | None = None
    storage_key_id: SecretValue | None = None
    storage_secret_key: SecretValue | None = None
    backup_encryption_key: SecretValue | None = None

    def __repr__(self) -> str:
        state = ", ".join(f"{f.name}={'set' if getattr(self, f.name) is not None else 'unset'}" for f in fields(self))
        return f"Secrets({state})"


ENV_VAR_FOR_FIELD: Mapping[str, str] = {
    "telegram_token": "COPYTRADE_TELEGRAM_TOKEN",
    "telegram_pin_hash": "COPYTRADE_TELEGRAM_PIN_HASH",
    "telegram_pin_salt": "COPYTRADE_TELEGRAM_PIN_SALT",
    "llm_api_key": "COPYTRADE_LLM_API_KEY",
    "storage_endpoint": "COPYTRADE_STORAGE_ENDPOINT",
    "storage_bucket": "COPYTRADE_STORAGE_BUCKET",
    "storage_key_id": "COPYTRADE_STORAGE_KEY_ID",
    "storage_secret_key": "COPYTRADE_STORAGE_SECRET_KEY",
    "backup_encryption_key": "COPYTRADE_BACKUP_ENCRYPTION_KEY",
}


def load_secrets(env: Mapping[str, str]) -> Secrets:
    """Read the secrets from ``env`` only (the caller passes ``os.environ``). Never reads files."""
    values: dict[str, SecretValue | None] = {}
    for attribute, variable in ENV_VAR_FOR_FIELD.items():
        raw = env.get(variable)
        values[attribute] = SecretValue(raw) if raw else None
    return Secrets(**values)
