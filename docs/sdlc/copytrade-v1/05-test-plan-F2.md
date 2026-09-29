# Test plan: F2 Append-only ledger and audit trail

Author: test-designer · Branch `feat/copytrade-v1/F2-ledger` · Spec: `04-spec.md` F2.AC1 to AC6 (+ Amendments), §3 (`ledger.heartbeat_interval_s`), §5 "Ledger append or verification failure", §10 ownership. Separate from the F1 `05-test-plan.md`.

## Interface stubs added (all bodies `raise NotImplementedError`; the developer owns them)
- `src/copytrade/ledger/{errors,records,store,export}.py`, `src/copytrade/cli/ledger.py`.
- `errors.py` has real (trivial) exception classes because tests read `LedgerCorruptError.seq`.
- Records are frozen dataclasses (`LedgerRecord`, `DecisionRecord`, `FillRecord`, `TradeRecord`, `RuleResult`, `RiskCheckResult`). Their docstrings state the validation the developer must add (the tests prove it).

## API the tests pin (my design; the spec is silent, see "Decisions needed")
- `Ledger.open(dir, *, clock)` -> single writer (OS lock), verifies whole chain, repairs an unterminated tail, raises `LedgerCorruptError(seq)` and logs ERROR on `copytrade.ledger`.
- `append(kind, payload, *, client_order_id=None)`, `append_decision/fill/trade`, `has_client_order_id`, `records`, `verify`, `last_seq`, `failed`, `close`, context manager.
- Read-only module functions that work while the writer runs: `verify_ledger(dir)`, `read_records(dir)`, `export_fills(dir, from_ms=, to_ms=, out=)`, `aggregate_trades(dir)`.
- Storage: one file `ledger.jsonl`, one `\n`-terminated line per record; `hash` = 64 hex; `h_n = sha256(bytes.fromhex(h_{n-1}) + canonical_bytes(rec_n))`, `GENESIS_HASH = "0"*64`.
- CLI: `copytrade ledger verify --ledger-dir D`; `copytrade export fills --ledger-dir D --from ISO --to ISO [--out F]`.

## Coverage matrix (AC -> tests)
Files: `tests/ledger/test_chain.py` (C), `test_payload.py` (P), `test_decisions.py` (D), `test_durability.py` (U), `test_export.py` (E), `test_cli.py` (L). All names are prefixed `test_F2_<AC>_`.

| AC | Tests |
|---|---|
| **F2.AC1** tamper evidence | C: `sequence_is_strictly_increasing_from_one`, `empty_ledger_is_valid_with_zero_records`, `hash_chain_follows_the_spec_formula`, `records_read_back_equal...`, `timestamp_is_the_injected_local_clock...`, `a_backwards_clock_never_breaks_the_sequence`, `the_api_offers_no_update_or_delete`, `chain_survives_close_and_reopen`, `verify_is_read_only_and_idempotent`, `canonical_bytes_*` (3), `every_byte_of_a_record_is_covered[first/middle/last]` (exhaustive single-byte flip), `altered_byte_names_the_sequence_number_engine_refuses_to_start_and_logs_an_alert`, `corruption_never_lets_a_writer_append`, `a_deleted_middle_record...`, `two_swapped_records...`, `a_replayed_duplicate_line...`, `a_terminated_garbage_line...`, `invalid_utf8_and_binary_noise...`, `read_records_stops_at_the_corrupt_record`, `property_any_payload_sequence_chains_verifies_and_round_trips`, `property_flipping_any_single_byte_fails_at_that_records_sequence_number`; P: payload rules (floats, NaN/Infinity Decimal, non-str keys, unserialisable, kind grammar, refused append leaves ledger usable, exact Decimal round-trip, hostile text/newlines/U+2028/NUL, 1 MB payload, empty payload, caller mutation); L: `cli_verify_passes/empty_or_missing/fails_non_zero_and_names_the_sequence_number` |
| **F2.AC2** decision record | D: `fifty_signals_yield_exactly_fifty_decision_records_with_no_null_field`, `all_eight_outcomes...`, `a_missing_required_field_is_refused[x15 fields]`, `empty_identity_text_is_refused`, `unknown_outcomes_are_refused`, `rejected_outcome_keeps_its_reason`, `timestamps_carry_the_right_source`, `clock_offset_must_be_an_int`, `negative_and_zero_clock_offsets...`, `latency_per_stage_must_be...`, `filter_and_risk_results_keep_input_threshold_and_result_exactly`, `a_signal_with_no_rules_evaluated...`, `sizes_and_price_are_exact_decimals`, `unicode_ids_and_reasons_round_trip`, `decode_refuses_records_of_another_kind`, `decisions_..._arrival_order...`, `the_same_signal_seen_twice_is_two_records` |
| **F2.AC3** crash durability | U: `force_killed_at_100_random_points_during_a_replay_of_1000_signals` (real subprocess, SIGKILL, seeded), `torn_final_write_is_dropped_on_restart_and_the_chain_continues`, `read_only_readers_ignore_a_torn_tail_without_touching_it`, `every_append_is_fsynced_before_it_returns`, `client_order_id_is_unique_and_a_duplicate_writes_nothing`, `client_order_ids_survive_a_restart`, `multiple_fills_may_share_one_client_order_id`, `client_order_id_check_is_exact_not_normalised`, `a_second_live_writer_is_refused`, `the_lock_is_released_on_close_so_restart_works`, `readers_work_while_the_writer_holds_the_ledger`, `opening_a_corrupt_ledger_does_not_leave_the_lock_held` |
| **F2.AC4** fill export | E: `header_is_exactly...`, `row_count_equals_the_number_of_fill_records_and_other_kinds_are_ignored`, `each_row_carries_the_fill_fields`, `time_is_iso_8601_utc...`, `decimal_strings_round_trip_exactly_and_are_never_scientific`, `range_is_from_inclusive_to_exclusive...` (boundaries lo-1, lo, hi-1, hi), `the_range_uses_fill_time...`, `out_of_order_fills...`, `a_duplicate_fill_record...`, `awkward_text_is_quoted...`, `empty_and_inverted_ranges`, `export_works_while_the_engine_holds_the_ledger`, `a_tampered_ledger_is_never_exported`, `property_every_decimal_in_every_row_round_trips_exactly`, `fill_validation`; L: `cli_export_fills_writes_the_csv_for_the_range_to_a_file`, `..._defaults_to_stdout`, `..._rejects_dates_that_are_not_explicit_utc_instants[x5]`, `..._refuses_a_tampered_ledger_and_writes_no_file` |
| **F2.AC5** honest aggregates | E: `aggregate_signature_has_no_parameter_that_could_exclude_records`, `totals_include_losers_and_every_flagged_kind` (hand-computed -1138.988, 9 trades, all six flags), `each_flag_alone_is_counted[x6]`, `empty_ledger_aggregates_to_zero`, `only_trade_records_are_aggregated`, `aggregate_is_exact_where_binary_float_would_drift`, `unknown_flag_is_refused...`, `aggregating_a_tampered_ledger_raises`, `property_aggregate_equals_the_plain_sum_over_all_trades_whatever_their_flags` |
| **F2.AC6** failed append | U: `an_fsync_failure_raises_to_the_caller_and_the_ledger_refuses_to_continue`, `append_never_returns_a_record_for_a_failed_write`, `a_real_disk_full_style_write_failure_raises_leaves_no_partial_record_and_recovers` (RLIMIT_FSIZE subprocess; POSIX only) |
| Invariants | A2 fail closed: AC6 + corruption tests (no writer on a corrupt ledger). A5: AC3 client-order-id tests. A6: payload float/NaN refusal, Decimal exactness. B5: AC2. E5: AC4. F1.AC5 canary: `P: F2_F1_AC5_*` (SecretValue refused; env canaries never appear in the ledger) plus the ledger is registered as a session-wide `SECRET_SINKS["ledger"]` from `tests/ledger/conftest.py` (no shared-file edit needed; every ledger dir created through the `ledger_dir` fixture is scanned at session end). |

## Run summary (against the stubs)
`uv run pytest tests/ledger`: **162 tests: 84 failed, 76 errors, 2 passed.** Full suite: F1's 1833 still pass (1835 passed total).
- Failure reasons: NotImplementedError from a stub (all `Ledger.open`, `verify_ledger`, `canonical_bytes`, `decode_*`, `export_fills`, `aggregate_trades`, `register`, and the worker subprocesses) and `DID NOT RAISE` assertions where the dataclass validation is not written yet (76 assertion-type failures). The 76 ERRORs are the same `NotImplementedError`, raised in the `ledger` fixture's `Ledger.open` (setup phase), not fixture bugs; they become plain tests once `open` exists.
- The 2 passing tests are structural guards over the stub signatures (`the_api_offers_no_update_or_delete`, `aggregate_signature_has_no_parameter_that_could_exclude_records`); they fail if the developer adds such a method or parameter.
- No import, syntax, collection or fixture-logic errors. ruff and mypy (strict) are clean on `src` and `tests`.
- **Validation of the tests themselves:** I ran the full suite against a throwaway reference implementation kept outside the repo (scratchpad, not committed): all 162 passed, including the 100-kill crash test and the RLIMIT test. This caught and fixed two bugs in my own tests (a hand-computed total, a Decimal `str` assumption).
- Runtime: about 10-15 s for the folder (crash test about 3 s).

## What this proves, and what it deliberately does not
- Proves: chain, tamper detection to the byte, fail-closed on corruption, crash and disk-full behaviour of the file layer, decision/fill/trade record content, CSV export exactness, honest aggregates.
- Not covered here:
  - **Engine wiring** ("the engine refuses to start", "halt all actions", downtime counted): F2 exposes `LedgerCorruptError`, `LedgerWriteError` and `Ledger.failed`; the supervisor behaviour is F21 (integration) and F13 (restart reconstruction).
  - **Recording ledger entries** (segment hashes, `data_gap`, tier tables, run records): F4, F9, F17, F23 through the generic `append`.
  - **Windows-specific file locking and fsync semantics:** tests are portable in design but ran on Linux only; QA on the PO's PC must run `tests/ledger`. The RLIMIT test skips without the `resource` module.
  - **Real power loss:** SIGKILL cannot lose OS-cached writes; fsync is proved by a spy, not by pulling the plug (QA / 24 h dry run).
  - **Tail truncation and whole-file replacement** are not detectable by a hash chain alone (deleting the last k complete records leaves a valid ledger). Mitigation is the daily encrypted backup and verified restore (F23.AC4), and a ledgered seq/hash anchor is an option (see decisions).
  - Performance and the 200 MB/day growth budget (F21).
  - `ledger.heartbeat_interval_s`: no F2 AC uses it (see decisions).

## Spec issues and decisions needed (PM/CTO)
1. **Heartbeat has no AC.** §3 gives F2 the key `ledger.heartbeat_interval_s` and §5 relies on "a heartbeat gap" to detect downtime, but no F2 AC defines a heartbeat record. Untested; needs an AC (or ownership moved to F21/F13).
2. **Decision fields for non-executed signals.** AC2 says "no required field null", yet a `duplicate`, `out_of_scope` or early-`rejected` signal has no real sizes or price. I required all fields, with sizes `0` and a `price_used` for every outcome. PM to confirm, or list which outcomes may carry null sizes/price.
3. **Client order ID scope.** AC3 says each client order ID appears at most once. I enforce that only for records appended with `client_order_id=` (orders); fill records may repeat it (partial fills, A8). Confirm.
4. **Export range semantics:** half-open `[from, to)` on the fill's own time (not append time), ledger order, ISO-8601 `Z` with milliseconds; the CLI requires explicit UTC. Confirm (tax users may prefer sorted-by-time).
5. **Trailing-newline ambiguity:** flipping the last byte (the final `\n`) of the last record is indistinguishable from a torn write. The AC1 exhaustive byte test exempts only that one byte. Alternative if the PM wants literal "any byte": a ledgered tail anchor.
6. **Trade record shape** (AC5) is my design: `trade_id, share_id, coin, closed_at, pnl_usd (net), flags`. F11/F12 will produce these; whether `pnl_usd` is net of fees and funding must be fixed there. Double-counting a re-appended `trade_id` is not prevented by F2 (not in the AC).
7. **Single-writer lock** and read-only verify/export while the engine runs are my additions (needed so the CLI works on a live ledger, and so two engines cannot fork the chain).
8. **CLI ledger directory** is passed as `--ledger-dir`; defaulting it from `storage.ledger_dir` in config is left to the developer/F21 (untested).

## Shared-file note
No shared file was edited. The ledger sink is registered from `tests/ledger/conftest.py` via the public `SECRET_SINKS` dict, so no CTO-serialized commit is needed. If the CTO prefers registering it in `tests/conftest.py`, it is a two-line change.

## Round 2 (mutation-driven additions)
New files only: `tests/ledger/test_canonical_form.py` (AC1) and `tests/ledger/test_exactness_and_failures.py` (AC4, AC5, AC6). 78 new tests: 69 pass on 4680d36, **9 fail on purpose** until the developer fixes three defects:
- 5x AC5 `aggregate_trades` on pathological Decimals (`1E+2000` + 1, overflow, span wider than the 1000-digit context) leaks a raw `decimal.Rounded`/`Inexact`; must be a `LedgerError`.
- 1x AC6 `_write_durably` spins forever if `os.write` returns 0; must raise `OSError` (surfaced as `LedgerWriteError`, ledger failed). The test caps retries at 100 and fails instead of hanging.
- 3x AC4 CLI `export fills` with an instant whose UTC conversion leaves years 1..9999 (`0001-01-01T00:00:00+05:00`, `9999-12-31T23:59:59-05:00`) raises `OverflowError`; must be an argparse error (exit 2, no traceback).

| Mutant | Killed by |
|---|---|
| drop `encode_line(record) != line` check | `test_F2_AC1_non_canonical_rewrite_with_a_valid_hash_...` (11 rewrites x 3 seqs: whitespace, reordered keys, duplicate key, `\u` escapes, `\r`, `-0`) |
| no `$` escape on encode / no unescape on decode | `test_F2_AC1_dollar_keys_*`, property round-trip, forged-line test |
| accept bare `$foo` / `$dec` with siblings | `test_F2_AC1_decoding_an_unescaped_reserved_key_is_refused`, `..._malformed_stored_decimal_marker_is_refused`, forged-line verify test |
| aggregate with 28-digit context | `test_F2_AC5_a_sum_needing_more_than_28_...`, `..._tiny_loss_next_to_a_huge_gain...`, rational-sum property |
| no rollback / wrong rollback size / id recorded before write / `_size` not advanced | `test_F2_AC6_a_failed_append_is_rolled_back_...` (rollback fsync ok and also failing), partial-write test |
| no BaseException latch | `test_F2_AC6_a_base_exception_during_an_append_latches_...` (fsync, write) |
| depth guard off / off-by-one both ways (encode, decode) / RecursionError unmapped | `test_F2_AC1_nesting_exactly_at_the_limit_...`, `..._absurdly_deep_...`, too-deep append, deep stored line |

Mutants ran in a scratch copy outside the repo with `pytest -o pythonpath=<mutant src>`.
