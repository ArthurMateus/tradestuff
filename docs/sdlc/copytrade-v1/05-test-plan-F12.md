# F12 test plan: position manager (money path)

Tests: `tests/positions/` (real `RiskGate`, real `PaperBroker`, real `GateAuthority`, real F2 ledger, real F12 manager).
Faked boundaries only: exchange-time clock, equity source, F4 candle reader, the leader's `clearinghouseState` and
`userFillsByTime`, the F9 entry policy (not built) and the alert sink. No `sleep`. Money-path: fail-closed boundaries
included. Every test fails today with `ModuleNotFoundError: copytrade.positions` (no stubs written, as instructed).

## Pinned public API (the developer's contract)

`copytrade.positions.book.PositionBook()` implements `risk.ports.ShareBook` (`open_shares() -> Sequence[ShareExposure]`,
only shares with status `open`, `open_risk_usd >= 0`; pending entries are NOT listed, the gate counts them itself) and adds
`state(share_id) -> ShareState | None` and `states() -> tuple[ShareState, ...]` (all shares ever, insertion order).
It is built first, passed to `RiskGate(shares=book)` and then to the manager (the gate and manager are circular otherwise).

`copytrade.positions.types.ShareState` (frozen): `share_id, trade_id, signal_id, leader, coin, is_long, status
("pending_entry" | "open" | "closed"), qty, entry_px (average fill price), initial_stop_px, current_stop_px,
initial_risk_usd, open_risk_usd (= qty x |entry_px - current_stop_px|, 0 when the stop is past the entry),
max_committed_risk_usd, atr (stored at entry), best_px, tp_done`.

`copytrade.positions.manager.PositionManager(*, config, gate: RiskGate, broker: PaperBroker, book: PositionBook,
ledger: Ledger, alerts: AlertSink, exchange_time: ExchangeTime, candles: CandleReader, leader_state: LeaderState,
leader_fills: LeaderFills, policy: EntryPolicy, run_id: str)`. Ports (Protocols in `positions.types`):
- `CandleReader.get(coin, interval, start_ms, end_ms) -> Sequence[Candle]` (the F4 `CandleStore.get` signature)
- `LeaderState.clearinghouse_state(wallet) -> ClearinghouseState` (account value for sizing and reconcile)
- `LeaderFills.user_fills_by_time(wallet, start_ms, end_ms) -> Sequence[Fill]`
- `EntryPolicy.vol_mult(signal) -> Decimal | None` (`None` vetoes; F9 implements it later)

Methods: `on_signals(signals)` (the F7 `SignalSink`; never raises for a skipped or failed open), `advance_to(now_ms)`,
`on_mark(MarkUpdate)`, `on_delist(coin, settlement_px, time_ms)` (each wraps the broker call and books the returned events,
and `advance_to` also runs reconcile and audit when due), `on_broker_events(events)` (idempotent), `flatten(*, run_id) ->
FlattenReport` (books every pass), `reconcile()`, `on_resync()` (= reconcile now), `run_fill_audit()`, `leader_dropped(wallet)`.

`copytrade.positions.rules` (pure, Decimal): `atr(candles, *, period, before_ms) -> Decimal | None` (mean true range of the last
`period` bars closed at or before `before_ms`, needs `period + 1` bars, `None` if short or not positive; this is F5's
`CandleBook.stop_distance` maths: share it, closes the F5 M14 follow-up), `trailed_stop(*, is_long, current_stop_px,
entry_px, initial_stop_px, best_px, atr, trail_start_r, trail_atr_mult) -> Decimal`, `reduce_plan(*, share_qty, fraction,
px, sz_decimals, min_order_usd) -> ReducePlan(kind, qty)` with kind `reduce | partial_below_min |
close_all_remainder_below_min`.

Ledger kinds written by F12 (payload keys): `share_state` {event, share_id, leader, coin, qty, entry_px, stop_px,
open_risk_usd, reason?} with events `opened, added, reduced, tp_filled, tp_skipped, stop_moved, closed, liquidated,
delisted, entry_rejected, ghost_share_dropped`; `signal_skip` {signal_id, leader, coin, share_id?, reason} with reasons
`no_atr, invalid_stop, no_share, partial_below_min, first_exit_won, invalid_signal, policy_veto, no_leader_av`;
`missed_exit` {missed_exit_id, leader, coin, share_id, event_type, event_exchange_ms, detected_ms, lag_ms,
case (late|orphan|reconstruction_failed), found_by (live|reconciliation|daily_audit|final_audit)}; `go_live_blocker`
{type "ME", missed_exit_id}; `fill_audit` {leader, start_ms, end_ms, complete}; `audit_breach` {leader, stretch_start_ms}.
Alert kinds: `missed_exit` (message holds `n/3` and `ME`), `reconcile_close`, `reconcile_failed`, `leader_mismatch`,
`position_mismatch` (broker versus book), `bad_signal`.

## Coverage matrix

| AC | Tests |
|---|---|
| F12.AC1 | test_ac1_shares.py: share_holds_qty_entry_stops_tp_risk..., leader_event_changes_only_that_leaders_share, book_implements_the_F10_port..., pending_entry_is_not_listed..., open_risk_is_never_negative..., short_share_mirrors..., share_ids_are_deterministic_unique..., client_order_ids_are_deterministic..., entry_fill_price_not_decision_price..., every_share_state_change_is_ledgered_in_order |
| F12.AC2 | test_ac2_stops.py: atr_* (3), trail_* (4), stop_never_widens_over_random_paths (10,000 examples), the_stored_stop_never_widens_through_the_real_stack, initial_stop_is_placed_through_the_gate_after_the_entry_fills, no_stop_is_sent_before_the_entry_fills, short_stop..., stop_multiplier_comes_from_config, atr_ignores_the_bar_still_forming, atr_uses_the_configured_interval_and_period, one_bar_short_of_the_period_skips_the_open, candle_source_failure_skips_the_open, take_profit_* (5), stop_loss_fill_closes_the_share, trailing_* (6) |
| F12.AC3 | test_ac3_partials.py: the three spec vectors, boundaries at exactly $10 (reduce and remainder), lot rounding, plan properties (Hypothesis), leader_reduce_reduces_by_the_fraction, partial_below_minimum_is_skipped_logged, remainder_below_minimum_closes_the_whole_share, reduce_after_a_take_profit, mirrored add (proportion, average entry, gate refusal, second add on booked qty); test_invariants_failsafe.py: reduce_fraction_of_exactly_one |
| F12.AC4 | test_ac4_first_exit.py: leader_close_closes_our_share, after_our_stop_closes_the_share_later_leader_events_are_ignored, leaders_next_open_..._is_a_new_signal, reduce_to_nonzero_keeps_the_ignore_window_open, flip (close first, open after the fill; open waits; flip after our stop; open refused), pre_existing_and_unparsed_are_ignored, exit_for_a_share_we_never_opened, other_leader, redelivered_signal, clock_flag, veto/leader-state failure |
| F12.AC5 | test_ac5_ac6_reconcile.py: leader_flat, leader_reversed, still_long_changes_nothing, dropped_reduce_caught_by_size_comparison, size_mismatch_without_fill, failed_leader_state_fetch, runs_every_interval_and_after_a_resync |
| F12.AC6 | same file: found 61 s late versus exactly 60 s (reconcile and live), paused mirror still missed, detection never pauses, blocker and running count (n/3), partial skip not missed, skip at 61 s missed, two on one share; test_ac4: leader close after our SL is not missed; test_ac3: skip is never a missed exit |
| F12.AC7 | not covered here: [simulation] gate (shadows on recorded data); see below |
| F12.AC8 | test_ac4_first_exit.py: dropped_leader_keeps_its_shares_managed..., dropped_leader_share_is_still_closed_by_its_stop |
| F12.AC9 | not covered here: [simulation] gate |
| F12.AC10 | test_ac10_audit.py: window bounds, orphan by daily audit, close and reopen, close then our own stop 5 minutes later, 60 s versus 61 s handled by our stop, coin without a share, handled in time, no duplicate with a live record, only leaders with a share, due from the loop, ledgered coverage, 71 h no breach, 72 h breach at the stretch start, failing audit does not stop exits |
| F10/F11 contracts | test_broker_events.py: events of a gate advance booked before return, on_broker_events idempotent, flatten books every pass and a second flatten finishes an in-flight entry, partial entry and partial exit fills, liquidation, delisting, exits independent of meta, oversized CLOSE (`exceeds_position`, RISK-12) resyncs, alerts and retries with a new deterministic id; broker reconciliation in test_ac5_ac6 (orphan, ghost, quantity drift, agreement) |
| Invariants | test_invariants_failsafe.py: A1 (static: no broker submit, stop or token use outside the gate; every order and stop carries a gate token), A2 (stop <= 0, malformed fraction, failing alert sink, exits with every F12 source down), A5 (replayed signal), A6 (no floats), A8 (entry rejected at fill) |

## Pinned ambiguities (defaults chosen; the PO or PM may overrule)

1. Entry stop is computed twice: a pre-order estimate from the signal price (needed for `OpenRequest.stop_px`), and the
   final stop from the entry FILL price after the fill (spec AC2). ATR is stored at entry; the trail uses that stored ATR
   (no live refresh, so a trail never needs candles).
2. `initial_risk_usd` and `open_risk_usd` exclude the estimated exit fee (the spec R definition adds it; F18 owns that).
3. Trail starts at best mark >= `trail_start_r` R (inclusive) and the stop = best -/+ `trail_atr_mult` x ATR, only if it is
   protective-direction tighter. Stops move by cancelling the old SL (`broker.cancel_stop`) and placing a new one through
   the gate (`StopRequest`, new signal id). After a TP fill or an add, the SL is re-placed for the share's current quantity.
   When a share closes, its remaining stops are cancelled.
4. TP $10 rule: the TP part is skipped (`tp_skipped`) when `tp1_fraction x qty` (rounded down to the lot) is under the minimum
   order or leaves a remainder under it.
5. An add never moves the share's stop (never widens); the add uses the share's stored stop as `current_stop_px`.
6. First-exit-wins window closes at the leader's next event that takes the leader flat; then the next OPEN is a new signal.
7. Late-mirror timing: lag = exchange "now" at the moment F12 sends the order minus the signal's exchange timestamp; missed
   iff lag > 60 s. A leader exit found by reconciliation or audit is case `orphan`; a live late one is `late`.
   Event time of a reconcile-found exit is the time of the leader's first unprocessed exit fill; with no fill found, F12
   alerts `leader_mismatch` and does NOT close (an unknowable event is never guessed).
8. A failed reconcile or audit fetch never closes or changes a share; exits never depend on candles, leader state, the
   policy, meta or the alert sink.
9. A flip's open leg waits for the close fill; if our share was already closed (our stop), the open leg is a plain OPEN.
10. The audit's first interval starts when the manager is built; `audit_breach` is recorded at 72 h from the first failed
    attempt without a run concept (F18 decides whether it lies inside `[t0, T_eval]`).
11. An ADD sent while the share's entry is still pending is not pinned beyond "book equals broker afterwards".
12. A reduce with fraction `None`, `<= 0` or `> 1` is skipped as `invalid_signal` with a `bad_signal` alert; fraction exactly 1
    closes the share.

## Deliberately not covered (and where)

- F12.AC7 and AC9 (shadows, mirror, candle-priced gap fills, cost per trade): [simulation] gate, needs recorded data and the
  F18 evaluator. The "settled gap exit" and "reconstruction failed" cases need F13's downtime port: F13.
- The fill audit's truncated-page handling, alert cadence (`storage.alert_interval_h`) and the final audit up to `T_eval`: F18/F20.
- Restart mid-operation (state in memory only, RISK-8): F13. Wiring and the supervisor loop, locking of gate calls: R0/F21.
- The real F7 detector feeding `on_signals` end to end, and the real `HlRestClient` as `LeaderState`/`LeaderFills`
  (adapters add the `priority` argument): R0 and /qa.
- Mutation testing of `rules.py` and the manager (cosmic-ray, not installed): at /verify.
- Weakness: harness numbers (qty 1.00 at $100, 1x leverage, liquidation at 2.5) were checked against the real gate/broker, but
  nothing could be run against a manager yet; expect the developer to report any test that encodes an unreachable state.

## Run summary (before implementation)

See the commit message of this slice for the final counts: 127 tests collected in `tests/positions/`, 127 fail with
`ModuleNotFoundError: No module named 'copytrade.positions'` (123 through the rig factory or `pos()`, 4 static checks that
assert the package exists).

## Round 1 addendum (fix batch F12-r1)

Files: `tests/positions/test_r1_blocking.py` (RED: fail on the round-1 code) and `tests/positions/test_r1_mutant_pins.py`
(GUARD: pass today, each docstring names the mutant it kills; checked by hand-applying 14 mutants to `manager.py`, all
killed). Clock faking: `ticking_clock` (test_r1_blocking) makes `exchange_now()` advance 100 ms per read like a real
clock, which is how the P3 race (TP fill between the manager's read of pending exits and the gate's own advance) is
reproduced with the real gate and broker; offsets are swept so a fix cannot pass by luck.

### Contracts the developer must meet (what the tests pin)

1. Signal age (RISK-31). `age = exchange_now - signal.exchange_ts.ms`; allowed while `age <= filter.max_signal_age_ms`
   (5000 in the fixture; exactly 5000 opens, 5001 does not). Applies to: a flip's open leg when it fires, every live OPEN
   and ADD, and deferred ADD replays (age measured at replay). Refusal = ledger `signal_skip` with reason `stale_signal`
   and the signal's own `signal_id`, no order, no alert required. Exits are never refused for age: a deferred or late CLOSE
   and a flip's close leg still execute.
2. Flip open leg. Stored with its signal and the share it waits for. It fires only when THAT share closes (not any
   later share of the leader on the coin), only if still fresh, and only if no later leader signal for that
   `(leader, coin)` has arrived since. It is dropped on entry reject, ghost drop, and a later leader signal (any action)
   or new open. Pinned scenarios: P1 (30 min and 6 s close fills, leader closes the flipped short 2 s later), P5
   (rejected entry then flip, with and without the short closed, then a later long opened and closed by the leader; ghost
   drop with a lost reject event; later REDUCE). Not pinned (ambiguity, see below): a close of the waiting share by our
   own stop while the leg waits.
3. Close refused `share_closed` or `exceeds_position` while the share is still OPEN with free quantity (P3): retried once
   with freshly computed free quantity and a distinct deterministic id (the existing `_RETRY_TID` scheme), no
   `_handled` entry and no `track.closing` left behind by the refused attempt. After the retry the last close decision is
   approved, the share is closed within one ack and the book quantity equals the broker's at every point a call returns
   (`test_..._P3_...`, offsets 0 to 900 ms; red at 100 and 200 ms).
4. Reconcile heals a lost entry fill (P2): a `pending_entry` share the broker holds (and has no pending entry for) becomes
   `open` with qty and entry price from the broker's share, `initial_stop_px`/`current_stop_px` from the stored ATR and
   the entry price (98.5 in the harness), share event `opened`, one SL registered for the full quantity through the gate
   (TP too when enabled), alert kind `position_mismatch`, deferred leader signals replayed (a deferred CLOSE gives exactly
   one close order). Leaders with a pending share are read by `reconcile` (`LeaderState.clearinghouse_state` called).
   A pending share that is still pending at the broker is left alone (guard).
5. ADD/REDUCE direction (P4): `sig.is_long != share.is_long` gives `signal_skip` reason `invalid_signal`, no order, alert
   kind `bad_signal`, and a reconcile of that leader (leader state is read). An ADD while `track.closing` (a close of ours
   in flight) is skipped (any reason: the test only requires a `signal_skip` record and no order; suggested
   `invalid_signal`).
6. Names kept as they are: alerts `stop_failed`, `position_mismatch`, `reconcile_close`, `bad_signal`, share events
   `opened`, `ghost_share_dropped`, close reason `stop_failed` / `close_remainder`.

### Coverage matrix (round 1)

| Finding / gap | Tests |
|---|---|
| RISK-31 P1 | `test_r1_blocking.py`: P1_flip_open_leg_older_than_the_signal_ttl (6 s and 30 min), P1_leader_closing_the_flipped_short_cancels..., P5_flip_leg_within_the_ttl_still_fires (guard) |
| RISK-31 P5 and leg clearing | P5_a_rejected_entrys_flip_leg_never_fires... (2), P5_a_ghost_dropped_entrys_flip_leg..., P5_a_later_leader_signal_on_the_coin_cancels... |
| RISK-31 TTL | TTL_an_open_older... (4999/5000 guard, 5001 red), TTL_a_deferred_add_replayed... (also guards the deferred close), TTL_a_live_add_older... |
| RISK-31 liquidation re-check in `_opened` | NOT TESTABLE through the real stack, see ambiguity A |
| RISK-32 P3 | P3_leader_close_while_our_take_profit_fills... (10 offsets, red at 2), P3_a_refused_close_is_retried_with_a_distinct_id |
| RISK-33 P2 | P2_reconcile_heals..., P2_healing_replays_the_leader_close..., P2_reconcile_also_reads_leaders_whose_only_share_is_pending, P2_a_pending_share_still_pending_at_the_broker_is_left_alone (guard) |
| RISK-34 P4 | P4_an_add_in_the_opposite_direction..., P4_a_reduce_in_the_opposite_direction..., P4_..._alerts_bad_signal_and_reconciles, P4_an_add_while_our_close_is_in_flight..., P4_same_direction_add_and_reduce_still_work (guard) |
| Gap: no SL placeable closes the share | `test_r1_mutant_pins.py`: GUARD_a_share_whose_initial_stop_is_refused_is_closed_at_once |
| Gap: new stop before cancelling the old | GUARD_a_refused_trailed_stop_leaves_the_old_stop..., GUARD_a_refused_replacement_after_a_take_profit... |
| Gap: `closing` self-heal, add filling during a close | GUARD_an_add_filling_while_our_close_is_pending... |
| Gap: deferred exit / add replayed after the fill | GUARD_a_leader_close_that_arrived_while_the_entry_was_pending..., GUARD_a_leader_add_that_arrived... |
| Gap: fills booked before the next gate call | GUARD_a_fill_produced_inside_a_gate_call_is_booked_and_protected (open/add x 10 offsets), GUARD_a_fill_produced_inside_an_exit_submit..., GUARD_a_signal_sees_the_fill_that_happened_before_it_arrived |
| Gap: flat and reversed leader boundary | GUARD_reconcile_closes_the_share_when_the_leader_is_flat_or_reversed... (10 cases, long and short) |
| Gap: add sized at the share's stop | GUARD_an_add_is_sized_at_the_shares_current_stop... (qty 1.13) |
| Gap: stop <= 0 | GUARD_an_open_whose_stop_is_zero_or_below... (49.98 / 50 / 50.02 / 60), GUARD_an_add_whose_stop... |
| Section 4 | GUARD_a_trail_that_is_not_tighter_places_no_new_stop, GUARD_after_an_accepted_close_later_leader_exits_send_nothing_more, GUARD_a_pending_share_the_broker_neither_holds_nor_has_pending_is_dropped_as_a_ghost; the audit held-at-event-time bound is already pinned by `test_ac10_audit.py` (window bounds) and is not duplicated |

### Ambiguities and untestable items (for the CTO)

A. Liquidation re-check in `_opened`: with the real stack it cannot be reached. The gate only opens when the liquidation
   price is at least `min_liq_distance_stop_mult` (3) stop distances from the decision price, and the paper broker fills only
   inside a 5 % depth band (`DEPTH_BAND`), so the fill-derived stop can never cross the liquidation price. No test was
   written; if the developer adds the check it needs a unit test of its own with a stubbed broker view, or the PO may
   drop it.
B. A close of the waiting share by our own stop/TP while a flip leg waits: the batch says "any close of the waiting
   share that is not its own flip close" clears the leg; the AC4 test "flip after our stop already closed the share"
   (existing) opens directly. Not pinned either way.
C. "Register the share in the book/_entry_orders BEFORE the submit's events can drain" cannot be provoked through the
   ports (the gate advances before it submits, so an entry's own fill cannot be in its submit's events). Not tested.
D. The P3 race needs a ticking clock; the fix may use any mechanism (sync before reading pending exits, the single retry,
   or both); the test only fixes the outcome.
E. The A8 test step (now + 6001) could not be edited in this run: the tool permission was denied for an edit of an
   existing test, so A8 still fails exactly as before. The edit is the one-line step change described in the batch.
