# Agentic SDLC

You (the user) are the **PO**. The main Claude Code session is the **CTO**: it brainstorms with you and orchestrates subagents, and never does tasks itself.

```mermaid
flowchart TD
  PO[PO idea] --> BS[Brainstorm: CTO + PO, many questions, no code]
  BS --> BR[brief.md + handoff.md]
  BR --> DI[Discovery: unanswered questions]
  DI -->|blocking questions| PO
  DI --> DR[Domain research, parallel:<br/>market-analyst, quant-researcher,<br/>risk-manager, trading-compliance]
  DR --> PM[PM: requirements + acceptance criteria]
  PM --> AR[Architect: design + tasks]
  AR --> TD[Test designers A and B, independent]
  TD --> TR[Test reviewer: honest, not over-mocked, RED]
  TR --> DEV[Developers: make tests green]
  DEV --> RP[Review panel, parallel, diff only:<br/>security, code, opinion, DRY, compliance, risk]
  RP --> SR[Senior dev]
  SR -->|blockers| AX[Fresh architect, diff only]
  AX --> DEV
  SR -->|approve| BT[Backtest validator]
  BT --> QA[QA: Playwright + Chromium, screenshots]
  QA -->|bugs + regression test| DEV
  QA --> PA[PM acceptance]
  PA -->|rework| DEV
  PA -->|wrong requirement| PO
  PA -->|accept| RL[Release: PR to main]
  RL --> PS[Paper-trading soak]
  PS --> GO[PO written go for live]
```

## Roles and models
| Role | Agent | Model | Why |
|---|---|---|---|
| Open questions | `discovery` | opus | thinking |
| Requirements, acceptance | `pm` | opus | thinking |
| Design, blocker resolution | `architect` | opus | thinking |
| Test design and review | `test-designer` x2, `test-reviewer` | opus | tests are the spec |
| Implementation | `developer` | sonnet | implementation |
| Code review | `senior-dev`, `security-reviewer`, `code-reviewer` | opus | thinking |
| Style / DRY / compliance review | `opinion-reviewer`, `dry-reviewer`, `compliance-reviewer` | sonnet | pattern work |
| QA | `qa` | sonnet | drives browser |
| History and small lookups | `history-explorer` | haiku | cheap |
| Trading domain | `market-analyst`, `quant-researcher`, `risk-manager`, `trading-compliance` | opus | thinking |
| Backtest audit, release | `backtest-validator`, `release-manager` | sonnet | procedural |

Run day to day at low or medium effort; raise it only for design, quant methodology and risk.

## Commands
`/brainstorm <idea>` -> `/epic <slug>` (or `/feature <slug> <desc>` for small work) -> `/review` (any time) -> `/release <slug>`.

## Principles
- **Abstract agents.** Generic agents know nothing about trading; project facts live in `CLAUDE.md`, `.claude/repo.md`, `docs/product/` and the four trading agents. To reuse the SDLC elsewhere, copy the generic agents and drop the trading ones.
- **Stateless reviewers** get only the diff. **PMs never read git history**; `history-explorer` answers small questions.
- **Tests first and red.** See `testing-policy.md`.
- **Implicit requirements** in `implicit-requirements.md` apply to every epic.
- **Branches and GitHub.** Everything merges to `main` via PR. Big features are epics on `epic/<slug>` so two big changes do not collide; each epic declares the modules it touches.
- **Artifacts, not chat.** Every phase writes to `docs/epics/<slug>/` (brief, questions, requirements, design, tests, review, backtest-report, qa + screenshots, acceptance, status).
- **CLAUDE.md stays short.**

## Human checkpoints
You approve: the brief; requirements; the merge to `main`; and, separately, any enablement of live trading. Everything else runs without you but is auditable in `docs/epics/<slug>/`.

## Known limits
Subagents cannot spawn subagents, so the CTO session runs the loops. Playwright needs the app runnable headless in the environment. Regulatory outputs are research to bring to counsel, not legal advice.
