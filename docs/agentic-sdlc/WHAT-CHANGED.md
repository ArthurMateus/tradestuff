# Review of v1: what was weak and what changed

Your v1 captured the lesson's ideas well. The gaps were mostly in the **mechanics**: how agents with
separate context windows actually pass work to each other, when loops stop, and how Claude Code really
behaves.

| # | Problem in v1 | Why it matters | Fix in v2 |
|---|---------------|----------------|-----------|
| 1 | Several agent files start with `\---` (escaped) or have no frontmatter delimiters | Claude Code doesn't parse the frontmatter, so the agent **silently doesn't load** | Every file starts with a clean `---` block. Check with `/agents` |
| 2 | No handoff contract. Agents are told to "review the diff" or "use the spec" with no path | Subagents share no memory. Each one guesses where things are, or the CTO pastes huge context | `protocol.md`: fixed artefact paths per epic, read and written by role |
| 3 | The PM "delegates to explore" | **Subagents can't spawn subagents** in Claude Code, so this can't happen | The `EXPLORE REQUEST:` protocol. The CTO relays and re-invokes |
| 4 | Loops had no exit ("loop until approved") | Two agents can ping-pong forever and burn your budget | Round caps per loop, escalating to the architect or the PO |
| 5 | Tests can't "fail for the right reason" against code that doesn't exist | They fail on ImportError, which proves nothing | The test designer may write interface stubs that raise `NotImplementedError` |
| 6 | Test honesty was checked only by reading | An LLM can be fooled by plausible-looking tests | Mutation testing on changed modules (senior-dev) plus a tamper check on tests since approval |
| 7 | "6,000 tests" was a volume target only | Volume without a quality signal rewards junk tests | Volume stays, backed by a mutation-score threshold |
| 8 | No traceability | "Done" couldn't be proven requirement by requirement | AC IDs in tests, commits and verification |
| 9 | Findings had free-form formats | The CTO can't aggregate 5–8 parallel reports reliably | One findings table plus a machine-readable `VERDICT:` first line |
| 10 | "Read-only" reviewers relied only on instructions | Weak enforcement | Reviewers get no Write/Edit tools. The CTO saves their reports. `settings.json` denies secrets and force-pushes |
| 11 | "CTO never edits files" had no exceptions | The CTO still has to record state, briefs and answers | Explicit carve-out: `docs/sdlc/**`, git branch management, and the CLAUDE.md Project block |
| 12 | No state tracking | New sessions don't know which gate passed, so gates get skipped | `STATE.md` per epic plus `/status` |
| 13 | QA was Playwright-only | Bots, APIs and trading engines have no browser UI | QA uses real interfaces per surface. qa-simulation covers trading |
| 14 | QA defects had no route | Bugs get fixed without regression tests | Code defect → failing test first → fix → review. Spec gap → PM |
| 15 | Discovery had no coverage checklist | It misses whole categories (failure, config, observability) | A lens sweep, plus a "what it changes" and a default for each question |
| 16 | PM ACs had no verification method or config table | ACs weren't testable, and thresholds ended up hardcoded | Each AC is tagged unit/integration/qa-ui/simulation. A config table is mandatory |
| 17 | The architect had `Read` on the whole repo | That defeats "diff only" | Instructed to read only the diff, the findings and the invariants |
| 18 | No commands folder shipped | The pipeline couldn't actually be run | 14 commands with gate checks |
| 19 | Nothing domain-specific | Trading bugs lose money in ways generic reviewers don't look for | The trading layer: 7 agents, invariants, /research, /go-live, /market-brief |
