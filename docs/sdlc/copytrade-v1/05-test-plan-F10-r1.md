# F10 review round 1: test plan for the blocking batch B1-B8

Branch `feat/copytrade-v1/F10-risk`. Source: `reviews/F10-r1-summary.md` (authoritative). Paper only. All tests use the real
gate, the real `PaperBroker`, real `GateAuthority` and the real F2 ledger; only true boundaries are faked (exchange time,
meta, books, returns) plus the not-yet-built F12 (share book, account view) and F8 (calendar). Failures are injected at the OS
boundary (`os.write` raising `OSError(EIO)` for one ledger record kind), never by replacing the Ledger.

No file under `src/` was touched. The only change to an existing file is an additive, defaulted `marked: bool = False`
parameter on `tests/risk/helpers.py::build_risk_env` (see "Existing tests that contradict a required behaviour").

## Pinned contracts (what the developer builds; the tests enforce exactly these)

### F11 (small read-only additions; tests in `tests/paper/test_r1_queries.py`)
* `PaperBroker.pending_entries() -> tuple[PendingEntry, ...]`: every accepted, unresolved OPEN/ADD order, in acceptance
  order. `PendingEntry` (frozen dataclass): `client_order_id, coin, side ("buy"/"sell"), action (OPEN/ADD), qty (positive,
  lot-rounded, still to fill), decision_px, leverage (int), share_id, trade_id, decided_at_ms`. Never lists exits or stops or
  refused orders. Leaves the list on fill, `no_book`, `no_depth`, delisting, or any other reject. A snapshot (tuple). Moves
  nothing, writes nothing, stays usable like `position()` (query, not `@_fail_closed`).
* `PaperBroker.positions() -> tuple[PositionView, ...]`: all open merged positions sorted by coin; each equals `position(coin)`.
* `PositionView.share_qtys: tuple[Qty, ...] = ()` (new last, defaulted field): absolute open quantity of each share in
  `share_ids` order. Needed so `/flatten` can close a broker share the share book does not list.
  (The stub was NOT written: the brief said not to edit `src/`, so these tests fail with `AttributeError`.)

### F10 gate
| Topic | Pin |
|---|---|
| Check order for an entry | `duplicate_order` first, then (after the snapshot) `opposite_side_entry`, `entry_in_flight`, `position_mismatch`, then position count, rate, sizing, caps, leverage. |
| B1 in-flight reason | `entry_in_flight`: any entry (OPEN or ADD, any share) on a coin that has a pending entry. Applies to `check` and `submit`. The other option (inherit the pending entry's leverage) was NOT chosen. |
| B1 opposite vs pending | `opposite_side_entry` (direction check sees pending entries too), refused before any token and before the broker. |
| B1 counting | A pending entry counts (as if filled) in: free equity (margin = qty x decision_px / leverage), open-position count, symbol/leader/total/BTC-bucket risk (the open risk the gate approved for it: `Decision.initial_risk_usd`, leader of that request), notional. Released when `pending_entries()` no longer lists it; once the share book lists the filled share it is counted only through the book (never twice). The gate keeps its own record (by client order id) of leader/risk/stop for what it sent; `pending_entries()` supplies what is still in flight. |
| B2 mismatch | `position_mismatch` when the broker position on the entry coin holds a share id the share book does not list on that coin AND it is not an entry fill produced by this submit's own `advance_to`. A booked share the broker does not hold is NOT a mismatch (book overstates risk; round-0 tests rely on it). Free equity = equity - margin of ALL `positions()`. |
| B2 own-advance fills | "Handled", not refused: the fill's share is known to the gate (risk, margin, position count keep counting until the book lists it); the second entry on that coin is decided normally at the position's leverage. (Refusing would break the round-0 test `test_F10_F11_contract_the_gate_advances_the_broker_to_exchange_time_before_every_submit`.) |
| B3 | ADD sized, capped, share-capped and risk-recorded at `current_stop_px`: `initial_risk_usd = qty x abs(decision_px - current_stop_px)`; independent of the add's own (tighter) `stop_px`. `stop_widening` unchanged. |
| B4 reasons | `equity_mark_stale`: before the first accepted mark, and when `decision now - last accepted mark's now_ms > 2 x eval.mark_interval_s x 1000` (exactly 2x = fresh, +1 ms = stale; `eval.mark_interval_s` is a fixed 60 in the compiled ceilings, so 120 000 ms). The check comes AFTER the equity read (an unknown equity is still `equity_unknown`). Exits and stops never refused for it. |
| B4 future marks | `mark_equity(now_ms)` reads the exchange clock itself; `now_ms > exchange_now + filter.max_signal_age_ms` (same tolerance as F11, 500..5000 ms, fixture 5000) is ignored: no state change, nothing saved, not a mark, never raises. Exactly at the tolerance is accepted. A failed/unknown-equity mark is not a mark. A past-stamped mark never makes a fresh gate stale (last-mark is a max). |
| B5 | Each share's `open_risk_usd` floored at 0 in every cap sum (symbol, leader, total, BTC bucket, and the share cap's `share_used_usd` on an ADD). |
| B6 flatten | (1) `pause()` persisted FIRST (survives a failing first close); (2) closes every share of every `positions()` entry using `share_qtys` (book not needed, works when `open_shares()` raises), reason `flatten`, qty = broker qty; (3) return value stays a `Sequence[Outcome]` but is a tuple subclass `FlattenReport` with `.in_flight` = `pending_entries()` after the closes (existing tests: `len`, iteration, `list(...) == []` keep working); (4) an entry in flight is blocked by the pause; once it fills, `flatten(run_id=<new>)` closes it (idempotency per `run_id` unchanged). An automatic close-on-fill hook is NOT pinned: it needs a supervisor (F21) that re-runs flatten while `in_flight` is non-empty. |
| B7 | For `close=True`, qty (and the book-quantity check) is netted with the fills of THIS submit's `advance_to` for that `(coin, share_id)`: entry fills add, exit fills subtract; the intent and `Decision.qty` carry the netted qty. No fills in the submit: unchanged (`exceeds_share` for qty above the book stays). |
| B8 | Already-true behaviour; pins M12, M23, M24, M33 (verified below). |

## Coverage matrix: finding -> tests

| Finding | Tests (file: name suffix) |
|---|---|
| F11 queries | `tests/paper/test_r1_queries.py` (21): `B1_pending_entries_*` (empty; fields; lot-rounded qty; short=sell; ADD listed; acceptance order; refused never listed; exits and stops never listed; leaves list on fill / `no_book` window (5000 exactly still pending, +1 gone) / delisting / `no_depth`; snapshot; query moves nothing), `B2_positions_*` (empty; sorted by coin and equals `position()`; closed leaves; `share_qtys` order / short positive / partial close / not reported before fill) |
| B1 | `tests/risk/test_r1_inflight.py` (18): five simultaneous opens on one coin send one; different coins never exceed equity (sequential free-equity invariant + broker margin); pending margin not free and released on expiry (`no_book`); pending counts as open position; leader cap; total cap; BTC-bucket cap; partly-sized pending counts at approved risk; `entry_in_flight` for OPEN, ADD/ADD, OPEN-vs-ADD; opposite side vs pending before the broker; `check` path; rejected frees the coin; filled carried by the book and not counted twice (2 tests); N coins x position limit (3, 5) |
| B2 | `tests/risk/test_r1_book_mismatch_and_risk.py`: `B2_*` (30 tests total in the file): hidden broker share refuses OPEN / ADD; ghost booked share is not a mismatch; matching ids fine; other coin fine; opposite side refusal first; unlisted position margin counts (leverage >= 3 at free 40; `insufficient_margin` at free 0); own-advance fills handled (leverage kept; symbol cap; position count; margin of the fill) |
| B3 | same file: `B3_*`: qty 0.50 and `initial_risk_usd` 1.00 for add stops 98 / 99 / 99.5 / 99.9 / 99.99 (current stop 98); share risk after add <= cap and the token intent carries that qty; widening still refused; liquidation rule at the current stop (`add_leverage_unsafe`) |
| B4 | `tests/risk/test_r1_marks.py` (22): before first mark (check, submit, add); first mark opens; unknown / raising equity is not a mark; `equity_unknown` precedes stale; boundary 0 / 119 999 / 120 000 fresh, 120 001 / 1 200 000 stale; no token or broker when stale; fresh mark revives; failed marks do not refresh; exits and stops never refused; future-mark tolerance 0 / 4 999 / 5 000 accepted, 5 001 / +1 day ignored; tolerance is `filter.max_signal_age_ms` (2000 override); future mark does not clear a daily halt or roll the day (persisted bytes unchanged), week, or a drawdown pause; past marks harmless; ignored future mark does not refresh |
| B5 | same file as B3: `B5_*`: total cap (-5, -1000, -0.01 equal 0 equal none), leader, symbol, BTC bucket, ADD share cap, zero-risk unchanged |
| B6 | `tests/risk/test_r1_flatten_and_close.py`: `B6_*`: pause first (failing first close), paused + persisted + entries refused, nothing open still pauses, hidden shares (two on one coin, a hidden short, a booked one), book unreadable, idempotent per run, `.in_flight` reported, next flatten closes the filled entry |
| B7 | same file: `B7_*`: ADD fills before the CLOSE (1.5 closed); TP partial fill before the CLOSE (0.5 closed, no `exceeds_position`); no fills unchanged; above-share with no fills still `exceeds_share`; another share's fill ignored |
| B8 | `tests/risk/test_r1_audit_and_exits.py` (10): M12 (2 tests + window expiry), M23 (exit and close), M24 (entry, add; exit still sent at audit failure), M33 (exit propagates; entry `broker_failed`) |

## Run summary (current code, `uv run pytest -q`)
* New tests: **114** (tests/paper 21, tests/risk 93). Failing on purpose: **82**. Passing on purpose: **32** (guards and B8).
* Failure reasons of the 82: 22 `AttributeError` for the not-yet-existing API (21 query tests: `pending_entries`,
  `positions`; 1 `.in_flight` on the flatten result), 1 `RuntimeError: share book down` (flatten reads the book; B6), and 59
  assertion failures on behaviour (wrong approve/reason/qty/leverage, state changed by a future mark, margin over equity).
  No import, fixture or collection errors.
* Guards that pass now and must keep passing (they pin non-regression, not new behaviour): B1 rejected-frees-coin,
  B1 filled-carried-by-book x2; B2 matching ids, other-coin mismatch, ghost booked share, opposite-side-first, own-advance
  fill handled; B3 `stop_px == current_stop_px`, widening refused, liquidation at the current stop; B4 `equity_unknown`
  precedence, exits/stops never refused, future mark within tolerance accepted (3 params), past marks harmless, drawdown pause
  not cleared by a future mark; B5 zero risk; B6 none; B7 no-fills unchanged, above-share `exceeds_share`, other share ignored;
  all 10 B8 tests.
* B8 checked against its mutants in a scratch copy (not in the repo): M12 (exits not counted), M23 (exit dedup removed), M24
  (audit failure no longer refuses an entry), M33 (exit advance failure refused instead of propagated): each mutant makes
  at least one B8 test fail; the unmutated code passes all 10.
* Existing suite: 4 449 existing + 32 new guards pass (4 481), nothing existing fails on the current code
  (full run: all failures are in the 82 new tests).

## Existing tests edited (CTO authorisation: direct consequences of B1 and B4; none weakened)
Checked by running the whole round-0 risk suite (382 tests) against a scratch prototype of the pinned rules (stale mark
after 120 000 ms, future-mark ignore beyond 5 000 ms, `entry_in_flight`, `position_mismatch`): all 382 pass. On today's code
they all pass too.

| Test / helper | Change | Why | Intent kept |
|---|---|---|---|
| `tests/risk/helpers.py::build_risk_env` | `marked` default flipped to `True`: takes one equity mark at `T0` after building the gate | B4: an entry needs a fresh mark; round-0 tests never marked | yes, only adds the precondition |
| `tests/risk/helpers.py::rebuild_gate` | new `marked=True` parameter: the restarted gate takes a mark at the current exchange time | a restarted gate has no mark (B4) | yes |
| `test_dev_extras.py::test_F10_AC7_a_non_finite_equity_is_unknown_equity[x3]` | `new_risk(marked=False)` | the test asserts the persisted state equals a gate that never marked | assertion unchanged |
| `test_dev_extras.py::test_F10_AC7_coin_rules_are_fetched_once_per_refresh_interval_and_a_failed_refresh_refuses_entries` | two `mark_equity(r.xtime.now)` calls after the clock jumps | the clock jumps 60 min, past the 2 x 60 s mark age | all fetch-count and refusal assertions unchanged |
| `test_limits.py::test_F10_AC5_the_daily_halt_holds_until_the_next_00_00_utc_even_if_equity_recovers` | one mark at `M0 + DAY - 60 000` before the boundary checks | entries need a fresh mark; the mark is before the boundary so the halt still ends by time, not by a mark | assertions unchanged |
| `test_limits.py::test_F10_AC5_the_weekly_halt_lasts_until_the_next_monday_00_00_utc` | one mark at `M0 + WEEK - 60 000` | same | assertions unchanged |
| `test_limits.py::test_F10_AC5_drawdown_writes_an_event_alerts_persists_across_restart_and_resume_clears_it` | `r.at(now + 60 000)` before the "further mark" (a mark stamped 60 s ahead of exchange time would be ignored as a future mark, making the assertion vacuous); the third restart uses `rebuild_gate(r2, marked=False)` | B4 future-mark rule; a mark at the still-breached equity correctly re-pauses | assertions unchanged |
| `test_gate_sizing.py::test_F10_AC3_orders_per_minute_cap_uses_a_sliding_window_in_exchange_time` | orders go to SOL, ETH, DOGE (was three on SOL) | B1: an entry in flight blocks its coin | same window boundaries: 59 999 ms blocked, 60 000 ms free; limit 2 |
| `test_gate_sizing.py::test_F10_AC3_orders_per_minute_default_is_30` | `equity="3000"`, each of 30 SOL orders on its own leader is filled and listed in the share book before the next (2 s apart), 31st checked at +59 s | B1 counts in-flight risk and blocks the coin; `risk.max_open_positions` is capped at 10 by the compiled ceilings, so 30 coins is impossible | 30 accepted, the 31st `rate_limit` |

## Spec ambiguities resolved here (PO/architect may overrule)
* In-flight same coin: refuse (`entry_in_flight`) rather than inherit leverage.
* `flatten` auto-close of entries that fill later: not built into the gate; the report exposes `.in_flight`, the next
  `flatten(run_id=...)` closes them. F21 (supervisor) must re-run it while `in_flight` is non-empty: follow-up.
* The "non-latching audit error" half of M24 cannot be produced at the OS boundary (every `os.write`/`fsync` failure latches
  the ledger), so the exit test asserts the exit is not blocked by the audit failure (token issued, broker reached).
* `posted_margin_usd` on a decision is the coin's existing margin, not the order's margin (0 for an OPEN on a fresh coin);
  tests use `final_notional_usd / leverage` for an order's margin.
* `mark_equity` when the clock is unsynced: not pinned (either ignoring the mark or using the last exchange time passes).

## What these suites deliberately do not cover
* Pure-maths properties of sizing/caps stay in the round-0 suites. Crash-restart with entries in flight (the new gate has no
  reservations; the broker's own pending list is empty after a restart too) belongs to R0 reload / F13 and to QA.
* Real exchange behaviour of in-flight orders and partial fills (F11 is a simulator: replay and simulation gates).
* Mutation re-run and independent verification: senior-dev and reviewer-risk (round 2).
