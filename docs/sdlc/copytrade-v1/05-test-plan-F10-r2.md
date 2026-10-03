# F10 round 2 mini-round: test plan (RISK-20, RISK-21)

Source: `reviews/F10-architect-r2.md`, `reviews/F10-r2-blocking.md`. Paper only. Real gate, real `PaperBroker`, real
authority and ledger; only time, books, meta, returns and the unbuilt F12 (share book) are faked. No `src/` change, no
existing test edited or weakened (none contradicts).

## Pinned contracts
* `FlattenReport.still_open: tuple[tuple[str, str, Qty], ...]` = `(coin, share_id, qty)` of every share in a FRESH
  `broker.positions()` (after the loop) not covered by an ACCEPTED flatten close of this run. A close refused
  `exceeds_position` does not cover; an accepted-but-unfilled close does. `in_flight` unchanged (fresh `pending_entries()`).
* Flatten loop: after the pause, passes re-read `broker.positions()`, close every uncovered `(coin, share_id)` (full
  `share_qtys`, re-reading `position(coin)` before each), stop after a pass with no newly accepted close, hard cap on passes
  (a share that never closes cannot loop; test bound: returns within 30 s and at most 10 outcomes). Every pass's outcomes are in
  the report, so every `broker_events` reaches the caller (the entry's fill event is in some outcome).
* RISK-21: an ADD's record outlives `pending_entries()` while the broker still holds the share AND broker share qty > book
  qty for that `(coin, share_id)`; counted as an extra exposure (same coin, share id, leader; `open_risk_usd` = approved risk)
  in share, symbol, leader, total, bucket sums; not in `unbooked_share_ids` (no `position_mismatch`); dropped when book qty >=
  broker qty or the share is no longer held. `_size_add` share-used = counted risk of every exposure with that coin and share id.

## Matrix: finding -> tests
| Finding | Tests |
|---|---|
| RISK-20a (T20a) | `tests/risk/test_r2_flatten.py`: `RISK20a_an_entry_that_fills_during_the_flatten_is_closed_in_the_same_flatten`; `..._the_fill_of_the_entry_closed_..._closes_the_whole_filled_quantity`; `..._an_entry_not_yet_due_is_in_flight_and_not_still_open`; `..._the_next_flatten_closes_the_entry_that_was_not_yet_due` |
| T20a2 | `RISK20a2_the_passes_send_one_close_per_share_and_produce_no_duplicate_outcomes`; `RISK20a2_a_rerun_in_the_same_run_id_sends_no_second_order_for_closed_shares` |
| RISK-20b (T20b) | `RISK20b_a_close_refused_exceeds_position_is_reported_as_still_open`; `..._a_new_run_after_the_reduce_fills_closes_the_residual`; `..._a_share_that_cannot_be_closed_never_makes_the_flatten_loop_forever`; `..._only_the_uncovered_share_is_still_open_when_another_share_closes` |
| T20c | `RISK20c_flatten_with_nothing_open_and_nothing_pending_returns_an_empty_report_and_pauses` |
| RISK-21 (T21a) | `tests/risk/test_r2_add_risk.py`: `RISK21a_a_second_add_decided_when_the_first_fills_sees_the_first_adds_risk`; `..._the_share_never_exceeds_its_cap_after_both_adds_fill`; `..._the_refusal_of_the_second_add_is_not_a_position_mismatch` (guard) |
| T21b | `RISK21b_an_open_on_another_coin_..._sees_its_risk_in_the_total`; `..._the_leader_cap_of_the_adds_leader_counts_the_filled_add`; `..._the_symbol_cap_counts_the_filled_add_for_an_open_on_the_same_coin` |
| T21c | `RISK21c_the_record_is_dropped_when_the_book_catches_up_so_nothing_counts_twice` (real F12-style book update); `RISK21c_nothing_leaks_after_the_share_is_fully_closed` (guard today, catches a leak after the fix) |

## Run summary (`uv run pytest -q`)
New tests 19 (flatten 11, ADD risk 8). Failing on purpose: 17 (11 + 6). Passing guards: 2 (position_mismatch not raised; no leak
after close; they pin non-regression for the fix). Existing: 4,563 pass, unchanged. Total: 4,565 passed, 17 failed.
Failure reasons: 9 `AttributeError: 'FlattenReport' has no attribute 'still_open'` (the new field), 2 behaviour assertions on
the flatten (SOL not closed: `['E1'] == ['E1','S10']`; `StopIteration`: no SOL close sent), 6 behaviour assertions for RISK-21 (second ADD
approved at 2.70, true share risk 5.70 vs cap 3.0; total 14.0 + 1.5 > 15; leader/symbol cap 3.3 exceeded; `before` check 1.5 vs 1.0).
No import, fixture or collection errors. ruff, ruff format, mypy clean.

## Ambiguities resolved
* T20a2 "re-run in the same run_id produces no duplicate_order outcomes": read as (1) inside one call the passes never resubmit a
  covered share (no `duplicate_order` outcome, one close per share), and (2) a second call in the same run sends no new order and
  accepts nothing. Not pinned: whether the second call reports `duplicate_order` outcomes for still-pending closes or lists them in
  `still_open` (the architect's text allows both); existing `test_F10_B6_running_flatten_twice...` stays valid.
* The not-yet-due entry (T20a) is tested in a separate test from the due entry (an entry decided at a later time would itself
  advance the broker and fill the first).
* The pending partial REDUCE (T20b) is a normal REDUCE accepted at T0 and filling at T0+1000; flatten runs at T0.
* ADD-race numbers: equity 300, `max_position_notional_equity_mult` 3.0 so the notional cap does not mask the share cap; stop 1.00
  from price; leader/symbol caps lowered to 3.3 in their own tests so they bind.
## Not covered here
Mutation re-run (senior-dev), reviewer-risk re-probes, F21 supervisor re-run cadence and the single gate lock (R0/F21), real exchange
partial fills (replay/simulation gates).
