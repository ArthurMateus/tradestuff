# Test plan F3: Hyperliquid client (REST, WebSocket, rate budget, access detection)

Epic copytrade-v1, branch `feat/copytrade-v1/F3-hl-client`. Spec: `04-spec.md` F3.AC1..AC6, §3.2, §5, invariants B1, B3, B4, A2, A6, and F1.AC3 (info-only).
Tests: `tests/hl/**` (7 files). Fixtures: `tests/fixtures/exchange/hl/**`. Stubs: `src/copytrade/hl/**` (signatures only, every body `raise NotImplementedError`).

## Run summary

`uv run pytest tests/hl`: **314 tests collected, 313 failing, 1 passing.**

| Failure reason | Count |
|---|---|
| `NotImplementedError` from an interface stub | 313 |
| Import, collection, fixture or syntax error | 0 |
| Assertion failure | 0 (nothing runs far enough yet to assert) |
| Passes today | 1: `test_F1_AC3_hl_package_has_no_exchange_endpoint_literal_and_no_signing_imports`. It is a guard on the stubs (no `/exchange` literal, no signing import in `src/copytrade/hl`), so it must pass now and must keep passing; it is not testing missing behaviour. |

Whole suite: 1834 F1 tests still pass. `ruff check src tests` and `mypy` (strict, `src` and `tests`) are clean. `ruff format --check src` is clean.

Important limit of this run: every F3 test fails at construction of a stub, so no assertion has been executed against any implementation. The expected values were derived by hand from the spec. Expect the developer to find a few test bugs in round 1; report them as a `ESCALATE:` / test-review item rather than editing tests.

## How the tests are built

- Only external boundaries are faked: the local clock (`FakeClock`), sleeping (`FakeSleeper` advances the fake clock), the HTTP transport (`FakeHttp`), the WebSocket connector (`FakeConnector`/`FakeConnection`), the alert sink and the ledger port. The real `RateBudget`, `AccessMonitor`, `SchemaFailureMonitor`, `HlRestClient` and `HlWsFeed` run together in every integration test (`tests/hl/support.py` only wires them).
- Config is the real F1 loader over the valid fixture tree with overrides, so every threshold is a validated §3 value.
- Nothing sleeps. The feed is driven by `tick()` once per fake second. Hypothesis is derandomized by the suite harness. Seeds are fixed.
- The only real sockets are loopback ones (`http.server` on 127.0.0.1, in 3 tests of `test_rest.py`). The suite-wide network guard therefore still proves that no test reaches Hyperliquid and that no `/exchange` request exists.
- **Fixture provenance (needs PO action):** `tests/fixtures/exchange/hl/*.json` are SYNTHETIC, written from the documented response shapes (edge-hypothesis §5 field list, market-context 2.3), because this sandbox cannot reach the API (proxy returned 403). `tests/fixtures/exchange/hl/README.md` says how to replace them with recordings from `hl_sample.py` on the PO's PC. Do this before /verify. `NEEDS RECORDING:` `allMids`, `l2Book`, `clearinghouseState`, `userFillsByTime` (including a fill with a `liquidation` object), `candleSnapshot`, `userRole`, `portfolio`, WS `userFills` snapshot and update, WS `pong`, WS `subscriptionResponse`, and a real region-block or 403 body.

## Interface stubs created (developer owns them from now on)

`src/copytrade/hl/`: `errors.py` (`HlError` tree), `ledger_port.py` (`DowntimeRecord`, `DowntimeSink`), `backoff.py` (`backoff_delay_s`), `budget.py` (`Priority`, `request_weight`, `RateBudget`, `QueuedRequest`, `Sleeper`, `INFO_REQUEST_TYPES`), `models.py` (typed responses), `schema.py` (`parse_response`, `parse_ws_fills`, `SchemaFailureMonitor`), `access.py` (`AccessMonitor`, `is_region_block_body`), `rest.py` (`HttpTransport`, `StdlibHttpTransport`, `HlRestClient`), `ws.py` (`WsConnector`, `WsConnection`, `FillSink`, `HlWsFeed`). Constructors take the loaded `Config` mapping (`config["hl.retry_max"]`), keyword-only.

Trap for the developer: F1.AC3's static scan (`tests/core/test_mode_paper_only.py`) flags any string literal, docstrings included, that contains the exchange endpoint path segment. Do not write it anywhere in `src/`.

## Coverage matrix (AC -> tests)

Every test name carries its AC ID. `(xN)` = N parametrised or property cases. F1.AC3 rows are the info-only guards that must keep holding.


### F3.AC1 Rate budget (39 cases)

- `test_budget.py::test_F3_AC1_weight_table` (x16)
- `test_budget.py::test_F3_AC1_userRole_and_portfolio_weights_come_from_config`
- `test_budget.py::test_F3_AC1_negative_item_count_is_rejected`
- `test_budget.py::test_F3_AC1_budget_boundary_exactly_at_one_below_and_one_above`
- `test_budget.py::test_F3_AC1_one_below_the_limit_leaves_room_for_exactly_the_remainder`
- `test_budget.py::test_F3_AC1_an_entry_leaves_the_window_exactly_60_seconds_after_it_was_recorded`
- `test_budget.py::test_F3_AC1_the_window_slides_it_does_not_reset_on_minute_boundaries`
- `test_budget.py::test_F3_AC1_weight_larger_than_the_whole_budget_is_refused_and_can_never_succeed`
- `test_budget.py::test_F3_AC1_wait_ms_counts_down_to_when_the_window_frees`
- `test_budget.py::test_F3_AC1_charge_records_late_weight_without_raising_even_over_the_limit`
- `test_budget.py::test_F3_AC1_scoring_cap_is_floor_of_budget_times_share`
- `test_budget.py::test_F3_AC1_scoring_stops_at_its_share_but_critical_may_use_the_rest`
- `test_budget.py::test_F3_AC1_critical_traffic_is_not_limited_by_the_scoring_share`
- `test_budget.py::test_F3_AC1_scoring_request_above_its_cap_can_never_be_served`
- `test_budget.py::test_F3_AC1_full_window_of_critical_traffic_blocks_scoring_until_it_frees`
- `test_budget.py::test_F3_AC1_drain_serves_critical_before_scoring_and_is_fifo_within_a_class`
- `test_budget.py::test_F3_AC1_a_waiting_critical_request_blocks_cheaper_scoring_requests_behind_it`
- `test_budget.py::test_F3_AC1_drain_only_returns_what_fits_and_keeps_the_rest_queued`
- `test_budget.py::test_F3_AC1_two_hour_simulated_load_keeps_every_window_and_the_scoring_share_and_serves_critical_first`
- `test_budget.py::test_F3_AC1_property_no_window_ever_exceeds_the_budget_or_the_scoring_cap`
- `test_rest.py::test_F3_AC1_client_waits_for_the_window_instead_of_exceeding_the_budget`
- `test_rest.py::test_F3_AC1_client_traffic_over_ten_minutes_respects_budget_and_scoring_share_including_late_item_weight`
- `test_rest.py::test_F3_AC1_scoring_request_that_can_never_fit_its_share_fails_without_sending`
- `test_rest.py::test_F3_AC1_critical_request_with_the_same_weight_is_served`

### F3.AC2 HTTP 429 and timeouts (34 cases)

- `test_backoff.py::test_F3_AC2_backoff_delay_is_between_the_exponential_floor_and_the_maximum`
- `test_backoff.py::test_F3_AC2_backoff_has_jitter_and_is_reproducible_from_the_seed`
- `test_backoff.py::test_F3_AC2_backoff_is_capped_at_max_for_huge_attempt_numbers`
- `test_backoff.py::test_F3_AC2_backoff_rejects_invalid_arguments` (x4)
- `test_rest.py::test_F3_AC2_every_request_carries_the_configured_timeout` (x3)
- `test_rest.py::test_F3_AC2_every_retry_also_carries_the_timeout`
- `test_rest.py::test_F3_AC2_a_server_that_always_returns_429_sees_exactly_retry_max_plus_one_requests` (x4)
- `test_rest.py::test_F3_AC2_429_backoff_grows_exponentially_from_base_and_is_capped_at_max`
- `test_rest.py::test_F3_AC2_backoff_starts_at_the_configured_base_not_at_one_second`
- `test_rest.py::test_F3_AC2_backoff_jitter_differs_between_seeds_and_repeats_for_the_same_seed`
- `test_rest.py::test_F3_AC2_no_endpoint_receives_more_than_one_request_per_second_while_it_returns_429`
- `test_rest.py::test_F3_AC2_429_then_success_returns_the_data_after_the_retries`
- `test_rest.py::test_F3_AC2_a_server_that_always_times_out_sees_retry_max_plus_one_requests` (x3)
- `test_rest.py::test_F3_AC2_timeout_then_success_recovers`
- `test_rest.py::test_F3_AC2_other_error_statuses_are_raised_at_once_without_retry` (x5)
- `test_rest.py::test_F3_AC2_user_fills_by_time_request_body`
- `test_rest.py::test_F3_AC2_open_ended_user_fills_by_time_omits_end_time`
- `test_rest.py::test_F3_AC2_stdlib_transport_returns_status_and_body_from_a_local_server`
- `test_rest.py::test_F3_AC2_stdlib_transport_raises_timeout_error_when_the_server_never_answers`
- `test_rest.py::test_F3_AC2_a_real_local_server_that_always_returns_429_sees_at_most_retry_max_plus_one_requests_per_call`

### F3.AC3 WebSocket limits and heartbeat (32 cases)

- `test_ws.py::test_F3_AC3_the_eleventh_distinct_user_is_refused_locally_and_never_sent`
- `test_ws.py::test_F3_AC3_the_eleventh_user_is_refused_after_the_connection_is_already_open`
- `test_ws.py::test_F3_AC3_resubscribing_a_known_user_is_a_no_op_not_an_error_and_not_a_second_message`
- `test_ws.py::test_F3_AC3_the_limit_follows_config` (x2)
- `test_ws.py::test_F3_AC3_unsubscribing_frees_a_slot`
- `test_ws.py::test_F3_AC3_subscribe_message_has_the_documented_shape`
- `test_ws.py::test_F3_AC3_new_connections_never_exceed_the_per_minute_limit_when_the_link_flaps` (x2)
- `test_ws.py::test_F3_AC3_pings_are_sent_at_the_configured_interval`
- `test_ws.py::test_F3_AC3_ping_interval_follows_config` (x2)
- `test_ws.py::test_F3_AC3_a_healthy_link_with_pongs_never_goes_stale`
- `test_ws.py::test_F3_AC3_a_connection_with_no_message_or_pong_for_stale_after_s_is_marked_stale`
- `test_ws.py::test_F3_AC3_stale_after_follows_config` (x2)
- `test_ws.py::test_F3_AC3_any_message_or_pong_resets_the_silence_timer` (x3)
- `test_ws.py::test_F3_AC3_stale_feed_refuses_opens_and_adds_with_feed_stale_but_never_exits`
- `test_ws.py::test_F3_AC3_a_wallet_with_no_subscription_fails_closed`
- `test_ws.py::test_F3_AC3_before_the_first_connection_the_wallet_is_stale`
- `test_ws.py::test_F3_AC3_one_alert_per_stale_episode_naming_the_wallets`
- `test_ws.py::test_F3_AC3_a_hard_disconnect_is_handled_like_a_stall_without_waiting_for_the_timer`
- `test_ws.py::test_F3_AC3_a_stale_connection_is_closed_and_replaced_after_about_one_to_two_seconds`
- `test_ws.py::test_F3_AC3_reconnect_backoff_grows_from_one_second_and_is_capped_at_the_configured_max` (x3)
- `test_ws.py::test_F3_AC3_reconnect_delays_are_jittered_between_seeds`
- `test_ws.py::test_F3_AC3_backoff_restarts_after_a_successful_reconnect`
- `test_ws.py::test_F3_AC3_after_reconnect_the_wallet_is_served_again_and_opens_are_allowed`
- `test_ws.py::test_F3_AC3_the_ping_message_is_valid_json`

### F3.AC4 Gap resync (24 cases)

- `test_resync.py::test_F3_AC4_reconnect_fetches_fills_since_the_last_seen_exchange_timestamp_and_merges_by_tid`
- `test_resync.py::test_F3_AC4_resync_uses_the_critical_class_never_the_scoring_share`
- `test_resync.py::test_F3_AC4_the_gap_is_ledgered_as_data_gap_downtime`
- `test_resync.py::test_F3_AC4_a_gap_with_no_missed_fills_is_still_ledgered_and_delivers_nothing_new`
- `test_resync.py::test_F3_AC4_a_stall_without_a_disconnect_is_resynced_too`
- `test_resync.py::test_F3_AC4_no_gap_and_no_resync_on_the_first_connection`
- `test_resync.py::test_F3_AC4_resync_fills_reach_the_consumer_before_any_fill_from_the_new_connection`
- `test_resync.py::test_F3_AC4_opens_stay_refused_and_nothing_new_is_delivered_until_the_resync_succeeded`
- `test_resync.py::test_F3_AC4_every_affected_wallet_is_resynced_and_ledgered`
- `test_resync.py::test_F3_AC4_a_snapshot_is_deduplicated_against_what_was_already_delivered`
- `test_resync.py::test_F3_AC4_the_first_snapshot_delivers_every_fill_once`
- `test_resync.py::test_F3_AC4_a_repeated_live_message_and_overlapping_batches_deliver_each_tid_once`
- `test_resync.py::test_F3_AC4_an_out_of_order_fill_with_a_new_tid_is_still_delivered`
- `test_resync.py::test_F3_AC4_a_wallet_is_deduplicated_independently_of_another`
- `test_resync.py::test_F3_AC4_a_message_with_a_bad_fill_is_rejected_whole_and_later_messages_still_flow`
- `test_resync.py::test_F3_AC4_three_bad_messages_raise_one_schema_alert`
- `test_resync.py::test_F3_AC4_junk_and_unknown_messages_do_not_crash_the_tick` (x6)
- `test_resync.py::test_F3_AC4_fills_for_a_wallet_we_did_not_subscribe_to_are_ignored`
- `test_resync.py::test_F3_AC4_property_across_a_gap_every_fill_is_delivered_exactly_once`

### F3.AC5 Access degraded (30 cases)

- `test_access.py::test_F3_AC5_three_403s_within_the_window_degrade_access_and_two_do_not`
- `test_access.py::test_F3_AC5_403_and_451_count_together`
- `test_access.py::test_F3_AC5_a_region_block_body_counts_as_an_access_error` (x2)
- `test_access.py::test_F3_AC5_ordinary_bodies_are_not_region_blocks` (x4)
- `test_access.py::test_F3_AC5_error_count_of_one_trips_on_the_first_403`
- `test_access.py::test_F3_AC5_error_count_of_two_needs_two`
- `test_access.py::test_F3_AC5_error_count_threshold_at_the_config_maximum`
- `test_access.py::test_F3_AC5_errors_spread_wider_than_the_window_do_not_add_up`
- `test_access.py::test_F3_AC5_errors_inside_the_window_do_add_up`
- `test_access.py::test_F3_AC5_success_rate_below_the_minimum_degrades_at_exactly_below_not_at` (x4)
- `test_access.py::test_F3_AC5_success_rate_follows_the_configured_minimum` (x2)
- `test_access.py::test_F3_AC5_rate_limited_429s_are_not_access_denial`
- `test_access.py::test_F3_AC5_opens_and_adds_are_refused_and_exits_are_not`
- `test_access.py::test_F3_AC5_exactly_one_alert_within_60_seconds_and_no_repeats_while_degraded`
- `test_access.py::test_F3_AC5_the_client_keeps_sending_requests_while_degraded`
- `test_access.py::test_F3_AC5_clears_after_recover_min_healthy_minutes_and_not_before`
- `test_access.py::test_F3_AC5_recover_min_follows_config`
- `test_access.py::test_F3_AC5_no_traffic_never_clears_the_state`
- `test_access.py::test_F3_AC5_a_bad_minute_restarts_the_recovery_clock`
- `test_access.py::test_F3_AC5_a_success_rate_above_95_percent_counts_as_healthy`
- `test_access.py::test_F3_AC5_a_success_rate_well_below_95_percent_never_clears_the_state`
- `test_access.py::test_F3_AC5_a_second_episode_alerts_again`

### F3.AC6 Schema validation (138 cases)

- `test_schema.py::test_F3_AC6_all_mids_parses_to_decimal_prices`
- `test_schema.py::test_F3_AC6_l2_book_parses_both_sides`
- `test_schema.py::test_F3_AC6_an_empty_book_side_is_valid`
- `test_schema.py::test_F3_AC6_clearinghouse_state_parses_signed_positions`
- `test_schema.py::test_F3_AC6_clearinghouse_state_with_no_positions_and_null_liquidation_is_valid`
- `test_schema.py::test_F3_AC6_fills_parse_with_exact_decimals_and_verbatim_dir` (x2)
- `test_schema.py::test_F3_AC6_an_empty_fill_list_is_valid`
- `test_schema.py::test_F3_AC6_unknown_dir_values_and_extra_fields_pass_through_unchanged`
- `test_schema.py::test_F3_AC6_candles_parse`
- `test_schema.py::test_F3_AC6_user_role_parses_to_the_role_string`
- `test_schema.py::test_F3_AC6_portfolio_parses_every_window`
- `test_schema.py::test_F3_AC6_a_fill_missing_any_required_field_rejects_the_whole_list` (x26)
- `test_schema.py::test_F3_AC6_a_fill_with_a_wrong_type_or_bad_value_rejects_the_whole_list` (x25)
- `test_schema.py::test_F3_AC6_rejection_is_all_or_nothing_no_partial_result_leaks`
- `test_schema.py::test_F3_AC6_list_endpoints_reject_the_wrong_container` (x14)
- `test_schema.py::test_F3_AC6_missing_required_field_rejects_the_response` (x27)
- `test_schema.py::test_F3_AC6_wrong_type_or_bad_value_rejects_the_response` (x22)
- `test_schema.py::test_F3_AC6_unknown_request_type_is_rejected`
- `test_schema.py::test_F3_AC6_the_error_names_the_endpoint_and_field_but_not_the_payload_values`
- `test_schema.py::test_F3_AC6_property_a_json_float_price_is_always_rejected`
- `test_schema.py::test_F3_AC6_property_valid_decimal_strings_round_trip_exactly`
- `test_schema.py::test_F3_AC6_property_arbitrary_json_is_accepted_or_rejected_with_a_schema_error_never_crashes`
- `test_schema.py::test_F3_AC6_two_failures_send_no_alert_and_the_third_sends_exactly_one`
- `test_schema.py::test_F3_AC6_more_failures_in_the_same_episode_send_no_further_alert`
- `test_schema.py::test_F3_AC6_failures_more_than_ten_minutes_apart_do_not_add_up`
- `test_schema.py::test_F3_AC6_three_failures_inside_ten_minutes_do_add_up`
- `test_schema.py::test_F3_AC6_failures_on_different_endpoints_are_counted_separately`
- `test_schema.py::test_F3_AC6_the_client_rejects_a_bad_response_reports_it_and_alerts_on_the_third`

### F1.AC3 (info-only guards held by F3) (17 cases)

- `test_rest.py::test_F1_AC3_info_only_client_refuses_action_like_request_types_without_sending` (x11)
- `test_rest.py::test_F1_AC3_client_refuses_any_exchange_url_at_construction` (x4)
- `test_rest.py::test_F1_AC3_every_request_goes_to_the_info_url_only`
- `test_rest.py::test_F1_AC3_hl_package_has_no_exchange_endpoint_literal_and_no_signing_imports`

## What each suite proves, and what it deliberately leaves out

| File | Proves | Does not cover (and who does) |
|---|---|---|
| `test_backoff.py` | Delay bounds (floor = min(max, base x 2^n), at most twice that, never above max), jitter exists and is seedable, huge attempt numbers, bad arguments. Hypothesis. | – |
| `test_budget.py` | Weight table with boundaries at 19/20/39/40 and 59/60 items; config weights; exact-at, one-below, one-above of the budget and of the scoring cap; a window entry leaves at exactly 60 000 ms; sliding, not minute-reset; head-of-line priority of exits and reconciliation; 2 h simulated load and a Hypothesis property over random sequences. | Real time. Multi-threaded callers (see decision D8). |
| `test_rest.py` | Timeout on every attempt; exactly retry_max + 1 requests on always-429 and always-timeout for 0, 1, 5 and 8; backoff floor, growth, cap and jitter; at most 1 request/s to an endpoint that returns 429 (also across back-to-back calls); other error statuses are not retried; budget enforced at client level including late item weight; scoring request that can never fit fails unsent; request bodies; info-only guard (action-like request types, exchange URLs, every URL ends `/info`, static scan of the package); the real stdlib transport against loopback (status, body, timeout, and the always-429 server). | Real TLS and the real endpoint (QA/simulation, paper dry run F21). Connection-level `OSError` handling other than via `record_timeout` (D6). |
| `test_access.py` | 403/451/region-body counting at count boundaries 1, 2, 3, 19, 20; window boundary; success-rate boundaries (below, at, above); 429 is neutral; opens and adds refused, exits never; exactly one alert per episode within 60 s; client keeps sending while degraded; recovery after recover_min, relapse restarts the clock, no traffic never clears, sustained 83% never clears, 96.7% clears; downtime ledgered; a second episode alerts again. | The real alert path to Telegram (F14). Ledger schema of the record (F2 adapter). Real region-block body text (needs a recorded sample, D4). |
| `test_schema.py` | Fixture payloads parse to exact Decimal types; every required field of every endpoint, missing and wrong-typed; JSON floats, NaN, negative prices, empty strings, booleans-as-ints rejected; extra fields and unknown `dir` pass through; whole-response rejection; error names endpoint and field but never the value; Hypothesis: float prices always rejected, decimals round-trip, arbitrary JSON never crashes; failure alert at 3 in 10 min per endpoint, boundary at 9 min 59 s and 10 min 1 s. | Semantic validity (a price of 0, crossed books). Real payload shapes until fixtures are recorded. |
| `test_ws.py` | Distinct-user cap (10, config 1 and 4) refused locally and never sent; unsubscribe frees a slot; new connections per any 60 s window stay within the limit under a flapping link (limits 1 and 3); ping cadence; stale boundary one second below and above; any message or pong resets silence; feed_stale refusal for opens and adds, not exits; unsubscribed wallet fails closed; one alert per episode; reconnect delay starts at 1 to 2 s, grows, is capped for max 5, 30 and 120, is jittered, and restarts after a success. | The real socket, ping/pong wire format (unconfirmed by HL, market-context says heartbeat unconfirmed; the fake echoes `{"channel":"pong"}`), Windows sleep or resume (F21 dry run). |
| `test_resync.py` | Resync request (`userFillsByTime`, startTime = last seen fill time, critical class) after a hard disconnect and after a silent stall; merge by tid with 0 duplicates; `data_gap` ledgered with wallets and interval; nothing new is delivered and opens stay refused until the resync succeeded; resync fills reach the consumer before the new connection's fills; snapshot dedupe (also the very first one); repeated batches; out-of-order tids; two wallets; a bad message is rejected whole and does not stop the feed; junk and unknown channels; Hypothesis over pre-gap, missed, snapshot and post-gap sets. | Restart of the process mid-gap (F13 reconstruction: the dedupe memory is in-process). Truncation at the 10 000-fill cap and pages of 2 000 (F12.AC10 and F4 handle paging; see D9). 24 h behaviour (F21). |

Invariants touched: A2 (fail closed: unknown wallet, unresolved gap, degraded access, unsynced budget), B1 (staleness), B3 (heartbeat, jittered reconnect, gap resync), B4 (rate budget, 429 backoff), A6 (Decimal money in every parsed field). A1, A4, A5, A7, A8 are not touched by F3 (no orders).

## Spec issues and decisions needed (test designer's pinned choices, each flagged)

| ID | Issue | What the tests pin | Decision needed from |
|---|---|---|---|
| D1 | F2 is not merged in this worktree, so no ledger API exists. | F3 owns a port: `DowntimeSink.record_downtime(DowntimeRecord(kind, start_ms, end_ms, wallets))` with kinds `data_gap` and `access_degraded`. `access_degraded` is written once, on clearing, with the interval [trip, clear]. | PM/CTO: F2 must provide an adapter; confirm the record shape. A crash while degraded loses the open interval (F13's job). |
| D2 | Jitter is unspecified, yet "at most 1 request/s" must hold at base 1 s. | Delay for retry n is at least min(max, base x 2^n), at most max, at most 2x the floor. Jitter is upward only. | PM: confirm (full jitter below the base would break the 1 request/s rule). |
| D3 | F3.AC5 gives no minimum sample for the success-rate trigger (1 failed request of 1 would be 0%). | Every rate test uses at least 20 requests; behaviour below that is unpinned. | PM: add a minimum-sample rule (recommend a `access.min_requests` key, about 10) or accept "fail closed on any sample". |
| D4 | "Region-block body" has no recorded sample. | Two literal examples ("...unavailable in your region", "...not available in your jurisdiction") with HTTP 400 count as access errors. | PO: send one real blocked response body when known; `hl_sample.py` logs may have one. |
| D5 | Does a 429 count against "REST success rate"? | 429 is neutral (ignored), so a rate-limit storm cannot trip `access_degraded`. Timeouts, 5xx and other 4xx count as failures. | PM/PO: confirm; the alternative would make scoring backoff trip the entry pause. |
| D6 | Non-429 statuses (500, 502, 404) and connection errors are unspecified. | 403, 451, 404, 500, 502 raise `HlHttpError` after exactly 1 request; only 429 and `TimeoutError` are retried. | PM: confirm 5xx should not retry. |
| D7 | A wallet with no subscription, and a feed that has never connected. | Both refuse opens and adds with `feed_stale` (A2). | PM: confirm the reason text for the never-connected case. |
| D8 | The REST client and `HlWsFeed.tick` are synchronous; a resync inside `tick` blocks the tick while the REST client sleeps in backoff. | Tests run single-threaded and set `hl.retry_max` 0 where a failing REST must not stall the tick. | Architect/dev: F21 supervisor must not starve the other wallets during a long backoff. Flag for review. |
| D9 | `userFillsByTime` returns at most 2 000 fills per call; a gap with more needs paging. | Not tested (fixtures hold 45 fills). | PM: add a paging AC to F3 or to F12.AC10; today no AC covers it. |
| D10 | The fill consumer cannot tell a snapshot fill from a live one (`FillSink.on_fills(wallet, fills)`). A first-connection snapshot delivers old fills. | Tests require the first snapshot to be delivered once. | PM: F7 must filter old fills by age (F7.AC5) or the sink needs an `is_snapshot` flag. |
| D11 | Info base URL has no §3 key. | `info_url` is a constructor argument with default `MAINNET_INFO_URL`; the client refuses any URL containing the exchange endpoint segment. | PM: acceptable, or add `hl.info_url` to §3 (F1 change). |
| D12 | Weight rounding for "+1 per 20 items". | Floor (`items // 20`, `items // 60`), so 19 items add 0 and 20 add 1. | PM: confirm against Hyperliquid docs (market-context marks the weights [S]). |
| D13 | Gap definition. | Fetch starts at the last seen fill time of the wallet (or the gap start when none); the ledgered `data_gap` starts at the last message from the lost connection and ends when the resync completed. | PM: confirm the two intervals are meant to differ. |
| D14 | F3.AC2 "at most 1 request/s to that endpoint". | Pinned for an endpoint that keeps returning 429, across back-to-back calls (a cooldown after a 429), not for healthy traffic. | PM: confirm. |

`ESCALATE:` none. `EXPLORE REQUEST:` none.
