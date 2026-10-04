# Test plan R5: a wallet's backfill resumable per call under the trading thread's REST time limit

Branch `feat/copytrade-v1/R5-backfill-steps`. Tests only (plus the support module); no `src` edit, no stub needed (the
public interface is unchanged: `Backfiller.step/refresh/inputs`).

## Problem reproduced
Live: `candleSnapshot: no answer within 0.6-1.1 s` + "rate budget has no room" repeating, done=0 of 49 after 6 minutes.
`tests/selection/r5_world.py` rebuilds the PO's wiring (real `TradingSleeper` as the scoring client's `call_limit`, real
`_FailFastSleeper`, real client + budget + `RestCandles` + `Backfiller`; fake: HTTP transport with scripted response
time, one fake time for clock and monotonic). With 0.5 s responses today's code never completes (`0 of 1 wallets complete
after 27 iterations`): fills, portfolio, clearinghouse and role use the 2.0 s, the candle is refused, and all four repeat.

## Coverage matrix
| AC | Tests (file) |
|---|---|
| R5.AC1 | `test_R5_AC1_a_failing_clearinghouse_does_not_repeat_the_fills_page_or_the_portfolio`, `..._a_failing_role_does_not_repeat_the_portfolio_or_the_clearinghouse_state`, `..._a_candle_chunk_that_times_out_does_not_repeat_any_other_call_of_the_wallet`, `..._no_call_that_succeeded_is_ever_requested_again_in_a_backfill_with_failures_everywhere` (`test_r5_ac1_ac2_resumable_calls.py`) |
| R5.AC2 | `test_R5_AC2_every_candle_request_asks_for_at_most_thirty_days`, `..._the_chunks_of_a_coin_cover_the_whole_window_and_the_bars_are_complete_and_unique`, `..._a_chunk_that_fails_is_asked_again_and_the_chunks_before_it_are_kept`, `..._two_wallets_with_the_same_coins_share_the_candles_of_the_hour` (guard), `..._the_next_hour_asks_only_for_the_bars_after_the_last_one_held_in_one_small_request` (guard) |
| R5.AC3 | `test_r5_ac3_bounded_steps.py`: half-second responses (whole budget / one second left), no repeated success, slow chunk that fits (guard today), cap and budget unchanged, two wallets |
| R5.AC4 | `test_r5_ac4_unfittable_call.py`: warning after M timeouts naming coin/window/status, cooldown `hl.backoff_max_s` with one warning per cooldown, other wallets progress + iteration < 3 s, one timeout then an answer is no warning (guard) |
| R5.AC5 | `test_r5_ac5_ac6_equivalence_and_progress.py`: single-step golden (guard), small wallet complete and unique (guard), resumed backfill with a mid failure ends with the same data |
| R5.AC6 | `test_R5_AC6_a_wallet_counts_as_done_only_when_all_its_calls_are_complete` |
| R5.AC7 | `tests/runner/test_r2b_ac3_all_rest_hanging.py` (helper `_shares`, same assertions); `uv run mypy` clean |
| R5.AC8 | `tests/selection/test_r5_ac8_empty_coin_not_core.py` (core.coins and scoring.reconstruct) |

## Derived constants (no new config key)
- Chunk: at most 721 bars (30 days + 1 closed-range bar), asserted as `end - start + 1 <= 721 h`; a 180 d window is >= 6 chunks.
- N (AC3) = 27: at most 1 + 3 + 2 x 7 = 18 calls per wallet of two coins; a step doing ONE call (accepted worst case) needs 18; +50 %.
  Two wallets: 2N.
- M (AC4): at least 2, at most `hl.retry_max + 1` consecutive timeouts of the same call (what a sleeping client attempts); cooldown
  `hl.backoff_max_s`; one WARNING per cooldown, text `coin=<c> window=<start>..<end> status=<code|word>` (the R4.AC3 shape), naming candles.
- Note for the developer: in the fail-fast client a timeout surfaces as `HlBudgetError` raised from the retry sleep, the timeout is its
  `__context__` (like the HTTP status in R4.AC3). The consecutive-timeout count must follow that chain.

## Run summary (before the fix)
25 new tests: 18 fail, 7 pass. Failure reasons: assertion on repeated successful calls (AC1: portfolio asked 3 times etc.), one
candle request of 4 320 bars (AC2), `N wallets complete after 27/54/60 iterations` (AC3, AC5 resumed, AC6), "no warning naming coin,
window and status" (AC4). No import, collection or fixture error. The 7 that pass are deliberate guards: AC8 (the predicate
already holds), the AC5 single-step golden and small-wallet checks (equivalence must stay), cache across wallets and next-hour
incremental fetch (AC2, existing behaviour), a slow-but-fitting chunk (AC3: with today's single 4 800-bar chunk per coin it fits),
and one timeout followed by an answer (AC4).

## Not covered here
Real latency/threads (R2b/R2c loop tests keep covering the 2.0 s cap and the < 3 s iteration with all endpoints hanging; the
timeout test in `r5_world` is deterministic, a fake time). Real Hyperliquid candle semantics (open in [start, end]; part-formed current
bar) are the fake's assumption: QA on testnet/replay. The PO's live run (49 wallets) is the /qa and /verify check.
Potential tension with R4.AC3 (a chunk failing with an HTTP status still caches the coin as failing, wallet completes without it):
unchanged, not weakened.

## R5 round-1 pins

Senior-dev hand-mutation score was 9/17. `tests/selection/test_r5_round1_pins.py` pins the five real survivors of `selection/backfill.py` (each confirmed on a copy: fails on the mutant, passes on the real src):

| Mutant | Test | Result on mutant |
|---|---|---|
| (a) `fetch.hour != hour` -> `fetch is None` (hour rolls over mid-fetch) | `test_R5_r1_a_a_fetch_that_spans_an_hour_boundary_...` | fails |
| (b1) `progress.stalled == call` -> `True` | `test_R5_r1_b1_timeouts_of_different_calls_in_a_row_do_not_cool_the_wallet` | fails (also kills (a)) |
| (b2) counter not reset on a non-timeout outcome | `test_R5_r1_b2_an_http_error_between_timeouts_...` (guard: `..._m_timeouts_of_the_same_call_...`) | fails |
| (c) `_stalled_until` left out of `_own_until` | `test_R5_r1_c_the_progress_line_waits_for_the_end_of_the_stall_cooldown` | fails |

Equivalent survivors, no test needed: the first-call guard `self._step_calls and`, the `>=` boundary of the 1 s gate, the missing `del self._fetches[coin]`.
Optional R5-SD3 pin skipped (the draft did not pass on the real src; not a mutant kill).
