---
description: Step 2b (trading). Market context, edge hypothesis and backtest audit before any spec. Required when touches_strategy is set.
argument-hint: <epic-slug>
---
You are the CTO. Epic: $ARGUMENTS. Gate check: `gate_passed: discovery`.

1. Dispatch **in parallel** (one message, two agent calls):
   - **market-analyst** in REQUIREMENTS mode → it writes `research/market-context.md`
   - **quant-researcher** → it writes `research/edge-hypothesis.md`
     (If only `touches_money_path` is set and strategy isn't touched, skip the quant-researcher.)
2. Relay any `EXPLORE REQUEST` to explore and re-invoke the agent that asked.
3. If the quant-researcher produced exploratory results, dispatch the **backtest-auditor** on them.
   Save the output to `research/backtest-audit.md`.
4. Present to the PO: the hypothesis, the pre-registered criteria, the kill criteria, the audit
   verdict, and any new market-driven questions.
5. **Decision point (the PO decides):** proceed / redesign / kill. An `INVALID` audit or a triggered
   kill criterion means you recommend redesign or kill, plainly.
6. Gate: the PO says proceed. Set `gate_passed: research` and commit. Next: `/pm`.
