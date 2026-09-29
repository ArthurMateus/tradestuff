VERDICT: VALID

# Backtest audit, round 3: copytrade-v1 (v2 + Addendum A1 and scripts)

Auditor: backtest-auditor · 2026-09-29 · branch `epic/copytrade-v1` @ `75f1fbf` (clean tree) · Python 3.11.15 · Hyperliquid network blocked.

VALID means the pre-registration and scripts are sound enough to build the spec on. It says nothing about whether an edge exists, because there is still no real data.

**Why VALID:**
- BT2-1 and BT2-2 are fixed, BT2-3 to BT2-9 are fixed, and nothing regressed.
- Every output reproduces byte-for-byte, and every hash matches section 12.
- An independent re-implementation of the A1.3b bootstrap and RNG, written from the text alone, reproduces the E13 vectors exactly.
- A1 complies with the 5.1 rule in substance and never makes a PASS easier.
- There are 7 new ADVISORY findings. BT3-1 and BT3-5 should be fixed in a dated Addendum A2, or in the spec, before run 1.

## Reproducibility
| Command | Result |
|---|---|
| `hl_sample.py --selftest` (E12) | `selftest OK (18 checks)`. 4 of 4 mutants killed. |
| `eval_reference.py` (E13), run twice | Byte-identical, sha256 `f335b6c2…f294` |
| Independent re-implementation of the RNG, bootstrap and `b0d_start` from the text | Identical: 96% (0.153333, 0.356667); 99% (0.143333, 0.383333) |
| Cluster-robust t interval by hand | (0.0956, 0.3978). Matches. |
| `t_ppf` against closed forms | Error ≤ 1e-12 |
| `b0d_cost_fr6.py` (E11, seed 41) | Byte-identical, sha256 `63813d96…606b` |
| `gate_power.py` E6, v2.0.1 | Byte-identical, sha256 `5a3a1b5d…a59b`. The diff since round 2 is docstring-only. |
| All 6 script hashes and 7 output hashes | Match section 12 |
| E5 / E10 | Not re-run. The scripts are unchanged since round 2, which reproduced them. |

E11 figures: corrected rule 0.1–0.5%; superseded wording 0.3–1.8% (0.05R) and 0.8–6.4% (0.10R); P2 alone in a trending month 8–34%; FR6 upper 95% bounds 0.4–3.6%. All match the output.

## Criteria vs observed
There is no real data and no paper run, so nothing has been observed. The synthetic operating characteristics:
- **P1** (300 opened by day 60): 0.43–1.00, depending on the scenario.
- **P2** at zero edge: 1.1–1.3% at 96%.
- **P2 + P2c** in a trending month with zero net timing value: 0.1–0.5%.
- **Family-wise false PASS** over 2 runs: 1.6% [1.3, 2.0].
- **FR6** fired in 0 of the passing runs under a homogeneous edge.
- **Real variants** 0, **paper runs** 0.

## Round-2 findings: status
| ID | Status | Evidence |
|---|---|---|
| BT2-1 | fixed | 6.2 B0d `:481`, 6.3 `:523-524`, rationale `:489-503`, 9.2 `:685`, test 10. B0d pays fees, spread and impact at its own fills, its own ack drift, and funding; no decay. Residual: BT3-3(b). |
| BT2-2 | fixed | Run record `:188-190`. Deploy rules `:287-299` (ABORTED by default, CONTINUE only on an identical replay). 8.1, register, test 11. Residual: BT3-2. |
| BT2-3 | fixed | Precedence `:276-285`; bootstrap and RNG `:238` (reproduced); transitive components `:235`; `/flatten` `:301-307` (residual BT3-1); marked trades `:233`; admissibility `:505-516` (residual BT3-3); register outside the hashed file `:333-338`. |
| BT2-4 | fixed | 5.9 `:412,423-427`; P2c non-removable `:193,249`; cross-day diagnostics `:317-321`; test 20. |
| BT2-5 | fixed (labelling); PO acknowledgement pending | Label `:670`; section 14 and the 8.1 precondition `:580`. Residuals: BT3-4 and BT3-5. |
| BT2-6 | fixed | Second truncation rule; cursor = max time plus dedupe; roles fail closed; `fetch` metadata; checks 14–18. Minor residual: ≥ 10k raw fills that aggregate to fewer than 2,000 rows go unflagged, but this is diagnosable from `first_fill_ms`. |
| BT2-7 | fixed | `month_pnl_check`, `leaderboard_month_check`, check 18. |
| BT2-8 | fixed | FR6 `:359`, S6 `:374`, test 19. |
| BT2-9 | fixed | `:410`, `:993`, docstring 5.3. |

**Addendum A1 against rule 5.1:**
- **Compliant in substance:** dated before run 1, every change marked `(A1.n)`, and PASS only tightened (checked against `git diff 1eba7c6..75f1fbf`).
- **Literal gap:** some replaced text is described rather than quoted (BT3-6).
- **Double counting:** none in the statistics. One wording risk: BT3-3(b).

**Pending PO acknowledgements (section 14):**
1. CI levels 96% then 99%
2. min of three CIs
3. G ≥ 5
4. 7-day close-out cap
5. lower-bound reading of "beating B0d"

Recommended additions (BT3-4):
6. a code deploy ruled ABORTED consumes one of the 2 runs
7. `/flatten` counts min(realised, shadow)
8. recording gaps can fail P2c through the 10% missing-window rule

## Findings
| ID | Severity | Location | Finding | Why it matters | Required fix |
|---|---|---|---|---|---|
| BT3-1 | ADVISORY | `:233,235,301-307,481` | A1.3d doesn't define when a flattened trade "closes" for `T_eval`, `hold_i`, the merged-position interval or marking. The PO could `/flatten` the open trades in S after `t300`, ending the evaluation at a moment they choose. | A small optional-stopping channel. | A2: a flattened trade closes at its **shadow** exit for `T_eval`, `hold_i`, merging, B0d and P3. A shadow still open at `t300 + 7 d` is marked. Extend test 15. |
| BT3-2 | ADVISORY | `:188-190,288,294,299,333`; `run-register.md:7` | (a) Which commit manages positions while entries are paused. (b) The dirty flag and commit cover all tracked files, including `docs/**`, which the register appends make dirty, so every docs commit becomes a "deploy". (c) Installed packages and gitignored data inputs aren't hashed. | Internal contradictions could waste a run or breach P5. (c) is a residual variant channel. | Define the engine path set (code, lockfile, config, data inputs), or run from a dedicated worktree pinned to the run commit. Only the recorded commit runs until a ruling. Hash the installed-package list and the data inputs in the run record. |
| BT3-3 | ADVISORY | `:249,513-516`; `eval_reference.py:173-175`; `:481` | (a) `D_i = min(R_i, 0)` can exceed the true D when `B̄_i > max(R_i, 0)`, and missing windows concentrate on long, high-beta holds. So "gaps can't help pass" is false; the 10% cap bounds the effect. (b) The ack drift and the book walk could be double-added. | A bounded beta leak; noise double counting. | (a) `D_i = min(R_i, 0, R_i − B̄_i^partial)`, or correct the claims, and report the pre-paper recorder gap rate. (b) State that B0d R comes from fill prices; the drift and spread are reported decompositions, never added. |
| BT3-4 | ADVISORY | `:20,1042-1057`; `:193,298,304,515` | Section 14 omits these A1 tightenings: a deploy ruled ABORTED consumes a run, and pause time counts toward P5; `/flatten` can only hurt; recording gaps can fail P2c; A1.4 binds future addenda. | The acknowledgement must be complete before run 1. | Add items 6–8 (and optionally A1.4), each with its "if no" consequence. |
| BT3-5 | ADVISORY | `:1053`, `:1040`; `gate_power_seed23.txt:74,82,90,98`; `:446,1047` | Item 1 quotes run-2 power of 13–24%, which is the iid figure. With merged positions (E6 D2), frozen P2 at 99% is 8.6% (no beta) and 2.7–6.4% (beta), before P2c. "D11 says 95%" is wrong; the 95% is in `01-brief.md:27,127`. | The PO would sign on a figure that is 2–4× overstated. | State run 2 ≈ 9% (no beta) and ≈ 3–6% (beta), before P2c. Cite `01-brief.md`. |
| BT3-6 | ADVISORY | `:438-448` | A1.3 describes rather than quotes several replaced v2 texts. | Traceability (D4). | Record the v2 file as commit `1eba7c6`, sha256 `36e35a032a6792a6182903e34872d7d0370118647b5789595e4e366e68a26fb1`, or quote the lines. |
| BT3-7 | ADVISORY | `eval_reference.py:35,52,110,124,178,208-276`; `:237-238`; `b0d_cost_fr6.py:65` | Section labels are off. The self-test has no golden asserts, so a percentile off-by-one survives it. The seed isn't specified as 32 raw bytes. E11 uses k = 20 B0d replications, undisclosed. | Robustness of the reference. | Fix the labels, add golden asserts, specify raw bytes, disclose k = 20. |

**Positive observations:**
- The B0d decomposition is correct.
- The identical-replay bar for CONTINUE is right.
- The reference implementation plus vectors makes the verdict reproducible across languages.
- The E12 mutation check is real.

## For the PO
**What this proves:** the rulebook is fixed, honest, reproducible and hard to game. A no-skill strategy passes about 1–2 times in 100 across both runs, and a market-riding one at most about 1 in 200.

**What it doesn't prove:** whether copying makes money. A modest real edge most likely comes back INCONCLUSIVE, and run 2 is much harder than stated: about 3–9%, not 13–24%.

**Before run 1:**
- Two small wording fixes.
- The PO signs the five choices plus three more: an emergency code fix during a run normally uses up that run; a manual flatten only counts against the result; recording gaps can fail the baseline test.

**What could still make it wrong live:**
- optimistic paper fills
- undocumented Hyperliquid data behaviour
- the Brazil access deadline of 2026-10-30
- one-regime profits
