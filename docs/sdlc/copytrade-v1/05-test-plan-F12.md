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
