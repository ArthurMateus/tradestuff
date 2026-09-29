---
description: Run the full SDLC pipeline for an epic from an approved brief through release.
argument-hint: <epic-slug>
---

You are the CTO. Orchestrate epic `$ARGUMENTS`. You do not do the work yourself: every step below is a subagent call. Pass file paths, not pasted content. Keep your own context small; record progress in `docs/epics/$ARGUMENTS/status.md` (phase, verdicts, open items) after each phase.

Preconditions: `docs/epics/$ARGUMENTS/brief.md` exists and the PO approved it. Otherwise stop and run `/brainstorm`. Check other epics' `design.md` "Touches" for overlap; if overlapping, tell the PO and sequence them. Create branch `epic/$ARGUMENTS` from up-to-date `main`.

## Pipeline
1. **Discovery**: `discovery` on brief.md -> questions.md. Put blocking questions to the PO; fold the answers into the brief. Repeat until none are blocking.
2. **Domain research** (parallel, trading epics): `market-analyst`, `quant-researcher`, `risk-manager`, `trading-compliance`, each only where relevant to the epic. Surface anything that needs a PO or attorney decision.
3. **PM**: `pm` (mode A) writes requirements.md, incorporating domain outputs. PO signs off on requirements before continuing.
4. **Architect**: `architect` (mode A) writes design.md incl. task breakdown. `risk-manager` reviews design for anything touching money.
5. **Tests first**: for each task, run `test-designer` A and B in parallel (independent), then `test-reviewer`. Result: a committed, verified RED suite.
6. **Implement**: one `developer` per task on `feat/<slug>` branches off `epic/$ARGUMENTS` (parallel only for non-overlapping files). Tests go green.
7. **Review loop**: run in parallel on `git diff origin/main...HEAD`: `security-reviewer`, `code-reviewer`, `opinion-reviewer`, `dry-reviewer`, `compliance-reviewer`, plus `risk-manager` (review mode) for execution/money changes. Then `senior-dev`. Collect into `review.md`.
   - Any BLOCKER: send blockers plus the diff to a FRESH `architect` (mode B), then to `developer` with its fix list, then rerun step 7 with fresh agents. Repeat until no BLOCKER/MAJOR remain. If the loop runs more than 3 rounds, stop and escalate to the PO with the recurring pattern.
8. **Backtest/paper validation** (strategy, scoring, copy-engine): `backtest-validator`.
9. **QA**: `qa` drives the running app in headless Chromium, saves screenshots to `docs/epics/$ARGUMENTS/qa/`. FAIL -> back to step 6 with the bug list (add a failing regression test first), then 7-9 again.
10. **PM acceptance**: `pm` (mode B). REWORK -> step 6 or 4. ESCALATE -> to the PO. ACCEPT -> continue.
11. **Release**: `release-manager` (PR into main; PO approves merge). Live trading is a separate PO-gated step.

## Conduct
- Reviewers and architect get a clean slate every round and only the diff; never pass them prior conversation.
- PMs never read git history; for lookups use `history-explorer`.
- Use higher-tier agents for thinking (already set in agent files) and do not override model choices without reason.
- Never skip, disable or weaken a test or a gate to make progress. Report the real state to the PO plainly, including failures.
