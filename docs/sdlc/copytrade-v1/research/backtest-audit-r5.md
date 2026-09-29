VERDICT: VALID

# Backtest audit, round 5 (light): copytrade-v1, Addendum A4 @ `3fa5dcf`

Scope (light, by PO token-economy decision):
- read: `backtest-audit-r4.md`; `edge-hypothesis.md` §5.13 and the `(A4.n)` marks, §9.2 rows, tests 25-29, E16, and §14 items 9-10; `eval_reference.py` v4
- not re-run: the other simulations and the 31-mutant harness (a throwaway outside the repo); the golden asserts cover the mutant targets

**Reproducibility:** `eval_reference.py` v4, run twice, prints `selftest OK (golden vectors asserted)`, with byte-identical output. Script `15522b60…c557` and output `e0e3da9f…dc04` match E16 in §12.

## BT4 status
| BT4 | Status | Evidence |
|---|---|---|
| 1 | fixed | Daily and final `userFillsByTime` audits; "handled" defined; fills and sizes reconciled; an incomplete audit breaches P4 after 72 h |
| 2 | fixed | Candle rule: 1m, else 1h; lo = worst + 8 bps; hi = best + 2 bps; gap-through SL/TP; hourly hashed candle store |
| 3 | fixed | Incremental chain costs plus trade cost; actual = realised |
| 4 | fixed | Breach time rules; ABORTED wins only if strictly earlier |
| 5 | fixed, one hole | Settled-gap rule. See BT5-1 |
| 6 | fixed | B̄ = max(with, without) for discretionary pauses; stricter only; complies with A1.4 |
| 7 | fixed | Untiered = alt for our trades, major for baselines; daily ledgered table |
| 8 | fixed (text and tests) | Stream and transport hashes, 5-minute chain, unhashed = gap, recompute from verified data, storage destination outside the config hash |
| 9 | fixed in text | Points (a)-(f) addressed. Item 9 inherits BT5-1 |
| 10 | fixed | Reworded |

**New false-PASS channels or unbounded waits:** no material false-PASS channel. The wait is bounded in practice, but the stated bound understates it.

## Findings
| ID | Severity | Location | Finding | Fix |
|---|---|---|---|---|
| BT5-1 | ADVISORY | EH:339,346,348; item 9 | An uncomputable mirror on a *settled* data-gap exit counts at actual R with no F2. That contradicts "a late fill after a gap never counts better". It needs a data gap, no recorded book and no exchange candles for > 72 h. Tiny effect; no plausible PASS. | Make it class 2 (reconstruction failed): it counts toward P4, costs +∞ and triggers F2. Correct item 9. |
| BT5-2 | ADVISORY | EH:362-366 | The reconciliation pass the verdict waits on has no retry bound. | Put it under the 72 h bound (breaching P4), or drop it from the preconditions, since the final audit covers it. |
| BT5-3 | ADVISORY | EH:346,366 | "Bounded after 72 h" understates the real bound: a late orphan starts a new candle retry, worst case about `T_eval` + 144 h (finite). | State the real bound, or share one 72 h budget from `T_eval`. |

None is BLOCKING.

**For the PO:** the ten round-4 gaps are closed. Three small wording and edge-case fixes remain before run 1. There is still no real data.
