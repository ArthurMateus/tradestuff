VERDICT: INCONCLUSIVE

# Backtest audit, round 2: copytrade-v1 (frozen pre-registration v2 and scripts)

Auditor: backtest-auditor · 2026-09-29 · branch `epic/copytrade-v1` @ `1eba7c6` · Python 3.11.15 · Hyperliquid network blocked.

**Why INCONCLUSIVE:**
- All 17 round-1 findings are fixed, and none regressed.
- All outputs reproduce byte-for-byte.
- `hl_sample.py` v2 has no remaining look-ahead in its gates or measurement, and no rate bug.
- The frozen rule is sound in structure, but has two cheap BLOCKING defects: **BT2-1**, where the direction-matched baseline is charged a delay cost it would never pay, and **BT2-2**, where mid-run code changes are an unrecorded variant channel.
- Fix both with a dated addendum to sections 5 and 6.2, before the PM spec and before run 1. With that done, this audit would be VALID. VALID would still say nothing about whether an edge exists.

## Reproducibility
| Command | Result |
|---|---|
| `python3 hl_sample.py --selftest` | `selftest OK (13 checks)` |
| `feasibility_mc.py --runs 2000 --seed 17` (E5) | Byte-identical, sha256 `a3b530d2…52ad` |
| `gate_power.py --sims 4000 --boot 1000 --seed 23 --jobs 3` (E6) | Byte-identical, sha256 `5a3a1b5d…a59b` |
| `few_clusters.py` (E10, seed 31) | Byte-identical, sha256 `bcb40402…ef16` |
| Script hashes | All four match section 12 |

All section 11, 5.9 and E6/E10 numbers match the outputs, except one trivial range (BT2-9).

## Round-1 findings: status
| ID | Status | Evidence |
|---|---|---|
| BT-1 | fixed | Window denominator. Truncation flagged. Self-tests 2 and 3. Residual: BT2-6. |
| BT-2 | fixed | `t_sel = end − 30d`. Gates use data at or before `t_sel`. Measurement uses opens after `t_sel` only. `fwd_leader_*` labels. Residual: BT2-7. |
| BT-3 | fixed | `value_at` uses the latest point at or before t, else excludes and counts the trade. |
| BT-4 | fixed | Min of three CIs. Frozen P2 false PASS is 1.1–1.3% at a day-factor correlation up to 0.5. Residual: BT2-4. |
| BT-5 | fixed | Hash in the run record, at most 2 runs, α 0.04/0.01, run register, no interim statistics. Family-wise false PASS 1.6% [1.3, 2.0]. Residual: BT2-2. |
| BT-6 | fixed | Joint P(PASS) reported as an upper bound. |
| BT-7 | fixed in structure | P2c gating, K9 on either condition. The cost specification is biased (BT2-1). |
| BT-8 | fixed | Realised lower bound plus mark-to-market upper bound, with a correlated scenario. |
| BT-9 | fixed | 3.1% / 0.4%, with denominators. |
| BT-10 | fixed | 3–5 trader, no-floor row: P(300 by day 60) = 0.43–0.45. |
| BT-11 | fixed | 4,000 sims per cell, B = 1,000, Wilson intervals. |
| BT-12 | fixed | Heavy tail: power 10% at +0.10R. FR1 and FR2 pre-registered. |
| BT-13 | fixed | Cost-in-R table, FR3/K12, spread recorded at signal time. |
| BT-14 | fixed | 300 opened trades. P3 window = `[t0, T_eval]`. |
| BT-15 | fixed | All 9 hashes verified. Path fixed. |
| BT-16 | fixed | Kaplan–Meier, mirrored adds, $10 rule, gates, dispersion, ATR stop. Drift is still at 1-minute resolution (labelled). |
| BT-17 | fixed (spec) | Resolution order, `dsr_resolution`, property test 14. |

## Frozen rule assessment
| Element | Assessment |
|---|---|
| α split 96% / 99% | Correct. The Bonferroni 2.5% bound holds for any data-dependent abort, so P&L visible to the PO can't inflate it. Simulated 1.6%, vs 3.2% for 2×95%. Implementable. |
| Min of three CIs | Formulas correct. Unspecified: the bootstrap statistic, the percentile index convention, the RNG algorithm, and the G = 1 case (BT2-3). |
| G ≥ 5 day clusters | Supported by E10 (0.9–1.6%). The change from 10 to 5 was made before any real data and is disclosed. Acceptable. F3 when G < 5 is unspecified (BT2-3). |
| P2c as a lower bound | Correct in principle. **Defect BT2-1.** |
| 7-day cap | Implementable. Hold and funding for marked trades are unspecified. It deviates from the PO's wording (BT2-5). |
| Verdict precedence | "G < 5 is INCONCLUSIVE" conflicts with FAIL precedence for G = 2–4. Low risk. |

**Match with the PO's decisions:**
- **Matches:** every research-phase decision.
- **Not visibly signed by the PO:**
  - the 96/99% levels
  - the min of three CIs
  - G ≥ 5
  - the 7-day cap
  - the lower-bound reading of "beating"

  All are conservative, but together they roughly halve power (BT2-5).

## Findings
| ID | Severity | Location | Finding | Why it matters | Required fix |
|---|---|---|---|---|---|
| BT2-1 | BLOCKING | `edge-hypothesis.md:385,393-396,403` | B0d pays "delay slippage from measured decay". A random-time entry has no signal to be late to, so D is inflated by the copy's own delay cost. P2c then tests the leader's gross timing, not our net value beyond beta. In a trending month with zero net timing value, P2 + P2c false PASS goes from 0.6–0.8% to 2.9–4.7% (+0.05R) and 11.6–14.4% (+0.10R). | This re-opens BT-7 at the scale of the prior edge. | Addendum: B0d pays fees plus the recorded spread and impact at its **own** times, plus the ack-delay drift at random times (≈ 0), never post-signal decay. Rewrite the `:393-396` rationale. Add an evaluation test. |
| BT2-2 | BLOCKING | `edge-hypothesis.md:177-184,263` | The run record hashes the doc and the config but not the engine code. "Bug fixes" continue the run with no definition, record or auditor ruling. | Mid-run behaviour changes are an unrecorded variant channel (D4). | Record the engine git commit and a dirty flag. Every mid-run deploy is logged with its diff and needs an auditor ruling (continue with the affected trades listed, or ABORTED). A change to signal, filter, scoring, sizing, exit, cost or fill logic is ABORTED by default. Add an evaluation test. |
| BT2-3 | ADVISORY | `:223-227,244-256,284,291` | Open edge cases: G < 5 with UB ≤ 0; the bootstrap statistic, percentile index and RNG; transitivity of merged-position overlap; `/flatten` inside S; B0d with no recorded window or a delisted coin; hold for marked trades; the run register editing the hashed file. | Divergent or unreproducible verdicts. | Precedence: F1/F2 → P1 incomplete → G < 5 (INCONCLUSIVE, no F3) → F3 → PASS → INCONCLUSIVE. Define the rest. Keep the register in the ledger, or exempt its appends from the hash rule. |
| BT2-4 | ADVISORY | `:225,345-351`; `gate_power.py:259-283` | With a continuous factor and holds crossing UTC days, frozen P2 alone under-covers: 1.7% (4h median hold), 2.5–3.2% (12h), 3.9% (24h), against a nominal 2%. P2c brings the conjunction back to ≤ 0.8% (≤ 1.3% with a trend). | A PASS is protected only because P2c is gating. | State this in 5.9. Make P2c non-removable. At `T_eval`, report (not gating) the median hold, the share of trades crossing a day boundary, and the P2 CI with overlap-component clusters. |
| BT2-5 | ADVISORY | `:223,226,236,547`; `decisions.md` | The 7-day cap deviates from "evaluated once after all have closed". The 96/99%, min of three CIs, G ≥ 5 and lower-bound P2c are not signed by the PO, and the split is mislabelled "PO". D11 still says 95%. | Run 1 power is 20% vs 41% naive at +0.10R; run 2 is 13–24%. | Record the PO's acknowledgement in `decisions.md` before run 1. Fix the label. |
| BT2-6 | ADVISORY | `hl_sample.py:213-230,226,562-564,591,206-211,850` | (a) The truncation flag counts aggregated fills, while the cap is on raw fills. (b) The cursor `max(time)+1` can drop fills that share a boundary millisecond. (c) A `userRole` error becomes "unknown" and passes the gate (fail-open). (d) `summary.json` lacks per-wallet first/last fill ms, page count and an ascending-order check. | The PO runs it once, so a shape failure would be undiagnosable. | Add these to `summary.json`. Also flag truncation when the first fill is more than 1 day after `sel_start` and a page was full. Set cursor = max time and dedupe. Report or exclude "unknown" roles. |
| BT2-7 | ADVISORY | `hl_sample.py:691-695,716-719` | The pool uses `allTime − month`, which is pre-`t_sel` only if the leaderboard `month` is a rolling 30 days. | A possible look-ahead in pool selection (D1). | Log leaderboard `month.pnl` next to the portfolio `perpMonth` change and its window start, or rank on portfolio P&L at or before `t_sel`. |
| BT2-8 | ADVISORY | `:293-305` | Fragility checks don't remove the best day or week. | One-regime profit isn't covered. | Add FR6: mean R without the best UTC-day cluster ≤ 0 is a go-live blocker. Report mean R by week. |
| BT2-9 | ADVISORY | `:350,823`; `gate_power.py:6` | The zero-edge joint figure should read 0.001–0.015. There is a hash backtick typo, and the docstring cites 5.0 instead of 5.3. | Traceability. | Correct them. |

**Positive observations:**
- The Bonferroni split protects against the PO seeing P&L.
- Every figure is honest and reproducible.
- The E10 bootstrap under-coverage was found and acted on.
- The `hl_sample` self-test has look-ahead traps.
- Survivorship is labelled everywhere.

## Assumptions the PO's first `hl_sample.py` run will test
1. `userFillsByTime` returns fills ascending from `startTime`.
2. The 10k cap counts raw fills.
3. The leaderboard `month` is a rolling 30 days.
4. The `portfolio` shape, and `perpAllTime` density.
5. Weights: `portfolio` 20 and `userRole` 60.
6. The shape of the `userRole` response.
7. How liquidation fills are marked.
8. The fill fields are present.
9. 1-minute candles go back at least 3 days.
10. There are about 15,000 leaderboard rows.
11. No geo-block (a 403 on everything means K10).

## For the PO
The rulebook is now honest and hard to fool. A no-skill strategy passes about 1–2 times in 100 across both runs. Nothing yet shows whether copying makes money. Two small rule fixes are needed: an honest cost for the random-timing comparison, and recording the code version with a review of any mid-run change. Please confirm the 96%/99% levels and the 7-day close-out cap. A real but modest edge will most likely come back INCONCLUSIVE.
