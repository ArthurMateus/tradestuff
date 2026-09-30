epic: copytrade-v1
branch: epic/copytrade-v1
gate_passed: build (F1 only)
touches_money_path: yes
touches_strategy: yes
has_ui: no
features: F1=approved+merged (F1.tests_commit=75c3221; advisories A2,A4,A5 queued), F2=approved+merged (tests_commit=6ba583c; round-2 tests a6340a7; build loops=2), F3=approved+merged (tests_commit=364d97b; round-2 tests d223541; fix 9c0bb2c; build loops=2), F4=approved+merged (tests_commit=5206439; round-2 tests f5f71bf; fix f81c90e; build loops=2), F5=approved+merged (tests_commit=651812a; round-2 tests 490d783; build loops=2), F6=queued, F7=approved+merged (tests_commit=621c934; round-2 tests a4bbf3b; advisories 19078bd; build loops=2), F10=queued, F11=approved+merged (tests_commit=7b59099; 5 build rounds + architect ruling + RISK-26 mini-round; Amendments 7-11; senior-dev APPROVED, reviewer-risk PASS at 3d2d457), F12=queued, F14=queued (stage 1); F8, F9, F13, F15-F21, F23 (stage 2) not started; F22 dropped
loops: tests=0 build=2 review=0 qa=0
escalations_open: none
updated: 2026-09-29T20:00:00Z

Research artifacts:
- research/market-context.md
- research/edge-hypothesis.md (frozen, with addenda A1-A4; A5 pending, see follow-ups)
- research/backtest-audit.md: INCONCLUSIVE
- research/backtest-audit-r2.md: INCONCLUSIVE
- research/backtest-audit-r3.md: VALID
- research/backtest-audit-r4.md: VALID
- research/backtest-audit-r5.md: VALID (light)
- research/run-register.md
- trading-compliance skipped (no paid users, no third-party accounts, no live money). It re-runs at /go-live.

PO acknowledgements: section 14 items 1-10, with the corrected wording of 9-10 pre-approved (see docs/product/decisions.md).

## Pipeline rules for this epic (PO decision 2026-09-29, token economy)
- **Review panel:** the full panel runs only on money-path features: F9, F10, F11, F12, F13, F16, F17, F18, F19 and F20. Every other feature gets reviewer-security, reviewer-changes and reviewer-general.
- **Test design:** one test-designer per feature, followed by the test-reviewer.
- **Rulebook audits:** none after the A4 check, unless the verdict logic changes.
- **F22:** dropped.

## Lean two-stage build plan (PO decision 2026-09-29: working product in about 1 week on Claude Pro)
This replaces the review-panel and test-design rules above wherever they conflict.

**Stage 1 (week 1): the bot runs in paper mode and posts to Telegram.**
Features: F1, F2, F3, F4, F5, F6, F7, F10, F11, F12, F14. Also included:
- the simple economic-event pause (F8) folded into F10
- F23 cut to "compress, then upload each finished day"

Stage 2 (weeks 2–3, while the recorder collects its 7 days): F17, F18, F19, F20, F13, F16, F21, F9 (advanced filters) and F15.

**Per feature (lean loop):**
1. one test-designer writes failing tests
2. developer
3. senior-dev
4. reviewer-risk, on money-path features only (F10, F11, F12; later F13, F17–F20)

The test-reviewer, the 3–8 reviewer panel and the architect run only when something is stuck. `/qa` runs once at the end of stage 1. No rulebook audits.

**Model:** the main session runs on Sonnet 5.5. Opus is only for reviewer-risk, quant-researcher and backtest-auditor. All agents run at medium effort. A new session for the build is recommended (small context, reads the repo).

**Honest caveats:** "1 week" is a target, since Pro usage limits can't be seen from here. Lighter review means more bugs surface at QA or in the dry run. That is acceptable in paper mode, and the rulebook still blocks real money.

## Follow-ups before run 1 (not blocking the build)
- BT5-1, BT5-2 and BT5-3 (`research/backtest-audit-r5.md`, VALID): fix them in a short Addendum A5 while building F18, with no new audit (token-economy rule). Correct item 9's wording for BT5-1, and have the PO confirm it.

Pending outside the pipeline: the PO runs hl_sample.py once and sends back summary.json. It feeds the VAL-S config keys.

Spec approved by the PO on 2026-09-29 (including the change that daily/weekly reports show no USD P&L while a run is active). Feature branches feat/copytrade-v1/<Fn>-<name> exist for stage 1.
Next: F2 senior-dev, F3 and F5 developers in progress (worktrees in ../wt/F2, F3, F5). Then F6, F7, F4, F10, F11, F12, F14 per plan. Open: F1 follow-up A2,A4,A5; F2 heartbeat owner; F3 fixtures are synthetic (replace with hl_sample.py recordings before /verify); F3 min-sample key for success-rate trigger.

## Open follow-ups (logged by CTO)
- F5 M14 copy replay omits the trailing stop and mirrored adds/partials, but EH M14 and F5.AC1 include them. Spec deviation: PO/PM to accept, or a follow-up sharing F12's exit code. Resolve before go-live (feeds G10 and score component 2).
- F5 hard-coded gaps (own-snapshot 1 h, perpMonth 6 h) should become `scoring.*` config keys (F1 schema + spec change). The 30-day recent window is normative in EH M17.
- F5 input hash excludes tid (an existing test relies on it); revisit with a tid-ordering hash.
- F3 adapter contract: Fill.liquidation is set by F3 (also `"iquidat" in dir`); F3 must map isSnapshot and liquidation into F5's Fill.
- F3: no concrete WsConnector (dependency decision for F21); success-rate trigger has no min-sample key; F1 cross-key check ping interval < feed.stale_after_s.
- Brazil: on/off-ramp, tax, and HL geo status unverified; check before /go-live (BCB deadline 2026-10-30).

## PAUSED (PO decision: pause after F3, token budget). Resume here.
Merged into epic: F1, F2, F5. F3 is on origin/feat/copytrade-v1/F3-hl-client (worktree ../wt/F3 may be gone; re-create from the branch and merge epic in).
F3 senior-dev round 1 = CHANGES REQUIRED:
- BLOCKING 1 (code bug): a malformed WS fill message is dropped without opening a gap or resync (ws.py _handle_message, HlSchemaError and unreadable-frame paths). Fix: open a gap for the wallet (or every wallet on the connection if unidentifiable) and resync via userFillsByTime. Needs a new test first (test-designer), then developer.
- BLOCKING 2 (test gap + semantics): stale-timer boundary in ws.py tick and is_stale (`>` vs `>=`); pin 1 ms before / exactly / 1 ms after. Spec says "no message or pong for feed.stale_after_s"; if stale at exactly N s, change to `>=`.
- BLOCKING 3 (test gap): access thresholds: RECOVERY_MIN_SUCCESS_PERCENT 95, `>=` at the 95% bucket, access-error window expiry, 403/451 count window boundary.
- Advisory: ws timing boundaries and untested ping clamp (3/4 of stale_after_s); schema 10-min window and alert-episode reset; budget `weight > budget`; pass isSnapshot to the sink; paginate userFillsByTime past ~2000 fills or refuse to close the gap; cap seen_tids and held; resync blocks tick (D8); late item weight; min-sample rule for access_degraded (spec amendment); host allow-list; sink failure after record_downtime re-writes data_gap.
Route: test-designer (items 1-3 tests plus advisory boundaries), then developer, then senior-dev re-review (round 2 of 3). Then merge F3 into epic.
Next after F3: F6, F7, F4 (then F10, F11, F12, F14). Cost so far about 0.5M subagent tokens per feature; consider batching all test gaps into one round and limiting mutant runs to money-path modules.
Other open follow-ups are listed above.

## Cost-cutting rules (PO approved 2026-09-29; apply from the F3 fix round on; they refine the lean plan)
1. **One complete first review.** The senior-dev prompt must ask for ALL findings in round 1: every blocking test gap, code bug and advisory, each tagged test-designer or developer, so there is one designer round then one developer round. A round-2 review only verifies; it does not open new blocking items unless a fix regressed something.
2. **Mutation checks only on money-path modules** (risk, paper, positions, evaluation, baselines; F10/F11/F12 and later F13, F17-F20). Other features: senior-dev reads the code and runs the suite, ruff and mypy, with at most ~10 targeted hand mutants on fail-closed guards. No broad mutant sweeps.
3. **Advisory-only gaps do not get a second designer round.** Only blocking items (code bug, spec-semantics, money or fail-closed guard gaps) go back to the test-designer. Advisories are logged as follow-ups in STATE.md.
4. **Combine small features in one pass** where dependencies allow (one test-designer, one developer, one senior-dev for the pair): candidates F6+F7 (after F3 and F5 are merged), F4+F14 if independent. Per-feature branches and ACs stay separate; the agents share one worktree per pair. Money-path features (F10, F11, F12) are never combined and always get reviewer-risk.
5. Never run mutation tools or the test suite from the CTO session; senior-dev verifies.

## F3 approved and merged (2026-09-30, scheduled fix round done)
Senior-dev round 2 verify-only: APPROVED. Blocking items 1-3 fixed (bad WS frame opens gap and resync; stale at exactly feed.stale_after_s with `>=`; access thresholds pinned). The PAUSED section above is superseded. Resume point: **F6+F7 as a pair** (deps F3 and F5 now merged), then F4, then F10, F11, F12 (never paired, reviewer-risk), F14; a minimal supervisor question is open with the PO (see chat).
F3 advisories still open (follow-ups, not blocking): bad-frame flood costs N CRITICAL REST calls per tick (add cooldown or reconnect after K bad frames); no test for the unidentifiable-frame-naming-unsubscribed-wallet branch; no exact `gap.start_ms` assertion or earlier-start-preserved test (senior-dev could not run mutants in round 2); resync pagination past ~2000 fills; seen_tids/held caps; isSnapshot to sink; min-sample rule for access_degraded; host allow-list; sink failure after record_downtime re-writes data_gap; concrete WsConnector needed by F21.

## F4+F7 pair pass (2026-09-30)
Tests pushed: F4 5206439 (170 cases), F7 621c934 (154 cases). Developer pass next (one agent, both worktrees ../wt/F4, ../wt/F7), then senior-dev (full first review), then F11 (money-path, alone, reviewer-risk), then F6 (needs F4), F10, F12, F14.
Decisions: Amendment 6 (stdlib lzma for F4.AC7; PO to confirm). PO decision open: WebSocket connector dependency for F7 real latency run / F21. F7 pins: flip of a pre-existing position = close leg `pre_existing`, open leg normal; `latency measure --ledger-dir` must refuse storage.ledger_dir. F4 pins new ledger kinds (recording_segment, recording_file_closed, day_complete, component_start, component_heartbeat, downtime kind disk_low); the F3 downtime adapter must use the same `downtime` kind and keys. F4 candle files are per coin/interval/UTC hour.

## F7 approved and merged (2026-09-30)
Senior-dev verify-only: APPROVED. Follow-ups (advisory): (1) if sink.on_signals raises inside the finally in SignalDetector.on_fills while a LedgerWriteError propagates, the sink error replaces it (ledger error only in __context__): F9 should catch Exception at this boundary, or log the ledger error first; a non-OSError alert failure skips sink delivery for already-ledgered signals (deliver the sink first or nest try/finally). (2) Mutation re-run of the 3 round-1 guards was not run by senior-dev (sandbox), designer's kill table is the evidence; re-run at /verify. (3) A pre-existing coin that goes flat through an unparseable/out-of-scope fill stays held: needs a spec decision and a new field in the ledger `signal` record. (4) Snapshot fills look live (F3 does not pass isSnapshot): F9 must refuse stale opens and ignore exits for positions it never opened; F3 follow-up to pass isSnapshot. (5) `dir` whitelist is brittle: an unlisted valid perp `dir` on an exit becomes `unparseable` (alerted, never traded); watch in QA. (6) f7 `latency measure` real run needs a WebSocket connector and a clock-offset source (PO dependency decision, open).

## F4 approved and merged (2026-09-30)
Senior-dev verify-only: APPROVED (m1, m8, transport-hash-skip and alert-stamp mutants die; m5, the second final-name read, survives: benign race guard). Follow-ups (advisory): (1) restart is bricked by RecordingIntegrityError raised in the Recorder constructor for a .part shorter than its last sealed segment, a corrupt sealed block or a mismatching closed .part: treat as a lost file (gap, logged and alerted) per D2/F23.AC3 (needs PM/PO agreement, test pins current behaviour). (2) Blocking work inside the tick: sealing compresses every due file in one tick, CandleStore does up to 2 REST calls per coin per hour in a tick; stagger sealing (offset by a hash of the key) or move compression and REST off the poll thread; F21 dry run must measure. (3) Reader cost: RecordingReader.coins() decodes every block just to test existence, block cache of 64 thrashes at 250 coins, scan is not lazy; unpinned readers rebuild the ledger index per call. (4) The segment chain link (prev_hash) is written but never verified on read: add a chain verifier for F23/F17. (5) No test pins alert-retry after a failed low-disk alert send. (6) CandleStore._absent grows without bound (small). (7) After a disk-floor resume, funding history refetches from the last stored point (confirm this fits "never back-filled"). (8) Recording compression is stdlib lzma (Amendment 6, PO to confirm); 250-coin ratio check <= 25% belongs to F21.AC2. (9) Concrete adapters (market WebSocket, metaAndAssetCtxs, fundingHistory, leaderboard host, DiskProbe walking to the nearest existing parent) are F21.

## F11 tests done; RESUME POINT (2026-09-30)
F11.tests_commit=7b59099 on origin/feat/copytrade-v1/F11-paper (plan: 05-test-plan-F11.md on that branch, 16 pinned ambiguities). Next: F11 developer (scheduled run ~06:57Z, trig_01G4UkqvHSvwABBzaxcBadsE), then senior-dev (one complete review) + reviewer-risk (Opus) in parallel, one fix round, verify-only, merge. Then F6 (unblocked), F10, F12, F14.
Gate token (F10 builds against it): `GateAuthority(key)`, `authority.issue(intent)` after risk_gate.check approves; token `GateToken(token_id, intent_digest, mac)` bound to the exact intent, single-use, consumed even if the order is then refused; intents OrderIntent (OPEN/ADD/REDUCE/CLOSE) and StopIntent (SL/TP); liquidation, delisting and stop triggers need no token; `liquidation_price(...)` is a pure function F10 reuses. F21 adapter must map F4 FundingPoint/AssetContext.oracle onto FundingSource.
Spec decisions pinned by the designer that need PO/PM confirmation (defaults stand until then): (1) book age window [decided+ack, decided+ack+5000] with no lookahead; (2) entries cancel a partial-fill remainder, exits re-queue and retry every exits.retry_interval_s; (3) zero depth or one-sided book: opens rejected `no_depth`, exits retry; (4) **liquidation loses margin minus maintenance margin, not the full margin (close at the liquidation price, P&L = move minus fees, loss bounded by margin): PO to confirm, AC5 wording says "loses its margin"**; (5) liquidation price = entry*(1 -/+ (1/L - 1/(2*maxLev))), rounded to nearest valid price; (6) funding: positive rate means longs pay, strict open < boundary < close, missing funding retried and alerted once as funding_missing; (7) delist settlement pays the taker fee; (8) unfilled-exit alert counts from decision time; (9) VWAP exact Decimal, fee = notional*bps/10000 unrounded, sizes round down, min-notional on rounded size (full reduce-only close exempt); (10) meta refresh failures keep last meta with no maximum staleness (A2 may want one); (11) broker re-validates its config keys and fails closed; (12) ledger append failure raises and the broker stays failed closed (state-before/after-append not pinned). Not covered by F11: restart reconstruction (F13), merged position management (F12), opposite-side netting (spec silent).

## F11 STATE (2026-09-30, PAUSED at 95% usage): RESUME HERE
Branch origin/feat/copytrade-v1/F11-paper (worktree ../wt/F11; re-create from the branch and merge epic in if gone). Rounds so far: r1 senior-dev+reviewer-risk CHANGES REQUIRED/BLOCK (RISK-1..7, PO approved liquidation reading B = Amendment 9), r2 verify (RISK-17 new blocker), r3 verify: senior-dev APPROVED, reviewer-risk BLOCK (RISK-21 two clocks, RISK-22 marks walk time forward, both upheld). Loop cap reached, so the architect ruled RETURN TO DEVELOPER: replace Amendment 10 with **Amendment 11** (clamp, never ignore; broker time only from advance_to; on_mark/on_delist never move time or call _run_until; stop decided at min(mark time, now) and fills at now+ack; liquidation/delist stamped now; exit decided_at_ms clamped; bad_timestamp alert once per (source, coin), quiet while time is 0; entries more than filter.max_signal_age_ms ahead refused `bad_decision_time`). No PO decision needed (PO informed).
Current step: test-designer (agent a8b67f444f45df343) is updating the round-3 'ignored' tests to 'clamped' and adding tests/paper/test_r4_time_clamp.py; it pushes to the F11 branch. NEXT: (1) confirm that commit is pushed (round-4 section in 05-test-plan-F11.md, some tests fail on purpose); (2) developer: implement Amendment 11 in src/copytrade/paper/{broker,settings,types}.py per the architect's list (replace `_time_is_plausible` with `_bounded_time`, on_mark/_settle_delisting stop calling _run_until, exits use min(decided, now), entries refuse bad_decision_time, docstrings: advance_to is the only source of time, all times are exchange ms), never edit tests; (3) verify-only senior-dev + reviewer-risk in parallel (final); (4) if both approve, merge F11 into epic, update STATE.md, push. If reviewer-risk still BLOCKs: escalate to the PO, do not merge.
F21 contract from Amendment 11: supervisor calls advance_to(ClockSync.exchange_now().ms), not while the clock is unsynced, before feeding marks each loop, heartbeat for a stalled loop (a stalled advance_to means triggered exits queue and never fill, no F11 alert); F10 stamps decided_at_ms in the exchange base; F16 drives advance_to(t) before on_mark(t); F21 24 h dry run shows zero bad_timestamp alerts.
Open F11 follow-ups (logged, not blocking): RISK-8 restart state in memory only (F21 must not wire the broker before F13; pending exits need reconstruction or new ids), RISK-10 late funding not in the trade P&L (F18 must add paper_funding by share_id, or a trade_funding_adjustment), RISK-11 verify-only broker interface and key minimum length, RISK-12 oversized CLOSE refused (F12 contract), RISK-16 stranded dust after an szDecimals cut, RISK-18 stale_decision under mark stream (pin decided_at_ms time base), RISK-20 max meta age for entries, RISK-24 no ledger record of clamps, alert-once logic untested, paper_stop_trigger ledger time untested. Margin is never checked by the broker (F10 must hold the line); opposite-side entries are refused (F10/F12: flip = CLOSE then OPEN after the fill); the gate token binds decided_at_ms, decision_px, exit_reason.
After F11: F6 (unblocked), F10, F12, F14; then stage-1 QA; minimal supervisor question for the PO still open (a first end-to-end paper run needs F21-like wiring); WebSocket connector dependency (PO); Amendment 6 lzma confirmation (PO).

## F11 update (2026-09-30): round-4 tests DONE and pushed
Designer finished: origin/feat/copytrade-v1/F11-paper at 5917300 (plan: round-4 section of 05-test-plan-F11.md on that branch). On the current code 3,801 tests: 3,757 pass, 44 FAIL ON PURPOSE (11 in the reworked tests/paper/test_r3_bad_timestamps.py, 33 in the new tests/paper/test_r4_time_clamp.py); against the designer's scratch reference implementation of Amendment 11 all 3,801 pass; 26/26 mutants killed. NEXT STEP IS NOW THE DEVELOPER (implement Amendment 11 per the architect's list; never edit tests), then the final verify round (senior-dev + reviewer-risk), then merge if both approve. The designer's reference sketch (outside the repo, may be gone): /tmp/claude-0/-home-user-tradestuff/7ebf9c73-bc42-5927-8e6b-58b64010ff1f/scratchpad/f11r4/ref/src. Paused for the PO's usage window (95%).

## F11 ESCALATED TO THE PO (2026-09-30): one narrow blocker left after the architect's ruling
Amendment 11 implemented (branch origin/feat/copytrade-v1/F11-paper at 133fcdf, 3,801 tests pass): senior-dev APPROVED (27/27 new mutants killed), reviewer-risk BLOCK on ONE new item, **RISK-26**: while broker time is 0 (before the first advance_to, including after every restart) `_admit_order` runs no time check, so a fresh broker accepts an OPEN decided 24 h ago (fills at the 24-hour-old book and charges 24 funding hours: a backdated trade) or decided +1 h ahead (fills an hour later at a made-up price), silently (clamp alert suppressed at time 0). Closed and re-verified: RISK-17, 19, 21, 22, 25; RISK-23 closed above time 0.
Required fix (small, reviewer-risk's proposal, consistent with the ruling): in `_admit_order` refuse OPEN/ADD while `_now_ms == 0` (reason `no_broker_time`, add to the SubmitResult docstring); invert `tests/paper/test_r4_time_clamp.py::test_R4_RISK23_an_entry_far_ahead_is_accepted_while_broker_time_is_zero` and add the 24 h-stale case at time 0; exits, stops, marks, delistings unaffected. Mini-round: designer (2 tests) then developer (one check) then reviewer-risk verify only. AWAITING PO GO (protocol: cap reached, PO decides).
New logged follow-ups: RISK-27 a stop and a liquidation in the same mark batch between two advance_to calls become a liquidation (F21: call advance_to before EACH mark message; dry run measures mark-to-advance delay vs ack); RISK-28 late-mark alerts fire at once and ledger times can be out of order (ties to RISK-24); RISK-29 advance_to trusts its input: F21 must guard ClockSync.exchange_now() against jumps; RISK-30 funding edge cases of at most one hour on one share; RISK-31 F10 must stamp decided_at_ms within the tolerance of the loop's advance_to (call advance_to right before submit) or every entry is refused `bad_decision_time` (fails closed but could zero out a paper run). F13 must set broker time before anything else runs when restoring positions.

## F11 APPROVED AND MERGED (2026-09-30)
Senior-dev approved (133fcdf, 27/27 new mutants killed); reviewer-risk PASS after the PO-approved RISK-26 mini-round (3d2d457: OPEN/ADD refused `no_broker_time` while broker time is 0). Merged into epic. Supersedes the two F11 PAUSED/ESCALATED sections above. Normative F11 amendments: 7 (defaults), 8 (review round 1), 9 (PO: liquidation reading B, full margin lost), 10 (superseded), 11 (architect: clamp, never ignore; broker time only from advance_to). RISK-26 closed by `no_broker_time`.
**F11 contracts for later features (must be honoured):**
- F21: supervisor calls `advance_to(ClockSync.exchange_now().ms)` on EVERY loop, BEFORE feeding marks/delistings and before `submit`; not while the clock is unsynced; heartbeat for a stalled loop (a stalled advance_to means triggered exits queue and never fill, no F11 alert); guard `exchange_now()` against jumps (RISK-29: one +1 h sample holds every stop/close fill until real time catches up); a 24 h dry run shows zero `bad_timestamp` alerts; measure mark-to-next-advance_to delay vs the ack delay (RISK-27: a stop and a liquidation in one mark batch between two advance_to calls become a liquidation); do NOT wire the broker before F13 (RISK-8: restart state is in memory only; a deterministic CLOSE client order id re-sent after a restart is refused `duplicate_client_order_id`).
- F10: issue `GateToken`s via `GateAuthority.issue(intent)` after the risk gate approves (single-use, bound to the exact intent incl. decided_at_ms, decision_px, exit_reason; consumed even if the order is refused; fresh token per attempt; `intent_digest` can raise ArithmeticError beyond 120 digits); stamp `decided_at_ms` in the exchange time base and call advance_to right before submit (entries outside [broker time, broker time + filter.max_signal_age_ms] are refused `stale_decision`/`bad_decision_time`, RISK-18/31); the broker NEVER checks margin against cash (F10 holds that line); never send an opposite-side OPEN/ADD (refused `opposite_side_entry`; a flip = CLOSE then OPEN after the fill); the F10 static check should also cover `.issue(` call sites (RISK-11).
- F12: events returned by `on_mark`/`on_delist` include other orders' fills; an oversized CLOSE is refused `exceeds_position` (RISK-12: clamp or handle the refusal); share ids should be unique per coin; exits and stops never depend on meta (use stored rules).
- F13: set broker time (advance_to) before anything else runs when restoring positions; persist consumed tokens or bind tokens to a broker epoch; pending exits need reconstruction or new ids.
- F18: late funding (rate missing at close) posts to cash and the ledger (`paper_funding` with share_id) but NOT into the closed trade's P&L (RISK-10): include `paper_funding` by `share_id` or add a `trade_funding_adjustment`.
Open F11 follow-ups (logged, not blocking): RISK-16 stranded dust after an szDecimals cut, RISK-20 maximum meta age for entries, RISK-24 no ledger record of clamps (ledger times can be out of order, RISK-28), RISK-30 funding edge case of at most one hour on one share, alert-once logic and paper_stop_trigger ledger time coverage, RISK-11 verify-only broker interface and a minimum key length.
Merged features: F1, F2, F3, F4, F5, F7, F11. Next: F10 (needs F11, now unblocked), F6 (needs F4, F3, F5: unblocked), then F12 (needs F7, F10, F11), F14 (needs F2, F10, F12). Open PO items: minimal supervisor question, WebSocket connector dependency, Amendment 6 (lzma) and Amendments 7-11 confirmation.

## v0 evidence gate (PO decision 2026-09-30; supersedes the stage-2 plan until decided)
**Stage 2 is ON HOLD pending the v0 gate.** Do NOT start F8, F9, F13, F15-F21, F23, the verdict/baseline/run-control machinery, or any edge-hypothesis evaluation tooling. Real money stays OFF; paper mode only until the gate is decided.
v0 = F1-F5, F7, F11 (merged) + F6 (selection), F10 (risk), F12 (positions), F14 (Telegram, minimal), built in the lean loop with a cap of TWO review rounds per feature (anything still open is logged as a follow-up, except a BLOCKING money-path finding). Tests run as `pytest -q -x --tb=short`.
When v0 is built and passes review: (1) run /qa once on the v0 bot (paper mode only); (2) tell the PO exactly how to start the bot and the recorder on the Windows PC and what to watch in Telegram (the CTO never starts it); (3) ask the PO to run hl_sample.py (docs/sdlc/copytrade-v1/research/scripts/README.md) and send back summary.json; (4) after 2-4 weeks of paper running, help the PO analyse the results with simple tools (a short script or a spreadsheet), not the full evaluation machinery.
Gate criteria (starting suggestions, the PO may adjust):
- Trade flow: enough paper trades to judge (for example 50-100 or more), and not many signals lost to the $10 minimum order.
- Reliability: no missed exits and no unexplained position mismatches.
- Results: paper P&L after fees, funding and slippage is positive, or at least not clearly negative, compared with simply holding BTC.
- Safety: all risk limits and kill switches worked.
- Decision: clearly negative, stop; promising, continue with stage 2; unclear, run longer before deciding.
Note: the v0 bot needs minimal wiring to run (a supervisor/runner) that the lean plan assigned to F21. The PO has not decided how v0 gets started; see the open question raised by the CTO (minimal runner in v0 scope vs none).

## Token-saving rules (PO, 2026-09-30)
- Tests run as `uv run pytest -q -x --tb=short` (quiet, stop at first failure, short tracebacks); rerun a single failing test verbosely only when needed.
- Cap each v0 feature at TWO review rounds; anything still open is logged as a follow-up, except a BLOCKING money-path finding.
- RTK (https://www.rtk-ai.app/): NOT installed. The cloud environment's network policy denied www.rtk-ai.app (gateway 403 to CONNECT). The required checks (git push --force still denied, the main-commit guard hook still fires, full pytest output recoverable via tee) were therefore not run. Allow the host in the environment's Network access settings to retry; meanwhile the quiet pytest flags above apply.
