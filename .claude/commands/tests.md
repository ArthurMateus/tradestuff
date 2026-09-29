---
description: Step 4. The test designer writes failing tests per feature. The test reviewer audits them. Loops up to 3 rounds.
argument-hint: <epic-slug> [Fn]
---
You are the CTO. Epic and feature: $ARGUMENTS. Gate check: `gate_passed: pm` (or this feature is
already in progress).

For each feature (all of them, or just the one given), on its feature branch or worktree. Features
the epic plan marks as parallel get dispatched together in one message:

1. Dispatch **test-designer** with the spec path, the feature ID, the branch, and any previous
   test-review files.
2. Record the commit hash of its test commit in STATE.md (`F<n>.tests_commit=<hash>`). The senior dev
   uses it later to detect test tampering.
3. Dispatch **test-reviewer**. Save its output to `reviews/test-review-r<N>.md`.
4. `CHANGES REQUIRED` → back to test-designer with the review file. Increment `loops.tests`.
   **Cap: 3 rounds.** After that, take the remaining disagreements to the PO, with both sides'
   arguments.
5. Gate per feature: the reviewer says `APPROVED`, every new test fails for the right reason, and
   every AC appears in the coverage matrix.

Set the feature status to `tests` in STATE.md, and set `gate_passed: tests` when all features are
done. Next: `/build`.
