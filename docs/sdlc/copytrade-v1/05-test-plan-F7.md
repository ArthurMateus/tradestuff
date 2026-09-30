# Test plan F7: Signal detection

Epic copytrade-v1, branch `feat/copytrade-v1/F7-signals` (PAIR pass with F4, cost rule 4). Spec: `04-spec.md` F7.AC1..AC6, §1 definitions, §3 keys (`markets.allowed_dexes`, `clock.max_offset_uncertainty_ms`, `latency.*`), §4 latency table (S1, S2), §5 "Unknown fill format", §10 ownership, invariants A2, A5, B1, B2, B5, C4, C6.
Tests: `tests/signals/**` (6 test files, a helper module, a conftest). Stubs: `src/copytrade/signals/**` and `src/copytrade/cli/latency.py` (signatures only, every logic body `raise NotImplementedError`). No payload fixture was needed: F3's `Fill` type is the input and the WebSocket messages come from `tests/hl/support.py` (F3's synthetic fixtures, still marked NEEDS RECORDING in `tests/fixtures/exchange/hl/README.md`).

## Run summary

`uv run pytest tests/signals`: **154 cases collected (77 test functions, parametrised), 151 failing, 3 passing.**

| Failure reason | Count |
|---|---|
| `NotImplementedError` from an interface stub | 151 |
| Import, collection, fixture or syntax error | 0 |
| Passes today | 3 (below) |

The 3 that pass today:
- `test_F7_AC6_the_measurement_modules_do_not_import_any_trading_module`: a structural guard on the stubs (no import of risk, paper, positions, filters, selection, telegram, reports, evaluation, baselines, replay, recovery or calendar). It must keep passing.
- `test_F7_AC6_bad_command_arguments_exit_2_without_building_any_boundary[extra8]` and `[extra9]`: a missing `--hours` or `--wallets` is an argparse error. They pass because the stub already declares those two flags as required; they guard that declaration.

Whole suite: 2,754 existing tests still pass (2,757 passing with the three guards). `ruff check src tests`, `ruff format --check src` and `mypy` are clean.

Limit of this run: nearly every test fails at the first construction of a stub, so no assertion has run against an implementation. Expected values were derived by hand from the spec (the 30 classification cases are literal hand-computed values). Expect the developer to find a few test bugs in round 1 and to report them as `ESCALATE:` / test-review items instead of editing tests.

## How the tests are built

- Only external boundaries are faked: the local clock, the clock-offset source, the alert sink, the downstream signal consumer, and (for `latency measure`) the WebSocket connector, HTTP transport and sleeping. The real F1 config loader and `ClockSync`, the real F2 `Ledger`, the real F3 `HlWsFeed`/`HlRestClient` and the real `SignalDetector` run together. Nothing sleeps.
- The F7.AC6 throughput test uses the real system clock on purpose (it measures wall time against the 50 ms budget); everything else uses a fake clock.
- Hypothesis is derandomised by the suite harness. Seeds are fixed.

## Interface decisions the tests pin (the developer must follow these; the PM should confirm)

1. **Types.** `classify_fill(fill) -> tuple[Leg, ...]` is pure. `Signal` carries `signal_id`, `wallet`, `coin`, `tid`, `leg`, `from_flip`, `action` (F1's `ActionKind`), `is_long`, `size`, `pre_position`, `post_position`, `reduce_fraction`, `px`, `exchange_ts`, `receive_ts`, `age_ms`, `s2_ms`, `outcome`, `flags`. `outcome` is `None` for a normal signal, else `out_of_scope`, `pre_existing` or `unparseable`. For `out_of_scope` and `unparseable` signals the classification fields (`action`, `is_long`, positions, fraction) are `None`: nothing is inferred for them. Exactly one signal per such fill (never a flip split).
2. **Flip.** A fill that changes sign gives two signals, close (leg 0) then open (leg 1), both `from_flip`, with distinct ids. Only a reduce has a `reduce_fraction`, computed as `(|pre| - |post|) / |pre|`.
3. **Pre-existing flip (spec gap).** F7.AC3 says "until W is flat on X; the next open is a normal signal". The tests read a flip of a pre-existing position as: the close leg is `pre_existing`, the open leg is a normal signal (the leader has just opened a new position). PM to confirm.
4. **Follow state API.** `begin_follow(wallet, ClearinghouseState, followed_at_ms)` (no-op if already followed), `end_follow(wallet)`, and `on_fills` for a wallet with no follow state raises `WalletNotFollowedError`. F6 must call `begin_follow`, with the `clearinghouseState` fetched at follow time, before it subscribes the wallet. Held coins are those with a non-zero `szi`.
5. **Idempotency key and restart.** The key is `(wallet, tid)`. It survives a restart: a new detector over the same ledger rebuilds the processed set, the followed wallets and the pre-existing coins (including "already flat") from ledger records. Duplicates create no signal, no ledger record and no sink call. Signal ids are deterministic (a pure function of wallet, `tid` and leg).
6. **Ledger kinds** written by F7 (other features read them): `signal` (keys documented on `SignalDetector`), `follow_started`, `follow_ended`, `latency_sample` (`signal_id`, `wallet`, `coin`, `s1_ms`, `s2_ms`, `exchange_ts_ms`, `receive_ts_ms`). A signal is ledgered before the batch is handed to the sink; a ledger failure raises and nothing is delivered (A2).
7. **Age.** `age_ms = (receive_local + offset) - exchange_ts`, where the offset is `sync.exchange_now().ms - clock.now_ms()` (no new F1 API needed). `age_ms < -clock.max_offset_uncertainty_ms` sets the `clock_anomaly` flag on every leg; `Signal.refusal_reason()` is `"clock_anomaly"` for opens and adds and `None` for reduces and closes. While `ClockSync` has no estimate, `age_ms` is `None`, the flag is `clock_unsynced`, and opens are refused the same way. Exits are never dropped or refused by F7.
8. **Old fills are signalled, not dropped.** F3 does not pass `isSnapshot` (or `liquidation`) to sinks, so F7 cannot tell a snapshot from a live fill. Tests require that a 3-hour-old fill still yields a signal with `age_ms = 10,800,000`. F9 must refuse stale opens (`filter.max_signal_age_ms`); the exit path must never be dropped by age (C4).
9. **Scope and `dir`.** Scope is decided before `dir`. `coin` containing `:` is HIP-3; `@...` or containing `/` is spot; both are `out_of_scope`. An empty `dir` or one outside `Open Long`, `Close Long`, `Open Short`, `Close Short`, `Long > Short`, `Short > Long`, `Liquidated ...` or `Auto-Deleveraging` is `unparseable` (alert kind `unparseable_fill`); `dir` never changes the classification, and there is deliberately no cross-check of `dir` against the computed action (F3's synthetic fixtures contain inconsistent pairs).
10. **Latency mode.** `measure_latency(hours, wallets, config, boundaries, ledger, alerts) -> LatencyReport` (library) and `copytrade latency measure --hours N --wallets A,B --ledger-dir DIR [--root PATH]` (CLI). `percentile` is nearest-rank. `enough_samples` is `signals >= latency.min_signals`. The CLI builds its real boundaries through a module-level factory, `copytrade.cli.latency.build_boundaries`, which the tests replace with fakes (the only seam; it builds external boundaries only). Output lines: `S1 n=<count> p50=<ms> p95=<ms> p99=<ms>`, the same for `S2`, `signals=<count>`, `enough_samples=true|false`. Exit 2 for bad arguments (before any boundary is built), 1 for a `CopytradeError`.
11. **CLI stub.** `cli/latency.py` declares its parser arguments and a handler that raises `NotImplementedError`, so the F1 registry does not report the module as skipped.

## Spec issues and open questions (PM, PO or CTO)

- **S1 (blocks the real latency run):** F7.AC6 says `latency measure` "can run before F9 to F12 exist", and the code can, but F3 has no concrete `WsConnector` (open F3 follow-up; F21 owns the dependency decision, for example `websockets`). Until one exists `build_boundaries` cannot return a real connector, so the command cannot run against Hyperliquid. Decide: a small connector in F7 or F3 with a CTO-serialised dependency commit, or accept that the 1-day measurement waits for F21. The tests do not depend on the answer.
- **S2 (A5/C4 window, not tested):** the signal is ledgered before delivery to the sink. A crash between the two leaves a ledgered signal that the sink never saw; after the restart the same fill is a duplicate, so it never reaches the sink. A missed leader exit in that window is caught by leader reconciliation (F12.AC5) and restart reconstruction (F13), but F12/F13 should say so. A delivered-marker record would close it; the spec does not ask for one.
- **S3:** the flip-of-a-pre-existing-position reading (decision 3 above).
- **S4:** `latency measure` writes `signal` records to `--ledger-dir`. Pointing it at the engine ledger would poison idempotency (those tids would then be duplicates in the real run). The tests do not enforce a separate directory; suggest a refusal when `--ledger-dir` equals `storage.ledger_dir`.
- **S5:** the ledger `signal` payload carries no `isSnapshot`/`liquidation`, because F3 does not pass them. If F12 needs to tell a leader liquidation apart, F3 must pass it through first (open F3 follow-up).
- **S6:** the 50 ms p99 test runs 1,000 real `fsync`s. On the PO's Windows disk it may take a few seconds; the budget it measures (classification, before the ledger write) is not affected.

## Coverage matrix (AC -> tests)

Every test name carries its AC ID. Parametrised functions run several cases; the 30-case classification table is one parametrised function.

#### F7.AC1 (15 tests)

- `test_ac1_ac2_detector.py::test_F7_AC1_each_fill_type_becomes_the_typed_signal_with_direction_size_and_fraction`
- `test_ac1_ac2_detector.py::test_F7_AC1_a_flip_gives_a_close_then_an_open_with_distinct_ids_and_one_ledger_record_each`
- `test_ac1_ac2_detector.py::test_F7_AC1_every_signal_is_in_the_ledger_before_the_batch_is_delivered`
- `test_ac1_ac2_detector.py::test_F7_AC1_one_batch_is_delivered_once_in_fill_order_and_an_empty_batch_delivers_nothing`
- `test_ac1_ac2_detector.py::test_F7_AC1_prices_and_sizes_stay_decimal_and_exact`
- `test_ac1_ac2_detector.py::test_F7_AC1_the_leader_liquidation_dir_values_are_classified_by_size_like_any_close`
- `test_ac1_ac2_detector.py::test_F7_AC1_an_unknown_dir_value_is_an_unparseable_signal_and_an_alert_and_is_never_traded`
- `test_ac1_ac2_detector.py::test_F7_AC1_a_zero_size_fill_is_unparseable_not_an_exception`
- `test_ac1_ac2_detector.py::test_F7_AC1_a_ledger_that_cannot_be_written_stops_the_batch_and_nothing_is_delivered`
- `test_ac1_classify.py::test_F7_AC1_the_fixture_has_thirty_cases_and_the_classifier_yields_every_type_from_them`
- `test_ac1_classify.py::test_F7_AC1_classification_of_each_fixture_case`
- `test_ac1_classify.py::test_F7_AC1_a_reduce_fraction_is_pre_minus_post_over_pre_exactly`
- `test_ac1_classify.py::test_F7_AC1_a_size_that_is_not_positive_is_unparseable`
- `test_ac1_classify.py::test_F7_AC1_dir_text_does_not_change_the_classification`
- `test_ac1_classify.py::test_F7_AC1_property_legs_reconstruct_the_position_change_and_match_the_type_table`

#### F7.AC2 (9 tests)

- `test_ac1_ac2_detector.py::test_F7_AC2_the_same_fill_through_websocket_snapshot_and_resync_creates_one_signal`
- `test_ac1_ac2_detector.py::test_F7_AC2_a_duplicate_creates_no_signal_and_no_ledger_record_and_no_empty_delivery`
- `test_ac1_ac2_detector.py::test_F7_AC2_duplicates_inside_one_batch_and_across_batches_count_once`
- `test_ac1_ac2_detector.py::test_F7_AC2_a_1000_event_fixture_with_30_percent_duplicates_yields_exactly_the_unique_count`
- `test_ac1_ac2_detector.py::test_F7_AC2_the_same_tid_on_two_different_wallets_is_two_fills`
- `test_ac1_ac2_detector.py::test_F7_AC2_fills_arriving_out_of_order_are_all_signalled_in_delivery_order`
- `test_ac1_ac2_detector.py::test_F7_AC2_signal_ids_are_deterministic_across_runs_and_unique_across_fills_and_legs`
- `test_ac1_ac2_detector.py::test_F7_AC2_after_a_restart_a_replayed_fill_is_still_a_duplicate`
- `test_ac1_ac2_detector.py::test_F7_AC2_a_wallet_written_in_upper_case_shares_the_state_of_its_lower_case_form`

#### F7.AC3 (13 tests)

- `test_ac3_ac4_follow_scope.py::test_F7_AC3_every_fill_on_a_coin_held_at_follow_time_is_pre_existing_until_the_wallet_is_flat_on_it`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_a_coin_the_wallet_did_not_hold_at_follow_time_is_a_normal_signal`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_a_short_held_at_follow_time_is_pre_existing_too`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_a_zero_size_entry_in_the_follow_time_state_is_not_a_held_position`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_a_flip_of_a_pre_existing_position_closes_it_as_pre_existing_and_opens_a_normal_signal`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_pre_existing_state_is_per_wallet`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_pre_existing_signals_are_ledgered_and_delivered_so_they_can_be_logged_as_decisions`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_fills_for_a_wallet_that_was_never_followed_are_refused_loudly`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_begin_follow_is_a_no_op_for_a_wallet_already_followed_and_end_follow_resets_it`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_end_follow_of_an_unknown_wallet_is_ignored_and_a_bad_address_is_rejected`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_follow_start_and_end_are_ledgered`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_the_pre_existing_state_survives_a_restart_including_progress_towards_flat`
- `test_ac3_ac4_follow_scope.py::test_F7_AC3_a_followed_wallet_is_still_followed_after_a_restart`

#### F7.AC4 (6 tests)

- `test_ac3_ac4_follow_scope.py::test_F7_AC4_fills_on_hip3_dex_markets_are_out_of_scope`
- `test_ac3_ac4_follow_scope.py::test_F7_AC4_spot_fills_are_out_of_scope_whatever_their_dir_says`
- `test_ac3_ac4_follow_scope.py::test_F7_AC4_core_perps_are_in_scope`
- `test_ac3_ac4_follow_scope.py::test_F7_AC4_an_out_of_scope_fill_gives_exactly_one_signal_even_if_it_looks_like_a_flip`
- `test_ac3_ac4_follow_scope.py::test_F7_AC4_scope_wins_over_pre_existing_and_does_not_disturb_it`
- `test_ac3_ac4_follow_scope.py::test_F7_AC4_out_of_scope_fills_are_still_deduplicated`

#### F7.AC5 (13 tests)

- `test_ac5_age.py::test_F7_AC5_a_signal_carries_both_timestamps_with_their_sources_and_the_age`
- `test_ac5_age.py::test_F7_AC5_age_is_receive_plus_offset_minus_exchange_time`
- `test_ac5_age.py::test_F7_AC5_the_receive_time_is_the_moment_the_batch_arrived`
- `test_ac5_age.py::test_F7_AC5_an_age_below_minus_the_max_offset_uncertainty_is_a_clock_anomaly`
- `test_ac5_age.py::test_F7_AC5_the_anomaly_threshold_follows_config`
- `test_ac5_age.py::test_F7_AC5_a_clock_anomaly_refuses_opens_and_adds_but_never_exits`
- `test_ac5_age.py::test_F7_AC5_both_halves_of_a_flip_are_flagged_and_only_the_open_half_is_refused`
- `test_ac5_age.py::test_F7_AC5_a_very_old_fill_has_a_large_positive_age_and_is_still_signalled_for_the_exit_path`
- `test_ac5_age.py::test_F7_AC5_while_the_clock_is_unsynced_the_age_is_unknown_and_entries_are_refused_but_exits_are_signalled`
- `test_ac5_age.py::test_F7_AC5_after_the_clock_syncs_the_age_is_known_again`
- `test_ac5_age.py::test_F7_AC5_the_offset_used_is_the_one_current_when_the_batch_arrives`
- `test_ac5_age.py::test_F7_AC5_property_age_is_always_receive_plus_offset_minus_exchange`
- `test_ac5_age.py::test_F7_AC5_s2_is_the_receive_to_classified_time_of_the_injected_clock`

#### F7.AC6 (21 tests)

- `test_ac6_latency.py::test_F7_AC6_a_burst_of_100_fills_per_second_for_10_seconds_across_9_wallets_has_p99_s2_under_50_ms_and_drops_nothing`
- `test_ac6_latency.py::test_F7_AC6_a_single_wallet_burst_of_100_fills_in_one_message_is_classified_within_the_budget`
- `test_ac6_latency.py::test_F7_AC6_percentile_is_the_nearest_rank_value`
- `test_ac6_latency.py::test_F7_AC6_percentile_rejects_empty_input_and_a_rank_outside_1_to_100`
- `test_ac6_latency.py::test_F7_AC6_property_percentile_is_a_member_of_the_input_and_monotone_in_q`
- `test_ac6_latency.py::test_F7_AC6_latency_measure_ledgers_one_sample_per_signal_with_stages_s1_and_s2`
- `test_ac6_latency.py::test_F7_AC6_the_report_summarises_both_stages_with_nearest_rank_percentiles`
- `test_ac6_latency.py::test_F7_AC6_the_run_lasts_the_requested_hours_of_the_boundary_clock`
- `test_ac6_latency.py::test_F7_AC6_nothing_is_traded_only_info_requests_are_made_and_no_decision_or_order_record_exists`
- `test_ac6_latency.py::test_F7_AC6_every_signal_is_sampled_including_pre_existing_and_out_of_scope_and_duplicates_are_not`
- `test_ac6_latency.py::test_F7_AC6_enough_samples_is_signals_at_least_the_configured_minimum`
- `test_ac6_latency.py::test_F7_AC6_a_wallet_list_with_duplicates_in_two_spellings_follows_it_once`
- `test_ac6_latency.py::test_F7_AC6_bad_arguments_are_a_value_error_before_any_request_or_sleep`
- `test_ac6_latency.py::test_F7_AC6_exactly_ten_distinct_wallets_are_accepted`
- `test_ac6_latency.py::test_F7_AC6_the_measurement_modules_do_not_import_any_trading_module`
- `test_ac6_latency.py::test_F7_AC6_latency_measure_runs_prints_both_stages_and_leaves_a_verifiable_ledger`
- `test_ac6_latency.py::test_F7_AC6_bad_command_arguments_exit_2_without_building_any_boundary`
- `test_ac6_latency.py::test_F7_AC6_ten_wallets_with_a_repeat_in_another_spelling_is_accepted`
- `test_ac6_latency.py::test_F7_AC6_a_copytrade_error_while_measuring_exits_1_with_its_message`
- `test_ac6_latency.py::test_F7_AC6_an_invalid_config_root_exits_1_naming_the_problem_and_measures_nothing`
- `test_ac6_latency.py::test_F7_AC6_the_measurement_run_leaves_a_ledger_the_engine_can_ignore_and_uses_no_network`

## What each suite proves, and what it deliberately does not

| Suite | Proves | Does not cover (and where it is covered) |
|---|---|---|
| `test_ac1_classify.py` | The 30-case hand-computed fixture (open, add, reduce with fraction, close, flip, aggregated fills), exact Decimals, unparseable sizes, `dir` does not matter, a property test against an independent restatement of the type table (legs reconstruct the position change, sizes sum to `sz`) | `dir` vs computed-action cross-checks (deliberately none) |
| `test_ac1_ac2_detector.py` | The same types through the real ledger and sink, ledger before delivery, batch order, unknown `dir` and zero size as `unparseable` with an alert, ledger failure delivers nothing; idempotency: three sources, duplicates in and across batches, the 1,000-event 30%-duplicate fixture, same `tid` on two wallets, out-of-order fills, deterministic ids, restart, address case | The A5 window between ledger and sink (S2); F9's `duplicate` outcome (signal-level, F9) |
| `test_ac3_ac4_follow_scope.py` | Pre-existing state to flat, per wallet, short side, zero-size entries, flips, follow/unfollow, unknown wallet, state across a restart; HIP-3 and spot are `out_of_scope` (one signal, ledgered, deduplicated, scope before `dir`, scope before pre-existing), core perps in scope | `markets.allowed_dexes` other than `core` (the ceiling fixes it to `core`) |
| `test_ac5_age.py` | The age formula with a real `ClockSync`, boundaries at -100/-101 ms and at the config minimum and maximum, flags on all legs of a flip, opens refused and exits not, old fills kept, unsynced clock, offset changes, property test, `s2_ms` | Clock-offset estimation itself (F1.AC6) |
| `test_ac6_latency.py` | 100 fills/s x 10 s x 9 wallets with p99 S2 <= 50 ms and 0 dropped (real clock), a 100-fill single message, `percentile` (nearest rank, property), `measure_latency` end to end (samples with S1 and S2, report percentiles, run length, info-only requests, no decision/fill/trade/order record, every signal kind sampled, duplicates not, `enough_samples` at 49/50/51, argument validation before any request), the CLI (output lines, exit codes, error paths, no network), no import of any trading module | A real WebSocket run (S1); the S1 network target itself (VAL-L, F21.AC3 1-day measurement); the F21 24h run |

Invariants: A2 (ledger failure delivers nothing; unsynced clock refuses opens), A5 (idempotency, deterministic ids, restart), B1 (age on every signal), B2 (both timestamps carry their source), B5 (ledger record before delivery), C4 (exits never dropped or refused by F7, flips split), C6 (S1 and S2 recorded per signal).

## Shared files

None touched. `pyproject.toml`, `tests/conftest.py`, `tests/harness.py`, `tests/hl/**` and `tests/core/**` are untouched (`tests/signals` imports `tests.hl.support` and `tests.core.helpers`). The new CLI module `cli/latency.py` is discovered by the F1 registry without editing `cli/main.py`. Open item for the CTO: S1 (WebSocket connector dependency).
