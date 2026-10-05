# R4 test plan: `#N` pseudo-coins and failing candles

Root cause (PO's real run): fills contain pseudo-coins `#0`, `#10`, `#140`, `#1020`, `#7521`; candleSnapshot answers
HTTP 500 for them and `is_core_perp` (scoring/reconstruct.py) treats them as core perps, so the backfill retries their
candles forever and the screen/scoring features include them.

Fake HL: `tests/selection/r4_world.py` (loopback `FakeHl` of r1_world; the backfiller's candles go over its HTTP through
the real `RestCandles`; `#N` coins and chosen coins answer 5xx/4xx; requests counted by coin from `world.http.calls`).

## Coverage matrix
| AC | Tests |
|---|---|
| R4.AC1 | `test_ac1_hash_coins_not_core.py`: `hash_names_are_not_core_perps[8]`, `the_recorder_universe_drops_hash_names[8]`, `real_core_perps_stay_core_in_both[8]`, `spot_pairs_and_hip3_stay_excluded_in_both[5]`, `the_two_predicates_cannot_disagree` (Hypothesis, via public `select_universe`), `any_name_starting_with_hash_is_excluded` (Hypothesis) |
| R4.AC2 | `test_ac2_...py`: `a_backfill_never_requests_candles_for_hash_coins`, `the_wallet_is_complete_with_bars_for_real_perps_only`, `hash_coins_do_not_stall_other_wallets`, `a_screened_wallet_with_hash_fills_is_admitted_and_backfilled_without_their_candles`, `S4_maker_share_ignores_hash_coin_maker_fills`, `S3_core_share_is_over_real_perps_hash_notional_cannot_rescue_it`, `S3_hash_notional_does_not_count_against_a_wallet_of_real_perps`, `S5_history_span_counts_real_core_fills_only`, `scoring_ignores_hash_coin_fills` |
| R4.AC3 | `test_ac3_...py` (7 cases: status 500/503/404/400 x sleeping/fail-fast client): `wallets_complete_with_the_failing_coins_bars_missing`, `the_failure_is_cached_per_coin_not_per_wallet`, `the_coin_is_asked_again_only_after_backoff_max_s`, `one_log_line_per_coin_per_cooldown_names_coin_window_and_status`; plus `other_wallets_are_not_blocked_or_starved`, `a_wallet_that_trades_only_the_failing_coin_still_completes`, `a_failing_coin_does_not_starve_the_screening_step` |

## Pinned decisions
- "Ignore" for S3: a `#N` fill is in neither numerator nor denominator of the core share (needs a distinct "pseudo-coin"
  test in screen.py, not just `not is_core_perp`: a plain non-core reading would make the guard test S3_hash_notional_does_not_count... fail).
- AC3 cooldown = `hl.backoff_max_s` (60 s), per coin, started at the failure; one request group (`hl.retry_max + 1` HTTP
  calls at most) per coin per cooldown for all wallets together; log text `coin=<name> window=<start>..<end> status=<code>`
  (ms epoch), once per coin per cooldown.
- Fail-fast client (PO's wiring): the retry sleep raises `HlBudgetError`, so the HTTP status is only available as the
  exception's `__context__`/cause chain; tests require `status=500` in the log also there (implementer must read it).
  The same `HlBudgetError` must not become the global wallet cooldown for a candle failure.

## Run summary (before implementation)
73 new tests: 58 fail, 15 pass. Failure reasons: all AssertionError (backfill never completes / `is_core_perp` True /
metrics differ). No import, collection or fixture errors.
15 passing = regression guards that must stay green: 13 AC1 parametrized "real perps stay core / spot and HIP-3 stay
excluded", `the_two_predicates_cannot_disagree` (today both predicates agree, both wrong; guard that keeps them equal after the fix),
and `S3_hash_notional_does_not_count_against_a_wallet_of_real_perps` (pins "ignore" semantics).

## Escalation: scoring of a coin without bars (existing code, not changed)
`CandleBook.stop_distance` returns None for a coin with no bars, so `replay_r` is None and that trip is OMITTED from
R_copy (M14) and from M16's executable share; but `n_rt = len(closed trips)` still counts it, and the shrinkage
(`shrink_toward_zero(copy_mean_r, n_rt)`) uses that n_rt. A wallet with many trips in a bar-less coin is therefore
scored on its measured trips with the confidence of all trips: mild over-confidence (mis-scoring), not fail-closed.
ESCALATE to PO/architect: decide whether n for shrinkage must be the measured count, or whether a wallet with a
bar-less share of trips above a threshold must be ineligible (a threshold would be a new config key). No test pins this.

## Not covered here
Live HL behaviour of `#N` (QA/explore on testnet-read), mutation testing of the predicate (money-path run), real wall-clock
retry timing (simulation gate).

## R4.AC4 (CTO ruling on the escalation): shrinkage n = measured trips
Fail closed, no gate change, no new config key: a trip in a bar-less coin (`replay_r` None) does not count toward the
copy-R shrinkage n; G2's `n_rt` keeps its definition. File `tests/scoring/test_r4_ac4_measured_trips_shrinkage.py`.
| Part | Test |
|---|---|
| (a) | `barless_trips_do_not_enter_the_shrinkage_n` (score and components equal those of the wallet without the extra zero-P&L SOL trips, `n_rt` 100 vs 80), `more_barless_trips_still_change_nothing` (1, 7, 25 extra trips) |
| (b) | `a_wallet_with_no_measurable_trip_stays_ineligible_by_the_existing_gates` (G10 and G12, existing gates only) |
| (c) | `all_bars_present_scores_are_unchanged_golden` (golden values taken from current src: score 0.65735718..., copy_mean_r x 0.0688286...) |
Run: 4 tests, 2 fail (AssertionError: score 0.6645 vs 0.6574 today), 2 pass (guards (b), (c)).
Limit: with `n_rt` unchanged, a wallet with only SOME measured trips (fewer than `gate.min_round_trips`) is not made
ineligible by any existing gate; (b) pins only the case where none is measurable. Copy_edge_ratio (M15) still uses all
closed trips and is not asserted.

## R4.AC3 cooldown tests: scoring budget cap lifted (test-only)

`test_R4_AC3_the_coin_is_asked_again_only_after_backoff_max_s` and `test_R4_AC3_one_log_line_per_coin_per_cooldown_...`
build their world with `hl.scoring_weight_share = 0.8` (the config maximum, cap 720/min instead of 450/min). Three
backfills (312) plus six refreshes at +50 s and +65 s (42 each) need 466 weight inside the window, so at the default cap
the fail-fast sleeper raised `HlBudgetError` before any candle code ran. Only the budget cap changes; `hl.backoff_max_s`,
the retries and the fake clock are untouched, so the failing-coin timing stays exact. Checked: with the per-coin failure
cache removed from a copy, all 14 of these tests (including the failfast-500/503/404 ones) still fail.
