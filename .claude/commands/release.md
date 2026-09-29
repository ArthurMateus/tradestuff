---
description: Verify all gates and release an epic (PR into main). Live trading enablement is separate.
argument-hint: <epic-slug>
---

Delegate to `release-manager` for epic `$ARGUMENTS`: verify every gate from its checklist against `docs/epics/$ARGUMENTS/`, then prepare the changelog and open the PR into `main`. Report to the PO exactly which gates pass or fail. Do not merge without the PO's explicit approval. Do not enable live trading; that needs the PO's written go in `docs/product/decisions.md` after the paper-trading soak.
