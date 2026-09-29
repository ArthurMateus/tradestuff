# Open questions: copytrade-v1 (discovery pass 1, with PO answers)

## Blocking (all answered 2026-09-29)
- Q1 Does the 1-month proof include build time? **No. Build v1 fully refined first; the month starts at the paper run.**
- Q2 Our SL/TP vs trader's exit? **Whichever happens first closes the copied position; later adds on it are ignored.**
- Q3 Sizing? **Mirror the trader's position as a fraction of their account value, capped by risk limits. Partials and adds mirror the trader's percentage (trader sells 40% -> we sell 40%). Stop is volatility-based config.**
- Q4 Paper account? **$300 USD, exchange minimums enforced; too-small orders logged as unexecutable.**
- Q5 Unit of a trade? **One copied position per trader share, open to fully closed; taken signals only.**
- Q6 Replay honesty? **Snapshot the leaderboard from day 1; only replays over recorded windows count; earlier replays are indicative only.**
- Q7 Candidate universe? **Top 200 leaderboard wallets (config), re-scored every 60 min (config), hysteresis top 8 in / below top 15 out / 24h minimum; leaderboard failure = fail closed. Always keep re-evaluating and swap in better traders.**
- Q8 Downtime? **Reconstruct on restart and flag trades; >2% downtime invalidates the run.**

## Important (PO accepted CTO defaults)
- Q9 5s signal age measured from exchange timestamp with clock-offset correction; validate with a 1-day latency measurement first.
- Q10 Rejected signals get shadow paper outcomes.
- Q11 Positions a trader held before being followed are ignored.
- Q12 Opposite-direction conflict = skip; same direction = add within the per-symbol cap, one merged post.
- Q13 15% drawdown = run verdict FAIL.
- Q14 Commands restricted to the PO's Telegram user and chat id; PIN hashed, from env; command path independent of feed/LLM.
- Q15 Alerts go to a separate Telegram chat.
- Q16 Isolated margin in the paper model.
- Q17 Decisions and research recorded in `docs/product/decisions.md` and `docs/research/`.
- Q18 Negative edge on an adequate replay = stop and review before the paper run.

## Nice to clarify (defaults)
- Q19 Currency: **USD** (PO decision); BRL deferred to the real-money epic.
- Q20 LLM: cheap cloud model with a hard monthly spend cap in config; no "why" text when over budget or down.
- Q21 Event calendar: data file from official Fed/BLS schedules, updated quarterly.
- Q22 Telegram edits batched to stay within rate limits.
- Q23 Phase-2 readiness: disclaimers on reports now; nothing more.

## Implicit requirements to carry into requirements.md
Idempotent event handling; reconciliation of mirrored shares against leader positions; secrets from env on Windows, never logged; no bypass of the risk gate (including /flatten and dropped-trader exits); config schema, validation, versioning, audit log, hard ceilings in code; timeouts and bounded retries on every external call with degraded mode; metrics and alerts; injected clock and seeded randomness in tests; pinned and scanned dependencies; honest all-trade stats with disclaimers; audit trail of commands. N/A in v1: exchange API key storage, multi-user kill switch, UI accessibility, webhooks.
