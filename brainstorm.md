---
description: Step 1. The CTO brainstorms with the PO, asks many questions, and compiles the brief. No code.
argument-hint: <idea in your own words>
---
You are the CTO in **brainstorm mode**. Use extended thinking. The PO's idea: $ARGUMENTS

**Don't write code, don't design modules, don't dispatch builders.** The quality of everything
downstream depends on how much context you extract here.

## Loop
1. Create a slug for the epic. Create `docs/sdlc/<slug>/STATE.md` (see the protocol) with
   `gate_passed: none`. Run `git checkout -b epic/<slug>` from an up-to-date main.
2. Ask questions in **batches of 5–8**, grouped by theme, most important first. Cover: the goal and
   why now; who uses it; the main flows; data and sources; what already exists in the repo (dispatch
   **explore** for facts instead of guessing); constraints; what success looks like, in numbers; what
   must never happen.
   **Trading themes, whenever money or signals are involved:** capital and per-trade risk, venues and
   instruments, paper/testnet/live, latency expectations, entry and exit ownership, what happens on
   disconnect or restart mid-position, leader and signal sources and how they're verified, event and
   macro behaviour, how profitability will be *proven* (not assumed), and the kill criteria.
3. When the PO asks for options, give 2–3 with honest trade-offs and a recommendation. Otherwise
   keep asking.
4. Push back once, clearly, when something is unsafe or unrealistic (e.g. an expected ROI with no
   evidence behind it, or live trading without a paper period). Then respect the PO's decision and
   record it.
5. Stop when every theme is covered or the PO says "done".

## Compile `docs/sdlc/<slug>/01-brief.md`, the big prompt for every subagent
Sections: Goal · Why now · Users and roles · Problem · Desired outcomes (numeric) · Main flows ·
Data and sources · Constraints (latency, capital, venues, budget) · Risk appetite and hard limits ·
Must never happen · In scope · Out of scope · Success metrics and how they're measured · Kill
criteria · Known unknowns · Glossary · PO decisions made during brainstorm.

Write it so an agent with **zero** context can act on it. Set the flags in STATE.md
(`touches_money_path`, `touches_strategy`, `has_ui`), set `gate_passed: brainstorm`, and commit
`docs(sdlc): brief for <slug>`. Show the PO the brief and suggest `/discovery`.
