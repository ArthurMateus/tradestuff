# Run register: copytrade-v1 (human-readable mirror)

- **Authoritative copy:** the append-only ledger's run register. This file mirrors it for humans.
- **Why it is separate:** it is not part of `edge-hypothesis.md`, so appending a row never changes the file hash stored in a run record (edge-hypothesis 5.4, addendum A1.3 h).
- **Rules:**
  - Rows are append-only. At most 2 paper runs (edge-hypothesis 5.4).
  - Every mid-run deploy and its backtest-auditor ruling gets a row (A1.2).
  - Only the recorded commit runs, from the run worktree, until the ruling is in the ledger, whether or not entries are paused (A2.2).
  - Appending rows here, or any other docs commit, happens outside the run worktree and is never a deploy (A2.2).

## Runs

| Run | Start (UTC) | End (UTC) | edge-hypothesis.md sha256 | Config sha256 | Engine commit | Dirty (engine path set) | Run worktree | Installed-package list sha256 | Data inputs sha256 (manifest of per-file hashes) | CI level | End reason | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|

## Mid-run deploys

| Run | Time (UTC) | Old commit | New commit | Diff sha256 (patch in ledger) | Touches signal/filter/scoring/sizing/exit/cost/fill? | Auditor ruling (CONTINUE with affected trades / ABORTED) | Ruling time (UTC) |
|---|---|---|---|---|---|---|---|
