"""F1.AC5: secrets come only from environment variables and never leak.

Canary values for every secret are injected for the whole suite (tests/conftest.py); the session
fails if any fragment appears in captured logs. These tests add targeted checks for the F1 surfaces:
the secrets object, log calls, exception traces, CLI output and config-file secrets.

Spec: 04-spec.md F1.AC5 (Amendment 1: storage credentials and backup key), invariant E2, §4 Security.
"""

from __future__ import annotations

import logging
import os
import traceback
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.config import load_config
from copytrade.core.errors import ConfigError
from copytrade.core.secrets import SecretValue, load_secrets
from copytrade.core.startup import startup
from tests.core.helpers import REPO_ROOT, ConfigTree, make_root, run_cli
from tests.harness import CANARY_SECRETS, find_canary_leaks

pytestmark = pytest.mark.unit

ATTRIBUTE_FOR_VAR = {
    "COPYTRADE_TELEGRAM_TOKEN": "telegram_token",
    "COPYTRADE_TELEGRAM_PIN_HASH": "telegram_pin_hash",
    "COPYTRADE_TELEGRAM_PIN_SALT": "telegram_pin_salt",
    "COPYTRADE_LLM_API_KEY": "llm_api_key",
    "COPYTRADE_STORAGE_ENDPOINT": "storage_endpoint",
    "COPYTRADE_STORAGE_BUCKET": "storage_bucket",
    "COPYTRADE_STORAGE_KEY_ID": "storage_key_id",
    "COPYTRADE_STORAGE_SECRET_KEY": "storage_secret_key",
    "COPYTRADE_BACKUP_ENCRYPTION_KEY": "backup_encryption_key",
}
assert set(ATTRIBUTE_FOR_VAR) == set(CANARY_SECRETS)


# --- environment only --------------------------------------------------------------------------------

@pytest.mark.parametrize(("var", "attr"), sorted(ATTRIBUTE_FOR_VAR.items()))
def test_F1_AC5_each_secret_is_read_from_its_environment_variable(var: str, attr: str, canary_secrets: dict[str, str]) -> None:
    secrets = load_secrets(canary_secrets)
    value = getattr(secrets, attr)
    assert isinstance(value, SecretValue)
    assert value.reveal() == canary_secrets[var]


def test_F1_AC5_secrets_come_only_from_the_given_environment_not_files_or_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # os.environ holds the canaries for the whole session, and a .env file sits in the working
    # directory: neither may be read when the caller passes an empty environment.
    (tmp_path / ".env").write_text("\n".join(f"{k}={v}" for k, v in CANARY_SECRETS.items()), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert os.environ["COPYTRADE_TELEGRAM_TOKEN"] == CANARY_SECRETS["COPYTRADE_TELEGRAM_TOKEN"]
    secrets = load_secrets({})
    assert all(getattr(secrets, attr) is None for attr in ATTRIBUTE_FOR_VAR.values())


def test_F1_AC5_empty_environment_variable_counts_as_unset(canary_secrets: dict[str, str]) -> None:
    env = {**canary_secrets, "COPYTRADE_LLM_API_KEY": ""}
    assert load_secrets(env).llm_api_key is None


# --- no leak through representations and logs ---------------------------------------------------------

def test_F1_AC5_secret_representations_never_contain_the_value(canary_secrets: dict[str, str]) -> None:
    secrets = load_secrets(canary_secrets)
    texts = [repr(secrets), str(secrets)]
    for attr in ATTRIBUTE_FOR_VAR.values():
        v = getattr(secrets, attr)
        texts += [repr(v), str(v), f"{v}", f"{v!r}", "{}".format(v), "%s" % v, "%r" % (v,)]
    leaks = find_canary_leaks("\n".join(texts))
    assert leaks == []


def test_F1_AC5_logging_secrets_at_any_level_never_emits_the_value(
    canary_secrets: dict[str, str], captured_log_text: Callable[[], str]
) -> None:
    secrets = load_secrets(canary_secrets)
    log = logging.getLogger("copytrade.test.secrets")
    before = len(captured_log_text())
    log.debug("secrets: %s", secrets)
    log.info("token: %s key: %r", secrets.telegram_token, secrets.storage_secret_key)
    log.warning(f"backup key {secrets.backup_encryption_key}")
    try:
        raise RuntimeError(f"upload failed for {secrets.storage_endpoint} / {secrets.storage_bucket}")
    except RuntimeError:
        log.exception("archive error")
    assert find_canary_leaks(captured_log_text()[before:]) == []


def test_F1_AC5_startup_failure_trace_and_cli_output_carry_no_secret(tmp_path: Path, canary_secrets: dict[str, str]) -> None:
    fake = make_root(tmp_path, ConfigTree().delete("risk.per_trade_fraction"))
    try:
        startup(fake.root, canary_secrets, code_root=REPO_ROOT, engine_module_files=[])
    except ConfigError:
        trace = traceback.format_exc()
    else:
        pytest.fail("startup accepted a config with a missing key")
    assert find_canary_leaks(trace) == []

    result = run_cli(["start", "--root", str(fake.root)])  # os.environ carries the canaries
    assert result.code != 0
    assert find_canary_leaks(result.stdout + result.stderr) == []


def test_F1_AC5_successful_startup_loads_secrets_without_logging_them(
    tmp_path: Path, canary_secrets: dict[str, str], captured_log_text: Callable[[], str]
) -> None:
    fake = make_root(tmp_path, ConfigTree())
    before = len(captured_log_text())
    result = startup(fake.root, canary_secrets, code_root=REPO_ROOT, engine_module_files=[])
    assert result.secrets.telegram_token is not None
    assert result.secrets.telegram_token.reveal() == canary_secrets["COPYTRADE_TELEGRAM_TOKEN"]
    assert find_canary_leaks(captured_log_text()[before:] + repr(result)) == []


# --- secret-looking keys in config files ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("telegram.bot_token", CANARY_SECRETS["COPYTRADE_TELEGRAM_TOKEN"]),
        ("telegram.pin", "1234"),
        ("telegram.pin", 1234),  # non-string, non-empty
        ("llm.api_key", CANARY_SECRETS["COPYTRADE_LLM_API_KEY"]),
        ("storage.secret_key", CANARY_SECRETS["COPYTRADE_STORAGE_SECRET_KEY"]),
        ("storage.SECRET", "x"),  # case-insensitive
        ("storage.backup.Api_Key", "x"),  # nested table
        ("vendor.refresh_token", "x"),  # outside any §3 area
    ],
    ids=lambda v: v if isinstance(v, str) and len(v) < 30 else "value",
)
def test_F1_AC5_config_file_with_a_secret_looking_key_fails_to_load_without_echoing_it(
    tmp_path: Path, key: str, value: Any
) -> None:
    config_dir = ConfigTree().set(key, value, file="leaky.toml").write(tmp_path / "config")
    with pytest.raises(ConfigError) as info:
        load_config(config_dir)
    assert info.value.key == key
    message = str(info.value) + repr(info.value) + "".join(traceback.format_exception(info.value))
    assert find_canary_leaks(message) == []
    if isinstance(value, str) and len(value) >= 4:
        assert value not in message


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("telegram.pin_max_attempts", 3),
        ("telegram.pin_lockout_min", 15),
        ("hl.ws_ping_interval_s", 20),
        ("llm.price_usd_per_1k_tokens.input", Decimal("0.003")),
    ],
)
def test_F1_AC5_schema_keys_that_match_the_secret_pattern_are_not_secrets(tmp_path: Path, key: str, value: Any) -> None:
    # Spec conflict flagged for the PM: the literal regex (?i)(token|secret|api_key|pin) matches these §3
    # keys. They are typed numbers (a string would fail the type check), so they must load.
    config = load_config(ConfigTree().set(key, value).write(tmp_path / "config"))
    assert config[key] == value
