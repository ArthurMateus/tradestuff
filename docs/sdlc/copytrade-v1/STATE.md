epic: copytrade-v1
branch: epic/copytrade-v1
gate_passed: build (F1 only)
touches_money_path: yes
touches_strategy: yes
has_ui: no
features: F1=approved+merged (F1.tests_commit=75c3221; advisories A2,A4,A5 queued), F2=approved+merged (tests_commit=6ba583c; round-2 tests a6340a7; build loops=2), F3=build, PAUSED at round-1 CHANGES REQUIRED (tests_commit=364d97b; impl 506ba0f..006ba87; test fix b8c2f94; branch pushed, NOT merged), F4=queued, F5=approved+merged (tests_commit=651812a; round-2 tests 490d783; build loops=2), F6=queued, F7=queued, F10=queued, F11=queued, F12=queued, F14=queued (stage 1); F8, F9, F13, F15-F21, F23 (stage 2) not started; F22 dropped
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
