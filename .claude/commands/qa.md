---
description: Step 7. QA drives the real software. Simulation QA stress-tests the trading path. Screenshots and reports go to the PO.
argument-hint: <epic-slug>
---
You are the CTO. Epic: $ARGUMENTS. Gate check: `gate_passed: review`.

1. Merge the reviewed feature branches into `epic/<slug>` locally for QA (no push yet), so QA tests
   the integrated epic.
2. Dispatch **in parallel**:
   - **qa**, if `has_ui: yes` or the spec has any `qa-ui` or `integration` ACs. Run ID: `<slug>-<timestamp>`.
   - **qa-simulation**, if `touches_money_path` or `touches_strategy` is set.
3. Save the outputs to `06-qa-report.md` and `06-sim-report.md`.
4. For each defect:
   - **code defect** → **test-designer** writes a failing regression test first → **developer** fixes
     it → **senior-dev** reviews → **reviewer-security** and **reviewer-changes** on the fix diff
     (plus **reviewer-risk** if it's on the money path) → re-run the QA that found it.
   - **spec gap** → a report to **pm** (spec mode, "amend") → the PO approves the amendment → a
     mini-pipeline for the delta.
   Increment `loops.qa`. **Cap: 3 rounds per defect**, then escalate to the PO.
5. Show the PO the screenshot folder path, the scenario table, the latency table, and the invariant
   violation count.
6. Gate: both verdicts are `PASS` and there are zero invariant violations. Set `gate_passed: qa`.
   Next: `/verify`.
