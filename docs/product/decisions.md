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
