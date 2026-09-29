# Product vision

**Goal:** the best copy-trading app on the market. It continuously searches for the most profitable traders and copies them instantly, with controlled risk.

**Focus:** day trading and copy trading. Assets and venues: TBD in brainstorm.

## What "best" must mean (to be turned into numbers in brainstorm)
- Finds traders whose edge is statistically real, not lucky, and keeps re-evaluating them.
- Copies with minimal latency and slippage, sized to each follower's account and risk.
- Protects followers: hard limits, automatic pausing, a kill switch, transparent risk.
- Transparent and honest: no guaranteed-return claims.

## Candidate epics (order and scope to be decided with the PO)
1. Foundations: project skeleton, config system, broker/exchange abstraction, audit log, paper-trading broker.
2. Market and leader data ingestion (point-in-time storage).
3. Trader scoring and ranking engine (quant-researcher protocol).
4. Copy engine: signal -> sizing -> risk gate -> idempotent execution -> reconciliation.
5. Risk controls and kill switches.
6. Backtest / copy-simulation framework.
7. Web app: onboarding, connect broker, choose/allocate, dashboards.
8. Compliance: KYC, disclosures, terms, audit exports.
9. Market regime and economic-event awareness.
10. Ops: monitoring, alerting, deployment.

## Non-negotiables
See `CLAUDE.md` and `docs/sdlc/implicit-requirements.md`. Real-money trading needs the PO's written go.
