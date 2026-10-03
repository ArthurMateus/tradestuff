"""Shared test-harness constants and helpers (F1). Imported by tests/conftest.py and by tests."""

from __future__ import annotations

# Each value is random-looking with no shared prefix, so any 12-character fragment is distinctive.
CANARY_SECRETS: dict[str, str] = {
    "COPYTRADE_TELEGRAM_TOKEN": "7355608:Qk3v9TzW1pLx8RmN4cYe2HsJ6uFa0DgB",
    "COPYTRADE_TELEGRAM_PIN_HASH": "c9f0f895fb98ab9159f51fd0297e236d8b1e2c6a",
    "COPYTRADE_TELEGRAM_PIN_SALT": "e4da3b7fbbce2345d7772b0674a318d5",
    "COPYTRADE_LLM_API_KEY": "sk-zq81Hc5MvW0nRt7YpKd2LsJ9XbFg4AeU",
    "COPYTRADE_STORAGE_ENDPOINT": "https://s3.r7k2q9w4m1z8.canary.invalid",
    "COPYTRADE_STORAGE_BUCKET": "bkt-u5y3t8r6e2w9q1",
    "COPYTRADE_STORAGE_KEY_ID": "K004d9e8c7b6a5f4e3d2c1b0a",
    "COPYTRADE_STORAGE_SECRET_KEY": "Zx9Cv8Bn7Mm6Ll5Kk4Jj3Hh2Gg1Ff0DdSsAa",
    "COPYTRADE_BACKUP_ENCRYPTION_KEY": "q2W3e4R5t6Y7u8I9o0P1a2S3d4F5g6H7j8K9l0Z=",
}

CANARY_FRAGMENT_LEN = 12


def canary_fragments(value: str) -> list[str]:
    """Every 12-character window of a canary value, minus windows that are generic URL scaffolding."""
    generic = ("https://", ".invalid", "canary.")
    frags = [value[i : i + CANARY_FRAGMENT_LEN] for i in range(len(value) - CANARY_FRAGMENT_LEN + 1)]
    return [f for f in frags if not any(g in f for g in generic)]


def find_canary_leaks(text: str) -> list[str]:
    """Names of the canary variables that have any distinctive fragment inside ``text``."""
    return [name for name, value in CANARY_SECRETS.items() if any(f in text for f in canary_fragments(value))]
