epic: copytrade-v1
branch: epic/copytrade-v1
gate_passed: research
touches_money_path: yes
touches_strategy: yes
has_ui: no
features: pending PO approval of 04-spec.md (F1-F21, F23; F22 dropped)
loops: tests=0 build=0 review=0 qa=0
escalations_open: none
updated: 2026-09-29T18:00:00Z

Research artifacts:
- research/market-context.md
- research/edge-hypothesis.md (frozen, with addenda A1, A2 and A3; A4 in progress)
- research/backtest-audit.md: INCONCLUSIVE
- research/backtest-audit-r2.md: INCONCLUSIVE
- research/backtest-audit-r3.md: VALID
- research/backtest-audit-r4.md: VALID
- research/run-register.md
- trading-compliance skipped (no paid users, no third-party accounts, no live money). It re-runs at /go-live.

PO acknowledgements: section 14 items 1-10, with the corrected wording of 9-10 pre-approved (see docs/product/decisions.md).

## Pipeline rules for this epic (PO decision 2026-09-29, token economy)
- **Review panel:** the full panel runs only on money-path features: F9, F10, F11, F12, F13, F16, F17, F18, F19 and F20. Every other feature gets reviewer-security, reviewer-changes and reviewer-general.
- **Test design:** one test-designer per feature, followed by the test-reviewer.
- **Rulebook audits:** none after the A4 check, unless the verdict logic changes.
- **F22:** dropped.

## Follow-ups before run 1 (not blocking the build)
- BT5-1, BT5-2 and BT5-3 (`research/backtest-audit-r5.md`, VALID): fix them in a short Addendum A5 while building F18, with no new audit (token-economy rule). Correct item 9's wording for BT5-1, and have the PO confirm it.

Pending outside the pipeline: the PO runs hl_sample.py once and sends back summary.json. It feeds the VAL-S config keys.

Next: commit A4 and run a light audit of A4, then have the PM align the spec with A4, then get PO approval of the spec, then /tests.
