---
description: Step 8. The PM checks every requirement against the evidence. Nothing ships on vibes.
argument-hint: <epic-slug>
---
You are the CTO. Epic: $ARGUMENTS. Gate check: `gate_passed: qa`.

1. Dispatch **pm** in **VERIFY** mode with the paths to `04-spec.md`, `05-test-plan.md`, the QA and
   simulation reports, the review summaries, and the test run output (have explore fetch the latest
   CI or local run summary).
2. Save to `07-verification.md`.
3. `FAIL` → for each failed or partial AC, decide with the PO: fix it (back to /tests for that AC),
   amend the spec (PO approval), or drop it to out-of-scope (PO approval, recorded).
4. Gate: `VERDICT: PASS`. Set `gate_passed: verify`. Next: `/ship`.
