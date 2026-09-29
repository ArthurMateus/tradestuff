---
description: Run the stateless parallel review panel on the current branch diff.
argument-hint: [base-branch, default origin/main]
---

Run these subagents IN PARALLEL in one message, each told only: "Review `git diff ${ARGUMENTS:-origin/main}...HEAD`; follow your instructions." Do not share any other context.

`security-reviewer`, `code-reviewer`, `opinion-reviewer`, `dry-reviewer`, `compliance-reviewer`, and `risk-manager` (review mode) if the diff touches order execution, sizing, limits, broker/exchange code, or money math.

Merge the results into `docs/epics/<slug>/review.md`: findings grouped by severity, de-duplicated, with the reporting agent named. If any BLOCKER exists, do not fix it yourself: hand the blockers and the diff to a fresh `architect` (mode B) and then to `developer`. Reply to the user with the verdict counts and blockers only.
