# Brief: copytrade-v1: AI-filtered copy-trading bot (Hyperliquid + Telegram, paper trading)
Date: 2026-09-29 · PO: repo owner · Compiled by the CTO from the brainstorm. Written so an agent with zero context can act on it.

## Goal
A bot that continuously finds proven, recurring profitable day traders on Hyperliquid, filters their moves with deterministic rules, and copies them automatically into a **$300 USD paper wallet at real mainnet prices**. It mirrors entries, adds, partial exits and full exits, and reports every trade in a private Telegram chat. v1 is built as refined and complete as possible **before** the paper run starts. The paper run must then give an honest verdict on whether copying is profitable after real costs, within about 1 month.

## Why now
The PO wants to trade this themself first and later sell it as a paid subscription. It must be proven with paper money before any real money or subscriber is involved.

## Users and roles
- **Phase 1 (this epic):** the PO alone, in a private Telegram chat, in paper mode.
- **Phase 2 (later epics):** paying subscribers through a Telegram channel. This is gated by a Brazilian legal opinion, a CNPJ and an accountant (decision D12).

## Problem
Copying traders naively loses money:
- leaders get lucky
- copy delay and fees eat the edge
- leverage liquidates followers
- leaderboards reward survivorship

The PO needs a system that picks traders on evidence, protects capital, and proves its own profitability honestly.

## Desired outcomes (numeric)
- Follow 5–10 traders (hard max 10), picked automatically and re-scored every 60 minutes (configurable).
- Signal-to-decision fast enough to skip anything older than 5s. Measure it from the exchange timestamp, correcting for clock offset. Validate with a 1-day latency measurement from the PO's home connection before fixing the value.
- Go-live gate:
  - The lower bound of the 95% CI of mean trade R is above 0, over at least ~300 paper trades, net of all costs.
  - Max drawdown under 15%.
  - Zero missed exits.
  - Downtime under 2%.

## Main flows
1. **Discover and rank traders.**
   - Take the top K candidates (default 200) from the Hyperliquid leaderboard and score them every N minutes (default 60), within API rate limits.
   - Keep checking both the followed traders and the candidates, and swap in a better trader when one clearly outperforms the weakest followed trader.
   - Hysteresis: a trader joins when in the top 8 and is dropped below the top 15, with a minimum follow of 24h. All of this is config.
   - Save leaderboard snapshots from day 1 so replays can be point-in-time.
2. **Detect a move.** Real-time fills and positions of followed traders arrive over the Hyperliquid WebSocket. Classify each as open, add, partial reduce or full close. Duplicated or replayed events are handled idempotently.
3. **Filter it.**
   - Deterministic rules decide yes or no: trader score, trend, volatility regime, liquidity, spread, funding, economic-event windows, signal age, and slippage versus the leader's price.
   - An LLM only writes the "why" text and a news summary. It has no vote.
   - Every verdict is logged. Rejected signals get a shadow paper outcome, so the filter's value can be measured.
4. **Size and enter (auto, no confirmation).**
   - Our position is the same fraction of our wallet as the trader's position is of their account, then capped by every risk limit. The cap always wins.
   - A paper fill is simulated against the live mainnet order book.
5. **Manage the position.**
   - Adds and partial exits mirror the trader's percentage change (the trader sells 40%, we sell 40%).
   - Stop-loss is volatility/ATR-based config. The stop ratchets to lock in profit and never widens. An add that would need a wider stop is skipped.
   - Take-profit is config.
   - Whichever comes first closes the position, our SL/TP or the trader's exit. After our SL/TP closes it, later adds by the trader on that position are ignored. A fresh open by the trader is a new signal.
6. **Report in Telegram.** A colour-coded (emoji) post shows:
   - symbol, direction, entry, SL, TP, size and leverage
   - the trader name(s), with their win rate and P&L
   - the "why" text

   The post is live-edited as the position changes. There is a daily and weekly report with a disclaimer.
7. **Control.**
   - Commands: /status, /pnl, /traders, /pause, /resume, and /flatten (which needs a PIN).
   - Only the PO's Telegram user and chat id are accepted.
   - Alerts go to a separate chat.
8. **Replay.** Replay followed traders' historical fills through the same engine, using only the leaderboard snapshots we recorded ourselves. Earlier history is labelled "indicative only".
9. **Restart after downtime.** Reconstruct the gap from traders' fills and historical prices, settle paper positions with our SL/TP, and flag those trades "reconstructed".

## Data and sources
- **Hyperliquid official API** (REST + WebSocket): wallet fills, positions and order books. Limits: 10 users per WS connection, 10 connections per IP. The leaderboard comes from an undocumented stats endpoint. If it breaks, keep the current traders, add none, and alert.
- **OKX public copy-trading endpoints:** fallback candidate/signal source, lowest-priority feature.
- **Economic calendar:** a data file built from the official Fed and BLS schedules, updated quarterly.
- **LLM:** a cheap cloud model with a hard monthly spend cap in config, and Ollama as an offline fallback. If it is down or over budget, the post goes out without the "why" text.
- Background research: `research/brainstorm-domain-research.md`.

## Constraints
- **Budget:** $0–50/month until proven.
- **Hosting:** the PO's Windows PC, kept awake. It must run on Windows.
- **Language:** Python. Latency is dominated by the network, and async is sufficient.
- **Money:** paper wallet $300 USD. Future live wallet $100–500. Hyperliquid's minimum order size, lot and tick rules are enforced in paper. Orders too small to execute are logged as "unexecutable", never faked.
- **Venue:** the PO is in Brazil. Binance futures is restricted for Brazilians, and a Central Bank deadline for foreign crypto providers falls on 2026-10-30.
- **Currency:** USD everywhere.

## Risk appetite and hard limits
Low for real money; aggressive experimentation in paper. These are config defaults with hard ceilings enforced in code:
- **Per trade:** ≤1% of the wallet at risk.
- **Leverage:** default 3x. Ceiling 5x on alts and 10x on BTC/ETH. 40x is not allowed.
- **Loss limits:** daily 2%, weekly 5%. A 15% drawdown from peak pauses the bot until /resume **and** makes the paper run a FAIL.
- **Exposure:** ≤10 concurrent positions, a cap on BTC-correlated open risk, and a per-trader allocation cap.
- **Signal freshness:** skip signals older than 5s, or with slippage above 0.3% (majors) or 0.8% (alts). Never chase.
- **Macro events:** pause new entries around FOMC (−30/+60 min) and CPI/PCE/NFP (−15/+30 min). Halve size when realised volatility is above a config percentile.
- **Conflicts:** if traders take opposite directions on a symbol, skip the conflicting signal. Same symbol and same direction from several traders makes one merged post, with each trader's share tracked separately so each trader's exits close only their share.
- Positions a trader already held before we started following them are ignored.
- Margin model: isolated.

## Must never happen
- A real order, real keys, or real money in this epic.
- An order that bypasses the risk gate, including /flatten and a dropped trader's exits.
- A position left open because we missed the trader's exit.
- Performance numbers that exclude losing trades, downtime-affected trades, or rejected signals' costs.
- The LLM changing whether or how much we trade.
- Anyone other than the PO controlling the bot.

## In scope
The 12 parts below are all built before the paper run:
- trader discovery and re-evaluation
- signal detection
- the filter
- paper execution at real prices
- sizing and exits
- duplicate and conflict handling
- risk controls
- economic-event awareness
- the Telegram bot
- the ledger and reporting
- replay
- restart reconstruction

The OKX fallback is the lowest priority.

## Out of scope
- Real-money execution, and the Hyperliquid testnet.
- Memecoins and on-chain spot.
- Binance and other exchange execution.
- WhatsApp, subscribers, payments, KYC, and a Telegram Mini App.
- An ML-trained filter. Data is collected now; the model comes later.
- Cloud hosting.
- BRL conversion and tax exports (needed before real money).

## Success metrics and how they're measured
- **One trade** is one copied position per trader share, from open to fully closed (adds and partials included). Only taken signals count. **R** is P&L divided by the initial risk at entry.
- The report computes mean R with a 95% CI from the append-only ledger, net of fees, spread, slippage, funding and copy delay. It returns PASS, FAIL or INCONCLUSIVE.
- The replay over our recorded window must agree in sign with the paper run.
- The go-live test is based on trade count, not calendar time. If there are too few trades after 1 month, the result is INCONCLUSIVE, not PASS.
- Before the paper run is declared started, the full pipeline must run a 24h dry run with no crashes.

## Kill criteria
- The replay and the paper run show no positive edge after costs, at an adequate sample size.
- Hyperliquid data access becomes unavailable or prohibited.
- An adequate replay shows a negative edge. In that case, stop and review before the paper run.

## Known unknowns
- Real latency from the PO's home connection.
- Stability of the leaderboard endpoint.
- How much fill history the API exposes per wallet.
- Whether ~300 trades are reachable in 1 month with 5–10 traders.
- Telegram edit rate limits under load.

## Glossary
- **R:** P&L in units of initial risk.
- **Trader share:** our portion of a merged position attributed to one trader.
- **Shadow outcome:** the simulated result of a rejected signal, kept out of the portfolio.
- **Hysteresis:** separate join and drop thresholds, so traders aren't churned on noise.
- **Paper:** simulated fills at real mainnet prices.

## PO decisions made during brainstorm
All of them, with reasons, are in `docs/product/decisions.md` (the 2026-09-29 entries: D1–D13 plus rounds 3–4). Discovery Q&A: `02-discovery.md` and `03-answers.md`.
