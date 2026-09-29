VERDICT: VALID

# Backtest audit, round 4: copytrade-v1, Addendum A3 and `eval_reference.py` v3

Auditor: backtest-auditor · 2026-09-29 · `epic/copytrade-v1` @ `0109b6f` · Python 3.11.15 · Hyperliquid network blocked.
HEAD moved to `209f295` during the audit, which only adds the PO's "ok" on items 9-10; the research files are unchanged. The spec is cited as committed at `0109b6f`.

**What VALID means here:** the pre-registration is still sound enough to build on.
- A3 follows rule 5.1 and faithfully encodes the PO's A4 and A14 decisions, mostly tightening them.
- All hashes reproduce, and all 16 mutants plus 8 of the auditor's own are killed.
- The 10 new findings are ADVISORY; none makes a pass by luck materially more likely.
- BT4-1, -2, -3, -5, -6 and -9 should go into a dated Addendum A4 before run 1. The PO must then re-acknowledge items 9-10, because the text they said "ok" to has inaccuracies (BT4-9).

## Reproducibility
| Check | Result |
|---|---|
| `eval_reference.py` (E15), run twice | `selftest OK (golden vectors asserted)`. Byte-identical, sha256 `f5a0dd09…ff55d`, matching §12 |
| All script and output hashes | Match §12 |
| E14 vs E15 | E14 reproduces `fbe80bb0…828b8f`. The diff is exactly as §12 claims |
| Mutation claim | 16 of 16 killed, plus 8 extra auditor mutants, 8 of 8 killed |
| Base-version hash in 5.12 | `e20ad5ed…4b40`. Matches |

## Criteria vs observed
There is no real data and no paper run. A3 changes no simulated operating characteristic: the round-3 figures stand (family-wise false PASS 1.6%; P2 + P2c 0.1-0.5%; run-2 power about 3-9%). Observed: nothing.

## Task checks
1. **Rule 5.1: compliant.** Every removed line is quoted verbatim, the additions are insertion-only, and the in-place marks are present.
2. **A4 and A14 faithfully encoded,** tightened where they differ. One narrow divergence: BT4-3.
3. **Loopholes:** none material for a pass by luck. BT4-1 and BT4-5 undercut "a bug never helps", and BT4-6 is an undisclosed `/pause` channel.
4. **Reproduction:** all numbers reproduce.
5. **Items 9-10:** mostly accurate. Two statements need fixing and three points are missing (BT4-9).

## Findings
EH = `research/edge-hypothesis.md`; SPEC = `04-spec.md` @ `0109b6f`.

| ID | Severity | Location | Finding | Why it matters | Required fix |
|---|---|---|---|---|---|
| BT4-1 | ADVISORY (before run 1) | EH:341,337,1015,1762; SPEC:578-583 | **Missed-exit detection is incomplete, but described as complete.** Reconciliation (F12.AC5, every 300 s, sign only) misses a dropped reduce, a close and reopen inside one interval, and a missed close where our SL/TP closes the share first. | These trades count at actual R with no min() and don't count toward P4. A silently dead `userFills` subscription produces exactly this. A3 tolerates 3 detected misses while undetected ones go uncounted. | A4: before the verdict (and daily, to stay under the 10k-fill cap), audit every followed leader's `userFillsByTime` over `[t0, T_eval]` against the ledger. Any unmirrored exit fill becomes an orphan missed exit before P4 and gate R. F12.AC5 compares sizes and fills, not only the sign. Correct EH:341 and item 9. |
| BT4-2 | ADVISORY (before run 1) | EH:334-335,1090; SPEC:600-608,1653 | **The fill price of a mirrored action over a recording gap is not frozen.** SPEC A20 isn't in the hashed file. Missed exits and gaps share causes. | Gate is protected by min(), but the choice of price within a candle moves mirror hi by 0.1-0.3R (1m) or ≥ 1R (1h). That is a way around F2. | A4: over a missing book, fill on the 1m candle (1h if the 1m is absent) at decision time + ack. lo = worst price + alt half-spread; hi = best price + major half-spread. With no candle: uncomputable, counted as > 1R, and mirror lo = actual. Fetch and hash the fallback candles during the run. |
| BT4-3 | ADVISORY | EH:339-340; SPEC:601 | **Cost is per trade, not per missed exit.** Two missed exits net each other: +1.3R and −0.5R give 0.8R, so no F2. "Actual R" for a flattened trade is undefined. | A narrow way around F2 that the PO's wording doesn't allow. The spec contradicts A3. | A4: FAIL if any missed exit's incremental cost, or the per-trade total, is > 1R. Actual R in the cost = realised R. |
| BT4-4 | ADVISORY | EH:269,287,340-341; `eval_reference.py:283-293`; SPEC:602,835-837 | **F2 timing is inconsistent.** The text says F2 fires when the 4th exit is ledgered; P4 counts by leader event time. A breach found at verdict time gives INCONCLUSIVE by the text but FAIL by the code. | It can't produce a PASS, but it changes FAIL vs INCONCLUSIVE and the K13/K4 recommendation. | A4: any P4 breach with leader events in the window is F2. The breach time is the leader event time of the 4th, or when the cost is established. The spec follows. |
| BT4-5 | ADVISORY (before run 1) | EH:328,331,342; SPEC:123,226-229 | **"Settled" is defined only for process restarts.** A WebSocket data gap has no reconstruction. Read literally, any exit inside a 5-s gap is a missed exit, which risks a spurious F2. Read leniently, a late fill counts at actual R, and lateness can help. | Ambiguous either way. | A4: an exit inside a data gap is settled if mirrored within `missed_exit_max_lag_s` of resync, with gate R = min(actual, mirror lo). Otherwise it is class 2. |
| BT4-6 | ADVISORY (before run 1) | EH:398,1018,1074,1079,1780 | **Excluding paused time from B0d cuts both ways.** A pause during a stretch that is good for the copy's direction lowers B̄ and raises D, by about 0.02-0.04R per affected trade (arithmetic). This is undisclosed, and it weakens P2c, which A1.4 forbids. | Disclosure is incomplete and it violates A1.4. | A4: for discretionary pauses (`/pause`, deploy-wait), B̄_i = max(including, excluding the paused time). Keep plain exclusion for process_down, data_gap, access_degraded and disk_low. Or correct the text and item 10. |
| BT4-7 | ADVISORY | EH:1105; SPEC:1639,1655 | **Untiered coins get the lenient cost in B1,** which makes K9 easier. The tier table is "frozen at run start" in one place and "recomputed 24 h" in another. | A go-live blocker is lenient on one side; the rule is ambiguous. | Comparators use the major fallback for untiered coins. Thresholds frozen; assignments recomputed daily from recorded data and ledgered. |
| BT4-8 | ADVISORY | EH:1086-1091,1282; SPEC:602 | **Recording integrity:** (a) compressed vs uncompressed hash; (b) a file never closed has no hash; (c) F2 cost is computed from files not yet hashed; (d) the storage destination sits in the frozen config, so an outage costs P5 or forces an ABORTED change. | Uncertainty around crashes; (d) is a way to waste a run. | Hash the uncompressed stream plus the transport object. A file with no hash is a gap; hash-chain segments every N minutes. Recompute F2 costs from verified files at `T_eval`. Consider moving the storage destination out of the config hash. |
| BT4-9 | ADVISORY (re-ack needed) | EH:1762,1764,1766-1767,1776-1782 | **Items 9-10 text:** (a) "a bug can never improve the verdict" is false for undetected or post-gap exits; (b) "generously" reads backwards; missing: (c) an F2 FAIL ends the run and uses one of the 2 runs, (d) 1R ≈ $1.50, (e) `/stats` shows realised figures while the verdict's can be lower, (f) the two-sided `/pause` effect. | The PO signed wording that overstates a guarantee. | Reword in A4, and the PO acknowledges the final text. |
| BT4-10 | ADVISORY | EH:337,1015 | **"Can only lower" is slightly overstated:** B0d's hold uses the later close; lowering one R can in rare cases raise the t-interval lower bound. | Negligible, but these are frozen statements. | Reword to "never raises a trade's R or USD; D_i and LB_r are affected only negligibly". |

**Positive observations:**
- The lo/hi split is the right design.
- The verdict waits `T_eval` + the lag.
- ME can't be cleared by a PO review alone.
- The rounding vector discriminates.
- The Bonferroni argument for `/stats` is correct.
- A3.5 correctly needs no rule change.

## For the PO
- Your changes (up to 3 tolerated missed exits, and `/stats`) were written in honestly. A no-edge bot still passes by luck only about 1-2 in 100 across both runs.
- There is still no real data.
- Three things to fix before run 1:
  - missed exits the bot never notices (the fix is a full check against every trader's fill history)
  - how the on-time alternative is priced when a recording gap coincides with a missed exit
  - pausing during a rally slightly flattering the baseline test
- Re-confirm items 9-10 after their wording is corrected.
