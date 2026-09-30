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
