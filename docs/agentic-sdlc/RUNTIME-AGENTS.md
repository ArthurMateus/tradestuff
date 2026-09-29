# Runtime agents: the ones that live inside your trading app

There are two different kinds of "agent" here. It's easy to mix them up.

- **Build-time agents** (`.claude/agents/`) build the software. They run while you develop.
- **Runtime components** run *inside* your app while it trades. They're **features**, and each one
  goes through the pipeline (`/brainstorm` → … → `/go-live`) like anything else.

Use this file as input to `/brainstorm`. It's a reference design, not a spec.

## Golden rule: keep LLMs off the hot path
The order path (signal → risk → order) must be deterministic and fast. LLMs run **beside** it, not
in front of it. They precompute context (regime, event risk, leader notes) into a cache that the hot
path reads in microseconds. If an LLM is ever inline (e.g. a trade "double-check"), it needs a hard
timeout and a deterministic fallback, and it may only **veto** (invariants F1–F3).

```
             ┌────────────── COLD PATH (seconds–hours) ──────────────┐
             │ Macro/Event Guard   Regime Detector   Leader Vetting  │
             │        │                  │                │         │
             │        └──────► context cache (Redis) ◄────┘         │
             └──────────────────────────┬────────────────────────────┘
                                        │ read-only, µs
HOT PATH:  leader fill ─► Signal Ingest ─► Consensus ─► Risk Gate ─► Execution ─► exchange
             (ms)                         (+AI veto, timeout)   (A1 chokepoint)
```

## Candidate components

| Component | Path | What it does | Key outputs | Invariants |
|-----------|------|--------------|-------------|------------|
| **Macro and Event Guard** | cold | Pulls the economic calendar and crypto events. Opens configurable blackout or reduced-size windows around high-impact releases | `blackout_active`, `size_multiplier` per symbol | A3, B1 |
| **Regime Detector** | cold | Classifies volatility and liquidity regime from realised vol, funding, OI and spread | `regime` ∈ {calm, normal, stressed} + evidence | B1, D1 |
| **Leader Vetting** | cold | Scores leaders from verified fills: sample size, drawdown, concentration, hold time, decay | `leader_score`, `eligible` | C1, D2 |
| **Independence Clustering** | cold | Detects leaders who copy each other or are highly correlated, and merges them into one vote | `cluster_id` per leader | C5 |
| **Signal Ingest** | hot | Normalises leader events from WS/on-chain, dedupes, stamps latency | `Signal` with timestamps | B1–B3, C4, C6 |
| **Consensus Engine** | hot | Waits for N independent eligible leaders on the same side within a window, weighted by score | `ConsensusSignal` | C5, D4 |
| **AI Veto** (optional) | hot, bounded | Short-timeout LLM check against the cached context. Can only block or annotate | `veto: bool`, `reason` | F1–F3 |
| **Risk Gate** | hot | The single chokepoint. Sizing by our budget, all limits, staleness, slippage guard, kill switch | approve/reject + reasons | A1–A4, A9, C2, C3 |
| **Execution** | hot | Idempotent submission, precision, lifecycle, reconciliation | fills, positions | A5–A8, B2–B4 |
| **Notifier** | cold | Telegram alerts for fills, rejects, breaches, disconnects, mismatches. Authenticated commands incl. kill switch | messages | A4, E3 |
| **Journal and Analytics** | cold | Append-only decision log, PnL after costs, latency percentiles, paper-vs-backtest divergence | reports, exports | B5, D6, E5 |

## Suggested build order (each one is its own epic)
1. Journal + Risk Gate + Kill Switch. **Safety first**: nothing else ships without them.
2. Execution hardening (idempotency, reconciliation, precision).
3. Leader Vetting + Independence Clustering (`/research` required).
4. Consensus Engine (`/research` required, pre-registered criteria).
5. Macro/Event Guard + Regime Detector.
6. AI Veto, only if the data shows it improves expectancy after latency cost.
