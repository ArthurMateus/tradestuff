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

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from collections.abc import Mapping


class SecretValue:
    """A secret string that never reveals itself except through ``reveal()``."""

    def __init__(self, value: str) -> None:
        raise NotImplementedError

    def reveal(self) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError


class Secrets:
    """All secrets the engine uses. Each attribute is a ``SecretValue`` or ``None`` when unset."""

    telegram_token: SecretValue | None
    telegram_pin_hash: SecretValue | None
    telegram_pin_salt: SecretValue | None
    llm_api_key: SecretValue | None
    storage_endpoint: SecretValue | None
    storage_bucket: SecretValue | None
    storage_key_id: SecretValue | None
    storage_secret_key: SecretValue | None
    backup_encryption_key: SecretValue | None

    def __repr__(self) -> str:
        raise NotImplementedError


def load_secrets(env: Mapping[str, str]) -> Secrets:
    """Read the secrets from ``env`` only (the caller passes ``os.environ``). Never reads files."""
    raise NotImplementedError
