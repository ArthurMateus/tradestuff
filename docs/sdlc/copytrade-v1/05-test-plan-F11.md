# Test plan: F11 Paper broker (fills, costs, funding, liquidation, delisting)

Epic copytrade-v1, branch `feat/copytrade-v1/F11-paper`. Money-path feature. Spec: `04-spec.md` F11.AC1-AC8, plus F10.AC1 (gate token), F1.AC3 / AC4, invariants A1, A2, A5, A6, A8, A10, B1, B5, D1, D3.

## Run summary

- 155 new tests in `tests/paper/` (117 test functions, parametrised to 155 cases). Hypothesis property tests: 9 (fill VWAP, fee, funding antisymmetry, liquidation model, liquidation loss bound, cash conservation, flat round trip, token property, liquidation price monotonicity).
- Against the interface stubs: **151 fail, 4 pass**. Every one of the 151 failures is `NotImplementedError` from a stub (breakdown: 151 x NotImplementedError, 0 import/collection/fixture errors, 0 assertion failures).
- The 4 passing tests are static guards that are correct on the stubs by design: package files exist and are scanned (non-vacuous check), no signing/network imports and no `/exchange` literal in `src/copytrade/paper/**` (F1.AC3), no float literal or `float()` in it (F1.AC4/A6), and `submit`/`place_stop` take a `token` parameter with no default. They must keep passing.
- Whole suite: 3090 collected, 2939 pass, 151 fail (all F11). The existing 2935 tests are unaffected (F1.AC3 static scans cover the new package and hold).
- ruff check, ruff format --check and mypy (strict, src and tests) are clean.
- **Validity probe (not committed).** The expected values are hand-computed, so to prove the tests are internally consistent I wrote a throwaway reference implementation in a scratch directory and ran the suite against it: 155/155 pass. It was not committed and the developer must not treat it as a design. 8 hand mutants of it (band 5%->6%, liquidation `<=`->`<`, funding open `<`->`<=`, book age +1 ms, lookahead check removed, min-notional `<`->`<=`, token not consumed, delist fee removed) were each killed by at least one test. Two further mutants were equivalent or no-ops (mine, not test gaps).

## Interfaces the tests pin (stubs in `src/copytrade/paper/`)

| Module | Contents |
|---|---|
| `paper/types.py` | `CoinMeta`, `FundingSnapshot`, `MarkUpdate`, `OrderIntent`, `StopIntent`, `GateToken`, `SubmitResult`, `BrokerEvent`, `PositionView` (data only) |
| `paper/ports.py` | F11-owned ports: `BookSource.first_book_at_or_after`, `MetaSource.fetch`, `FundingSource.funding_at` (F21 wires adapters over F3/F4; F11 imports no unmerged code) |
| `paper/gate.py` | `GateAuthority(key).issue(intent) -> GateToken`, `.verify(token, intent) -> bool` |
| `paper/liquidation.py` | `liquidation_price(side, avg_entry_px, leverage, max_leverage, sz_decimals) -> Price` (F10 reuses it, F10.AC10 property 7) |
| `paper/broker.py` | `PaperBroker(config, books, meta, funding, ledger, clock, alerts, authority)` with `submit`, `place_stop`, `cancel_stop`, `advance_to`, `on_mark`, `on_delist`, `position`, `cash_usd` |

### Gate token shape (for F10)

- F10 holds a `GateAuthority` (constructed with a secret key) and calls `authority.issue(intent)` only after `risk_gate.check()` approves. The same authority object is passed to `PaperBroker`.
- `GateToken(token_id, intent_digest, mac)`: opaque; bound to the exact intent (coin, side, qty, action, client order ID, share and trade IDs, leverage); authenticated with the authority's key; single use; a token is consumed by any validated presentation, even when the order is then refused on its merits (`unknown_coin`, `below_min_notional`, ...).
- `OrderIntent` (market order, OPEN/ADD/REDUCE/CLOSE via `core.domain.ActionKind`) and `StopIntent` (SL/TP on a share) are the two things a token can approve. Exchange-originated events (liquidation, delisting, a stop trigger) need no token.
- The broker's `submit` and `place_stop` have a required `token` parameter; a static test pins that.

## Coverage matrix

Test names are abbreviated by prefix; file in `tests/paper/`.

| AC | Tests (file) |
|---|---|
| F11.AC1 fill model | `spec_example_vwap_is_100_05`, `position_and_cash_after_the_fill`, `sell_walks_the_bids`, `nothing_fills_before_the_ack_delay_elapses`, `snapshots_before_the_fill_time_are_ignored_and_the_first_at_or_after_is_used`, `ack_delay_is_data_driven` (2500 ms), `no_lookahead_a_recorded_future_book_is_not_used_early`, `book_age_boundary_exactly_max_book_age_is_usable`, `book_age_one_ms_over_the_limit_is_refused_no_book`, `no_book_yet_at_exactly_the_window_end...`, `depth_beyond_5pct_of_mid_gives_a_partial_fill...` (records `partial_fill`, remainder cancelled), `a_level_exactly_at_5pct_of_mid_is_included`, `a_level_one_tick_past_5pct_of_mid_is_excluded`, `sell_side_band_boundaries`, `no_depth_inside_the_band...`, `one_sided_or_empty_book...` (3 cases), `half_spread_and_slippage_are_paid_by_crossing_the_real_book`, property `vwap_is_bounded_exact_and_never_overfills` (test_fill_model.py) |
| F11.AC2 fees | `entry_and_manual_close_each_pay_4_5_bps_and_the_trade_nets_them`, `fee_rate_is_data_driven`, `the_maker_fee_key_is_ignored_no_maker_fills_or_rebates`, `every_fill_kind_pays_the_taker_fee_stop_tp_liquidation_delist`, property `fee_is_exactly_notional_times_bps_and_never_negative` (test_fees.py); fee asserted again in the stop, liquidation and delisting tests |
| F11.AC3 funding | `long_pays_positive_rate_at_the_boundary`, `short_receives_positive_rate`, `negative_rate_flips_the_sign`, `nothing_accrues_one_ms_before_the_boundary`, `each_hour_uses_its_own_actual_rate_and_oracle_price_over_a_multi_hour_jump`, `advancing_again_never_accrues_an_hour_twice`, `closing_fill_carries_the_accrued_funding...`, `a_share_closed_before_the_boundary_pays_nothing`, `a_share_opened_after_the_boundary_pays_only_from_the_next_hour`, `pinned_a_fill_at_exactly_the_boundary_ms...`, `a_fill_one_ms_either_side...`, `two_shares_on_one_coin...`, `missing_funding_data_is_not_skipped...`, `funding_only_touches_open_positions`, property `long_and_short_funding_are_exact_opposites` (test_funding.py) |
| F11.AC4 exchange rules | `minimum_notional_boundary` (4 cases: $10.00, $9.999, $10.0008, $9.9999), `minimum_is_data_driven`, `reduce_only_full_close_below_the_minimum_is_allowed`, `a_partial_reduce_below_the_minimum_is_refused`, `unknown_coin_is_refused_and_logged`, `size_is_rounded_down_to_the_lot`, `a_size_that_rounds_to_zero...`, `leverage_above_the_coin_max...`, `an_entry_without_leverage_is_refused`, `a_reduce_or_close_larger_than_the_share_is_refused`, `meta_is_refreshed_every_paper_meta_refresh_min_and_not_before` (59:59.999 vs 60:00.000), `a_coin_listed_after_the_refresh_becomes_tradable`, `meta_unavailable_at_first_use...`, `pinned_a_failed_refresh_keeps_the_last_known_meta...`, `fill_prices_stay_exact_decimals...` (test_exchange_rules.py) |
| F11.AC5 liquidation | `liquidation_price_vectors` (6), property `liquidation_price_model` (200 cases: ordering, distance, monotone in leverage), `position_view_reports_margin_and_liquidation_price`, `no_liquidation_while_the_mark_is_above...` (82.51), `long_liquidated_when_the_mark_reaches...` (82.5, exact P&L and cash), `short_liquidated_at_the_upper_price`, `a_mark_that_gaps_through_both_the_stop_and_the_liquidation_price_is_liquidated`, `a_stop_hit_above_the_liquidation_price_is_a_normal_stop`, `merged_position_uses_the_average_entry_and_liquidates_every_share`, `liquidating_one_coin_leaves_the_others_alone`, property `an_isolated_liquidation_never_loses_more_than_the_posted_margin` (test_liquidation.py); alert kind `liquidated` |
| F11.AC6 delisting | `long_share_is_force_settled...`, `short_share_is_settled_by_buying_back`, `the_forced_settlement_counts_in_every_statistic` (F2 `aggregate_trades`), `every_share_on_the_coin_is_settled`, `pending_stops_are_cancelled...`, `a_pending_order_on_a_delisted_coin_is_rejected_delisted`, `new_orders_on_a_delisted_coin_are_refused`, `delisting_a_coin_with_no_position_or_an_unknown_coin_is_harmless` (test_delisting.py) |
| F11.AC7 stops | `spec_example_long_stop_99_fills_at_the_next_bid_97`, `stop_triggers_when_the_mark_equals_the_trigger_and_not_one_tick_above`, `trigger_uses_the_mark_not_the_book`, `take_profit_long...`, `short_stop_loss_buys_at_the_ask`, `short_take_profit`, `a_second_mark_does_not_create_a_second_exit_order`, `once_the_share_is_closed_its_other_stops_are_inert`, `a_cancelled_stop_never_fires`, `a_stop_on_a_position_that_does_not_exist_is_refused`, `partial_depth_on_a_stop_exit_fills_what_it_can_and_retries_the_rest` (test_stops.py) |
| F11.AC8 rejects | `open_with_no_book_is_refused_no_book_logged_and_never_retried`, `an_add_with_no_book...`, `an_exit_is_never_rejected_for_lack_of_a_book_it_keeps_retrying`, `one_alert_after_alert_after_s_boundary_exact_and_only_one` (9.999 s none, 10.000 s one), `alert_delay_is_data_driven`, `the_exit_fills_as_soon_as_a_book_appears_after_the_retries`, `an_exit_that_fills_promptly_raises_no_alert` (test_rejects.py) |
| F10.AC1 gate token (A1) | `the_broker_entry_points_require_a_token_parameter_with_no_default`, `a_valid_token_is_accepted...`, `every_action_kind_is_refused_without_a_valid_token` (OPEN, ADD, REDUCE, CLOSE), `a_stop_without_a_valid_token...`, `a_token_from_a_different_authority...`, `a_token_is_bound_to_the_exact_intent` (7 field changes), `a_tampered_or_malformed_token...`, `a_token_is_single_use`, `a_token_is_consumed_even_when_the_order_is_refused_on_the_merits`, `authority_issues_unique_tokens...`, `authority_never_raises_on_garbage_tokens`, property `no_order_ever_fills_without_a_valid_token...` (test_gate.py) |
| A5 idempotency | `same_client_order_id_with_a_fresh_token_is_a_duplicate_and_fills_once`, `a_restart_does_not_double_submit...` (new broker over the reopened ledger), ledger-level `has_client_order_id` (test_gate.py) |
| A2 fail closed | `a_ledger_that_cannot_record_the_order_makes_submit_raise...`, `a_ledger_failure_at_fill_time_raises_and_the_broker_keeps_failing_closed` (F2.AC6), `a_missing_config_key_fails_closed_naming_the_key` (9 keys), `out_of_range_config...` (8 boundary cases: limit loads, one step beyond refused) |
| A6, F1.AC4 money is Decimal | `paper_package_has_no_float_literal_and_no_float_call`, `a_float_config_value_is_refused`, `money_returned_by_the_broker_is_decimal_typed_never_float`, exact-Decimal fee/VWAP/funding assertions throughout, properties `cash_equals_wallet_plus_sum_of_trade_pnl_and_each_trade_pnl_is_exact` and `a_flat_round_trip_costs_exactly_two_taker_fees` (test_properties.py) |
| A10, F1.AC3 paper only | `broker_refuses_any_mode_but_paper` (live, testnet, Paper, empty, "paper "), `paper_package_imports_no_signing_client_and_no_network_module`, `a_full_paper_session_makes_no_network_attempt` (no connect, not even loopback) (test_paper_only.py) |
| Ledger via F2 (AC1-AC8) | Every behaviour test reads the real `Ledger` back: fills (`FillRecord`: time source EXCHANGE, coin, side, qty, price, fee, funding, client order ID, trade, share, exit reason), trades (`TradeRecord` with flags `liquidated` / `delisted_force_settle`), `paper_order`, `paper_reject`, `partial_fill`, `paper_funding`. F2.AC4/AC5 consumers: `aggregate_trades` in the delisting and property tests |

## Ledger records F11 writes (pinned payload keys)

- `fill`, `trade`: the typed F2 records.
- `paper_order` (with the ledger `client_order_id`): one per accepted order; the A5 dedupe key.
- `paper_reject`: `client_order_id`, `coin`, `reason`.
- `partial_fill`: `client_order_id`, `requested_qty`, `filled_qty`, `cancelled_qty`.
- `paper_funding`: `coin`, `share_id`, `hour_ms`, `rate`, `oracle_px`, `amount` (cash flow to us; paid is negative).
- Alerts (F1 `Alert.kind`): `liquidated`, `delisted_force_settle`, `exit_unfilled`, `funding_missing`.

## What the suite proves, and what it deliberately does not

Proves: exact hand-computed fills, fees, funding, liquidation, delisting and stop economics; the boundaries in the config table (ack delay, book age, 5% band, min notional, meta refresh, alert delay, hour boundary, liquidation reach); no lookahead; the gate token is mandatory, bound, unforgeable without the key and single-use; idempotency across a restart; every failure listed in the spec (no book, missing meta, unknown coin, ledger failure, missing funding) is an explicit, logged outcome; paper-only and float-free by static scan.

Does not cover (and the later gate that does):
- Merged-position management across leaders, first-exit-wins, mirroring: F12.
- Restart reconstruction of broker state from the ledger (positions, pending orders, funding cursor): F13. Here a restart only proves A5 dedupe.
- The risk gate itself, the "only the risk gate calls `submit`" static test, leverage choice: F10 (it will use `GateAuthority` and `liquidation_price`).
- Opposite-direction orders on a coin that already holds a position (netting): not specified in F11; F10/F12 must never send one. No test.
- Real recorded book/funding payloads: the fixtures here are synthetic fakes at the port (F3/F4 own the wire formats). Replaying recorded books through the port is F16/F21 (simulation). Mutation testing on `src/copytrade/paper/**` (money path) is for senior-dev at review time.
- Performance budget S4 (fill computed within 10 ms): QA/simulation.
- ADL: N/A in paper (spec 7).

## Shared-file needs for a CTO-serialised commit

None. Tests use `tests/paper/conftest.py` (registers the paper ledger as a secret sink via `SECRET_SINKS`, no edit to `tests/conftest.py`) and read the shared fixture `tests/core/helpers.fixture_leaves` only. Per-file `# mypy: disable-error-code="union-attr"` headers are used because `BrokerEvent.fill`/`trade` are optional, so no `pyproject.toml` override is needed.

## Spec issues and decisions needed (details also in the report to the CTO)

1. **Gate token shape** (above): confirm, or F10 to request changes before its tests are written.
2. **Fill time and timing model.** "Snapshot within `paper.max_book_age_ms`" is read as: first snapshot with `time in [decided + ack, decided + ack + max_book_age]` (an age measured forward from the fill time, since replay has no "now"), and never one later than the broker's current time (D1). Confirm.
3. **Exits are re-queued, not cancelled, on partial depth.** AC1 says the remainder of a market order is cancelled; for an exit that would leave an orphan (C4, and AC8 says exits retry until filled). Pinned: entries cancel the remainder (`partial_fill`), exits keep retrying the remainder every `exits.retry_interval_s`. An exit with zero depth inside the 5% band retries; an entry with zero depth is `reject no_depth` (not in the spec).
4. **`no_depth` and a one-sided book.** Mid needs both sides; a one-sided or empty book is `no_depth` for an open. Not in the spec.
5. **Liquidation "loses its margin".** AC5 says the position closes at the liquidation price and loses its margin. With maintenance margin = initial margin at max leverage / 2 the loss at the liquidation price is `margin - maintenance margin`, not the whole margin. Pinned: closes at the liquidation price, P&L = price move minus fees (so the loss is bounded by, and normally below, the posted margin). If the PO wants the full margin lost, AC5 must say the extra maintenance margin is also charged.
6. **Liquidation price formula and rounding.** Pinned to F10.AC4's fixture: `entry x (1 -/+ (1/L - 1/(2 x maxLeverage)))`, rounded with F1 `round_price` (nearest, ties to the lower). "To the tick" in F10.AC10 property 7 is read as this rounding. Merged position: qty-weighted average entry, latest leverage.
7. **Delisting fee.** Settlement is charged the taker fee (conservative reading of AC2 "every fill"; real venues may not charge one).
8. **Funding conventions.** Positive rate: longs pay. Amounts are cash flows to us (paid is negative). A fill at exactly the boundary millisecond does not hold the position over it (strict `open < boundary < close`), which the spec leaves open. Missing funding data is retried and alerted once (`funding_missing`), never skipped (D2/D3). The accrued funding sits on the closing fill's `funding` field and in the trade P&L; entry fills carry 0.
9. **Fee and VWAP exactness.** VWAP is an exact Decimal division (not snapped to a tick); fee = notional x bps / 10,000, unrounded.
10. **Stop trigger.** `on_mark` returns no fill; the exit fills through `advance_to` at trigger time + ack delay. SL: long triggers at mark <= trigger, short at >=; TP the reverse; equality triggers. Once a share is closed its other stops are inert.
11. **Alert timing for unfilled exits** is counted from the decision time (`decided_at_ms + exits.alert_after_s`). The spec does not say from when.
12. **Token consumption on business refusal.** A validated token is consumed even if the order is refused (`unknown_coin`, `below_min_notional`, ...); F10 must issue a fresh token per attempt. Rejected orders do not register their client order ID.
13. **Meta refresh failure.** First load failing gives `meta_unavailable` (no order). A failed refresh keeps the last known meta and retries on the next call (A2 would arguably want a maximum staleness; not specified).
14. **Config validation inside the broker.** The broker re-checks its own keys against the F1 ceilings and fails closed (`ConfigError` naming the key, `ModeNotPermittedError` for mode). It must not trust a hand-built `Config`.
15. **Lot handling.** Sizes are rounded down to `szDecimals` (never up); the min-notional check uses the rounded size and the intent's `decision_px`. `paper.wallet_usd` (Decimal 300) is the starting cash; margin is posted, not deducted from cash.
16. **Leader-side data the recorder does not yet expose.** F4's `AssetContext` carries mark, oracle and funding, but no hourly funding history keyed by hour. F11 defines `FundingSource.funding_at(coin, hour_ms)`; the F21 adapter must map `FundingPoint` and `AssetContext.oracle` onto it.

---

## Round 2 (Amendments 8 and 9): senior-dev round 1 + reviewer-risk RISK-1..7 + the PO's liquidation reading B

New test files (all in `tests/paper/`, no implementation touched): `test_r2_stale_and_opposite.py`, `test_r2_meta_and_failures.py`, `test_r2_gate.py`, `test_r2_funding.py`, `test_r2_determinism.py`, `test_r2_accounting.py`, `test_r2_admission.py`, `test_r2_liquidation.py`, plus the helper module `r2_helpers.py` (fault-injecting wrappers at TRUE boundaries only: alert sink, book/meta/funding ports, disk; a live-style book port; a stuck book port). The real broker, gate authority and F2 ledger are used everywhere.

### Run summary

- `tests/paper`: 476 cases (155 from round 1 + 321 new). Whole suite: 3601 collected. **On the current code: 108 fail, 3493 pass.** All 108 are in `tests/paper`; every other test is untouched and green.
- The 108 = **103 new intentional failures** (below) + **5 existing liquidation tests edited for Amendment 9** (they fail until the developer changes the liquidation fill price).
- Failure reasons: 0 import errors, 0 collection errors, 0 fixture errors, 0 `NotImplementedError`. Every failure is a behaviour failure: an assertion on the wrong result (most), or the very bug the test targets surfacing as an exception out of the broker (a `RuntimeError`, `ValueError` or `lzma.LZMAError` from a sink or port latching the broker, RISK-6), or a missing event (`ValueError: not enough values to unpack` on an empty event list in the late-book test).
- The other 218 new cases PASS on the current code on purpose: mutation-hole tests, controls (an entry on another coin is still fine, an entry on a dropped coin is still refused, the broker time is not the local clock) and the ledger-latch tests.
- **Validity proof.** A throw-away reference fix of Amendments 8 and 9 (scratch copy of `src` outside the repo, `-o pythonpath=<copy>`, never committed, not a design) makes all 476 pass (round-1 tests included, the two edited groups aside as listed below). Ruff, ruff format and mypy (strict) are clean.

### Intentional failures (the developer must make these pass)

| Group | New failing cases | Fix needed |
|---|---|---|
| RISK-1 stale decisions (`test_r2_stale_and_opposite.py`) | 6 (entry refused `stale_decision` x2, exit old decision fills no earlier than broker time x2, funding-boundary test, property) | Refuse OPEN/ADD with `decided_at_ms` < broker time; clamp an exit's decision time to at least broker time |
| RISK-2 opposite side (same file) | 12 (opposite entry refused `opposite_side_entry` x6, two flat-accepted entries never net, liquidated and closed share ids never reused by a pending entry x2, pending entry is not a reduction, leverage not overwritten x2) | Refuse at submit and again at fill time; an entry never reduces; remember retired share ids; keep the position's leverage; a pending entry must not count as a reduction of the share |
| RISK-3 exits/stops without meta (`test_r2_meta_and_failures.py`) | 8 | Exits and stops use the position's stored `sz_decimals` / `max_leverage` |
| RISK-6 non-money dependency failures (same file) | 24 | Catch `Exception` (log, treat as no data / retry) around the alert sink and the book, meta and funding ports |
| RISK-4 gate digest (`test_r2_gate.py`) | 9 | Canonicalise numbers under a fixed explicit Decimal context |
| RISK-5 funding (`test_r2_funding.py`) | 3 | Settle each hour on its own; one `funding_missing` alert per coin per stretch, re-armed once the rate arrives |
| RISK-7 determinism (`test_r2_determinism.py`) | 18 | Attempt-based exit retry that does not depend on the `advance_to` cadence (a snapshot that does not exist yet keeps the attempt alive; only attempts whose book-age window has closed are dropped) |
| Amendment 9 liquidation (`test_r2_liquidation.py`) | 23 | Close a liquidated position at the bankruptcy price `entry x (1 -/+ 1/L)` (average entry of the merged position, its leverage), fee on that fill |

(Counts per group are of the failing cases against the current code; the groups sum to 103.)

### Pinned readings (decisions the CTO/PO should confirm)

1. **"The broker's current time" = the latest time given to `advance_to` / `on_mark` / `on_delist`**, NOT the local clock. `test_R2_RISK1_the_broker_time_is_the_time_it_was_advanced_to_not_the_local_clock` pins it (a replay has no wall clock) and it keeps three round-1 meta-refresh tests unedited, which submit orders decided at `D0` after moving the fake clock an hour without advancing the broker.
2. **A pending opposite entry does not count as a reduction** of the share when an exit is admitted (`_pending_reduction` counts exits only). Follows from "an entry never reduces a position"; without it a pending entry could block the CLOSE of the share it names.
3. **A closed or liquidated share id is never reopened by a pending entry** (no naked short reusing its trade id). The rejection reason is left free (`share_closed`, `opposite_side_entry`, ...); the test only asserts nothing fills.
4. **Merged-position leverage stays the first entry's** (`position("SOL").leverage == 5` after an ADD at 10x or 2x). Round 1 had "latest leverage" in the plan text only; no round-1 test pinned it.
5. **`funding_missing` is alerted once per coin per stretch of missing data** (one alert when B1 is missing while B2 and B3 are known; a new alert only after that coin's missing hours have all arrived and a later hour goes missing).
6. **Bankruptcy price at merged positions** uses the average entry and the position's leverage; each share closes at that one price, so the per-share losses differ but the position's loss is exactly its margin. The vectors use only exactly representable prices (leverages 2, 4, 5, 10, 20, 40 with entries 100 to 300 for SOL and 1000 for BTC), so the tests do not pin whether the bankruptcy price is snapped to the price grid; exponents like 1/3 are deliberately not tested.
7. **A stop trigger or mark stamped before the broker time** is clamped to the broker time (already true in the code; pinned).

### Existing tests edited (and why); nothing else was touched

| File / test | Why |
|---|---|
| `test_fill_model.py::test_F11_AC1_half_spread_and_slippage_are_paid_by_crossing_the_real_book` | Sent a `sell` OPEN (`action=None`) on the long share to pin the mirror fill. Amendment 8: an OPEN opposite an existing position is refused `opposite_side_entry`. Now a `sell` CLOSE of the whole share (same qty, same book, same asserted prices) |
| `test_liquidation.py::test_F11_AC5_long_liquidated_when_the_mark_reaches_the_liquidation_price` | Amendment 9: fill at the bankruptcy price 80 (was 82.5), fee 0.036, trade P&L -20.081 (the whole 20 margin + 0.045 + 0.036), cash 279.919. The trigger 82.5 is unchanged |
| `test_liquidation.py::test_F11_AC5_short_liquidated_at_the_upper_price` | Fill at 120 (was 117.5), P&L -20.099 (margin 20 + 0.045 + 120 x 0.00045). Trigger 117.5 unchanged |
| `test_liquidation.py::test_F11_AC5_a_mark_that_gaps_through_both_the_stop_and_the_liquidation_price_is_liquidated` | Fill price 80 (was 82.5) |
| `test_liquidation.py::test_F11_AC5_merged_position_uses_the_average_entry_and_liquidates_every_share` | Closes at 105 x 0.8 = 84: per-share P&L -16.0828 / -26.0873 (were -13.45898125 / -23.46348125); trigger 86.625 unchanged; asserts the single fill price |
| `test_liquidation.py::test_F11_AC5_property_an_isolated_liquidation_never_loses_more_than_the_posted_margin` | Superseded and renamed `..._loses_exactly_the_posted_margin_plus_fees`: the old bound `loss <= margin` (fees included) is false under reading B. Now: fill at the bankruptcy price, fee on that fill, P&L = -(margin + entry fee + liquidation fee); leverages limited to 2, 4, 5, 10, 20 so the price is exact |
| `test_liquidation.py` module docstring | States reading B |

Not edited, still passing on both old and new code: `test_fees.py::..._every_fill_kind_pays_the_taker_fee...` (fee = qty x price x rate holds at any fill price), the three `test_exchange_rules.py` meta-refresh tests (pinned reading 1).

### Coverage matrix (round 2)

| Requirement | Tests (`tests/paper/`) |
|---|---|
| RISK-1 stale decisions | `test_r2_stale_and_opposite.py`: `..._an_entry_decided_before_the_broker_time_is_refused_stale_decision` (OPEN, ADD), `..._decided_exactly_at_the_broker_time_is_accepted_and_fills` (OPEN, ADD), `..._one_ms_later_than_the_broker_time_is_accepted`, `..._an_exit_with_an_old_decision_time_is_accepted_and_fills_no_earlier_than_broker_time` (CLOSE, REDUCE), `..._a_stop_trigger_with_an_old_mark_time_...`, `..._no_fill_precedes_a_funding_boundary_that_was_already_charged`, property `..._no_fill_is_ever_earlier_than_the_broker_time_at_submission`, `..._the_broker_time_is_the_time_it_was_advanced_to_not_the_local_clock` |
| RISK-2 opposite side | same file: `..._an_entry_opposite_to_a_long_position_is_refused_opposite_side_entry` (OPEN/ADD x S1/S2), `..._to_a_short_position...` (OPEN/ADD), `..._larger_than_the_position_is_refused_and_opens_no_short`, `..._on_another_coin_or_after_the_close_is_still_fine` (control), `..._two_entries_accepted_while_flat_never_net_against_each_other`, `..._a_liquidated_share_never_lets_a_pending_entry_open_a_naked_short_on_its_ids`, `..._a_closed_share_never_lets_...`, `..._a_pending_opposite_entry_never_counts_as_a_reduction_...`, `..._the_leverage_of_a_merged_position_is_not_overwritten_by_a_later_entry` (10x, 2x) |
| RISK-3 exits/stops without meta | `test_r2_meta_and_failures.py`: `..._a_close_still_works_after_a_meta_refresh_dropped_or_broke_the_coin`, `..._a_reduce_uses_the_stored_lot_size_after_meta_broke`, `..._a_stop_can_still_be_placed_and_fires_after_meta_broke` (each: coin dropped, rules invalid, lot changed), `..._a_stop_registered_before_the_meta_broke_still_fires_after`, `..._entries_still_need_meta_...` (control), `..._meta_refresh_failures_of_any_kind_do_not_block_an_exit` |
| RISK-4 gate digest | `test_r2_gate.py`: `..._an_order_token_issued_in_the_default_context_verifies_in_the_broker_for_a_35_digit_price`, `..._a_stop_token_...35_digit_trigger`, `..._a_35_digit_value_stays_bound_to_its_last_digit`, `..._the_digest_does_not_depend_on_the_ambient_context` (7 contexts), property `..._digest_is_context_independent_and_distinct_values_have_distinct_digests` |
| RISK-5 funding | `test_r2_funding.py`: `..._a_missing_first_hour_does_not_block_the_known_second_and_third_hours`, `..._the_missing_hour_is_alerted_once_and_settles_late_when_its_rate_arrives`, `..._the_alert_is_re_armed_after_a_rate_arrives`, `..._a_missing_hour_of_one_coin_does_not_block_another_coin` |
| RISK-6 non-money failures | `test_r2_meta_and_failures.py`: alert sink raising `RuntimeError` / `ValueError` / `LZMAError` on the unfilled-exit alert, liquidation, delisting and missing funding; book port raising (exit later fills; entry does not latch); funding port raising (missing, alerted once, retried); meta port raising on first use (`meta_unavailable`). A ledger or state error still latches: below |
| A2 fail-closed latch | same file: `..._a_ledger_that_fails_on_the_nth_write_latches_every_state_changing_call_and_no_write_follows` (write 1 to 10 of a scripted session x a `LedgerWriteError` disk fault and a `RuntimeError` state fault; afterwards `submit`, `advance_to`, `on_mark`, `on_delist`, `cancel_stop`, `place_stop` raise `PaperBrokerFailedError`, no write is attempted, cash is queryable), `..._writes_enough_records_...` (guards the range) |
| RISK-7 determinism | `test_r2_determinism.py`: 11 scenarios (one-sided book then good at +3500 / +2500, only book exactly `max_book_age` after the attempt / one ms later / stale for the first attempts, one-sided then a book too old for the next attempt, zero-depth exit that later fills with its alert, no book at all, entry with a book exactly at the window end / one ms past / one-sided) x cadences single / coarse 5 s / every second / odd 777 ms / every ms, on a replay port AND a live port (a snapshot exists only once its time has come): identical events, fills, prices, cash; property with arbitrary step times; alert stamped at its due time; late-visible book |
| Partial-exit P&L (a) | `test_r2_accounting.py`: long 2 @100, 1 @110 then 1 @120 (cash 329.8065, trade 29.8065, intermediate cash 309.8605 and no trade), the short mirror (329.8335), a losing then a winning leg, three closes of an inexact 1/3 basis (long and short), four closes of a 1/7 basis, property over any partition (intermediate cash after every leg and final P&L) |
| Gate binding (b) | `test_r2_gate.py`: every field of `OrderIntent` (27 entry/exit cases) and `StopIntent` (10 cases) changes verification and the broker refuses `invalid_gate_token`; separators inside adjacent fields cannot collide (13 characters); order vs stop token; other key; `GateAuthority(b"")` and an empty `bytearray` raise |
| Funding (d) | `test_r2_funding.py`: snapshot of another hour / another coin / zero, negative oracle price / NaN / infinite rate is not accepted (alerted once, retried, accepted when real); entry and exit filling exactly at the boundary ms while another coin is held; an exit one ms after the boundary pays |
| Admission (e) | `test_r2_admission.py`: same-side exit (CLOSE/REDUCE x long/short) and stop (SL/TP x long/short) refused `exceeds_position`; a stop one lot above the share refused for SOL (2 decimals), DOGE (0), BTC (5) and one that rounds down to the share accepted; unknown share / other coin; `liquidation_price` rejects `leverage == max + 1` (5 maxima x 2 sides) and 0; a port answering with a book from before the asked time or of another coin is ignored (entry `no_book`, exit not filled); delisting cancels the coin's stops with reason `delisted` and leaves other coins' stops |
| Amendment 9 liquidation | `test_r2_liquidation.py`: 12 vectors (SOL long/short at 2, 4, 5, 10, 20x; BTC 5x long, 40x short): fill at the bankruptcy price, loss = margin + entry fee + liquidation fee, `flags == {liquidated}`, cash, fee on the liquidation fill; marks between the trigger and the bankruptcy price, exactly at it and gapped through it (long 81 / 80 / 50 / 0.01, short 119 / 120 / 200 / 10000) all close at the bankruptcy price; gap through a stop; trigger unchanged (82.51 nothing, 82.5 liquidates); merged short at the average entry; alert once. Edited round-1 tests: above |

### Mutant to killing test (scratch mutants of the reference fix; each run against the new files only)

88 hand mutants: **85 killed by a new test, 3 equivalent (survived, argued below).** A mutant is killed if any new test fails.

| Mutant | Killed by |
|---|---|
| A1-A9 partial close: forgets earlier realised P&L / earlier fees, basis not reduced or over-reduced, short sign flipped, fee left out of cash, a trade per partial, floor-divided basis, per-unit basis ignoring the closed quantity | `test_r2_accounting.py` long/short partial tests, the 1/3 and 1/7 basis tests (A7, A8) |
| G1-G11, GS1-GS8 digest omits any single field of `OrderIntent` / `StopIntent` | `..._a_token_does_not_verify_when_any_single_order_field_changes[...]` / `..._stop_field_changes[...]` (one case each; GS6 also by the 35-digit test) |
| G12 empty key accepted | `..._an_authority_with_an_empty_key_is_refused` |
| G13 fields joined with `|` (ambiguous encoding) | `..._a_separator_character_inside_a_field_cannot_be_moved_to_the_next_field[|]` |
| G14 verify ignores the intent binding | `..._a_35_digit_value_stays_bound_to_its_last_digit` |
| L1 failure does not latch; L2 only ledger errors latch; L3 latch never checked; L4 x6 `submit`, `place_stop`, `cancel_stop`, `advance_to`, `on_mark`, `on_delist` each unguarded | `..._a_ledger_that_fails_on_the_nth_write_latches_every_state_changing_call_and_no_write_follows` |
| F1 hour mismatch, F2 coin mismatch, F3 `oracle_px == 0`, F4 non-finite rate accepted | `..._a_snapshot_that_is_not_the_hour_the_coin_and_a_usable_rate_is_not_accepted[...]` |
| F5 entry ranked before the boundary, F6 exit ranked after it, F7 closing one coin stops the funding clock of the others | the entry / exit "exactly at the boundary ms while another coin is held" tests |
| F9 alert re-armed on every pass, F10 never alerted | `..._the_missing_hour_is_alerted_once_and_settles_late_...` |
| E1 same-side stop, E3 same-side exit accepted, E10 stop one lot above the share accepted | `..._a_stop_on_the_same_side_...`, `..._an_exit_on_the_same_side_...`, `..._a_stop_one_lot_above_its_share_...` |
| E4 `leverage == max + 1` accepted | `..._liquidation_price_rejects_leverage_one_above_the_coin_maximum...` |
| E5 exit accepts an early book, E6 entry accepts an early book, E7 / E11 a book of another coin (exit / entry path) | `..._a_book_from_before_the_attempt_never_fills_an_exit`, `..._before_the_time_asked_about_is_ignored_for_an_entry`, `..._a_book_of_another_coin_never_fills_an_exit`, `..._a_book_of_another_coin_is_ignored` |
| E8 delisting leaves stops, E9 delisting cancels other coins' stops | `..._delisting_cancels_the_coins_stops_with_the_reason_delisted_and_leaves_other_coins_alone` |
| R1a-R1d `<=`, `< now - 1`, no clamp, local clock as the broker time | stale-decision tests, `..._the_broker_time_is_the_time_it_was_advanced_to...` |
| R2a-R2e opposite entry accepted at submit / not stopped at fill, closed share reusable, leverage overwritten, pending entry counted as a reduction | RISK-2 tests |
| R3a exits use meta, R3b stored rules altered | RISK-3 tests, the stop lot test |
| R4 digest under a 28-digit context | RISK-4 tests |
| R5b a missing hour blocks the later hours | `..._a_missing_first_hour_does_not_block_...` |
| R6a-R6e alert sink / raw book / entry book / meta / funding tolerate only `OSError` | RISK-6 tests, one per port |
| R7a exit fills from a book that does not exist yet, R7c attempts dropped before their window closed, R7f / R7g entry window one ms too wide / narrow | `test_r2_determinism.py` (R7c only on the live port: this is why the live port is there) |
| R9a-R9d close at the liquidation price / at the mark / bankruptcy on the wrong side / off-by-one leverage | `test_r2_liquidation.py` |

Equivalent mutants (survived, and cannot be killed by any test):
- **F8** (every entry restarts the funding clock): an entry stored while a boundary is pending always yields the same next boundary, because everything due at or before the fill time was applied first.
- **R7b** (a missing snapshot moves the attempt to `now`): the attempt only ever bounds the first usable snapshot from below, and no snapshot with a time in `[attempt, now]` exists when the port answered `None`.
- **R7e** (the exit book-age window one retry too wide): an exit is retried every second, so any snapshot is usable by some attempt at or before it, and the fill is at the snapshot's own time. The book-age window is observable for entries only (single attempt): pinned there at exactly `max_book_age_ms` and one ms more (R7f, R7g).

### What round 2 deliberately does not cover

- Restart state (RISK-8, F13), late funding into a trade's P&L (RISK-10, F18/F11 later), margin checks, RISK-11..15, tick performance: not tested, per the brief.
- Whether the bankruptcy price is snapped to the price grid (reading 6): unpinned by design.
- The 104 hand mutants of senior-dev round 1 were not handed to me as a list; the table above is my own set (88 mutants covering their categories a-e and every reviewer-risk item). If the developer or senior-dev reruns theirs, any survivor is a gap to report back.


---

## Round 3 (final fix round): Amendment 10, RISK-13, RISK-15 and the round-2 mutation holes

New files only (no existing test was edited): `tests/paper/test_r3_bad_timestamps.py` (42), `test_r3_share_ids_and_views.py` (14), `test_r3_mutation_holes.py` (26), `test_r3_gate_digits_and_cadence.py` (61). **143 new tests: 44 fail on the current code (d0c7d2e, intentionally), 99 pass** (pins of behaviour that already holds, boundary controls, and the mutation holes). The full suite is 3,743 tests: 3,699 pass and the 44 fail-until-fixed tests fail with assertion errors or an unpacked empty event list (never an import or collection error). ruff, ruff format and mypy are clean.

### Pinned readings (round 3)

1. **The broker's trusted time is the time given to `advance_to`** (Amendment 10). A mark, a delisting or an exit stamped more than `filter.max_signal_age_ms` after it is bad data. The new tests never use `Env.mark` for a bogus mark (it also moves the fake local clock); they call `broker.on_mark` directly. The behaviour before the very first `advance_to` call is not tested (every test advances first).
2. **A bad mark or delisting is ignored**: no events, no state change, no time change, no funding accrual, the broker is not latched, at least one error-level log record and at least one alert (the alert kind is left free, but it is not `exit_unfilled`). A delisting stamped too far ahead is not settled at the trusted time.
3. **A far-future exit `decided_at_ms`** (RISK-19): the test accepts any of (a) the order is refused at once (with a reason), (b) it is accepted and fills at the normal time, (c) it is accepted, waits, and an `exit_unfilled` alert is sent within 20 s. Silent waiting until the stamped time fails. The `tolerance + 1` case passes today by accident (the book-age window is wide enough) and is a control.
4. **The `exit_unfilled_alert` event time** is the exit's own decision time + `exits.alert_after_s`, also when that time is before the broker's time (the alert then comes out on the next call, with the past time), and for a stop trigger the mark's own time (also a late one). Consequence: an exit decided or triggered long ago now also emits the alert event alongside its fill; the tests that check a fill filter on `kind == "fill"`.
5. **RISK-15 (defined here): `position()` returns a view** when the liquidation price is off the grid: qty, average entry, leverage (the position's, not 1), margin and share ids are exact; `liquidation_px` is a fallback that is finite, > 0 and on the loss side of the average entry (the tests do not pin whether it is rounded). `on_mark` never raises, and a mark at or below that trigger (0.0769 for the 2x case, 0.0875 for the 1x case; the tests use marks far on either side) liquidates at the bankruptcy price; stops and closes keep working. A named error instead of a view would fail these tests: if the developer prefers that, the CTO must say so and the test is changed.
6. **RISK-13**: a share is `(share_id, coin)`; closing SOL `S1` by a fill, a liquidation or a delisting leaves ETH `S1`'s stop and its pending exit alone (control: SOL's own stop is still retired).

### Coverage matrix (round 3)

| Requirement | Tests |
|---|---|
| RISK-17 stop is not delayed by a bogus mark | `test_R3_RISK17_a_bogus_future_mark_on_another_coin_does_not_delay_the_stop_loss` (BTC, ETH not held x +5001 ms, +1 h, +30 days): the reviewer's repro, stop fills at the normal time, price, reason, cash |
| RISK-17 liquidation not stamped bogus | `..._the_liquidation_is_not_stamped_with_a_bogus_future_time` (x3 offsets); `..._a_close_decided_at_the_normal_time_still_fills_after_a_bogus_mark` (x3) |
| RISK-17 held coin | `..._a_bogus_mark_on_the_held_coin_is_ignored_even_at_a_liquidating_price` (x3): no liquidation, stop still registered, a normal mark then works |
| RISK-17 time is not advanced | `..._a_bogus_mark_does_not_advance_the_broker_time` (BTC, SOL x3: an entry decided at the trusted time is not stale); `..._does_not_crawl_the_funding_clock_over_an_hour_boundary` |
| RISK-17 tolerance is the config key | `..._the_tolerance_is_filter_max_signal_age_ms_exactly` (500, 2000, 5000: exactly at it advances time, one ms more is ignored); `..._a_mark_within_the_tolerance_still_triggers_the_stop_at_its_own_time` |
| RISK-17 late marks never block | `..._a_mark_that_is_merely_late_never_blocks_an_exit` (an hour old), `..._an_exit_with_a_very_old_decision_time_fills_at_the_broker_time` |
| RISK-17 delisting | `..._a_bogus_future_delisting_is_ignored_and_does_not_move_time` (x3), `..._a_delisting_within_the_tolerance_settles_at_its_own_time` |
| RISK-17 log and alert | `..._a_bogus_mark_is_logged_as_an_error_and_alerted`, `..._a_bogus_delisting_is_logged_as_an_error_and_alerted` |
| RISK-17 alert timing | `..._the_alert_is_timed_from_the_exits_own_decision_time_not_from_the_broker_time`, `..._of_an_exit_decided_in_the_future_within_tolerance_is_not_early_or_late`, `..._of_a_stop_trigger_is_timed_from_the_marks_own_time` (late mark), `..._within_the_tolerance_is_timed_from_the_mark`, `..._a_bogus_mark_never_makes_the_alert_of_a_stop_exit_late` |
| RISK-19 | `test_R3_RISK19_a_far_future_exit_decision_does_not_wait_silently` (+5001 ms, +1 h, +30 days) |
| RISK-13 | `test_R3_RISK13_closing_sol_s1_does_not_drop_the_stop_of_eth_s1`, `..._does_not_cancel_the_pending_exit_of_eth_s1` (each x close fill, liquidation, delisting), `..._closing_a_share_still_retires_its_own_stops_and_exits` (control) |
| RISK-15 | `test_R3_RISK15_position_stays_queryable_when_the_liquidation_price_is_off_the_grid`, `..._the_liquidation_trigger_still_fires_...`, `..._a_stop_still_triggers_and_a_close_still_fills_...`, `..._a_close_still_fills_...`, `..._the_fallback_view_keeps_the_positions_leverage_and_it_still_liquidates_at_its_bankruptcy_price` (2x, 0.075) |
| (f) bankruptcy price 0 | `test_R3_pin_a_1x_long_liquidates_at_the_bankruptcy_price_zero_...` (fill at 0, P&L -100.045, cash 199.955) |
| (a) `on_delist` price | `test_R3_hole_a_on_delist_refuses_a_settlement_price_...` (0, NaN, Inf, -Inf, -1, sNaN: `ValueError`, no state change, not latched, a following submit and a valid delisting work), `..._the_smallest_positive_settlement_price_is_accepted` |
| (b) funding cap | `test_R3_hole_b_a_funding_rate_up_to_the_cap_is_accepted` (0.04, -0.04, 0.03, 0.0299, -0.0299, 0), `..._beyond_the_cap_is_not_a_rate_alerted_and_retried` (0.0401, -0.0401, 0.05, -0.05, 1: no funding, one alert, settles when a real rate arrives) |
| (c) `liquidation_unrepresentable` | `test_R3_hole_c_an_add_is_rejected_when_a_meta_refresh_lowers_max_leverage_below_the_positions_leverage` (order leverage 1, 2, 3 against a position at 5x), `..._an_add_that_pulls_the_average_entry_off_the_grid_...`, control `..._the_same_add_fills_...` |
| (d) stored rules | `test_R3_hole_d_an_add_refreshes_the_positions_max_leverage_and_sz_decimals_and_a_later_exit_uses_them` (liquidation price 85 not 82.5; a 0.55 reduce fills 0.5 after the coin was dropped from meta) |
| (e) duplicate stop id | `test_R3_hole_e_a_stop_with_a_used_client_order_id_is_refused_...`, `..._reusing_an_order_client_order_id_is_refused` |
| (g) gate digits | `test_R3_hole_g_equal_values_with_different_trailing_zeros_share_one_digest` (5 pairs x order qty/price, stop qty/trigger), `..._a_token_for_1_0_verifies_for_1_00_...`, `..._120_significant_digits_can_be_digested_and_verified`, `..._more_than_120_significant_digits_cannot_be_approved_and_verify_is_false` (4 fields), `..._differ_only_at_the_120th_digit_...` |
| (h) exit cadence | `test_R3_hole_h_a_retry_interval_longer_than_the_book_age_window_single_call` (7 cases), `..._the_result_does_not_depend_on_the_advance_cadence` (7 cases x second / odd 777 ms / every ms x replay and live port). Config `exits.retry_interval_s = 5` with `paper.max_book_age_ms = 1000`, inside the F1 bounds (5 s is the ceiling and 1000 ms the floor), so it was testable |

### Intentional failures (44, until the developer fixes the code)

| Group | Count | Tests |
|---|---|---|
| RISK-17 stop, liquidation, close, held coin, time, funding, tolerance, delisting (bogus timestamps) | 28 | the `_bogus_...`, `_tolerance_is_..._exactly`, `..._delisting_is_ignored...` tests above |
| RISK-17 log and alert | 2 | `..._logged_as_an_error_and_alerted` (mark, delisting) |
| RISK-17 alert timing | 3 | own decision time, stop trigger from a late mark, a bogus mark never makes the stop alert late |
| RISK-19 | 2 | +1 h and +30 days (the +5001 ms case passes today) |
| RISK-13 | 6 | stop and pending exit x 3 ways of closing SOL S1 |
| RISK-15 | 3 | `position()`, the liquidation trigger, the 2x fallback view |

Per file: 35 in `test_r3_bad_timestamps.py` (28 + 2 + 3 + 2) and 9 in `test_r3_share_ids_and_views.py` (6 + 3). All other new tests pass on the current code.

### Mutant to killing test (scratch mutants of a reference fix; each run against the four new files only)

The reference fix (in a scratch copy of `src` outside the repo, `-o pythonpath=<copy>`) makes all 143 tests pass. It does: `PaperSettings.max_signal_age_ms`, a `_trusted_ms` set by `advance_to`, `_too_far_ahead` (error log, alert, ignore) in `on_mark`, `on_delist`, and exit `submit` (clamped to the broker time), the alert due time from the own decision or mark time, `_retire_share` by `(share_id, coin)`, and a fallback `Position.view()`. 54 mutants of it: **54 killed, 0 survived.** (First pass: two survived, R15-4 and a5, both because of my own weak tests or a wrong mutant. I added the 2x fallback test and fixed the mutant; both are now killed.)

| Mutant | Result | Killed by |
|---|---|---|
| R17-1 tolerance hard-coded 5000 | killed | `RISK17_the_tolerance_is_filter_max_signal_age_ms_exactly[500]` |
| R17-2 tolerance boundary exclusive (a mark exactly at it is ignored) | killed | `RISK17_the_tolerance_is_filter_max_signal_age_ms_exactly[500]` |
| R17-3 tolerance one ms too wide | killed | `RISK17_a_bogus_future_mark_on_another_coin_does_not_delay_the_stop_loss[btc_not_he` |
| R17-3b tolerance doubled | killed | `RISK17_a_bogus_future_mark_on_another_coin_does_not_delay_the_stop_loss[btc_not_he` |
| R17-4 a bogus mark is ignored only on a coin we do not hold | killed | `RISK17_a_bogus_mark_on_the_held_coin_is_ignored_even_at_a_liquidating_price[one_ms` |
| R17-4b a bogus mark is ignored only on a coin we hold | killed | `RISK17_a_bogus_future_mark_on_another_coin_does_not_delay_the_stop_loss[btc_not_he` |
| R17-5 a bogus mark is clamped to the trusted time and applied instead of ignored | killed | `RISK17_a_bogus_mark_on_the_held_coin_is_ignored_even_at_a_liquidating_price[one_ms` |
| R17-6 a bogus delisting is not checked | killed | `RISK17_a_bogus_future_delisting_is_ignored_and_does_not_move_time[one_ms_beyond_to` |
| R17-6b a bogus delisting is settled at the broker time instead of ignored | killed | `RISK17_a_bogus_future_delisting_is_ignored_and_does_not_move_time[one_ms_beyond_to` |
| R17-7 a far-future exit decision is not checked | killed | `RISK19_a_far_future_exit_decision_does_not_wait_silently[one_hour]` |
| R17-8 exit alert timed from the clamped decision time | killed | `RISK17_the_alert_is_timed_from_the_exits_own_decision_time_not_from_the_broker_tim` |
| R17-9 stop alert timed from the clamped mark time | killed | `RISK17_the_alert_of_a_stop_trigger_is_timed_from_the_marks_own_time` |
| R17-10 not logged at error level | killed | `RISK17_a_bogus_mark_is_logged_as_an_error_and_alerted` |
| R17-11 no alert for bad data | killed | `RISK17_a_bogus_mark_is_logged_as_an_error_and_alerted` |
| R17-13 a mark within tolerance does not advance the broker time | killed | `RISK17_the_liquidation_is_not_stamped_with_a_bogus_future_time[one_ms_beyond_toler` |
| R13-1 pending exits retired by share id only | killed | `RISK13_closing_sol_s1_does_not_cancel_the_pending_exit_of_eth_s1[close_fill]` |
| R13-2 stops retired by share id only | killed | `RISK13_closing_sol_s1_does_not_drop_the_stop_of_eth_s1[close_fill]` |
| R15-1 view() raises on an unrepresentable price (reverts the fix) | killed | `RISK15_position_stays_queryable_when_the_liquidation_price_is_off_the_grid` |
| R15-2 fallback liquidation price 0: the trigger can never fire | killed | `RISK15_position_stays_queryable_when_the_liquidation_price_is_off_the_grid` |
| R15-3 fallback on the wrong side | killed | `RISK15_position_stays_queryable_when_the_liquidation_price_is_off_the_grid` |
| R15-4 fallback leverage wrong | killed | `RISK15_the_fallback_view_keeps_the_positions_leverage_and_it_still_liquidates_at_its_bankruptcy` |
| a1 settlement price 0 accepted | killed | `hole_a_on_delist_refuses_a_settlement_price_that_is_not_a_positive_finite_price[ze` |
| a2 NaN / Inf accepted (is_finite dropped) | killed | `hole_a_on_delist_refuses_a_settlement_price_that_is_not_a_positive_finite_price[na` |
| a3 negative and zero accepted | killed | `hole_a_on_delist_refuses_a_settlement_price_that_is_not_a_positive_finite_price[ze` |
| a4 no validation at all | killed | `hole_a_on_delist_refuses_a_settlement_price_that_is_not_a_positive_finite_price[ze` |
| a5 validation inside the fail-closed method (latches the broker) | killed | `hole_a_on_delist_refuses_a_settlement_price_that_is_not_a_positive_finite_price` |
| b1 cap 0.03 | killed | `hole_b_a_funding_rate_up_to_the_cap_is_accepted[0.04-291.91]` |
| b2 cap 0.05 | killed | `hole_b_a_funding_rate_beyond_the_cap_is_not_a_rate_alerted_and_retried[0.0401]` |
| b3 cap exclusive | killed | `hole_b_a_funding_rate_up_to_the_cap_is_accepted[0.04-291.91]` |
| b4 negative rates unbounded | killed | `hole_b_a_funding_rate_beyond_the_cap_is_not_a_rate_alerted_and_retried[-0.0401]` |
| b5 positive rates unbounded | killed | `hole_b_a_funding_rate_beyond_the_cap_is_not_a_rate_alerted_and_retried[0.0401]` |
| b6 cap doubled | killed | `hole_b_a_funding_rate_beyond_the_cap_is_not_a_rate_alerted_and_retried[0.0401]` |
| b7 cap removed | killed | `hole_b_a_funding_rate_beyond_the_cap_is_not_a_rate_alerted_and_retried[0.0401]` |
| c1 an unrepresentable entry is accepted | killed | `hole_c_an_add_is_rejected_when_a_meta_refresh_lowers_max_leverage_below_the_positi` |
| c2 the check uses the order's leverage | killed | `hole_c_an_add_is_rejected_when_a_meta_refresh_lowers_max_leverage_below_the_positi` |
| c3 wrong reject reason | killed | `hole_c_an_add_is_rejected_when_a_meta_refresh_lowers_max_leverage_below_the_positi` |
| c4 rejected as a cancel: no reject event | killed | `hole_c_an_add_is_rejected_when_a_meta_refresh_lowers_max_leverage_below_the_positi` |
| d1 an ADD does not refresh max_leverage | killed | `hole_d_an_add_refreshes_the_positions_max_leverage_and_sz_decimals_and_a_later_exi` |
| d2 an ADD does not refresh sz_decimals | killed | `hole_d_an_add_refreshes_the_positions_max_leverage_and_sz_decimals_and_a_later_exi` |
| d3 stored rules set on OPEN only | killed | `hole_d_an_add_refreshes_the_positions_max_leverage_and_sz_decimals_and_a_later_exi` |
| d4 exits use meta instead of the stored rules | killed | `hole_d_an_add_refreshes_the_positions_max_leverage_and_sz_decimals_and_a_later_exi` |
| e1 duplicate stop id not checked | killed | `hole_e_a_stop_with_a_used_client_order_id_is_refused_duplicate_client_order_id` |
| g1 digest precision 60 | killed | `hole_g_120_significant_digits_can_be_digested_and_verified` |
| g2 digest precision 119 | killed | `hole_g_120_significant_digits_can_be_digested_and_verified` |
| g3 digest precision 125 (121 digits accepted) | killed | `hole_g_more_than_120_significant_digits_cannot_be_approved_and_verify_is_false[ord` |
| g4 Inexact not trapped (silent rounding) | killed | `hole_g_more_than_120_significant_digits_cannot_be_approved_and_verify_is_false[ord` |
| g5 no normalisation (1.0 != 1.00) | killed | `hole_g_equal_values_with_different_trailing_zeros_share_one_digest[1.0-1.00]` |
| g6 plus() instead of normalize (1.0 != 1.00) | killed | `hole_g_equal_values_with_different_trailing_zeros_share_one_digest[1.0-1.00]` |
| h1 an attempt dropped before its window closed | killed | `hole_h_the_result_does_not_depend_on_the_advance_cadence[stale_first_window_then_u` |
| h2 the next attempt ignores the book-age window | killed | `hole_h_a_retry_interval_longer_than_the_book_age_window_single_call[exactly_at_the` |
| h3 the window end is exclusive | killed (hang) | `an infinite loop in the exit retry (attempt never advances): every cadence test reaches it and ` |
| h4 the window is one ms too wide | killed | `hole_h_a_retry_interval_longer_than_the_book_age_window_single_call[one_ms_past_th` |
| h5 the attempt grid uses the book age instead of the retry interval | killed | `hole_h_a_retry_interval_longer_than_the_book_age_window_single_call[stale_first_wi` |
| h6 the skip of closed attempts uses the book age as the step | killed | `hole_h_the_result_does_not_depend_on_the_advance_cadence[stale_first_window_then_u` |

Mutant h3 turns the retry loop into an infinite loop, so the tests do not fail: they hang. It is "killed" by a timeout, which a CI timeout also gives.

### Existing tests that would break under a literal Amendment 10 (found with the reference fix; now updated, see the next section)

Running the whole existing suite against the reference fix, 61 existing tests in `tests/paper` fail (the reference is a literal reading of the amendment). Two causes:
- **About 38 tests send a mark or a delisting stamped more than 5 s ahead of the last `advance_to`** (typically `D0 + 30_000` after the broker was advanced to `D0 + 1000`), so the broker now ignores them. Files: `test_delisting.py`, `test_fees.py`, `test_liquidation.py`, `test_paper_only.py`, `test_stops.py`, `test_r2_liquidation.py`, `test_r2_admission.py`, `test_r2_meta_and_failures.py`. Changing `Env.mark` in `tests/paper/helpers.py` to call `broker.advance_to(time_ms)` before `on_mark` fixes 38 of them (my new tests do not use `Env.mark` for bogus marks, so they are unaffected). (Measured: with that one helper change, 23 of the 61 still fail.) The delisting tests call `on_delist` directly and need an `advance` before it.
- **The rest (the 23 that remain after the helper change) are the direct delistings above, plus tests that count the alert or the fill from the clamped time**, which Amendment 10 says never: `test_rejects.py` (2), `test_r2_stale_and_opposite.py` (5), `test_r2_meta_and_failures.py`, `test_r2_admission.py`.

The developer's round therefore has to be followed by a mechanical update of these tests (the CTO should authorise it). The amendment's intent (a bogus stamp never moves time) is what the new tests pin.

### Mechanical update of the pre-round-3 tests for Amendment 10 (done; no assertion or expected value changed)

Result: all 618 tests in `tests/paper` (the original 155, round 2's 321 and round 3's) pass against the reference fix of Amendments 8 to 10; on the current code (d0c7d2e behaviour) the full suite is 3699 passed and exactly the same 44 round-3 intentional tests fail (identical list before and after the edit). ruff, ruff format and mypy are clean. `src` is untouched.

Edited files and the mechanical change:
- `tests/paper/helpers.py`: `Env.mark` now calls `broker.advance_to(clock time)` before `on_mark` (the supervisor advances broker time every loop), keeping the returned events unchanged. This fixed 38 of the 61.
- `test_delisting.py` (7 sites), `test_fees.py` (1), `test_r2_admission.py` (1 delist): an `e.advance(<delist time>)` line before each direct `on_delist`.
- `test_paper_only.py`, `test_r2_admission.py` (2 tests), `test_r2_meta_and_failures.py` (the book-port test), `test_rejects.py` (`_close_without_book`): an `e.advance(<exit decided_at_ms>)` before the exit is submitted, so the exit's decision time is not ahead of broker time.
- `test_r2_meta_and_failures.py` scripted latch session: one extra `advance_to(D0 + 10_000)` step before the exit submit (the write count stays 10, so the fail_at range is unchanged).
- `test_r2_stale_and_opposite.py` (5 tests): the exits there carry an old decision time, so per Amendment 10 the `exit_unfilled` alert event (timed from that decision) may now precede the fill; the events are filtered to drop `exit_unfilled_alert` before the unchanged `== ["fill"]` and fill-time/price assertions.

### What round 3 deliberately does not cover

Restart state, late funding, margin, RISK-16, RISK-18, RISK-20 (per the brief). The behaviour of the broker before its first `advance_to`, the alert kind name for bad data, whether the fallback liquidation price is rounded, and whether a bogus exit is refused or clamped (any of the three outcomes above passes). The F21 contract (`advance_to` on every loop with the F1 clock) is a wiring test for F21, not testable here.
