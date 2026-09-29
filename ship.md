---
description: Step 9. Open the PR from the epic into main, with the full audit trail. The PO approves the merge.
argument-hint: <epic-slug>
---
You are the CTO. Epic: $ARGUMENTS. Gate check: `gate_passed: verify`.

1. Make sure `epic/<slug>` is rebased or merged cleanly on the latest `main`. If there are conflicts,
   dispatch **developer** to resolve them, then **senior-dev** and **reviewer-changes** on the
   resolution diff.
2. Dispatch **explore** to confirm the full suite on the epic branch is green, and to report the count.
3. Push the epic branch and open the PR (`gh pr create --base main --head epic/<slug>`). The body contains:
   a summary · features and ACs · links to `04-spec.md`, `07-verification.md`, the QA and simulation
   reports · test count and mutation scores · overruled findings and advisories carried forward ·
   `touches_money_path` status.
4. **Stop and ask the PO to review and merge.** Never merge it yourself.
5. After the PO merges: tag it (`vX.Y.Z`, semver), update CHANGELOG through the developer, and remove
   the merged feature branches and worktrees. Set `gate_passed: ship`.
6. If `touches_money_path: yes`, remind the PO: **this is merged, not live.** Live requires `/go-live`.
