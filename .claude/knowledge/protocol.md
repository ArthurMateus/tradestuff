# Handoff Protocol

Every agent reads this file before starting. It is the contract that lets agents with separate
context windows work together without sharing memory.

## 1. Workspace

Everything for one epic lives in `docs/sdlc/<epic-slug>/` and is committed on the epic branch
(it becomes the audit trail). Screenshots and raw QA artefacts go to `qa-artifacts/` (gitignored).

```
docs/sdlc/<epic-slug>/
├── STATE.md                 CTO – current gate, loop counters, flags
├── 01-brief.md              CTO – the compiled brainstorm ("the big prompt")
├── 02-discovery.md          discovery
├── 03-answers.md            CTO – PO answers to discovery, verbatim
├── research/
│   ├── edge-hypothesis.md   quant-researcher
│   ├── market-context.md    market-analyst
│   └── backtest-audit.md    backtest-auditor
├── 04-spec.md               pm – features, acceptance criteria, config table
├── 05-test-plan.md          test-designer – AC → test coverage matrix
├── reviews/
│   ├── diff.patch           CTO – the exact diff under review
│   ├── test-review-r<N>.md  test-reviewer
│   ├── senior-r<N>.md       senior-dev
│   ├── panel-r<N>/<reviewer>.md
│   └── architect-r<N>.md
├── 06-qa-report.md          qa
├── 06-sim-report.md         qa-simulation
├── 07-verification.md       pm (verification mode)
└── 08-go-live.md            CTO – go-live checklist + PO sign-off
```

Read-only agents do not write files. They return their report as their final message, and the CTO
saves it verbatim to the path above.

## 2. IDs and traceability

- Features: `F1`, `F2`, … Acceptance criteria: `F1.AC1`, `F1.AC2`, …
- Discovery questions: `Q1`, `Q2`, … Findings: `<REVIEWER>-<N>`, e.g. `SEC-3`, `RISK-1`.
- Test names or docstrings include the AC ID they prove: `test_F1_AC2_rejects_order_above_max_notional`.
- Commits follow Conventional Commits and reference ACs: `feat(risk): enforce max notional [F1.AC2]`.
- Every AC must be traceable to at least one test or one QA/simulation step. Anything that isn't
  traceable doesn't count as done.

## 3. Report format (all reviewing agents)

The first line is always machine-readable:

```
VERDICT: APPROVED | CHANGES REQUIRED | CLEAN | PASS | FAIL | PROCEED | RETURN TO DEVELOPER
```

Findings go in one table:

| ID | Severity | Location (file:line) | Finding | Why it matters | Required fix |
|----|----------|----------------------|---------|----------------|--------------|

Severity:
- **BLOCKING**: incorrect, unsafe, insecure, loses money, violates the spec or an invariant. Must be
  fixed before the gate passes.
- **ADVISORY**: quality or taste. It gets logged and doesn't hold the gate. Never promote taste to BLOCKING.

If you find nothing, say `VERDICT: CLEAN` and stop. Don't invent findings to look useful, and don't
hold back real ones to be agreeable.

## 4. Loops and escalation

| Loop | Cap | On cap |
|------|-----|--------|
| test-designer ↔ test-reviewer | 3 rounds | CTO escalates the remaining disagreements to the PO |
| developer ↔ senior-dev | 3 rounds | architect adjudicates the open findings |
| review panel → architect → developer | 2 rounds | CTO escalates to the PO with the architect's report |
| qa defect → fix | 3 rounds per defect | CTO escalates to the PO |

The CTO increments counters in STATE.md. Any agent can stop early with:

```
ESCALATE: <one-line reason>
<what decision is needed, options, your recommendation>
```

Use it for: spec contradictions, a test you believe is wrong (developer), missing access, or a
decision that belongs to the PO.

## 5. Explore requests

Subagents cannot spawn subagents. If you need a repo fact you're not allowed or equipped to fetch
(the PM may not read git history), end your message with:

```
EXPLORE REQUEST:
1. <small factual question>
2. ...
```

The CTO runs `explore` and re-invokes you with the answers.

## 6. Git

- `main` is always releasable. Nobody commits to it directly.
- Epic branch: `epic/<slug>`. Feature branches: `feat/<slug>/<Fn>-<short-name>`, cut from the epic.
- Features that can run in parallel use separate worktrees:
  `git worktree add ../wt-<Fn> feat/<slug>/<Fn>-<name>`.
- The PM's epic plan assigns file ownership per feature so parallel work doesn't collide.
- Feature → epic after /verify. Epic → main through a PR after all its features pass.

## 7. STATE.md format

```
epic: <slug>
branch: epic/<slug>
gate_passed: brainstorm | discovery | research | pm | tests | build | review | qa | verify | ship | go-live
touches_money_path: yes | no          # execution, risk, sizing, order routing, positions
touches_strategy: yes | no            # signals, trader selection, consensus, filters
has_ui: yes | no
features: F1=verify, F2=build, ...
loops: tests=0 build=0 review=0 qa=0
escalations_open: none
updated: <ISO-8601 UTC>
```

## 8. Universal rules for every agent

- Stay in your role. If a task belongs to another role, say so and stop.
- Never read `.env`, key files or secrets. Never print environment variables.
- Never place a live order, never use live credentials, never switch the mode to live.
- Honour `.claude/knowledge/trading-invariants.md` when your work touches trading code.
- Be concrete: file, line, value, command. Vague output is a failed run.
