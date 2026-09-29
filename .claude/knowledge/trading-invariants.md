# Trading Invariants

These apply to every project that moves money. A violation is **BLOCKING** for every reviewer,
not just reviewer-risk. The PM carries them into the spec as implicit acceptance criteria. The
test designer writes tests for the ones a feature touches.

## A. Execution safety (money path)

| # | Invariant |
|---|-----------|
| A1 | **Single chokepoint.** Every order goes through one risk gate. No code path reaches the exchange client without it. |
| A2 | **Fail closed.** Missing or invalid config, unknown risk state, stale data, a failed risk check or an exception inside the gate means no order. |
| A3 | **Hard limits are config, not code:** max position notional, max leverage, max open positions, max per-symbol exposure, max daily loss, max orders per minute. |
| A4 | **Kill switch.** One command (CLI and Telegram) halts new orders and optionally flattens. It persists across restarts and has a test. |
| A5 | **Idempotency.** Every order carries a deterministic client order ID derived from the signal. Retries and restarts never double-submit. |
| A6 | **Money is Decimal.** No floats for price, quantity, notional, PnL or fees. Round to the exchange's tick size and step size, and respect min notional. |
| A7 | **Exchange is the source of truth.** Reconcile positions and open orders on startup and periodically. Local state that disagrees gets corrected and alerted, never trusted. |
| A8 | **Partial fills, rejects, cancels, liquidations and ADL** are each handled explicitly, never collapsed into "error". |
| A9 | **Units are explicit** in names or types: qty vs notional, bps vs %, leverage vs margin, long vs short sign. |
| A10 | **Mode is explicit:** `paper` / `testnet` / `live`. The default is `paper`. `live` needs an explicit flag **and** a passed /go-live gate. Tests never touch mainnet. |

## B. Data and timing

| # | Invariant |
|---|-----------|
| B1 | **Staleness guard.** Never act on a price or signal older than its configured TTL. |
| B2 | Timestamps are UTC and carry their source (exchange time vs local time). Clock skew is handled (e.g. Binance `recvWindow`, server-time sync). |
| B3 | WebSockets have heartbeats, reconnect with jittered backoff, and detect gaps. After a gap, resync from a REST snapshot before acting. |
| B4 | Rate limits are budgeted per endpoint. 429/418 (or equivalent) trigger backoff, never retry storms. |
| B5 | Every order decision is audit-logged, append-only: signal, inputs, each risk check result, price used, latency breakdown, outcome. |

## C. Copy trading and consensus

| # | Invariant |
|---|-----------|
| C1 | Leaders are scored on **verified fills** (e.g. on-chain), never on self-reported ROI. There's a minimum sample size (trades and days) before a score counts. |
| C2 | Size by **our** risk budget, never by the leader's size. |
| C3 | **Slippage guard.** Skip the copy if price has moved more than the configured threshold since the leader's fill. |
| C4 | Detect closes, reductions and flips from the leader and mirror them. Never leave an orphaned copy position. |
| C5 | Consensus signals count **independent** leaders only. Wallets that copy each other or are highly correlated collapse into one vote. |
| C6 | Signal-to-order latency is measured end to end (leader fill → detection → decision → our ack) and exported as a metric. |

## D. Research validity (any claim that something is profitable)

| # | Invariant |
|---|-----------|
| D1 | No lookahead. Data is point-in-time. Features only use information available at decision time. |
| D2 | No survivorship bias: dead or delisted symbols and leaders who blew up stay in the dataset. |
| D3 | Fees, funding, spread and realistic slippage are always included. |
| D4 | Success criteria are written **before** the results are seen. The number of variants tried gets recorded. |
| D5 | Out-of-sample or walk-forward validation, plus a comparison against naive baselines (random entry, buy-and-hold, "follow top N by raw ROI"). |
| D6 | Paper trading must confirm backtest behaviour before live. Divergence beyond tolerance is a failure. |

## E. Secrets, access and compliance

| # | Invariant |
|---|-----------|
| E1 | Exchange API keys are trade-only: **withdrawals disabled**, IP-whitelisted where the venue supports it. |
| E2 | Keys are never logged, never committed, never baked into images. They're loaded from env or a secret store at runtime. |
| E3 | Remote control surfaces (Telegram bot, HTTP API) authenticate the caller, e.g. an allow-list of chat IDs. Unauthorized commands are rejected and logged. |
| E4 | Postgres, Redis and admin ports are not exposed publicly. Containers run as non-root. |
| E5 | Every fill is exportable (for tax records). |
| E6 | If the product is ever offered to third parties (managing or copying for others, or selling signals), stop and flag it for legal review before building. That's regulated activity in most jurisdictions, including Brazil. |

## F. AI in the loop

| # | Invariant |
|---|-----------|
| F1 | LLM calls never block the order hot path without a hard timeout **and** a deterministic fallback. |
| F2 | An LLM can veto or annotate. It can never raise size or bypass a limit. |
| F3 | LLM inputs and outputs for trade decisions are logged (B5) so decisions can be replayed. |
