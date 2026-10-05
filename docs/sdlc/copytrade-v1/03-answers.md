# PO answers to discovery (2026-09-29)

The PO's words are quoted where given. The brief (`01-brief.md`) was updated to reflect every answer.

| ID | Status | Answer |
|---|---|---|
| Q1 | answered | "no, it does not include building it, i want to make it as refined as possible before trying the paper trading". The full v1 is built first; the month starts at the paper run. |
| Q2 | answered | "yes, whatever happens first". |
| Q3 | answered | "size of wallet according to trader most likely depending on budget, also for the sell it is the example you said, sell 40%, we sell 40%". Size mirrors the trader's position as a fraction of their account, capped by risk limits. |
| Q4 | answered | "paper wallet can be 300". |
| Q5 | answered | "yes, that is one trade". |
| Q6 | answered | "sounds good for the replay". |
| Q7 | answered | "good for the traders". Also: "always check the traders to see how they are doing, if there are better traders whenever there are better performing ones". |
| Q8 | answered | "on restart we can reconstruct, but probably wont be a big problem". |
| Q9–Q18 | default accepted | As proposed in `02-discovery.md`. |
| Q19 | answered | "go for USD instead of BRL". |
| Q20–Q23 | default accepted | As proposed. |

Earlier brainstorm answers (budget $0–50, own Windows PC, paper instead of testnet, no CNPJ or accountant yet, fully automatic trader selection, 5–10 traders, target 1 month, future wallet $100–500, Python, private chat now and a channel later) are in `docs/product/decisions.md`.

## Research-phase decisions (2026-09-29)
The PO accepted all 15 CTO recommendations after the backtest audit ("sounds good, lets run with 300$"). They are logged individually in `docs/product/decisions.md`. In summary:
- **Research gate:** proceed.
- **Run length:** extend to 60 days if fewer than 300 trades by day 30.
- **Risk:** 0.5% per trade.
- **Extra PASS conditions:** USD P&L > 0, beating a direction-matched baseline, and a day-clustered CI.
- **R:** initial-risk R for the gate, with max-risk R also reported.
- **Sample:** 300 opened trades, at most 2 runs.
- **Minimum order:** $10 partial-exit rule.
- **Following:** at most 9 wallets, with an incremental backfill first.
- **Markets:** crypto only, recording HIP-3 data.
- **Recording:** market data from day 1.
- **Blackouts:** entries and adds only.
- **Access:** alert and pause if Hyperliquid access degrades.
- **Costs:** hourly funding; delisting settlements count as normal trades.
- **Data:** no paid S3 data.

On the PO's questions:
- **A.** Fixed connection.
- **B.** The PO will run the fixed `hl_sample.py` once.
- **C.** Wallet $100–500. Paper is $300 and live starts at $300 or more.
- **On stocks:** excluded from v1 trading; data is recorded for a later epic.
