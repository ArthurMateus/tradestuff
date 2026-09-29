# Domain research for copytrade-v1 (2026-09-29)

Condensed from four research agents (market-analyst, quant-researcher, risk-manager, trading-compliance). Not financial or legal advice. [U] = unverified.

## Trader sources (market-analyst)
| Source | Access | Verdict |
|---|---|---|
| Hyperliquid | Official public API: any wallet's fills/positions over WebSocket/REST; limits of 10 users per WS connection, 10 connections per IP; leaderboard via undocumented stats endpoint | **v1 primary** |
| OKX copy trading | Official public lead-trader position endpoints (REST polling) [U: redistribution ToS] | Fallback |
| Binance leaderboard | `getOtherPosition` moved private in 2025; scraping only, likely ToS breach; traders can hide positions | Excluded |
| Bybit / Bitget | No confirmed official public API | Excluded |
| Solana/EVM memecoin wallets | Helius gRPC ($499/mo), Birdeye APIs | Deferred |
| Telegram/X call channels | Scraping, no verifiable record | Excluded |

Recurring-winner heuristics: at least 90-180 days and 100-150 trades; profitable in most rolling windows; walk-forward ranking (rank on window N, keep only if still top tercile on N+1); best single trade under 25% of total PnL; median holding time at least 20x our copy delay; replay with our delay and costs ("copyability").

Brazil venues: CVM Ato Declaratório 17.961 (2020) barred Binance derivatives offering to Brazilians. BCB Resolutions 519-521 took effect 2026-02-02; unauthorized foreign providers must stop by **2026-10-30**. Hyperliquid's terms block the US, Ontario and sanctioned countries; Brazil is not listed [U: check before live].

Macro events: FOMC -30/+60 min, CPI/PCE/NFP -15/+30 min, PPI/GDP -5/+15 min; BTC fell after 7 of 8 FOMC meetings in 2025. Calendar: official Fed/BLS schedules (free); Finnhub or Trading Economics as paid fallback.

## Quant (quant-researcher)
- **Leverage at 40x:** liquidation ~2.1% adverse; a taker round trip = 4% of margin, slippage ~2%, funding ~1.2%/day. Heimer & Imas (RFS 2022): leverage caps cut high-leverage traders' losses by 40%. Apesteguia et al. (Mgmt Sci 2020): copy trading induces excess risk.
- **Luck control:** with N=5,000 zero-skill traders the best shows Sharpe ≈ √(2 ln N) ≈ 4.1 standard errors; use the Deflated Sharpe Ratio (Bailey & López de Prado 2014) and walk-forward ranking.
- **Eligibility gates (start values):** at least 180d and 150 trades, positive in 3 of the last 4 quarters, max DD ≤ 35%, profit factor ≥ 1.3 after costs, DSR probability ≥ 0.95, median hold ≥ 15 min, no asset > 50% of profit.
- **Blow-up detectors:**
  - more than 20% of adds are made while losing
  - size grows after losses
  - win rate > 85% while average loss > 3x average win
  - worst loss > 10x the median loss
  - unrealized drawdown far larger than realized drawdown
- **Copy delay:** edge per trade must be at least 3x (fees + median slippage). Scalpers are uncopyable at 1-3s.
- **Stops:** Kaminski & Lo (2014) find stops add value only under momentum. Default stop is the tighter of structure and 2×ATR(14); take half at 2R and trail the rest at 2×ATR after +1R.
- **AI filter:** in Alpha Arena S1 (Oct-Nov 2025), 4 of 6 LLMs lost money. Use rules, then a learned model trained on logged outcomes. Detecting a 0.2R filter lift needs about 880 trades per arm.
- **Forward test:** 300 trades gives a 95% CI of about ±0.17R (SD 1.5R). Paper fills are optimistic, so follow with a small live stage of ≥100 trades.

## Risk (risk-manager)
- **Sizing and leverage:** size = equity × risk% / stop%. Leverage is the smallest value that keeps liquidation at least 3x the stop distance away.
- **Exposure limits:** daily 2%, weekly 5%, drawdown 15% (ceilings 5/10/25%); 5-10 concurrent positions; per-symbol risk 1.5%; BTC-beta bucket 3%; per-leader 30%. Auto-pause a leader at a 10% drawdown or 5 consecutive losses.
- **Entry guards:** signal ≤ 5s old, price ≤ 2s old, spread ≤ 0.1%/0.3%, order ≤ 1% of depth within 0.5% of mid. Client order id = hash(leader, signal, user). Re-check that R:R ≥ 1.5 at our fill.
- **Stop policy:** stop ratchets and never widens. When live, place stops exchange-side and reduce-only on mark price. Flatten if the stop can't be placed within 2s.
- **Leader feed loss:** freeze entries after 30s with no heartbeat. On reconnect, reconcile against the leader. Tighten stops to breakeven after 5 minutes.
- **Kill switch:** runs as an independent process. /flatten needs a PIN. Global halt is admin only.
- **Security when live:** trade-only keys, no withdrawal, IP-locked, envelope-encrypted. Never collect keys in chat.

## Compliance (trading-compliance)
- **Phase 1 (personal):** lawful. Tax: IN RFB 2291/2025 (DeCripto) requires monthly reporting when operations exceed R$35k. Law 14.754/2023 taxes offshore gains at 15%/year [U: treatment of futures and DeFi]. MP 1.303 lapsed on 2025-10-08.
- **Phase 2 (paid):**
  - Auto-executing crypto derivatives for subscribers ≈ discretionary management (CVM Res. 21, possibly a crime under Law 6.385 art. 27-E).
  - Paid futures signals ≈ consulting or analysis (CVM Res. 19/20).
  - Spot execution for third parties may be PSAV activity (Law 14.478).
  - CDC/CONAR ban superlatives and cherry-picked win rates.
  - LGPD applies to named traders, so pseudonymize by default.
  - AML is handled via a licensed payment processor.
- **Questions for counsel:** listed in the agent report; see the D12 gate in `docs/product/decisions.md`.

## Key sources
- [Hyperliquid rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)
- [Binance leaderboard endpoint made private](https://github.com/bukowa/binance-leaderboard/issues/2)
- [BCB PSAV rules](https://www.mattosfilho.com.br/unico/normas-regulamentacao-ativos-virtuais/)
- [DeCripto](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/declaracoes-e-demonstrativos/criptoativos/decripto)
- [CVM Res. 19](https://conteudo.cvm.gov.br/legislacao/resolucoes/resol019.html)
- [Heimer & Imas](https://www.ssrn.com/abstract=3300456)
- [Apesteguia et al.](https://dl.acm.org/doi/abs/10.1287/mnsc.2019.3508)
- [Solidus Labs on pump.fun](https://www.coindesk.com/business/2025/05/07/98-of-tokens-on-pump-fun-have-been-rug-pulls-or-an-act-of-fraud-new-report-says)
- [Alpha Arena S1](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/)
- [Binance futures fees](https://www.binance.com/en/fee/futureFee)
- [Finnhub calendar](https://finnhub.io/docs/api/economic-calendar)
