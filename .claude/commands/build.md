---
description: Step 5. Developer and senior dev loop until approved. The architect breaks deadlocks.
argument-hint: <epic-slug> [Fn]
---
You are the CTO. Epic and feature: $ARGUMENTS. Gate check: the feature's tests were approved.

For each feature (parallel features get dispatched together, each in its own worktree):

1. Dispatch **developer** with the spec path, the test-plan path, the feature ID and branch, and any
   open `senior-r*.md` or `architect-r*.md` findings.
   - If it returns `ESCALATE: TEST DEFECT`, dispatch **test-reviewer** to rule on that test only. If
     the test really is wrong, test-designer fixes it and test-reviewer re-approves (record a new
     `tests_commit`). The developer never touches tests.
2. Dispatch **senior-dev** with the branch, the epic branch name, `F<n>.tests_commit`, and the path to
   its previous reviews. Save the output to `reviews/senior-r<N>.md`.
3. `CHANGES REQUIRED` → back to developer. Increment `loops.build`. **Cap: 3 rounds.** After that:
   `git diff epic/<slug>...HEAD > reviews/diff.patch`, then dispatch a **fresh architect** with the
   diff and the open BLOCKING findings only. Follow its verdict: PROCEED, or one final developer
   round with its exact change list.
4. Gate per feature: senior says `APPROVED`, the full suite is green (senior's own run), and mutation
   testing meets the threshold.

Set `gate_passed: build` when all features are done. Next: `/review`.
