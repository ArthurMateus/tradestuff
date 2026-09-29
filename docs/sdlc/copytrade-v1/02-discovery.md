VERDICT: CHANGES REQUIRED

Discovery pass 1 on the draft brief, 2026-09-29. Condensed from the discovery agent's report; the answers are in `03-answers.md`.

Goal (one sentence): within about one month of a paper run, show whether automatically copying top Hyperliquid traders is profitable after real costs.

## Blocking
| ID | Lens | Question | What it changes | Proposed default |
|---|---|---|---|---|
| Q1 | scope / time | Does "proven within 1 month" include the build? | Order of work, minimum slice | Month starts after deploy; build a minimum slice first |
| Q2 | exit ownership | Our SL/TP versus the leader's exits: which wins? | Core copy-engine logic and outcome measurement | First exit wins |
| Q3 | sizing | Proportional mirroring or risk-based sizing? Where does the stop come from? | Size, definition of R | Risk rule for entry, ATR stop, adds/partials mirror the leader's % |
| Q4 | capital | Paper equity versus exchange minimums? | Whether paper results transfer to live | $300, minimums enforced |
| Q5 | measurement | What is "one trade" and "R"? | Count and CI, so PASS vs INCONCLUSIVE | One position per trader share, taken only |
| Q6 | research validity | Point-in-time replay feasibility? | Survivorship bias in the gate | Snapshot from day 1 |
| Q7 | data / limits | Candidate universe size and leaderboard reliability? | Rate limits, discovery outages | Top 200, fail closed |
| Q8 | restart | Home-PC downtime handling? | Missed exits, honest stats | Reconstruct, flag, 2% downtime budget |

## Clarifying
| ID | Lens | Question | Proposed default |
|---|---|---|---|
| Q9 | latency | 5s cutoff: measured from what? Is it feasible from home? | Exchange timestamp, clock offset corrected; 1-day measurement |
| Q10 | measurement | Shadow outcomes for rejected signals? | Yes |
| Q11 | copy logic | Positions held before we followed the trader? | Ignore |
| Q12 | copy logic | Opposing or same-direction leaders? | Skip conflicts; same direction adds within the cap |
| Q13 | risk | 15% drawdown pause and the run verdict? | Automatic FAIL |
| Q14 | security | Command auth, PIN, independence from the feed? | Telegram id allow-list, hashed PIN from env, independent path |
| Q15 | observability | Where do alerts go? | Separate alerts chat |
| Q16 | risk | Margin model? | Isolated |
| Q17 | process | Decisions and research recorded? | Record them in the repo |
| Q18 | research | Negative replay edge? | Stop and review |
| Q19 | data | Currency conversion? | Daily PTAX |
| Q20 | cost | LLM spend? | Hard cap; no "why" text when over the cap |
| Q21 | data | Event calendar source? | Data file, quarterly |
| Q22 | limits | Telegram edit rate? | Batch edits |
| Q23 | phase 2 | Channel readiness? | Disclaimers only |

## Invariants the brief didn't address
- Idempotency of WebSocket events.
- Reconciliation of mirrored shares.
- Secrets from env on Windows.
- No bypass of the risk gate.
- Config schema and hard ceilings in code.
- Timeouts and bounded retries.
- Metrics and alerts.
- Deterministic tests.
- Pinned dependencies.
- Honest all-trade stats.
- Command audit trail.
