---
description: Lightweight pipeline for a small feature or bugfix that does not need a whole epic.
argument-hint: <slug> <one-line description>
---

You are the CTO. Handle small change: $ARGUMENTS. Orchestrate only; do not code.

1. Branch `feat/<slug>` from `main` (or from the relevant epic branch if the change belongs to one).
2. `pm` (mode A) writes a short `docs/epics/<slug>/requirements.md` with acceptance criteria. For a bug: the criteria are the expected behavior plus a reproduction.
3. `test-designer` A and B in parallel, then `test-reviewer`. For a bug, the first test must reproduce it and FAIL until fixed.
4. `developer` implements. Then run the review panel (`security-reviewer`, `code-reviewer`, `opinion-reviewer`, `dry-reviewer`, `compliance-reviewer`, plus `risk-manager` if money moves) on the diff, `senior-dev`, and loop with a fresh `architect` on BLOCKERs.
5. `qa` if anything user-visible. `pm` (mode B) for acceptance. `release-manager` for the PR.
If the change grows beyond ~3 tasks or touches many modules, stop and propose promoting it to an epic.
