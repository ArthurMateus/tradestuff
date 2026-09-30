# Test plan F4: Market-data recorder and leaderboard snapshots

Epic copytrade-v1, branch `feat/copytrade-v1/F4-recorder` (PAIR pass with F7, cost rule 4). Spec: `04-spec.md` F4.AC1..AC9 with Amendments 1 to 5, §3.3, §4, §5 (disk rows), §10 ownership, invariants A2, A6, B1, B3, D1, D2.
Tests: `tests/recorder/**` (9 test files, a helper module, a conftest and a subprocess worker). Fixture: `tests/fixtures/exchange/hl/leaderboard.json` (**NEEDS RECORDING**, see `README_recorder.md` beside it). Stubs: `src/copytrade/recorder/**` and `src/copytrade/cli/recorder.py` (signatures only, every logic body `raise NotImplementedError`).

## Run summary

`uv run pytest tests/recorder`: **170 cases collected (159 test functions, parametrised), 168 failing, 2 passing.**

| Failure reason | Count |
|---|---|
| `NotImplementedError` from an interface stub | 164 |
| Assertion failure that carries the stub's `NotImplementedError` (the subprocess worker cannot start: the kill tests) | 2 |
| `Failed: DID NOT RAISE` (validation the stub does not perform: `Record(...)` with a float, an unknown stream or a float timestamp) | 2 |
| Import, collection, fixture or syntax error | 0 |
| Passes today | 2: `test_F4_AC6_the_recorder_package_imports_no_trading_module` and `test_F4_AC6_the_recorder_takes_no_trading_state_as_an_input`. They are structural guards on the stubs (no import of a trading module, no trading-state constructor parameter), so they must pass now and must keep passing. |

Whole suite: 2,754 existing tests still pass (2,756 passing with the two guards). `ruff check src tests`, `ruff format --check src` and `mypy` (strict on `src`, `tests` relaxed as before) are clean.

Limit of this run: nearly every test fails at the first construction of a stub, so no assertion has run against an implementation. Expected values were derived by hand from the spec. Expect the developer to find a few test bugs in round 1 and to report them as `ESCALATE:` / test-review items instead of editing tests.

## How the tests are built

- Only external boundaries are faked: the local clock, the market feed, the REST-style market source, the leaderboard endpoint, the candle endpoint, the open-coin set (F12 owns it), the disk probe, the archive backlog and the identity source (except one class that runs real `git` in temporary repositories) and the alert sink. The real F2 `Ledger`, the real F1 config loader (fixture config plus overrides), the real `RecordingStore`, `Recorder` and `CandleStore` run together in every integration test.
- Nothing sleeps: tests step a fake clock (`Rig.run`, `StoreRig.advance_to`).
- Crash tests use a real subprocess and `SIGKILL` (`tests/recorder/_worker.py`), as F2 did.
- Hypothesis is derandomised by the suite harness.

## Interface decisions the tests pin (the developer must follow these; the PM should confirm)

1. **Ports** (`recorder/ports.py`). F3 has no market-data subscription and its allow-list has no `metaAndAssetCtxs`, `fundingHistory` or leaderboard request, so F4 defines its own Protocols: `MarketFeed` (L2 and `allMids`, non-blocking `poll`), `MarketSource` (asset contexts, funding history), `LeaderboardSource` (raw bytes), `UniverseSource`, `CandleSource`, `OpenCoinsSource`, `DiskProbe`, `BacklogSource`. Concrete adapters (and the WebSocket dependency) arrive with F21.
2. **Record model and hashes** (`records.py`, `store.py`). `Record(stream, coin, exchange_ts_ms, receive_ts_ms, source, data)`; canonical bytes via the F2 codec rules; stream sha256 = sha256 of `serialize_record(r) + b"\n"` for each record; transport sha256 = sha256 of the stored file bytes.
3. **Segment records** pin their formula: `segment_hash = sha256(bytes.fromhex(prev_hash) + stream bytes of the segment)`, `prev_hash` = 64 zeros first, and **a segment holds the records written before the seal instant** (`tick` seals, then the record stamped at that same instant belongs to the next segment). One record per open stream that has new records, every `recording.segment_hash_minutes` from the first tick.
4. **Files.** Open files have a `.part` or `.tmp` suffix and a final name appears only by rename after the `recording_file_closed` ledger record. A stream/coin/day can have several files (restart, disk floor, late candle). Candle files are per coin, interval and UTC hour (F4.AC9 asks for "candle files for hours 10, 11, 12"; F4.AC7 says day-partitioned; the tests follow AC9 for candles).
5. **Crash recovery on construction.** A `.part` file left by a crash is kept only up to its last sealed segment and closed with reason `recovered`; the unhashed tail is dropped (a gap).
6. **Readers see hashed data only.** The records of the currently open segment (up to 5 minutes) are invisible to `scan` and `as_of`; live decisions must not depend on the store for the freshest book.
7. **Ledger kinds** written by F4 (new, other features read them): `recording_segment`, `recording_file_closed`, `day_complete`, `component_start`, `component_heartbeat`, and `downtime` with `kind: "disk_low"`, `start_ms`, `end_ms`, `wallets: []` (the F3 downtime adapter, not yet written, must use the same kind name and keys).
8. **Leaderboard retry:** the first attempt on the first tick, then 3 retries (4 attempts) inside the hour, then a `missing` record and one alert of kind `leaderboard_missing`; the next hourly attempt still happens.
9. **Disk alert kinds:** `disk_free_low` (once per 6 h, message holds the free GB and the backlog days and GB) and `disk_floor_stopped` (once per stop). Floor is `free < floor`, resume is `free >= floor + margin`.
10. **Universe:** `select_universe` is pure. Traded input that looks like spot (`@..`, `../..`) or a dex name is dropped; HIP-3 markets count toward the cap; BTC, ETH and SOL are never dropped; ties drop the name that sorts last.
11. **Gap statistics:** an interval between consecutive snapshots longer than the threshold counts in full (that is how 10 min of 60 is 16.7%, not 16.5%), the window edges count as snapshots, exactly 5 s (L2) or 60 s (mid) is not a gap. CLI output format: `<COIN> l2_gap_pct=16.7 mid_gap_pct=16.7`.
12. **Package-list hash:** `name==version`, lower-cased, sorted, each line ends in LF (the last too). F17 must reuse `packages_sha256` so both agree.
13. **CLI stub.** `cli/recorder.py` declares its parser arguments and a handler that raises `NotImplementedError`, because F1's registry would otherwise print "skipped" for every `copytrade` command.

## Spec issues and open questions (PM or PO)

- **S1 (dependency, CTO-serialised):** the spec says "columnar format with zstd or an equivalent". `pyproject.toml` has no dependencies and Python 3.11 has no zstd in the standard library. The tests are format-agnostic (a `compression_level` of 1 or 9 must give different transport hashes and the same stream hash; ratio <= 25%). Decide: add `zstandard` (and `pyarrow` if columnar is required), or accept the standard library (`lzma` or `gzip`) with a spec amendment. Columnar layout itself cannot be tested without that decision.
- **S2:** "at least every `recording.l2_interval_ms`" cannot be a property of the recorder alone: the feed decides the cadence, and REST fallbacks would break the rate budget. The test proves that no polled event is lost and that gaps are recorded honestly (F4.AC4).
- **S3:** the F4.AC7 1-hour, 250-coin size check is too big for a unit run. The tests measure a 12-coin, 1-hour representative stream (over 5 MB of JSON lines). The 250-coin figure and `recording.max_gb_per_day` are measured in the 24h dry run (F21.AC2).
- **S4:** a non-JSON leaderboard body: the test only pins "no crash, registry untouched". Whether it counts as a failed fetch (retry, `missing`) or is stored as raw evidence is open.
- **S5:** the disk probe raising `OSError` (unknown free space) is not specified; A2 suggests treating it as the floor. Not tested.
- **S6:** `ledger.heartbeat_interval_s` is used here by `ComponentReporter` for the recorder and archive processes; the F21 supervisor heartbeat (F21 text) and the STATE follow-up "F2 heartbeat owner" remain separate and unresolved.
- **S7:** the spec says F4.AC2 snapshots are "compressed, with fetch timestamp and sha256"; the tests store the body inside a `leaderboard` record (`status`, `body`, `sha256`) so they get both file hashes for free.

## Coverage matrix (AC -> tests)

Every test name carries its AC ID. Parametrised functions run several cases.

#### F4.AC1 (25 tests)

- `test_ac1_coverage.py::test_F4_AC1_the_universe_always_includes_btc_eth_and_sol_even_with_no_traded_coins`
- `test_ac1_coverage.py::test_F4_AC1_the_universe_is_traded_coins_plus_the_always_set_plus_all_hip3_markets_sorted`
- `test_ac1_coverage.py::test_F4_AC1_spot_and_dex_names_in_the_traded_input_are_not_core_perps_and_are_dropped`
- `test_ac1_coverage.py::test_F4_AC1_over_the_cap_the_lowest_24h_volume_is_dropped_first_and_hip3_counts_toward_the_cap`
- `test_ac1_coverage.py::test_F4_AC1_a_volume_tie_drops_the_name_that_sorts_last_and_a_missing_volume_counts_as_zero`
- `test_ac1_coverage.py::test_F4_AC1_btc_eth_sol_survive_the_cap_even_with_zero_volume`
- `test_ac1_coverage.py::test_F4_AC1_exactly_at_the_cap_nothing_is_dropped_and_one_over_drops_one`
- `test_ac1_coverage.py::test_F4_AC1_a_cap_below_the_always_set_is_a_value_error`
- `test_ac1_coverage.py::test_F4_AC1_property_universe_is_capped_keeps_the_always_set_and_keeps_the_highest_volumes`
- `test_ac1_coverage.py::test_F4_AC1_start_subscribes_the_feed_to_the_universe_including_hip3_and_uses_the_configured_lookback`
- `test_ac1_coverage.py::test_F4_AC1_start_caps_the_universe_at_max_coins_by_24h_volume`
- `test_ac1_coverage.py::test_F4_AC1_an_l2_book_is_recorded_with_top_levels_both_timestamps_and_the_ws_source`
- `test_ac1_coverage.py::test_F4_AC1_the_recorded_depth_follows_recording_l2_levels`
- `test_ac1_coverage.py::test_F4_AC1_a_book_with_fewer_levels_than_the_configured_depth_is_recorded_as_is`
- `test_ac1_coverage.py::test_F4_AC1_allmids_updates_are_recorded_exactly`
- `test_ac1_coverage.py::test_F4_AC1_a_burst_of_events_in_one_poll_is_recorded_without_loss_and_in_order`
- `test_ac1_coverage.py::test_F4_AC1_asset_contexts_are_recorded_every_configured_interval`
- `test_ac1_coverage.py::test_F4_AC1_the_asset_context_cadence_follows_config_at_its_minimum`
- `test_ac1_coverage.py::test_F4_AC1_hourly_funding_history_is_recorded_and_no_point_is_recorded_twice`
- `test_ac1_coverage.py::test_F4_AC1_a_rest_source_that_is_down_leaves_a_gap_and_never_stops_the_book_stream`
- `test_ac1_coverage.py::test_F4_AC1_hip3_markets_are_recorded_and_their_file_names_are_safe_on_windows`
- `test_ac1_coverage.py::test_F4_AC1_coin_names_that_look_like_paths_cannot_escape_the_recordings_directory`
- `test_ac1_coverage.py::test_F4_AC1_over_a_one_hour_stub_feed_l2_gaps_are_at_most_5_seconds_in_at_least_99_9_percent_of_intervals`
- `test_ac1_coverage.py::test_F4_AC1_property_every_polled_event_becomes_exactly_one_record`
- `test_ac1_coverage.py::test_F4_AC1_the_hip3_market_is_subscribed_though_no_followed_wallet_ever_traded_it`

#### F4.AC2 (18 tests)

- `test_ac2_leaderboard.py::test_F4_AC2_wallets_are_read_from_the_leaderboard_fixture_lower_cased_in_order`
- `test_ac2_leaderboard.py::test_F4_AC2_a_body_that_is_not_a_leaderboard_is_a_value_error`
- `test_ac2_leaderboard.py::test_F4_AC2_an_empty_leaderboard_has_no_wallets`
- `test_ac2_leaderboard.py::test_F4_AC2_the_registry_keeps_every_wallet_ever_added_across_restarts`
- `test_ac2_leaderboard.py::test_F4_AC2_the_registry_ignores_things_that_are_not_wallet_addresses`
- `test_ac2_leaderboard.py::test_F4_AC2_the_registry_has_no_way_to_forget_a_wallet`
- `test_ac2_leaderboard.py::test_F4_AC2_a_snapshot_stores_the_body_exactly_with_its_fetch_time_and_sha256`
- `test_ac2_leaderboard.py::test_F4_AC2_snapshots_are_taken_every_interval_within_plus_or_minus_five_minutes`
- `test_ac2_leaderboard.py::test_F4_AC2_the_interval_follows_config_at_its_minimum`
- `test_ac2_leaderboard.py::test_F4_AC2_a_large_leaderboard_is_stored_compressed_and_partitioned_by_day`
- `test_ac2_leaderboard.py::test_F4_AC2_a_failed_fetch_is_retried_and_a_later_success_is_stored_without_a_missing_record`
- `test_ac2_leaderboard.py::test_F4_AC2_a_fetch_that_fails_every_time_is_retried_three_times_within_the_hour_then_recorded_missing_with_one_alert`
- `test_ac2_leaderboard.py::test_F4_AC2_after_a_missing_snapshot_the_next_hourly_snapshot_is_still_attempted_and_stored`
- `test_ac2_leaderboard.py::test_F4_AC2_a_timeout_counts_as_a_failed_fetch_like_any_other_error`
- `test_ac2_leaderboard.py::test_F4_AC2_wallets_seen_in_any_snapshot_stay_in_the_registry_after_they_leave_the_leaderboard`
- `test_ac2_leaderboard.py::test_F4_AC2_a_body_that_is_not_json_does_not_crash_the_recorder_or_touch_the_registry`
- `test_ac2_leaderboard.py::test_F4_AC2_the_store_has_no_way_to_delete_or_prune_a_snapshot`
- `test_ac2_leaderboard.py::test_F4_AC2_a_recorded_snapshot_parses_as_the_json_that_was_fetched`

#### F4.AC3 (10 tests)

- `test_ac3_as_of.py::test_F4_AC3_as_of_excludes_records_received_after_t_even_when_future_records_exist`
- `test_ac3_as_of.py::test_F4_AC3_as_of_is_inclusive_at_t_and_excludes_one_millisecond_later`
- `test_ac3_as_of.py::test_F4_AC3_as_of_with_no_record_at_all_is_none_and_never_raises`
- `test_ac3_as_of.py::test_F4_AC3_as_of_looks_back_across_a_day_boundary`
- `test_ac3_as_of.py::test_F4_AC3_as_of_and_scan_order_by_receive_time_not_by_the_order_of_appending`
- `test_ac3_as_of.py::test_F4_AC3_scan_is_half_open_from_inclusive_to_exclusive`
- `test_ac3_as_of.py::test_F4_AC3_records_keep_the_exchange_timestamp_and_the_receive_timestamp_apart`
- `test_ac3_as_of.py::test_F4_AC3_the_recorder_stamps_both_timestamps_on_every_kind_of_record`
- `test_ac3_as_of.py::test_F4_AC3_property_as_of_returns_the_latest_record_not_after_t_and_never_a_later_one`
- `test_ac3_as_of.py::test_F4_AC3_a_reader_over_the_ledger_directory_sees_what_the_writer_hashed`

#### F4.AC4 (18 tests)

- `test_ac4_gaps.py::test_F4_AC4_a_one_hour_fixture_with_a_ten_minute_gap_reports_16_7_percent`
- `test_ac4_gaps.py::test_F4_AC4_a_gap_free_hour_reports_zero`
- `test_ac4_gaps.py::test_F4_AC4_the_gap_is_the_whole_interval_between_snapshots_not_the_part_beyond_five_seconds`
- `test_ac4_gaps.py::test_F4_AC4_l2_threshold_exactly_5000_ms_is_not_a_gap_and_5001_is`
- `test_ac4_gaps.py::test_F4_AC4_mid_threshold_exactly_60_seconds_is_not_a_gap_and_60001_ms_is`
- `test_ac4_gaps.py::test_F4_AC4_a_mid_gap_is_covered_by_the_marks_of_the_same_coin_and_the_other_way_round`
- `test_ac4_gaps.py::test_F4_AC4_marks_of_another_coin_do_not_cover_a_coins_mid_gap`
- `test_ac4_gaps.py::test_F4_AC4_the_window_edges_count_as_snapshots_so_missing_head_and_tail_are_gaps`
- `test_ac4_gaps.py::test_F4_AC4_a_coin_with_no_data_in_the_window_is_entirely_a_gap`
- `test_ac4_gaps.py::test_F4_AC4_default_coins_are_those_with_any_l2_record_in_the_window`
- `test_ac4_gaps.py::test_F4_AC4_a_window_that_is_empty_or_reversed_is_a_value_error`
- `test_ac4_gaps.py::test_F4_AC4_data_not_covered_by_a_ledgered_hash_is_a_gap`
- `test_ac4_gaps.py::test_F4_AC4_a_stopped_interval_is_reported_and_never_back_filled`
- `test_ac4_gaps.py::test_F4_AC4_property_shares_are_fractions_and_an_extra_snapshot_never_increases_the_gap`
- `test_ac4_gaps.py::test_F4_AC4_recorder_gaps_prints_one_line_per_coin_with_the_percentages`
- `test_ac4_gaps.py::test_F4_AC4_recorder_gaps_rejects_a_window_that_is_not_forward_or_has_no_offset`
- `test_ac4_gaps.py::test_F4_AC4_recorder_gaps_on_an_unreadable_directory_exits_1`
- `test_ac4_gaps.py::test_F4_AC4_a_reader_over_the_ledger_directory_gives_the_same_stats_as_the_writer`

#### F4.AC5 (19 tests)

- `test_ac5_disk.py::test_F4_AC5_free_space_is_probed_on_every_volume_holding_the_three_directories_each_check_interval`
- `test_ac5_disk.py::test_F4_AC5_the_check_interval_follows_config`
- `test_ac5_disk.py::test_F4_AC5_no_alert_at_exactly_the_alert_threshold_and_one_alert_just_below_it`
- `test_ac5_disk.py::test_F4_AC5_the_alert_states_the_free_gb_and_the_unarchived_backlog`
- `test_ac5_disk.py::test_F4_AC5_the_low_disk_alert_repeats_at_most_once_per_six_hours`
- `test_ac5_disk.py::test_F4_AC5_a_low_volume_that_only_holds_the_cache_directory_still_triggers_the_alert`
- `test_ac5_disk.py::test_F4_AC5_at_exactly_the_floor_recording_continues_and_just_below_it_stops_within_two_check_intervals`
- `test_ac5_disk.py::test_F4_AC5_at_the_floor_open_files_are_closed_atomically_with_reason_disk_floor_and_one_alert_is_sent`
- `test_ac5_disk.py::test_F4_AC5_while_stopped_opens_and_adds_are_refused_with_disk_low_and_exits_are_never_refused`
- `test_ac5_disk.py::test_F4_AC5_while_stopped_nothing_is_written_and_nothing_is_buffered_for_later`
- `test_ac5_disk.py::test_F4_AC5_the_ledger_heartbeat_and_ledger_appends_continue_while_recording_is_stopped`
- `test_ac5_disk.py::test_F4_AC5_the_stop_is_ledgered_as_disk_low_downtime_once_recording_resumes`
- `test_ac5_disk.py::test_F4_AC5_recording_resumes_at_floor_plus_margin_and_not_a_hundredth_of_a_gb_earlier`
- `test_ac5_disk.py::test_F4_AC5_the_margin_follows_config`
- `test_ac5_disk.py::test_F4_AC5_after_resume_the_stopped_interval_is_a_gap_and_new_records_land_in_a_new_file`
- `test_ac5_disk.py::test_F4_AC5_two_stops_give_two_alerts_and_two_downtime_intervals`
- `test_ac5_disk.py::test_F4_AC5_the_floor_follows_config`
- `test_ac5_disk.py::test_F4_AC5_a_floor_stop_on_any_one_of_the_three_volumes_stops_recording`
- `test_ac5_disk.py::test_F4_AC5_a_day_end_while_stopped_still_closes_and_marks_the_day_complete`

#### F4.AC6 (3 tests)

- `test_ac6_independence.py::test_F4_AC6_the_recorder_package_imports_no_trading_module`
- `test_ac6_independence.py::test_F4_AC6_the_recorder_takes_no_trading_state_as_an_input`
- `test_ac6_independence.py::test_F4_AC6_pause_kill_switch_loss_halt_and_access_degraded_records_change_nothing_about_recording`

#### F4.AC7 (34 tests)

- `test_ac7_storage.py::test_F4_AC7_serialisation_is_deterministic_and_independent_of_data_key_order`
- `test_ac7_storage.py::test_F4_AC7_serialisation_keeps_decimal_scale_and_text_exactly`
- `test_ac7_storage.py::test_F4_AC7_a_record_with_a_float_or_a_non_finite_number_is_refused`
- `test_ac7_storage.py::test_F4_AC7_a_record_with_an_unknown_stream_or_a_float_timestamp_is_refused`
- `test_ac7_storage.py::test_F4_AC7_deserialising_garbage_raises_value_error`
- `test_ac7_storage.py::test_F4_AC7_property_serialise_then_deserialise_is_the_identity`
- `test_ac7_storage.py::test_F4_AC7_a_one_hour_fixture_reads_back_exactly_equal_to_what_was_written`
- `test_ac7_storage.py::test_F4_AC7_decompressing_a_file_yields_the_bytes_the_recorder_serialised`
- `test_ac7_storage.py::test_F4_AC7_unicode_and_hostile_text_survive_the_file_round_trip`
- `test_ac7_storage.py::test_F4_AC7_files_are_partitioned_by_stream_utc_day_and_coin`
- `test_ac7_storage.py::test_F4_AC7_the_utc_day_is_taken_from_the_receive_time_at_the_exact_midnight_boundary`
- `test_ac7_storage.py::test_F4_AC7_nothing_with_a_final_name_is_partial_and_open_files_are_marked_temporary`
- `test_ac7_storage.py::test_F4_AC7_close_all_twice_writes_no_second_closed_record`
- `test_ac7_storage.py::test_F4_AC7_close_all_with_nothing_open_writes_nothing`
- `test_ac7_storage.py::test_F4_AC7_a_second_file_for_the_same_stream_and_day_never_overwrites_the_first`
- `test_ac7_storage.py::test_F4_AC7_a_late_record_stamped_before_midnight_lands_in_its_own_day_file`
- `test_ac7_storage.py::test_F4_AC7_every_closed_file_is_ledgered_once_with_both_hashes_matching_its_bytes`
- `test_ac7_storage.py::test_F4_AC7_stream_hash_ignores_compression_and_transport_hash_follows_it`
- `test_ac7_storage.py::test_F4_AC7_the_closed_record_exists_in_the_ledger_before_a_reader_can_list_the_file`
- `test_ac7_storage.py::test_F4_AC7_a_reader_refuses_a_file_whose_bytes_changed`
- `test_ac7_storage.py::test_F4_AC7_reading_an_unknown_or_missing_path_raises_integrity_error`
- `test_ac7_storage.py::test_F4_AC7_a_one_day_fixture_has_exactly_one_closed_record_per_file_and_each_matches_its_file`
- `test_ac7_storage.py::test_F4_AC7_day_complete_is_written_after_the_upload_delay_and_not_before`
- `test_ac7_storage.py::test_F4_AC7_day_complete_follows_the_configured_delay`
- `test_ac7_storage.py::test_F4_AC7_a_day_is_marked_complete_once`
- `test_ac7_storage.py::test_F4_AC7_the_current_day_keeps_recording_after_the_previous_day_is_closed`
- `test_ac7_storage.py::test_F4_AC7_a_segment_record_is_ledgered_every_five_minutes_for_each_open_stream`
- `test_ac7_storage.py::test_F4_AC7_no_segment_is_sealed_one_second_early`
- `test_ac7_storage.py::test_F4_AC7_segment_hashes_are_chained_from_zeros_over_the_records_of_each_segment`
- `test_ac7_storage.py::test_F4_AC7_each_stream_has_its_own_chain`
- `test_ac7_storage.py::test_F4_AC7_records_of_the_open_segment_are_not_readable_until_they_are_hashed`
- `test_ac7_storage.py::test_F4_AC7_after_a_force_kill_mid_segment_the_unhashed_tail_is_a_gap_and_never_used`
- `test_ac7_storage.py::test_F4_AC7_after_force_kills_at_20_random_points_every_file_present_reads_back_complete`
- `test_ac7_storage.py::test_F4_AC7_compressed_bytes_are_at_most_25_percent_of_the_uncompressed_json_lines`

#### F4.AC8 (15 tests)

- `test_ac8_component.py::test_F4_AC8_the_package_hash_is_over_sorted_lowercase_name_equals_version_lines_with_lf`
- `test_ac8_component.py::test_F4_AC8_the_package_hash_ignores_input_order_and_changes_with_a_version`
- `test_ac8_component.py::test_F4_AC8_the_package_hash_of_no_packages_is_the_hash_of_nothing`
- `test_ac8_component.py::test_F4_AC8_installed_packages_lists_this_interpreters_distributions`
- `test_ac8_component.py::test_F4_AC8_the_identity_of_a_clean_worktree_has_the_real_commit_lockfile_hash_and_python_version`
- `test_ac8_component.py::test_F4_AC8_the_default_package_hash_is_the_hash_of_the_installed_packages`
- `test_ac8_component.py::test_F4_AC8_dirty_is_judged_over_the_engine_path_set_only`
- `test_ac8_component.py::test_F4_AC8_a_directory_that_is_not_a_git_worktree_is_an_error_not_a_made_up_identity`
- `test_ac8_component.py::test_F4_AC8_start_ledgers_one_component_start_with_the_full_identity`
- `test_ac8_component.py::test_F4_AC8_the_archive_process_uses_the_same_record_with_its_own_component_name`
- `test_ac8_component.py::test_F4_AC8_a_heartbeat_with_the_same_identity_is_ledgered_every_interval_and_not_before`
- `test_ac8_component.py::test_F4_AC8_the_heartbeat_interval_follows_config_at_its_minimum`
- `test_ac8_component.py::test_F4_AC8_a_long_pause_yields_one_heartbeat_not_a_burst_of_catch_up_records`
- `test_ac8_component.py::test_F4_AC8_the_recorder_ledgers_its_component_start_when_it_starts`
- `test_ac8_component.py::test_F4_AC8_two_worktrees_at_different_commits_give_two_records_that_differ_exactly_in_commit_and_path`

#### F4.AC9 (17 tests)

- `test_ac9_candles.py::test_F4_AC9_the_fixture_gives_candle_files_for_x_at_hours_10_11_12_and_for_y_at_hour_11_each_with_a_closed_record`
- `test_ac9_candles.py::test_F4_AC9_only_coins_with_something_open_in_that_hour_are_ever_requested`
- `test_ac9_candles.py::test_F4_AC9_an_hour_is_fetched_after_it_has_closed_and_not_before`
- `test_ac9_candles.py::test_F4_AC9_each_candle_carries_its_fetch_time_and_the_candle_fields`
- `test_ac9_candles.py::test_F4_AC9_candle_files_are_hashed_like_any_recording_file`
- `test_ac9_candles.py::test_F4_AC9_a_completed_hour_is_not_fetched_again_and_a_restart_does_not_refetch_it`
- `test_ac9_candles.py::test_F4_AC9_a_candle_missing_at_first_fetch_is_fetched_later_stored_once_and_the_rest_stay_as_stored`
- `test_ac9_candles.py::test_F4_AC9_a_stored_candle_is_never_replaced_even_if_the_exchange_now_says_something_else`
- `test_ac9_candles.py::test_F4_AC9_with_the_endpoint_unreachable_the_fetch_is_retried_every_retry_interval_and_other_recording_continues`
- `test_ac9_candles.py::test_F4_AC9_one_alert_per_alert_interval_while_the_endpoint_stays_down`
- `test_ac9_candles.py::test_F4_AC9_when_the_endpoint_comes_back_within_the_retry_window_the_hour_is_stored`
- `test_ac9_candles.py::test_F4_AC9_retries_stop_after_the_missing_data_retry_window_of_72_hours`
- `test_ac9_candles.py::test_F4_AC9_a_reader_gets_stored_candles_without_any_fetch`
- `test_ac9_candles.py::test_F4_AC9_a_reader_needing_a_candle_that_is_not_there_yet_gets_it_fetched_and_hashed_first`
- `test_ac9_candles.py::test_F4_AC9_a_reader_needing_a_missing_candle_from_an_unreachable_exchange_gets_an_error_not_a_guess`
- `test_ac9_candles.py::test_F4_AC9_get_returns_typed_decimal_candles_sorted_by_open_time`
- `test_ac9_candles.py::test_F4_AC9_the_recorder_process_drives_the_candle_store`

## What each suite proves, and what it deliberately does not

| Suite | Proves | Does not cover (and where it is covered) |
|---|---|---|
| `test_ac1_coverage.py` | Universe rules (pure and through `start`), recorded depth, timestamps, no event lost in a burst or in a 1-hour 20-coin run, gap share in 99.9% of intervals, asset-context and funding cadence, HIP-3 and path-hostile coin names | 250 coins and real WebSocket behaviour (F21 dry run, F21.AC2); real REST payload shapes (adapters, F21) |
| `test_ac2_leaderboard.py` | Body stored verbatim with fetch time and sha256, hourly cadence, retry and `missing` and alert, registry keeps every wallet across restarts, no delete API | The real endpoint schema (fixture is synthetic, NEEDS RECORDING); archive retention (F23.AC2) |
| `test_ac3_as_of.py` | `as_of` and `scan` never look ahead (boundaries, property test, out-of-order appends, day boundary), both timestamps on every stream | Readers in other features (F9, F12, F13, F16, F19 use this interface) |
| `test_ac4_gaps.py` | 16.7% on the 10-minute-gap fixture, thresholds at 5000/5001 ms and 60000/60001 ms, mark/mid union per coin, unhashed data and stopped intervals count as gaps, CLI output and exit codes, monotone property | Gap policy in B0d (F19) |
| `test_ac5_disk.py` | Probe of all three volumes, alert threshold and 6 h throttle, floor, safe close with `disk_floor`, `disk_low` for opens and adds only, ledger and heartbeat continue, downtime record, resume boundary at floor + margin, gap never back-filled | "A leader close still produces our close within the exit budget" (F12 and F21, needs the position manager); archive backlog source (F23) |
| `test_ac6_independence.py` | The recorder has no import of, or input from, trading state; ledgered pause, kill-switch, loss-halt, access-degraded records change nothing recorded | The real `/pause`, kill switch, loss halt and `access_degraded` in a paper run: simulation (F21) and /qa |
| `test_ac7_storage.py` | Serialisation (exact, deterministic, hostile text, property), lossless 1-hour read-back, day partition and midnight boundary, atomic names, one closed record per file with both hashes, transport vs stream hash under another compression level, segment chain formula and timing, unhashed tail after a real `SIGKILL` is a gap, 20 random kills leave only complete files, corruption is refused, `day_complete` boundaries, ratio <= 25% | Columnar layout and zstd (S1); archive read-back (F23) |
| `test_ac8_component.py` | `component_start` and heartbeat fields, cadence and boundaries, real `git` for commit, dirty over the engine path set, two worktrees differ exactly in commit and path, package-list hash bytes | The run-commit guard itself (F17.AC2/AC3, wired by a CTO-serialised commit and F21) |
| `test_ac9_candles.py` | The A4.2 fixture (X at hours 10, 11, 12, Y at hour 11, nothing for others), only-after-the-hour fetch, fetch time on each candle, hashes, late candle stored once, never replaced, retry cadence and alert throttle, 72 h retry window, readers fetch-and-hash first, restart does not refetch | The real open-coin set (F12) and the end-to-end candle fixture (F21 integration suite, §10) |

Invariants: A2 (disk floor fails closed for opens), A6 (no floats: `Record` refusal), B1 (readers only see hashed, timestamped data), B3 (gaps recorded, never synthesised), D1 (`as_of`), D2 (registry never forgets) each have tests above.

## Shared files

None touched. `pyproject.toml`, `tests/conftest.py`, `tests/harness.py`, `tests/hl/**` and `tests/core/**` are untouched (`tests/recorder` imports `tests.hl.support` and `tests.core.helpers`). A new CLI module `cli/recorder.py` is discovered by the F1 registry without editing `cli/main.py`. Open item for the CTO: S1 (dependency).
