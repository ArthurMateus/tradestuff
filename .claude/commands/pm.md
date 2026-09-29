---
description: Step 3. The PM writes the feature spec and definition of done. The PO approves it. This is the PO's main leverage point.
argument-hint: <epic-slug>
---
You are the CTO. Epic: $ARGUMENTS. Gate check: `gate_passed` is `discovery` or `research`
(it must be `research` if `touches_strategy: yes`).

1. Dispatch **pm** (spec mode) with the paths to the brief, discovery, answers and research.
2. If it ends with `EXPLORE REQUEST:`, dispatch **explore** with those questions and re-invoke pm with
   the answers. Repeat as needed. **Never** give pm raw git history.
3. If it returns `ESCALATE:`, take it to the PO and re-invoke pm with the decision.
4. Present `04-spec.md` to the PO. Highlight the feature list, any AC without a concrete number, the
   config table, the out-of-scope list, and the epic plan. **Tell the PO this is the most important
   review in the pipeline.** Iterate with pm until the PO approves.
5. On approval: update the STATE flags from spec section 6, list the features in STATE.md, and create
   the feature branches from the epic: `git branch feat/<slug>/<Fn>-<name> epic/<slug>`. For features
   the epic plan marks as parallel, create worktrees.
6. Set `gate_passed: pm` and commit. Next: `/tests`.
