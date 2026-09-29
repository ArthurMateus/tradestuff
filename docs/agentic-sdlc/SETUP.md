# Setup

## 1. Copy into your repo
```
your-repo/
├── CLAUDE.md
└── .claude/
    ├── settings.json      permission guardrails (blocks reading .env, force-push, pushing to main)
    ├── agents/            21 role definitions
    ├── commands/          14 pipeline commands
    └── knowledge/         protocol.md + trading-invariants.md (shared rules every agent reads)
```
If your repo already has a `.claude/settings.json`, merge the `permissions` block instead of overwriting it.

## 2. Run `/onboard` once
It detects your stack, test, run, lint and mutation commands, fills the Project block in CLAUDE.md,
fixes `.gitignore`, and checks whether a secret was ever committed. If one was, **rotate the key**:
removing it from git history isn't enough.

## 3. Tools the pipeline expects (Python example)
```bash
pip install pytest hypothesis mutmut pip-audit
npm i -D @playwright/test && npx playwright install chromium   # only if you have a web UI
```
Also install GitHub CLI (`gh`) and run `gh auth login` for `/ship`.

## 4. Record real exchange fixtures (once, on testnet)
Save real REST and WebSocket payloads (order ack, partial fill, reject, exchange info, user-data
events) to `tests/fixtures/exchange/<venue>/`. The test designer and reviewer-exchange rely on them.
Strip account IDs first.

## 5. Model tiering
It's set in each agent's frontmatter (`model: opus | sonnet | haiku`). If your plan has no Opus
access, change `opus` to `sonnet` and keep `explore` on `haiku`.

## 6. First run
```
/brainstorm consensus copy-trading: only copy when ≥3 independent vetted leaders open the same side within 10 minutes
/discovery <slug>
/research <slug>
/pm <slug>
/tests <slug>
/build <slug>
/review <slug>
/qa <slug>
/verify <slug>
/ship <slug>
/go-live <slug>
```
Run them in order. The gates are the product.

## 7. Check that the agents loaded
In Claude Code, run `/agents`. All 21 should be listed. If one is missing, its file must start with
`---` on line 1: no blank line and no backslash before it.
