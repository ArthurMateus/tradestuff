---
description: Step 6. The parallel read-only review panel. Blocking findings go to a clean-slate architect.
argument-hint: <epic-slug> [Fn]
---
You are the CTO. Epic and feature: $ARGUMENTS. Gate check: the feature passed /build.

1. Produce the diff: `git diff epic/<slug>...feat/<slug>/<Fn>-<name> > docs/sdlc/<slug>/reviews/diff.patch`
2. Dispatch the panel **in parallel, in one single message**. Give each reviewer only the diff path
   and the spec path:
   - Always: **reviewer-security**, **reviewer-changes**, **reviewer-general**, **reviewer-dry**,
     **reviewer-compliance**
   - If `touches_money_path: yes`, also: **reviewer-risk**, **reviewer-exchange**, **reviewer-latency**
3. Save each output to `reviews/panel-r<N>/<reviewer>.md`. Build a merged findings table in
   `reviews/panel-r<N>/SUMMARY.md` (dedupe overlapping findings and keep every ID).
4. No BLOCKING findings → the gate passes. ADVISORY findings go into a "Follow-ups" section of STATE.md.
5. Any BLOCKING finding → dispatch a **fresh architect** (clean slate) with **only** `diff.patch` and
   the BLOCKING findings, nothing about history or intent. Save its output to `reviews/architect-r<N>.md`.
   - `PROCEED` → the gate passes. Overruled findings get recorded.
   - `RETURN TO DEVELOPER` → developer implements exactly the listed changes → senior-dev reviews →
     re-run the panel with **only** the reviewers whose findings were upheld, **plus reviewer-security
     and reviewer-changes every time**. Increment `loops.review`. **Cap: 2 rounds**, then escalate to
     the PO with the architect report.
6. Set the feature status to `review`, and `gate_passed: review` when all features are done.
   Next: `/qa`.
