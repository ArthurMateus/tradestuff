# Test plan R2: restart safety (RISK-59, 60, 66, 67, 68, AC6 pin gap, AC7 pacing)

Branch `feat/copytrade-v1/R2-restart-safety`. Money path. Tests only: no stubs were needed (every behaviour change is inside
existing code), so every new test fails on an assertion, none on an import or `NotImplementedError`. No config key and no
F11 amendment is required (code constants: bound 5 s of loop time, 2 s per iteration, force interval 600 s).

## Coverage matrix

| AC | Tests |
|---|---|
| R2.AC1 | `tests/runner/test_r2_ac1_unsynced_restart.py`: `test_R2_AC1_after_a_long_downtime_and_an_unsynced_restart_a_triggered_stop_fills_within_5_s` (4 params: unsynced / too_uncertain x clean_stop / hard_kill, 120 s downtime, forward-only broker time), `..._broker_time_catches_up_to_live_exchange_time_while_the_clock_is_untrusted` (2), `..._entries_stay_refused_while_broker_time_catches_up`, `..._a_flatten_close_fills_within_5_s_after_an_unsynced_restart`, `..._a_pending_leader_close_requeued_at_the_restart_fills_within_5_s`, `..._restored_positions_and_a_clock_that_drops_between_reload_and_step_1_still_advance_and_mark` |
| R2.AC2 | `tests/runner/test_r2_ac2_nonblocking_rest.py`: `..._with_l2book_answering_429_every_iteration_is_bounded_and_the_stop_is_processed`, `..._a_resample_that_keeps_answering_429_never_stalls_the_loop_for_an_hour_of_doubt`, `..._with_l2book_hanging_the_iteration_returns_within_2_s`, `..._flatten_does_not_wait_on_the_gate_lock_for_a_hanging_resample`, `..._no_rest_call_sleeps_on_the_trading_thread_for_an_hour_of_429[metaAndAssetCtxs, fundingHistory, candleSnapshot, clearinghouseState, userFillsByTime, allMids, l2Book]` |
| R2.AC3 | `tests/runner/test_r2_ac3_ledger_growth.py`: `..._an_idle_runner_writes_a_checkpoint_only_after_the_force_interval`, `..._the_seen_signal_ids_are_not_rewritten_in_full_by_every_checkpoint`, `..._idle_growth_in_a_simulated_hour_is_small_and_bounded`, `..._a_restart_after_an_idle_hour_still_knows_every_seen_signal[clean_stop, hard_kill]`, `..._a_changed_state_is_still_checkpointed_promptly`, `..._a_loop_iteration_with_pruning_due_over_a_50_mb_ledger_stays_fast_and_walks_nothing`, `..._the_post_facts_of_an_opened_and_a_closed_position_do_not_scan_the_ledger` |
| R2.AC4 | `tests/runner/test_r2_ac4_ac5_restore.py`: `test_R2_AC4_a_pending_share_whose_fill_the_broker_holds_is_not_dropped_and_no_position_without_share_is_flagged`, `..._the_reload_reconciles_so_the_share_is_open_and_has_its_stop_at_once`, `..._the_valid_copy_is_not_closed_as_an_orphan_at_the_first_reconcile` |
| R2.AC5 | same file: `test_R2_AC5_kill_after_an_add_fill_keeps_one_full_size_sl_at_every_kill_point`, `..._an_sl_whose_quantity_equals_the_brokers_share_quantity_is_never_cancelled`, `..._after_a_take_profit_fill_the_sl_is_not_larger_than_the_position_and_no_valid_share_is_closed`, `..._a_stale_checkpoint_stop_never_replaces_a_tighter_broker_stop` |
| R2.AC6 | `tests/paper/test_r2_restore_dedupe.py`: `..._two_surviving_stops_for_one_share_leave_exactly_one_live_stop`, `..._the_duplicate_is_cancelled_in_the_ledger_so_a_second_restart_does_not_find_it_live`, `..._the_surviving_stop_still_triggers_exactly_once`, `..._a_stop_whose_share_is_gone_is_cancelled_with_a_reason_and_not_registered`, `..._a_stop_that_differs_in_trigger_is_not_a_duplicate` |
| R2.AC7 | `tests/selection/test_r2_ac7_pacing.py`: `..._the_cooldown_after_a_budget_refusal_is_the_stated_wait_so_no_request_precedes_it`, `..._refused_attempts_over_ten_minutes_are_far_below_one_per_slice`, `..._a_pass_over_50_candidates_completes_in_about_the_minimum_time_the_budget_allows` |

Shared helpers: `tests/runner/r2_support.py` (open copy, add, kill-point enumeration, ledger-walk counter, sleep log, 429 switch,
measured loop iteration). The existing fake HL is not modified: 429 is produced by wrapping its `_reply` on the instance.

## Run summary (targeted runs only, never the full suite)

44 tests: 32 fail, 12 pass. Failure reasons: 32 assertion failures that name the defect (no import, collection or fixture
errors). The 12 passing tests are deliberate guards, not defects in the tests:

* AC6 (5): pins of existing behaviour (the gap was surviving mutants). Mutation check done by hand on `PaperBroker._restore_stop`:
  removing the duplicate guard fails 2 tests, removing the cancel inside the branch fails 2, removing the `share is None`
  half fails 1.
* AC7 (1): completion time of a 50-candidate pass (guards against a fix that over-waits). With a prototype fix (cooldown =
  stated wait) the thresholds were checked: refusals 20 today, 10 with the fix; pass time 730 s both (minimum ~620 s).
* AC5 (1): `stale_checkpoint_stop_never_replaces_a_tighter_broker_stop` passes today (the restored `best_px` keeps `_trail`
  from loosening); it guards the fix, which will take the stop from the broker.
* AC3 (3): restart remembers every seen signal (clean and kill -9), and a changed state is still checkpointed: guards for the
  delta/force-interval fix.
* AC1 (1): entries stay refused while the clock is untrusted (guard for the catch-up).
* AC2 (1): `allMids` over 429: REST `allMids` is called at start only, never in the loop.

Per AC (fail/pass): AC1 9/1, AC2 10/1, AC3 5/3, AC4 3/0, AC5 3/1, AC6 0/5, AC7 2/1.

## Findings the tests surface (for the developer)

* RISK-67 breadth: besides the forced resample, these requests block the trading thread for 48 to 205 s of back-off under 429:
  the periodic `ClockSync.tick` estimate (`runner.step` first line, outside the lock, every 600 s), `metaAndAssetCtxs` (205 s;
  hourly delisting check and rules refresh), `fundingHistory` (160 s; hourly funding boundary), `userFillsByTime` (145 s;
  reconciliation/audit/gap resync), `clearinghouseState` (55 s; leader reconciliation every 300 s, under `gate_lock`),
  `candleSnapshot` (48 s). `allMids` is start-up only.
* The PO's "< 200 KB/h idle" cannot hold: `component_heartbeat` (one record per `ledger.heartbeat_interval_s` = 10 s) is 180 KB/h
  by design (4 MB/day, not RISK-59). The bounds used: checkpoint records <= 8/h and <= 25 KB/h, idle growth without the
  heartbeat <= 100 KB/h, with it <= 300 KB/h. Today: 355 KB of checkpoints and 572 KB total per idle hour.
* Reload: `restore_state` books a PENDING_ENTRY share closed even when the broker holds its fill (position_without_share
  pause, orphan close at the first reconcile 300 s later). `verify_protection` compares stops with the stale checkpoint
  quantity: after an add it re-places a 1.00 SL and cancels the correct 1.60 one; after a take-profit it keeps a 1.00 SL for 0.50.
* Selection pacing: the refusal's "would wait X s" is only in the message; the cooldown is the doubling 1 s base, so the second
  attempt 10 s later is refused again (20 refusals per 10 minutes, 10 with the stated wait).

## What the suites prove, and what they do not

* AC1/AC2: the loop's observable behaviour (fill time, bounded iteration, `/flatten` not blocked) over real sockets and the real
  components. They do not prove the real-network behaviour of a Brazilian round trip: /qa measures the real `l2Book` round
  trip and uncertainty; a real 429 storm is simulation territory. Wall-time bounds (2 s, 0.25 s) are generous (a normal iteration
  is a few ms) to stay stable on slow machines.
* AC3: a 50 MB synthetic ledger (filler records no component reads) stands in for weeks of data; real growth over 2-4 weeks is
  checked in /qa-simulation. Start-up cost (the restart still makes about five whole-ledger passes) is NOT pinned: only the
  loop and the post facts are; read-once-at-startup is advisory.
* AC4/AC5: every kill point between the event and the next checkpoint (ledger truncated there). Not covered: a kill during the
  reload itself (R0 torn-restore tests cover it) and funding-boundary interplay.
* AC6: the unit-level restore only; the runner-level two-restart test already exists (`test_failsafe_restart`).
* AC7: the real `wiring._FailFastSleeper` is imported (private name): if it is renamed, update the import. It does not cover the
  real exchange's weight accounting (F3 tests do).
* Not tested here by design: live orders or keys (none exist), mutation score of the fix (run the senior-dev mutants again at /review).

## R2b addendum (round-1 fix batch: RISK-73..79, R2-SD1..SD3; R2b.AC10 progress lines moved to the R3 branch)

All new tests fail on current src unless listed as guards. No existing test was edited. Shared helpers in `r2_support.py`.

| AC | Tests (file) |
|---|---|
| R2b.AC1 (RISK-73) | `tests/runner/test_r2b_ac1_catch_up.py`: slow first estimate (12 s / 30 s) does not push broker time ahead and the stop fills; bogus future book time; wall-clock step forward after a restart; offset estimate times only its final attempt |
| R2b.AC2 (RISK-74) | `tests/runner/test_r2b_ac2_thread_safety.py`: RateBudget (wait_ms vs record, expiry, concurrent acquires, exact totals), SchemaFailureMonitor alert-once, AccessMonitor (guards, pass today), `_delistings` exception does not escape step |
| R2b.AC3 (RISK-75, R2-SD3) | `tests/runner/test_r2b_ac3_all_rest_hanging.py`: loop iteration duration with every REST endpoint hanging and 5 leaders; each endpoint alone; /flatten waits at most the bound; funding retries >= 10 s apart |
| R2b.AC4 (R2-SD1) | `tests/runner/test_r2b_ac4_heal_wrong_size_stop.py`: a stop of another quantity [0.40, 1.50] is replaced; right-size stop still taken (guard) |
| R2b.AC5 (R2-SD2, RISK-79b) | `tests/ledger/test_r2b_ac5_read_from.py`: unterminated last line (guard, passes: read_from already leaves it); bad line logged and skipped, also with a kinds filter |
| R2b.AC6 (RISK-77) | `tests/runner/test_r2b_ac6_reload_reconciles.py`: share opened/filled in the checkpoint gap is not closed as orphan; known and protected right after start; OPEN share whose SL filled after the checkpoint is no ghost (checkpoints stretched by the module constants) |
| R2b.AC7 (RISK-76) | `tests/runner/test_r2b_ac7_reconcile_retry.py`: after a failed leader read a new attempt within 90 s (not +300 s) |
| R2b.AC8 (RISK-78) | `tests/runner/test_r2b_ac8_synced_start_keeps_guard.py`: synced restart + wall step +300 s before step 1 is refused as `clock_jump` |
| R2b.AC9 (RISK-79a) | `tests/runner/test_r2b_ac9_resample_off_lock.py`: gate_lock acquirable while the forced resample request hangs |

Run summary (targeted): 36 tests, 27 fail on assertions naming the defect, 9 pass as deliberate guards (AC2 x4 incl. AccessMonitor and world fixture sanity, AC3 x3: l2Book/fundingHistory alone and the 1 s-step variant already within the bound, AC4 x1, AC5 x1). RISK-73 probe reproduced as AC1 (first estimate 12/30 s, later estimates uncertain, SL never fills).
Notes for the developer: AC3 bound is 3 s of loop time, code constants only (no new config key). AC7 bound 90 s covers max(wait_s, 30 s). AC6 relies on `runner_module.CHECKPOINT_MIN_INTERVAL_S` / `CHECKPOINT_FORCE_INTERVAL_S` module constants. AC9 probes `runner.gate_lock.acquire(timeout=0.1)` from the test thread.
Not covered here: real-network RTT (QA), long-run lock contention (simulation), advisory R2-SD4/5/6 (no test).

## R2c addendum (round 3, final mini-round: R2-V2-1..V2-5; no src and no existing test edited)

| AC | Tests (file) | Today | Mutant it kills |
|---|---|---|---|
| R2c.AC1 (V2-1) | `test_r2c_ac1_agreeing_future_books.py`: two agreeing books stamped +60 s / +600 s: broker time never ahead (every step), and once the bogus stamps age out of the hub the stop fills within 30 s of loop time | 2 pass (guard) | `catchcap` (`confirmed > clock.now_ms() + CATCH_UP_MAX_AHEAD_MS` removed): verified by hand on a copy, both fail with "58600 / 598600 ms ahead" |
| R2c.AC2 (V2-2) | `test_r2c_ac2_leaderboard_and_ws_hang.py`: leaderboard GET hanging + leader-feed WS connect hanging (loopback `SwitchProxy` that accepts TCP and never answers the handshake): iteration < 3 s and the stop fills; leaderboard alone; hub (market) reconnect alone; no `loop_stalled` in 60 loop-seconds; /flatten does not wait on gate_lock | 4 fail (iteration blocked 60 s / 61 s / 20 s / 10 s), 1 pass (flatten: guard, the cycle runs outside gate_lock) | any fix that leaves either call on the trading thread beyond the bound |
| R2c.AC3 (V2-4) | `test_r2c_ac3_partly_spent_budget.py`: `TradingSleeper` with an injected monotonic clock: 1.5 s spent leaves 0.5 s; spent budget refuses; new iteration restores; a non-trading thread's call is capped at 2.0 s when `hl.rest_timeout_s` is 10 | 15 pass (guard) | `loopbudget` alone: 5 fail; `restbound` alone: 4 fail (the non-owner-thread tests, where the iteration budget cannot mask the cap); verified on copies |
| R2c.AC4 (V2-5) | `test_r2c_ac4_clock_worker_joined.py`: estimate hanging at stop (released 1 s into `stop()`): no live `r0-clock-estimate` thread when `stop()` returns | 1 pass (guard) | `join` (clock_worker.join removed): fails, verified on a copy |
| R2c.AC5 (V2-3) | `test_r2c_ac5_exhausted_budget_entries_and_exits.py`: two entries after a spent budget are skipped with `signal_skip` reason `no_leader_av` (no share opened, iteration < 3 s); a leader close and a triggered stop still close our copy within the paper ack latency (6 x 500 ms, same as with no hang) | 3 pass (guard) | n/a (pins behaviour) |

Reading of the code for AC5: exits are NOT starved. `PositionManager` reads REST only for opens (ATR candles, `clearinghouse_state`), adds (ATR) and a wrong-direction reduce (failure caught); a leader close and the broker's stop use books only. No ESCALATE.
Run summary (targeted): 27 tests; 4 fail (all R2c.AC2, on assertions naming the blocked seconds), 23 pass as guards for already-correct behaviour and mutants. Not covered: DNS stalls (socket timeouts do not cover name resolution; /qa on the PC), a hub reconnect hang cannot be combined with a stop fill (no books arrive without the hub: only the bound is pinned). AC2 failing runs take about 4 min (real hangs of 10-60 s); with the fix they take seconds. No new config key is needed.
