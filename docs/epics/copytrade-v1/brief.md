# Brief: Copy-trade signal bot v1 (Hyperliquid + Telegram, paper trading)
Slug: copytrade-v1 | Status: final, awaiting PO go for `/epic` | Date: 2026-09-29

## Problem and outcome
The PO wants a bot that continuously finds proven, recurring profitable day traders, filters their moves, and copies them automatically with controlled risk, reporting everything in Telegram. v1 is built as refined and complete as possible FIRST; then a paper-trading run at real market prices must prove (or disprove) that copying is profitable after real costs, within ~1 month of the run starting. Build time is not part of that month.

## Who benefits and how
- Phase 1 (this epic): the PO alone, private Telegram chat, paper trading only, USD.
- Phase 2 (later epics): paying subscribers through a Telegram channel. Gated by a Brazilian legal opinion, CNPJ and accountant (see `docs/product/decisions.md`).

## Scope of v1 (all items built before the paper run starts)
1. **Trader discovery and continuous re-evaluation (fully automatic).**
   - Source: public Hyperliquid wallets (official API). The leaderboard (undocumented stats endpoint) provides candidates. Fallback candidate/signal source: OKX public copy-trading endpoints (lowest priority task).
   - Score the top K candidates (config, default 200) every N minutes (config, default 60) within API rate limits. Always keep checking followed traders and candidates; when a candidate clearly outperforms the weakest followed trader, swap them.
   - Follow the best 5-10 (hard max 10). Hysteresis: join when in top 8, drop when below top 15, minimum 24h follow (all config).
   - Score is data-driven config: risk-adjusted return (Sortino, Calmar), win rate, P&L ratio (profit factor), trade count, consistency across rolling windows, max drawdown, copyability after our delay and costs, deflated-Sharpe luck correction. Eligibility gates and blow-up detectors (martingale / grid / averaging-down) per `docs/research/copytrade-v1-domain-research.md`.
   - A dropped trader's open copied positions keep mirroring that trader's exits until closed.
   - If the leaderboard breaks: keep current traders, stop adding new ones, alert (fail closed).
   - Save leaderboard/candidate snapshots from day 1 (needed for honest replay).
2. **Signal detection.** Real-time fills/positions of followed traders via Hyperliquid WebSocket. Detect opens, adds, partial reductions, full closes. Idempotent against duplicate or replayed events. Positions a trader held before we followed them are ignored; only new opens are copied.
3. **Filter (yes/no).** Deterministic, measurable rules decide: trader score, trend, volatility regime, liquidity, spread, funding, economic-event windows, signal age, slippage vs leader. An LLM (cheap cloud model, hard monthly spend cap in config; Ollama as offline fallback) only writes the "why" text and news summary; it has no vote. If the LLM is down or over budget, the post goes out without the "why". Every signal and verdict is logged; rejected signals get a shadow paper outcome (same engine, kept out of the portfolio) so the filter's value can be measured.
4. **Paper execution at real prices.** Simulated fills against the live Hyperliquid mainnet order book with fees, spread, slippage, copy delay, funding, partial fills, isolated-margin liquidation, and exchange minimum order size / lot / tick rules. Paper wallet: $300 USD. Orders that would be below the exchange minimum are logged as "unexecutable", never faked. Auto-entry (no confirmation).
5. **Sizing and exits.**
   - Entry size mirrors the trader: our position as a fraction of our wallet = the trader's position as a fraction of their account value, then capped by every risk limit (risk per trade, leverage caps, exposure caps). The cap binds, never the other way round.
   - Adds and partial exits mirror the trader's percentage change: trader sells 40% of their position -> we sell 40% of ours (rounded down to lot size; a remainder below minimum is closed).
   - Every position has a stop-loss (volatility/ATR-based, config) and a take-profit. The stop ratchets to lock in profit and never widens; an add that would need a wider stop is skipped.
   - Exit authority: whichever happens first closes. If our SL/TP closes the position, that copied position is over and later adds by the trader on that position are ignored; a fresh open by the trader is a new signal.
6. **Duplicate and conflict handling.** Same symbol + same direction from several traders = one Telegram post listing all traders; each trader's share is tracked separately so each trader's exits close only their share; total size stays within the per-symbol cap. Opposite direction on a symbol we already hold = skip the conflicting signal.
7. **Risk controls** (config with defaults and hard ceilings enforced in code): max 1% of wallet at risk per trade; leverage default 3x, ceiling 5x alts / 10x BTC-ETH; daily loss 2%, weekly 5%; 15% drawdown from peak -> pause until /resume AND the paper run's verdict is FAIL; max 10 concurrent positions; BTC-correlated open-risk cap; per-trader allocation cap; skip signals older than 5s (measured from exchange timestamp, clock offset corrected; validate with a 1-day latency measurement before fixing the value) or with slippage beyond 0.3% majors / 0.8% alts; never chase.
8. **Economic-event awareness.** Pause new entries around FOMC (-30/+60 min) and CPI/PCE/NFP (-15/+30 min); halve size when realized volatility exceeds a config percentile. Event dates from a data file sourced from the official Fed/BLS schedules.
9. **Telegram bot (private chat).** Only the PO's Telegram user/chat id may use it. Color-coded (emoji) posts: symbol, direction, entry, SL, TP, size, leverage, trader name(s), their win rate and P&L, why. Posts are live-edited as the position changes (within Telegram rate limits). Commands: /status, /pnl, /traders, /pause, /resume, /flatten (PIN). The command path works when the data feed or LLM is down. Alerts (feed lag, crash, drift, kill-switch) go to a separate alerts chat. Daily and weekly reports with a past-performance/risk disclaimer. Layout designed to become a subscriber channel later.
10. **Ledger and reporting (USD).** Append-only record of every signal, decision, simulated order, fill, fee, funding, pause and command (who, when, state before/after). UTC storage. Performance computed over all taken trades, net of costs, reproducible from the ledger.
11. **Replay.** Replay followed traders' Hyperliquid fills through the same engine using only the leaderboard snapshots we recorded ourselves (point-in-time). Replays on unrecorded history are labeled "indicative only" and do not count toward the go-live gate. If an adequate replay shows negative edge, stop and review before the paper run.
12. **Restart after downtime.** On restart, reconstruct what would have happened during the gap from traders' fills and historical prices, settle paper positions with our SL/TP, flag those trades "reconstructed". Downtime above 2% of the run invalidates the run.

## Definitions
- **One trade** = one copied position per trader share, from open to fully closed (adds and partials included). Taken signals only; rejected signals are tracked separately as shadow outcomes.
- **R** = trade P&L divided by the initial risk at entry (distance to stop x size).

## Success metrics (go-live gate for real money)
- Paper run net of all costs: lower bound of the 95% CI of mean trade R > 0, with >= ~300 trades.
- Replay over our recorded window agrees in sign with the paper run.
- Max drawdown < 15% from peak (hitting it = FAIL). Zero missed exits, zero unexplained position mismatches, downtime < 2%.
- Target: reach this within 1 month of the paper run starting. Too few trades = INCONCLUSIVE, not PASS.

## Decisions
See `docs/product/decisions.md` (2026-09-29 entries) and research in `docs/research/copytrade-v1-domain-research.md`.

## Constraints
- Budget: $0-50/month until proven. Hosting: PO's Windows PC (kept awake). Language: Python (async; latency is dominated by network). Must run on Windows.
- PO in Brazil. Future live wallet $100-500 USD.
- No real money in this epic. No exchange API keys needed in paper mode.

## Risk appetite
Low for real money; aggressive experimentation in paper.

## Out of scope (v1)
Real-money execution; Hyperliquid testnet; memecoins / on-chain spot; Binance and other CEX execution; WhatsApp; subscribers, payments, KYC; Telegram Mini App; ML-trained filter (data collected now, model later); cloud hosting; BRL conversion and tax exports (needed before real money).

## Kill criteria
Replay and paper show no positive edge after costs at adequate sample size; or Hyperliquid data access becomes unavailable or prohibited.

## Open questions
Discovery questions and PO answers: `docs/epics/copytrade-v1/questions.md`.
