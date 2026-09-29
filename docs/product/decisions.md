# Decision log (PO)

Format: `YYYY-MM-DD | decision | reason | epic`

2026-09-29 | Real-money live trading is OFF until the PO records a written go here. | Safety and regulatory exposure. | all
2026-09-29 | D1: Trader source = public Hyperliquid wallets; OKX public copy-trading as fallback; no Binance leaderboard scraping. | Only official, real-time, unfakeable public data; Binance lead-trader data went private in 2025 and scraping breaks its ToS. | copytrade-v1
2026-09-29 | D2: Execution venue = Hyperliquid (trade-only agent key when live); Binance spot possibly later. | Same venue as the traders minimizes copy slippage; Binance futures restricted for Brazilians (CVM 2020) and BCB PSAV deadline 2026-10-30. | copytrade-v1
2026-09-29 | D3: Leverage default 3x, ceiling 5x alts / 10x BTC-ETH; 40x removed; size from stop distance and risk caps, never from leader leverage. | At 40x liquidation is ~2.1% away and costs eat ~6% of margin per trade; leverage caps cut retail losses. | copytrade-v1
2026-09-29 | D4: Memecoins deferred to a later epic (alerts/paper only first). | Mostly exit liquidity for copiers; no exchange-side stops on-chain; good data costs ~$499/mo. | copytrade-v1
2026-09-29 | D5: Deterministic rules make the yes/no call; LLM only writes the explanation, no vote. | No credible evidence LLMs judge trade profitability; 4 of 6 LLMs lost money in Alpha Arena S1. | copytrade-v1
2026-09-29 | D6: Risk defaults: <=1% risk/trade, daily 2%, weekly 5%, 15% peak drawdown pauses until /resume. | Risk-manager recommendation. | copytrade-v1
2026-09-29 | D7: Auto-entry with guards (signal age <=5s, slippage <=0.3%/0.8%), never chase; stop ratchets, never widens. | Avoid chasing moved prices. | copytrade-v1
2026-09-29 | D8: Duplicate positions = one post, per-trader shares tracked separately. | PO wants merged posts; separate shares keep exits correct. | copytrade-v1
2026-09-29 | D9: Exits fully automatic incl. partials/adds; exchange-side SL/TP when live; /pause and PIN-protected /flatten. | PO requirement plus outage safety. | copytrade-v1
2026-09-29 | D10: Pause entries around FOMC (-30/+60 min) and CPI/PCE/NFP (-15/+30 min); halve size in extreme volatility. | Liquidation cascades around macro releases. | copytrade-v1
2026-09-29 | D11: Go-live gate by trade count and confidence interval (~300 trades, CI lower bound > 0), target within 1 month of the paper run. | Separate skill from luck; PO wants proof within a month. | copytrade-v1
2026-09-29 | D12: Paid phase needs a Brazilian lawyer opinion, CNPJ and accountant before launch; fallback is spot-only or signals-only. | Auto-trading futures for subscribers may be unlicensed portfolio management (CVM Res. 21). | phase 2
2026-09-29 | D13: Telegram (private chat now, subscriber channel later); not WhatsApp. | Editable messages, inline buttons, free API. | copytrade-v1
2026-09-29 | Budget $0-50/month; hosting on PO's Windows PC; Python. | Until proven. | copytrade-v1
2026-09-29 | Paper trading at real mainnet prices instead of Hyperliquid testnet. | Testnet prices and liquidity are not real, results would mislead. | copytrade-v1
2026-09-29 | Fully automatic trader selection, re-scored continuously (default 60 min), follow 5-10 (max 10), swap in better traders. | PO requirement. | copytrade-v1
2026-09-29 | Paper wallet $300; future live wallet $100-500. | Paper must match the real wallet incl. minimum order sizes. | copytrade-v1
2026-09-29 | Sizing mirrors the trader's position as a fraction of their account, capped by risk limits; partial exits mirror the trader's percentage. | PO requirement. | copytrade-v1
2026-09-29 | Exit authority: whichever of our SL/TP or the trader's exit happens first. | PO decision. | copytrade-v1
2026-09-29 | Build v1 fully refined before the paper run; the 1-month clock starts at the paper run. | PO decision. | copytrade-v1
2026-09-29 | Report in USD; BRL conversion and tax exports deferred to the real-money epic. | PO decision. | copytrade-v1
2026-09-29 | Research gate: PROCEED to spec, expecting month one may be INCONCLUSIVE. | Audit INCONCLUSIVE (no real data); the build is needed to gather evidence. | copytrade-v1
2026-09-29 | Fewer than 300 trades by day 30: extend up to 60 days with the same frozen config, one evaluation. | Feasibility estimate is 100-300 trades per month. | copytrade-v1
2026-09-29 | Paper risk per trade 0.5% (ceiling stays 1%). | Cuts false FAIL on drawdown for a real edge from 7-16% to <1%. | copytrade-v1
2026-09-29 | PASS also requires net USD P&L > 0 and beating a direction-matched random-time baseline; CI clustered by UTC day. | Mean R can be positive while losing dollars; beta in a trending month is not skill (BT-4, BT-7). | copytrade-v1
2026-09-29 | R = P&L / initial risk (gate); R on max committed risk also reported. | Adds make initial-risk R flattering. | copytrade-v1
2026-09-29 | Sample = first 300 opened trades, evaluated once after all have closed; max 2 paper runs; any config change mid-run restarts it and counts as a run; PO sees trades and P&L during the run. | Prevent optional stopping (BT-5, BT-14). | copytrade-v1
2026-09-29 | Mirrored partial exit below the $10 minimum: skip and log; if the remainder would fall below $10, close it all. | Exchange minimum order value. | copytrade-v1
2026-09-29 | Follow at most 9 wallets at steady state (1 WebSocket user slot reserved for swaps); 12-24h incremental candidate backfill before following. | Hyperliquid limits: 10 WS users, 1,200 REST weight per minute per IP. | copytrade-v1
2026-09-29 | Crypto perps only (allowed_dexes = core); exclude HIP-3 stock/commodity/FX perps from trading in v1, but record their data from day 1 for a later epic. | ~2x fees, oracle-lagged off-hours prices, few eligible traders, CVM securities exposure. | copytrade-v1
2026-09-29 | Record L2 books, mids, mark/oracle, funding, OI and hourly leaderboard snapshots from day 1. | No historical L2 via API; enables honest replay. | copytrade-v1
2026-09-29 | Event blackouts block new entries and adds only, never exits; minor releases ignored; trades around events count toward the sample. | Exits must never be blocked. | copytrade-v1
2026-09-29 | Hyperliquid access degraded or geo-blocked: alert and pause new entries. | BCB deadline 2026-10-30. | copytrade-v1
2026-09-29 | Funding charged hourly from real funding history and included in R; delisting settlements count as normal trades. | Honest costs. | copytrade-v1
2026-09-29 | No paid S3 historical data for now. | Budget. | copytrade-v1
2026-09-29 | PO home connection is fixed broadband (full REST budget); PO will run the fixed hl_sample.py once from their PC. | Replace synthetic priors with real numbers. | copytrade-v1
2026-09-29 | Paper wallet $300; live starts at >= $300 (never smaller than the paper-tested size). | Results at $300 do not transfer to $100 because of the $10 minimum. | copytrade-v1
2026-09-29 | PO acknowledged all 8 items in edge-hypothesis section 14 ("ok"). Items: (1) CI levels 96% run 1 / 99% run 2 (run-2 power ~3-9%); (2) most pessimistic of three CI methods; (3) at least 5 UTC-day clusters, else INCONCLUSIVE; (4) evaluation at the last close or 7 days after the 300th open, open trades marked; (5) "beating the baseline" = lower bound of the advantage > 0; (6) a code deploy ruled ABORTED consumes one of the 2 runs, and pause time counts toward downtime; (7) /flatten counts min(realised, shadow); (8) recording gaps can fail the baseline test via the 10% missing-window rule. | Keeps the family-wise false-PASS rate at 2.5% or less and closes optional-stopping routes (backtest audits r2 and r3). Supersedes the ~95% wording in 01-brief.md. | copytrade-v1
2026-09-29 | Research gate passed: backtest audit round 3 VALID (the pre-registration is sound; no edge is proven yet). | PO said proceed. | copytrade-v1
