epic: copytrade-v1
branch: epic/copytrade-v1
gate_passed: build (F1 only)
touches_money_path: yes
touches_strategy: yes
has_ui: no
features: F1=approved+merged (F1.tests_commit=75c3221; advisories A2,A4,A5 queued), F2=queued, F3=queued, F4=queued, F5=queued, F6=queued, F7=queued, F10=queued, F11=queued, F12=queued, F14=queued (stage 1); F8, F9, F13, F15-F21, F23 (stage 2) not started; F22 dropped
loops: tests=0 build=1 review=0 qa=0
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
Next: F2, F3, F5 in parallel (lean loop). Wave 0 (F1) done. Queued small F1 follow-up: A2 explicit exempt list + test rename, A4 ClockSync immutable pair, A5 atr_candle_interval 1h only + allowed_user_id > 0. /onboard done.
