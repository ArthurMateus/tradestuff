# Test plan: copytrade-v1

Author: test-designer · One section per feature; later features append theirs.

## How to run

| What | Command (from the repo root) |
|---|---|
| Install (pinned by `uv.lock`, Python from `.python-version`) | `uv sync` |
| Full suite | `uv run pytest` |
| Unit only / integration only | `uv run pytest -m unit` / `uv run pytest -m integration` |
| One feature | `uv run pytest tests/core` |

Works the same on Windows (PowerShell) and Linux. The suite needs no network, no keys and no services.

Suite-wide harness (`tests/conftest.py`, `tests/harness.py`; shared, and later changes go through the CTO):
- **Network guard.** Any DNS lookup or connection to a non-loopback host is blocked and recorded. The test that made the attempt fails, and so does the session. Loopback stays open for later features' local stubs.
- **Secret canaries.** All nine secret environment variables hold canary values for the whole session. Every log record is captured, and the session fails if any 12-character fragment of a canary appears. Later features register their own sinks (ledger, Telegram payloads, LLM prompts) in `SECRET_SINKS`.
- **Hypothesis** runs derandomized (profile `copytrade`), so failures reproduce on every machine.

I checked the harness itself: a test that swallows a blocked connection errors at teardown, and a canary written to a log makes `pytest` exit 1.

---

## F1 Platform core

Branch `feat/copytrade-v1/F1-core`. Tests are in `tests/core/`, fixtures in `tests/core/fixtures/`.

### Interface the tests fix (stubs raise `NotImplementedError`; the developer owns them)

| Module | Public surface |
|---|---|
| `copytrade.core.errors` | `CopytradeError`, `ConfigError(key, file)`, `ModeNotPermittedError(ConfigError)`, `EnginePathError(path)` |
| `copytrade.core.config` | `load_config(config_dir) -> Config`. `Config` is an immutable `Mapping` keyed by dotted §3 keys. |
| `copytrade.core.ceilings` | `Bounds(min, max, min_exclusive)`, `ceiling_for(key)`, and the constant `HIGH_LEVERAGE_COIN_UNIVERSE` |
| `copytrade.core.money` | `Price`, `Qty`, `Notional`, `Fee`, `Funding`, `Pnl` (all `Decimal` subclasses), `round_price(px, sz_decimals)`, `round_size(qty, sz_decimals)` |
| `copytrade.core.clock` | `TimeSource`, `Timestamp(ms, source)` with `from_datetime`/`to_datetime`, `Clock`, `SystemClock`, `OffsetEstimate`, `OffsetSource`, `ClockSync` (`tick`, `refusal_reason`, `exchange_now`, `from_config`) |
| `copytrade.core.domain` / `events` | `ActionKind` (OPEN, ADD, REDUCE, CLOSE); `Alert(kind, message)`, `AlertSink` |
| `copytrade.core.secrets` | `SecretValue`, `Secrets`, `load_secrets(env)`. The environment variable names are listed in the module docstring. |
| `copytrade.core.manifest` | `EnginePathSet` (`from_file`, `from_lines`, `patterns`, `covers`), `PathGuard` (`check`, `open_input`) |
| `copytrade.core.startup` | `startup(root, env, *, code_root, engine_module_files) -> StartupResult`. The check order is in the docstring. |
| `copytrade.cli.main` | `main(argv) -> int`, with the subcommand `start [--root PATH]` |

Scaffold: `pyproject.toml` (hatchling, src layout, with the dev group pytest, hypothesis and tomli-w), `uv.lock`, `.python-version` (3.11), and the `src/copytrade/{core,cli}` packages. The config format is **TOML**, read with the standard-library `tomllib` and `parse_float=Decimal`, so no binary float ever enters the config. Each area has one file in `config/`.

### Coverage matrix

| AC | Tests (`tests/core/…`) | Count |
|---|---|---|
| **F1.AC1** Config validation, no code defaults, key named, no network | `test_config_loader.py`: `valid_fixture_tree_loads_every_key_with_its_value`, `tables_split_across_files_merge`, `no_loaded_value_is_a_binary_float`, `loaded_config_is_immutable`, `missing_key_is_rejected_naming_it` [×314, one per §3 leaf], `empty_config_dir_is_rejected_naming_a_missing_key`, `missing_config_dir_is_rejected`, `wrong_type_is_rejected_naming_it` [×314], `nasty_wrong_types_are_rejected` [numeric strings, bool-as-int, fraction-as-int, string-as-list, wrong list elements], `nan_and_infinity_are_rejected`, `integer_literal_for_a_decimal_key_loads_as_decimal`, `empty_required_path_is_rejected`, `time_of_day_keys_validate_format`, `unknown_enum_value_is_rejected`, `negative_telegram_group_chat_id_loads`, `unicode_text_value_round_trips`, `malformed_toml_is_rejected_naming_the_file`, `same_key_in_two_files_is_rejected_naming_the_key`, `startup_with_invalid_config_names_the_key_and_opens_no_connection`, `cli_start_exits_nonzero_naming_the_key_without_network` [missing / wrong type / out of range] | 683 |
| **F1.AC2** Compiled ceilings and floors | `test_ceilings.py`: `value_equal_to_max_loads` + `value_one_step_above_max_is_rejected` [×141 each, every §3 Max], `value_equal_to_min_loads` + `value_one_step_below_min_is_rejected` [×187 each, every §3 Min, including the exclusive "> 0" floors], `required_ceiling_cases_are_rejected` [the 5 spec cases, verbatim], `required_floor_cases_are_rejected` [the 4 spec cases, verbatim], `fixed_key_rejects_any_other_value` [×84], `high_leverage_coins_accepts_any_subset_of_btc_eth_sol`, `high_leverage_coins_with_any_other_coin_is_rejected` [DOGE, lowercase, Cyrillic look-alike, trailing space, kPEPE], `high_leverage_coin_universe_is_a_compiled_constant`, `ceiling_constants_match_the_spec`, `price_floor_is_exclusive`, `config_cannot_raise_a_ceiling`, `environment_cannot_raise_a_ceiling`, `cross_key_bounds` [min/max followed, join/drop rank, blocks, DSR trials, cycle duration, disk alert vs floor, tier-1 vs floor], `score_weights_*`, `score_anchor_with_equal_lo_and_hi_is_rejected` | 799 |
| **F1.AC3** Paper only, no `/exchange` request, no signing client | `test_mode_paper_only.py`: `live_and_testnet_modes_fail_with_the_exact_message`, `any_mode_that_is_not_exactly_paper_is_refused` [case, whitespace, zero-width space, empty], `paper_mode_loads`, `startup_refuses_live_and_testnet`, `cli_start_exits_nonzero_with_the_exact_message`, `no_cli_flag_can_select_live_or_testnet`, `network_guard_blocks_and_records_any_request_to_the_exchange_endpoint`, `importing_every_engine_module_makes_no_network_attempt`, `static_scan_detects_a_signing_import_in_synthetic_source`, `no_engine_module_imports_an_order_signing_client`, `lockfile_pins_no_order_signing_distribution`, `importing_every_engine_module_loads_no_signing_module`. Also the session-wide network guard in `tests/conftest.py`. | 24 |
| **F1.AC4** Money is Decimal; tick and step rounding | `test_money.py`: `constructing_money_from_a_binary_float_raises`, `property_no_float_is_ever_accepted` (Hypothesis), `constructing_money_from_a_bool_raises`, `money_accepts_decimal_int_and_str_and_is_a_decimal`, `signed_money_accepts_negative_values`, `non_finite_or_malformed_money_raises`, `arithmetic_with_a_float_raises`, `property_money_round_trips_through_str`, `price_rounding_vectors` [the 2 spec vectors + 7], `price_above_five_significant_figures_uses_the_nearest_integer`, `property_rounded_price_is_valid_and_nearest`, `property_price_rounding_is_idempotent`, `non_positive_price_is_rejected`, `non_finite_price_is_rejected`, `price_rounding_refuses_a_float`, `out_of_range_sz_decimals_is_rejected`, `size_rounds_down_to_sz_decimals` [the spec vector + 7], `size_rounding_refuses_a_float`, `property_size_never_grows_and_loses_less_than_one_step`, `property_size_rounding_is_idempotent`, `property_size_rounding_is_monotonic` | 167 |
| **F1.AC5** Secrets from the environment only, never leaked | `test_secrets.py`: `each_secret_is_read_from_its_environment_variable` [all 9, including the storage credentials and backup key from Amendment 1], `secrets_come_only_from_the_given_environment_not_files_or_process_env` [`.env` file present, canaries in `os.environ`], `empty_environment_variable_counts_as_unset`, `secret_representations_never_contain_the_value`, `logging_secrets_at_any_level_never_emits_the_value`, `startup_failure_trace_and_cli_output_carry_no_secret`, `successful_startup_loads_secrets_without_logging_them`, `config_file_with_a_secret_looking_key_fails_to_load_without_echoing_it` [8 keys: case, nesting, non-string value], `schema_keys_that_match_the_secret_pattern_are_not_secrets` [see spec issue 1]. Also the session-wide canary check in `tests/conftest.py`. | 27 |
| **F1.AC6** UTC ms with a source tag; clock guard | `test_clock.py`: `timestamp_is_epoch_ms_with_a_source_tag`, `source_tags_are_exchange_local_derived`, `timestamp_rejects_non_integer_ms`, `timestamp_requires_a_timesource`, `naive_datetime_is_rejected`, `aware_datetime_in_another_zone_is_converted_to_utc`, `property_datetime_round_trip_preserves_ms_and_source`, `offset_is_estimated_on_first_tick_and_then_every_interval` [1 ms before, exactly at], `exchange_now_applies_the_offset_and_is_tagged_derived`, `from_config_uses_the_clock_keys`, `synced_clock_refuses_nothing`, `before_any_estimate_entries_are_refused_fail_closed`, `uncertainty_boundary` [99/100/101 ms], `high_uncertainty_refuses_entries_immediately_alerts_once_and_keeps_exits`, `estimate_age_boundary_and_single_alert_while_source_is_down` [1800 s allowed, 1801 s refused], `failing_offset_source_never_raises_out_of_tick`, `recovery_clears_the_refusal_and_a_new_episode_alerts_again` | 27 |
| **F1.AC7** Engine path set | `test_engine_path_set.py`: `committed_manifest_exists_at_the_repo_root`, `committed_manifest_lists_every_required_entry`, `committed_manifest_never_lists_docs_research_tests_or_storage_dirs` [including `storage.cache_dir`, Amendment 1], `committed_manifest_covers_the_real_engine_files`, `manifest_pattern_semantics` [×28: `..` escapes, prefix look-alikes, `.bak`], `windows_style_paths_are_normalised`, `absolute_paths_are_never_covered`, `comments_and_blank_lines_are_ignored`, `missing_manifest_fails_closed_naming_it`, `path_guard_opens_a_covered_data_input`, `path_guard_refuses_an_input_outside_the_set_naming_it`, `path_guard_refuses_a_file_outside_the_root`, `startup_passes_with_every_input_inside_the_set`, `startup_fails_closed_when_the_manifest_is_missing`, `startup_fails_closed_when_a_config_file_is_outside_the_set`, `startup_fails_closed_when_a_data_input_is_outside_the_set`, `startup_fails_closed_when_an_engine_module_is_outside_the_set`, `cli_start_names_an_imported_engine_module_outside_the_set` | 51 |

**Invariants touched:**

| Invariant | Tests |
|---|---|
| A2 fail closed | AC1 (every key), AC6 (fail closed before the first estimate), AC7 (missing manifest) |
| A3 limits in config under compiled ceilings | AC2 |
| A6 Decimal money and tick/step rounding | AC4, and AC1 `no_loaded_value_is_a_binary_float` |
| A9 explicit units | The money types in AC4 and `TimeSource` in AC6 (naming is also checked in review) |
| A10 paper only | AC3 |
| B1 and B2 staleness and UTC with a source tag | AC6 |
| E2 secrets | AC5 |

A1, A5, A7 and A8 are not touched by F1.

### Run summary (stub state, commit below)

- **1,778 tests collected, 1,771 failing, 7 passing.** There are 0 collection, import, syntax or fixture errors.
- **Why the failing tests fail:**
  - 1,766 raise `NotImplementedError` from the stubs.
  - 5 fail on an `AssertionError` about missing behaviour:
    - 4 because the committed `engine-path-set.txt` doesn't exist yet
    - 1 because `ceilings.HIGH_LEVERAGE_COIN_UNIVERSE` isn't defined yet
- **The 7 passing tests pass by design. None of them is vacuous:**
  - `F1_AC6_source_tags_are_exchange_local_derived` checks the `TimeSource` enum, which is part of the interface stub.
  - `F1_AC3_network_guard_blocks_and_records_any_request_to_the_exchange_endpoint` is the self-test of the suite-wide guard that enforces "0 `/exchange` requests".
  - `F1_AC3_static_scan_detects_a_signing_import_in_synthetic_source` proves the static scanner is not vacuous.
  - Four regression guards hold today and must keep holding: `no_engine_module_imports_an_order_signing_client`, `lockfile_pins_no_order_signing_distribution`, `importing_every_engine_module_loads_no_signing_module` and `importing_every_engine_module_makes_no_network_attempt`.

### What the suites prove, and what they don't

- **Unit suites (AC1, AC2, AC4, AC5, AC6)** cover:
  - the loader's contract over every §3 key: missing, wrong type, Min, Max, fixed and cross-key rules
  - money construction and rounding, with Hypothesis properties: valid and nearest, idempotent, monotonic, never grows
  - secret handling on F1's surfaces
  - the clock guard, driven by an injected fake clock and a fake offset source, with no sleeps
- **Integration suites (AC3, AC7, parts of AC1)** run the real startup path and the real `copytrade start` CLI in-process against a temporary repository root. They also scan the real source tree, lockfile and committed manifest. No Postgres or Redis exists in this project: the ledger is file-based, so none is used.
- **Deliberately not covered here:**
  - **The committed `config/` tree loading as a whole.** F1 owns only `config/platform.*` (§10), so the full tree can load only once every area's file exists. The F21 integration suite covers that, and the fixture tree stands in for it until then.
  - **Canary checks on the ledger, Telegram payloads and LLM prompts.** F2, F14 and F15 register their sinks in `SECRET_SINKS`.
  - **An HTTP-level `/exchange` stub on loopback** is left to F3, which owns the HTTP client.
  - **The real offset source** (exchange time or NTP) belongs to F3 and F21. **The real alert delivery** belongs to F14.
  - **The engine running on Windows** is F21.AC5, and **the latency of the clock gate** is F21.AC3 (simulation). The tests are written to be cross-platform: pathlib only, `PureWindowsPath` cases, explicit UTF-8, loopback-only sockets.
  - **Min-notional checks** are F11.AC4.

### Spec issues and interpretations for the PM or CTO

1. **Contradiction in F1.AC5.** The regex `(?i)(token|secret|api_key|pin)` matches four legitimate §3 keys: `telegram.pin_max_attempts`, `telegram.pin_lockout_min`, `hl.ws_ping_interval_s` and `llm.price_usd_per_1k_tokens.*`.
   - The tests exempt §3 schema keys, which are typed numbers, so a string secret would fail the type check anyway.
   - A secret-looking key outside the schema is rejected, and its value is never echoed.
   - **Ask:** the PM amends the AC wording to match.
2. **Environment variable names are not in the spec.** The tests fix them as `COPYTRADE_TELEGRAM_TOKEN`, `_TELEGRAM_PIN_HASH`, `_TELEGRAM_PIN_SALT`, `_LLM_API_KEY`, `_STORAGE_ENDPOINT`, `_STORAGE_BUCKET`, `_STORAGE_KEY_ID`, `_STORAGE_SECRET_KEY` and `_BACKUP_ENCRYPTION_KEY`. An empty variable counts as unset.
3. **Config ownership versus "every key present".** The F1 loader and its ceilings must know every §3 key, but other features own their `config/<area>.toml` files. Each feature adds its file; until they all exist, `copytrade start` on the committed tree fails closed by design.
4. **Unset thresholds** (`filter.*` in record-only mode) are written as the string `"unset"`, because TOML has no null and every key must be present.
5. **Price rounding** returns the *nearest valid* price, and integers are always valid. So 123456.7 rounds to 123457, not 123460. Size rounds toward zero, which for a negative quantity means its magnitude never grows. `sz_decimals` outside 0..6 is rejected.
6. **"Within 1 s"** is read as: the scheduler calls `ClockSync.tick()` at least once a second, and refusal is effective at the first tick after the condition. Before the first successful estimate, entries are refused (§5, "offset unknown").
7. **Mode** must be exactly `paper`: case-sensitive, with no whitespace. `live` and `testnet` give the exact message `mode not permitted in this build`.
8. **Unknown config keys:** the spec doesn't say whether they are allowed. The tests accept either behaviour. `okx.*` is absent from the fixture, because F22 is void under Amendment 3.
9. **Tooling:**
   - uv, with `uv.lock` as the lockfile named in the manifest, and Python pinned to 3.11 in `.python-version`.
   - No lint or mutation tool is configured yet; that is left to `/onboard`. `uvx ruff check` is clean for pyflakes errors.
   - Suggestion: mutmut needs `fork` and doesn't run on Windows natively, so cosmic-ray may be the better mutation tool for the PO's PC.
