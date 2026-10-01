# HANDOFF: finishing v0 of the copytrade bot with another AI assistant (Gemini / Antigravity)
Written 2026-10-01 for the PO. Self-contained: the assistant needs nothing from the Claude session. Repo: https://github.com/ArthurMateus/tradestuff

## 0. What this project is (30 seconds)
A paper-trading copy-trading bot for Hyperliquid with Telegram control. Python 3.11, `uv`, pytest, ruff, mypy. v0 = everything needed to run it in PAPER mode for 2-4 weeks. 11 of 12 v0 features are merged on branch `epic/copytrade-v1`. The last feature, **R0 (the runner: `copytrade run`)**, is built but is in its final fix round on branch `feat/copytrade-v1/R0-runner`.

## 1. HARD RULES (from CLAUDE.md; the assistant must obey them)
- PAPER MODE ONLY. Never place a live order, never use live keys, never write a real token or PIN into any file, never print environment variables.
- Never commit to `main`. Work only on `feat/copytrade-v1/R0-runner` and `epic/copytrade-v1`.
- Role split (do not mix): TEST files (anything under `tests/`) may only be changed by the "test designer" step; SOURCE (`src/`, `config/`, `README.md`) only by the "developer" step. A developer step must NEVER edit a test to make it pass: if a test looks wrong, stop and write the reason to `docs/sdlc/copytrade-v1/reviews/R0-escalation.md` (test name + why) and tell the PO.
- Never skip, delete, xfail or weaken a test to get green. Never mock our own code in tests (only Hyperliquid and Telegram are faked, with loopback servers).
- Every commit message ends with these two lines (blank line before them):
  `Co-Authored-By: <the assistant's name> <noreply@example.com>` (any honest attribution is fine)
  Do not claim to be Claude.
- Commit and push after every green slice (a usage cut-off must not lose work): `git push origin feat/copytrade-v1/R0-runner`.
- Useful role prompts live in `.claude/agents/` (test-designer.md, developer.md, senior-dev.md, reviewer-risk.md): read them as instructions for each role. Money-safety rules: `.claude/knowledge/trading-invariants.md` (BLOCKING). Project rules: `CLAUDE.md`. Full state log: `docs/sdlc/copytrade-v1/STATE.md` (read its LAST sections).

## 2. Setup (once)
```
git clone https://github.com/ArthurMateus/tradestuff C:\tradestuff   (or any folder)
cd tradestuff
git fetch origin
git checkout feat/copytrade-v1/R0-runner
git merge origin/epic/copytrade-v1        (should be a no-op or a clean merge)
uv sync
```
Test commands: `uv run pytest -q -x --tb=short tests/runner` (about 7 minutes; the full suite is about 10 minutes), `uv run ruff check .`, `uv run ruff format --check .` (format `src` only: `uv run ruff format src`), `uv run mypy`. Two tests are known to be flaky only under heavy load and pass when run alone: `tests/signals/test_ac6_latency.py` and `tests/hl/test_w0_connector.py`.

## 3. HOW TO SEE WHERE WE ARE
Run `git log --oneline -12 origin/feat/copytrade-v1/R0-runner` and read the newest commit messages:
- Last commit is `e1c0724` or earlier ("developer tests ..." / "fix four tests ..."): **Step A (test designer) is not done**. Start at Step A.
- A commit or commits from the designer whose messages start `test(runner):` and mention clock/flatten/restart/mutants AFTER e1c0724, and `uv run pytest -q tests/runner` shows FAILING tests: **Step A is done, start Step B (developer)**.
- `uv run pytest -q tests/runner` is fully green and `src/copytrade/runner/timebase.py` contains `monotonic_ms`: **Step B is done, start Step C (verification)**.
- R0 is already merged into `epic/copytrade-v1` (see `git log origin/epic/copytrade-v1`): start at Step E.
If unsure, also read the last section of `docs/sdlc/copytrade-v1/STATE.md`.

## STEP A: write the failing tests (TEST DESIGNER role; only touch `tests/` and docs)
Read: `docs/sdlc/copytrade-v1/reviews/R0-architect-r1.md` (THE SPEC for this round), `reviews/R0-r1-batch.md`, `reviews/R0-r1-risk.md`, `05-test-plan-R0.md`, and the existing harness in `tests/runner/` (`world.py`, `fake_hl.py`, `test_timebase.py`, `test_reload.py`).
Do:
1. Write every test listed under "Tests (designer)" in R0-architect-r1.md (clock/time base with an injected monotonic clock; runner scenarios; flatten; marks-stalled alert; torn restore; two consecutive restarts; fsync failure alert; non-money exception does not kill the loop; hub polled independently of the recorder).
2. DELETE and replace (do not weaken) `test_R0_AC4_a_sustained_jump_is_accepted_once_local_time_has_caught_up_with_it` as the document says.
3. Pin the mutation survivors listed there (br_funding_boundary, br_stop_cancel, rl_gate_entries, rn_mark_stale, rp_trigger_cap, br_exit_action, rl_no_behind_flag, rl_no_unproven_flag, rn_stall, rn_jump_realert, rl_time_floor).
4. Add a per-test timeout using something already installed (no new dependency).
5. Fix the flaky `World.telegram_ready` in `tests/runner/world.py` (wait for a getUpdates count above the pre-start count).
6. Add a "Fix-round addendum" to `05-test-plan-R0.md` with the names the developer needs (alerts `clock_rebased`, `runner_crashed`, `marks_stalled`, `flatten_incomplete`; constants `DOUBT_RESAMPLE_S=30`, `REBASE_FRESH_ESTIMATES=2`, `DOUBT_REALERT_S=300`, `MARKS_STALE_ALERT_N=5`; the injected `monotonic_ms` parameter of `TimeBase`).
Done when: the new tests FAIL for the right reason (not import/fixture errors), all other tests still pass, `ruff`/`mypy` clean on tests. Commit + push.

## STEP B: make the code pass (DEVELOPER role; only `src/`, `config/`, `README.md`)
Read the same documents plus `src/copytrade/runner/` (runner.py, timebase.py, flatten.py, reload.py, adapters.py), `src/copytrade/paper/broker.py` (restore) and `src/copytrade/positions/manager.py` (restore_state).
Implement (the architect's spec, no new config keys, thresholds as code constants):
1. **Clock (TimeBase):** monotonic projection `broker_target = last accepted exchange target + monotonic elapsed`, forward-only; "in doubt" when unsynced / candidate differs from the projection by more than 2 x `clock.max_offset_uncertainty_ms` / unverified baseline after restart; while in doubt force a new offset estimate every 30 s; rebase after TWO consecutive fresh consistent estimates; alert `clock_unsynced`/`clock_jump` on entering doubt, re-alert every 300 s only while positions are open, alert `clock_rebased` once. **While in doubt: refuse ENTRIES only; ALWAYS keep calling `advance_to`, marks and delistings from the projection** (stops, liquidations, exits and /flatten must keep working).
2. **Flatten supervisor (runner/flatten.py):** unfinished while `broker.positions()` or pending exits are non-empty (or in_flight/still_open); alert `flatten_incomplete` at the limit then every 300 s; a raise in `manager.flatten` is caught and a re-run still scheduled.
3. **Marks alert:** after 5 consecutive iterations with positions open and stale mids or rejected/unknown marks, alert `marks_stalled`, repeat every 300 s.
4. **Restart stop-loss safety:** in the paper broker's restore write the NEW stop/exit record BEFORE the cancel; at reload verify every OPEN share has a live stop in `broker.stops()` (opposite side, right quantity); take `sl_cid` from the broker's restored stops; if missing, re-place via the gate or flag and close.
5. **Dead-loop fail-safe:** catch `Exception` in non-money sections (log + throttled alert); on a money-path/ledger failure queue a `runner_crashed` alert naming the open positions BEFORE stopping so the final flush sends it; `run_app` catches `Exception` and exits 1 with one line.
6. **MarketHub** drained by the runner itself, independent of the recorder tick.
7. **README** (Windows section): supervised restart (Task Scheduler, restart on failure), stop with Ctrl+C only and never close the window, and the truth about logging (only warnings reach the console).
Rules: all orders only through the risk gate (a test enforces it); one shared `gate_lock`; Decimal for money; no secrets in logs.
Done when: `uv run pytest -q tests/runner` fully green, then the whole suite green (rerun the 2 flaky tests alone if they fail), `ruff check .`, `ruff format --check .`, `mypy` clean. Commit + push after each slice.

## STEP C: verification (do it yourself, honestly)
1. Re-run the full suite once, plainly, and record the result in `docs/sdlc/copytrade-v1/STATE.md` (counts, anything flaky).
2. Hand-mutation check (target >= 70% killed): for each of the 11 pinned mutants, temporarily break the named guard in a COPY of the file, run `uv run pytest -q -x tests/runner tests/paper`, confirm a test fails, restore the file (`git checkout -- <file>`), repeat. If a mutant is NOT caught, ask the test-designer step for one more test.
3. Re-read the diff of `timebase.py`, `runner.py`, `flatten.py`, `reload.py`, `paper/broker.py` against the money-safety rules (`.claude/knowledge/trading-invariants.md`) and the architect's spec. Specifically check: exits/stops/liquidations still run while the clock is in doubt; entries are refused while in doubt; a restart never leaves a position without a stop; no live order path exists.
4. If something blocking remains, fix it (Step A tests first, then Step B code). Cap at two extra rounds, then write the open item into STATE.md for the PO.

## STEP D: merge R0 into the epic
```
git checkout epic/copytrade-v1 && git pull origin epic/copytrade-v1
git merge --no-edit feat/copytrade-v1/R0-runner
git push origin epic/copytrade-v1
```
Append a short "R0 APPROVED AND MERGED" section to `docs/sdlc/copytrade-v1/STATE.md` (final commit hash, test counts, open advisories) and push. Do NOT merge anything into `main` and do NOT merge PR #2 (epic -> main): that waits for the PO.

## STEP E: update the local-test guide and QA
1. Open `docs/sdlc/copytrade-v1/LOCAL-TEST.md`; change the checkout line to `git checkout epic/copytrade-v1`; remove the "DRAFT" note; push.
2. QA is done by the PO on his PC (paper only), following LOCAL-TEST.md section B (30-minute smoke test). Also ask the PO to measure the real order-book round-trip time from Brazil (the clock design depends on it): while the bot runs the console/alerts show `clock_unsynced` if it is not good enough.

## STEP F: the PO's tasks (not the assistant's)
- Smoke test (LOCAL-TEST.md B), then leave it running 2-4 weeks (C).
- Run `docs/sdlc/copytrade-v1/research/scripts/README.md` -> `hl_sample.py`, keep `summary.json` (it checks Hyperliquid response formats written from docs).
- After 2-4 weeks: zip `copytrade-data\ledger` and analyse: trade count (50-100 wanted), missed exits (must be 0), position mismatches, kill switches worked, paper P&L after fees/funding/slippage vs holding BTC. A short script reading the ledger (JSON lines, one record per line) or a spreadsheet is enough.

## STEP G: known follow-ups to schedule BEFORE the long paper run (not blockers for the smoke test)
- RISK-59: the ledger grows about 37 MB/day (checkpoint every 60 s with 500 seen ids) and retention scans the whole ledger on the trading thread: lengthen/compact the checkpoint and move pruning off the trading thread.
- RISK-60: restore turns a pending entry into CLOSED even if the broker holds the fill (spurious `startup_uncertain` + a valid copy closed): keep it pending so reconcile heals it.
- The advisory list in `docs/sdlc/copytrade-v1/reviews/R0-r1-batch.md` section D and in STATE.md.
Stage 2 features (F8, F9, F13, F15-F21, F23: event pause, per-signal filters, LLM explainer, evaluation) are ON HOLD by PO decision. Do not start them.

## If anything is unclear or a rule conflicts with a task
Stop and write the question into STATE.md (last section) for the PO instead of guessing. Safety first: when in doubt, refuse entries, never block exits, never touch live trading.
