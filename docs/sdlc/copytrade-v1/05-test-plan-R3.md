# Test plan R3: candidate screen (stage 1 ranking, stage 2 first-page screen, cooldowns, hand-off, early exits, rotation, progress, logging)
Test designer, 2026-10-03. Branch feat/copytrade-v1/R3-candidate-screen (from epic ffd95de). FAILING tests only, no src edit, no stub needed
(everything is driven through the public manager / PacedInputs / Backfiller / REST client that already exist).
Spec: research/candidate-ranking.md sections 2 and 9 (pre-registered, written by the researcher). PO decision 2026-10-03 (option A): the
numbers P4-P8, K1 cap, S3 0.50, 30 trips, 72 h, 100 screens are CODE CONSTANTS, no new config key (AC1 pins that no `prefilter.*` key exists).
No gate, risk or broker file is touched by these tests: no ESCALATE.

## Harness (tests/selection/r3_world.py)
Real F6 manager, PacedInputs, Backfiller, F3 REST client + RateBudget, F5 scorer; doubles only at the true boundaries (loopback fake HL of r1_world,
clock, fail-fast sleeper = the PO's wiring, candle/state/share/leaderboard sources). Leaderboard rows are built from exact Decimals (`row()`), fills from
real round trips (`trip`, `good_trips`, `full_page`). Pages can be served relative to the call time (`serve_at`) so "exactly 60 days before the
screen" holds whatever the clock says. Page features were checked once with F5's reconstruct (core share, maker share, trips, hold, exec share).

## Pinned decisions (the research doc leaves them open; the developer follows these, ESCALATE if one is wrong)
1. Stage 1 happens in `run_cycle` with no HTTP request; the screen is a `userFillsByTime {user, startTime = t - scoring.window_days, aggregateByTime}`
   (no endTime) sent from `PacedInputs.work()` slices, one wallet per slice, in K1 order.
2. Observable per screen: ONE INFO record, event `candidate_screened`, message text `wallet=<addr> outcome=ok|rejected failed=<S3,S4|none> not_evaluable=<ids|none>`
   (ids ascending). All nine rules are computed and logged even after the first failure.
3. Stage-1 summary: one INFO record per cycle, event `candidate_prefilter`, message has `rows=<N> ranked=<M>` (L5; B5 persistence is NOT tested here, see below).
4. Unreadable figures (missing, unparsable, NaN, Infinity) in P1 make the row unrankable (L4), never rejected. AV 0 / negative / zero volumes never divide by zero.
5. A fetch or schema error is not a screen: no log line, no screen cooldown, R1's error cooldown applies and the wallet is tried again. A budget refusal
   that says "would wait W s" is honoured: nothing is sent before W s have passed (any wallet), and the refused wallet is not rejected.
6. When the screens of a cycle are done (list exhausted, K OK wallets, or 100 screens) and every OK wallet is backfilled, `complete` is True even when
   nobody passed (else the manager stays BACKFILLING and never re-scores the followed wallets); the next cycle then applies.
7. Followed wallets (manager.restore) are never screened (no `candidate_screened` line), never rejected, and are backfilled and scored whatever their row or
   first page say, including a row that fails stage 1 (doc preamble: "followed wallets are always re-scored, whatever the prefilter says").
8. EX2/EX1 records: `backfill_empty` (reason `backfill_empty`, with `vlm_week` and `vlm_month` of the row in the message when the row is known) and the
   existing `backfill_too_active` with reason `too_active_first_page`, `pages=1`; the same exits fire in the bare Backfiller (no row) and in the manager flow.
9. Rotation counts only SCORED cycles (a BACKFILLING cycle counts for nobody), an eligible cycle resets the streak, the cooldown starts in the cycle where the
   third ineligible result is applied and takes effect for the NEXT cycle's list; a rotated wallet is neither refreshed nor screened for 72 h.
10. Completion line: `backfill of a candidate complete: wallet=<a> fills=<N> pages=<P>` (pages include the screen page), once per wallet. Progress line:
    `backfill progress: done=X of Y candidates, screened=S, screen_ok=K, screen_rejected=R, dropped=D, cooling=C, next retry in N s` at most once per 60 s of the
    clock, only while the pass is incomplete, S = K + R, counters never decrease within a pass, N > 0 (and <= 60) while the pass waits for the budget; one
    `backfill pass complete` line, none after it.
11. S6 is strict (`rate x window < 10 000`, exactly 36 days at 180 d fails); S1-S5, S7-S9 and P1-P8 are inclusive as the doc writes them. Decimal-exact boundaries
    (a float implementation that misjudges exactly 0.70, 0.50 or 10 USD fails by design).

## Coverage matrix (AC -> tests)

**R3.AC1** (26 tests)

- `test_r3_ac1_stage1.py::test_R3_AC1_stage_1_makes_no_request_of_any_kind`
- `test_r3_ac1_stage1.py::test_R3_AC1_the_new_numbers_are_code_constants_not_config_keys`
- `test_r3_ac1_stage1.py::test_R3_AC1_one_info_line_per_cycle_with_the_row_and_ranked_counts`
- `test_r3_ac1_stage1.py::test_R3_AC1_a_row_that_passes_every_rule_is_the_only_candidate_among_failing_filler`
- `test_r3_ac1_stage1.py::test_R3_AC1_P2_an_excluded_address_is_never_a_candidate_whatever_its_case`
- `test_r3_ac1_stage1.py::test_R3_AC1_P3_account_value_at_the_minimum_is_kept_one_cent_below_is_dropped`
- `test_r3_ac1_stage1.py::test_R3_AC1_P4_the_week_volume_must_be_positive`
- `test_r3_ac1_stage1.py::test_R3_AC1_P4_the_month_turnover_must_be_at_least_2`
- `test_r3_ac1_stage1.py::test_R3_AC1_P5_the_month_turnover_must_be_at_most_500`
- `test_r3_ac1_stage1.py::test_R3_AC1_P5_the_day_turnover_must_be_at_most_50`
- `test_r3_ac1_stage1.py::test_R3_AC1_P6_profit_is_needed_in_the_last_month_and_before_it`
- `test_r3_ac1_stage1.py::test_R3_AC1_P7_edge_per_traded_dollar_is_at_least_10_bps_in_both_periods`
- `test_r3_ac1_stage1.py::test_R3_AC1_P8_the_month_return_may_not_exceed_100_percent_of_account_value`
- `test_r3_ac1_stage1.py::test_R3_AC1_the_roi_field_is_not_used`
- `test_r3_ac1_stage1.py::test_R3_AC1_a_row_that_fails_P4_to_P8_is_not_appended_even_when_few_rows_are_ranked`
- `test_r3_ac1_stage1.py::test_R3_AC1_unrankable_rows_are_appended_in_served_order_after_the_ranked_ones_when_few_are_ranked`
- `test_r3_ac1_stage1.py::test_R3_AC1_unrankable_rows_that_violate_P2_or_P3_or_have_no_address_are_never_appended`
- `test_r3_ac1_stage1.py::test_R3_AC1_when_candidates_k_rows_are_ranked_no_unrankable_row_is_appended`
- `test_r3_ac1_stage1.py::test_R3_AC1_K1_ranking_caps_the_edge_at_50_then_all_time_pnl_then_lower_case_address`
- `test_r3_ac1_stage1.py::test_R3_AC1_the_list_does_not_depend_on_the_order_the_rows_are_served` x4
- `test_r3_ac1_stage1.py::test_R3_AC1_K1_decides_before_all_time_pnl`
- `test_r3_ac1_stage1.py::test_R3_AC1_a_board_where_no_row_passes_makes_no_request_and_does_not_crash`
- `test_r3_ac1_stage1.py::test_R3_AC1_stage_1_leaves_the_leaderboard_outage_rule_alone`

**R3.AC2** (51 tests)

- `test_r3_ac2_screen.py::test_R3_AC2_each_candidate_gets_one_window_start_page_request_in_stage_1_rank_order`
- `test_r3_ac2_screen.py::test_R3_AC2_a_wallet_that_is_not_a_candidate_is_not_screened`
- `test_r3_ac2_screen.py::test_R3_AC2_S1_a_page_with_no_fill_is_rejected`
- `test_r3_ac2_screen.py::test_R3_AC2_S1_one_fill_is_enough_to_pass_S1`
- `test_r3_ac2_screen.py::test_R3_AC2_S2_a_full_page_spanning_less_than_a_day_is_rejected`
- `test_r3_ac2_screen.py::test_R3_AC2_S2_a_full_page_spanning_exactly_a_day_is_not_an_S2_failure`
- `test_r3_ac2_screen.py::test_R3_AC2_S2_a_page_of_1999_fills_inside_a_day_is_not_full_so_not_an_S2_failure`
- `test_r3_ac2_screen.py::test_R3_AC2_S3_core_share_below_one_half_fails_only_S3`
- `test_r3_ac2_screen.py::test_R3_AC2_S3_core_share_of_exactly_one_half_passes`
- `test_r3_ac2_screen.py::test_R3_AC2_S3_spot_pairs_and_hip3_names_are_not_core`
- `test_r3_ac2_screen.py::test_R3_AC2_S3_an_unusual_core_perp_name_counts_as_core`
- `test_r3_ac2_screen.py::test_R3_AC2_S3_and_S4_fail_when_every_fill_is_outside_the_universe`
- `test_r3_ac2_screen.py::test_R3_AC2_S4_a_maker_share_of_0_703_fails_only_S4`
- `test_r3_ac2_screen.py::test_R3_AC2_S4_a_maker_share_of_exactly_0_70_passes`
- `test_r3_ac2_screen.py::test_R3_AC2_S4_the_share_is_over_core_fills_only`
- `test_r3_ac2_screen.py::test_R3_AC2_S4_repeated_rows_are_counted_once`
- `test_r3_ac2_screen.py::test_R3_AC2_S5_a_first_core_fill_59_days_back_fails_only_S5`
- `test_r3_ac2_screen.py::test_R3_AC2_S5_exactly_60_days_passes_one_millisecond_less_fails`
- `test_r3_ac2_screen.py::test_R3_AC2_S5_the_first_CORE_fill_counts_not_an_older_spot_fill`
- `test_r3_ac2_screen.py::test_R3_AC2_S6_a_full_page_at_12000_fills_a_window_fails_only_S6`
- `test_r3_ac2_screen.py::test_R3_AC2_S6_the_limit_is_strictly_below_10000_fills_per_window` x3
- `test_r3_ac2_screen.py::test_R3_AC2_S6_a_page_that_is_not_full_is_not_evaluable_never_a_failure`
- `test_r3_ac2_screen.py::test_R3_AC2_S6_uses_the_scoring_window_from_config`
- `test_r3_ac2_screen.py::test_R3_AC2_S7_a_median_hold_just_under_15_minutes_fails_only_S7`
- `test_r3_ac2_screen.py::test_R3_AC2_S7_a_median_hold_of_exactly_15_minutes_passes`
- `test_r3_ac2_screen.py::test_R3_AC2_S7_open_trips_count_as_infinite_holds`
- `test_r3_ac2_screen.py::test_R3_AC2_S7_open_trips_do_not_rescue_a_short_median`
- `test_r3_ac2_screen.py::test_R3_AC2_S8_an_executable_share_just_under_one_half_fails_only_S8`
- `test_r3_ac2_screen.py::test_R3_AC2_S8_an_executable_share_of_exactly_one_half_passes`
- `test_r3_ac2_screen.py::test_R3_AC2_S8_a_trip_is_executable_when_its_scaled_open_reaches_the_minimum_order` x2
- `test_r3_ac2_screen.py::test_R3_AC2_S7_and_S8_are_not_evaluable_below_30_trips_so_never_a_failure`
- `test_r3_ac2_screen.py::test_R3_AC2_S7_is_evaluated_from_30_trips`
- `test_r3_ac2_screen.py::test_R3_AC2_S7_and_S8_count_open_trips_towards_the_30`
- `test_r3_ac2_screen.py::test_R3_AC2_S9_149_closed_round_trips_fail_only_S9`
- `test_r3_ac2_screen.py::test_R3_AC2_S9_150_closed_round_trips_pass`
- `test_r3_ac2_screen.py::test_R3_AC2_S9_a_full_page_is_not_evaluable_never_a_failure`
- `test_r3_ac2_screen.py::test_R3_AC2_S9_a_position_open_before_the_page_is_ignored_until_flat`
- `test_r3_ac2_screen.py::test_R3_AC2_S9_a_flip_splits_into_a_close_and_a_new_trip`
- `test_r3_ac2_screen.py::test_R3_AC2_a_page_that_passes_everything_it_can_be_judged_on_is_ok_and_lists_what_it_could_not_judge`
- `test_r3_ac2_screen.py::test_R3_AC2_the_reused_thresholds_come_from_config` x6
- `test_r3_ac2_screen.py::test_R3_AC2_a_fetch_or_schema_error_is_not_a_screen_the_wallet_is_tried_again` x2
- `test_r3_ac2_screen.py::test_R3_AC2_the_screen_makes_one_request_per_wallet_whatever_the_outcome`

**R3.AC3** (19 tests)

- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_a_rejected_wallet_is_not_asked_again_until_its_cooldown_is_over` x9
- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_cooldowns_are_per_wallet`
- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_the_cooldown_key_is_the_lower_case_address`
- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_after_the_cooldown_the_wallet_is_judged_again_on_its_new_page`
- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_a_screen_that_could_not_be_fetched_starts_no_cooldown`
- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_a_cycle_makes_at_most_100_screens_and_the_rest_wait_for_the_next_cycle`
- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_the_cycle_stops_screening_at_candidates_k_ok_wallets` x2
- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_screens_never_exceed_the_scoring_share_of_the_budget`
- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_a_refusal_that_says_would_wait_is_honoured`
- `test_r3_ac3_cooldowns_budget.py::test_R3_AC3_a_refused_screen_is_not_a_rejection_the_wallet_is_tried_again`

**R3.AC4** (9 tests)

- `test_r3_ac4_handoff.py::test_R3_AC4_a_non_full_screen_page_is_the_complete_backfill`
- `test_r3_ac4_handoff.py::test_R3_AC4_a_full_screen_page_is_page_1_and_the_backfill_resumes_after_its_last_fill`
- `test_r3_ac4_handoff.py::test_R3_AC4_a_full_page_that_failed_the_screen_gets_no_second_page`
- `test_r3_ac4_handoff.py::test_R3_AC4_only_survivors_receive_the_rest_of_the_backfill_and_reach_the_scorer`
- `test_r3_ac4_handoff.py::test_R3_AC4_the_pass_completes_when_nobody_passed_and_the_next_cycle_applies`
- `test_r3_ac4_handoff.py::test_R3_AC4_a_followed_wallet_is_not_screened_and_not_dropped_by_a_screen_it_would_fail`
- `test_r3_ac4_handoff.py::test_R3_AC4_a_followed_wallet_whose_row_fails_stage_1_is_still_fetched_and_scored`
- `test_r3_ac4_handoff.py::test_R3_AC4_a_followed_wallet_is_never_skipped_by_a_cooldown`
- `test_r3_ac4_handoff.py::test_R3_AC4_the_screen_window_start_is_the_scoring_window`

**R3.AC5** (13 tests)

- `test_r3_ac5_early_exits.py::test_R3_AC5_a_wallet_with_no_fill_in_the_window_is_dropped_after_one_request`
- `test_r3_ac5_early_exits.py::test_R3_AC5_fills_older_than_the_window_count_as_no_fill`
- `test_r3_ac5_early_exits.py::test_R3_AC5_one_fill_is_not_empty`
- `test_r3_ac5_early_exits.py::test_R3_AC5_an_empty_wallet_is_logged_once_with_its_reason`
- `test_r3_ac5_early_exits.py::test_R3_AC5_the_empty_cooldown_is_168_hours`
- `test_r3_ac5_early_exits.py::test_R3_AC5_an_empty_wallet_that_the_row_called_active_logs_the_row_volume`
- `test_r3_ac5_early_exits.py::test_R3_AC5_a_full_first_page_inside_a_day_is_too_active_at_once_one_request_not_five`
- `test_r3_ac5_early_exits.py::test_R3_AC5_just_under_a_day_is_too_active_exactly_a_day_is_not`
- `test_r3_ac5_early_exits.py::test_R3_AC5_the_too_active_cooldown_is_one_day`
- `test_r3_ac5_early_exits.py::test_R3_AC5_a_first_page_that_is_not_full_is_never_too_active_at_once`
- `test_r3_ac5_early_exits.py::test_R3_AC5_only_the_first_page_is_judged_a_later_full_page_inside_a_day_goes_on`
- `test_r3_ac5_early_exits.py::test_R3_AC5_the_truncation_rule_of_R1_still_catches_a_wallet_whose_first_page_spans_more_than_a_day`
- `test_r3_ac5_early_exits.py::test_R3_AC5_a_too_active_candidate_in_the_manager_flow_costs_one_request_and_one_record`

**R3.AC6** (7 tests)

- `test_r3_ac6_rotation.py::test_R3_AC6_three_ineligible_cycles_in_a_row_free_the_slots_for_the_wallets_below`
- `test_r3_ac6_rotation.py::test_R3_AC6_one_eligible_cycle_resets_the_streak`
- `test_r3_ac6_rotation.py::test_R3_AC6_without_the_reset_the_third_ineligible_cycle_rotates_it`
- `test_r3_ac6_rotation.py::test_R3_AC6_a_better_ranked_newcomer_does_not_push_a_slot_holder_out`
- `test_r3_ac6_rotation.py::test_R3_AC6_a_slot_holder_that_stops_passing_stage_1_frees_exactly_one_slot`
- `test_r3_ac6_rotation.py::test_R3_AC6_a_holder_keeps_its_slot_only_within_the_top_two_times_k` x2

**R3.AC7** (6 tests)

- `test_r3_ac7_progress.py::test_R3_AC7_one_line_per_wallet_when_its_backfill_completes`
- `test_r3_ac7_progress.py::test_R3_AC7_the_line_counts_the_pages_of_a_wallet_with_a_long_history`
- `test_r3_ac7_progress.py::test_R3_AC7_progress_lines_come_at_most_once_a_minute_while_the_pass_is_incomplete`
- `test_r3_ac7_progress.py::test_R3_AC7_the_progress_counters_are_consistent_and_never_go_down`
- `test_r3_ac7_progress.py::test_R3_AC7_the_progress_line_says_how_long_the_pass_waits_for_the_budget`
- `test_r3_ac7_progress.py::test_R3_AC7_one_pass_complete_line_and_no_progress_line_after_it`

**R3.AC8** (5 tests)

- `test_r3_ac8_screen_log.py::test_R3_AC8_every_screened_wallet_gets_one_line_with_its_failed_rules`
- `test_r3_ac8_screen_log.py::test_R3_AC8_the_ids_are_written_ascending_comma_separated_and_none_when_empty`
- `test_r3_ac8_screen_log.py::test_R3_AC8_the_line_is_at_info_or_above_and_has_the_event_name`
- `test_r3_ac8_screen_log.py::test_R3_AC8_a_wallet_in_cooldown_is_not_logged_again_and_a_rescreen_is`
- `test_r3_ac8_screen_log.py::test_R3_AC8_the_line_reads_on_the_console_with_the_failed_rules`

## Run summary (before any implementation)
136 tests in 8 files (tests/selection/test_r3_ac1_stage1.py .. test_r3_ac8_screen_log.py), 127 fail, 9 pass; whole R3 set runs in about 30 s.
All 127 failures are assertion failures (missing behaviour: filler rows fetched, no `candidate_screened` line, no cooldown, no progress lines, ...); no
import, syntax, collection or fixture error, and no NotImplementedError because no stub was needed.
| AC | tests | failing | passing now |
|----|-------|---------|-------------|
| R3.AC1 | 26 | 23 | 3 |
| R3.AC2 | 51 | 51 | 0 |
| R3.AC3 | 19 | 19 | 0 |
| R3.AC4 | 9 | 7 | 2 |
| R3.AC5 | 13 | 9 | 4 |
| R3.AC6 | 7 | 7 | 0 |
| R3.AC7 | 6 | 6 | 0 |
| R3.AC8 | 5 | 5 | 0 |
The 9 that pass today are deliberate regression guards of behaviour that must keep working (investigated, not "testing nothing"): AC1 no request in
`run_cycle`, no `prefilter.*` config key, leaderboard outage unchanged; AC4 a full screen page resumes after its last fill without refetching page 1, the
screen window start is the scoring window; AC5 one fill is not empty, a non-full first page is never too active at once, only the FIRST page is judged
for EX1, EX3 truncation still caught when the first page spans more than a day.

## What the suites prove / do not prove
Prove: every P and S rule at its threshold (at, one below, one above; each crafted wallet fails exactly one rule), K1 order (cap 50, all-time pnl,
lower-case address, order independence), L4 append rules, not-evaluable never a failure (S6 non-full, S9 full, S7/S8 under 30 trips, open trips as
infinite holds, flips split, positions open before the page ignored, repeated rows counted once), reused config keys read from config, cooldown lengths
(168/24/72 h, +-1 h, per wallet, lower-case key), 100-screen cap, stop at K OK, scoring-share budget and honoured waits, hand-off (no page-1 refetch,
only survivors backfilled and scored, followed wallets untouched), early exits, rotation after exactly 3 scored cycles with reset, L3 stickiness incl. the
2K boundary, progress and completion lines, screen log lines (also through the runner's real console/file formatter).
Do NOT cover (later gates): whether the screen or the ranking has any edge (PO override of the KILL verdict, no claim), real Hyperliquid payload shapes
(fixtures stay SYNTHETIC-PENDING-RECORDING, QA/PO run), real wall-clock pacing on the PO's PC (QA), V8/L5 persistence of per-rule counts and features to the
store (B5: not in the AC list given to the designer, flagged for the PM: add an AC or drop it), mutation testing (developer/senior-dev), property-based tests
(thresholds are exact-boundary table tests; no free-form maths was added in this slice).

## Conflicts with EXISTING tests (not edited; the developer/CTO must decide, I could only analyse them statically)
Stage 1 filters/ranks rows and the early exits change what a Backfiller does with busy or empty wallets, so these existing tests will probably break:
- tests/selection/test_r1_ac3_prefilter.py: `board_body` rows (template windowPerformances, filler AV 50 000, month volume 0.8 x AV) fail P4 and are no longer
  candidates; `test_R1_AC3_candidates_k_takes_the_first_k_survivors_in_served_order` contradicts K1 ranking; every `fetched == {...}` assertion needs rows that pass stage 1.
- tests/selection/test_r1_ac2_too_active.py: `it_is_logged_once_with_the_reason` expects `pages == 50` (R3.AC5: 1 page, reason too_active_first_page for these 12 000/101 000
  fills 50 ms apart); `a_wallet_just_inside_the_cap_is_not_dropped` (99 000 fills 50 ms apart: first page full inside a day, now dropped at once); the manager test uses `board_body`.
- tests/selection/test_r1_ac1_visibility.py:126 and test_r1b_ac1_readable_messages.py:103: 2 500 fills in ONE millisecond now exit at the first page (too_active_first_page)
  instead of `backfill_incomplete`/stuck; test_r1_ac8_error_cooldown.py:133 and test_r1b_ac1:88 (`synth_fills(20_000)`) likewise.
- tests/selection/helpers.py `leaderboard_body` rows (AV 10 000, template windows) pass P1-P8 with K1 = 25 and identical all-time pnl, so they rank by lower-case address, not served
  order: F6 tests that assert candidates in served order with fake inputs (test_ac4/5/6/7) may need `first=` addresses that sort first.
- Any Backfiller test whose wallet has NO fills in the window now gets dropped after one request (R3.AC5, 168 h) instead of being scored on empty data.
Suggested fix route (CTO): the developer adapts the harness defaults (`board_body` default rows pass stage 1, synth wallets spread over more than a day) in a separate
commit and reports each assertion that has to change; none of R3's assertions should be weakened to make an old test pass.

## Superseded existing tests (R3 vs R1/F6 fixtures)
The old tests keep their intent and assertion strength; fixtures were changed so they agree with R3. Verified only against today's src (all pass, nothing
weakened); R3-compatibility is by analysis of the spec, the R3 files stay failing until the developer implements R3.
| old test / file | what changed | why |
|---|---|---|
| `r1_world.board_body` (all R1 manager tests) | every row (and, by default, the filler) carries windowPerformances that pass P1, P4-P8 for any AV 10 000..200 000, identical on all rows; new `filler_passes=False` option | template windows fail P4 (month volume 0.8 x AV), so no row would be a candidate; identical figures keep the K1 order = address order |
| `test_r1_ac3_prefilter::a_row_without_a_readable_account_value_is_kept` | filler built with `filler_passes=False` | L4: unrankable rows are appended only while fewer than K rows are ranked; 1 000 ranked filler rows would fill K first. Assertion unchanged |
| `test_r1_ac3_prefilter::candidates_k_takes_the_first_k_survivors_in_served_order` renamed `..._in_rank_order` | w5 now has AV 20 000 (was: no AV); expected set unchanged | OBSOLETE "served order": K1 ranks (all rows tie, so address order, which equals the served order here); an unreadable w5 is no survivor once K rows are ranked, that case is the test above |
| `test_r1_ac2_too_active` (setup, `just_inside_the_cap`, manager test) | heavy wallets use `spread` fills (1 a minute from 175 d ago) instead of 50 ms steps | a full first page inside a day now exits at page 1 (R3.AC5); 50-page cap assertions (`pages == 50`, 99 000 fills kept) unchanged. In the manager flow R3's screen rejects such a wallet (S6) before the cap: the manager assertions (never followed, not stuck, no refetch) hold either way, the cap itself is proved by the Backfiller tests |
| `test_r1_ac7_truncated_window` (`recent`, `starting_at`) | one fill a minute (was 50 ms / 1 s) | 2 000 fills must span more than a day on page 1 so the R1 truncation rule, not R3's first-page exit, is tested |
| `test_r1_ac1_visibility::incomplete_case_logs_pages_and_fills_fetched`, `test_r1b_ac1::incomplete_message...` | `stuck_fills()`: one fill 2 days old, then 2 500 in one ms; expected fills 2 000 -> 2 001 (pages still 2) | 2 500 fills in one ms is a full first page inside a day (R3 exit). Any stuck cursor with a first page that spans a day has at least 1 + 2 000 distinct fills, so the number is 2 001 by construction |
| `test_r1_ac8_error_cooldown::make_cooling('too_active')`, `test_r1b_ac1::too_active_message...` | `spread_fills(20_000)` | same as R1.AC7 (truncation path) |
| `test_r1_ac4_fairness` HEAVY 24 000 fills | `spread_fills` | same |
| `test_ac4_backfill` (5 tests with empty wallets) | `one_fill(fr)`: one fill in the window for the fake server | R3.AC5: a wallet without a fill in the window is dropped after one request (168 h), so it could not be held/scored |
| `tests/selection/helpers.leaderboard_body` | docstring only | rows pass P1-P8 and tie, so they rank by address; all callers pass `first` in ascending address order below the filler, so candidate lists are unchanged |

Still failing ONLY because src lacks R3 (verified by the run below): none of the old tests (final run of tests/selection tests/hl tests/recorder tests/runner/test_wiring*: 932 passed, 127 failed = exactly the R3 files; `tests/hl/test_w0_connector.py::test_W0_e2e_feed_heartbeat_ping...` failed once in a first run, a timing flake, passed in the second). Of the old tests
only `test_r1_ac3_prefilter` and `test_r1_ac2_too_active` manager flow exercise stage 1/screen through the real manager; they pass today and are expected to pass under R3
by the analysis above, not demonstrated.
