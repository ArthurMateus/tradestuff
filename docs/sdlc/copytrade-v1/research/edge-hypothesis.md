# Edge hypothesis: copytrade-v1

Date: 2026-09-29. Author: quant-researcher. Status: **PRE-REGISTRATION**. No result on real data exists yet.

Inputs:
- `01-brief.md`, `02-discovery.md`, `03-answers.md`
- `docs/product/decisions.md`
- `research/brainstorm-domain-research.md`
- `research/market-context.md` (read after it landed at 16:12 UTC)

Labels used below:
- **[PO]** a fixed PO decision, reproduced and not changed
- **[QR]** a research choice made here, which the PO or PM may override
- **[EXPL]** exploratory and synthetic. It is not evidence and has not yet been reviewed by the backtest-auditor.

## 0. Base rates and prior

- **Most Hyperliquid traders lose money.** A 30-day, 10,000-wallet on-chain sample (Nov 2024) found 73.8% of wallets losing, 16.5% profitable and 27.2% losing more than 85% of capital. That is a third-party analysis of public data, so treat it as a base rate, not a precise number. Another sample of 1,000 wallets found 16.6% profitable.
- **Leaderboards select on luck.** About 15,000 leaderboard rows (market-context 2.1) means the best of 15,000 zero-skill wallets shows a t-statistic of about 3.9 by chance (section 5, E).
- **Copy trading adds its own costs.** Following adds taker fees on both legs, the spread, delay slippage, and a payoff change from our own stops. Apesteguia et al. (2020) show copy trading induces excess risk-taking. In Alpha Arena S1, 4 of 6 LLM traders lost money.
- **Prior (QR):** P(mean copy R > 0 after all costs) is about 0.25. Conditional on being positive, the most likely true mean is below 0.10R. Scalpers and market makers are uncopyable at 1-5 s delay. Whatever edge exists should come from multi-hour discretionary or informed traders.

**Default belief: no edge.** Everything below is designed to find that out cheaply and honestly.

---

## 1. Hypothesis

**H1 (primary; the one the go-live gate tests).** Automatically copying the 5-10 Hyperliquid wallets ranked highest by the scoring model in section 10 into a $300 paper wallet yields a positive mean R per trade over the first 300 closed taken trades, net of all costs. The copy uses our deterministic filter, mirrored fractional sizing capped by risk limits, and first-exit-wins exits, and costs include taker fees, the spread and book impact at our decision time plus the configured ack delay, and hourly funding. The 95% cluster-robust CI lower bound must be above 0, with peak-to-trough drawdown below 15%.

**H2 (selection adds information).** Over the same window, the mean R of H1 exceeds both of these:
- (a) the 95th percentile of the random-entry baseline (matched coin, frequency, holding time, sizing, stops and costs)
- (b) the mean R of copying the top 8 by raw 30-day ROI through the same engine

**H3 (filter adds value, exploratory only).** Taken signals have a higher mean R than rejected signals' shadow outcomes. The design cannot answer this in v1: detecting a 0.2R lift needs about 880 trades per arm. It is reported, never gating.

Each of these can be falsified:
- H1 fails at N=300 if the CI upper bound is ≤ 0, or if drawdown reaches 15%.
- H2 fails if our mean R does not exceed those baselines.

## 2. Mechanism: why an edge could exist, and who is on the other side

**Why it could exist:**
1. **Persistent skill in a small minority.** Some traders have skill at multi-hour horizons: information processing, flow reading, funding and basis dislocations. Their edge accrues over minutes to hours, so a 1-5 s copy delay costs a small fraction of it. The eligibility gates keep only these (median hold ≥ 15 min).
2. **Informed flow.** Some large Hyperliquid wallets have traded ahead of news. Copying public on-chain fills is legal. Whether such edges persist is unknown.
3. **Transparency.** Hyperliquid publishes every wallet's fills in real time, so the edge is observable without trusting self-reported ROI (C1).

**Who is on the other side:**
- **Of the leader's trade:** market makers (including HLP) and less informed takers.
- **Of our copy:** market makers who have already seen the leader's flow, and other copy bots racing us for the same liquidity. If crowding matters, it shows up as adverse drift in the seconds after the leader's fill (the decay metric, section 4). At $300 our own book impact is negligible, but the crowd's is not.

**Why it probably does not exist, or does not transfer to us:**
- **Luck.** Thousands of wallets means impressive track records happen by chance.
- **Execution edges are uncopyable.** Maker rebates, queue position and HFT profits do not survive a copy.
- **Our exits change the payoff.** A leader who averages down and holds through a 3×ATR drawdown wins where our 2×ATR stop took −1R. The leader's historical P&L therefore does not predict our copy's R. The scoring model scores the copy-replay R, not the leader's P&L (section 10).
- **Sizing distortion.** Mirrored sizing plus the $10 minimum silently drops small, early-tranche and partial orders.
- **Regime dependence.** A 30-day window is a single regime.

Mechanism strength: weak to moderate. The prior in section 0 stands.

## 3. Data

| Need | Source | Fields | Granularity | History | Point-in-time? | Gaps / notes |
|---|---|---|---|---|---|---|
| Candidate list | `GET stats-data.hyperliquid.xyz/Mainnet/leaderboard` (undocumented) | `ethAddress`, `accountValue`, `windowPerformances` (day/week/month/allTime: `pnl`, `roi`, `vlm`) | snapshot | none: current state only | **Only from our own hourly snapshots, from day 1** | Survivorship: wallets that blew up drop off. We store every snapshot and never delete a wallet we have seen (D2). |
| Leader fills (scoring) | `POST /info userFillsByTime` (`aggregateByTime: true`) | `coin`, `px`, `sz`, `side`, `time`, `startPosition`, `dir`, `closedPnl`, `fee`, `crossed`, `oid`, `tid`, `hash` | per fill, ms | **Latest 10,000 fills per wallet**; ≤ 2,000 per call | Yes: fills are immutable; score at t uses fills with `time ≤ t` only | History is bounded by fill count. Busy wallets cover only days, which gate G3 handles. TWAP slice fills are a separate stream, not covered. |
| Leader fills (live) | WS `userFills` | same | per fill | live | Yes; exchange timestamp + local receive timestamp (B2) | Max 10 unique users per IP (market-context 2.3) |
| Leader equity and P&L curve | `POST /info portfolio` | `accountValueHistory`, `pnlHistory` per `perpDay`/`perpWeek`/`perpMonth`/`perpAllTime` | allTime about 93 points (coarse); month finer | account lifetime | **No**: fetched now, covers the past. Point-in-time only for values we snapshot ourselves. | `accountValue` jumps with deposits. Returns use `pnlHistory` (deposit-neutral) divided by the prior account value. |
| Leader funding | `POST /info userFunding` | per-hour funding paid | hourly | bounded | yes | Adds weight per 20 items |
| Current positions and account value | `clearinghouseState` (weight 2) | positions, `marginSummary.accountValue` | snapshot | none | Only when we snapshot it | Needed for mirrored sizing at signal time |
| Prices for the copy replay | `candleSnapshot` 1h (about 208 days) and 1m (about 3.5 days) | OHLCV | 1h / 1m | 5,000 candles | yes | 1h bars are coarse for stop checks. On an ambiguous bar, assume the stop hit first (conservative). |
| Books, mids, trades (paper fills, decay) | WS `l2Book`, `allMids`, `trades`; REST `l2Book` | levels, mid, prints | tick | **none historically via API** | Only what we record | **Record from day 1** for every coin followed wallets trade. S3 `hyperliquid-archive` is requester-pays and needs AWS credentials, which are not used here. |
| Funding rates, OI, mark/oracle | `metaAndAssetCtxs`, `fundingHistory` | `funding`, `openInterest`, `markPx`, `oraclePx` | hourly / snapshot | bounded | Only what we record | Paper funding accrues hourly |
| Exchange rules | `meta` | `szDecimals`, `maxLeverage` | static | now | Snapshot at startup | $10 minimum order value; reduce-only full close is exempt [T] |
| Macro calendar | Fed, BLS, BEA data file | event, ET time | event | quarterly | yes | Times anchored to America/New_York |

**Survivorship treatment (D2):**
1. The go-live evidence uses only our own point-in-time data: leaderboard snapshots, scores, decisions, books and paper fills recorded live.
2. Any replay before our recording started is labelled "indicative only, survivorship-biased" and never counts as evidence.
3. A trader who is dropped, blows up or vanishes from the leaderboard stays in the dataset, and their copied trades stay in the stats.
4. Delisted coins are force-settled at the exchange price and included.

**Look-ahead (D1):**
- The score at cycle t uses fills with `time ≤ t` and the portfolio or clearinghouse snapshot fetched at or before t.
- Every cycle's inputs, metrics, score, rank and decision are persisted, so replays read the stored snapshot rather than refetching.
- ATR for a stop uses candles closed before entry.
- The filter uses only data older than the decision timestamp.

**Known gaps:**
- There is no historical order book, so the replay's slippage is modelled.
- The 10,000-fill cap limits history.
- The coarse 93-point allTime equity curve makes the hidden-drawdown detector approximate.
- Brazil-to-Tokyo latency has not been measured.
- The leaderboard endpoint is undocumented and can break.
- **The Hyperliquid API was not reachable from this research environment (egress 403), so no real sample was pulled.**

## 4. Metrics

All metrics come from the append-only ledger. They are net of taker fees, spread and book impact, delay, and hourly funding, and cover every taken trade, including losers, reconstructed trades and delisting force-settles.

| Metric | Definition |
|---|---|
| **R per trade [PO]** | `net_pnl_usd / initial_risk_usd`, where `initial_risk_usd = qty_at_entry × |entry_fill_px − initial_stop_px|` + estimated exit fee. One trade is one trader share, from open to fully closed. |
| R_maxrisk (reported) [QR] | `net_pnl_usd / max_committed_risk_usd` over the trade's life, counting risk added by adds. See concern C4. |
| Expectancy | mean R, and mean USD P&L per trade |
| Risk-weighted mean R (reported) [QR] | `Σ net_pnl_usd / Σ initial_risk_usd`. Equals total P&L in R units. See concern C3. |
| Win rate and payoff ratio | share of trades with R > 0; `mean(R | R>0) / |mean(R | R≤0)|`. Always reported together. |
| Max drawdown | peak-to-trough of **marked-to-market** paper equity (mark every 60 s), as a % of peak |
| Trade count | closed taken trades. Also counted separately: signals seen, rejected by reason, unexecutable (below $10), and conflict-skipped. |
| Exposure time | fraction of wall-clock time with ≥ 1 open position; time-average of open risk as % of equity |
| Turnover | Σ traded notional / mean equity, per day |
| Exit-reason mix | our SL, our TP, trader close, trader reduce to zero, force-settle, reconstructed |
| Mirror fidelity | share of leader adds and partials we could not mirror (below $10, risk cap, stop-widening skip) |
| **Signal-to-fill decay** | `decay(Δ) = mean over signals of s × (mid(t_leader + Δ) − px_leader) / px_leader`, in bps, where s = +1 for long and −1 for short, Δ ∈ {0.25, 0.5, 1, 2, 3, 5, 10, 30, 60, 300} s, and mids come from our recorded WS stream. **Edge lost per second** = OLS slope of decay on Δ over 0-5 s (bps/s), also expressed as a % of the mean leader gross round-trip move. Covers taken and rejected signals. |
| Latency breakdown (C6) | leader fill (exchange ts) → WS receive → decision → simulated ack. p50/p95/p99 per stage, clock-offset corrected. |
| Shadow mean R | mean R of rejected signals, simulated with the same exit rules (H3, reported only) |

## 5. Pre-registered success criteria (D4)

Written 2026-09-29 before any result. Changing any number after the paper run starts voids the run.

### 5.1 Go-live gate (the PO's criteria, pinned to exact numbers)

| ID | Criterion | Threshold |
|---|---|---|
| P1 [PO] | Sample size | **N = 300** closed taken trades. "~300" is pinned to exactly 300 [QR]. |
| P2 [PO + QR method] | Mean R 95% CI lower bound | **> 0.** Two-sided 95% CI, computed as the lower (more conservative) of (a) the t-interval and (b) a cluster bootstrap. For (b), a cluster is all trader shares of one merged position (same symbol and direction, overlapping in time), B = 10,000, percentile, fixed seed stored in the ledger. |
| P3 [PO] | Max drawdown (mark-to-market) | **< 15%** at every point of the run. Touching 15% is an immediate FAIL. |
| P4 [PO] | Missed exits | **0** |
| P5 [PO] | Downtime | **< 2%** of wall-clock time in the run |
| P6 [PO] | Replay over our recorded window vs paper | Same sign of mean R |
| P7 [QR] | **Single look** | The PASS, FAIL or INCONCLUSIVE verdict is computed once, on the first 300 closed trades. Earlier trades are not "peeked" into a verdict. Running statistics can be displayed but carry the label "interim, not a verdict". See concern C2. |

**Verdict mapping at N = 300:**
- PASS if P2-P6 all hold.
- FAIL if P3 or P4 is breached at any time, or the CI upper bound is ≤ 0.
- INCONCLUSIVE otherwise, including fewer than 300 trades at the calendar cap.

### 5.2 Secondary criteria (reported; gating only if the PO approves concerns C3 and C4)

| ID | Criterion | Threshold |
|---|---|---|
| S1 | Net USD P&L over the 300 trades | > 0 |
| S2 | Risk-weighted mean R | > 0 |
| S3 | H2(a): mean R vs the random-entry baseline | above the baseline's 95th percentile (1,000 replications) |
| S4 | H2(b): mean R vs the top-8-by-raw-ROI baseline | greater |
| S5 | Payoff check | Not both: win rate > 70% and payoff ratio < 0.5. That combination is a hidden short-volatility profile. |

### 5.3 Variant budget (D4)

- **Paper run:** exactly **1** frozen configuration (V0, or the variant chosen in the pre-paper replay).
- **Pre-paper replay:** at most **8** variants, all declared here, and the count is reported with any result:

| ID | Variant |
|---|---|
| V0 | Defaults from section 9 |
| V1 | All filters off (the raw copy of the selected traders) |
| V2 | Equal score weights |
| V3 | Stop 1.5×ATR |
| V4 | Stop 3×ATR |
| V5 | No TP (exit on our SL or the trader's exit only) |
| V6 | Join rank 5 / drop rank 10 |
| V7 | Minimum median hold 60 min |

**Rule:** V0 is kept unless another variant beats it by more than one replay CI half-width. Otherwise the selection is noise.

**Sensitivity runs:** costs ×1.5 and ×2, and delay of 1, 3 and 5 s. These run on the chosen variant only. They are robustness checks and do not count as variants.

## 6. Validation protocol (D5)

**Stages, in order:**
1. **Indicative replay.** Run before our own recording exists, over historical fills of today's candidates. It is survivorship-biased, labelled indicative only, and used for kill checks only (K1), never as evidence of an edge.
2. **Point-in-time replay.** Covers the window from our day-1 snapshots through the start of the paper run. It uses the same engine, the stored snapshots and recorded books where available. This is the pre-paper out-of-sample test.
3. **Paper run.** A forward, true out-of-sample test with a frozen configuration.
4. **Walk-forward inside replays.** The score at cycle t is computed from data ≤ t only, and trades after t are the out-of-sample fold. There is no in-sample fit: weights and gates are priors, not fitted. The only fitting is the variant choice in 5.3.

**Baselines.** Every baseline runs through the same engine, risk limits, cost model and window.

| ID | Baseline | Construction |
|---|---|---|
| B0 | **Random entry at matched frequency** | For each taken trade: the same coin, a uniformly random entry time within the same UTC week, a random direction, the same holding time (capped by our SL/TP), and the same sizing and stop rules. 1,000 replications gives a distribution of mean R. |
| B0b | Random direction at the same time | Same coin and entry time as the real trade, direction flipped by a coin toss. Tests whether direction carries information beyond timing. |
| B1 | **Top N by raw ROI** | Each hour, follow the top 8 of our leaderboard snapshot by 30-day `roi` (accountValue ≥ $10k), with no gates and no filter. |
| B2 | **Buy-and-hold BTC** | $300 in BTC perp at 1× from the run start, funding included. Compare USD return and max drawdown. Also a volatility-matched version scaled to our realised volatility. |
| B3 | Unfiltered copy of our selected traders | This is V1 and the shadow ledger. It isolates what the filter contributes. |
| B4 | The leaders' own P&L over the window | An upper bound. The gap between B4 and H1 is the cost of copying. |

**Cost model:**
- **Fees:** taker 0.045% per side on every paper fill, including SL and TP, which trigger on mark price and fill as market orders. No maker fills or rebates are assumed. HIP-3 markets are excluded, or charged 2× if the PO includes them.
- **Spread and impact (paper):** the fill walks the live L2 book captured at the decision time plus `paper_ack_delay_ms` (default 1,000 ms, per the median order-to-fill of about 884 ms from Tokyo in market-context 2.4).
- **Spread and impact (replay):** each coin's median half-spread from our recordings × 1.5. The fallback when unrecorded is 2 bps for majors and 8 bps for alts, per side.
- **Delay slippage (replay):** our measured `decay(Δ)` at the p95 detection latency. The fallback is 5 bps for majors and 15 bps for alts.
- **Stops:** fill at the book at trigger + ack delay, with no guaranteed stop price (gap-through is modelled).
- **Funding:** accrued hourly from actual rates.
- **Liquidation:** isolated positions use the mark-price and maintenance-margin model.

## 7. Kill criteria (stop, don't build further or don't go live)

| ID | Trigger | Action |
|---|---|---|
| K1 | Indicative or point-in-time replay with ≥ 100 trades: mean R CI upper bound < 0 | Stop before paper (this is the PO's kill criterion) |
| K2 | Point-in-time replay with ≥ 150 trades: point estimate ≤ 0 | Stop and review with the PO before paper |
| K3 | Paper at N = 300: CI upper bound ≤ 0 | FAIL. Recommend kill or redesign, not re-run. |
| K4 | Paper at N = 300: INCONCLUSIVE with point estimate ≤ 0 | Recommend kill or redesign rather than extension |
| K5 | Drawdown ≥ 15% at any time | FAIL [PO] |
| K6 | Decay: median adverse drift at our p50 latency ≥ 50% of the median leader gross round-trip move | Uncopyable: redesign |
| K7 | In the 24h dry run plus the first week, fewer than 5 eligible traders on ≥ 50% of scoring cycles | The premise fails. Redesign the gates as a logged variant **before** a new run, never mid-run. |
| K8 | > 50% of filter-passing signals unexecutable at $300 (below $10 after caps) | The $300 mirror model is invalid: PO decision on sizing |
| K9 | S3 and S4 both fail while P2 passes | Positive result but no evidence that selection adds value (beta or luck). Do not go live without PO review. |
| K10 | Hyperliquid data access unavailable or prohibited (including a Brazil geo-block around 2026-10-30) | Stop [PO] |

## 8. Paper-trading plan (D6)

- **Preconditions:**
  - a 24h dry run with no crash
  - a 1-day latency measurement from the PO's PC
  - at least 1 week of recorded books and leaderboard snapshots, which feeds the point-in-time replay
  - K1 and K2 not triggered
  - the configuration frozen and its hash written to the ledger
- **Duration:** until 300 closed taken trades, with a calendar cap of 30 days [PO]. If N < 300 at 30 days, the verdict is INCONCLUSIVE. Extending to 60 days with the same frozen config and the same single look at N = 300 needs PO approval (question Q5).
- **Minimum trades:** 300 for a verdict. Below 100 at day 30, report "infeasible at this configuration" (feeds K7 and K8).
- **Frozen config:** any change to scoring, filter, sizing, exits or risk parameters restarts the trade count as a new run. Bug fixes are logged; trades affected by a bug stay in the stats, and the backtest-auditor rules on them.
- **Tolerated divergence**, with the replay run over the paper window through the same engine:

| Check | Tolerance |
|---|---|
| Take/skip decision agreement per signal | ≥ 90% |
| Per-trade R, paper vs replay, on matched trades | median absolute difference ≤ 0.05R; mean difference ≤ 0.10R |
| Sign of mean R | Must match [PO] |
| Paper fill price vs the replay cost model | median deviation ≤ 3 bps; p90 ≤ 10 bps |
| Trade count | Replay count within ±10% of paper |

Exceeding any tolerance is a D6 failure: the replay cannot be trusted, so stop before any live step.
- **After a PASS (future epic):** a small live stage of ≥ 100 trades. Paper-vs-live tolerance is set in that epic. Paper fills are optimistic, with no queue position and no rejects.

## 9. Config implications (for the PM's config table)

Flags:
- **OF** = overfitting risk: a prior with few or no data points behind it. It must not be tuned on paper-run data.
- **CAL** = calibrate once from pre-paper recorded data, then freeze.

### 9.1 Scoring and selection (section 10)

| Key | Default | Unit | Range / ceiling | Basis | Flag |
|---|---|---|---|---|---|
| `scoring.candidates_k` | 200 | wallets | 50-500 | brief | |
| `scoring.interval_min` | 60 | min | 15-1440 | brief | |
| `scoring.window_days` | 180 | days | 90-365 | brainstorm | OF |
| `gate.min_account_age_days` | 180 | days | ≥ 90 | brainstorm | OF |
| `gate.min_round_trips` | 150 | count | ≥ 50 | brainstorm | OF |
| `gate.min_fill_span_days` | 60 | days | ≥ 30 | QR (10k fill cap) | OF |
| `gate.min_positive_blocks` / `gate.n_blocks` / `gate.block_days` | 4 / 6 / 30 | count, days | | QR (replaces "3 of 4 quarters", which is not observable in 180d) | OF |
| `gate.max_drawdown` | 0.35 | fraction | ≤ 0.5 | brainstorm | OF |
| `gate.min_profit_factor` | 1.3 | ratio | ≥ 1.0 | brainstorm | OF |
| `gate.min_dsr_prob` | 0.95 | probability | 0.5-0.99 | brainstorm / BLdP | |
| `gate.dsr_n_trials` | 15000 | count | ≥ `candidates_k` | market-context (leaderboard size) | see C14 |
| `gate.min_median_hold_min` | 15 | min | ≥ 20 × p95 latency | brainstorm | OF |
| `gate.max_top_trade_share` | 0.25 | fraction | | brainstorm | OF |
| `gate.max_top_asset_share` | 0.50 | fraction | | brainstorm | OF |
| `gate.min_copy_edge_ratio` | 3.0 | ratio | ≥ 1 | brainstorm | OF |
| `gate.min_account_value_usd` | 10000 | USD | | QR | OF |
| `gate.min_executable_share` | 0.50 | fraction | | QR | OF |
| `gate.max_maker_share` | 0.70 | fraction | | QR (excludes market makers) | OF |
| `gate.max_current_drawdown` | 0.20 | fraction | | QR | OF |
| `gate.exclude_vaults` | true | bool | | QR | |
| `blowup.max_adds_while_losing_share` / `min_adds` | 0.20 / 10 | fraction, count | | brainstorm | OF |
| `blowup.max_size_after_loss_ratio` / `min_each` | 1.5 / 20 | ratio, count | | QR | OF |
| `blowup.skew_win_rate` / `skew_loss_mult` | 0.85 / 3.0 | | | brainstorm | OF |
| `blowup.max_worst_to_median_loss` / `min_losses` | 10 / 10 | ratio, count | | brainstorm | OF |
| `blowup.hidden_dd_mult` / `hidden_dd_floor` | 2.0 / 0.15 | ratio, fraction | | QR | OF |
| `blowup.max_median_eff_leverage` | 10 | x | | QR | OF |
| `blowup.max_open_unrealized_loss` | 0.10 | fraction of account value | | QR | OF |
| `blowup.any_liquidation` | true | bool | | QR | |
| `score.weights` (dsr_excess, copy_mean_r, pos_blocks, max_dd, recent_sr, executable) | 0.30, 0.25, 0.15, 0.15, 0.10, 0.05 | sum = 1 | each 0-1 | QR prior | **OF** |
| `score.anchors.*` (lo, hi per component, see 10.4) | see 10.4 | | lo ≠ hi | QR prior | **OF** |
| `score.shrink_k_trades` | 100 | trades | ≥ 0 | QR | OF |
| `score.shrink_k_days_recent` | 30 | days | ≥ 0 | QR | OF |
| `select.join_rank` / `select.drop_rank` | 8 / 15 | rank | join < drop | brief | OF |
| `select.join_confirm_cycles` / `select.drop_confirm_cycles` | 2 / 2 | cycles | ≥ 1 | QR | |
| `select.min_follow_hours` | 24 | h | | brief | |
| `select.min_followed` / `select.max_followed` | 5 / 10 | count | max ≤ WS user cap | brief; market-context Q1 | |
| `select.swap_margin` | 0.10 | score units [0,1] | | QR | OF |
| `select.max_swaps_per_cycle` | 1 | count | | QR | |
| `leader_pause.max_copy_dd` / `leader_pause.max_consec_losses` | 0.10 / 5 | fraction of allocation, count | | brainstorm risk | OF |
| `copyreplay.delay_ms` | measured p95, else 3000 | ms | ≤ 5000 | QR | CAL |
| `copyreplay.half_spread_bps` (majors / alts) | recorded median × 1.5, else 2 / 8 | bps | | QR | CAL |

### 9.2 Evaluation, costs and the run

| Key | Default | Unit | Basis | Flag |
|---|---|---|---|---|
| `eval.n_trades` | 300 | trades | PO | |
| `eval.ci_level` | 0.95 | | PO | |
| `eval.ci_method` | min(t, cluster_bootstrap) | | QR | |
| `eval.bootstrap_b` / `eval.bootstrap_seed` | 10000 / stored | | QR | |
| `eval.max_dd` | 0.15 | fraction | PO | |
| `eval.calendar_cap_days` | 30 | days | PO | |
| `eval.extension_days` | 0 (Q5) | days | PO decision pending | |
| `eval.single_look` | true | bool | QR | |
| `cost.taker_fee_bps` / `cost.maker_fee_bps` | 4.5 / 1.5 | bps | market-context [T] | |
| `cost.hip3_fee_mult` | 2.0 | x | market-context [T] | |
| `paper.ack_delay_ms` | 1000 | ms | market-context | CAL |
| `paper.mark_interval_s` (for drawdown) | 60 | s | QR | |
| `decay.deltas_s` | 0.25, 0.5, 1, 2, 3, 5, 10, 30, 60, 300 | s | QR | |
| `baseline.random_reps` | 1000 | | QR | |
| `baseline.top_roi_n` | 8 | | QR | |

The risk, filter and exit parameters (`risk_per_trade`, ATR multiple, TP, loss limits, slippage and age guards, event windows) come from the brief and the risk research, and the PM owns them. From a research standpoint:
- **OF:** every filter threshold (volatility percentile, funding extreme, spread, OI drop). None has data behind it yet.
- **CAL then freeze:** calibrate each of those thresholds once on pre-paper recorded data, then freeze it.

---

## 10. Trader scoring model (precise, for the config table and property tests)

### 10.1 Inputs, point-in-time

For wallet w at cycle time t (UTC ms):
- `F_w(t)` = cached fills with `time ≤ t`, within `window_days`.
- `P_w(t)` = the latest `portfolio` snapshot fetched at or before t.
- `C_w(t)` = the latest `clearinghouseState` fetched at or before t.
- `K(t)` = 1h candles with close time ≤ t.

Missing or stale inputs, meaning older than `2 × interval_min`, make the wallet **ineligible** (fail closed, A2).

**Round-trip reconstruction.** Implemented in `research/scripts/hl_sample.py::reconstruct`, which has a self-test.
- A per-coin position goes from 0, to non-zero, and back to 0. A flip splits into a close and a new open.
- A position already open at the first available fill is ignored until it is flat.
- Spot and excluded dexes are skipped.
- Per round trip j, the reconstruction records:
  - coin, direction s_j, open and close times, entry px and size
  - peak notional `N_j = max|pos| × avg_px`
  - adds, adds-while-losing, reduce fractions
  - leader net P&L `L_j = Σ closedPnl − Σ fee − funding_j`

**Daily returns.** `r_d = ΔpnlHistory_d / AV_{d−1}`.
- `ΔpnlHistory_d` comes from `perpAllTime` or `perpMonth` `pnlHistory`, step-interpolated at UTC midnights. It is deposit-neutral.
- `AV_{d-1}` comes from `accountValueHistory`.
- Days with no change count as 0.
- T = the number of days in the window.

### 10.2 Metrics (per wallet, per cycle)

| ID | Metric | Formula |
|---|---|---|
| M1 | `n_rt` | closed round trips in the window |
| M2 | `fill_span_days` | (last fill − first fill) / 1 day, within the window |
| M3 | `account_age_days` | t − the first `perpAllTime` point |
| M4 | `profit_factor` | `Σ_{L_j>0} L_j / |Σ_{L_j<0} L_j|`, capped at 10 |
| M5 | `sr_d` | `mean(r_d) / sd(r_d)`, daily, zeros included |
| M6 | `skew`, `kurt` | sample skewness and (non-excess) kurtosis of r_d |
| M7 | `dsr_prob` | `Φ((sr_d − SR0)·√(T−1) / √(1 − skew·sr_d + (kurt−1)/4·sr_d²))` with `SR0 = Emax(N)/√T`, `Emax(N) = (1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N·e))`, γ = 0.5772, N = `dsr_n_trials` (Bailey & López de Prado 2014, with the null variance of the Sharpe estimate taken as 1/T) |
| M8 | `pos_blocks` | number of the last `n_blocks` blocks of `block_days` with Σ `pnlHistory` change > 0. A block with no data counts as not positive. |
| M9 | `max_dd` | max(DD of realised equity `AV_0 + cumΣ L_j`, DD of the mark-to-market curve `AV_0 + pnlHistory`) |
| M10 | `median_hold_min` | median (close − open) over round trips |
| M11 | `top_trade_share` | `max_j L_j / Σ_j L_j` (ineligible if Σ ≤ 0) |
| M12 | `top_asset_share` | `max_coin Σ_{j∈coin} L_j / Σ_j L_j` |
| M13 | `maker_share` | notional of fills with `crossed = false` / total notional |
| M14 | **`copy_mean_r`** | **Copy replay.** Each round trip is re-traded as we would trade it: entry at the leader's open px plus a delay cost, our ATR stop (from `K(t)` before entry), our TP, the leader's close or our SL/TP whichever comes first (the high/low of 1h bars; ambiguous bar means stop first), mirrored partial cuts, adds ignored, our costs. Gives `R_copy_j` and `copy_mean_r = mean_j R_copy_j`. |
| M15 | `copy_edge_ratio` | `mean_j(gross_bps_j) / mean_j(cost_bps_j)`, where `gross_bps_j = Σ closedPnl_j / N_j × 1e4` and `cost_bps_j = 2·taker + 2·half_spread(coin) + delay_bps(coin)` |
| M16 | `executable_share` | share of opens whose mirrored notional `(open_notional / AV_at_open) × our_equity`, after the risk cap with our stop, is ≥ $10 |
| M17 | `recent_sr` | `sr_d` over the last 30 days × 30/(30 + `shrink_k_days_recent`) |
| M18 | `current_dd` | (peak − current) / peak of the mark-to-market curve |
| M19 | `eff_leverage_median` | median over opens of `N_j / AV_at_open` |

### 10.3 Eligibility gates (all must hold; fail closed)

| ID | Gate |
|---|---|
| G1 | `account_age_days ≥ min_account_age_days` (180) |
| G2 | `n_rt ≥ min_round_trips` (150) |
| G3 | `fill_span_days ≥ min_fill_span_days` (60). This handles the 10k-fill cap: very active wallets cannot show 60 days, and are mostly scalpers anyway. |
| G4 | `pos_blocks ≥ min_positive_blocks` (4 of 6 × 30d) |
| G5 | `max_dd ≤ 0.35` |
| G6 | `profit_factor ≥ 1.3` |
| G7 | `dsr_prob ≥ 0.95` (**luck correction**) |
| G8 | `median_hold_min ≥ max(15, 20 × p95_latency_min)` |
| G9 | `top_trade_share ≤ 0.25` and `top_asset_share ≤ 0.50` |
| G10 | `copy_edge_ratio ≥ 3` **and** `copy_mean_r × n_rt/(n_rt + shrink_k_trades) > 0` |
| G11 | `AV ≥ $10,000` |
| G12 | `executable_share ≥ 0.50` |
| G13 | `maker_share ≤ 0.70`; not a vault; not HLP |
| G14 | no blow-up flag (10.5) |
| G15 | `current_dd ≤ 0.20` |

### 10.4 Score (eligible wallets only)

`u_k = clip((x_k − lo_k) / (hi_k − lo_k), 0, 1)` and `S = Σ_k w_k · u_k`, with Σ w_k = 1 and w_k ≥ 0, so S ∈ [0, 1].

Each component uses **fixed config anchors, not cross-sectional z-scores**. As a result, S depends only on the wallet's own data (point-in-time and order-independent) and is monotone in each component.

| k | Component x_k | lo | hi | w |
|---|---|---|---|---|
| 1 | `dsr_excess = sr_d − SR0` | 0 | 0.15 | 0.30 |
| 2 | `copy_mean_r_shrunk = copy_mean_r × n_rt/(n_rt + 100)` | 0 | 0.30 R | 0.25 |
| 3 | `pos_blocks / n_blocks` | 0.5 | 1.0 | 0.15 |
| 4 | `max_dd` (lower is better, so lo > hi) | 0.35 | 0.05 | 0.15 |
| 5 | `recent_sr` | 0 | 0.30 | 0.10 |
| 6 | `executable_share` | 0.5 | 1.0 | 0.05 |

**Tie-break**, which keeps the ranking deterministic: higher `n_rt` first, then the lowercase address in ascending order.

**Luck correction, in three places:**
1. the G7 Deflated Sharpe gate and the dsr_excess component, with N = leaderboard size
2. shrinkage of `copy_mean_r` toward 0 by n/(n + 100), and of `recent_sr` by 30/(30 + 30)
3. persistence required by the hysteresis (10.6)

### 10.5 Blow-up detectors (any flag makes the wallet ineligible, and triggers an immediate safety drop if followed)

| ID | Detector | Rule |
|---|---|---|
| BU1 | Martingale adds | Of adds made while `(add_px − avg_px)·s < 0` (adding to a loser), the share > 0.20, evaluated when ≥ 10 adds |
| BU2 | Size up after losses | `median(N_j/AV)` of trades following a loss ÷ `median(N_j/AV)` following a win > 1.5, evaluated when ≥ 20 of each |
| BU3 | Short-volatility profile | win rate > 0.85 **and** mean loss > 3 × mean win |
| BU4 | Tail loss | worst `L_j` < −10 × median loss magnitude, evaluated when ≥ 10 losses |
| BU5 | Hidden drawdown | mark-to-market DD > 2 × realised DD **and** mark-to-market DD > 0.15 |
| BU6 | Liquidation | any liquidation fill in the window |
| BU7 | Leverage | `eff_leverage_median > 10` |
| BU8 | Bag holding now | open unrealised loss in `C_w(t)` > 10% of AV |

### 10.6 Selection and hysteresis (each cycle)

1. Compute eligibility and S for all candidates and currently followed wallets. Rank the eligible by S, descending.
2. **Safety drop (immediate; ignores the minimum follow time):**
   - trigger: a followed wallet has any BU flag, fails G15, or our per-leader pause trips (copy DD ≥ 10% of its allocation, or 5 consecutive losses of our copies)
   - effect: new opens stop at once
3. **Rank drop:**
   - trigger: a followed wallet has rank > `drop_rank` (15), or fails a non-safety gate, for `drop_confirm_cycles` (2) consecutive cycles, **and** it has been followed ≥ `min_follow_hours` (24)
4. **Join:**
   - trigger: an unfollowed wallet is eligible with rank ≤ `join_rank` (8) in `join_confirm_cycles` (2) consecutive cycles, and there is room (followed < `max_followed`)
5. **Swap:**
   - trigger: followed = `max_followed`, and a join-qualified candidate has `S_cand ≥ S_weakest + swap_margin` (0.10)
   - condition: the weakest followed wallet has been followed ≥ 24h
   - effect: the candidate replaces the weakest, at most 1 swap per cycle
6. If fewer than `min_followed` are eligible, follow all eligible wallets. Never pad the list with ineligible wallets. Alert. With 0 eligible, take no new entries.
7. **Dropped wallets:** no new opens are copied. Existing shares stay managed by our SL/TP and the wallet's exits (C4), through the risk gate, until they close. The WebSocket slot is held until then (see market-context Q1).
8. **Leaderboard unavailable:** keep the current wallets, add none, alert [PO].
9. Persist every cycle's inputs, metrics, u_k, S, rank and decision (B5, and point-in-time replay).

### 10.7 Property tests (for the test designer)

1. For any valid config, the weights are all ≥ 0 and sum to 1 (±1e-9). Otherwise config load fails closed.
2. S ∈ [0, 1], and each u_k is non-decreasing in its "better" direction (monotonicity).
3. S for wallet A does not depend on any other wallet's data or on input order.
4. The same inputs always give the same S, rank and decisions (determinism, including the tie-break).
5. **Point-in-time:** adding fills with `time > t` never changes the score at t.
6. An ineligible wallet is never followed, and a missing input implies ineligible.
7. The followed count never exceeds `max_followed`. It is below `min_followed` only when fewer are eligible.
8. A wallet ranked in `(join_rank, drop_rank]` keeps its current status (the hysteresis band).
9. No rank-based drop happens before `min_follow_hours`. A safety drop can happen at any time.
10. There is at most `max_swaps_per_cycle` swaps per cycle.
11. Each BU detector fires exactly at its threshold boundary (inclusive or exclusive, as specified) and not below its minimum sample.
12. DSR: `dsr_prob` is non-increasing in `dsr_n_trials` and non-decreasing in `sr_d` (for fixed skew and kurtosis in the valid domain).
13. `copy_mean_r_shrunk` has the same sign as `copy_mean_r` and a smaller or equal magnitude.

---

## 11. Feasibility: is ~300 trades in 30 days realistic?

**Short answer: not reliably.** It is roughly a coin flip in the base case, near impossible in the pessimistic case, and likely only if leaders are active (≥ 3 opens per trader per day) and have a real edge.

**Where the estimate comes from:**
- `scripts/feasibility_mc.py`, seed 7, 2,000 runs per cell, **[EXPL, synthetic priors, not Hyperliquid data]**.
- Rejections modelled:
  - filter
  - signal age
  - slippage
  - conflicts
  - caps
  - $10 minimum
  - 10 concurrent positions
  - net daily and weekly loss halts
  - the 15% drawdown stop, which ends the run as a FAIL

| Scenario (followed; opens/trader/day; filter pass) | True mean R | Taken trades in 30d, p10 / p50 / p90 | P(≥ 300 before a 15% DD) | P(DD ≥ 15%) | Partials below $10 |
|---|---|---|---|---|---|
| Pessimistic (5; 1.5; 0.50) | 0.00 | 44 / 72 / 118 | 0.00 | 0.006 | 37% |
| Pessimistic | +0.10 | 45 / 72 / 120 | 0.00 | 0.000 | 37% |
| Base (8; 3.0; 0.65) | 0.00 | 115 / 267 / 424 | 0.39 | 0.46 | 16% |
| Base | +0.10 | 241 / 366 / 523 | 0.75 | 0.07 | 16% |
| Optimistic (10; 6.0; 0.80) | 0.00 | 92 / 262 / 729 | 0.45 | 0.86 | 6% |
| Optimistic | +0.10 | 327 / 904 / 1235 | 0.91 | 0.16 | 6% |
| Base, 0.5% risk per trade | 0.00 | 268 / 387 / 547 | 0.81 | 0.14 | 25% |
| Base, 0.5% risk per trade | +0.10 | 295 / 430 / 595 | 0.89 | 0.004 | 25% |

**Reading:**
1. **The binding constraint is leader activity × pass rate, not latency.** The eligibility gates only guarantee ≥ 0.83 opens per trader per day (150 round trips in 180 days). Multi-hour swing traders often make 1-3 trades a day. **My central estimate is 100-300 taken trades in 30 days**, with 300 likely only in the base-to-optimistic range.
2. **With 1% risk per trade, the drawdown line decides many runs.**
   - A zero-edge run hits 15% about 46% of the time, which is the gate working as intended.
   - A +0.10R edge still fails on drawdown 7-16% of the time.
   - Net daily and weekly loss halts also remove 5-20% of candidate entries.
3. **The $10 minimum hurts partial exits more than opens.**
   - Mirrored partial reduces fall below $10 in 6-37% of cases, depending on how large leaders' positions are relative to their accounts.
   - Opens are rejected mainly when leaders use a small fraction of their account: about 17% of opens that passed the other guards in the pessimistic case (16 of about 95 per run), about 1% in the base and optimistic cases.
   - This must be measured: `hl_sample.py` does so once network access exists.
4. More trades per trader share inflates N without adding independent information (concern C1).

## 12. Exploratory work log (all EXPL; for the backtest-auditor)

| # | What | Files | Result | Counts as a strategy variant? |
|---|---|---|---|---|
| E1 | Reach the Hyperliquid API from the research sandbox | n/a | **Unreachable**: egress proxy CONNECT 403 for `api.hyperliquid.xyz`, `stats-data.hyperliquid.xyz` and `hyperliquid.gitbook.io`. No real data pulled. | no |
| E2a | `feasibility_mc.py` first run | superseded | **Modelling bug**: loss halts summed gross losses instead of net P&L, and the run did not stop at a 15% drawdown. Results discarded, logged here for honesty. | no (sensitivity) |
| E2b | `feasibility_mc.py` second run | superseded | Net-P&L halts fixed; still no drawdown stop. Discarded. | no |
| E2c | `feasibility_mc.py --runs 2000 --seed 7` (final): 4 scenarios × 2 true means | `docs/sdlc/copytrade-v1/research/scripts/feasibility_mc.py`; output `research/data/feasibility_mc_seed7.txt` (gitignored) | Section 11 table | no: 8 sensitivity cells of the synthetic model |
| E3 | `gate_power.py --sims 4000 --seed 11` | `docs/sdlc/copytrade-v1/research/scripts/gate_power.py`; output `research/data/gate_power_seed11.txt` | Section 13 (C1, C2, C3, C5) | no |
| E4 | `hl_sample.py --selftest` | `docs/sdlc/copytrade-v1/research/scripts/hl_sample.py` | Self-test OK: round-trip reconstruction, flip split, pre-existing positions skipped, add-while-losing, reduce fraction, $10 checks, drift sign. **Never run against the live API.** | no |

**Strategy variants tried on real data: 0.** The variant budget in 5.3 is untouched.

**Key numbers from E3** [EXPL; per-trade R modelled as a normal distribution clipped to −1.05..+3R]:

| Topic | Result |
|---|---|
| CI half-width at n = 300 | ±0.113R at SD 1.0R; ±0.136R at SD 1.2R; ±0.170R at SD 1.5R |
| True mean R needed for 80% power | 0.16R (SD 1.0); 0.19R (SD 1.2); 0.24R (SD 1.5) |
| Power at +0.05R | 10-15% |
| Power at +0.10R | 34-49% |
| Power at +0.15R | 64-83% |
| False PASS at a true mean of 0 | single look 1.9%; checked every 10 trades from 30 to 300: **10.1%**; "keep running" from 300 to 600: 5.4% |
| Clustered trader shares (mean cluster size 1.5-1.8, within-cluster correlation 0.7-0.9) | naive t-CI false PASS **4.4-6.2%**; cluster bootstrap 1.6-2.4% |
| Luck (Emax) | E[max z] = 2.77 (N = 200), 3.45 (N = 2,000), 4.12 (N = 30,000). With T = 180 days, SR0 = 0.21 to 0.31 per day, i.e. annualised Sharpe 3.9-5.9 needed just to match luck. |
| Mean R vs USD | 6 wins of +0.5R on $1 risk and 1 loss of −1R on $9 risk: mean R = **+0.29R**, but USD = **−$6**. |

## 13. Concerns for the PO (statistical soundness; no PO decision has been changed)

| ID | Concern | Evidence | Recommendation (needs PO approval unless marked as method only) |
|---|---|---|---|
| C1 | **Counting trader shares as independent trades overstates N.** Several trader shares of one merged position, and BTC-beta trades in the same hour, move together. A naive CI then passes a zero-edge strategy 2-3× too often. | E3: 4.4-6.2% vs 1.9% | Method only, so pre-registered in P2: use the more conservative of the t-interval and the cluster bootstrap. The PO's "95% CI lower bound > 0" is unchanged. |
| C2 | **Peeking.** Declaring PASS the first time the running CI clears 0 multiplies the false-pass rate by about 5. | E3: 10.1% vs 1.9% | Method only, so pre-registered in P7: one look at N = 300. Please confirm. |
| C3 | **Mean R can be positive while the account loses money.** Mirrored sizing makes the dollar risk per trade vary widely: a $0.30-risk trade weighs as much as a $3 one. | E3 toy: +0.29R and −$6 | Add S1 (USD P&L > 0) and S2 (risk-weighted mean R > 0) as **co-conditions** of PASS. **PO decision.** |
| C4 | **R understates risk when the leader adds.** The brief defines R on initial risk, but mirrored adds with the same stop add dollar risk. A trade that tripled in size and won is scored as +3× what was actually risked. | definition | Gate on the PO's R, and also report R_maxrisk. Better: define R on the maximum committed risk. **PO decision.** |
| C5 | **Low power.** 300 trades detects only edges ≥ about 0.16-0.24R with 80% probability. A realistic copy edge, if one exists, is likely < 0.10R, so **INCONCLUSIVE is the most likely honest outcome even if the strategy works modestly.** | E3 | Accept that INCONCLUSIVE is common. Optionally pre-register a larger fixed N (e.g. 600, one look) with a calendar cap of 60 days. **PO decision (Q5).** |
| C6 | **1% risk per trade plus a 15% drawdown FAIL** gives a 7-16% chance of failing a real +0.10R edge in one month. Zero-edge strategies fail on drawdown about 46% of the time, which is desirable. | E2c | Consider defaulting `risk_per_trade` to 0.5%, which is within the PO's ≤ 1% ceiling. Drawdown failure at +0.10R falls to 0.4%, but more partial exits fall below $10 (25% vs 16%). **PO decision.** |
| C7 | **300 trades in 30 days is uncertain.** P ≈ 0.4-0.75 in the base case; about 0 if leaders make about 1.5 opens per day. | E2c | Keep "INCONCLUSIVE if N < 300" [PO]. Decide the extension policy now, not after seeing data (Q5). |
| C8 | **Paper at $300 does not transfer to a $100 live wallet.** The unexecutable share (below $10) and partial-exit fidelity get worse as the wallet shrinks, which changes which trades are taken. | E2c partial-exit rates | The live wallet should be ≥ the paper wallet, or re-paper at the live size. **PO decision.** |
| C9 | **Partial exits below $10 cannot be mirrored.** 6-37% of partials in the synthetic model; reduce-only full closes are exempt. | E2c; market-context 1.1 | Needs a rule. Proposal: round the cut up to $10 if the remainder stays ≥ $10; if the remainder would fall below $10, close fully. Log every deviation from a pure mirror. **PO/PM decision.** |
| C10 | **Our stops change the leader's payoff.** Leaders' historical P&L does not predict our copies. | mechanism | Method only: the scoring model uses the copy-replay R (M14), not the leader's ROI. |
| C11 | **Deflated Sharpe with N = 15,000** may leave fewer than 5 eligible traders, because a daily Sharpe of about 0.3 is needed. | E3 luck | If that happens, it is evidence that the leaderboard shows no distinguishable skill. Do **not** loosen the gate mid-run. Any relaxation is a logged pre-paper variant. **PO awareness.** |
| C12 | **Pre-recording replay is survivorship-biased**, because it uses today's leaderboard. | D2 | Use it only for kill checks (K1). Evidence comes from the point-in-time replay and the paper run. |

## 14. Questions for the PO

| # | Question |
|---|---|
| Q1 | (C3) Add "net USD P&L > 0" and "risk-weighted mean R > 0" as co-conditions of PASS? |
| Q2 | (C4) Define R on maximum committed risk (initial + adds) instead of initial risk? Or keep initial risk and report both? |
| Q3 | (C2, C1) Confirm the single evaluation at exactly N = 300, and the conservative cluster-robust CI? |
| Q4 | (C6) Default `risk_per_trade` 0.5% (inside your 1% ceiling) for the paper run, or keep 1%? |
| Q5 | (C5, C7) If N < 300 at day 30: stop as INCONCLUSIVE (your current rule), or extend up to 60 days with the same frozen config and the same single look? Must be decided before the run. |
| Q6 | (C9) Partial exit mirroring below $10: round up to $10, close fully, or skip (log only)? |
| Q7 | (C8) Will the live wallet be at least $300? If not, should the paper run use the live size? |
| Q8 | Allow a one-off ~$1-6 AWS requester-pays S3 pull of historical fills and L2 for a better pre-paper replay? This needs an AWS account that you control, and research agents never handle keys. Or accept replay only from our own recordings? |
| Q9 | Run `hl_sample.py` once from your PC (public endpoints, no keys) to replace the synthetic priors in section 11 with real trade frequency, holding time, and $10-rejection rates before the PM freezes defaults? |

## Sources

- [Hyperliquid 10,000-trader analysis (73.8% losing, Nov 2024)](https://medium.com/@envyprotocol/i-analyzed-10-000-hyperliquid-traders-the-results-are-brutal-a29adcca8c2a)
- [Only 166 of 1,000 Hyperliquid traders profitable](https://www.thecoinrepublic.com/2025/06/16/hyperliquid-crypto-only-166-of-1000-traders-profitable-whats-going-on/)
- [userFillsByTime limits (Chainstack)](https://docs.chainstack.com/reference/hyperliquid-info-user-fills-by-time)
- [Hyperliquid S3 backfill discussion](https://github.com/tribulnation/sdk/issues/1)
- [portfolio endpoint (QuickNode)](https://www.quicknode.com/docs/hyperliquid/info-endpoints/portfolio)
- [Leaderboard payload (Apify)](https://apify.com/gochujang/hyperliquid-leaderboard)
- [Hyperliquid fees overview](https://hyperliquidguide.com/guides/fees)
- [Order precision and minimum order value (Chainstack)](https://docs.chainstack.com/docs/hyperliquid-order-precision)
- Bailey & López de Prado (2014), "The Deflated Sharpe Ratio"
- Apesteguia, Oechssler & Weidenholzer (2020), Management Science
- Heimer & Imas (2022), Review of Financial Studies
