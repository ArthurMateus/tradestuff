# Brief: Copy-trade signal bot v1 (Hyperliquid + Telegram, paper trading)
Slug: copytrade-v1 | Status: draft | Date: 2026-09-29

## Problem and outcome
The PO wants a bot that continuously finds proven, recurring profitable day traders, filters their moves, and copies them automatically with controlled risk, reporting everything in Telegram. v1 must PROVE (or disprove) that copying works after real costs, within ~1 month, using paper trading at real market prices.

## Who benefits and how
- Phase 1 (this epic): the PO alone, private Telegram chat, paper trading only.
- Phase 2 (later epics): paying subscribers via a Telegram channel. Gated by legal opinion, CNPJ and accountant (see decisions).

## Scope of v1
1. **Trader discovery and scoring (fully automatic).** Source: public Hyperliquid wallets (official API; leaderboard as candidate list). Fallback source: OKX public copy-trading endpoints. Every N minutes (config) re-score candidates; follow the top 5-10 (max 10). Score is data-driven config: risk-adjusted return (Sortino/Calmar), win rate, P&L ratio, trade count, consistency across rolling windows, max drawdown, copyability after our delay and costs, deflated-Sharpe luck correction. Eligibility gates and blow-up detectors (martingale/grid/averaging-down) per quant research. Hysteresis so traders are not added/dropped on noise. A dropped trader's open copied positions keep mirroring that trader's exits until closed.
2. **Signal detection.** Real-time fills/positions of followed traders via Hyperliquid WebSocket. Detect opens, adds, partial reductions, full closes.
3. **Filter (yes/no).** Deterministic, measurable rules decide (trader score, trend, volatility regime, liquidity, spread, funding, economic-event windows, signal age, slippage vs leader). An LLM (cheap cloud model; Ollama as offline fallback) only writes the "why" text and news summary; it has no vote. Every signal and verdict is logged (taken and rejected) so the filter's value can be measured.
4. **Paper execution at real prices.** Simulated fills against live Hyperliquid mainnet order book with fees, spread, slippage, copy delay, funding, partial fills, and liquidation modeled. Auto-entry (no confirmation). Mirrors adds, partial and full exits proportionally. Every position has a stop-loss and take-profit; stop ratchets to lock profit, never widens.
5. **Duplicate handling.** Same symbol + direction from multiple traders = one Telegram post listing all traders; each trader's share tracked separately so each trader's exits close only their share.
6. **Risk controls** (config with defaults and hard ceilings): 0.5% risk/trade (1% max); leverage default 3x, max 5x alts / 10x BTC-ETH, sized from stop distance; daily loss 2%, weekly 5%, 15% peak drawdown -> pause until /resume; max 10 concurrent positions; BTC-correlated exposure cap; per-trader allocation cap; skip signals older than 5s or with slippage beyond 0.3% majors / 0.8% alts; never chase.
7. **Economic-event awareness.** Pause new entries around FOMC (-30/+60 min) and CPI/PCE/NFP (-15/+30 min); halve size in extreme volatility. Free official Fed/BLS schedules.
8. **Telegram bot (private chat).** Color-coded (emoji) posts: symbol, direction, entry, SL, TP, size, leverage, trader name(s), their win rate and P&L, why. Live-edited as position changes. Commands: /status, /pnl, /traders, /pause, /resume, /flatten (PIN). Daily and weekly performance report. Designed to become a subscriber channel later.
9. **Ledger and reporting.** Append-only record of every signal, decision, simulated order, fill, fee, funding; UTC and BRT timestamps, BRL value. Performance computed over ALL signals, net of costs, reproducible.
10. **Backtest / replay.** Replay followed traders' historical Hyperliquid fills through the same engine with point-in-time trader selection, our delay and cost model, to get evidence on day 1 before the paper month.

## Success metrics (go-live gate for real money)
- Paper results net of all costs, lower bound of 95% CI of mean trade R > 0 (trade count, not calendar, is the gate; target >= ~300 trades).
- Backtest/replay with point-in-time selection agrees in sign with paper results.
- Max drawdown < 15% from peak. Zero missed exits, zero unexplained position mismatches, no crash left unrecovered.
- Target: reach this within 1 month of deployment. If the trade count is too low in 1 month, the verdict is INCONCLUSIVE, not PASS.

## Decisions made (with reasons)
See `docs/product/decisions.md` (D1-D13 plus round 3). Highlights: Hyperliquid as source (only official, real-time, unfakeable public data; Binance leader data is closed and Binance futures is restricted for Brazil); paper trading instead of testnet (testnet prices are not real); LLM has no vote (no evidence LLMs judge trades well); 40x removed (liquidation ~2% away); memecoins deferred (mostly exit liquidity for copiers, needs ~$499/mo data).

## Constraints
- Budget: $0-50/month until proven. Hosting: PO's Windows PC (must stay awake; bot reconciles on startup). Language: Python (latency dominated by network; async is sufficient).
- PO in Brazil. Future live wallet $100-500 (must respect Hyperliquid minimum order size).
- No real money in this epic.

## Risk appetite
Low for real money; aggressive on experimentation in paper.

## Out of scope (v1)
Real-money execution; memecoins / on-chain spot; Binance and other CEX execution; WhatsApp; subscribers, payments, KYC; Telegram Mini App; ML-trained filter (data collected now, model later); cloud hosting.

## Kill criteria
Paper + replay show no positive edge after costs at adequate sample size; or Hyperliquid data access becomes unavailable/prohibited.

## Open questions (to discovery)
Pending discovery pass.

## Links
Vision: `docs/product/vision.md`. Research summaries relayed in brainstorm (market-analyst, quant-researcher, risk-manager, trading-compliance) to be saved under `docs/research/` before `/epic`.
