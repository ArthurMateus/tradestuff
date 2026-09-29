---
description: Step 2. Runs the discovery agent and collects the PO's answers.
argument-hint: <epic-slug>
---
You are the CTO. Epic: $ARGUMENTS. Gate check: STATE.md must say `gate_passed: brainstorm`.

1. Dispatch **discovery** with the path to `docs/sdlc/<slug>/01-brief.md`.
2. Save its output verbatim to `02-discovery.md`.
3. Show the PO the **blocking** questions first, then the clarifying questions, then the assumptions.
   Ask the PO to answer, or to reply "accept defaults" per question.
4. Record the answers verbatim in `03-answers.md`, marking each one `answered` or `default accepted`.
5. If the answers materially changed scope, update the brief (note the change in its decisions
   section) and re-run discovery **once**.
6. Gate: no blocking question left unanswered. Set `gate_passed: discovery` and commit.
   Next: `/research` if `touches_strategy` or `touches_money_path` is set, otherwise `/pm`.
