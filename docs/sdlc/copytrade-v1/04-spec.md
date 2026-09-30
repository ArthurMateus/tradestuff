# Spec: copytrade-v1 (AI-filtered copy-trading bot, Hyperliquid + Telegram, paper)

Author: pm (SPEC mode) · Date: 2026-09-29 · Status: draft for /tests, Amendments 1 to 11 applied

## Amendment 11 (2026-09-30, architect ruling on the F11 deadlock; supersedes Amendment 10's rule; PO informed, no PO decision needed)

Source: reviewer-risk RISK-21 and RISK-22 (both upheld by the architect): Amendment 10's "ignore a mark whose timestamp is too far ahead, and let marks nudge broker time" rule (a) switches stops, liquidations and one-shot delistings off for good when the supervisor's clock and the exchange clock differ by more than the tolerance, and (b) lets a chain of plausible marks walk broker time forward without limit. Rule: **clamp, never ignore; broker time is only what `advance_to` says.**
- **F11 broker time** is set only by `advance_to`, as `_now_ms = max(_now_ms, t)`. Marks (`on_mark`) and delistings (`on_delist`) never move it and never call `_run_until`. All times are exchange milliseconds.
- Marks and delistings are always processed at broker time: a stop that triggers is decided at `min(mark.time_ms, _now_ms)` and fills at `_now_ms + ack_delay`; a liquidation or delisting is stamped `_now_ms`. Nothing is dropped. The `paper_stop_trigger` ledger row keeps the raw mark time.
- An exit's `decided_at_ms` is clamped to `min(decided_at_ms, _now_ms)`; the alert clock uses that decision time, the fill is `max(decided, now) + ack`.
- The once-per-(source, coin) `bad_timestamp` alert (now worded "clamped") fires only when a timestamp is more than `filter.max_signal_age_ms` ahead of broker time; it is suppressed while broker time is 0 and cleared when a non-ahead timestamp arrives. No new config key.
- **RISK-23:** an entry whose `decided_at_ms` is more than `filter.max_signal_age_ms` ahead of broker time (broker time > 0) is refused `bad_decision_time`.
- **Time-base contract:** F21 owns it: the supervisor calls `advance_to(ClockSync.exchange_now().ms)`, does not advance while the clock is unsynced, calls `advance_to` before feeding marks or delistings each loop, and a heartbeat detects a stalled loop (a stalled `advance_to` means triggered exits queue and never fill: F21 must alert). F10 stamps `decided_at_ms` in the same exchange base. F16 replay drives `advance_to(t)` before `on_mark(t)`. F11 cannot detect skew; it enforces monotonic time, clamped external timestamps, nothing dropped. F21 wiring test: the 24 h dry run shows zero `bad_timestamp` alerts.
- Status: RISK-17, 19, 21, 22, 23, 25 closed by this rule; RISK-24 (ledger record of clamps) stays logged.

## Amendment 10 (SUPERSEDED by Amendment 11; 2026-09-30, CTO default from the F11 verify round; PO to confirm)

Source: reviewer-risk RISK-17 (blocking, reproduced: one BTC mark stamped one hour ahead froze every stop and every close on every coin, and a stop-loss loss of about 5.5 USD became a full-margin liquidation of 20.08 USD).
- **F11 time is never moved by one bad timestamp.** An external timestamp (a mark, a delist, an exit's `decided_at_ms`) more than `filter.max_signal_age_ms` (existing key, ceiling 5,000 ms; no new config key) ahead of the broker's trusted time is treated as bad data: it is ignored with an error log and the alert path, it never advances broker time, and it never delays an exit or a stop. The broker's trusted time is the time given to `advance_to` by its caller (F21 supervisor, from the F1 clock); marks may advance it only within that tolerance. A mark or time that is merely late never blocks an exit.
- **The `exit_unfilled` alert** is timed from the exit's own decision time (the intent's `decided_at_ms`, or the mark's own time for a stop trigger), never from a clamped or advanced time (spec: one alert after `exits.alert_after_s`).
- **F21 contract:** the supervisor must call `advance_to` with the F1 clock time on every loop, and F10 must stamp `decided_at_ms` in the same time base (RISK-18).
- Logged, not fixed now: RISK-16 (stranded dust after an szDecimals cut), RISK-19 (far-future exit `decided_at_ms`, covered by the rule above), RISK-20 (maximum meta age for entries), RISK-8/10/11/12 as before.

## Amendment 9 (2026-09-30, PO decision)

- **F11.AC5 liquidation (PO approved reading B, replaces the Amendment 7 reading):** when a position is liquidated, the paper broker closes it at the bankruptcy price (entry x (1 -/+ 1/L)), so the whole posted margin is lost, plus the taker fee. Loss = posted margin + fee. The liquidation trigger price is unchanged (entry x (1 -/+ (1/L - 1/(2 x maxLev)))). Reason: real liquidations gap and fill worse than a clean close, so the conservative loss avoids flattering the paper verdict. Amendment 8's open item RISK-9 is closed.

## Amendment 8 (2026-09-30, CTO defaults from the F11 review round 1; PO to confirm)

Source: reviewer-risk RISK-1..6 (confirmed by scripts against the real broker) and senior-dev round 1.
- **F11 stale decisions:** the broker never fills at a book earlier than its own time. An OPEN/ADD with `decided_at_ms` before the broker's current time is refused `stale_decision`. An exit (CLOSE/REDUCE/stop) with an old `decided_at_ms` is never refused: its fill time is clamped to at least the broker's current time.
- **F11 flip semantics:** a flip is CLOSE, then OPEN after the close fills. An OPEN/ADD on the opposite side of an existing position on the coin is refused `opposite_side_entry`; an entry never reduces a position.
- **F11 exits and stops never depend on meta:** they use the rules stored on the position, so a meta refresh that drops the coin cannot block an exit (F10.AC7, §5).
- **F11 gate token:** the intent digest is canonicalised under a fixed explicit Decimal context, so a value issued in F10's default context verifies in the broker's context.
- **F11 funding:** each funding hour settles on its own; a missing hour never blocks later hours (alerted once per stretch, `funding_missing`).
- **F11 non-money dependencies:** alert-sink and read-only port failures (any `Exception`) are logged and treated as no data or retry; only ledger and state errors latch the broker.
- **F11 exit retry** is independent of the `advance_to` cadence: only attempts whose book-age window has closed are dropped.
- **Open, PO decision before run 1 (RISK-9):** Amendment 7's liquidation reading (close at the liquidation price) understates the loss by the maintenance margin (2.5% of notional for SOL, 5% DOGE). Reviewer-risk recommends the conservative reading: the full posted margin is lost (close at the bankruptcy price) plus the fee.
- **Logged for later features:** RISK-8 (restart state is in memory only: F21 must not wire the broker before F13; pending exits need reconstruction or new IDs), RISK-10 (late funding is not in the trade P&L: F18 must add `paper_funding` by `share_id`, or F11 writes a `trade_funding_adjustment`), RISK-11 (F10 static check covers `.issue(` call sites; consider a verify-only broker interface and a 32-byte minimum key), RISK-12 (oversized CLOSE refused, F12 contract), RISK-13 (retire by share_id and coin), RISK-14 (settlement_px > 0, funding-rate bound, funding-hour mapping pinned by F21), RISK-15 (unguarded `Position.view()`).

## Amendment 7 (2026-09-30, CTO defaults from the F11 test plan, PO to confirm)

F11 (`05-test-plan-F11.md`, 16 pinned ambiguities) stands on the safest reading until the PO decides:
- **F11.AC5 liquidation:** the position closes at the liquidation price and the loss is the price move plus fees, bounded by the margin. It is not the full margin (maintenance margin is half the max-leverage initial margin). **PO to confirm; if the PO wants the full margin lost, AC5 changes.**
- Entries cancel the remainder of a partial fill; exits re-queue and retry every `exits.retry_interval_s`. A zero-depth or one-sided book rejects opens (`no_depth`) and retries exits. Delisting settlement pays the taker fee. Funding: positive rate means longs pay; strict open < boundary < close; missing funding is retried and alerted once (`funding_missing`).
- Gate token: `GateAuthority` issues a single-use `GateToken` bound to the exact intent (F10 builds against this).

## Amendment 6 (2026-09-30, CTO default, PO to confirm)

- **F4.AC7 compression:** the stdlib `lzma` codec replaces zstd/columnar for v1, so the project adds **no new dependency** (Python 3.11 has no zstd; supply-chain risk). The ≤ 25% size ratio, the stream and transport sha256 and the segment chain are unchanged. Swap to zstd later only with a PO-approved dependency.
- **Open PO decision:** F7's real `latency measure` run and F21 need a concrete WebSocket connector. Stdlib has none, so this needs a dependency (for example `websockets`) or a hand-written RFC 6455 client. Not added yet.

## Amendment 5 (2026-09-29, PO)

- **F1.AC5:** the secret-key check `(?i)(token|secret|api_key|pin)` exempts keys whose §3 type is a number or a timing (`telegram.pin_max_attempts`, `telegram.pin_lockout_min`, `hl.ws_ping_interval_s`, `llm.price_usd_per_1k_tokens.*`) and the fixed boolean `eval.run_worktree_pinned`. **Calendar windows:** the §3.5 defaults "−30 / +60" (`calendar.window_fomc_min`) and "−15 / +30" (`calendar.window_tier1_min`) are written as non-negative before/after minutes, 30 / 60 and 15 / 30, since Min is 0. The nine env var names are fixed in the F1 table below. F1 also ships the project tooling (uv, pytest, ruff, type check); mutation testing runs only on the money-path modules (risk, paper, positions, evaluation, baselines).

## Amendment 4 (2026-09-29)

**Source.** Edge-hypothesis Addendum A4 (`research/edge-hypothesis.md` §5.13, marks `(A4.1)`–`(A4.12)`) and `research/scripts/eval_reference.py` v4 (E16), now committed. A4 is normative and supersedes A3 where they differ. It settles four open points from Amendment 2: §11 A20 (a) and (b), F9.AC8 against A3.3, and A25. Amendment 3 (F22 dropped) stands.

**Changed ACs** (the old text is replaced in place):

| AC | Change | A4 item |
|---|---|---|
| §1 missed exit | "Handled" defined: a mirror action, a rule-based skip record, or the share's full close, within 60 s (a skip recorded later is missed). Class 2 includes a data-gap exit not handled within 60 s after resync; class 3 includes exits found by the fill audit. Settled-gap rule | A4.1, A4.5 |
| §1 major/alt | An untiered coin is a major for B0d, B0, B0b, B1 and B3, and an alt for paper trades, replays, reconstruction and shadows | A4.7 |
| F4.AC7 | Stream and transport sha256 per file; a segment record every 5 min with a chain hash; unhashed data is a gap | A4.8 a, b |
| F9.AC8 | Tier table recomputed every 24 h during a run, ledgered, in force from its ledger time; the table at `t0` goes in the run record | A4.7 |
| F12.AC5 | Each pass fetches leader fills since the last pass and compares sizes; any mismatch runs the detector | A4.1 |
| F12.AC6 | Missed-exit definition per A4.1 and A4.5; alert and record fields (how found) | A4.1, A4.5 |
| F12.AC7 | `/flatten` shadows use lo candle prices inside a gap | A4.2 |
| F12.AC9 | Candle fill rule; uncomputable after 72 h = cost > 1R, lo = actual, exit = real close (replaces "no verdict while pending"); incremental and trade costs; actual R definition | A4.2, A4.3 |
| F14.AC6, F14.AC9 | Run-result content before `T_eval` only in `/stats` and each trade's own post; operational content allowed, never with a pass/fail label | A4.11 |
| F16.AC6 | Untiered coin = alt for paper trades, replays, reconstruction and shadows | A4.7 |
| F17.AC1, F17.AC4 | The table at `t0` is stored; only a table the rule does not reproduce is ABORTED | A4.7 |
| F18.AC1 | The oracle is E16 with the `GOLDEN_A4_*` vectors and 31 mutants | A4.12 |
| F18.AC3, F18.AC11 | The verdict waits for the final fill audit and for recomputation from verified data, bounded at 72 h | A4.1, A4.8 c |
| F18.AC6 | ABORTED wins only when strictly earlier; a tie goes to FAIL | A4.4 |
| F18.AC7 | Breach time rules; breach found after `T_eval` is still FAIL | A4.4 |
| F19.AC2, F19.AC4 | Discretionary pauses are not excluded from B0d draws (B̄ = max rule); non-discretionary downtime stays excluded; the 24 h test excludes all downtime; untiered = major | A4.6, A4.7 |
| F20.AC1 | Report adds how each missed exit was found, incremental cost, uncomputable mirrors, breach time and when found, audit coverage per leader, settled-gap exits, candle-priced fills; untiered rule for B1 and B3 | A4.1–A4.5, A4.7 |
| F23.AC1, F23.AC3 | Both hashes verified; reads try local, then every ledgered destination, newest first | A4.8 |
| F23.AC5 | A destination change is ledgered; it is not a config change or a deploy | A4.8 d |
| DoD item 11 | Needs the PO's re-acknowledgement of §14 items 9 and 10 as rewritten by A4.9 | A4.9 |

**Added ACs:**

| AC | Content | A4 item |
|---|---|---|
| F4.AC9 | Hourly candle store (1m and 1h) for every coin with an open share, shadow or mirror, hashed like recordings | A4.2 |
| F12.AC10 | Leader-fill audit: every 24 h, a final one up to `T_eval`, 72 h bound, audits continue after `T_eval` | A4.1 |

**Other sections changed:**
- §3: new frozen keys `eval.fill_audit_interval_h`, `eval.missing_data_retry_max_h`, `recording.segment_hash_minutes`, `eval.missed_exit_cost_rule`, `eval.p4_breach_time`, `eval.settled_gap_rule`, `baseline.dm_discretionary_pause_rule` and `recording.candle_store`; updated `eval.missed_exit_gap_rule`, `cost.fallback_tier_rule`, `eval.recording_integrity`, `baseline.dm_exclude_downtime`, and the wording of `tiers.recompute_interval_h`
- §4: the fill-audit and candle-store budgets
- §5: the "cost can't be computed" row becomes F2 after 72 h; new "incomplete fill audit" row; tier and destination rows
- §7: mappings
- §9: DoD items 3 and 11
- §10: ownership of the new ACs
- §11: A20 is replaced by A4.2, A25 is confirmed, A26 added

**Feature count:** unchanged, 23 (F22 is out of scope by Amendment 3).

---

## Amendment 3 (2026-09-29, CTO, on PO decision)
- **F22 (OKX recorder) is removed from this epic** and moved to out-of-scope. The PO chose to cut cost (`decisions.md`, 2026-09-29). F22's ACs, config keys and ownership rows below are void for this epic. DoD item 1 is read as covering F1–F21 and F23.
- **Run 2 is refused while any run-1 missed exit has no resolution record** (F17.AC9) is confirmed as the PO's decision. It resolves open point 5 of Amendment 2.

## Amendment 2 (2026-09-29)

**Source.** Edge-hypothesis Addendum A3 (`research/edge-hypothesis.md` §5.12, marks `(A3.n)`, tests 21–24) and `research/scripts/eval_reference.py` v3 (E15), both now committed. A3 is normative. This amendment aligns the spec with A3 and ends the "provisional" status that Amendment 1 gave F12.AC6, F12.AC9, F14.AC6, F14.AC9, F18.AC7 and F18.AC11. /tests takes their vectors from A3 tests 21–24 and from the E15 golden literals quoted in the ACs below.

**Changed ACs** (the old text is replaced in place):

| AC | Change | A3 item |
|---|---|---|
| F4.AC7 | Compression is lossless (the records are byte-identical); each finished file's sha256 is ledgered when the file is closed | A3.4 |
| F12.AC6 | For the missed-exit definition, downtime means only `process_down` and a `data_gap` before resync, so a late mirror during an entry pause is a missed exit; the count covers all trades; the ME blocker also applies after `T_eval` and in FAIL or ABORTED runs; detection never pauses entries | A3.1 |
| F12.AC9 | The mirror is built with the `/flatten` shadow machinery from the first missed event; each action is decided at the leader time + `copyreplay.delay_ms` and filled at the book + `paper.ack_delay_ms`; ambiguous gap bars resolve stop-first (lo, used for the gate) and TP-first (hi, used for the cost); cost per trade = hi − actual, stored once the trade and its mirror have both closed (or marked at `T_eval`); "uncomputable counts as > 1R" is replaced by "no verdict while a cost is pending" | A3.1 |
| F13.AC1 | Fallback costs are major or alt by `cost.fallback_tier_rule` (copy side) | A3.3 |
| F14.AC6 | The forbidden list is now exactly edge-hypothesis §5.5 (adding standard errors, p-values, B0d replications, D_i, K9/S4, P6, G and the cross-day diagnostics); logs are covered; the allowed list includes the operational counters, with no pass/fail label | A3.2 |
| F14.AC9 | `/stats` matches §5.5: the "descriptive, not the verdict" label on average R, drawdown as the P3 quantity, and the operational counters (downtime used against 2%, missed exits with their costs, pending deploy rulings) | A3.2 |
| F16.AC6 | Fallback costs by `cost.fallback_tier_rule`; an untiered coin is an alt for copies | A3.3 |
| F17.AC2 | `run start` also refuses unless the recorder and archive processes run the run commit from the run worktree, and refuses run 2 while a run-1 missed exit is unresolved (F17.AC9) | A3.4, A3.1 |
| F17.AC3 | Deploy checks cover the recorder and archive processes; a deploy whose stated reason is an interim result can only be ruled ABORTED | A3.2 c, A3.4 |
| F18.AC1 | The oracle is `eval_reference.py` v3 (E15): it adds `GOLDEN_MISSED`, `GOLDEN_MISSED_CLOSE` and 16 mutants | A3.6 |
| F18.AC3 | A missed-exit trade's evaluation close is the later of its real (or shadow) close and its mirror exit; open mirrors are marked; the verdict waits for `T_eval` + 60 s and a reconciliation pass | A3.1 |
| F18.AC4 | Day-cluster intervals also use the mirror exit | A3.1 |
| F18.AC6 | The F2 input to the grid is `p4_breach`; the E15 verdict cases are added | A3.1 |
| F18.AC7 | The F1 shadow curve includes the stop-first mirrors; F2 fires at the 4th ledgered missed exit, or when a trade and its mirror have both closed with a cost > 1R, or at `T_eval` with the open sides marked; the F2 alert states K13 | A3.1 |
| F18.AC9 | A flattened trade with a missed exit uses the minimum of three R values | A3.1 |
| F18.AC10 | The refused list is exactly §5.5; instrumented functions prove nothing is computed before `T_eval` | A3.2 |
| F18.AC11 | Rewritten to A3.1: counting window and population, per-trade cost from the TP-first mirror, F2 timing, verdict timing, the E15 vectors and mutants M11–M16 | A3.1 |
| F19.AC2 | No B0d start time inside recorded P5 downtime, `/pause` included | A3.2 b |
| F19.AC4 | The relaxed set also excludes downtime; its fallback half-spread uses `cost.fallback_tier_rule` (untiered = major for B0d) | A3.2 b, A3.3 |
| F20.AC1 | Missed-exit section: every missed exit in and after the window, mirrored lo and hi R, and the total change in ΣR over S | A3.1 |
| F20.AC4 | ME blocker wording, including missed exits after `T_eval` and in FAIL or ABORTED runs; a FAIL by F2 is headed with K13 | A3.1 |
| F23.AC1 | Verification is a read-back compared with the ledger sha256; a store-side checksum alone is not enough | A3.4 |
| F23.AC2 | The delete primitive itself refuses any file without a verified upload | A3.4 |
| F23.AC3 | Every read verifies the ledger sha256; a file with no matching copy is lost and becomes a recording gap (this replaces the `archive_corrupt` batch failure) | A3.4 |

**Added ACs:**

| AC | Content | A3 item |
|---|---|---|
| F4.AC8 | Component-start record (commit, dirty flag, worktree, lockfile, packages) for the recorder and archive processes | A3.4 |
| F17.AC9 | Run 2 can't start while a missed exit from run 1 has no resolution record (K13; Assumption A24) | A3.1 |

**Other sections changed:**
- header and inputs
- §1: outcomes, and the definitions of tiers (majors and alts), missed exit and the missed-exit rule
- §3: `exits.missed_exit_max_lag_s` is now fixed at 60 and FROZEN; `eval.show_interim_stats` becomes an enum; five FROZEN keys are added; the fallback-cost rows point to `cost.fallback_tier_rule`
- §4: missed-exit cost latency; read verification in the batch budgets
- §5: missed-exit rows, a pending missed-exit cost, a lost recording file, and the deploy and worktree rows
- §7: mappings
- §9: DoD items 3, 10 and 11
- §10: the A3 gating note, collision rule 7, and F19 reads
- §11: A4, A14, A16, A17 and A20 rewritten; A24 and A25 added

**Config keys added (§3.9, all FROZEN through A3):** `eval.missed_exit_gate_rule`, `eval.missed_exit_gap_rule`, `baseline.dm_exclude_downtime`, `cost.fallback_tier_rule` and `eval.recording_integrity`.

**Config keys changed:** `exits.missed_exit_max_lag_s` (fixed at 60, FROZEN) and `eval.show_interim_stats` (bool → enum `descriptive_only`).

**Feature count:** unchanged, 23.

---

## Amendment 1 (2026-09-29)

**Source.** The six "Spec review" decisions dated 2026-09-29 in `docs/product/decisions.md`: A2 (leverage), A4 (missed exits), A6 (coin tiers), A9 (news source), A10 (storage) and A14 (`/stats`). The same entries accept every other §11 assumption as a default, and §11 records that.

**Dependency on edge-hypothesis A3.** The quant-researcher is writing the pre-registration Addendum A3 in `research/edge-hypothesis.md` in parallel. A3 is **normative** for the missed-exit rule (gate R, USD P&L and the FAIL thresholds) and for what may be shown during a run. Where this spec paraphrases A3, A3 wins. Until A3 is committed, these ACs are provisional, and /tests takes their exact vectors from A3: F12.AC6, F12.AC9, F14.AC6, F14.AC9, F18.AC7 and F18.AC11. **(Resolved by Amendment 2: A3 is committed and these ACs are aligned with it.)**

**Changed ACs** (the old text is replaced in place):

| AC | Change | Decision |
|---|---|---|
| F1.AC2 | Required ceiling cases now cover the new leverage keys, the high-leverage coin list and the liquidation-multiple floor | A2 |
| F1.AC5 | Storage credentials and the backup encryption key join the env-only secrets and the canary test | A10 |
| F1.AC7 | The manifest also never lists `storage.cache_dir` | A10 |
| F4.AC1 | The recording universe always includes SOL | A2, A6 |
| F4.AC2 | Leaderboard snapshots are never deleted **from the archive**; local copies are pruned like recordings | A10 |
| F4.AC5 | Disk guard: alert threshold, then a hard floor that stops recording safely; exits are never blocked | A10 |
| F4.AC6 | Recording continues in every trading state, except below the disk floor | A10 |
| F9.AC1 | Slippage and spread thresholds apply by liquidity tier, not by a majors list | A6 |
| F10.AC4 | Leverage is the lowest value that fits the margin, up to the ceilings (5x alts; 10x BTC, ETH and SOL), subject to the liquidation-distance rule | A2 |
| F12.AC6 | A missed exit alerts with a running count and is a go-live blocker; it no longer fails the run by itself | A4 |
| F14.AC4 | `/stats` is added to the command table; `/status` shows free disk, archive state and projected storage cost | A14, A10 |
| F14.AC6 | The visibility lock now allows the `/stats` figures and forbids the gate CI, P2c, FR checks and any verdict preview | A14 |
| F14.AC7 | Daily and weekly reports add missed exits, coin-tier changes, archive state and projected storage cost | A4, A6, A10 |
| F17.AC1 | The run record stores the frozen coin-tier table and its sha256 | A6 |
| F17.AC2 | `run start` also refuses on a missing or stale tier table, or an unhealthy archive | A6, A10 |
| F17.AC4 | A tier table differing from the run record is treated as a config change | A6 |
| F18.AC6 | The F2 input to the precedence grid is now the output of F18.AC11 | A4 |
| F18.AC7 | Immediate FAIL by F2 follows the A3 thresholds, not "any missed exit" | A4 |
| F18.AC10 | The API also refuses D, B0d, P2c, FR and per-condition results before `T_eval`; `/stats` never uses it | A14 |
| F20.AC1 | The report lists every missed exit with its actual, mirrored and gate R and its cost | A4 |
| F20.AC4 | Any missed exit also blocks a PASS from going live | A4 |
| F20.AC5 | The readiness report adds the tier table and archive health | A6, A10 |
| F21.AC2 | The 24h dry run also checks compressed recording size and one verified archive day | A10 |

**Added ACs:**

| AC | Content | Decision |
|---|---|---|
| F4.AC7 | Compressed, day-partitioned, atomically written recordings | A10 |
| F9.AC7 | Coin tiers assigned automatically from measured liquidity | A6 |
| F9.AC8 | Tier recompute schedule, freeze at run start, meme-perp fixtures | A6 |
| F10.AC10 | Property tests for automatic leverage | A2 |
| F12.AC9 | Mirrored counterfactual and cost of each missed exit | A4 |
| F14.AC9 | `/stats` content and labelling | A14 |
| F18.AC11 | Missed-exit rule: count and cost thresholds, gate R | A4 |
| F23.AC1–AC7 | **New feature F23**: archive, cloud offload, pruning, transparent reads, ledger backup, credentials, budget | A10 |

**Other sections changed:** §1 (definitions of tiers and the missed-exit rule, outcomes), §3 (new, renamed and removed keys), §4 (storage and cost budgets), §5 (disk, archive, missed-exit, tier and leverage rows), §7 (mappings), §8 (J7 Tracker), §9 (DoD items 1, 5, 7, 11 and new 13), §10 (F23 wave and ownership, tier and leverage ownership), §11 (A2, A4, A6, A9, A10, A14 rewritten; A17–A23 added; acceptance status recorded).

**Config keys removed or renamed:** `markets.majors` (removed; tiers replace it), `risk.leverage_default` (removed; replaced by `risk.leverage_min`), `risk.max_leverage_btc_eth` → `risk.max_leverage_high_tier`, `filter.max_slippage_pct_major`/`_alt` → `_tier1`/`_tier2`, `filter.max_spread_pct_major`/`_alt` → `_tier1`/`_tier2`, `recording.disk_pause_free_gb` → `recording.disk_floor_free_gb`.

**Config keys added:**
- **Leverage (§3.6):** `risk.leverage_min`, `risk.max_leverage_high_tier`, `risk.high_leverage_coins`. The floor of `risk.min_liq_distance_stop_mult` is raised from 2 to 3.
- **Tiers (§3.5):** `tiers.lookback_days`, `tiers.recompute_interval_h`, `tiers.max_age_h`, `tiers.depth_band_pct`, `tiers.tier1_min_depth_usd`, `tiers.tier1_min_volume_usd`, `tiers.floor_min_depth_usd`, `tiers.floor_min_volume_usd`, `tiers.min_coverage_fraction`, and the renamed `filter.max_slippage_pct_tier1/2` and `filter.max_spread_pct_tier1/2`.
- **Recorder (§3.3):** `recording.disk_check_interval_s`, `recording.disk_floor_free_gb`, `recording.disk_resume_margin_gb`, `recording.max_gb_per_day`.
- **Storage (§3.1):** `storage.cache_dir`, `storage.upload_delay_min`, `storage.upload_deadline_h`, `storage.local_retention_days`, `storage.max_unarchived_days`, `storage.cache_max_gb`, `storage.read_retry_max_min`, `storage.retry_interval_min`, `storage.alert_interval_h`, `storage.ledger_backup_time_utc`, `storage.monthly_budget_usd`, `storage.budget_alert_fraction`, `storage.price_usd_per_gb_month`, `storage.price_usd_per_10k_ops`.
- **Evaluation (§3.9, FROZEN via edge-hypothesis A3):** `eval.missed_exit_max_count` (3), `eval.missed_exit_max_cost_r` (1.0). The meaning of `eval.show_interim_stats` is narrowed to gate statistics.
- **New config flag:** VAL-R, meaning "validate against our recordings before freezing".

**Feature count:** 23 (F1–F23).

---

**Inputs.**
- `01-brief.md`, `02-discovery.md` and `03-answers.md`.
- `research/edge-hypothesis.md` (frozen v2 + A1 to A4) and `research/scripts/eval_reference.py` v4 (E16, which supersedes E15).
- `research/backtest-audit-r3.md` (VALID), `research/run-register.md`, `research/market-context.md` and `research/brainstorm-domain-research.md`.
- `docs/product/decisions.md` and `.claude/knowledge/trading-invariants.md`.

**Precedence.**
- Where `01-brief.md` conflicts with a later decision in `decisions.md`, the later decision wins:
  - risk per trade is 0.5%, not 1%
  - we follow at most 9 wallets, not 5–10 with a maximum of 10
  - the CI level is 96% for run 1 and 99% for run 2, not 95%
  - leverage is chosen automatically up to 5x alts and 10x BTC, ETH and SOL (Spec review A2), not a 3x default with a BTC/ETH-only 10x tier (D3)
  - liquid Hyperliquid meme perps are tradable when they qualify by liquidity tier (Spec review A6); D4's deferral now covers on-chain memecoins only
- `edge-hypothesis.md` §5 (the frozen pre-registration) and its addenda, including A3 and A4, are **normative** for everything under evaluation. Where this spec paraphrases it, the frozen text wins.
- `research/scripts/eval_reference.py` v4 (E16, which keeps every E15 literal) is the **conformance oracle**. If it disagrees with the frozen text, the frozen text wins and the oracle is a bug.

**Notation.**
- ACs are written `Fn.ACm [tag]`. The tag is one of `unit`, `integration`, `qa-ui` or `simulation`. `simulation` means the AC is run in paper mode or replay against recorded data.
- "Equity" is marked-to-market paper equity in USD.
- "Share" means one trader share, as defined in §1.
- All times are UTC epoch milliseconds, unless a time zone is named.

---

## 1. Problem and goals

**Problem.** Naive copy trading loses money:
- leaders are often lucky
- copy delay, fees and spread eat the edge
- leverage liquidates followers
- leaderboards reward survivorship

The PO wants to know, **honestly and cheaply**, whether automatically copying evidence-selected Hyperliquid traders is profitable after real costs. The PO wants this known before any real money or subscriber is involved.

**What the PO wants (intent):**
1. A bot that finds and keeps re-checking a small set (at most 9) of Hyperliquid wallets with evidence of real, copyable skill. It swaps in better ones as they appear.
2. The bot copies those wallets' moves automatically into a **$300 paper wallet at real mainnet prices**. It mirrors opens, adds, partial exits and full exits, with deterministic filters and hard risk caps that always win.
3. It reports every trade in a private Telegram chat, and the PO keeps full control through a small set of authenticated commands.
4. After a paper run judged once on its first 300 opened trades, it gives a verdict computed exactly as pre-registered: `PASS`, `FAIL`, `INCONCLUSIVE` or `ABORTED`. That verdict must be one the PO can trust not to be fooled by luck, beta, costs, survivorship or optional stopping.

**User-visible outcomes:**
- From day 1, the PO's PC records the market data and leaderboard snapshots needed for honest, point-in-time replays. Recordings are compressed, each finished UTC day is archived to cheap object storage and verified, and only a rolling window stays on the PC's ~100 GB of free disk. Storage costs ≤ $5/month.
- The full pipeline runs unattended on the PO's Windows PC in paper mode. It survives restarts without leaving a position open, and without faking results.
- During a run the PO sees trades, positions and USD P&L. `/stats` shows descriptive figures (P&L, win rate, average R, drawdown, per-trader stats and progress to 300) and operational counters (downtime used against the 2% budget, missed exits with their costs, and pending deploy rulings).
- Before `T_eval`, the PO never sees, and the system never computes, any of these (edge-hypothesis §5.5, A3.2): the gate CI by any method, B0d, D, P2c, FR1–FR6, K9/S4, P6, G, the cross-day diagnostics, or any verdict preview.
- **Run-result content** (A4.11) is any figure computed from the outcomes (R, USD P&L, exit prices, exit reasons) of our trades, shadows, mirrors or any baseline. Before `T_eval` it appears only in the `/stats` list and in each trade's own post. Operational content (mode, health, disk, archive, storage cost, followed wallets with score and rank, counts of signals, entries, exits, refusals and skipped mirrors by reason, set and tier changes, latency, and the operational counters) may appear in `/status`, `/traders`, alerts and reports, never with a pass/fail label.
- At `T_eval` a report states the verdict, every gate value and every go-live blocker.
- The epic's deliverable is a **run-1-ready system** (see §9). The paper run itself, and its verdict, happen after this epic ships and are tracked in the run register.

**Definitions** (binding for every AC):
- **Trade / share:** one copied position per leader, from our entry fill to fully closed, including adds and partials. Only taken signals count.
- **Merged position:** every open share on one coin in one direction.
- **R:** `net_pnl_usd / initial_risk_usd`, where `initial_risk_usd = qty_at_entry × |entry_fill_px − initial_stop_px| + estimated exit fee` (edge-hypothesis §4).
- **Liquidity tier:** each allowed core coin is assigned automatically, from measured liquidity in our own recordings (F9.AC7), to **tier 1** (most liquid), **tier 2**, or **below floor** (not tradable). There is no hand-written coin list for tiers. The tier table at `t0` is stored in the run record. During a run the table is recomputed every 24 h under the frozen rule and thresholds, ledgered, and in force from its ledger time (F9.AC8, A4.7).
- **Major / alt** (edge-hypothesis §6.3, A3.3; `cost.fallback_tier_rule`). This applies wherever the edge-hypothesis or this spec says "major" or "alt", which is the fallback costs in F13, F16, F19 and §3.
  - A **major** is a coin in the tightest liquidity tier (tier 1) in the tier assignment in force at the decision time of the trade or replication, read from the ledger's tier records (F9.AC7, F9.AC8).
  - Every other tier, below floor included, is an **alt**.
  - A coin with **no tier record** at that time (A4.7) is an **alt for paper trades, replays, restart reconstruction and shadows**, and a **major for B0d, B0, B0b, B1 and B3**. Each choice is the conservative side. Missed-exit mirrors and gap fills use the fixed candle constants of F12.AC9 (8 bps lo, 2 bps hi), not the tier rule.
  - The leverage list `risk.high_leverage_coins` is unrelated to majors.
- **High-leverage coins:** the coins in `risk.high_leverage_coins` (BTC, ETH and SOL), which may use up to 10x. This list is about leverage only and is independent of the liquidity tiers.
- **Missed exit** (edge-hypothesis §5.3 "Missed-exit rules", A3.1): a leader exit event (a close, a reduce or a flip) on a coin where we hold that leader's open share, which is one of:
  1. **Late:** the event's exchange timestamp is outside position downtime, and it is not **handled** within `exits.missed_exit_max_lag_s` (60 s, FROZEN) of it.
  2. **Reconstruction failed:** the event is inside position downtime and was not settled. In a `process_down` interval, that means the restart reconstruction (F13) did not settle it. In a `data_gap` before resync, it means it was not handled within 60 s after the resync (A4.5).
  3. **Orphan:** it is found only by leader reconciliation (F12.AC5) or by the leader-fill audit (F12.AC10), and it was not handled within 60 s of its exchange timestamp, outside position downtime.

  **Handled** (A4.1) means that within 60 s the ledger holds a mirror action for the event, a rule-based skip record for it, or the full close of our share for any reason (our SL/TP included). A skip recorded later than 60 s is missed. A leader exit that our own SL/TP closes more than 60 s later is missed.

  **Settled gap** (A4.5, `eval.settled_gap_rule`): an exit inside a data gap that is handled within 60 s of the resync is not a missed exit and does not count toward P4. Its trade still gets a mirror from that event on and gate R = min(actual, mirrored lo), like a missed-exit trade, with the later evaluation close. It has no cost test.

  **Position downtime**, for this definition only, means the ledgered `process_down` intervals plus the `data_gap` intervals before resync: the times the engine could not manage positions.
  - Entry pauses keep exits managed, so a late mirror during one of them **is** a missed exit. The entry pauses are `/pause`, `access_degraded`, `disk_low`, deploy-wait pauses, loss halts and blackouts.
  - P5 downtime (F18.AC8) is wider: it also includes the entry pauses.

  Rule-based non-mirrors are not missed exits: a partial skipped below $10, or a share already closed by our own SL/TP (Assumption A4). Each ledgered `missed_exit` record is one missed exit, and one share can have more than one.
- **Missed-exit rule** (edge-hypothesis A3.1 is normative; this is a paraphrase):
  - **Mirror.** Each share with a missed exit gets one mirror, built like the `/flatten` shadow. From its first missed leader event on, that event and every later leader event on the share are mirrored on time (F12.AC9). Over a recording gap, an ambiguous bar is resolved stop-first for the **mirrored lo R** and TP-first for the **mirrored hi R**, and fills use the candle rule (F12.AC9).
  - **Gate.** A trade in S with a missed exit counts at **min(actual R, mirrored lo R)**, or at the minimum of realised, shadow and mirrored lo R if it was also flattened. Its USD P&L follows the same choice. A bug can therefore never help the verdict.
  - **Evaluation close.** It is the later of the real close (the shadow exit if flattened) and the mirror exit.
  - **Cost** (A4.3): per missed exit and per trade, mirrored hi R rounded half-even to 1e-6. The incremental cost of missed exit j is hi R(M_j) − hi R(M_(j−1)), with hi R(M_0) = actual R; the trade cost is hi R(M_k) − actual R. Actual R is the realised R (the flatten price for a flattened trade, the marked value if still open).
  - **F2.** The run FAILs if any of these holds (F18.AC11):
    - more than 3 (`eval.missed_exit_max_count`) missed exits have their leader event in `[t0, T_eval]`. They are counted over all trades: in S or not, including trades opened after the 300th and missed exits during entry pauses.
    - any such incremental cost or trade cost is > 1R (`eval.missed_exit_max_cost_r`)
    - a mirror is uncomputable after 72 h (cost counts as > 1R), or a leader-fill audit stretch is still incomplete after 72 h (F12.AC9, F12.AC10)

    One to three missed exits that each cost ≤ 1R leave the run running, and PASS stays possible.
  - **ME and K13.**
    - Every missed exit alerts at once (F12.AC6).
    - Every missed exit is go-live blocker **ME** until it is explained and fixed (F20.AC4), whatever the verdict. That includes missed exits after `T_eval` and in a run that ended FAIL or ABORTED.
    - A FAIL by F2 is an engineering failure, not evidence about the edge (**K13**). Run 2 can't start until every missed exit of run 1 has a recorded resolution (F17.AC9).

---

## 2. Features and acceptance criteria

### F1 Platform core (config, ceilings, mode, money, secrets, clock, engine path set)
- **Value:** every other feature gets validated configuration, paper-only operation, exact money arithmetic and secret hygiene. Without it, nothing else is safe to build.
- **Dependencies:** none. F1 also scaffolds the project, the lockfile and the package layout used by the §10 ownership map.

- **F1.AC1 [unit]**
  - *Given* a config tree under `config/` where any key in §3 is missing, has the wrong type, or has a value outside [Min, Max],
  - *when* the engine starts,
  - *then* it exits non-zero with an error naming the key, and it opens no network connection.
  - The engine has **no code defaults**: every §3 key must be present in the config files.
- **F1.AC2 [unit]** Hard ceilings are constants in code and can't be raised by config.
  - *Given* each §3 key with a Max: a value equal to Max loads, and a value one step above it is rejected.
  - Required cases: `risk.per_trade_fraction` = 0.0101, `risk.max_leverage_alt` = 6, `risk.max_leverage_high_tier` = 11, `select.max_followed` = 10, `filter.max_signal_age_ms` = 5001 are each rejected.
  - `risk.high_leverage_coins` accepts any subset of {BTC, ETH, SOL}, and a list containing any other coin (for example DOGE) is rejected.
  - Floors work the same way: `cost.taker_fee_bps` = 4.4, `risk.min_liq_distance_stop_mult` = 2.9, `recording.disk_floor_free_gb` = 4 and `tiers.floor_min_depth_usd` = 19,999 are each rejected.
- **F1.AC3 [integration]** Paper only.
  - *Given* no `mode` key value other than `paper`: `mode` = `live` or `testnet` makes startup fail with `mode not permitted in this build`.
  - *Given* any test run, with a network stub that fails the test on any request to the Hyperliquid `/exchange` endpoint: 0 such requests are made.
  - No module imports an order-signing client, which a static test checks.
- **F1.AC4 [unit]** Money is Decimal.
  - Constructing a price, quantity, notional, fee, funding or P&L value from a binary float raises.
  - Price rounding follows the exchange rule: ≤ 5 significant figures, ≤ (6 − `szDecimals`) decimals, and integers are always allowed.
  - Size rounds **down** to `szDecimals`.
  - Vectors: (67123.45, sz 5) → 67123; (0.01234567, sz 0) → 0.012346; size 0.123456 at sz 3 → 0.123.
- **F1.AC5 [unit]** Secrets come only from environment variables: the Telegram token, the PIN hash and salt, the LLM key, the object-storage endpoint, bucket, key ID and secret key, and the ledger-backup encryption key.
  - *Given* canary secret values injected for the whole test suite: 0 occurrences appear in logs, ledger records, Telegram payloads, LLM prompts or exception traces.
  - A config file that contains a key matching `(?i)(token|secret|api_key|pin)` with a non-empty value fails to load, unless the key is a §3 number or timing key (Amendment 5).
  - **Env var names (Amendment 5):**

    | Secret | Variable |
    |---|---|
    | Telegram token | `COPYTRADE_TELEGRAM_TOKEN` |
    | Telegram PIN hash | `COPYTRADE_TELEGRAM_PIN_HASH` |
    | Telegram PIN salt | `COPYTRADE_TELEGRAM_PIN_SALT` |
    | LLM key | `COPYTRADE_LLM_API_KEY` |
    | Storage endpoint | `COPYTRADE_STORAGE_ENDPOINT` |
    | Storage bucket | `COPYTRADE_STORAGE_BUCKET` |
    | Storage key ID | `COPYTRADE_STORAGE_KEY_ID` |
    | Storage secret key | `COPYTRADE_STORAGE_SECRET_KEY` |
    | Ledger-backup encryption key | `COPYTRADE_BACKUP_ENCRYPTION_KEY` |
- **F1.AC6 [unit]** Every timestamp is UTC epoch ms and carries a source tag: `exchange`, `local` or `derived`.
  - The clock offset is re-estimated every `clock.offset_interval_s`.
  - *Given* offset uncertainty above `clock.max_offset_uncertainty_ms`, or no estimate for more than `clock.max_estimate_age_s`, *then*:
    - opens and adds are refused with reason `clock_unsynced` within 1 s
    - one alert is sent
    - exits continue
- **F1.AC7 [integration]** The engine path set.
  - The committed manifest `engine-path-set.txt` lists: `src/copytrade/**`, the lockfile, the project metadata file, `config/**`, `data/inputs/**` and itself.
  - It never lists `docs/**`, `research/**`, `tests/**`, `storage.ledger_dir`, `storage.recordings_dir` or `storage.cache_dir`. A test enforces this.
  - At startup, the engine fails closed and names the file if any imported engine module, or any file opened as config or data input, is outside the manifest.

### F2 Append-only ledger and audit trail
- **Value:** a single, tamper-evident source for every decision, fill, run record and statistic. It gives honest numbers (B5, D4) and tax export (E5).
- **Dependencies:** F1.

- **F2.AC1 [unit]** Tamper evidence.
  - Records carry a strictly increasing sequence number and a hash chain, `h_n = sha256(h_{n−1} ‖ canonical_bytes(record_n))`.
  - The API offers no update or delete.
  - *Given* any single byte of a stored record is altered, *when* the ledger is verified (at startup and via CLI), *then*:
    - verification fails at that sequence number
    - the engine refuses to start
    - an alert is written to the local log
- **F2.AC2 [unit]** One decision record per signal (B5). It holds:
  - the signal id, leader, coin, event type
  - the exchange timestamp, local receive timestamp and clock offset
  - each filter rule's input value, threshold and result, and each risk check's result
  - the mirror, risk-cap and final sizes, and the price used
  - the latency per stage (§4)
  - the outcome: `taken`, `rejected:<reason>`, `unexecutable`, `conflict`, `duplicate`, `out_of_scope` or `pre_existing`

  A fixture of 50 signals yields exactly 50 decision records, with no required field null.
- **F2.AC3 [integration]** Crash durability.
  - *Given* the process is force-killed at 100 random points during a replay of 1,000 signals, *when* it restarts, *then*:
    - the ledger verifies
    - there are 0 partial records
    - each client order ID appears at most once
- **F2.AC4 [unit]** Fill export.
  - `export fills --from --to` writes CSV with one row per paper fill: ISO-8601 UTC time, coin, side, qty, price, fee, funding, client order ID, trade ID, share ID and exit reason.
  - The row count equals the number of fill records, and Decimal strings round-trip exactly.
- **F2.AC5 [unit]** Honest aggregates. No aggregate API has a parameter that excludes records by outcome or flag.
  - *Given* a fixture that includes losers and trades flagged `reconstructed`, `unreconstructable`, `delisted_force_settle`, `liquidated`, `marked` and `manual_flatten`, *then* the aggregate USD P&L and trade count equal the hand-computed totals over all of them.
- **F2.AC6 [unit]** A ledger append that fails (I/O error, disk full) raises to the caller. The engine then enters the fail-closed state in §5 and never continues silently.

### F3 Hyperliquid client (REST, WebSocket, rate budget, access detection)
- **Value:** reliable, rate-safe access to public Hyperliquid data, with gap detection. This is the basis for every signal and every price.
- **Dependencies:** F1 and F2.

- **F3.AC1 [unit]** Rate budget.
  - Weights: 20 per info request; 2 for `l2Book`, `allMids` and `clearinghouseState`; +1 per 20 items for fills and funding, and +1 per 60 for candles. `userRole` and `portfolio` take `hl.weight_userRole` and `hl.weight_portfolio`.
  - *Given* those weights, then over a 2-hour simulated load:
    - every sliding 60 s window stays ≤ `hl.rest_weight_budget_per_min`
    - scoring traffic stays ≤ `hl.scoring_weight_share` of the budget
    - reconciliation and exit-related requests are always served before scoring requests
- **F3.AC2 [unit]** HTTP 429 and timeouts.
  - Every REST call has a `hl.rest_timeout_s` timeout.
  - A 429 or a timeout backs off exponentially with jitter, from `hl.backoff_base_s` to `hl.backoff_max_s`, for at most `hl.retry_max` retries.
  - A test with a server that always returns 429 observes ≤ `hl.retry_max` + 1 requests per call and ≤ 1 request/s to that endpoint.
- **F3.AC3 [integration]** WebSocket limits and heartbeat.
  - Subscribing a user beyond `hl.ws_max_unique_users` distinct users is refused locally and never sent.
  - New connections stay ≤ `hl.ws_max_new_conns_per_min`.
  - When a connection gets no message or pong for `feed.stale_after_s`, *then*:
    - it is marked stale
    - opens and adds for the wallets it serves are refused with `feed_stale`
    - it reconnects with jittered backoff of 1 s up to `hl.ws_reconnect_backoff_max_s`
- **F3.AC4 [integration]** Gap resync.
  - *Given* a disconnect of N seconds, *when* the feed reconnects, *then*, before any new decision for an affected wallet:
    - fills in `[last seen exchange ts, now]` are fetched with `userFillsByTime` and merged by `tid`, with 0 duplicates
    - the gap is written to the ledger as `data_gap` downtime
  - *Given* a snapshot message (`isSnapshot: true`), it is deduplicated the same way.
- **F3.AC5 [unit]** Access degraded (K10).
  - *Given* either of these within `access.degraded_window_min`:
    - at least `access.degraded_error_count` responses with HTTP 403 or 451, or a region-block body
    - a REST success rate below `access.degraded_min_success_rate`

    *then* all of the following happen:
    - the state becomes `access_degraded`
    - opens and adds are refused
    - one alert is sent within 60 s
    - exits, reconciliation and recording keep retrying
    - the time counts as downtime
  - The state clears after `access.recover_min` consecutive minutes with a success rate of at least 95%.
- **F3.AC6 [unit]** Schema validation (failure case).
  - A response that is missing a field or has a wrong type is rejected as a whole and never partially used.
  - At least 3 schema failures in 10 minutes on one endpoint raise one alert.

### F4 Market-data recorder and leaderboard snapshots
- **Value:** point-in-time data from day 1. It is the only source for honest replay, B0d, reconstruction and HIP-3 research [PO].
- **Dependencies:** F2 and F3.

- **F4.AC1 [integration]** Coverage.
  - The recording universe:
    - every core perp traded in the last `recording.universe_lookback_days` by any followed or top-`scoring.candidates_k` wallet
    - plus BTC, ETH and SOL
    - plus all HIP-3 markets (recorded, never traded)
    - capped at `recording.max_coins`, by 24h volume
  - For each coin, these are recorded:
    - L2 book, top `recording.l2_levels` levels, at least every `recording.l2_interval_ms`
    - `allMids` updates
    - mark, oracle, funding and OI every `recording.asset_ctx_interval_s`
    - hourly funding history
  - Over a 1-hour run against a stub feed, the gap between consecutive L2 snapshots is ≤ 5 s in ≥ 99.9% of intervals, for every coin.
- **F4.AC2 [integration]** Leaderboard snapshots.
  - The full leaderboard JSON is stored every `recording.leaderboard_interval_min` (± 5 min), compressed, with its fetch timestamp and sha256.
  - Snapshots are never deleted from the archive (F23.AC2). Local copies are pruned only under the F23.AC2 rule. Every wallet ever seen stays in the local wallet registry (D2).
  - A failed fetch is retried 3 times within the hour, then recorded as `missing` with one alert.
- **F4.AC3 [unit]** Point-in-time reads.
  - Every record stores the exchange timestamp (where one exists) and the local receive timestamp.
  - `as_of(t)` returns no record received after `t`. The test inserts future records and asserts they are excluded.
- **F4.AC4 [unit]** Gap statistics.
  - `recorder gaps --from --to` reports, per coin:
    - the share of time with no L2 snapshot within 5 s
    - the share of time with a mid or mark gap over 60 s
  - On a 1-hour fixture with one injected 10-minute gap, the reported share is 16.7% ± 0.1%.
- **F4.AC5 [integration]** Disk guard (failure case).
  - Free space on every volume holding `storage.recordings_dir`, `storage.ledger_dir` or `storage.cache_dir` is checked every `recording.disk_check_interval_s`.
  - **Alert:** below `recording.disk_alert_free_gb`, one alert per 6 h states the free GB and the unarchived backlog (days and GB, from F23).
  - **Floor:** below `recording.disk_floor_free_gb`, within 2 check intervals:
    - the recorder flushes and closes its open files atomically (no partial file), stops writing, and sends one alert
    - opens and adds are refused with `disk_low`, and the time counts as downtime (F18.AC8)
    - exits, SL/TP, reconciliation, `/flatten`, ledger appends and archive uploads continue. A fixture at the floor shows a leader close still produces our close within the §4 exit budget.
  - Recording resumes automatically once free space is ≥ `recording.disk_floor_free_gb` + `recording.disk_resume_margin_gb`. The stopped interval is a recorder gap (F4.AC4) and is never back-filled with synthetic data.
- **F4.AC6 [simulation]** Recording is independent of trading state. With `/pause`, the kill switch, a loss halt or `access_degraded` active, snapshots continue at the configured rates. The only thing that stops recording is the disk floor (F4.AC5).
- **F4.AC7 [integration]** Compressed storage format and file hashes (edge-hypothesis §6.2 "Recording integrity", A3.4, A4.8 a and b; test 24).
  - Recordings and leaderboard snapshots are written compressed, in a columnar format with zstd or an equivalent, partitioned by UTC day (and by coin for market data).
  - **Lossless.** Decompressing any file yields records byte-identical to what the recorder serialised. A 1-hour fixture reads back exactly equal to what was written: Decimal strings, both timestamps and source tags.
  - Files are written atomically (temporary file, then rename). After a force-kill at 20 random points, every file present reads back complete, and no reader ever sees a partial file.
  - **Two hashes per file (A4.8 a).** Each file has a **stream sha256** (over the records' canonical serialised bytes, independent of the compression) and a **transport sha256** (over the stored file bytes). Both are ledgered. On a fixture, recompressing the same records with another zstd level changes the transport hash and leaves the stream hash unchanged.
  - **Segment records (A4.8 b).** Every `recording.segment_hash_minutes` (5) the recorder ledgers a segment record for each open stream: the hash of the records written in that segment, chained to the previous segment's hash. Data not covered by a ledgered hash, including the tail of a file after a crash, is a **gap** for every reader. On a fixture with a force-kill mid-segment, the unhashed tail is read as a gap and never used.
  - **Hashed at close.** When a file is closed, its stream sha256, transport sha256, byte count and record count are ledgered as `recording_file_closed` with its path, before any reader can see the file. This applies to every kind of close: normal, day end, disk floor or shutdown. On a 1-day fixture there is exactly one such record per file, and each record matches its file's sha256.
  - On a representative 1-hour fixture of 250 coins, the compressed bytes are ≤ 25% of the same data as uncompressed JSON lines.
  - A finished UTC day's files are closed and marked `day_complete` within `storage.upload_delay_min` after 00:00 UTC, so F23 can archive them.
- **F4.AC8 [integration]** Component version record (edge-hypothesis A3.4: the recorder is engine code).
  - Every start of the recording process, and of the archive process (F23), ledgers a `component_start` record. It holds:
    - the component name and the absolute worktree path
    - the 40-hex commit and the dirty flag over the engine path set
    - the lockfile sha256 and the Python version
    - the installed-package-list sha256, computed as in F17.AC1
  - Each of these processes writes a heartbeat with the same identity every `ledger.heartbeat_interval_s`.
  - F17.AC2 and F17.AC3 use these records to hold the recorder and the archive process to the run commit during a run.
  - Starting the recorder from two worktrees at different commits gives two records that differ exactly in commit and path.
- **F4.AC9 [integration]** Candle store (edge-hypothesis A4.2, A4.8; `recording.candle_store`; test 26).
  - Every hour during a run (and in dry-run mode), the recorder fetches the exchange 1m and 1h candles of the hour just closed for every coin on which any share, shadow or mirror was open during that hour.
  - They are stored as recording files under F4.AC7: compressed, lossless, atomic, with both hashes and segment records, each candle carrying its fetch time.
  - A candle missing from the store may be fetched later, within `eval.missing_data_retry_max_h`. It is then stored and hashed the same way, and a stored candle is never replaced.
  - Every reader that needs exchange candles (mirrors, `/flatten` shadows, B0d's relaxed set, reconstruction) reads them only through this store. A candle it needs that is not there yet is fetched and hashed first.
  - Fixture: a share open from 10:20 to 12:40 on coin X and a mirror open on coin Y from 11:00 to 11:30 give 1m and 1h candle files for X at hours 10, 11 and 12, and for Y at hour 11, each with a `recording_file_closed` record. A coin with nothing open in that hour gets none.
  - Failure case: with the candle endpoint unreachable, the fetch is retried every `storage.retry_interval_min` with one alert per `storage.alert_interval_h`, and recording of everything else continues.

### F5 Trader scoring (metrics, gates, blow-up detectors, score)
- **Value:** traders are picked on verified-fill evidence, with luck correction (C1). This is edge-hypothesis §10.1–10.5, exactly.
- **Dependencies:** F1. It uses the fills, portfolio and candle interfaces from F3 and F4, stubbed in tests.

- **F5.AC1 [unit]** Metrics.
  - M1–M19 follow the edge-hypothesis §10.2 formulas.
  - On 6 hand-computed fixture wallets, each metric matches the expected value: exactly for Decimal money fields, and to 1e-9 for ratios.
- **F5.AC2 [unit]** Round-trip reconstruction matches `research/scripts/hl_sample.py::reconstruct` on its self-test fixtures:
  - a flip splits into a close and an open
  - a position open at the first fill is ignored until flat
  - spot and `dex:`-prefixed fills are skipped
- **F5.AC3 [unit]** Gates G1–G15, at their boundaries.
  - Required examples:
    - `n_rt` = 149 is ineligible and 150 is eligible
    - `median_hold_min` = 14.99 is ineligible when p95 latency ≤ 45 s
    - `max_dd` = 0.3500 is eligible and 0.3501 is ineligible
  - A missing input, or one older than `scoring.stale_input_mult × scoring.interval_min`, makes the wallet ineligible with reason `stale_input` (fail closed).
- **F5.AC4 [unit]** BU1–BU8 fire exactly at their §10.5 thresholds, and never below their minimum samples. For example, BU1 at 9 adds never fires, and at 10 adds it fires at a share of 0.21 but not at 0.20.
- **F5.AC5 [unit]** Score properties (edge-hypothesis §10.7, tests 1–5 and 12–15).
  - Weights that don't sum to 1 (± 1e-9) fail config load.
  - `S` ∈ [0, 1], and each component is monotone.
  - A wallet's `S` is independent of other wallets and of input order.
  - Results are deterministic, including the tie-break.
  - Fills with `time > t` never change the score at `t`.
  - DSR is monotone.
  - The shrinkage keeps the sign.
  - `perpAllTime` is never interpolated.
  - Account value is taken at or before the event, never after.
- **F5.AC6 [unit]** Verified fills only (C1, abuse case). Setting the leaderboard `pnl`, `roi` and `accountValue` fields to arbitrary values leaves every metric and `S` unchanged.
- **F5.AC7 [unit]** Persistence (B5). Every cycle persists, per wallet:
  - input hashes, metrics, `u_k`, `S` and rank
  - eligibility reasons
  - `dsr_resolution`

### F6 Trader selection and follow manager
- **Value:** automatically follows the best eligible wallets, with hysteresis, within WebSocket limits [PO].
- **Dependencies:** F3, F4 and F5.

- **F6.AC1 [unit]** Hysteresis (edge-hypothesis §10.6 and §10.7 tests 6–10).
  - A wallet joins at rank ≤ `select.join_rank` for `select.join_confirm_cycles` consecutive cycles.
  - It is dropped at rank > `select.drop_rank` for `select.drop_confirm_cycles` cycles, and only once it has been followed ≥ `select.min_follow_hours`.
  - A wallet in the band `(join, drop]` keeps its status.
  - There are ≤ `select.max_swaps_per_cycle` swaps per cycle, each with `S_cand ≥ S_weakest + select.swap_margin`.
  - The followed count is always ≤ `select.max_followed` (9).
- **F6.AC2 [unit]** Safety drop, immediate.
  - Triggers: any BU flag, a G15 failure, a copy drawdown ≥ `leader_pause.max_copy_dd × risk.leader_allocation_fraction × equity`, or `leader_pause.max_consec_losses` consecutive copy losses.
  - From the next signal (within 1 s), the wallet's opens and adds are refused with `leader_paused`, whatever its follow time.
- **F6.AC3 [integration]** WebSocket slots.
  - Distinct subscribed users stay ≤ 10: followed wallets, plus dropped wallets that still have open shares, plus an incoming wallet.
  - A join or swap without a free slot is deferred and logged `no_ws_slot`.
  - A dropped wallet keeps its subscription until its last share closes, and releases it ≤ 60 s later.
- **F6.AC4 [integration]** Backfill first [PO]. No wallet is followed until the incremental backfill of all `scoring.candidates_k` candidates has completed. At default config against a rate-budget simulator, that finishes in ≤ `select.backfill_max_hours`.
- **F6.AC5 [unit]** Leaderboard outage (failure case).
  - Triggers: an HTTP error, a timeout, a schema failure, or fewer than 1,000 rows.
  - Effect: the current followed set is kept, 0 wallets are added, and one alert is sent per outage. Followed wallets keep being re-scored from fills.
- **F6.AC6 [unit]** Few eligible.
  - With fewer than `select.min_followed` eligible, all eligible wallets are followed, and the list is never padded with ineligible ones.
  - With 0 eligible, opens are refused with `no_eligible_leaders` and one alert is sent.
- **F6.AC7 [unit]** Cadence.
  - A cycle starts every `scoring.interval_min` ± 2 min.
  - A cycle that has not finished within `select.max_cycle_duration_min` keeps the previous followed set, and is logged `cycle_overrun`.

### F7 Signal detection
- **Value:** turns followed wallets' fills into typed, deduplicated, timestamped signals.
- **Dependencies:** F2 and F3.

- **F7.AC1 [unit]** Classification.
  - From `startPosition`, `sz` and `side`:
    - open: 0 → non-zero
    - add: same sign, |post| > |pre|
    - reduce: same sign, 0 < |post| < |pre|, with fraction `(|pre| − |post|) / |pre|`
    - close: post = 0
    - flip: sign change, which gives a close plus an open
  - A 30-case fixture covers each type, including aggregated fills.
- **F7.AC2 [unit]** Idempotency (A5).
  - A fill whose `tid` was already processed, whether it arrives from the WebSocket, a snapshot or a REST resync, creates no signal.
  - A 1,000-event fixture with 30% duplicates yields exactly the unique count.
- **F7.AC3 [unit]** Pre-existing positions.
  - *Given* wallet W is followed at `t_f` and holds coin X at `t_f`, according to `clearinghouseState` at follow time,
  - *then* every W fill on X is `pre_existing` (logged, not traded) until W is flat on X.
  - The next open is a normal signal.
- **F7.AC4 [unit]** Scope. These produce outcome `out_of_scope` and are never traded:
  - fills on `dex:`-prefixed (HIP-3) markets
  - spot fills
  - coins outside `markets.allowed_dexes`
- **F7.AC5 [unit]** Age.
  - Each signal carries the exchange timestamp, the local receive timestamp and `age_ms = (receive_local + offset) − exchange_ts`.
  - An `age_ms` below −`clock.max_offset_uncertainty_ms` is flagged `clock_anomaly` and refused for opens.
- **F7.AC6 [integration]** Throughput and latency mode.
  - A burst of 100 fills/s for 10 s across 9 wallets is classified with p99 receive-to-signal ≤ 50 ms, and 0 fills are dropped.
  - `latency measure --hours N --wallets <list>` records the per-signal stages S1–S2 (§4) without trading. It can run before F9–F12 exist.

### F8 Economic calendar and blackouts
- **Value:** no new exposure into scheduled macro releases [PO D10].
- **Dependencies:** F1.

- **F8.AC1 [unit]** Windows are computed in `calendar.timezone` and converted at runtime:
  - FOMC 2026-10-28 14:00 EDT → blackout 17:30–19:00 UTC
  - FOMC 2026-12-09 14:00 EST → 18:30–20:00 UTC
  - CPI 2026-10-08 08:30 EDT → 12:15–13:00 UTC
- **F8.AC2 [unit]** A blackout refuses opens and adds only, with `event_blackout`. It never blocks reduces, closes, SL/TP, `/flatten` or reconstruction.
- **F8.AC3 [unit]** Fail closed (failure case). If the calendar file is missing, fails to parse, or covers fewer than `calendar.min_coverage_days` from now, *then*:
  - opens and adds are refused with `calendar_invalid`
  - one alert is sent
  - F17 refuses to start a run
- **F8.AC4 [unit]** Events whose class is not in `calendar.blocking_classes` (PPI, GDP, retail sales, minutes) never block.
- **F8.AC5 [unit]** Blackout intervals are ledgered as `rule_blackout` and are never counted as downtime.

### F9 Filter and decision
- **Value:** deterministic yes/no per signal with a full audit trail, plus shadow outcomes so the filter's value can be measured later (H3). Coins qualify for trading, and get their thresholds, from measured liquidity, so liquid meme perps can trade and thin coins can't.
- **Dependencies:** F4, F7 and F8. Tier computation reads recordings through the store interface (F4, with F23's archive fallback when present).

- **F9.AC1 [unit]** Boundaries of the enforced rules. The first value passes, the second is refused with the reason given. Tiers come from the tier table in force (F9.AC8).

  | Rule | Passes | Refused | Reason |
  |---|---|---|---|
  | Signal age | 5,000 ms | 5,001 ms | `stale_signal` |
  | Adverse slippage vs the leader's fill price, for our expected VWAP from the book at decision, tier-1 coin | 0.300% | 0.301% | `slippage` |
  | Same, tier-2 coin | 0.800% | 0.801% | `slippage` |
  | Spread, tier-1 coin | 0.100% | 0.101% | `spread` |
  | Spread, tier-2 coin | 0.300% | 0.301% | `spread` |
  | Order share of depth within `filter.depth_band_pct` of mid | 1.00% | 1.01% | `depth` |
  | Book or mark age | 2,000 ms | 2,001 ms | `stale_price` |
  | Coin tier | tier 1 or tier 2 | below floor | `illiquid_coin` |
  | Coin present in the tier table in force | present | absent | `untiered` |

  The same tier-1 thresholds apply to a coin whatever its name: a fixture where DOGE is tier 1 applies 0.300% / 0.100% to DOGE, and one where BTC is tier 2 applies 0.800% / 0.300% to BTC.

- **F9.AC2 [unit]** Determinism and point-in-time (D1).
  - The same inputs give the same verdict.
  - Adding data received after the decision timestamp doesn't change it.
- **F9.AC3 [unit]** Conflicts.
  - An open on coin X in direction d, while any of our open shares on X has direction −d, is refused with `conflict`.
  - The same direction is accepted as a new share of the merged position, subject to F10 caps.
- **F9.AC4 [unit]** Volatility regime.
  - Realised volatility is the standard deviation of 1h log returns over the last `filter.vol_window_h`.
  - When its percentile against a trailing `filter.vol_lookback_days` of 1h candles is ≥ `filter.vol_halving_percentile`, the size multiplier is `filter.vol_size_mult`. Otherwise it is 1.0.
  - At the 90th percentile exactly, the multiplier is 0.5. At the 89.9th, it is 1.0.
- **F9.AC5 [unit]** Record-only rules.
  - Trend, funding, OI drop and premium compute and log their value on every decision.
  - While their mode is `record_only`, they never change the verdict.
  - With mode `enforce` and a threshold set, the veto applies at the threshold boundary.
- **F9.AC6 [simulation]** Shadow outcomes.
  - Every refused open, except `duplicate`, `out_of_scope` and `pre_existing`, gets a shadow trade with the same sizing, exits and cost model.
  - Shadows are flagged `shadow` and are never in equity, risk state, the trade count or S.
- **F9.AC7 [unit]** Automatic tier assignment (A6).
  - For each allowed core coin in the recording universe, two metrics are computed over the last `tiers.lookback_days` of our own recordings, using only records received at or before the computation time:
    - **depth:** the median, over L2 snapshots, of min(bid notional, ask notional) in USD within `tiers.depth_band_pct` of mid
    - **volume:** the median of the recorded 24h notional volume, sampled once per UTC hour
  - **Tier 1** iff depth ≥ `tiers.tier1_min_depth_usd` **and** volume ≥ `tiers.tier1_min_volume_usd`.
  - **Tier 2** iff not tier 1, and depth ≥ `tiers.floor_min_depth_usd` **and** volume ≥ `tiers.floor_min_volume_usd`.
  - **Below floor** otherwise, and also when recorded coverage over the lookback is < `tiers.min_coverage_fraction` (fail closed).
  - Boundaries, with defaults: depth $1,000,000 and volume $200,000,000 is tier 1; depth $999,999 with the same volume is tier 2; depth $50,000 and volume $10,000,000 is tier 2; depth $49,999 is below floor; coverage 0.79 is below floor.
  - Load-time check: a tier-1 threshold below its floor counterpart fails config load.
  - The tier code reads no coin-name list; a static test finds no coin symbol literal in the tier module. HIP-3 (`dex:`), spot and non-core coins are never tiered.
  - Each computed table (coin, metrics, tier, coverage, computation time, data window) is ledgered with its sha256. The same inputs give a byte-identical table.
- **F9.AC8 [unit]** Tier schedule (A6; edge-hypothesis A4.7).
  - The table is recomputed every `tiers.recompute_interval_h` (± 10 min), and during a run every 24 h under the frozen rule and thresholds. Each new table is ledgered with its sha256 and comes into force from its ledger time. Changes (coin, old tier, new tier) go into the next daily report.
  - At run start, the table in force at `t0` is stored in the run record with its sha256 (F17.AC1). A recomputed table during a run is not a config change. Each open, replay and cost decision uses the table in force at its decision time, read from the ledger.
  - Only a table that the frozen rule does not reproduce from the recorded data (F17.AC4) is a config change.
  - Fixture: a coin thins below tier 1 on day 3 of a run. Opens on day 4 use tier-2 thresholds and the alt fallback, while opens on day 2 keep their tier-1 decisions.
  - With no table in force, or one older than `tiers.max_age_h` outside a run, every open is refused with `untiered`, and one alert is sent.
  - Meme-perp fixtures: with recordings where DOGE, kPEPE and WIF meet the tier-2 thresholds, their opens pass the tier rule. With WIF below the floor, a WIF open is refused `illiquid_coin`, and DOGE and kPEPE are unaffected.
  - A coin that drops below the floor while a share is open keeps being managed: exits, SL/TP and reconciliation are never refused for tier reasons.

### F10 Risk gate and sizing
- **Value:** a single chokepoint that sizes every order from our risk budget and enforces every hard limit. The cap always wins.
- **Dependencies:** F2 and F11. F11 exposes a broker interface that requires a gate token.

- **F10.AC1 [integration]** Single chokepoint (A1).
  - Every order intent passes `risk_gate.check()`: open, add, reduce, close, SL/TP, `/flatten`, a dropped leader's exit, and a reconstruction settlement.
  - The broker rejects and logs any order without a valid, single-use gate approval.
  - A static test asserts that only the risk gate module calls broker submit.
- **F10.AC2 [unit]** Sizing.
  - `mirror_notional = (leader post-fill position notional / leader account value at or before the fill) × equity`
  - `risk_notional = equity × risk.per_trade_fraction × vol_mult / stop_distance_fraction`
  - `final = min(mirror, risk, every cap in AC3)`, rounded down to the lot.
  - Worked example: equity $300, stop 1.5%, leader at 50% of their account. Mirror is $150, risk is $100, so final is $100.
  - A final below `sizing.min_order_usd` is `unexecutable`: logged, with no order and no trade.
  - A leader account value that is missing, or older than `follow.max_leader_av_age_s`, gives `no_leader_av`.
- **F10.AC3 [unit]** Caps. The size is reduced to fit, then the $10 check is re-applied. Each cap is tested at its boundary:
  - open merged positions ≤ `risk.max_open_positions`
  - total open risk ≤ `risk.max_total_open_risk_fraction`
  - per coin ≤ `risk.max_symbol_open_risk_fraction`
  - BTC bucket, same direction ≤ `risk.max_btc_bucket_open_risk_fraction`. The bucket is BTC plus every coin with a correlation of 1h returns to BTC ≥ `risk.btc_bucket_corr_threshold` over `risk.btc_bucket_corr_window_days`.
  - per leader ≤ `risk.max_leader_open_risk_fraction`
  - notional ≤ `risk.max_position_notional_equity_mult × equity`
  - orders ≤ `risk.max_orders_per_min`
- **F10.AC4 [unit]** Automatic leverage and margin (A2).
  - Margin is isolated, one position per coin (the merged position). Size and initial risk are fixed first by AC2 and AC3; leverage never changes them.
  - **Ceiling:** `C = min(risk.max_leverage_high_tier if the coin is in risk.high_leverage_coins else risk.max_leverage_alt, the exchange maxLeverage for the coin)`.
  - **Choice:** at each open or add, L is the **lowest integer** in [`risk.leverage_min`, C] for which the merged position's required isolated margin (post-order notional / L) ≤ its currently posted margin + free equity. Free equity is equity minus all posted isolated margin.
  - No integer in the range fits → refused `insufficient_margin`.
  - **Liquidation rule:** at the chosen L, for **every** share of the merged position, the distance from the decision price to the liquidation price (the F11.AC5 model) must be ≥ `risk.min_liq_distance_stop_mult` × the distance from the decision price to that share's current stop. Otherwise the order is refused `liq_too_close`. No higher L is tried, because a higher L only moves liquidation closer.
  - Vectors, on a fixture where the liquidation distance is `1/L − 1/(2 × maxLeverage)` and the decision price equals the entry:
    - equity $300, no open positions, BTC $100 notional → 1x
    - free equity $40, ETH $100 → 3x
    - free equity $15, alt $100 (ceiling 5x needs $20) → `insufficient_margin`
    - free equity $12, SOL $100, exchange maxLeverage 20 → 9x (liquidation distance 8.611%); stop 2.8% passes (8.4% ≤ 8.611%); stop 2.9% is refused `liq_too_close` (8.7%)
    - free equity $12, DOGE $100 (not a high-leverage coin) → `insufficient_margin` (5x needs $20)
  - The chosen L, the ceiling C, the posted margin and the liquidation price go into the decision record (F2.AC2) and the trade post (F14.AC2).
  - Exits (reduce, close, SL/TP, `/flatten`, reconstruction settlement) are never refused for margin or leverage.
- **F10.AC5 [unit]** Loss limits and drawdown.
  - **Daily:** equity change since 00:00 UTC ≤ −`risk.daily_loss_limit` of that day's opening equity halts opens and adds until the next 00:00 UTC. At −1.99% nothing halts; at −2.00% it halts.
  - **Weekly:** from Monday 00:00 UTC, ≤ −`risk.weekly_loss_limit` halts until the next Monday.
  - **Drawdown:** mark-to-market equity is marked every `eval.mark_interval_s`. A drawdown from peak ≥ `eval.max_dd` does all of the following:
    - pauses until `/resume`
    - writes an F1 event
    - alerts
  - Loss halts are rule-based and are not downtime.
- **F10.AC6 [integration]** Kill switch (A4).
  - Telegram `/pause` or the CLI `pause` refuses new opens and adds within 1 s.
  - The state persists: after a restart the engine is still paused.
  - `/resume` or the CLI `resume` clears it.
  - `/flatten <PIN>` or the CLI `flatten --pin` closes every share through the gate.
  - All of this works with market-data feeds down.
- **F10.AC7 [unit]** Fail closed (A2, failure case).
  - Any exception in a check, an unknown equity or risk state, an unverified ledger, or config that failed validation each refuse opens and adds, with the reason logged.
  - Exits are **never** refused by caps, limits, blackouts or pauses. The gate only validates reduce-only, a quantity ≤ the share and idempotency.
- **F10.AC8 [unit]** Idempotency (A5).
  - The client order ID is `sha256(run_id ‖ leader ‖ coin ‖ sorted signal tids ‖ action ‖ share_id)`, truncated as the broker requires.
  - Re-submitting the same intent after a restart produces 0 extra fills.
- **F10.AC9 [unit]** Adds.
  - The add quantity is our share qty × (leader add size / leader pre-add |position|).
  - The add is skipped as `stop_widening` when its own ATR stop would sit beyond the current stop: below it for a long, above it for a short.
  - It is capped so the share's open risk is ≤ `risk.max_share_risk_fraction × equity`, and by the AC3 caps.
  - Below $10, it is skipped as `add_below_min`.
- **F10.AC10 [unit]** Leverage property tests (A2). Over ≥ 10,000 generated cases (coin in or out of the high-leverage list, equity, free equity, open shares, stops, exchange maxLeverage, notional), for every accepted open or add:
  1. **Ceiling:** 1 ≤ L ≤ C, and L ≤ 10 for high-leverage coins and ≤ 5 for every other coin, whatever the config.
  2. **Minimality:** L = `risk.leverage_min`, or L − 1 does not fit the margin.
  3. **Liquidation:** every share of the resulting merged position meets the liquidation rule.
  4. **Risk unchanged:** the final size and `initial_risk_usd` are identical to those computed with free equity set to infinity. Leverage never changes risk per trade.
  5. **Monotone:** raising free equity, all else equal, never raises L.
  6. **Refusal is exact:** an order is refused `insufficient_margin` iff no L in range fits, and `liq_too_close` iff the minimal fitting L fails the liquidation rule.
  7. **Single model:** the liquidation price used by the gate equals the F11.AC5 liquidation price for the same position, to the tick.
  8. **Exits:** no exit is ever refused for margin, leverage or liquidation distance.

### F11 Paper broker (fills, costs, funding, liquidation, delisting)
- **Value:** paper fills at real mainnet prices, with realistic costs, so the results transfer (D3).
- **Dependencies:** F1 and F2. It reads the book, mark and funding interfaces from F3 and F4.

- **F11.AC1 [unit]** Fill model.
  - A market order decided at `t` fills by walking the book at `t + paper.ack_delay_ms`: the first snapshot at or after that time within `paper.max_book_age_ms`.
  - The price is the VWAP across the levels needed.
  - Example: asks [100.0 × 0.5, 100.1 × 1.0], buy 1.0 → VWAP 100.05.
  - Depth insufficient within 5% of mid gives a partial fill, recorded as `partial_fill` (A8), with the remainder cancelled.
- **F11.AC2 [unit]** Fees.
  - Every fill, including SL, TP and liquidation, pays `cost.taker_fee_bps` of its notional.
  - No maker fills or rebates are simulated.
- **F11.AC3 [unit]** Funding.
  - At each UTC hour boundary, each open share pays or receives `qty × oracle_px × hourly rate`, signed by side, at that hour's actual rate.
  - A share closed before the boundary, or opened after it, pays nothing for that hour.
- **F11.AC4 [unit]** Exchange rules.
  - Orders below `sizing.min_order_usd` are refused with `below_min_notional`, except a reduce-only full close.
  - Tick and lot rules come from `meta`, refreshed every `paper.meta_refresh_min`.
  - A coin missing from `meta` is refused with `unknown_coin`.
- **F11.AC5 [unit]** Liquidation (A8).
  - An isolated position whose mark reaches its liquidation price closes at that price. It loses its margin and is flagged `liquidated`, and an alert is sent. Maintenance margin is half the initial margin at the asset's max leverage.
  - A fixture where the mark gaps through both the stop and the liquidation price gives `liquidated`.
- **F11.AC6 [unit]** Delisting. An open share on a delisted coin closes at the exchange settlement price, flagged `delisted_force_settle`, and it counts in every statistic.
- **F11.AC7 [unit]** Stops.
  - SL and TP trigger on mark and fill at the book at trigger time + `paper.ack_delay_ms`, never at a guaranteed price.
  - Example: long stop at 99, next book bid 97.0 → the fill is ≤ 97.0.
- **F11.AC8 [unit]** Rejects (A8, failure case).
  - With no book within `paper.max_book_age_ms`, an open is refused with `no_book` and not retried.
  - An exit is retried every `exits.retry_interval_s` until it fills, with one alert after `exits.alert_after_s`.

### F12 Position manager (shares, exits, mirroring, reconciliation, shadows)
- **Value:** first-exit-wins management that mirrors the leader's adds and partials, and never leaves an orphaned copy (C4).
- **Dependencies:** F7, F10 and F11.

- **F12.AC1 [unit]** Per-leader shares.
  - Each share has its own qty, entry, initial stop, current stop, TP state, initial risk and max committed risk.
  - A leader's event changes only that leader's share.
  - With leaders A and B both long ETH, A's close leaves B's share unchanged.
- **F12.AC2 [unit]** Stops and TP.
  - **Stop:** `entry_fill_px ∓ exits.stop_atr_mult × ATR(exits.atr_period)` on `exits.atr_candle_interval` candles that closed before entry.
  - **Take-profit:** with `exits.tp_enabled`, close `exits.tp1_fraction` of the share at `+exits.tp1_r` R, applying the $10 rules.
  - **Trailing stop:** after `+exits.trail_start_r` R, trail at `exits.trail_atr_mult × ATR` from the best mark since entry.
  - **Never widens:** a property test over 10,000 random paths shows the stop is non-decreasing for longs and non-increasing for shorts.
- **F12.AC3 [unit]** Partials [PO].
  - A leader reduce of fraction f reduces our share by f × its qty, rounded down to the lot.
  - A reduce notional below $10 is skipped as `partial_below_min`.
  - A remainder below $10 closes everything, as `close_all_remainder_below_min`.
  - Vectors: share $50 at f 0.4 reduces $20. Share $20 at f 0.4 is skipped ($8). Share $30 at f 0.7 closes all ($9 remainder).
- **F12.AC4 [unit]** First exit wins [PO].
  - A leader close closes our share.
  - After our SL or TP closes a share, that leader's later adds, reduces and close on that position are ignored until the leader is flat. The leader's next open is a new signal.
  - A leader flip closes our share and emits a new open signal.
- **F12.AC5 [integration]** Leader reconciliation (C4 and A7 analogue; edge-hypothesis A4.1).
  - It runs every `reconcile.interval_s` and after every resync.
  - For each open share, it reads the leader's `clearinghouseState`. If the leader is flat or reversed on that coin, *then*:
    - our share closes at once with `reconcile_close`
    - an alert is sent
    - F12.AC6 runs
  - **Fills and sizes.** Each pass also fetches the leader's fills since the last pass (`userFillsByTime`) and compares the leader's size on each coin where we hold that leader's share with `startPosition` + the signed size of the last fill the ledger has processed. Any mismatch, or any fetched fill not yet processed, runs the missed-exit detector (F12.AC6) at once.
  - Fixture: a dropped reduce that leaves the leader's sign unchanged is caught by the size comparison in the next pass, and it is a missed exit if more than 60 s old.
- **F12.AC6 [unit]** Missed-exit detector (P4 / F2, edge-hypothesis A3.1, A4.1, A4.5; test 21).
  - **Record.** Each §1 case is detected and ledgered as `missed_exit`. The record holds:
    - a missed-exit ID, the leader, the coin, the share ID and the event type
    - the event's exchange timestamp, the detection timestamp and the lag
    - the case: late, reconstruction failed or orphan (class 2 includes a data-gap exit not handled within 60 s after resync; class 3 includes exits found by the fill audit, F12.AC10)
    - how it was found: live, reconciliation, or daily or final fill audit
  - **Handled.** An event is handled if, within 60 s of its exchange timestamp, the ledger holds a mirror action, a rule-based skip record, or the share's full close. A skip recorded at 61 s is missed.
  - **Settled gap.** An exit inside a `data_gap` that is handled within 60 s of the resync is ledgered as `settled_gap_exit`, not as `missed_exit`. It does not count toward the `n/3` count or P4, its trade gets a mirror, and its gate R = min(actual, mirrored lo R).

    Each record is one missed exit, and a share can have several.
  - **Downtime.** For the three cases, position downtime is only `process_down` and `data_gap` before resync (§1). The P5 downtime union (F18.AC8) is never used here.
  - **Mirroring.** The share is brought in line with the leader at once: the late reduce or close goes through the gate.
  - **Alerts.**
    - One alert is sent within 60 s of detection.
    - It states the running count as `n/3`. During a run, the count covers missed exits with a leader event at or after `t0`. With no run active, it covers the time since the dry-run start, and that scope is labelled.
    - It states that the event is go-live blocker ME, and that its cost will follow (F12.AC9).
    - A second alert gives the cost once it is stored.
  - **Blocker.** Each missed exit writes a `go_live_blocker` record of type ME that no later record can clear within this epic (F20.AC4). That includes missed exits after `T_eval`, after the run ended FAIL or ABORTED, and in dry-run mode.
  - **No pause, no FAIL by itself.** Detection never pauses entries by itself (edge-hypothesis A3.1, P5). A missed exit does **not** by itself end the run: the FAIL decision belongs to F18.AC11.
  - On fixtures:
    - a dropped exit event found by reconciliation 61 s later is a missed exit; one found 60 s later is not
    - an exit mirrored 61 s late while `/pause` is active is a missed exit, because entries are paused but exits are managed; the same holds under `access_degraded`, `disk_low` and a deploy-wait pause
    - an exit inside a `process_down` interval that F13 settles is not a missed exit
    - a leader close inside a `process_down` gap longer than `restart.max_reconstruct_gap_h` (F13.AC3) is a missed exit, case "reconstruction failed"
    - a partial skipped under the $10 rule is not a missed exit, and neither is a leader close after our SL already closed the share
    - two missed exits on one share give two records and a count of 2
    - a rule-based skip record written 61 s after the event is a missed exit; written at 60 s it is not
    - a leader exit that our own SL/TP closes 61 s later is a missed exit; one closed 60 s later is not
    - a leader exit inside a data gap, mirrored 60 s after resync, is a settled gap exit (no count, its trade counts at min(actual, mirrored lo)); mirrored 61 s after resync it is a missed exit of class 2
    - an exit found only by the daily fill audit is ledgered as an orphan with "found by: audit"
- **F12.AC7 [simulation]** `/flatten` shadows (edge-hypothesis A1.3 d, A2.1 and A4.2).
  - Each flattened share gets a shadow, managed on recorded data under the frozen exit rules: leader exits, SL/TP and hourly funding. Over recording gaps it uses candles from the candle store (F4.AC9), with the stop assumed hit first, and **inside a gap it fills at the lo candle prices** of F12.AC9 (worst price + 8 bps, SL/TP at the trigger or a gapped-through open).
  - The shadow runs until the shadow exit, whose time and R are stored.
  - Moving the flatten time while the shadow path is unchanged leaves the shadow exit unchanged.
- **F12.AC8 [unit]** A dropped leader's shares stay managed by our SL/TP and that leader's exits, through the gate, until they close.
- **F12.AC10 [integration]** Leader-fill audit (edge-hypothesis A4.1; test 25; `eval_reference.py::exit_class`).
  - **Schedule.** Every `eval.fill_audit_interval_h` (24 h), for every leader with a share open at any time since the last audit (followed or dropped), the engine fetches the leader's fills (`userFillsByTime`) from the end of the previous audit to `exits.missed_exit_max_lag_s` before now. It classifies every leader exit event on a coin where we held that leader's share at the event time.
  - **Result.** An event that was neither handled within 60 s nor settled inside downtime is a missed exit. If the ledger does not hold it yet, it is ledgered now as an orphan, "found by: audit".
  - **Final audit.** Before the verdict, one more audit covers every such leader up to `T_eval` (F18.AC3).
  - **After `T_eval`.** Audits continue every 24 h until every share of the run has closed, so late missed exits are still found (they are ME, F20.AC4).
  - **Incomplete audit.** An audit interval is complete when every fill in it has been retrieved. If the API is unreachable or a page is truncated, the interval is retried every `storage.retry_interval_min` for up to `eval.missing_data_retry_max_h` (72 h) from its first attempt, with one alert per `storage.alert_interval_h`.
    - A stretch of `[t0, T_eval]` in which we held a leader's share that is still unaudited after 72 h is a **P4 breach** (F2), with breach time at the stretch's start (F18.AC7).
    - An unaudited stretch after `T_eval` is listed with the ME list.
  - **Coverage.** Per leader, the audited intervals, retries and any unaudited stretch are ledgered and reported (F20.AC1).
  - Fixtures:
    - a reduce dropped by a dead `userFills` subscription is found by the daily audit as an orphan
    - a close and reopen between two reconciliation passes is found the same way
    - a leader close that our own SL/TP closes 5 minutes later is found as a missed exit
    - an audit interval unreachable for 71 h and then retrieved gives no breach, and one unreachable for 72 h gives a breach at the stretch's start
    - a dropped leader with an open share is still audited
    - a leader with no share since the last audit is skipped, so 0 requests are sent for it
- **F12.AC9 [simulation]** Mirror, gate values and cost (edge-hypothesis §5.3 "Missed-exit rules", A3.1, A4.2, A4.3; tests 21, 26 and 27; `eval_reference.py` `gap_candle`, `gap_fill_px`, `gap_trigger_px`, `missed_exit_costs`).
  - **Construction.** For each share with a missed exit, the engine builds one **mirror** with the `/flatten` shadow machinery (F12.AC7). The mirror is the share managed on recorded data under the frozen exit rules from its **first** missed leader event on. That event and every later leader event on the share (adds, reduces, closes and flips) are mirrored on time.
    - The mirror uses the same stop, TP, trailing stop, $10 rules and hourly funding as the real share.
    - A mirrored leader action is decided at the event's exchange timestamp + `copyreplay.delay_ms`. It is filled by the F11.AC1 fill model at the book recorded at that decision time + `paper.ack_delay_ms`, walked with the share's size.
    - **Candle fill rule (A4.2).** Without a recorded book within `baseline.dm_max_book_gap_s` (5 s) of the fill time (a recording gap, a lost file, or data not covered by a ledgered hash), a mirrored action fills on the 1m candle that contains the fill time, else the 1h candle, from the candle store (F4.AC9).
      - **lo** = the candle's worst price for our side (high for a buy, low for a sell) moved against us by 8 bps.
      - **hi** = the candle's best price for our side moved against us by 2 bps.
      - Both pay the taker fee. There is no delay term, and the tier table is not used.
      - An SL or TP triggered inside a gap fills at its trigger price, or at the bar's open if the bar opened beyond the trigger (gap-through), moved against us by 8 bps (lo) or 2 bps (hi).
    - Over a gap in our recording, the SL/TP path uses the same candles. A lost file (F23.AC3) counts as a gap. An ambiguous bar is resolved **both ways**: stop first gives the **mirrored lo R**, and TP first gives the **mirrored hi R**. Without an ambiguous bar, lo = hi (fills excepted).
    - A mirror still open at `t300 + eval.closeout_max_days` is marked at the recorded mid − taker fee − half-spread (F18.AC3).
  - **Values.**
    - **Gate R** = min(actual R, mirrored lo R). For a flattened trade it is the minimum of realised, shadow and mirrored lo R (`eval_reference.gate_r`). The gate USD P&L is the USD of the chosen outcome.
    - **Costs (A4.3).** Number the share's missed exits 1..k by leader event time (ties by missed-exit ID). Mirror M_j is the share managed from missed exit 1 on with missed exits 1..j and every other leader event mirrored on time, and missed exits j+1..k handled as the engine actually handled them (or not at all if the share closed first). M_k is the mirror above.
      - The **incremental cost** of missed exit j = hi R(M_j) − hi R(M_(j−1)), with hi R(M_0) = actual R.
      - The **trade cost** = hi R(M_k) − actual R, the sum of the increments.
      - Each is in the share's R, rounded half-even to 1e-6 (`eval_reference.missed_exit_costs`). Two missed exits cannot net each other out.
      - **Actual R** is the realised R at the real full close (the flatten price for a flattened trade, never its shadow), or the marked value if the trade is still open at `t300 + eval.closeout_max_days`.
    - A mirrored hi R below the mirrored lo R is an error and is never stored.
  - **Timing.** Actual, lo and hi R, gate R and cost are stored within 5 min of the later of the share's full close and its mirror exit, or at `T_eval` with whichever is still open marked. Until then, the missed exit shows "cost pending".
  - **Uncomputable mirror (fail closed, A4.2).** A mirror is uncomputable if a fill or a gap stretch of its SL/TP path needs a candle that is neither in the candle store nor obtained from the exchange within `eval.missing_data_retry_max_h` (72 h) of the first attempt. Until then:
    - the build is retried every `storage.retry_interval_min`, with one alert per `storage.alert_interval_h`
    - no cost is guessed, and the missed exit shows "cost pending"

    After 72 h:
    - every cost of that share counts as **above 1R** (F2 through `p4_breach`, with the cost as +∞)
    - the mirrored lo R = actual R, so gate R = actual R
    - the mirror exit = the real close
    - the breach time is the leader event time of its first missed exit (F18.AC7)
    - the verdict never waits beyond the bound
  - Vectors (E15 `GOLDEN_MISSED`, plus spec cases):
    - actual +0.8, mirrored lo +0.3 → gate +0.300000
    - actual −1.4, mirrored lo = hi −0.2 → gate −1.400000, cost 1.200000
    - realised +0.5, shadow +0.2, mirrored lo +0.4 → gate +0.200000
    - actual −1.3, mirrored lo −0.5, hi −0.2 → gate −1.300000, cost 1.100000
    - actual −2.003, mirrored hi −1.003 → cost 1.000000. The binary64 difference is 1.0000000000000002, so only the rounded Decimal may be compared.
    - actual +0.8, mirrored lo = hi +0.5 (the late exit was luckier) → gate +0.500000, cost −0.300000
    - mirrored lo +0.2 with hi +0.1 → error
    - timing: leader event at T, `copyreplay.delay_ms` 3,000 and `paper.ack_delay_ms` 1,000 → decided at T + 3,000 ms, filled at the first book at or after T + 4,000 ms
    - a recording gap with one 1h bar touching both the stop and the TP gives lo from the stop exit and hi from the TP exit; the gate uses lo and the cost uses hi
    - candle fill (spec arithmetic; /tests takes the exact `GOLDEN_A4_*` vectors from E16): a buy filled in a 1m candle with high 101.00 and low 99.00 gives lo = 101.00 × 1.0008 = 101.0808 and hi = 99.00 × 1.0002 = 99.0198 (before fees); with no 1m candle in the store, the 1h candle is used
    - a gapped-through SL: the bar opens at 95 beyond a long stop at 97, so the mirror fills at 95 minus 8 bps (lo) or minus 2 bps (hi), not at 97
    - two missed exits on one share with increments +1.3R and −0.5R: trade cost 0.8R, but the first increment (1.3R) breaches P4
    - no candle obtainable for 72 h: the cost counts as above 1R, lo = actual, exit = the real close, and the breach time is the first missed exit's leader event time; at 71 h 59 min it is still pending
    - over the grid actual ∈ {−2.0, −0.7, 0, 0.4, 1.9} × mirrored lo ∈ {−1.5, −0.1, 0, 0.6, 3.0}, gate R ≤ both
  - Every value is Decimal quantised to 1e-6, and the same inputs give byte-identical records.

### F13 Restart reconstruction
- **Value:** downtime on a home PC never leaves a position unmanaged, and never fakes a result.
- **Dependencies:** F3, F4 and F12.

- **F13.AC1 [simulation]** Reconstruction.
  - Scope: shares open at the last heartbeat `t_s`, with a restart at `t_r` where `t_r − t_s` ≤ `restart.max_reconstruct_gap_h`.
  - Before any new decision, the engine walks the leader fills from `userFillsByTime` over `[t_s, t_r]` and the `restart.candle_interval` candles, in time order:
    - the first of SL, TP or a leader exit acts; the stop is assumed first on an ambiguous bar, and partials are mirrored
    - fills are at the trigger or leader price ± `cost.fallback_half_spread_bps` and `cost.fallback_delay_slippage_bps`, plus taker fees. The major or alt value is chosen by `cost.fallback_tier_rule` on the copy side (§1): tier 1 at decision time is a major, and anything else, untiered included, is an alt.
    - hourly funding is accrued
    - these shares are flagged `reconstructed`
- **F13.AC2 [unit]** Leader opens during the gap are never taken. They are logged `missed_during_downtime` and are not trades.
- **F13.AC3 [unit]** Gap too long (failure case).
  - A gap over `restart.max_reconstruct_gap_h`, or candles that can't be fetched, closes each share at the first fresh book after restart.
  - Those shares are flagged `unreconstructable`, an alert is sent, and they are included in every statistic.
- **F13.AC4 [integration]** Downtime and speed.
  - `[t_s, t_r]` is ledgered as `process_down` downtime.
  - The kill-switch state is restored before any other component starts.
  - For a gap of ≤ 1 h, the engine is trading-ready ≤ 120 s after process start.
- **F13.AC5 [unit]** A second restart during reconstruction gives an identical result, with 0 duplicated closes.

### F14 Telegram bot, reports and alerts
- **Value:** the PO sees every trade and controls the bot securely from their phone.
- **Dependencies:** F2, F10 and F12. It uses F15's interface optionally.

- **F14.AC1 [integration]** Authentication (E3, abuse case).
  - Only updates from `telegram.allowed_user_id` in `telegram.control_chat_id` are executed.
  - 5 commands from another user or chat cause 0 state changes and write 5 ledger audit records: user ID, chat ID, command name, time and result.
  - At most one alert is sent per `telegram.unauthorized_alert_interval_min`.
- **F14.AC2 [qa-ui]** Trade posts.
  - On entry, a post arrives within 5 s (p95) and shows:
    - a direction marker (green for long, red for short) and a `PAPER` label
    - coin, direction, entry price, SL, TP, size (qty and USD) and leverage
    - each leader's label (display name or shortened address) with that leader's scoring-window win rate and P&L
    - the "why" text, or "why unavailable"
  - A merged position has exactly one post, which is edited on each add, partial, stop move and close.
  - The final post shows the realised USD P&L and the exit reason.
- **F14.AC3 [unit]** Edit rate.
  - Each message gets ≤ 1 edit per `telegram.min_edit_interval_s`, and intermediate states are coalesced.
  - The latest state is visible ≤ 10 s after the last change.
  - Each chat gets ≤ `telegram.max_msgs_per_min_per_chat`.
  - An HTTP 429 `retry_after` is honoured.
- **F14.AC4 [qa-ui]** Commands, each answering within 3 s (p95):

  | Command | Shows or does |
  |---|---|
  | `/status` | Mode, running or paused (with reasons), followed count, open positions, feed health, run number and n/300, free disk, archive state (backlog days, last verified day and backup, or `archive: not configured`) and the projected monthly storage cost |
  | `/pnl` | USD realised and unrealised: today, this week, and this run |
  | `/traders` | Followed wallets with score, rank and follow start |
  | `/stats` | Descriptive run statistics (F14.AC9) |
  | `/pause`, `/resume` | Pause or resume new opens and adds |
  | `/flatten <PIN>` | Close every share |

- **F14.AC5 [unit]** PIN (abuse case).
  - The PIN is checked against a salted hash from the environment, and the PIN itself is never stored.
  - A wrong PIN is refused, audited and alerted.
  - `telegram.pin_max_attempts` failures within `telegram.pin_lockout_min` lock `/flatten` for `telegram.pin_lockout_min`. The CLI flatten stays available.
  - The bot deletes the message containing the PIN after processing.
- **F14.AC6 [unit]** Visibility lock (edge-hypothesis §5.5, A3.2; test 7).
  - While a run is active and before `T_eval`, no message, command, report, alert or log shows any of these:
    - any interval, bound (`LB_r`, `UB_r`), standard error, t statistic, p-value or bootstrap output of the mean of R or of D, by any of the three methods
    - any B0d replication, B̄_i, D_i or P2c status
    - FR1–FR6, K9/S4 (B1), P6, G, any cross-day diagnostic, or the D6 checks
    - any verdict preview: pass, fail or "on track" for any gate condition (P1–P6, P2b, P2c, F1–F3), a projected bound, a probability of PASS, or a traffic light
  - **Run-result content (A4.11)** is any figure computed from the outcomes (R, USD P&L, exit prices, exit reasons) of our trades, shadows, mirrors or any baseline. Before `T_eval` it appears **only** in the `/stats` list (F14.AC9) and in each trade's own post.
    - Every other aggregate of outcomes is refused: per coin, per day or week, per exit reason, the exit-reason mix, payoff ratio, R_maxrisk, S2–S6, decay and edge lost per second, and every item of the "Also computed at `T_eval`" list except the missed-exit counter.
    - **Operational content** is not computed from outcomes and stays allowed in `/status`, `/traders`, alerts and reports, never with a pass/fail label: mode, health, disk, archive and storage cost; followed wallets with score, rank and follow state; the leaders' own figures in trade posts; counts of signals, entries, exits, refusals and skipped mirrors by reason; followed-set and tier changes; latency; and the operational counters (downtime used, missed exits with costs, pending deploy rulings).
    - The operational counters show raw values against their limits, with no pass, fail or on-track label.
    - Adding a run-result metric to `/stats` or to a report is a spec change, checked against §5.5 (Assumption A25, confirmed).
  - A test renders every template, including `/stats`, `/status`, `/traders`, alerts and reports, with a run fixture and finds 0 forbidden fields or phrases. A log capture over a simulated run finds none either.
  - A second test feeds a fixture with known outcomes and asserts that outside the `/stats` list and trade posts, no template contains any outcome-derived figure (for example, a daily report with a per-coin P&L is refused).
  - A static dependency test shows that `telegram` and `reports` never import `evaluation` or `baselines`.
- **F14.AC7 [qa-ui]** Reports.
  - The daily report goes out at `report.daily_time_utc` and the weekly one at `report.weekly_time_utc`.
  - Each covers: USD P&L (**omitted while a run is active and before `T_eval`**, because a daily or weekly P&L is an outcome aggregate outside the `/stats` list, A4.11; the report then points to `/stats`), trades opened and closed, refusals by reason, unexecutable count, downtime, followed-set changes, missed exits (count and IDs), coin-tier changes (F9.AC8), archive state and the projected monthly storage cost (F23.AC7).
  - Each ends with `report.disclaimer`.
- **F14.AC8 [integration]** Alerts and outage (failure case).
  - Alerts go only to `telegram.alerts_chat_id`.
  - If the Telegram API is unreachable:
    - messages queue up to `telegram.queue_max_messages` or `telegram.queue_max_age_h`
    - trading continues
    - alerts are also written to the local log
    - the queue drains in order on recovery
- **F14.AC9 [qa-ui]** `/stats` (PO decision A14; edge-hypothesis §5.5, A3.2, A4.11). It is one of only two places that show run-result content before `T_eval` (the other is each trade's own post).
  - It answers within 3 s (p95), from ledger aggregates (F2) only.
  - **Scope.** It covers the active run. With no run active, it covers the time since the dry-run start or the last run end, and labels that scope.
  - **Results, overall and per trader followed at any time in the scope:**
    - net USD P&L: realised, marked unrealised for open positions, and total
    - closed-trade count and win rate (the share of closed trades with realised R > 0)
    - average R: the plain mean of realised R over closed trades, labelled "descriptive, not the verdict"
  - **Drawdown, overall** (the P3 quantity, marked to market): current and maximum. It is shown on actual equity, and also on the F18.AC7 shadow equity once any trade has been flattened or has a missed exit.
  - **Progress:** trades opened (n/300), closed and open, and days elapsed against the 30-day cap and the 60-day extension.
  - **Operational counters.** Each is shown as a raw value against its limit, with no pass/fail label:
    - **downtime used:** the P5 union (F18.AC8) since `t0`, in hours and as a percentage of the elapsed `[t0, now]`, against the 2% limit, labelled "P5 is judged on [t0, T_eval]"
    - **missed exits:** the count since `t0` against the limit of 3, each with its ID and its cost (F12.AC9), or "cost pending"
    - **pending deploy rulings:** the count, and each deploy ID awaiting a ruling (F17.AC3)
  - **Footer (fixed):** "Descriptive only, realised results. Not the gate statistic and not a verdict. The verdict is computed once at T_eval."
  - Vectors:
    - 12-trade fixture (7 winners, R values summing to +1.800000, USD +$4.20): 12 closed, 58.3% win rate, average +0.150R, +$4.20
    - 3 h of `/pause` plus 1 h of `process_down` over 10 elapsed days: downtime 4.0 h, 1.67% of elapsed, limit 2%
    - one missed exit with cost 0.200000R and one with its cost pending: "missed exits 2 / limit 3", each listed
    - with 0 closed trades: "no closed trades yet", and no ratios (no division by zero)
  - Nothing outside this list appears (F14.AC6). The figures are realised, never gate-adjusted (Assumption A23).
  - From an unauthorised user or chat, it behaves as F14.AC1: 0 output and one audit record.

### F15 LLM explainer ("why" text and summary)
- **Value:** readable context for each trade, with zero influence on trading [PO D5].
- **Dependencies:** F2 and F14's interface.

- **F15.AC1 [unit]** Off the hot path (F1 invariant).
  - The trade post is sent without waiting for the LLM.
  - The "why" text is added by an edit if it returns within `llm.timeout_s`. Otherwise the post stays "why unavailable".
- **F15.AC2 [unit]** Budget.
  - When the tracked month-to-date spend reaches `llm.monthly_budget_usd`, cloud calls stop until 00:00 UTC on the 1st of the next month.
  - `llm.fallback` (Ollama) is tried next. If both are unavailable, there is no "why" text.
  - Spend never exceeds the cap by more than one call's cost.
- **F15.AC3 [unit]** Logging (F3 invariant). Each prompt and output is logged with its decision ID, and prompts contain 0 secrets (canary test).
- **F15.AC4 [unit]** No vote (F2 invariant). A static dependency test shows that `filters`, `risk` and `positions` never import `llm`. An LLM stub returning "reject" or "double the size" changes 0 decisions.
- **F15.AC5 [unit]** Injection (abuse case).
  - A leader display name or an output containing Markdown or HTML, or text like "ignore previous instructions", is escaped in Telegram.
  - Output is truncated to `llm.max_output_chars`.
  - Inputs are limited to the trade record, the calendar events within ±24 h and the coin's recorded regime metrics. No web fetch.

### F16 Replay engine
- **Value:** point-in-time replays through the **same** engine, for the kill checks, variant choice, P6 and D6.
- **Dependencies:** F4, F9, F10, F11 and F12.

- **F16.AC1 [simulation]** Same code. Replay drives the same signal → filter → gate → broker → position modules, with a replay clock. A static test finds no replay-only decision code.
- **F16.AC2 [simulation]** Point-in-time (D1 and D2).
  - At replay time t, it uses only recordings received ≤ t and our own leaderboard snapshots.
  - Injecting future data changes 0 decisions.
- **F16.AC3 [simulation]** Determinism. Two replays of the same window and config give byte-identical ledgers.
- **F16.AC4 [unit]** Indicative mode.
  - Any replay that uses data from before our recording start (API history) labels every output `indicative_only_survivorship_biased`.
  - The evaluation API refuses it as input.
- **F16.AC5 [simulation]** Variant budget (D4).
  - Only V0–V7 (edge-hypothesis §5.8) can be run, and the ledger counts distinct variants. A 9th is refused.
  - Sensitivity runs (`replay.sensitivity_cost_mults`, `replay.sensitivity_delays_s`) run on the selected variant and are not counted.
- **F16.AC6 [simulation]** Cost model (edge-hypothesis A3.3, A4.7).
  - Spread: recorded at signal time; otherwise the coin's median half-spread × `cost.fallback_half_spread_mult`; otherwise `cost.fallback_half_spread_bps`.
  - Delay: measured decay at the p95 detection latency; otherwise `cost.fallback_delay_slippage_bps`.
  - The major or alt value of each fallback is chosen by `cost.fallback_tier_rule` on the copy side (§1, edge-hypothesis A3.3).
  - Ambiguous bars: the stop is assumed first.
  - Test 23, copy side. At decision time:
    - a coin in tier 1 uses 2 / 5 bps
    - a tier-2 or below-floor coin uses 8 / 15 bps
    - a coin with no tier record uses 8 / 15 bps (an alt for paper trades, replays, reconstruction and shadows)

    The random-time side and the other baselines (B0d, B0, B0b, B1, B3, where an untiered coin is a major) are in F19.AC4 and F20.AC1.
- **F16.AC7 [simulation]** Speed. A replay of 7 recorded days for 9 wallets finishes in ≤ 60 min on the PO's PC.

### F17 Run control (run record, freeze, deploys, run register)
- **Value:** runs that can't be quietly altered. This implements edge-hypothesis §5.1, §5.3 (engine changes) and §5.4.
- **Dependencies:** F1 and F2. F8 supplies the calendar-coverage check.

- **F17.AC1 [integration]** Run record. `run start` writes:
  - the run number and `t0`
  - the sha256 of `docs/sdlc/copytrade-v1/research/edge-hypothesis.md`
  - the config hash: sha256 over the sorted (path, bytes) of `config/**`
  - the CI level: `eval.ci_level_run1` or `eval.ci_level_run2`
  - a 32-byte CSPRNG seed as hex
  - the 40-hex engine commit and the dirty flag
  - the lockfile sha256 and the Python version
  - the installed-package-list sha256: `name==version` with normalised lowercase names, sorted, UTF-8, LF line endings
  - the per-file sha256 of every non-config data input
  - the coin-tier table in force at `t0` (F9.AC8), stored in full with its sha256. It is the starting table only: later tables are ledgered every 24 h (F9.AC8).

  A fixture checks each field and the canonical package-list bytes.
- **F17.AC2 [integration]** Refusals (fail closed). `run start` refuses when any of these holds:
  - the dirty flag is true: a tracked engine-path-set file differs from the commit, or an untracked file exists inside the set
  - the checkout is not a worktree detached at the run commit
  - the ledger doesn't verify
  - the calendar covers fewer than `calendar.min_coverage_days`
  - the candidate backfill is incomplete
  - `eval.max_runs` runs are already registered
  - no tier table is in force, or it is older than `tiers.max_age_h`
  - the archive is unhealthy: storage credentials are missing, a finished UTC day older than `storage.max_unarchived_days` is not archived, or no ledger backup has verified in the last 48 h (F23)
  - **(A3.4)** the recording process or the archive process is not running on the run commit from the run worktree. That means either of these:
    - it has no heartbeat within `feed.stale_after_s`
    - its latest `component_start` record (F4.AC8) differs from the run record in commit, dirty flag, worktree path, lockfile, Python version or package list

    A fixture where the recorder still runs from the pre-run recording worktree is refused, and the refusal names the recorder.
  - **(A3.1, K13)** it is run 2, and a missed exit from run 1 is unresolved (F17.AC9)

  A commit or untracked file under `docs/**` or `research/**` does **not** make the tree dirty.
- **F17.AC3 [integration]** Mid-run deploys (edge-hypothesis §5.3 "Engine changes", §5.5, A3.1, A3.2 c, A3.4).
  - **Scope.** The check runs at each process start during a run of any engine component: the trading engine, the recording process and the archive process (F4.AC8).
  - **What is compared.** Six things, against the run's version in force: the commit, the dirty flag, the lockfile hash, the Python version, the installed-package-list hash and the data-input hashes.
  - **On any difference:**
    - A deploy record is written. It holds the time, the component, the old and new commit, the full `git diff` stored as a patch with its sha256, the lockfile diff, and a stated reason.
    - The stated reason has a **reason kind**:
      - `defect`, with a reference to the spec AC or edge-hypothesis section the running code violates
      - `interim_result`
      - `other`

      The reason text is stored verbatim.
    - The new code exits non-zero, without trading, managing positions or recording, until a ruling is in the ledger: `CONTINUE` with the affected trade IDs, or `ABORTED`.
    - The recorded commit keeps running from the run worktree, for the engine and for the recorder.
    - Any paused time counts as downtime.
  - **Interim results can't justify a deploy (A3.2 c).** `run ruling <deploy ID> CONTINUE` is refused for a deploy whose reason kind is `interim_result`, or `defect` without a reference. Only `ABORTED` can be recorded for it.
    - Fixture: a deploy with reason kind `interim_result` gets CONTINUE refused, while ABORTED is accepted and ends the run as ABORTED at that moment.
  - **Missed-exit fixes (A3.1).** A fix for the cause of a missed exit is a deploy like any other, and nothing above is relaxed for it. Missed exits under the recorded commit while a ruling is pending count toward F2.
  - **Recorder (A3.4).** A recorder started from another worktree or commit during a run writes a deploy record and exits without writing any recording file, while the run-worktree recorder keeps recording.
- **F17.AC4 [unit]** Config change. A config hash that differs from the run record, checked at start and every 60 s, makes the run `ABORTED` at that moment. The run count increments, and a 3rd run can't start. A tier table is **not** a config change merely because it differs from the table at `t0`: each 24 h recomputation is ledgered and in force from its ledger time (F9.AC8, A4.7). Only a table that the frozen rule and thresholds do not reproduce from the recorded data (a check recomputes it from the ledgered inputs) is treated as a config change, and makes the run `ABORTED`. Fixture: a recomputed table that the rule reproduces leaves the run running, and a hand-edited table is ABORTED.
- **F17.AC5 [unit]** Manual end.
  - `run stop --confirm` ends the run as `ABORTED`.
  - An auditor void-ruling record makes it `ABORTED` even after an F1 or F2 breach, and it can never produce `PASS`.
- **F17.AC6 [unit]** Run register.
  - Start, end, deploy and ruling rows are appended to the ledger's run register.
  - `run register export` prints rows in the `research/run-register.md` column order.
  - Appending never changes the edge-hypothesis or config hash (evaluation test 18).
- **F17.AC7 [unit]** Dry-run mode. It runs the full pipeline without writing a run record, and none of its trades can ever enter any run's sample.
- **F17.AC8 [unit]** A crash restart is not a deploy: same commit, a clean tree, the same lockfile, config, package list and data inputs, from the run worktree. It writes only downtime.
- **F17.AC9 [unit]** Missed exits before run 2 (edge-hypothesis K13 and §5.3 "Engine changes"; Assumption A24).
  - `run start` for run 2 refuses, naming each missed-exit ID, while any missed exit ledgered during run 1 has no `missed_exit_resolution` record. This covers missed exits at any time, including after `T_eval`.
  - A resolution record holds the missed-exit ID, a written root cause, the fix commit, and the ID of a regression test that reproduces the missed exit.
  - `run start` checks that the fix commit is an ancestor of the run commit, and that the test ID exists under `tests/**` at the run commit.
  - A resolution record never clears go-live blocker ME. The report still lists the ME, with its resolution next to it (F20.AC4).
  - Fixture: run 1 has 2 missed exits and only one is resolved, so run 2 is refused and the other is named. With both resolved, run 2 starts. With a fix commit that is not an ancestor, run 2 is refused.

### F18 Evaluation: verdict core (edge-hypothesis §5.3, exact)
- **Value:** the pre-registered PASS / FAIL / INCONCLUSIVE / ABORTED verdict, computed reproducibly across implementations.
- **Dependencies:** F2. F18 is pure over ledger records; B0d inputs come from F19, and the P6 input from F16.

- **F18.AC1 [unit]** Conformance oracle.
  - The implementation reproduces every golden literal in `research/scripts/eval_reference.py` v4 (E16, edge-hypothesis A4.12), which keeps every E15 literal. RNG outputs must match exactly, cost strings exactly as Decimal, and everything else to 1e-6:
    - `GOLDEN_RNG` and `GOLDEN_REJ`, including the rejection case n = 2^63 + 1
    - the percentile indices: 200 and 9,799 at 96%, 50 and 9,949 at 99%
    - `GOLDEN_TOY`, `GOLDEN_UNEQUAL`, `GOLDEN_DISTINCT` and `GOLDEN_DC`
    - `GOLDEN_FLATTEN` and `GOLDEN_D`
    - **(A3.6)** `GOLDEN_MISSED` and `GOLDEN_MISSED_CLOSE` (F12.AC9, F18.AC3, F18.AC11)
    - **(A4.12)** every `GOLDEN_A4_*` vector (candle fills, incremental and trade costs, breach time, settled gap, B̄ max rule, fill audit, uncomputable mirror)
  - Each of the 31 E16 mutants (edge-hypothesis §12), applied to the implementation, fails at least one test. The count includes the 16 E15 mutants M1–M16.
- **F18.AC2 [unit]** Sample S.
  - S is the first `eval.n_trades` shares by entry-fill time in `[t0, t0 + eval.calendar_cap_days + eval.extension_days)`. Ties are broken by client order ID, ascending.
  - Trade 301 is never in S, even when it closes first.
  - Refused, shadow and unexecutable signals are never trades.
- **F18.AC3 [unit]** `T_eval`, evaluation close, marking and verdict timing.
  - `T_eval = min(last evaluation close in S, t300 + eval.closeout_max_days)`.
  - The **evaluation close** is:
    - the full close, by default
    - the shadow exit, for a flattened trade
    - **(A3.1)** for a trade with a missed exit, the later of the above and its mirror exit (F12.AC9)

    `hold_i` = min(evaluation close, `T_eval`) − entry fill.
  - Trades, shadows or mirrors still open at the cap are marked at the recorded mid − taker fee − half-spread.
  - Funding counts through the last hourly funding ≤ `T_eval`.
  - A later real outcome is reported separately, and the stored verdict never changes.
  - **Verdict timing (A3.1, A4.1, A4.8 c).** The verdict is computed no earlier than `T_eval + exits.missed_exit_max_lag_s`, and only after all of these:
    - a reconciliation pass (F12.AC5) over every share open at `T_eval` has completed
    - the final leader-fill audit (F12.AC10) has completed, for every leader on whom we held a share in the window
    - every value the verdict uses has been recomputed from hash-verified data (F23.AC3)

    So every missed exit with a leader event at or before `T_eval` is in the ledger first. The wait is bounded at `eval.missing_data_retry_max_h` (72 h): after that, an incomplete audit or an uncomputable mirror counts as a P4 breach (F18.AC11) and the verdict is computed. Fixture: a final audit that completes at `T_eval` + 30 h delays the verdict to then. One that never completes gives FAIL at `T_eval` + 72 h.
  - Vectors (E15 `GOLDEN_MISSED_CLOSE`). The fixture: t300 = d0 + 30 h; M is SOL long, entry d0 + 1 h, real close d0 + 2 h, missed exit, mirror exit d0 + 40 h; N is SOL long, d0 + 30 h to d0 + 32 h; O is ETH short, d0 + 26 h to d0 + 28 h.
    - `T_eval` = d0 + 40 h, and hold M = 39 h. M is not marked.
    - With M's mirror still open, `T_eval` = d0 + 198 h, and M is marked.
    - With a real close at d0 + 45 h and a mirror exit at d0 + 40 h, M's evaluation close is d0 + 45 h.
- **F18.AC4 [unit]** Day clusters.
  - Clusters are transitive merged components: same coin and direction, closed intervals, touching counts. Each interval ends at the F18.AC3 evaluation close, so shadow exits count for flattened trades and the later of the real close and the mirror exit counts for missed-exit trades.
  - A trade's cluster is the UTC day of the component's first entry. G is the number of distinct clusters.
  - This reproduces `GOLDEN_DC` and the `GOLDEN_MISSED_CLOSE` clusters M/N/O = 0/0/1: N joins M through M's mirror exit, not its real close.
- **F18.AC5 [unit]** Intervals.
  - `LB_r` and `UB_r` are the min and max of three intervals:
    - the iid t-interval, with n − 1 df
    - the day-cluster percentile bootstrap: B = `eval.bootstrap_b`, pooled mean, tags `bootR` and `bootD`, seeded with the 32 raw bytes of the run seed
    - the cluster-robust t-interval, with G − 1 df and the G/(G − 1) factor
  - Results are rounded half-even to 1e-6 before comparison.
  - A hex-text seed, or a seed that isn't exactly 32 bytes, is an error.
- **F18.AC6 [unit]** Precedence.
  - The order is: ABORTED → FAIL (F1/F2) → INCONCLUSIVE (P1) → INCONCLUSIVE (G < 5) → FAIL (F3) → PASS (P1–P6, P2b, P2c) → INCONCLUSIVE.
  - Over a generated grid of every boolean combination, with G ∈ {3, 4, 5, 6} and LB/UB ∈ {−0.000001, 0.000000, 0.000001}, the result equals `eval_reference.verdict` for 100% of cases.
  - The F2 boolean in that grid is `p4_breach(count, costs)` from F18.AC11, never "at least one missed exit".
  - **ABORTED versus FAIL (A4.4).** ABORTED wins only when its time is strictly earlier than the P4 breach time (F18.AC7). A tie goes to FAIL. Fixture: an abort at the same millisecond as the 4th missed exit's leader event gives FAIL, and an abort 1 ms earlier gives ABORTED.
  - The E15 verdict cases hold, on an otherwise passing fixture:
    - 3 missed exits, each with cost 1.000000R (−2.003 vs −1.003) → PASS
    - 4 missed exits → FAIL, including with 120 opened and with G = 3
    - 1 missed exit costing 1.100000R → FAIL
    - ABORTED with 4 missed exits → ABORTED
- **F18.AC7 [unit]** Immediate FAIL (edge-hypothesis §5.3 F1, F2 and precedence item 2; A3.1). Either of these at or before `T_eval` records FAIL, ends the run and pauses the bot:
  - **F1:** drawdown ≥ `eval.max_dd` at any mark, on either of two curves:
    - the actual equity curve
    - the shadow equity curve, where flattened trades are replaced by their shadows and **trades with a missed exit by their stop-first (lo) mirrors**
  - **F2** (F18.AC11; A4.4, `eval_reference.py::p4_breach_time`). The **breach time** is the earliest of:
    - the leader event time of the 4th missed exit, in leader-event order (never the order in which they were ledgered)
    - for a cost > 1R, the moment it is established: the later of the trade's real close and its mirror exits, capped at `T_eval` (a side still open then is marked)
    - for an uncomputable mirror, the leader event time of its first missed exit
    - for an incomplete fill audit, the start of the unaudited stretch

    It always lies in `[t0, T_eval]`. It is reported with the time the breach was found.
  - **When it takes effect.** A breach found before `T_eval` (live or by a daily audit) records FAIL when found. A breach found after `T_eval` (by the final audit, the recomputation or the 72 h bound) is **still FAIL**, with the breach time as above, and it changes the verdict only.
  - The F2 FAIL alert states K13: "missed-exit limit: engineering failure, not evidence about the edge. Explain and fix every missed exit before run 2."
  - A missed exit that does not breach F2 leaves the run running, and never pauses entries by itself.
- **F18.AC8 [unit]** P5 downtime.
  - Downtime is the union of: `process_down`, `data_gap` before resync, `access_degraded`, `disk_low`, manual `/pause`, and deploy-wait pauses.
  - `rule_blackout` and loss halts are excluded.
  - P5 holds iff downtime < `eval.max_downtime_fraction` of `[t0, T_eval]`. At exactly 2.000%, P5 fails.
- **F18.AC9 [unit]** P2b, P6 and the flatten rule.
  - P2b: Σ net USD over S > 0.
  - P6: the replay mean R over `[t0, T_eval]` and the paper mean R over S are both > 0 or both < 0. A zero on either side fails.
  - A flattened trade uses min(realised R, shadow R), and USD P&L from the same choice. A flattened trade that also has a missed exit uses the minimum of realised, shadow and mirrored lo R (`eval_reference.gate_r`, F18.AC11).
- **F18.AC10 [unit]** Nothing gate-related before `T_eval` (edge-hypothesis §5.5, A3.2; test 7).
  - For an active run before `T_eval`, the evaluation API returns `not_before_T_eval` for:
    - the gate mean R
    - any interval, bound, standard error, t statistic or p-value of the mean of R or D, by any method
    - B0d replications, B̄_i, D_i and P2c
    - FR1–FR6, K9/S4, P6, G, the cross-day diagnostics and D6
    - the status of any gate condition, and any verdict
  - Only counts and progress are served.
  - **Never computed.** Every function in `evaluation` and `baselines` that computes any of the items above is instrumented. A simulated run fixture from `t0` to just before `T_eval` records 0 calls to them. The fixture includes `/stats` calls, daily and weekly reports, and missed exits.
    - The only computations allowed during the run are the ones the rules need live: the missed-exit mirror, gate and cost values (F12.AC9), `p4_breach` (F18.AC11), and P3 marking on both curves (F18.AC7).
  - `/stats` (F14.AC9) never calls this API. Its figures come from ledger aggregates.
- **F18.AC11 [unit]** Missed-exit rule, P4 and F2 (edge-hypothesis §5.3 "Missed-exit rules", A3.1, A4.1–A4.5; tests 21 and 25–29).
  - **Count.** The count is the number of `missed_exit` records whose leader event's exchange timestamp is in `[t0, T_eval]`. It runs over **all** trades: in S or not (trades opened after the 300th included), and including missed exits during entry pauses. A missed exit whose leader event is after `T_eval` never enters the verdict; it is still ME (F20.AC4).
  - **Costs.** For each trade with at least one missed exit whose leader event is in the window, in S or not, the incremental cost of each missed exit and the trade cost are the F12.AC9 costs (rounded half-even to 1e-6). An uncomputable mirror (after 72 h) counts as above 1R.
  - **F2** holds iff the count is > `eval.missed_exit_max_count`, **or** any incremental or trade cost, compared as the rounded Decimal, is > `eval.missed_exit_max_cost_r`, **or** a mirror is uncomputable, **or** a fill-audit stretch is incomplete after 72 h (`eval_reference.p4_breach`). Its timing is in F18.AC7. A settled-gap exit (F12.AC6) is not counted and has no cost test.
  - **Gate values.**
    - A trade in S with a missed exit enters R, D and P2b's USD sum at gate R = min(actual, mirrored lo), or the minimum of three if flattened, with the matching USD.
    - Its evaluation close (F18.AC3) drives `T_eval`, `hold_i`, merged positions, the B0d hold and P3.
    - A trade outside S never enters S's statistics, even when it counts toward F2.
  - **Verdict timing.** It follows F18.AC3 (`T_eval` + 60 s, the reconciliation pass, the final fill audit and recomputation from verified data). The wait for a pending cost or an incomplete audit is bounded at `eval.missing_data_retry_max_h` (72 h). After that the breach is F2, and the verdict is computed (F12.AC9, F12.AC10).
  - Vectors (E15 `GOLDEN_MISSED`, plus spec boundaries):
    - 3 missed exits, costs 0.200000 / 1.000000 / 0.000000 → no F2
    - 4 missed exits, costs 0 → F2 at the ledgering of the 4th
    - 1 missed exit, cost 1.100000 → F2
    - 1 missed exit, cost 1.000000 from −2.003 vs −1.003 → no F2
    - 0 missed exits → no F2
    - 1 missed exit with cost 1.000001 → F2; with cost 1.0000004 (which rounds to 1.000000) → no F2
  - Scenario fixtures (test 21):
    - trade 305, opened after the 300th, has a missed exit with a leader event before `T_eval`. It counts toward the 4 and toward the cost test, and its R never enters S.
    - a leader close at `T_eval − 10 s` that is never mirrored is found by the post-`T_eval` reconciliation pass and counted. The verdict is not computed before `T_eval + 60 s`.
    - a missed exit with a leader event at `T_eval + 1 ms` is not counted, and is listed as ME
    - a late mirror during `/pause` counts
  - **A bug never helps.** Gate R ≤ actual R on every fixture. On a fixture where a late exit beat mirroring, mean gate R over S is lower than the mean computed with actual R.
  - Scenario fixtures (A4):
    - the 4th missed exit's breach time is its leader event time even when it was ledgered before an earlier-event one
    - a breach found by the final audit after `T_eval` is FAIL
    - an uncomputable mirror breaches at its first missed exit's leader event time
    - an incomplete audit breaches at the stretch's start
    - a settled-gap exit is not counted
  - **Mutants.** Each of the E16 mutants fails at least one test, including E15 M11–M16: counting at actual R; FAIL at 3; a cost ≥ 1R failing; the cost from the stop-first mirror; an evaluation close that ignores the mirror; the cost compared without rounding. The remaining A4 mutants are listed in E16.

### F19 B0d baseline and P2c inputs (edge-hypothesis §6.2, exact)
- **Value:** the gating test that the trades beat a direction-matched, random-time baseline. This is P2c, and it is non-removable.
- **Dependencies:** F4, F11 (its fill model is reused) and F18.

- **F19.AC1 [unit]** Draws. Start times come from `rng_uint` with tag `b0d`, counters (trade index in S, replication) and uniform ms over the admissible set. The draws reproduce `eval_reference.b0d_start` for the golden seed.
- **F19.AC2 [unit]** Admissibility. A start `t` is admissible only if all of these hold:
  - the coin is listed on core throughout `[t, t + hold_i + ack]`
  - a book exists within `baseline.dm_max_book_gap_s` of the entry and time-exit fills
  - there is no mid or mark gap over `baseline.dm_max_mid_gap_s`
  - `t` is not in a blackout
  - **(A3.2 b, A4.6, `baseline.dm_exclude_downtime`)** `t` is not inside a recorded **non-discretionary** downtime interval (F18.AC8): `process_down`, `data_gap` before resync, `access_degraded` or `disk_low`
  - `t ∈ [t0, T_eval − hold_i]`

  **Discretionary pauses** (`/pause` and deploy-wait pauses) are **not** excluded from B0d draws (A4.6, `baseline.dm_discretionary_pause_rule`). Instead, for each trade B̄_i = max(mean of all draws, mean of the draws outside the discretionary pause intervals), both computed from the **same draws**. No second draw set is made. With no pause in `[t0, T_eval]`, both means are equal.

  A test with 10,000 draws finds 0 draws outside the set. Test 22: on a fixture with a 3-hour `/pause` and a 1-hour `process_down`, 10,000 draws from the full set and 10,000 from the relaxed set (F19.AC4) include 0 inside the `process_down` interval, and some inside the `/pause` interval. B̄_i on that fixture equals max(all, outside the pause) to 1e-6, and a fixture where the outside-pause mean is the lower one gives the all-draws mean.
- **F19.AC3 [simulation]** Replication. Each replication:
  - uses the same risk per trade, with its ATR stop and TP from 1h candles that closed before `t`
  - fills at the book recorded at `t + paper.ack_delay_ms`, with its own size
  - pays taker fees on both legs and hourly funding
  - exits at SL or TP (trigger on mark) or at `hold_i`; a marked trade uses the marking formula
  - takes its R from fill prices only

  Evaluation test 10: when the mid jumps X bps after every leader fill, changing X changes `R_i` and leaves every `B̄_i` unchanged, and doubling `copyreplay.delay_ms` leaves `B̄_i` unchanged.
- **F19.AC4 [unit]** Missing windows.
  - The `baseline.dm_min_admissible_hours` (24 h) test is measured with **all** downtime excluded, discretionary pauses included (A4.6). Fixture: a trade whose only admissible hours are inside a `/pause` has less than 24 h and takes the missing-window steps, although its B0d draws may fall in the pause.
  - A trade with less than `baseline.dm_min_admissible_hours` of admissible starts gets `D_i = min(R_i, 0, R_i − B̄_i^partial)`, using the 3-step chain. The step used is recorded.
  - **Relaxed set (step 2, edge-hypothesis §6.2, A3.2 b, A3.3).**
    - It is `[t0, T_eval − hold_i]`, restricted only by the listing, blackout and non-discretionary downtime conditions of F19.AC2. The B̄_i max rule for discretionary pauses applies here too.
    - Where our book or mid recording is missing, a replication uses the coin's median recorded half-spread without the ×1.5 multiplier. Failing that, it uses the major or alt value of `cost.fallback_half_spread_bps` by `cost.fallback_tier_rule` on the random-time side.
    - Its SL/TP path uses exchange 1h candles, with an ambiguous bar resolved TP first.
  - Test 23, random-time side (A4.7): a B0d, B0, B0b, B1 or B3 replication for a coin with no tier record uses the major fallback (2 bps), while a paper trade, copy replay, reconstruction or shadow of the same coin uses the alt fallback (F16.AC6). A tier-2 coin uses 8 bps on both sides.
  - When more than `baseline.dm_max_missing_share` of S (more than 30 trades) is missing a window, P2c fails.
  - This reproduces `GOLDEN_D`.
- **F19.AC5 [unit]** P2c.
  - P2c is `LB_r(D) > 0` on the same day clusters as P2, with tag `bootD`.
  - A config without `eval.baseline_gate`, or with it disabled, fails to load (non-removable, A1.4).
- **F19.AC6 [simulation]** Scale and determinism. 300 trades × `baseline.dm_reps` replications finish in ≤ 4 h on the PO's PC, and two runs give a byte-identical D vector.

### F20 Evaluation report and pre-run readiness report
- **Value:** every verdict comes with its go-live blockers and diagnostics, and the PO gets the pre-run kill checks before run 1.
- **Dependencies:** F16, F18 and F19.

- **F20.AC1 [unit]** The `T_eval` report contains all of the following:
  - **Verdict:** the verdict; each of P1–P6, P2b and P2c with its value; `LB_r`, `UB_r` and all three intervals for R and D; n and G.
  - **Secondary statistics:** S2, S3 (B0), S4 (B1, top 9 by raw ROI), S5, S6 (weekly blocks), R_maxrisk, FR1–FR6, K9 and the D6 checks.
  - **Execution:** decay(Δ) and edge lost per second, latency p50/p95/p99 per stage, mirror fidelity, and the exit-reason mix.
  - **Baseline detail:** the B0d mean (B̄_i as the max rule of F19.AC2), and the count of missing windows by step. For B0d, B0, B0b, B1 and B3, a coin with no tier record is a major (A4.7).
  - **Cross-day diagnostics:** the KM median hold, the midnight-crossing share, and the overlap-component CI with G_ov (labelled "degenerate" below 5, and "P2 fragile" when applicable).
  - **Flattened and marked trades:** the flattened count with realised-minus-shadow R, and the marked trades' later outcomes.
  - **Missed exits (A3.1, A4.1–A4.5):**
    - the count in the window against `eval.missed_exit_max_count`
    - every missed exit, in the window and after it, with: missed-exit ID, share ID, leader, coin, class, lag, actual R, mirrored lo R, mirrored hi R, gate R, incremental cost, the trade cost, and whether it is in the window
    - **how it was found:** live, reconciliation, or the daily or final fill audit
    - every **uncomputable mirror**, with the candle or stretch that was missing
    - the **P4 breach time** and **when it was found**, if any
    - the **fill-audit coverage per leader:** audited intervals, retries, and any unaudited stretch
    - every **settled-gap exit**, with its actual R and mirrored lo R
    - every mirror or shadow fill **priced from candles**, with the candle used (1m or 1h, its hash reference)
    - the total change in ΣR over S caused by the min(actual, mirrored lo) rule
  - **Outside S:** trades after the 300th, shown separately.
  - **Other baselines:** B0b, B2, B3 and B4, plus the shadow mean R labelled exploratory (H3).
- **F20.AC2 [unit]** Fragility boundaries.
  - FR1: without the top 5 R trades, mean ≤ 0.
  - FR2: without the leader with the largest ΣR, mean ≤ 0.
  - FR3: `mean(R_i − c_i)` ≤ 0.
  - FR4: win rate > 70% **and** payoff < 0.5.
  - FR5: mean R_maxrisk ≤ 0.
  - FR6: drop the day with the largest ΣR (earliest on a tie), then mean ≤ 0.

  Each fires at its boundary and not one step inside it.
- **F20.AC3 [unit]** D6 (edge-hypothesis §8.2). The check flags D6 when any of these holds:
  - decision agreement < `d6.min_decision_agreement`
  - median |ΔR| > `d6.max_median_abs_r_diff`
  - |mean ΔR| > `d6.max_mean_r_diff`
  - fill deviation median > `d6.max_median_fill_dev_bps` or p90 > `d6.max_p90_fill_dev_bps`
  - trade-count deviation > `d6.max_trade_count_dev`
- **F20.AC4 [unit]** Blocked PASS and go-live blockers (edge-hypothesis §5.6 ME, §7 K13; A3.1).
  - A PASS with any of K9/S4, FR1–FR6 or D6 triggered, **or with at least one missed exit** in the run, is headed `PASS: live blocked pending PO review of <items>`. Missed exits are listed as `ME <missed-exit ID> (share <share ID>): explain and fix`.
  - **ME.** Every missed exit of the run is listed as open go-live blocker ME, including those after `T_eval`. It appears in every `T_eval` report whatever the verdict, and in a blocker report written when a run ends FAIL or ABORTED before `T_eval`.
    - A PO review alone does not clear an ME. Clearing happens at /go-live, and needs both:
      - a written root cause in the verdict report
      - the fix merged with a regression test that reproduces the missed exit and now passes
    - The report offers no field or flag that clears one. A `missed_exit_resolution` record (F17.AC9) is shown next to its ME, but does not clear it.
  - **K13.** A FAIL by F2 is headed `FAIL (F2): missed-exit limit. Engineering failure, not evidence about the edge (K13). Explain and fix every missed exit before run 2; run 2 is judged at 99%.`
- **F20.AC5 [simulation]** Readiness report. It is built from the dry run, ≥ 7 days of recording, and the point-in-time replay. It states:
  - the recorder gap rate per coin, and the projected share of trades without an admissible B0d window
  - K1 (`kill.k1_min_trades`), K2 (`kill.k2_min_trades`), K6, K7 and K8, each as `triggered`, `not triggered` or `not evaluable (n = x)`
  - the latency summary (§4)
  - the tier table in force, with each coin's depth, volume and tier, and the tier-1, tier-2 and below-floor counts (F9.AC7)
  - archive health: compressed GB per day (mean and max), days archived and verified, local window size, the last verified ledger backup, and the projected monthly storage cost (F23)
- **F20.AC6 [simulation]** Reproducibility and honesty.
  - Regenerating either report from the same ledger gives byte-identical output.
  - Removing any trade record from the fixture changes the output. No outcome-based exclusion exists.

### F21 Integration, supervisor, 24h dry run and latency measurement
- **Value:** the whole pipeline runs unattended on the PO's Windows PC, proven by a 24h dry run and a 1-day latency measurement.
- **Dependencies:** F1–F20 and F23.

- **F21.AC1 [integration]** Supervisor.
  - One command starts every component in paper mode on Windows 10/11.
  - A ledger heartbeat is written every `ledger.heartbeat_interval_s`.
  - A crashed component restarts after `supervisor.restart_delay_s`.
  - More than `supervisor.max_restarts_per_hour` restarts in an hour means: stay down with opens refused, and alert.
  - A heartbeat gap over `feed.stale_after_s` (sleep, wake or freeze) is ledgered as downtime and triggers a resync.
- **F21.AC2 [simulation]** 24h dry run. The full pipeline runs in dry-run mode on live mainnet data for ≥ 24 h continuous, with:
  - 0 unhandled exceptions, 0 missed exits and 0 ledger verification failures
  - downtime < 2%
  - every Telegram command answered
  - process RSS at hour 24 ≤ 1.2 × RSS at hour 1
  - compressed recording written for the 24 h ≤ `recording.max_gb_per_day`
  - at least one finished UTC day archived and verified (F23.AC1) and one ledger backup verified (F23.AC4)

  0 missed exits is deliberately stricter than the run rule (F18.AC11): any missed exit in the dry run is a bug to fix before run 1.
- **F21.AC3 [simulation]** Latency measurement.
  - It runs for ≥ `latency.measure_hours` on the PO's connection, with n ≥ `latency.min_signals` signals, clock-offset corrected.
  - It reports p50/p95/p99 for each §4 stage, and the share of signals older than 1, 2, 3 and 5 s at decision.
  - If n is below `latency.min_signals`, the measurement is extended until it is reached.
- **F21.AC4 [integration]** No inbound surface (E4). The running engine opens 0 listening sockets, as a socket enumeration test confirms. Telegram uses outbound polling.
- **F21.AC5 [integration]** The full test suite passes on Windows 10/11 with the pinned Python and lockfile.

### F22 OKX lead-trader recorder (record-only, lowest priority)
- **Value:** collects fallback candidate data for a later epic, with no effect on the pre-registered run (H1 is Hyperliquid wallets only).
- **Dependencies:** F2.

- **F22.AC1 [integration]** With `okx.enabled` = true, public lead-trader endpoints are polled every `okx.poll_interval_s` and stored point-in-time.
- **F22.AC2 [unit]** OKX data never produces a signal, score, share or trade. A static import test and a runtime test confirm it.
- **F22.AC3 [unit]** Failure case: an endpoint error backs off and sends ≤ 1 alert per day, with 0 effect on any other component.

### F23 Recording archive, cloud offload and ledger backup (A10)
- **Value:** recording fits on the PO's ~100 GB of free disk, run data gets an off-site copy, and replay, B0d and evaluation still see every recorded day. Storage costs ≤ $5/month.
- **Dependencies:** F1 and F2, plus F4's day-partitioned files and store interface (F4.AC3, F4.AC7). The bucket is any S3-compatible store (Backblaze B2 or Cloudflare R2), reached over outbound HTTPS only.
- **Split rationale:** F4 was too big for one developer with this added. F4 keeps writing and the disk guard; F23 owns everything after a day is complete.

- **F23.AC1 [integration]** Daily upload and verification.
  - After a UTC day is `day_complete` (F4.AC7), every recording and leaderboard file for that day is uploaded, followed by a day manifest listing each object's path, bytes and sha256. The manifest goes last.
  - **(A3.4, A4.8 a)** Each object is verified by reading it back and comparing **both hashes** (the stream sha256 and the transport sha256) with the file's ledger record (F4.AC7) and with the manifest. A store-side checksum alone is not enough.
  - A day becomes `archived` only when every object and the manifest verify. The ledger then gets `archive_verified` with the day and the manifest sha256.
  - Against an S3-compatible stub, a 1-day fixture is archived with 0 mismatches. With a stub that corrupts one object, the day stays not archived, the object is re-uploaded, and one alert is sent.
  - A normal day is archived ≤ `storage.upload_deadline_h` after 00:00 UTC.
- **F23.AC2 [integration]** Pruning (D2).
  - A local day is deleted only when it is `archived` **and** older than the newest `storage.local_retention_days` finished days.
  - A day that is not archived is never deleted, whatever its age and whatever the free disk.
  - **(A3.4)** Deletion is also guarded per file. The only delete primitive for recordings refuses any local file whose ledger sha256 has no matching `archive_verified` read-back.
    - A direct call on an unverified file is refused and logged, and the file remains (test 24).
    - A static test finds no other code path that deletes files under `storage.recordings_dir`.
  - The engine never deletes or overwrites a verified object, and never changes bucket lifecycle rules. The stub records 0 such calls over the whole test suite.
  - Fixture: 10 finished days, with days 1 and 2 not archived and retention 7. After pruning, days 1, 2 and 4–10 are local, and day 3 is deleted.
- **F23.AC3 [simulation]** Transparent reads.
  - Replay (F16), B0d (F19), evaluation and reports (F18, F20), reconstruction (F13) and tier computation (F9) read recordings through one store interface. It serves local files first; otherwise it tries **every ledgered destination, newest first** (F23.AC5), downloading the day into `storage.cache_dir`, verifying each object against the day manifest and both ledger hashes, then serving it.
  - The cache is bounded by `storage.cache_max_gb`, with least-recently-used eviction, and never evicts a file in use.
  - Reading a 3-day fixture through the interface gives byte-identical records whether the days are local or only in the archive.
  - End to end, once F16 and F19 exist (run in F21's integration suite): a 3-day replay run once fully local and once with all 3 days only in the archive gives byte-identical ledgers. The same holds for a B0d D vector (F19.AC6).
  - The point-in-time rule (F4.AC3) holds for archived data.
  - **Verified on every read (A3.4, A4.8 a).** Every read through the store interface verifies **both** the stream sha256 and the transport sha256 of the file against its ledger record (F4.AC7), whether the file is local or downloaded. Recomputation of verdict values uses only verified reads (A4.8 c, F18.AC3).
  - **Lost file (failure case, A3.4, A4.8; test 24).**
    - If the local copy fails its hash, every ledgered destination is tried, newest first. A downloaded object that fails is downloaded again for up to `storage.read_retry_max_min`. A copy that fails a hash is never used.
    - A file is **lost** when no copy matching its ledger hashes exists: it is absent locally and every ledgered destination answers "not found", or every copy fails its hash.
    - A lost file is ledgered once as `recording_file_lost` (path, day, expected sha256, reason), and one alert is sent.
    - From then on, every reader treats the file's time span as a gap in our recording: B0d admissibility (F19), the 1h-candle fallback for shadows and mirrors (F12.AC7, F12.AC9), the replay (F16), tier coverage (F9.AC7) and the gap statistics (F4.AC4).
    - A lost file is never replaced by re-recording, by another data source, or by a copy that doesn't match its hash.
    - Fixture: a day with one file whose bytes are altered in both copies is read as a gap by B0d, a mirror and the replay, with exactly one `recording_file_lost` record.
  - **Archive unreachable** (connection errors or timeouts, as opposed to "not found"). A read that needs a non-local day retries for `storage.read_retry_max_min`, then the batch job exits non-zero naming the day. It never proceeds with the day missing, and an unreachable file is never declared lost.
- **F23.AC4 [integration]** Ledger backup.
  - Daily at `storage.ledger_backup_time_utc`, the ledger is backed up to the bucket, fully or incrementally since the last verified backup.
  - It is encrypted on the PC with authenticated encryption, using a key from the environment, before upload. It is then verified by checksum, and `ledger_backup_verified` is ledgered with the head sequence number and head hash.
  - The uploaded bytes contain 0 occurrences of a canary record string planted in the ledger.
  - **Restore drill:** `archive restore-ledger --to <dir>` rebuilds a ledger that verifies (F2.AC1) with the same head sequence number and hash as the backup record.
  - A backup with a wrong key or a tampered object fails to restore with an error; it never yields a partial ledger.
- **F23.AC5 [unit]** Credentials and transport (E2, abuse case).
  - The endpoint, bucket, key ID, secret key and backup encryption key come only from the environment (F1.AC5). With canary values, 0 occurrences appear in logs, the ledger, Telegram payloads, exception traces, object names or object metadata.
  - A non-HTTPS endpoint fails config validation.
  - **Destination changes (A4.8 d).** The archive destination (endpoint and bucket) is outside the config hash. A change is written to the ledger as `archive_destination_changed` with the time, the old and new destination (never credentials), and the reason. It is **not** a config change and **not** a deploy, so it never makes a run ABORTED and needs no ruling. The reason is that the destination changes where copies live, and every read is verified against the ledger hashes, so it cannot change any value. Retention, cache size and upload timings (`storage.local_retention_days`, `storage.cache_max_gb`, `storage.upload_delay_min`, `storage.upload_deadline_h`) **stay in the config hash**. Fixture: changing the bucket mid-run leaves the config hash and the run running, writes one ledger record, and reads then try the new destination first and the old one after it. Changing `storage.local_retention_days` mid-run is ABORTED (F17.AC4).
  - With any credential missing: recording continues locally, nothing is uploaded or pruned, one alert is sent per `storage.alert_interval_h`, `/status` shows `archive: not configured`, and `run start` refuses (F17.AC2).
- **F23.AC6 [integration]** Upload failure and backlog (failure case).
  - On an upload or verification failure, local data is kept, the upload is retried every `storage.retry_interval_min`, and one alert is sent per `storage.alert_interval_h` stating the backlog in days and GB.
  - Recording continues. Only the disk floor (F4.AC5) stops it.
  - Gaps caused by a floor stop count in the recorder gap statistics (F4.AC4) and in B0d admissibility under edge-hypothesis §14 item 8. They are never back-filled with synthetic data.
  - Trading, exits and the ledger are unaffected by any archive failure.
- **F23.AC7 [unit]** Storage budget.
  - Once a day, the projected monthly cost is computed as stored GB × `storage.price_usd_per_gb_month` + the month's operation count × `storage.price_usd_per_10k_ops` / 10,000. It is ledgered and shown in `/status` and the daily report.
  - When the projection reaches `storage.budget_alert_fraction` × `storage.monthly_budget_usd`, one alert per day is sent. Uploads continue (Assumption A21).
  - Fixture: 60 GB at $0.006/GB-month plus 100,000 operations at $0.004 per 10,000 → $0.40. At 700 GB → $4.24, which trips the 0.8 × $5 = $4.00 alert.

---

## 3. Config table

**Rules.**
- Every key must be present, because there are no code defaults (F1.AC1).
- **Max** is a hard ceiling compiled into code. Where safety needs a floor, **Min** is a hard floor, as for fees.
- "fixed" means Min = Max = Default.

**Source codes.**

| Code | Source |
|---|---|
| PO | `decisions.md` or `03-answers.md` |
| EH§ | `edge-hypothesis.md` |
| MC | `market-context.md` |
| BR | `brainstorm-domain-research.md` |
| BRF | `01-brief.md` |
| HL | exchange limit |
| PM | this spec, with an assumption ref where one applies |

**Flags.**

| Flag | Meaning |
|---|---|
| **FROZEN** | Pre-registered. It can change only by addendum before a run. |
| **CAL** | Calibrate once on pre-paper recorded data, then freeze before run 1. |
| **OF** | A prior; overfitting risk. Never tuned on paper-run data. |
| **VAL-S** | Validate with the PO's `hl_sample.py` `summary.json` (not yet available). |
| **VAL-L** | Validate with the 1-day latency measurement (F21.AC3). |
| **VAL-R** | A prior. Validate against ≥ 7 days of our own recordings (shown in the readiness report, F20.AC5) and adjust before the config is frozen for run 1. |

### 3.1 Platform, storage, supervisor
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `mode` | Trading mode | enum | paper | paper | paper (live/testnet refused in this epic) | PO, A10 |
| `storage.ledger_dir` | Ledger location, outside any worktree | path | required | – | – | PM (EH 5.1 A2.2) |
| `storage.recordings_dir` | Recordings location, outside any worktree | path | required | – | – | PM |
| `storage.cache_dir` | Download cache for archived days, outside any worktree | path | required | – | – | PM (A10) |
| `storage.upload_delay_min` | Wait after 00:00 UTC before a day is closed and uploaded | min | 15 | 5 | 120 | PM (A10) |
| `storage.upload_deadline_h` | A normal day is archived within this after 00:00 UTC | h | 6 | 1 | 24 | PM (A10) |
| `storage.local_retention_days` | Rolling window of finished days kept locally | days | 7 | 2 | 30 | PO (A10) |
| `storage.max_unarchived_days` | `run start` refuses if an older finished day is not archived | days | 2 | 1 | 7 | PM (A21) |
| `storage.cache_max_gb` | Download cache size | GB | 20 | 2 | 50 | PM (A10) |
| `storage.read_retry_max_min` | Retry window for an archive read before the batch job fails | min | 30 | 1 | 240 | PM |
| `storage.retry_interval_min` | Upload and backup retry period | min | 15 | 1 | 120 | PM |
| `storage.alert_interval_h` | Throttle for archive and backup alerts | h | 6 | 1 | 24 | PM |
| `storage.ledger_backup_time_utc` | Daily encrypted ledger backup | HH:MM | 00:30 | – | – | PM (A10) |
| `storage.monthly_budget_usd` | Object-storage budget | USD/month | 5 | 0 | 5 | PO (A10) |
| `storage.budget_alert_fraction` | Projected cost share that alerts | fraction | 0.8 | 0.1 | 1.0 | PM (A21) |
| `storage.price_usd_per_gb_month` | Provider storage price, for the projection | USD/GB-month | 0.006 (B2; 0.015 if R2) | > 0 | – | PM (A10) |
| `storage.price_usd_per_10k_ops` | Provider operation price, for the projection | USD | 0.004 | 0 | – | PM (A10) |
| `clock.offset_interval_s` | Clock-offset re-estimation period | s | 600 | 60 | 3600 | PM (B2) |
| `clock.max_offset_uncertainty_ms` | Above this, entries pause | ms | 100 | 10 | 500 | PM · VAL-L |
| `clock.max_estimate_age_s` | Maximum age of the offset estimate | s | 1800 | 600 | 3600 | PM |
| `ledger.heartbeat_interval_s` | Liveness heartbeat | s | 10 | 1 | 60 | PM |
| `supervisor.restart_delay_s` | Delay before restarting a crashed component | s | 30 | 5 | 120 | PM |
| `supervisor.max_restarts_per_hour` | Restart cap before staying down | count | 5 | 1 | 10 | PM |

### 3.2 Hyperliquid client and feeds
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `hl.rest_weight_budget_per_min` | Our REST weight budget | weight/min | 900 | 100 | 1100 (HL limit 1,200) | MC 2.3 |
| `hl.scoring_weight_share` | Share of the budget available to scoring | fraction | 0.5 | 0.1 | 0.8 | MC 2.3 |
| `hl.weight_userRole` / `hl.weight_portfolio` | Assumed weights | weight | 60 / 20 | 20 / 20 | – | EH E8 |
| `hl.rest_timeout_s` | REST timeout | s | 10 | 2 | 30 | PM |
| `hl.retry_max` | Retries per request | count | 5 | 0 | 8 | PM (B4) |
| `hl.backoff_base_s` / `hl.backoff_max_s` | Exponential backoff range | s | 1 / 60 | 1 / 10 | 10 / 300 | PM |
| `hl.ws_max_unique_users` | Distinct WS users | users | 10 | 1 | 10 (HL) | MC 2.3 |
| `hl.ws_max_new_conns_per_min` | New WS connections | per min | 20 | 1 | 30 (HL) | MC 2.3 |
| `hl.ws_ping_interval_s` | Ping cadence | s | 20 | 5 | 50 | PM (MC: heartbeat unconfirmed) |
| `hl.ws_reconnect_backoff_max_s` | Maximum reconnect backoff | s | 30 | 5 | 120 | BR |
| `feed.stale_after_s` | No message → stale; entries pause | s | 30 | 5 | 60 | BR · VAL-L |
| `access.degraded_error_count` | 403/451 count that trips `access_degraded` | count | 3 | 1 | 20 | PM (PO K10) |
| `access.degraded_window_min` | Detection window | min | 5 | 1 | 30 | PM |
| `access.degraded_min_success_rate` | Below this → degraded | fraction | 0.5 | 0.1 | 0.9 | PM |
| `access.recover_min` | Healthy minutes needed to clear | min | 10 | 1 | 60 | PM |
| `follow.clearinghouse_poll_s` | Leader account-value poll | s | 60 | 10 | 300 | PM |
| `follow.max_leader_av_age_s` | Oldest leader account value usable for sizing | s | 300 | 60 | 900 | PM |

### 3.3 Recorder
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `recording.markets` | Recorded markets | list | core + HIP-3 | – | – | PO |
| `recording.max_coins` | Recording universe cap | coins | 250 | 10 | 400 | PM (A10; 1,000 subscriptions per IP) |
| `recording.universe_lookback_days` | Coins traded by followed or candidate wallets in the last N days | days | 30 | 7 | 90 | PM |
| `recording.l2_levels` | Book levels per side | levels | 10 | 5 | 20 | PM (A10) |
| `recording.l2_interval_ms` | Minimum L2 snapshot rate | ms | 2000 | 500 | 4000 (must stay < 5 s B0d rule) | PM |
| `recording.asset_ctx_interval_s` | Mark/oracle/funding/OI cadence | s | 60 | 10 | 300 | MC 5 |
| `recording.leaderboard_interval_min` | Leaderboard snapshot period | min | 60 | 15 | 60 | PO |
| `recording.disk_check_interval_s` | Free-disk check period | s | 60 | 10 | 300 | PM (A10) |
| `recording.disk_alert_free_gb` | Free-disk alert threshold; must exceed the floor | GB | 20 | 6 | – | PM (A10) |
| `recording.disk_floor_free_gb` | Hard floor: recording stops, opens and adds refused; room kept for the ledger | GB | 8 | 5 (hard floor) | – | PM (A10, A18) |
| `recording.disk_resume_margin_gb` | Free space above the floor needed to resume recording | GB | 2 | 1 | 20 | PM |
| `recording.max_gb_per_day` | Compressed recording budget, checked in the 24h dry run | GB/day | 1.5 | 0.1 | 5 | PM (A10) · VAL-R |
| `recording.segment_hash_minutes` | Period of the hash-chained segment record; data not covered by a ledgered hash is a gap (F4.AC7) | min | 5 | fixed | fixed | EH A4.8 b · FROZEN |
| `recording.candle_store` | Hourly store of 1m and 1h exchange candles for every coin with an open share, shadow or mirror, hashed like recordings (F4.AC9) | enum | hourly_1m_1h_hashed | fixed | fixed | EH A4.2 · FROZEN |

### 3.4 Scoring and selection (EH §9.1, §10)
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `scoring.candidates_k` | Candidates scored | wallets | 200 | 50 | 500 | BRF · VAL-S |
| `scoring.interval_min` | Scoring cycle | min | 60 | 15 | 1440 | BRF |
| `scoring.window_days` | Fill window | days | 180 | 90 | 365 | BR · OF |
| `scoring.dsr_min_daily_days` | Minimum daily-resolution days (T) | days | 60 | 30 | – | EH · OF |
| `scoring.stale_input_mult` | Input older than mult × interval → ineligible | × | 2 | 1 | 4 | EH 10.1 |
| `gate.min_account_age_days` | G1 | days | 180 | 90 | – | BR · OF |
| `gate.min_round_trips` | G2 | count | 150 | 50 | – | BR · OF · VAL-S |
| `gate.min_fill_span_days` | G3 | days | 60 | 30 | – | EH · OF · VAL-S |
| `gate.min_positive_blocks` / `gate.n_blocks` / `gate.block_days` | G4 | count / count / days | 4 / 6 / 30 | 1 / 2 / 7 | n_blocks / 12 / 90 | EH · OF |
| `gate.max_drawdown` | G5 | fraction | 0.35 | 0.05 | 0.50 | BR · OF |
| `gate.min_profit_factor` | G6 | ratio | 1.3 | 1.0 | – | BR · OF |
| `gate.min_dsr_prob` | G7 | prob | 0.95 | 0.50 | 0.99 | BR |
| `gate.dsr_n_trials` | DSR trial count | count | 15000 | = `scoring.candidates_k` | – | MC 2.1 |
| `gate.min_median_hold_min` | G8 floor | min | 15 | 5 | – | BR · OF · VAL-S |
| `gate.hold_latency_mult` | G8: hold ≥ mult × p95 latency | × | 20 | 5 | – | BR · VAL-L |
| `gate.max_top_trade_share` | G9 | fraction | 0.25 | 0.05 | 1.0 | BR · OF |
| `gate.max_top_asset_share` | G9 | fraction | 0.50 | 0.10 | 1.0 | BR · OF |
| `gate.min_copy_edge_ratio` | G10 | ratio | 3.0 | 1.0 | – | BR · OF |
| `gate.min_account_value_usd` | G11 | USD | 10000 | 1000 | – | EH · OF · VAL-S |
| `gate.min_executable_share` | G12 | fraction | 0.50 | 0.10 | 1.0 | EH · OF · VAL-S |
| `gate.max_maker_share` | G13 | fraction | 0.70 | 0.10 | 1.0 | EH · OF · VAL-S |
| `gate.max_current_drawdown` | G15 | fraction | 0.20 | 0.05 | 0.50 | EH · OF |
| `gate.exclude_roles` | G13 roles | list | vault, agent, missing | – | – | EH |
| `gate.exclude_addresses` | G13 addresses | list | [HLP vault address] | – | – | EH |
| `blowup.max_adds_while_losing_share` / `blowup.min_adds` | BU1 | fraction / count | 0.20 / 10 | 0 / 1 | 1 / – | BR · OF |
| `blowup.max_size_after_loss_ratio` / `blowup.min_each` | BU2 | ratio / count | 1.5 / 20 | 1.0 / 5 | – | EH · OF |
| `blowup.skew_win_rate` / `blowup.skew_loss_mult` | BU3 | fraction / × | 0.85 / 3.0 | 0.5 / 1 | 1 / – | BR · OF |
| `blowup.max_worst_to_median_loss` / `blowup.min_losses` | BU4 | ratio / count | 10 / 10 | 2 / 3 | – | BR · OF |
| `blowup.hidden_dd_mult` / `blowup.hidden_dd_floor` | BU5 | ratio / fraction | 2.0 / 0.15 | 1 / 0 | – / 1 | EH · OF |
| `blowup.max_median_eff_leverage` | BU7 | × | 10 | 1 | 50 | EH · OF |
| `blowup.max_open_unrealized_loss` | BU8 | fraction of account value | 0.10 | 0.01 | 1.0 | EH · OF |
| `blowup.any_liquidation` | BU6 | bool | true | – | – | EH |
| `score.weights` | dsr_excess, copy_mean_r, pos_blocks, max_dd, recent_sr, executable | each 0–1, Σ = 1 | 0.30, 0.25, 0.15, 0.15, 0.10, 0.05 | 0 each | 1 each | EH · OF |
| `score.anchors` | lo/hi per component (EH 10.4) | mixed | 0/0.15; 0/0.30R; 0.5/1.0; 0.35/0.05; 0/0.30; 0.5/1.0 | lo ≠ hi | – | EH · OF |
| `score.shrink_k_trades` | Shrinkage of copy_mean_r | trades | 100 | 0 | – | EH · OF |
| `score.shrink_k_days_recent` | Shrinkage of recent_sr | days | 30 | 0 | – | EH · OF |
| `select.join_rank` / `select.drop_rank` | Hysteresis | rank | 8 / 15 | 1 / join + 1 | – | BRF · OF |
| `select.join_confirm_cycles` / `select.drop_confirm_cycles` | Confirmations | cycles | 2 / 2 | 1 / 1 | 6 / 6 | EH |
| `select.min_follow_hours` | Minimum follow before a rank drop | h | 24 | 1 | – | BRF |
| `select.min_followed` | Target minimum followed | count | 5 | 1 | = max_followed | BRF · VAL-S |
| `select.max_followed` | Followed wallets | count | 9 | 1 | 9 (WS users − 1) | PO |
| `select.backfill_max_hours` | Initial backfill deadline | h | 24 | 1 | 48 | PO |
| `select.swap_margin` | Score margin for a swap | score units | 0.10 | 0 | 1 | EH · OF |
| `select.max_swaps_per_cycle` | Swaps per cycle | count | 1 | 0 | 1 | EH |
| `select.max_cycle_duration_min` | Longer cycle → keep the previous set | min | 45 | 10 | = interval | PM |
| `leader_pause.max_copy_dd` | Leader pause: copy drawdown | fraction of the leader allocation | 0.10 | 0.02 | 0.50 | BR · OF |
| `leader_pause.max_consec_losses` | Leader pause: consecutive copy losses | count | 5 | 2 | 20 | BR · OF |
| `risk.leader_allocation_fraction` | Leader allocation, the base of `max_copy_dd` | fraction of equity | 0.30 | 0.05 | 0.50 | BR (per-leader 30%) |
| `copyreplay.delay_ms` | Copy-replay delay | ms | measured p95, else 3000 | 250 | 5000 | EH · CAL · VAL-L |
| `copyreplay.half_spread_bps` | Copy-replay spread fallback, major / alt by `cost.fallback_tier_rule` (§1, EH A3.3) | bps | recorded, else 2 / 8 | 2 / 8 (floor) | – | EH · CAL |

### 3.5 Markets, filter, calendar
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `markets.allowed_dexes` | Tradable dexes | list | core | core | core (fixed) | PO · FROZEN |
| `tiers.lookback_days` | Recorded window for the tier metrics | days | 7 | 3 | 30 | PM (A6) · VAL-R |
| `tiers.recompute_interval_h` | Tier recompute period. During a run the cadence is 24 h (EH A4.7); each table is ledgered and in force from its ledger time (F9.AC8). See Assumption A26 | h | 24 | 1 | 168 | PM (A6) · EH A4.7 |
| `tiers.max_age_h` | Oldest usable tier table outside a run, and at run start | h | 48 | 2 | 336 | PM (A6) |
| `tiers.depth_band_pct` | Band around mid for the depth metric | % | 0.5 | 0.1 | 2.0 | PM (A6) · VAL-R |
| `tiers.tier1_min_depth_usd` | Tier 1: median min-side depth within the band; must be ≥ the floor value | USD | 1,000,000 | = floor value | – | PM (A6) · VAL-R · OF |
| `tiers.tier1_min_volume_usd` | Tier 1: median 24h notional volume; must be ≥ the floor value | USD | 200,000,000 | = floor value | – | PM (A6) · VAL-R · OF |
| `tiers.floor_min_depth_usd` | Tradable floor: median min-side depth within the band | USD | 50,000 | 20,000 (hard floor) | – | PM (A6) · VAL-R · OF |
| `tiers.floor_min_volume_usd` | Tradable floor: median 24h notional volume | USD | 10,000,000 | 2,000,000 (hard floor) | – | PM (A6) · VAL-R · OF |
| `tiers.min_coverage_fraction` | Recorded coverage of the lookback needed to be tiered | fraction | 0.8 | 0.5 | 1.0 | PM (A6) |
| `filter.max_signal_age_ms` | Signal age cut-off | ms | 5000 | 500 | 5000 | PO D7 · VAL-L |
| `filter.max_slippage_pct_tier1` | Adverse slippage vs the leader fill, tier 1 | % | 0.30 | 0.05 | 0.30 | PO D7, A6 |
| `filter.max_slippage_pct_tier2` | Same, tier 2 | % | 0.80 | 0.10 | 0.80 | PO D7, A6 |
| `filter.max_spread_pct_tier1` | Spread, tier 1 | % | 0.10 | 0.01 | 0.30 | BR · CAL |
| `filter.max_spread_pct_tier2` | Spread, tier 2 | % | 0.30 | 0.02 | 0.80 | BR · CAL |
| `filter.max_depth_share` | Order / depth within the band | fraction | 0.01 | 0.001 | 0.05 | BR |
| `filter.depth_band_pct` | Depth band around mid | % | 0.5 | 0.1 | 2.0 | BR |
| `filter.max_price_age_ms` | Book or mark staleness | ms | 2000 | 250 | 5000 | BR (B1) |
| `filter.vol_window_h` | Realised-vol window | h | 24 | 4 | 72 | PM · CAL |
| `filter.vol_lookback_days` | Percentile lookback, 1h candles | days | 90 | 30 | 200 (candle cap) | PM · CAL |
| `filter.vol_halving_percentile` | Size-halving threshold | percentile | 90 | 50 | 99 | PO D10 · PM · CAL · OF |
| `filter.vol_size_mult` | Size multiplier in high vol | × | 0.5 | 0.1 | 1.0 (never raises size) | PO D10 |
| `filter.trend.mode` | Trend rule | enum | record_only | – | – | PM (A5) · CAL |
| `filter.trend.ema_period_h` | Trend EMA on 1h | h | 50 | 10 | 200 | PM · CAL · OF |
| `filter.trend.min_aligned_atr` | Veto if (close − EMA)·dir / ATR < x | ATR | unset (record_only) | −5 | 5 | PM · CAL · OF |
| `filter.funding.mode` / `filter.funding.max_adverse_rate_per_h` | Funding-extreme rule | enum / fraction per h | record_only / unset | – / 0 | – / 0.04 | MC 4 · CAL · OF |
| `filter.oi_drop.mode` / `filter.oi_drop.max_drop_pct_24h` | OI-collapse rule | enum / % | record_only / unset | – / 5 | – / 90 | MC 4 · CAL · OF |
| `filter.premium.mode` / `filter.premium.max_abs_pct` | Mark–oracle premium rule | enum / % | record_only / unset | – / 0.05 | – / 10 | MC 4 · CAL · OF |
| `shadow.enabled` | Shadow outcomes for refused opens | bool | true | – | – | BRF (H3) |
| `calendar.file` | Macro calendar data input | path | `data/inputs/macro_calendar` | – | – | BRF |
| `calendar.timezone` | Event time zone | tz | America/New_York | fixed | fixed | MC 3.1 |
| `calendar.blocking_classes` | Classes that block | list | FOMC, CPI, PCE, NFP | – | – | PO |
| `calendar.window_fomc_min` | Before / after an FOMC decision | min | −30 / +60 | 0 | 240 | PO D10 |
| `calendar.window_tier1_min` | Before / after CPI, PCE, NFP | min | −15 / +30 | 0 | 240 | PO D10 |
| `calendar.min_coverage_days` | Required forward coverage | days | 67 | 67 | 120 | PM (60 + 7-day run cap) |

### 3.6 Risk, sizing, exits
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `risk.per_trade_fraction` | Initial risk per share | fraction of equity | 0.005 | 0.001 | 0.01 | PO · FROZEN |
| `risk.max_share_risk_fraction` | Share open risk after adds | fraction of equity | 0.01 | 0.005 | 0.02 | PM (A7) |
| `risk.max_total_open_risk_fraction` | Portfolio open risk | fraction of equity | 0.05 | 0.005 | 0.10 | PM (A7) |
| `risk.max_symbol_open_risk_fraction` | Per-coin open risk | fraction of equity | 0.015 | 0.005 | 0.03 | BR |
| `risk.max_btc_bucket_open_risk_fraction` | BTC-correlated, same direction | fraction of equity | 0.03 | 0.005 | 0.05 | BR |
| `risk.btc_bucket_corr_threshold` | Bucket membership | correlation | 0.6 | 0.3 | 0.9 | PM (A7) |
| `risk.btc_bucket_corr_window_days` | Correlation window, 1h returns | days | 30 | 7 | 90 | PM |
| `risk.max_leader_open_risk_fraction` | Per-leader open risk | fraction of equity | 0.015 | 0.005 | 0.03 | BR (30% of total) |
| `risk.max_open_positions` | Concurrent merged positions | count | 10 | 1 | 10 | BRF |
| `risk.max_position_notional_equity_mult` | Notional per merged position | × equity | 1.0 | 0.1 | 3.0 | PM (A3) |
| `risk.leverage_min` | Lowest leverage tried by the automatic choice | × | 1 | 1 | 3 | PO (A2) |
| `risk.max_leverage_alt` | Ceiling for coins not in the high-leverage list | × | 5 | 1 | 5 | PO D3, A2 |
| `risk.max_leverage_high_tier` | Ceiling for coins in `risk.high_leverage_coins` | × | 10 | 1 | 10 | PO D3, A2 |
| `risk.high_leverage_coins` | Coins allowed up to the high-tier ceiling | list | BTC, ETH, SOL | – | subset of {BTC, ETH, SOL} (compiled) | PO (A2) |
| `risk.min_liq_distance_stop_mult` | Liquidation distance ≥ mult × stop distance, every share | × | 3 | 3 (hard floor) | – | PO (A2) |
| `risk.daily_loss_limit` | Daily halt | fraction of opening equity | 0.02 | 0.005 | 0.05 | PO D6 |
| `risk.weekly_loss_limit` | Weekly halt | fraction of opening equity | 0.05 | 0.01 | 0.10 | PO D6 |
| `risk.max_orders_per_min` | Order rate | orders/min | 30 | 1 | 60 | PM (A3) |
| `sizing.min_order_usd` | Exchange minimum notional | USD | 10 | 10 | – | MC 1.1 |
| `sizing.partial_below_min_action` | Partial below $10 | enum | skip_and_log | fixed | fixed | PO · FROZEN |
| `sizing.close_all_if_remainder_below_min` | Remainder below $10 → close all | bool | true | fixed | fixed | PO · FROZEN |
| `paper.wallet_usd` | Paper wallet | USD | 300 | fixed | fixed | PO · FROZEN |
| `live.min_wallet_usd` | Future live floor (not used in this epic) | USD | 300 | 300 | – | PO |
| `exits.stop_atr_mult` | Initial stop | × ATR | 2.0 | 1.0 | 4.0 | BR · EH (V3/V4) · OF |
| `exits.atr_period` / `exits.atr_candle_interval` | ATR definition | bars / interval | 14 / 1h | 5 / – | 50 / – | BR |
| `exits.tp_enabled` | Take-profit on | bool | true | – | – | PM (A1; V5 = false) |
| `exits.tp1_r` / `exits.tp1_fraction` | Partial TP | R / fraction | 2.0 / 0.5 | 0.5 / 0.1 | 10 / 1.0 | BR · PM (A1) · OF |
| `exits.trail_start_r` / `exits.trail_atr_mult` | Trailing stop | R / × ATR | 1.0 / 2.0 | 0.25 / 0.5 | 5 / 5 | BR · PM (A1) · OF |
| `exits.missed_exit_max_lag_s` | Missed-exit threshold; it enters the verdict and the verdict delay (F18.AC3) | s | 60 | fixed | fixed | PM (A4) · EH A3.1 · FROZEN |
| `exits.retry_interval_s` / `exits.alert_after_s` | Exit retry and alert | s | 1 / 10 | 1 / 5 | 5 / 60 | PM |
| `reconcile.interval_s` | Leader reconciliation | s | 300 | 60 | 600 | PM (A7, C4) |

### 3.7 Paper costs and restart
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `cost.taker_fee_bps` | Taker fee | bps | 4.5 | 4.5 (floor) | 20 | MC 1.1 |
| `cost.maker_fee_bps` | Maker fee (not used; no maker fills) | bps | 1.5 | 1.5 | 20 | MC |
| `cost.funding_accrual` | Funding method | enum | hourly_actual | fixed | fixed | PO |
| `paper.ack_delay_ms` | Simulated order ack | ms | 1000 | 500 (floor) | 5000 | MC 2.4 · CAL |
| `paper.max_book_age_ms` | Oldest book usable for a fill | ms | 5000 | 1000 | 5000 | EH 6.2 |
| `paper.meta_refresh_min` | Tick/lot/leverage refresh | min | 60 | 5 | 1440 | PM |
| `cost.fallback_half_spread_bps` | Major / alt by `cost.fallback_tier_rule` (§1, EH A3.3) | bps | 2 / 8 | 2 / 8 (floor) | – | EH 6.3 |
| `cost.fallback_half_spread_mult` | × recorded median | × | 1.5 | 1.5 (floor) | – | EH 6.3 |
| `cost.fallback_delay_slippage_bps` | Major / alt by `cost.fallback_tier_rule` (§1, EH A3.3); copies only, never random-time baselines | bps | 5 / 15 | 5 / 15 (floor) | – | EH 6.3 |
| `restart.max_reconstruct_gap_h` | Longest reconstructable gap | h | 72 | 1 | 84 (1m candle cap) | MC 2.2 |
| `restart.candle_interval` | Reconstruction candles | interval | 1m | fixed | fixed | MC 2.2 |

### 3.8 Telegram, reports, LLM, OKX, latency
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `telegram.allowed_user_id` | PO user | int | required | – | – | BRF |
| `telegram.control_chat_id` / `telegram.alerts_chat_id` | Chats | int | required | – | – | BRF |
| `telegram.min_edit_interval_s` | Edits per message | s | 5 | 3 | 60 | PM (Q22) |
| `telegram.max_msgs_per_min_per_chat` | Send rate | msg/min | 20 | 1 | 20 | PM (Telegram limit) |
| `telegram.queue_max_messages` / `telegram.queue_max_age_h` | Outage queue | count / h | 1000 / 24 | 10 / 1 | 10000 / 72 | PM |
| `telegram.pin_max_attempts` / `telegram.pin_lockout_min` | PIN lockout | count / min | 3 / 15 | 1 / 5 | 5 / 1440 | PM (A12) |
| `telegram.unauthorized_alert_interval_min` | Alert throttle | min | 10 | 1 | 60 | PM |
| `report.daily_time_utc` / `report.weekly_time_utc` | Report times | HH:MM | 00:05 / Mon 00:10 | – | – | PM (A13) |
| `report.disclaimer` | Report footer | text | "Paper trading. Not investment advice. Past results do not guarantee future results." | – | – | BRF |
| `report.weekly_block_days` | S6 blocks | days | 7 | fixed | fixed | EH |
| `llm.enabled` | Why-text on | bool | true | – | – | BRF |
| `llm.monthly_budget_usd` | Hard spend cap | USD/month | 5 | 0 | 20 | BRF · PM (A9) |
| `llm.timeout_s` | LLM timeout | s | 20 | 1 | 30 | PM (F1 invariant) |
| `llm.max_output_chars` | Output length | chars | 600 | 100 | 1500 | PM |
| `llm.fallback` | Offline fallback | enum | ollama | – | – | BRF |
| `llm.price_usd_per_1k_tokens` | Spend accounting (input / output) | USD | model price, set at build | >0 | – | PM |
| `okx.enabled` / `okx.poll_interval_s` | OKX recorder | bool / s | false / 60 | – / 30 | – / 3600 | BRF · PM (A8) |
| `latency.measure_hours` / `latency.min_signals` | Latency measurement | h / count | 24 / 100 | 24 / 50 | – | BRF |

### 3.9 Replay, run and evaluation (EH §9.2; FROZEN unless noted)
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `replay.max_variants` | Pre-paper variant budget | count | 8 | fixed | fixed | EH 5.8 · FROZEN |
| `replay.sensitivity_cost_mults` / `replay.sensitivity_delays_s` | Sensitivity runs | list | 1.5, 2.0 / 1, 3, 5 | – | – | EH 5.8 |
| `eval.sample_basis` | Sample basis | enum | opened | fixed | fixed | PO · FROZEN |
| `eval.n_trades` | Sample size | trades | 300 | fixed | fixed | PO · FROZEN |
| `eval.calendar_cap_days` / `eval.extension_days` | Run length | days | 30 / 30 | fixed | fixed | PO · FROZEN |
| `eval.closeout_max_days` | Close-out cap after t300 | days | 7 | fixed | fixed | EH (PO-ack) · FROZEN |
| `eval.ci_level_run1` / `eval.ci_level_run2` | CI levels | level | 0.96 / 0.99 | fixed | fixed | EH (PO-ack) · FROZEN |
| `eval.max_runs` | Paper runs | runs | 2 | fixed | fixed | PO · FROZEN |
| `eval.ci_method` | min of {iid t, day-cluster bootstrap, day-cluster CR t (G−1 df)} | enum | min3 | fixed | fixed | EH (PO-ack) · FROZEN |
| `eval.cluster_key` | UTC day of the merged component's first entry (transitive) | enum | merged_first_entry_day | fixed | fixed | EH · FROZEN |
| `eval.min_day_clusters` | G minimum | clusters | 5 | fixed | fixed | EH (PO-ack) · FROZEN |
| `eval.bootstrap_b` | Bootstrap resamples | count | 10000 | fixed | fixed | EH · FROZEN |
| `eval.bootstrap_seed` | 32 CSPRNG bytes at run start, stored as hex, consumed raw | bytes | generated | fixed | fixed | EH A2.7 · FROZEN |
| `eval.bootstrap_statistic` | Pooled trade mean | enum | pooled_mean | fixed | fixed | EH · FROZEN |
| `eval.rng` | SHA-256 counter with rejection | enum | sha256_counter_rejection | fixed | fixed | EH · FROZEN |
| `eval.percentile_index` | ⌊B·(100−L)/200⌋; UB at B−1−index | enum | floor_index | fixed | fixed | EH · FROZEN |
| `eval.gate_round_dp` | Rounding of LB/UB | dp | 6 | fixed | fixed | EH · FROZEN |
| `eval.flatten_gate_rule` | min(realised, shadow); shadow exit = evaluation close | enum | min_realised_shadow | fixed | fixed | EH A2.1 · FROZEN |
| `eval.require_clean_engine_tree` | Dirty → refuse | bool | true | fixed | fixed | EH A1.2 · FROZEN |
| `eval.engine_path_manifest` | Manifest path | path | `engine-path-set.txt` | fixed | fixed | EH A2.2 · FROZEN |
| `eval.run_worktree_pinned` | Detached worktree at the run commit | bool | true | fixed | fixed | EH A2.2 · FROZEN |
| `eval.run_record_env_hashes` | Package list + data inputs | list | packages, data_inputs | fixed | fixed | EH A2.2 · FROZEN |
| `eval.deploy_policy` | Ruling required; logic changes abort by default | enum | auditor_ruling_required | fixed | fixed | EH A1.2 · FROZEN |
| `eval.require_usd_pnl_positive` | P2b | bool | true | fixed | fixed | PO · FROZEN |
| `eval.baseline_gate` | B0d lower-bound gate, non-removable | enum | direction_matched_random_time | fixed | fixed | PO + EH · FROZEN |
| `eval.max_dd` / `eval.mark_interval_s` | P3 threshold and mark cadence (also the risk pause) | fraction / s | 0.15 / 60 | fixed | fixed | PO · FROZEN |
| `eval.max_downtime_fraction` | P5 | fraction | 0.02 | fixed | fixed | PO · FROZEN |
| `eval.show_interim_stats` | Interim visibility. `descriptive_only`: run-result content before `T_eval` appears only in `/stats` (F14.AC9) and each trade's own post; operational content stays allowed with no pass/fail label; the gate statistics in §5.5 are never computed or shown before `T_eval` (F14.AC6, F18.AC10, EH A4.11) | enum | descriptive_only | fixed | fixed | PO (A14) · EH A3.2 · FROZEN |
| `eval.missed_exit_max_count` | F2 fires when more than this many missed exits have a leader event in `[t0, T_eval]`, counted over all trades | count | 3 | fixed | fixed | PO (A4) · EH A3.1 · FROZEN |
| `eval.missed_exit_max_cost_r` | F2 fires when any missed-exit trade's cost (mirrored hi R − actual R, rounded to 1e-6) exceeds this | R | 1.0 | fixed | fixed | PO (A4) · EH A3.1 · FROZEN |
| `eval.missed_exit_gate_rule` | Gate R = min(actual, mirrored lo); evaluation close = the later of the real close and the mirror exit | enum | min_actual_mirrored | fixed | fixed | PO (A4) · EH A3.1 · FROZEN |
| `eval.missed_exit_gap_rule` | Ambiguous bar and fills in a mirror over a gap: stop first and lo candle prices (worst + 8 bps) for the gate and P3, TP first and hi candle prices (best + 2 bps) for the cost; 1m candle, else 1h; SL/TP at the trigger or a gapped-through open | enum | candle_lo_stop_first_hi_tp_first | fixed | fixed | EH A3.1, A4.2 · FROZEN |
| `eval.missed_exit_cost_rule` | Incremental cost of each missed exit and trade cost, each tested against `eval.missed_exit_max_cost_r`; actual R = realised R; an uncomputable mirror counts as > 1R with lo = actual and exit = real close | enum | incremental_and_trade_hi | fixed | fixed | EH A4.2, A4.3 · FROZEN |
| `eval.p4_breach_time` | Breach time = the 4th exit's event time (event order), or when a cost is established (capped at `T_eval`), or the first missed exit's time for an uncomputable mirror, or the start of an unaudited stretch; ABORTED wins only when strictly earlier | enum | earliest_event_order | fixed | fixed | EH A4.4 · FROZEN |
| `eval.settled_gap_rule` | An exit inside a data gap handled within 60 s of the resync is not a missed exit; its trade counts at min(actual, mirrored lo) | enum | settled_min_lo | fixed | fixed | EH A4.5 · FROZEN |
| `eval.fill_audit_interval_h` | Leader-fill audit period, for every leader with a share open since the last audit; a final audit up to `T_eval`; audits continue after `T_eval` until all shares close | h | 24 | fixed | fixed | EH A4.1 · FROZEN |
| `eval.missing_data_retry_max_h` | Retry bound for an incomplete audit stretch or an uncomputable mirror, from the first attempt; after it, a P4 breach | h | 72 | fixed | fixed | EH A4.1, A4.2 · FROZEN |
| `baseline.dm_exclude_downtime` | No B0d start time (full or relaxed set) inside a recorded **non-discretionary** downtime interval: `process_down`, `data_gap` before resync, `access_degraded`, `disk_low`. The 24 h missing-window test is measured with all downtime excluded | bool | true | fixed | fixed | EH A3.2 b, A4.6 · FROZEN |
| `baseline.dm_discretionary_pause_rule` | `/pause` and deploy-wait pauses are not excluded from B0d draws; B̄_i = max(mean of all draws, mean of draws outside the pause), from the same draws | enum | max_all_outside_pause | fixed | fixed | EH A4.6 · FROZEN |
| `cost.fallback_tier_rule` | Major = tier 1 at decision time. No tier record = alt for paper trades, replays, reconstruction and shadows; major for B0d, B0, B0b, B1 and B3 (§1) | enum | tightest_tier_conservative | fixed | fixed | EH A3.3, A4.7 · FROZEN |
| `eval.recording_integrity` | Lossless compression; a stream sha256 and a transport sha256 per file in the ledger, both verified on every read; a hash-chained segment record every 5 min (unhashed data is a gap); local delete only after a verified read-back upload; reads try local, then every ledgered destination, newest first; a missing or failed file is a recording gap; verdict values recomputed from verified data; the recorder runs the run commit during a run. The storage destination is outside the config hash (a ledgered change); retention, cache size and upload timings stay inside it | enum | lossless_hashed_verified | fixed | fixed | EH A3.4, A4.8 · FROZEN |
| `baseline.dm_costs` | Fees + own-time book + own ack drift + funding; no decay; R from fills | enum | own_time_no_decay | fixed | fixed | EH A1.1/A2.3 · FROZEN |
| `baseline.dm_min_admissible_hours` / `baseline.dm_max_missing_share` | Missing-window rule | h / fraction | 24 / 0.10 | fixed | fixed | EH · FROZEN |
| `baseline.dm_missing_rule` | min(R, 0, R − B̄_partial) with the 3-step chain | enum | min_r_0_partial | fixed | fixed | EH A2.3 · FROZEN |
| `baseline.dm_max_book_gap_s` / `baseline.dm_max_mid_gap_s` | Admissibility | s | 5 / 60 | fixed | fixed | EH · FROZEN |
| `baseline.dm_reps` / `baseline.random_reps` | Replications | count | 1000 / 1000 | fixed | fixed | EH · FROZEN (dm) |
| `baseline.top_roi_n` | B1 size | wallets | 9 | fixed | fixed | EH · FROZEN |
| `fragility.top_k_trades` / `fragility.drop_best_day_clusters` / `fragility.cost_stress_mult` | FR1 / FR6 / FR3 | count / count / × | 5 / 1 / 2.0 | fixed | fixed | EH · FROZEN |
| `decay.deltas_s` | Decay horizons | s | 0.25, 0.5, 1, 2, 3, 5, 10, 30, 60, 300 | – | – | EH |
| `data.paid_s3` | Paid S3 data | bool | false | fixed | fixed | PO |
| `d6.min_decision_agreement` | D6 | fraction | 0.90 | fixed | fixed | EH 8.2 |
| `d6.max_median_abs_r_diff` / `d6.max_mean_r_diff` | D6 | R | 0.05 / 0.10 | fixed | fixed | EH 8.2 |
| `d6.max_median_fill_dev_bps` / `d6.max_p90_fill_dev_bps` | D6 | bps | 3 / 10 | fixed | fixed | EH 8.2 |
| `d6.max_trade_count_dev` | D6 | fraction | 0.10 | fixed | fixed | EH 8.2 |
| `kill.k1_min_trades` / `kill.k2_min_trades` | K1 / K2 sample floors | trades | 100 / 150 | fixed | fixed | EH 7 |
| `kill.k6_decay_share` | K6 | fraction | 0.50 | fixed | fixed | EH 7 |
| `kill.k7_min_eligible` / `kill.k7_cycle_share` | K7 | count / fraction | 5 / 0.50 | fixed | fixed | EH 7 |
| `kill.k8_unexecutable_share` | K8 | fraction | 0.50 | fixed | fixed | EH 7 |

**Values that the PO's `hl_sample.py` run must validate (VAL-S).** These are all research priors today:
- `scoring.candidates_k` and `select.min_followed`
- `gate.min_round_trips`, `gate.min_fill_span_days`, `gate.min_median_hold_min`, `gate.min_account_value_usd`, `gate.min_executable_share` and `gate.max_maker_share`

The quant-researcher reviews them against `summary.json` before the config is frozen. A change goes into the config before run 1; it never needs an addendum, because none of these keys is FROZEN.

**Values that the latency measurement must validate (VAL-L):** `filter.max_signal_age_ms` (it can only go down: the ceiling is 5,000 [PO]), `copyreplay.delay_ms`, `feed.stale_after_s`, `clock.max_offset_uncertainty_ms` and `gate.hold_latency_mult`.

**Values that our recordings must validate (VAL-R):** `tiers.lookback_days`, `tiers.depth_band_pct`, the four tier thresholds and `recording.max_gb_per_day`. The tier defaults are priors, not measurements. They are checked against ≥ 7 days of recordings in the readiness report, then adjusted within their bounds and frozen. None is FROZEN, so no addendum is needed; the hard floors on the tradable floor can't be lowered.

---

## 4. Non-functional requirements

**Latency budgets per stage.** Leader timestamps are exchange time, corrected by the clock offset.

| Stage | p50 | p95 | p99 | Note |
|---|---|---|---|---|
| S1: leader fill (exchange) → WS receive | ≤ 700 ms | ≤ 1,500 ms | ≤ 3,000 ms | Network and exchange; a **measured target** (VAL-L), not a code budget |
| S2: WS receive → signal classified | ≤ 5 ms | ≤ 20 ms | ≤ 50 ms | F7 |
| S3: signal → decision (filter, gate, sizing) | ≤ 20 ms | ≤ 60 ms | ≤ 150 ms | F9 and F10 |
| S4: decision → paper fill computed | ≤ 10 ms | ≤ 30 ms | ≤ 100 ms | Plus the simulated `paper.ack_delay_ms` (1,000 ms) |
| Leader fill → decision (S1 + S2 + S3) | ≤ 800 ms | ≤ 1,700 ms | ≤ 3,300 ms | At least 95% of signals decided within 5 s |
| Leader exit receive → our close decision | ≤ 20 ms | ≤ 60 ms | ≤ 150 ms | The exit path |
| Missed exit detected → alert sent | ≤ 5 s | ≤ 30 s | ≤ 60 s | F12.AC6. The cost follows within 5 min of the later of the share's close and its mirror exit, or at `T_eval` (F12.AC9) |
| Daily fill audit, per leader | ≤ 30 s | ≤ 2 min | ≤ 10 min | F12.AC10; an audit interval is retried for up to 72 h, then it is a P4 breach |
| Hourly candle fetch and store, per hour | ≤ 30 s | ≤ 2 min | ≤ 10 min | F4.AC9; a missing candle is retried for up to 72 h |
| Mark crossing SL/TP → close decision | ≤ 50 ms | ≤ 200 ms | ≤ 1,000 ms | |
| Entry fill → Telegram post sent | ≤ 2 s | ≤ 5 s | ≤ 15 s | Subject to Telegram limits |
| Telegram command → reply | ≤ 1 s | ≤ 3 s | ≤ 10 s | |
| Scoring cycle, incremental, 200 candidates + followed | ≤ 10 min | ≤ 20 min | ≤ 45 min | |
| Restart → trading-ready, gap ≤ 1 h | ≤ 60 s | ≤ 120 s | ≤ 300 s | |

**Throughput:**
- 9 followed wallets, with bursts of 100 fills/s sustained for 10 s.
- Recording of ≤ 250 coins at `recording.l2_interval_ms`.
- REST ≤ 900 weight/min.
- The recorder and the trading path together use ≤ 500 WS subscriptions.

**Availability:**
- Downtime < 2% of the evaluation window (P5): about 14 h in 30 days and about 32 h at the 67-day maximum.
- In the 24h dry run, the target is ≥ 99.5% uptime, with no single outage over 15 min.

**Resources** (PO's Windows PC):
- RAM ≤ 2 GB RSS.
- Average CPU ≤ 25% of one core, excluding the evaluation and replay batch jobs. Compression and upload are included.
- Recording ≤ `recording.max_gb_per_day` (1.5 GB/day) compressed on disk, measured in the 24h dry run (A10).
- The ledger grows ≤ 200 MB/day.
- **Local disk footprint** at steady state ≤ 50 GB of the PO's ~100 GB free: the local window plus the current day (8 days × ≤ 1.5 GB), the download cache (≤ 20 GB) and the ledger (≤ 200 MB/day, about 15 GB over 74 days).
- Archive upload ≤ 1 day of recording per `storage.upload_deadline_h` (6 h), and upstream use ≤ 2 GB/day.

**Batch jobs:**
- The `T_eval` verdict plus 300,000 B0d replications take ≤ 4 h.
- A replay of 7 days × 9 wallets takes ≤ 60 min.
- The report regenerates in ≤ 10 min from computed baselines.
- These budgets hold with every input day local, and they include the sha256 verification of every file read (F23.AC3). When days must first be downloaded from the archive, the download time is extra and is reported separately.
- The verdict is computed no earlier than `T_eval` + 60 s, after the reconciliation pass, the final fill audit and the recomputation from verified data (F18.AC3), and no later than 72 h after `T_eval` (A4.1). The 4 h budget starts from then.
- The fill-audit and candle requests use the reconciliation and exit priority class of F3.AC1 and never exceed the REST budget.

**Cost:**
- Total ≤ $50/month.
- LLM ≤ `llm.monthly_budget_usd` ($5 default).
- Object storage ≤ `storage.monthly_budget_usd` ($5/month), including operations and egress (F23.AC7). At an expected ≤ 1.5 GB/day, 74 days is ≤ 111 GB: about $0.70/month on B2, or $1.70 on R2.
- Every data source is $0. No paid S3 **data** (`data.paid_s3`); the object-storage bucket is our own archive, not a data purchase.

**Security:**
- 0 inbound listening ports.
- Secrets only from the environment.
- The Telegram allow-list is one user and one chat.
- The object-storage key should be scoped to the one bucket, without delete rights. The engine needs read, write and list only (F23.AC2).
- The ledger backup is encrypted on the PC before upload (F23.AC4). Recordings are public market data and are not encrypted.

---

## 5. Failure behaviour

The default is **fail closed for opens and adds, never for exits**.

| Dependency / event | Detection | Behaviour | User-visible effect | Recovery |
|---|---|---|---|---|
| HL WebSocket disconnect or silent stall | No message or pong for `feed.stale_after_s` | Refuse opens and adds for affected wallets; the gap is ledgered as `data_gap` downtime | Alert "feed stale: <wallets>"; `/status` shows it | Jittered reconnect; REST resync by `tid` before any decision; missed leader exits are mirrored immediately; gap positions are reconstructed (F13) |
| Book or mark stale | Age > `filter.max_price_age_ms` | Refuse opens; SL/TP evaluation waits for fresh data; over `feed.stale_after_s` it becomes a data gap | Refusal reason `stale_price` | On fresh data, evaluate triggers; gap → reconstruct from 1m candles |
| REST 429 | HTTP 429 | Backoff (F3.AC2); scoring deferred; exits and reconciliation first | None unless it lasts > 10 min (then alert) | Automatic |
| HL 403/451 or geo-block (BCB deadline 2026-10-30) | F3.AC5 | `access_degraded`: refuse opens and adds; keep retrying; counts as downtime (K10) | Alert; `/status` shows the reason | Clears after `access.recover_min` healthy; if it persists, PO decides (K10) |
| Leaderboard endpoint fails or changes schema | HTTP error, timeout, schema failure, < 1,000 rows | Keep the followed set; add none | One alert per outage | Automatic on success |
| Wallet history truncated at 10k fills | Truncation rules (hl_sample BT2-6) | Flag the wallet; G3 decides eligibility | None | – |
| Clock offset unknown or too large | F1.AC6 | Refuse opens and adds | Alert `clock_unsynced` | Clears when the offset is back within bounds |
| Invalid config at start | F1.AC1 | Refuse to start | Non-zero exit with the key named | Fix the config (in a run, that is ABORTED) |
| Config hash change mid-run | F17.AC4 | Run → ABORTED; the engine keeps managing positions | Alert "run ABORTED: config change" | Run 2 needs a new run record |
| Dirty tree, wrong worktree, or recorder/archive process not on the run commit at run start | F17.AC2 | Refuse run start | Error message naming the cause | Clean or re-pin; restart the recorder and archive processes from the run worktree; then start |
| Run 2 with an unresolved missed exit from run 1 | F17.AC9 | Refuse run start | Error naming each missed-exit ID | Record a resolution (root cause, fix commit, regression test) for each (K13) |
| Mid-run code or dependency change (engine, recorder or archive process) | F17.AC3 | New code refuses to run for the run; the recorded commit continues, including the recorder | Alert "deploy pending ruling" | Auditor ruling: CONTINUE or ABORTED. A deploy whose stated reason is an interim result can only be ABORTED (A3.2 c). |
| Ledger append or verification failure | F2.AC1 / F2.AC6 | Halt all actions; paper positions freeze; counts as downtime | Alert (Telegram if possible, and the local log) | Restart after repair; reconstruction settles the gap |
| Free disk below the alert threshold | F4.AC5 | Keep running; report the unarchived backlog | Alert once per 6 h | Archive catches up (F23), or the PO frees space |
| Free disk below the hard floor | F4.AC5 | Recorder flushes and stops safely; opens and adds refused `disk_low` (downtime); exits, ledger and uploads continue | Alert "recording stopped: disk floor" | Automatic resume above floor + margin; the gap counts under edge-hypothesis §14 item 8 |
| Archive upload or verification fails | F23.AC1 / F23.AC6 | Keep local data; retry; never prune the day | Alert with the backlog (days, GB) | Automatic on success; if the backlog reaches the disk floor, see the row above |
| Storage credentials missing | F23.AC5 | Record locally; no upload or pruning; `run start` refused | Alert; `/status` shows `archive: not configured` | PO sets the env variables |
| Recording file fails its ledger sha256, or is missing | F23.AC3 | Try every ledgered destination, newest first, and re-download for `storage.read_retry_max_min`; never use a failing copy. With no matching copy, the file is **lost**: ledgered once and treated as a recording gap by every reader | Alert `recording_file_lost` with the file and day | None for the file: it is never re-recorded or replaced (A3.4). Its effect goes through B0d admissibility, the 1h-candle fallback for shadows and mirrors, and D6 (edge-hypothesis §14 item 8). A bad archived copy is re-uploaded from a local copy only if that copy matches the ledger sha256. |
| Archive unreachable during a batch read | F23.AC3 | Retry for `storage.read_retry_max_min`, then the batch job exits non-zero | Error naming the day | Re-run when reachable; trading is unaffected |
| Ledger backup fails | F23.AC4 | Retry; trading continues | Alert | Automatic; `run start` refused after 48 h without a verified backup |
| Projected storage cost ≥ 80% of $5/month | F23.AC7 | Keep uploading | Daily alert | PO decides (A21) |
| Tier table missing or stale | F9.AC8 | Refuse opens with `untiered`; exits continue; `run start` refused | Alert | Next recompute with enough coverage |
| Tier table in force that the frozen rule does not reproduce | F17.AC4 | Run → ABORTED. A table the rule reproduces (each 24 h recompute) is not a config change | Alert "run ABORTED: tier table" | Run 2 needs a new run record |
| No leverage within the ceiling fits the margin, or liquidation too close | F10.AC4 | Refuse the open or add (`insufficient_margin` / `liq_too_close`); never an exit | Logged refusal; counted in the daily report | None needed |
| Telegram API down | Send errors | Queue messages (F14.AC8); trading continues; the kill switch stays available on the CLI | Delayed posts | Queue drains in order |
| LLM down, timeout or over budget | F15 | Post without "why"; try Ollama | "why unavailable" | Automatic; the budget resets monthly |
| Calendar missing, invalid or expiring | F8.AC3 | Refuse opens and adds; refuse run start | Alert `calendar_invalid` | Update the data file (a data-input change: a deploy if mid-run) |
| Process crash, Windows update reboot, PC sleep or power loss | Supervisor, or a heartbeat gap | Restart; reconstruct; downtime | Alert on restart with the gap duration | F13 |
| Coin delisted with an open share | Exchange delist or settlement | Close at the settlement price | Post with `delisted_force_settle` | – |
| Mark reaches liquidation | F11.AC5 | Liquidate the share | Post with `liquidated`; alert | – |
| Leader flat or reversed but our share open | Reconciliation | Close the share; missed-exit check | Alert; possibly a missed exit (row below) | – |
| Unknown fill format or `dir` value | Schema or classifier failure | Signal `unparseable`, not traded; immediate reconciliation if it involves an open share | Alert | Code fix (a deploy if mid-run) |
| Drawdown ≥ 15% | F10.AC5 | Pause until `/resume`; FAIL (F1) | Alert "drawdown stop, run FAIL" | PO `/resume`; the run is over |
| Daily or weekly loss limit | F10.AC5 | Halt opens and adds until reset (not downtime) | Alert once | Automatic at reset |
| Missed exit detected (including during an entry pause, on a trade outside S, or after `T_eval`) | F12.AC6 | Bring the share in line with the leader. Build the mirror (F12.AC9) and, once the trade and its mirror have both closed, store gate R = min(actual, mirrored lo) and cost = mirrored hi − actual. Write go-live blocker ME. Entries are not paused. | Alert "missed exit n/3, go-live blocker ME", then a second alert with the cost | The run continues unless F2 fires (next row). ME stays until explained and fixed at /go-live. Run 2 needs a resolution record (F17.AC9). A fix during the run is a deploy (F17.AC3); the recommended route is to fix it after `T_eval`. |
| 4th missed exit with a leader event in `[t0, T_eval]`, or a missed-exit trade whose cost > 1R (edge-hypothesis A3.1) | F18.AC11, F18.AC7 | FAIL (F2) at the ledgering of the 4th missed exit, or when the trade and its mirror have both closed, or at `T_eval` with the open side marked; the run ends; the bot pauses | Alert "missed-exit limit, run FAIL (K13): engineering failure, not evidence about the edge" | The run is over. Explain and fix every missed exit before run 2 (K13, F17.AC9). |
| Missed-exit cost can't be computed (book missing and exchange candles unreachable) | F12.AC9 | Retry every `storage.retry_interval_min`; no cost is guessed for up to 72 h. **After 72 h it is F2 (K13):** the cost counts as > 1R, lo = actual R, mirror exit = the real close, breach time = the first missed exit's leader event time | Alert per `storage.alert_interval_h`; "cost pending", then the F2 alert | Automatic if the data arrives within 72 h. After that the FAIL stands; fix the cause before run 2. |
| Incomplete leader-fill audit (API unreachable or a page truncated) | F12.AC10 | Retry every `storage.retry_interval_min` for up to 72 h from the first attempt. **After 72 h a stretch of `[t0, T_eval]` still unaudited is a P4 breach (F2, K13)** at the stretch's start; the verdict waits for the final audit, bounded at 72 h. An unaudited stretch after `T_eval` is listed with ME | Alert per `storage.alert_interval_h`; the audit coverage in the report | Automatic if the fills are retrieved within 72 h. After that the FAIL stands. |
| Verdict time reached | F18.AC3 | Wait until `T_eval` + 60 s, one reconciliation pass over every share open at `T_eval`, the final fill audit, and recomputation from hash-verified data; bounded at 72 h, then compute | None | – |
| Archive destination changed | F23.AC5 | Ledger `archive_destination_changed`; reads try local, then every ledgered destination, newest first; not a config change or deploy | None | – |
| Unauthorized Telegram command | F14.AC1 | Refuse; audit | Throttled alert | – |
| Repeated wrong PIN | F14.AC5 | Lock `/flatten` in Telegram | Alert | Lockout expires; CLI flatten still works |
| NTP or offset source unreachable | Estimate age grows | After `clock.max_estimate_age_s`, refuse opens and adds | Alert | Automatic |
| OKX endpoint error | F22.AC3 | Back off; no effect elsewhere | ≤ 1 alert per day | Automatic |

---

## 6. Flags

- `touches_money_path`: **yes**. Sizing, the risk gate, paper execution, positions and exits are the money path, and they port to live later.
- `touches_strategy`: **yes**. Trader scoring and selection, filters, exits and the pre-registered evaluation are all in scope.
- `has_ui`: **no**. There is no web UI. Telegram is the only interface; `qa` tests it as `integration` and `qa-ui`.

---

## 7. Implicit requirements

**Trading invariants (`.claude/knowledge/trading-invariants.md`):**

| Invariant | Enforced by |
|---|---|
| A1 single chokepoint | F10.AC1 |
| A2 fail closed | F1.AC1, F10.AC7, F5.AC3, F8.AC3, F3.AC5, F4.AC5, F9.AC7–AC8 (below floor, untiered), F10.AC4 (no fitting leverage), F12.AC9, F12.AC10 and F18.AC11 (an uncomputable mirror or incomplete audit is F2 after 72 h, never a pass; no guessed cost), F17.AC2 (recorder not on the run commit), F23.AC3 (every read hash-verified; a failing copy is never used), §5 |
| A3 hard limits in config (notional, leverage, open positions, per-symbol exposure, daily loss, orders/min) | F1.AC2, F10.AC3–AC5, F10.AC10 (leverage ceilings 5x/10x and the compiled high-leverage coin set); §3.6 |
| A4 kill switch (CLI + Telegram, persistent, tested) | F10.AC6, F14.AC4–AC5, F13.AC4 |
| A5 idempotency / deterministic client order IDs | F10.AC8, F7.AC2, F2.AC3, F13.AC5 |
| A6 Decimal money, tick/step rounding, minimum notional | F1.AC4, F11.AC4, F2.AC4 |
| A7 exchange is the source of truth | **Paper analogue:** our "exchange" is the paper broker, whose state is rebuilt from the verified ledger at startup (F2.AC1, F13). The leader's positions are reconciled against `clearinghouseState` (F12.AC5). Real exchange reconciliation is N/A: there is no exchange account in this epic. |
| A8 partial fills, rejects, cancels, liquidations, ADL | F11.AC1, AC5, AC8; F10.AC4 keeps liquidation ≥ 3 × the stop distance. **ADL: N/A.** A paper position can't be auto-deleveraged, and no per-account ADL data exists; revisit at /go-live. |
| A9 explicit units | F1.AC4; §3 unit column. Naming is enforced in review. |
| A10 explicit mode, paper default, live refused | F1.AC3 |
| B1 staleness guard | F9.AC1, F3.AC3, F7.AC5 |
| B2 UTC timestamps with source and clock skew | F1.AC6, F7.AC5 |
| B3 heartbeats, reconnect with jitter, gap resync | F3.AC3, F3.AC4, F21.AC1 |
| B4 rate budget and 429 backoff | F3.AC1, F3.AC2 |
| B5 append-only audit of every decision | F2.AC1, F2.AC2, F5.AC7 |
| C1 verified fills and minimum sample | F5.AC3, F5.AC6 |
| C2 size by our risk budget | F10.AC2 (the mirror is only an upper bound; the risk cap always applies) |
| C3 slippage guard | F9.AC1 (thresholds by liquidity tier), F9.AC7 |
| C4 mirror closes, reductions and flips; no orphans | F12.AC3, AC4, AC5, AC6, AC8, AC9, AC10 (the fill audit); a missed exit is always go-live blocker ME (F20.AC4), and run 2 needs its resolution (F17.AC9) |
| C5 independent leaders in consensus | **N/A:** no consensus voting exists. Each leader is a separate share. Correlated leaders' stacking is bounded by the per-coin, BTC-bucket and per-leader caps (F10.AC3). |
| C6 end-to-end latency measured and exported | F7.AC6, F21.AC3, F20.AC1, §4 |
| D1 no look-ahead | F4.AC3, F5.AC5, F9.AC2, F9.AC7 (tiers from data received ≤ computation time), F16.AC2, F23.AC3 |
| D2 no survivorship | F4.AC2, F16.AC4, F2.AC5, F23.AC2 (the archive is never deleted from; no local delete before a verified upload), F23.AC3 (a lost file is a gap, never replaced) |
| D3 fees, funding, spread and slippage | F11.AC1–AC3, AC7, F16.AC6, F19.AC3, F19.AC4 (fallbacks by `cost.fallback_tier_rule`, the conservative side per use) |
| D4 criteria before results; variants counted | F17 (frozen hashes, including the tier table; interim-result deploys only ABORTED, F17.AC3), F16.AC5, F18.AC10, F18.AC11, F14.AC6, F14.AC9, F19.AC2 (no B0d start inside `/pause` or other downtime); edge-hypothesis A3 is dated before run 1 |
| D5 out-of-sample and naive baselines | F16 (point-in-time replay), F19 (B0d), F20.AC1 (B0, B0b, B1–B4) |
| D6 paper confirms replay | F18.AC9 (P6), F20.AC3 |
| E1 trade-only keys | **N/A:** no exchange keys exist in this epic (F1.AC3). |
| E2 secrets from env, never logged | F1.AC5, F15.AC3, F23.AC5 |
| E3 authenticated control surface | F14.AC1, F14.AC5 |
| E4 no public admin ports | F21.AC4 |
| E5 every fill exportable | F2.AC4; the encrypted ledger backup (F23.AC4) protects the records against loss of the PC |
| E6 third-party offering → legal review | **N/A in this epic.** Phase 2 is out of scope and gated by D12. Reports carry a disclaimer (F14.AC7). |
| F1 LLM hard timeout and fallback, off the hot path | F15.AC1, F15.AC2 |
| F2 LLM can't raise size or bypass limits | F15.AC4 (it has no vote at all [PO D5]) |
| F3 LLM inputs and outputs logged | F15.AC3 |

**CLAUDE.md implicit requirements:**

| Requirement | Enforced by |
|---|---|
| Secure by default; secrets never read, logged or committed | F1.AC5, F14.AC1, F14.AC5, F21.AC4, F23.AC4 (encrypted backup), F23.AC5 (env-only storage credentials, HTTPS only) |
| Anything data-driven is data-driven | F1.AC1 (no code defaults), §3; the calendar is a data file (F8); coin tiers come from measured liquidity, not a hand list (F9.AC7); leverage is computed per order (F10.AC4) |
| Money-safety invariants are BLOCKING | This section; every reviewer treats a violation as BLOCKING |
| No agent places a live order or touches live keys; tests use paper or replay | F1.AC3; every `simulation` AC runs in paper or replay |
| Real money only after /go-live and a written PO go | F1.AC3 (live refused in this build); out of scope (§8) |

**Frozen pre-registration** (edge-hypothesis §5), mapped to ACs:
- Run record: F17.AC1
- Engine path set: F1.AC7 and F17.AC2
- Deploy rules: F17.AC3
- Verdict rule and precedence: F18
- B0d and P2c: F19
- Go-live blockers and diagnostics: F20
- Visibility (§5.5, A3.2): F14.AC6, F14.AC9 and F18.AC10; interim-result deploys (A3.2 c): F17.AC3
- Missed-exit rule (P4/F2, A3.1, A4.1–A4.5): F12.AC5, F12.AC6, F12.AC9, F12.AC10, F4.AC9, F18.AC3, F18.AC4, F18.AC6, F18.AC7, F18.AC9, F18.AC11 and F20.AC1; ME and K13: F20.AC4 and F17.AC9
- `/flatten` shadow: F12.AC7 and F18.AC3
- B0d downtime exclusion and the discretionary-pause max rule (A3.2 b, A4.6): F19.AC2 and F19.AC4
- Fallback tier rule and untiered coins (A3.3, A4.7): §1, F13.AC1, F16.AC6, F19.AC4, F20.AC1; tier table in a run (A4.7): F9.AC8, F17.AC1 and F17.AC4
- Recording integrity (A3.4, A4.8): F4.AC7, F4.AC8, F4.AC9, F17.AC2, F17.AC3, F23.AC1, F23.AC2, F23.AC3 and F23.AC5
- Visibility of run-result content (A4.11): F14.AC6, F14.AC7, F14.AC9 and F18.AC10
- Conformance oracle E16 (A4.12): F18.AC1
- Run register: F17.AC6
- Evaluation tests 1–24 (§10.8): covered across F4, F12, F14, F16, F17, F18, F19, F20 and F23; the test plan maps each. Tests 21–24 map to F12.AC6/AC9 and F18.AC3/AC11 (21), F19.AC2 (22), F16.AC6 and F19.AC4 (23), and F4.AC7, F17.AC2/AC3 and F23.AC2/AC3 (24). Tests 25–29 (A4) map to F12.AC5/AC10 (25), F12.AC9 and F4.AC9 (26), F12.AC9 and F18.AC11 (27), F18.AC6/AC7 (28), and F12.AC6 (29). The numbering of tests 25–29 follows the A4 table and is to be confirmed against §10.8.

---

## 8. Out of scope

- F22, the OKX lead-trader recorder. It was removed by Amendment 3 to cut cost, and a later epic may bring it back.

- Real-money execution, live keys, the Hyperliquid testnet, and exchange-side SL/TP placement (D9 applies when live).
- Running the paper runs themselves, and their verdicts. They start after /ship, on the PO's go, and are tracked in the run register (A11).
- HIP-3 **trading**; its data is recorded. On-chain memecoins, on-chain spot, Binance, and any other execution venue. Liquid Hyperliquid meme perps (for example DOGE, kPEPE, WIF) are **in** scope when they qualify by liquidity tier (F9.AC7).
- OKX **signals or trading**. F22 records only.
- An ML-trained filter. Data is collected; the model is a later epic.
- Web UI, WhatsApp, subscribers, payments, KYC, a Telegram channel or Mini App, and all phase-2 legal work (D12).
- Cloud compute hosting, a VPS and paid data (paid S3 data, CoinGlass, Nansen). Object storage for our own archive and ledger backup is **in** scope (F23, ≤ $5/month).
- Automatic restore of the whole recording archive to a new PC. Only the ledger restore drill (F23.AC4) and on-demand reads of archived days (F23.AC3) are in scope.
- BRL conversion and tax exports beyond the USD fill CSV (F2.AC4).
- Any news source, paid or free, for the LLM summary (A9). **J7 Tracker was not evaluated**; the PO may send a link for a later epic. The LLM has no vote either way.
- Strategy changes after run 1 starts, other than by a dated addendum (edge-hypothesis §5.1).

---

## 9. Definition of done

The epic is done, meaning **run-1-ready**, when all of the following hold:
1. **ACs met.** Every AC in F1–F21 and F23 is `MET` in `07-verification.md`, with evidence. F22 is `MET` too, or has been moved to out-of-scope by the PO (A8).
2. **Tests.**
   - The full test suite passes on Windows 10/11 with the pinned lockfile (F21.AC5).
   - Every test that proves an AC fails before its implementation.
   - The mutation threshold set by /onboard is met for `risk`, `paper`, `positions`, `evaluation`, `baselines` and `archive`.
3. **Conformance.** The evaluation reproduces every E16 golden vector (`eval_reference.py` v4, including `GOLDEN_MISSED`, `GOLDEN_MISSED_CLOSE` and the `GOLDEN_A4_*` vectors), and all 31 E16 mutants are killed (F18.AC1).
4. **Reviews.** No BLOCKING finding is open from /review or /qa.
5. **24h dry run.**
   - ≥ 24 h continuous, full pipeline, live mainnet data, dry-run mode, on the PO's PC (F21.AC2).
   - 0 crashes, 0 missed exits, downtime < 2%, and the ledger verifies.
   - "0 missed exits" is stricter than the run rule on purpose (F21.AC2): in the dry run any missed exit is a bug to fix before run 1, not something to absorb under the edge-hypothesis A3 limits.
   - Compressed recording ≤ `recording.max_gb_per_day`, one day archived and verified, and one ledger backup verified.
   - It starts once ≥ `tiers.lookback_days` × `tiers.min_coverage_fraction` days of recording exist, so a tier table is in force.
6. **Latency measurement.**
   - ≥ 24 h, n ≥ 100 signals (F21.AC3), on the PO's connection.
   - The VAL-L keys are set from it before freezing: `filter.max_signal_age_ms` ≤ 5,000, and `copyreplay.delay_ms` = measured p95.
7. **Recording and archive.**
   - ≥ 7 days of continuous, compressed recording and hourly leaderboard snapshots exist before run 1.
   - Every finished day older than `storage.max_unarchived_days` is archived and verified, and local pruning has run at least once under F23.AC2.
   - The ledger restore drill (F23.AC4) has passed on the PO's PC.
   - A replay of ≥ 1 archived-only day has matched its local replay byte for byte (F23.AC3).
8. **Readiness report** (F20.AC5), delivered to the PO. It includes:
   - the recorder gap rate and the projected share of trades without a B0d window
   - K1, K2, K6, K7 and K8 statuses
   - the point-in-time replay result

   If K1 or K2 is triggered, the epic stops for PO review (edge-hypothesis §7).
9. **Config frozen.**
   - `hl_sample.py` `summary.json` has been received, and the quant-researcher has reviewed the VAL-S keys.
   - The CAL keys are calibrated on pre-paper data.
   - The complete config is committed, and its hash is recorded in the readiness report.
10. **Run-control artifacts.**
    - `engine-path-set.txt` is committed.
    - The run-worktree procedure is documented in `docs/sdlc/copytrade-v1/`. It includes moving the recorder and archive processes from the pre-run recording worktree to the run worktree before `run start` (A16, edge-hypothesis A3.4).
    - `run start` refuses on a dirty tree, and while the recorder runs from another worktree (both demonstrated).
11. **Acknowledgements.**
    - The PO's acknowledgement of section-14 items 1–8 is recorded. It already is: `decisions.md`, 2026-09-29.
    - The PO's **re-acknowledgement** of section-14 **items 9 (missed exits) and 10 (`/stats`)**, as rewritten in plain language by edge-hypothesis A4.9, is recorded in `decisions.md`. An acknowledgement of the A3 wording does not satisfy this. **It is pending.** The edge-hypothesis makes it a run-1 precondition (header and §8.1).
    - Edge-hypothesis Addenda A3 and A4 are committed and dated before run 1. They are. The ACs were reconciled with A3 in Amendment 2 and with A4 in Amendment 4.
12. **No live path.** No live order path exists in the build (F1.AC3).
13. **Tiers validated.** The VAL-R tier thresholds have been reviewed against recorded data in the readiness report, and the tier table in force at config freeze is shown to the PO with its tier-1, tier-2 and below-floor coins.

---

## 10. Epic plan

**Order and parallelism.** Each feature is sized for one developer on `feat/copytrade-v1/<Fn>-<name>`. A wave starts when its dependencies have passed /verify into `epic/copytrade-v1`.

| Wave | Features (parallel within a wave) | Depends on | Note |
|---|---|---|---|
| 0 | F1 | – | Scaffolds the stack, lockfile, `engine-path-set.txt`, config loader, shared domain types and CLI registry |
| 1 | F2, F3, F8, F5, F18 | F1 | F5 and F18 are pure logic over interfaces and fixtures |
| 2 | F4, F7, F11, F15, F22 | F2, F3 | **F4 ships to a recording worktree right after /verify**, so day-1 recording and leaderboard snapshots start early (the ≥ 7-day precondition). F7 enables the early 1-day latency measurement (F7.AC6). |
| 3 | F6, F9, F10, F17, F19, F23 | F4 + F5 → F6; F4 + F7 + F8 → F9; F11 → F10; F2 → F17; F4 + F11 + F18 → F19; F2 + F4 → F23 | **F23 also ships to the recording worktree right after /verify**, so archiving and pruning start well before the local disk fills (at ≤ 1.5 GB/day, the ~100 GB lasts ~50 days without it). F10's leverage choice uses F11's liquidation model through its interface. |
| 4 | F12, F14 | F7, F10, F11 → F12; F10 (+ F12 events) → F14 | F14 may start on F10 alone and wire F12 events when they land. `/stats` needs only F2 aggregates. |
| 5 | F13, F16 | F12 | |
| 6 | F20, F21 | F16, F18, F19, F23 → F20; all → F21 | F21 runs the 24h dry run and the final latency run |

**Critical path:** F1 → F3 → F4/F7 → F9/F10/F11 → F12 → F16 → F20/F21. F23 is off the critical path but must pass before the recording worktree nears the disk alert threshold, and before run 1. F22 is off the critical path and is the first to be dropped under schedule pressure.

**Edge-hypothesis A3 and A4:** committed. The A3- and A4-derived vectors are final: F4.AC7/AC9, F9.AC8, F12.AC5/AC6/AC9/AC10, F14.AC6/AC9, F17.AC4, F18.AC1/AC3/AC4/AC6/AC7/AC10/AC11, F19.AC2/AC4, F20.AC1 and the F23 integrity cases. /tests takes them from A3 tests 21–24, A4 tests 25–29 and 22–24 as amended, and the E16 literals (`GOLDEN_A4_*`). If /tests finds a gap between this spec and A3 or A4, the addendum wins, and the PM is asked to amend.
- **Candle store wiring (F4.AC9).** F4 (wave 2) owns the store and a request interface. The set of coins with an open share, shadow or mirror comes from F12 (wave 4) through that interface, so F4 tests use a stub set. F21 wires the two together, and the end-to-end candle fixture runs in F21's integration suite.
- **Fill audit (F12.AC10)** is owned by F12 and uses F3's `userFillsByTime` and F4's store interface only.

**File-ownership map.**
- A feature may create or modify only the paths it owns.
- Shared files have one owner, and other features change them only through a small CTO-serialized commit on the epic branch before cutting or rebasing their branch.
- Tests live under `tests/<area>/`, owned by the same feature.

| Feature | Owns (create or modify) | Reads, or uses through interfaces only |
|---|---|---|
| F1 | Project metadata file and lockfile (**shared**; dependency additions are CTO-serialized); `engine-path-set.txt`; `src/copytrade/core/**` (config loader, ceilings, mode, money/units, clock, secrets, domain types, events); `src/copytrade/cli/main.*` (subcommand registry); `config/platform.*`; `tests/core/**` | – |
| F2 | `src/copytrade/ledger/**`; `src/copytrade/cli/ledger.*`; `config/ledger.*`; `tests/ledger/**` | core |
| F3 | `src/copytrade/hl/**`; `config/hl.*`; `tests/hl/**` | core, ledger |
| F4 | `src/copytrade/recorder/**` (writers, compressed day-partitioned format with stream and transport hashes and segment records, hourly candle store, disk guard, and the store **interface** with its local implementation); `src/copytrade/cli/recorder.*`; `config/recording.*`; `tests/recorder/**` | hl, ledger |
| F5 | `src/copytrade/scoring/**`; `config/scoring.*`; `tests/scoring/**` | core; hl and recorder interfaces |
| F6 | `src/copytrade/selection/**`; `config/selection.*`; `tests/selection/**` | scoring, hl, recorder, ledger |
| F7 | `src/copytrade/signals/**`; `src/copytrade/cli/latency.*`; `config/markets.*`; `tests/signals/**` | hl, ledger |
| F8 | `src/copytrade/calendar/**`; `data/inputs/macro_calendar.*`; `config/calendar.*`; `tests/calendar/**` | core |
| F9 | `src/copytrade/filters/**` (including the liquidity-tier computation and the tier table in force); `config/filter.*`; `config/tiers.*`; `tests/filters/**` | signals, calendar, recorder (store interface) |
| F10 | `src/copytrade/risk/**` (gate, sizing, caps, automatic leverage, kill-switch state); `src/copytrade/cli/killswitch.*`; `config/risk.*`; `tests/risk/**` | paper (broker interface and liquidation model), ledger |
| F11 | `src/copytrade/paper/**`; `config/paper.*`; `tests/paper/**` | recorder, hl, ledger |
| F12 | `src/copytrade/positions/**` (shares, exits, mirroring, reconciliation, missed-exit detector, leader-fill audit, candle-priced mirror and shadow fills, shadows); `config/exits.*`; `tests/positions/**` | risk, paper, signals |
| F13 | `src/copytrade/recovery/**`; `config/restart.*`; `tests/recovery/**` | positions, hl, recorder |
| F14 | `src/copytrade/telegram/**` (including `/stats`); `src/copytrade/reports/**`; `config/telegram.*`; `tests/telegram/**` | risk, positions, ledger, llm interface. **Never** evaluation or baselines (F14.AC6). |
| F15 | `src/copytrade/llm/**`; `config/llm.*`; `tests/llm/**` | ledger |
| F16 | `src/copytrade/replay/**`; `src/copytrade/cli/replay.*`; `config/replay.*`; `tests/replay/**` | signals, filters, risk, paper, positions, recorder |
| F17 | `src/copytrade/run/**`; `src/copytrade/cli/run.*`; `tests/run/**` | core, ledger, calendar, filters (tier table), archive (health) |
| F18 | `src/copytrade/evaluation/**`; `config/eval.*`; `tests/evaluation/**` (including golden literals copied from E16) | ledger |
| F19 | `src/copytrade/baselines/**`; `config/baseline.*`; `tests/baselines/**` | evaluation, paper (fill model), recorder, ledger (downtime intervals, tier records) |
| F20 | `src/copytrade/reporting/**`; `src/copytrade/cli/report.*`; `config/report.*`; `tests/reporting/**` | evaluation, baselines, replay |
| F21 | `src/copytrade/app/**` (supervisor and wiring); `src/copytrade/cli/app.*`; `tests/app/**`; `docs/sdlc/copytrade-v1/run-worktree.md` | everything |
| F22 | `src/copytrade/okx/**`; `config/okx.*`; `tests/okx/**` | ledger |
| F23 | `src/copytrade/archive/**` (uploader, verifier, pruner, archive-backed store implementation reading every ledgered destination newest first, destination ledgering, ledger backup and restore, cost projection); `src/copytrade/cli/archive.*`; `config/storage.*`; `tests/archive/**` (including the S3-compatible stub) | recorder (store interface, day files), ledger, core |

**Collision rules.**
1. The config tree is split one file per area, so parallel features never edit the same config file. The config hash covers all of `config/**`.
2. `src/copytrade/core/` domain types belong to F1. A later change is a CTO-serialized commit.
3. The CLI registry (`cli/main.*`) discovers `cli/<area>.*` files, so features don't edit it.
4. `engine-path-set.txt` lists directory globs, so new modules under `src/copytrade/**` and `data/inputs/**` don't require editing it.
5. `storage.ledger_dir` and `storage.recordings_dir` stay in `config/platform.*` (F1). Every other `storage.*` key lives in `config/storage.*` (F23).
6. Readers of recordings (F9, F12, F13, F16, F19, F20) depend only on F4's store interface. F23 provides the archive-backed implementation, with both-hash verification on every read, the every-ledgered-destination read order and the lost-file gap rule (F23.AC3, A4.8), and F21 wires it in, so no reader changes when F23 lands.
7. **Run-version startup guard (A3.4).** F17 owns the guard in `src/copytrade/run/**` that F17.AC2/AC3 describe. F4 and F23 ship before F17, and only write their `component_start` records (F4.AC8). When F17 lands, a small CTO-serialized commit wires the guard into the recorder and archive entry points (`cli/recorder.*`, `cli/archive.*`). F21 wires it into `app/**`, and its integration suite proves the recorder pinning end to end (test 24). A run can't start before F21 passes /verify, so no run exists without the guard.

---

## 11. Assumptions for the PO to confirm

None of these contradicts a PO decision. Each fills a gap the PO hasn't ruled on. Defaults apply unless the PO says otherwise before /tests closes.

**Status (Amendment 1, 2026-09-29):**
- **Accepted by the PO** ("Other points OK"): A1, A3, A5, A7, A8, A11, A12, A13, A15 and A16.
- **Replaced by PO decisions** (Spec review, `decisions.md`), rewritten below: A2, A4, A6, A9, A10 and A14.
- **New, pending PO confirmation:** A17 to A23. Each follows from applying the Spec review decisions.

**Status (Amendment 4, 2026-09-29):**
- **A20 is replaced by edge-hypothesis A4.2** and is no longer an assumption.
- **A25 is confirmed** by A4.11.
- **A26 is new** (below), for the A4 author or PO to confirm.
- **PO action:** DoD item 11 needs the PO's re-acknowledgement of §14 items 9 and 10 as rewritten by A4.9.

**Status (Amendment 2, 2026-09-29):**
- **Rewritten to match edge-hypothesis A3:** A4 (A3.1), A14 (A3.2), A16 (A3.4) and A20 (A3.1).
- **Resolved by A3.3:** A17. It is no longer an assumption.
- **New:** A24 and A25.
  - A24 is pending PO confirmation.
  - A25 is pending quant-researcher confirmation. It interprets frozen text.
  - The parts of A20 that A3 doesn't pin are also for the quant-researcher.

| # | Assumption | Why it matters | Alternative |
|---|---|---|---|
| A1 | **Exits:** initial stop = 2 × ATR(14) on 1h candles (no "structure" stop). TP closes 50% at +2R. After +1R the stop trails at 2 × ATR from the best mark and never widens. | "TP is config" in the brief; this is the risk-research default, and V3, V4 and V5 vary it | A single full TP at a fixed R, or no TP (V5) |
| A2 | **[PO decision, Spec review A2]** **Leverage** is chosen automatically per open or add: the lowest value that fits the margin, up to 5x for alts and 10x for BTC, ETH and SOL, and only while the liquidation distance stays ≥ 3 × the stop distance for every share. Otherwise the signal is refused. Risk per trade is unchanged, because it is set by the stop (F10.AC4, F10.AC10). | More room for positions on $300 | – (decided) |
| A3 | **Loss limits** use marked-to-market equity. The daily limit resets at 00:00 UTC (21:00 BRT); the weekly one on Monday 00:00 UTC. Loss halts are rule-based and are **not** downtime for P5. | Defines when halts start and whether they cost the run | Count halts as downtime (stricter on P5) |
| A4 | **[PO decision, Spec review A4; exact rule edge-hypothesis A3.1]** A **missed exit** is an exit not mirrored within 60 s, outside process-down and pre-resync data gaps, or one that the restart reconstruction couldn't settle (§1). A late mirror during `/pause` or another entry pause is a missed exit. The trade counts at min(actual R, mirrored lo R), where the mirror is built like the `/flatten` shadow and resolves recording gaps stop first. The run FAILs if more than 3 missed exits fall in `[t0, T_eval]`, counted over all trades including those opened after the 300th, or if any missed-exit trade cost more than 1R against its TP-first mirror. Every missed exit alerts and is go-live blocker ME until explained and fixed. A FAIL by F2 is an engineering failure (K13). The 60 s lag is now FROZEN (A3.1). The PO's acknowledgement of edge-hypothesis §14 item 9 is pending (DoD item 11). | The PO wants a FAIL only when it costs money; a bug must never help the verdict | – (decided) |
| A5 | **Trend, funding, OI-drop and premium filters start as record-only.** Before run 1 they are either calibrated on ≥ 1 week of recorded data and switched to enforce, or left record-only; then frozen. Volatility halving at the 90th percentile is enforced from the start. | There is no data behind any threshold (OF); inventing them would be strategy by folklore | Enforce hand-picked thresholds now |
| A6 | **[PO decision, Spec review A6]** **Coin tiers** are assigned automatically from measured liquidity (book depth within a band and 24h volume, from our recordings). Tier 1 gets 0.3% slippage / 0.1% spread, tier 2 gets 0.8% / 0.3%, and coins below the floor are skipped. Liquid meme perps (DOGE, kPEPE, WIF) trade when they qualify. The table is recomputed daily and frozen at run start with the config hash. Default thresholds are in A22. | The PO wants more coins, including big meme perps, without trading thin books | – (decided) |
| A7 | **Exposure caps:** total open risk 5%; per coin 1.5%; BTC bucket (correlation ≥ 0.6) 3% same direction; per leader 1.5%; share risk after adds ≤ 1%; notional per position ≤ 1 × equity; ≤ 30 orders/min. | The brief names these caps without numbers except "≤ 10 positions" | Other values within the ceilings |
| A8 | **OKX** is record-only and off by default. H1 is pre-registered on Hyperliquid wallets only, so OKX signals can't enter run 1. F22 may be dropped. | Brief: "lowest priority" | Drop F22 now |
| A9 | **[PO decision, Spec review A9]** **LLM** cap is $5/month (ceiling $20). There is no news source, paid or free, in v1. The "news summary" is built from the calendar and our recorded market metrics. J7 Tracker was not evaluated (§8). The LLM has no vote. | News would only affect the explanation text | – (decided) |
| A10 | **[PO decision, Spec review A10]** **Disk and storage.** The PC has ~100 GB free. Recordings are compressed (estimate ≤ 1.5 GB/day, VAL-R). Each finished UTC day is uploaded to Backblaze B2 or Cloudflare R2, verified by checksum, and only then pruned locally, keeping 7 days. The ledger stays local, with a daily encrypted cloud backup. Replay, B0d and evaluation read local or cloud transparently. A disk guard alerts, then stops recording at a floor without blocking exits. Budget ≤ $5/month (F4, F23). **The PO chooses B2 or R2 and sets the bucket and credentials as environment variables.** B2 pricing is the default for the cost projection. | ~350 GB of raw recording would not fit | – (decided) |
| A11 | **Epic done = run-1-ready** (§9). Paper runs start after /ship, on your go, and are tracked in the run register. | A run takes 30–67 days | Keep the epic open until the run-1 verdict |
| A12 | **`/flatten` PIN:** 3 wrong attempts in 15 min lock the Telegram flatten for 15 min (the CLI still works). The bot deletes the PIN message. | Abuse protection | Other limits |
| A13 | **Reports** are sent daily at 00:05 UTC (21:05 BRT) and weekly on Monday at 00:10 UTC. | Timing | Other times |
| A14 | **[PO decision, Spec review A14; exact list edge-hypothesis §5.5, A3.2]** **Interim visibility.**<br>• **You see:** per-trade results, USD P&L, counts and progress to 300.<br>• **`/stats` shows:** USD P&L, win rate, average R (labelled "descriptive, not the verdict"), drawdown (the P3 quantity), per-trader figures and progress. It also shows three operational counters: downtime used against the 2% budget, missed exits with their costs, and pending deploy rulings.<br>• **Never computed or shown before `T_eval`:** the gate CI by any method (or any standard error, t statistic or p-value), B0d, D, P2c, FR1–FR6, K9/S4, P6, G, the cross-day diagnostics, or any verdict preview.<br>• **Deploys:** a mid-run deploy whose stated reason is an interim result can only be ruled ABORTED (F17.AC3).<br>• **B0d:** it never draws start times inside `/pause` or other downtime (F19.AC2).<br>• The PO's acknowledgement of edge-hypothesis §14 item 10 is pending (DoD item 11). | Full visibility for the PO; the 2-run α split keeps the family-wise false-PASS rate | – (decided) |
| A15 | **Signal age** can be lowered after the latency measurement, never raised above 5 s. If the measured p95 is above 5 s, that comes back to you as a decision, not a config change. | "Never chase" [PO D7] | – |
| A16 | **Recorder runs early; during a run it runs only the run commit** (amended for edge-hypothesis A3.4; the pre-run part is unchanged and PO-accepted).<br>• **Before a run:** after F4 passes /verify, the recorder runs continuously from its own worktree on the epic branch, before /ship, to start day-1 recording. F23 joins it there after its own /verify. Between runs, the recorder may be updated there freely.<br>• **At run start:** the recorder and archive processes are restarted from the run worktree at the run commit, and `run start` refuses until they are (F17.AC2). The short switch-over gap is before `t0`.<br>• **During a run:** the recorder is engine code. It runs only from the run worktree, and any change to it is a mid-run deploy under the auditor-ruling rules (F17.AC3). | ≥ 7 days of recording is a run-1 precondition; the evaluation reads the recordings, so the recorder must be frozen with the run | Wait for /ship, which delays run 1 by ≥ 7 days |
| A17 | **Resolved by edge-hypothesis A3.3 (`cost.fallback_tier_rule`, FROZEN).** A major is a coin in the tightest liquidity tier (tier 1) in the tier assignment in force at the decision time of the trade or replication, read from the ledger's tier records. Every other tier is an alt. A coin with no tier record is an alt for copies and a major for random-time baselines (§1; F13.AC1, F16.AC6, F19.AC4). Fallbacks apply only where our recording is missing. | – | – (no longer an assumption) |
| A18 | **Below the disk floor, opens and adds are refused** (`disk_low`, counted as downtime), as well as recording stopping. Exits always continue. | A trade opened while nothing is recorded has no B0d window or replay data, so it could only hurt P2c and P6 | Keep trading while recording is stopped |
| A19 | **Leverage starts at 1x** (`risk.leverage_min` = 1). At each open or add, the merged position's leverage is re-chosen as the lowest that fits the whole position. Early positions therefore use more margin, and later ones may need higher leverage or be refused `insufficient_margin`. | "Lowest value that fits" read literally; lower leverage keeps liquidation furthest away | Start at 2x or 3x, which leaves more free margin for later signals |
| A20 | **Replaced by edge-hypothesis A4.2 (FROZEN; no longer an assumption).** With no recorded book within 5 s of the fill time, a mirrored action fills on the 1m candle, else the 1h candle, from the hashed candle store (F4.AC9). lo = the worst price for our side + 8 bps, hi = the best price for our side + 2 bps, plus the taker fee, with no delay term and no tier table. SL/TP fill at the trigger or a gapped-through open. `/flatten` shadows use the lo prices. A mirror uncomputable after 72 h costs more than 1R (F2), with lo R = actual R and mirror exit = the real close (F12.AC9). "No verdict while pending" is not adopted.<br>**Superseded text follows, kept for history only. Where it differs from the above, the above wins.**<br>**Fixed by A3.1:**<br>• the mirror is built with the `/flatten` shadow machinery from the first missed leader event<br>• each mirrored leader action is decided at its exchange timestamp + `copyreplay.delay_ms` and filled at the book recorded at that time + `paper.ack_delay_ms`<br>• over a recording gap, the SL/TP path uses exchange 1h candles, with ambiguous bars resolved stop first (lo, gate) and TP first (hi, cost)<br>**Not pinned by A3; PM default for the quant-researcher to confirm:**<br>(a) **No recorded book at a mirrored leader action.** The fill is the exchange 1m candle open at the fill time ± the fallback half-spread and delay slippage, plus the taker fee. The lo mirror uses the copy-side tier rule (untiered = alt). The hi mirror always uses the major values: generous for the mirror, so a gap can't hide a cost, in the spirit of A3.1's TP-first rule.<br>(b) **Neither a book nor exchange candles are available.** No cost is guessed. It stays pending and is retried, and the verdict is not computed until it exists. This replaces Amendment 1's "uncomputable counts as > 1R", because A3 defines F2 only through `p4_breach`. | A3.1 fixes the rule but not the fill when our book is missing | (a) Use the copy-side tier rule for both lo and hi (a gap could then understate the cost). (b) Keep "uncomputable counts as > 1R" (a FAIL that A3 doesn't define). |
| A21 | **Storage policy details.** (a) At ≥ 80% of the $5 projected monthly cost, alert daily but **keep uploading**: losing run data costs more than a small overage, and at ≤ 1.5 GB/day the projection is under $2. (b) `run start` refuses while a finished day older than 2 days is unarchived, or no ledger backup has verified in 48 h. | Never lose run data silently; start a run only with a working backup | (a) Stop uploading at the cap. (b) Allow a run to start without a verified backup. |
| A22 | **Tier default thresholds** (VAL-R priors, not measurements): tier 1 = median thinner-side depth ≥ $1,000,000 within 0.5% of mid **and** median 24h volume ≥ $200M; tradable floor = ≥ $50,000 **and** ≥ $10M; 7-day lookback; ≥ 80% coverage; recomputed every 24 h. Expected, but not measured: BTC and ETH in tier 1, SOL around the line, and DOGE, kPEPE and WIF in tier 2. Our orders are ≤ $300, so the floor keeps each order ≤ 1% of depth. | Thresholds need numbers before recordings exist; the readiness report replaces the guess with data | Other thresholds within the bounds in §3.5 |
| A23 | **`/stats` shows realised figures**, not gate-adjusted values (not min(realised, shadow) for flattened trades, and not min(actual, mirrored) for missed exits). It is labelled "descriptive only". With no run active, it covers the time since the dry-run start or the last run end. | Gate-adjusted numbers would move `/stats` closer to a verdict preview | Show gate-adjusted R, labelled as such |
| A24 | **K13 is enforced by the engine** (F17.AC9). Run 2 can't start while any missed exit from run 1 lacks a resolution record: a written root cause, a fix commit that is an ancestor of the run-2 commit, and a regression test ID. A resolution record doesn't clear go-live blocker ME, which is cleared only at /go-live. | Edge-hypothesis K13 and §5.3 say to explain and fix every missed exit before run 2. A checklist item could be skipped. | Keep it procedural: the PO or CTO checks before starting run 2, with no engine refusal |
| A25 | **Confirmed by edge-hypothesis A4.11 (FROZEN).** **What §5.5's "Nothing else is shown" covers.** Run-result content is any figure computed from the outcomes of our trades, shadows, mirrors or any baseline. Before `T_eval` it appears only in the `/stats` list and each trade's own post. Operational content stays allowed, never with a pass/fail label. Consequence: the daily and weekly reports omit USD P&L while a run is active before `T_eval` (F14.AC7). The original reading follows. The spec reads edge-hypothesis §5.5 and test 7 as limiting **run-result and evaluation statistics**. That leaves the existing operational content, which states nothing about the edge:<br>• `/status`: mode, feed health, disk, archive state and cost<br>• `/traders`: score and rank<br>• trade posts: the leader's own scoring-window figures<br>• daily and weekly reports: refusals by reason, unexecutable count, followed-set changes, tier changes, archive state and storage cost<br>Any new run-result metric still needs a spec change checked against §5.5 (F14.AC6). | Test 7 says every command and report serves "only the 5.5 list"; read literally, it would remove `/status`, `/traders` and most of the reports | Restrict every command and report to the §5.5 list literally (drops most operational content), or amend A3 to list the operational content explicitly |
| A26 | **Points that A4 leaves open, with PM defaults for the A4 author to confirm.**<br>(a) **Tier cadence.** `tiers.recompute_interval_h` has a range of 1–168 h, but A4.7 fixes 24 h during a run. Default: the key stays at 24 in the frozen config, and it is part of the config hash, so changing it mid-run is ABORTED.<br>(b) **Stream and transport hash.** The stream sha256 covers the canonical serialised records, and the transport sha256 covers the stored file bytes (F4.AC7). A4.8 a names the two hashes but not their scope.<br>(c) **Reports before `T_eval`.** The daily and weekly reports omit USD P&L while a run is active (F14.AC7), as a consequence of A4.11. `/stats` and each trade's post carry it.<br>(d) **Incremental-cost breach.** A breach by an incremental cost alone (the trade cost below 1R) is F2, as A4.3 says.<br>(e) **`/flatten` mirror shadows and settled-gap trades** use the lo prices where inside a gap. | A4 pins the rules but not these details | (a) Make the in-run cadence a fixed constant. (b) Hash the compressed bytes only. (c) Keep USD P&L in reports and amend A4.11. |
