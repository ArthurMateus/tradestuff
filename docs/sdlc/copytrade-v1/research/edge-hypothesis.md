# Edge hypothesis: copytrade-v1

Date: 2026-09-29. Author: quant-researcher. Version: **v2 + Addenda A1 and A2** (both dated 2026-09-29, written before run 1 and before any real result).

Status: **PRE-REGISTRATION FROZEN.** No result on real data exists yet. No paper run has started.
- v2 encodes the PO's research-phase decisions and closes backtest-audit findings BT-1 to BT-17. The closure table is in section 15.
- **Addendum A1 (5.10)** closes round-2 audit findings BT2-1 to BT2-9. It follows the 5.1 addendum rule: every change to frozen text is listed in 5.10 with the v2 wording it replaces, and the amended text is in place, marked `(A1.n)`.
- Section 5 is the frozen pre-registration. Section 5.1 says how it is frozen and how it can legitimately change.
- **Addendum A2 (5.11)** closes round-3 audit findings BT3-1 to BT3-7 (all ADVISORY; the round-3 verdict was VALID). It follows the same rule: every replaced text is quoted verbatim in 5.11, and the amended text is in place, marked `(A2.n)`.
- **Run 1 must not start until the PO has acknowledged the eight items in section 14** (pending PO acknowledgement, BT2-5; items 6-8 added by A2.4).

Inputs:
- `01-brief.md`, `02-discovery.md`, `03-answers.md` (including "Research-phase decisions")
- `docs/product/decisions.md` (2026-09-29 entries)
- `research/brainstorm-domain-research.md`, `research/market-context.md`
- `research/backtest-audit.md` (BT-1 to BT-17), `research/backtest-audit-r2.md` (BT2-1 to BT2-9), `research/backtest-audit-r3.md` (BT3-1 to BT3-7)

Labels used below:
- **[PO]** a fixed PO decision, reproduced and not changed
- **[QR]** a research choice made here. The PO or PM may override it, but only before run 1 starts (5.1).
- **[QR, PO-ACK pending]** a research choice that interprets or tightens a PO decision. It needs the PO's written acknowledgement before run 1 (section 14). The CTO records the answer.
- **[EXPL]** exploratory and synthetic. It is not evidence and has not yet been reviewed by the backtest-auditor.

## 0. Base rates and prior

- **Most Hyperliquid traders lose money.** A 30-day, 10,000-wallet on-chain sample (Nov 2024) found:
  - 73.8% of wallets losing
  - 16.5% profitable
  - 27.2% losing more than 85% of capital

  That is a third-party analysis of public data, so treat it as a base rate, not a precise number. Another sample of 1,000 wallets found 16.6% profitable.
- **Leaderboards select on luck.** The leaderboard has about 15,000 rows (market-context 2.1). Among 15,000 zero-skill wallets, the best shows a t-statistic of about 3.9 by chance (Emax(15,000), between the N = 2,000 and N = 30,000 values in E6 section E).
- **Copy trading adds its own costs:**
  - taker fees on both legs
  - the spread
  - delay slippage
  - a payoff change from our own stops

  In R terms these costs are about 0.04-0.53R per trade (6.3). Apesteguia et al. (2020) show copy trading induces excess risk-taking. In Alpha Arena S1, 4 of 6 LLM traders lost money.
- **Prior (QR):** P(mean copy R > 0 after all costs) is about 0.25.
  - Conditional on being positive, the most likely true mean is below 0.10R.
  - Scalpers and market makers are uncopyable at 1-5 s delay.
  - Whatever edge exists should come from multi-hour discretionary or informed traders.

**Default belief: no edge.** Everything below is designed to find that out cheaply and honestly. The most likely honest verdict of a paper run is INCONCLUSIVE (5.9, 11).

---

## 1. Hypothesis

**H1 (primary; the go-live gate tests this).**
- **Setup:** automatically copy the 5-9 Hyperliquid wallets ranked highest by the scoring model in section 10 [PO: at most 9] into a $300 paper wallet at 0.5% risk per trade [PO]. The copy uses:
  - our deterministic filter
  - mirrored fractional sizing capped by risk limits
  - first-exit-wins exits
- **Claim:** this yields a positive mean R per trade over the **first 300 opened trades**, evaluated once all 300 have closed [PO].
- **Costs:** every trade is net of taker fees, spread and book impact at decision time plus the configured ack delay, and hourly funding.
- **Test:** the exact rule is the frozen rule in 5.3. In short:
  - the day-clustered CI lower bound at the run's CI level is > 0
  - net USD P&L is > 0
  - the trades beat a direction-matched, random-time baseline
  - mark-to-market drawdown stays below 15%

**H2 (selection adds information beyond direction and beta).** Over the same evaluation window:
- (a) **gating [PO]:** the trades beat B0d, the direction-matched random-time baseline in 6.2. This is P2c in 5.3.
- (b) **go-live blocker, not gating:** our mean R exceeds the mean R of copying the top 9 wallets by raw 30-day ROI through the same engine (S4, K9).

**H3 (filter adds value; exploratory only).** Taken signals have a higher mean R than the shadow outcomes of rejected signals. v1 cannot answer this: detecting a 0.2R lift needs about 880 trades per arm. It is reported, never gating.

**Falsification:**
- H1 fails when the frozen rule returns FAIL: the CI upper bound ≤ 0, or drawdown reaches 15%, or a missed exit.
- H2(a) fails when P2c fails.
- H2(b) fails when S4 fails.

## 2. Mechanism: why an edge could exist, and who is on the other side

**Why it could exist:**
1. **Persistent skill in a small minority.** Some traders have skill at multi-hour horizons: information processing, flow reading, funding and basis dislocations.
   - Their edge accrues over minutes to hours, so a 1-5 s copy delay costs only a small fraction of it.
   - The eligibility gates keep only these traders (median hold ≥ 15 min).
2. **Informed flow.** Some large Hyperliquid wallets have traded ahead of news. Copying public on-chain fills is legal. Whether such edges persist is unknown.
3. **Transparency.** Hyperliquid publishes every wallet's fills in real time, so the edge is observable without trusting self-reported ROI (C1).

**Who is on the other side:**
- **Of the leader's trade:** market makers (including HLP) and less informed takers.
- **Of our copy:** market makers who have already seen the leader's flow, and other copy bots racing us for the same liquidity.
  - If crowding matters, it shows up as adverse drift in the seconds after the leader's fill: the decay metric in section 4.
  - At $300 our own book impact is negligible, but the crowd's is not.

**Why it probably does not exist, or does not transfer to us:**
- **Luck.** Thousands of wallets means impressive track records happen by chance.
- **Execution edges are uncopyable.** Maker rebates, queue position and HFT profits do not survive a copy.
- **Our exits change the payoff.**
  - A leader who averages down and holds through a 3×ATR drawdown wins where our 2×ATR stop took −1R.
  - The leader's historical P&L therefore does not predict our copy's R.
  - The scoring model scores the copy-replay R, not the leader's P&L (section 10).
- **Sizing distortion.** Mirrored sizing plus the $10 minimum drops small, early-tranche and partial orders. Under the PO rule, a partial below $10 is skipped, or the position is closed in full if the remainder would be below $10.
- **Beta, not skill.** A long-biased copy portfolio profits in a rising month. The direction-matched random-time baseline (P2c) exists to catch this.
- **Regime dependence.** A 30-60-day window is a single regime.

Mechanism strength: weak to moderate. The prior in section 0 stands.

## 3. Data

| Need | Source | Fields | Granularity | History | Point-in-time? | Gaps / notes |
|---|---|---|---|---|---|---|
| Candidate list | `GET stats-data.hyperliquid.xyz/Mainnet/leaderboard` (undocumented) | `ethAddress`, `accountValue`, `windowPerformances` (day/week/month/allTime: `pnl`, `roi`, `vlm`) | snapshot | none: current state only | **Only from our own hourly snapshots, recorded from day 1 [PO]** | Survivorship: wallets that blew up drop off. We store every snapshot and never delete a wallet we have seen (D2). |
| Leader fills (scoring) | `POST /info userFillsByTime` (`aggregateByTime: true`) | `coin`, `px`, `sz`, `side`, `time`, `startPosition`, `dir`, `closedPnl`, `fee`, `crossed`, `oid`, `tid`, `hash`, `liquidation` | per fill, ms | **Latest 10,000 fills per wallet**; ≤ 2,000 per call | Yes: fills are immutable; the score at t uses fills with `time ≤ t` only | History is bounded by fill count; gate G3 handles busy wallets. TWAP slice fills are a separate stream and not covered. |
| Leader fills (live) | WS `userFills` | same | per fill | live | Yes: exchange timestamp plus local receive timestamp (B2) | Max 10 unique users per IP. 9 followed plus 1 slot for swaps [PO]. |
| Leader equity and P&L curve | `POST /info portfolio` | `accountValueHistory`, `pnlHistory` per `perpDay`/`perpWeek`/`perpMonth`/`perpAllTime` | allTime about 93 points (coarse); month finer | account lifetime | **No**: fetched now, covering the past. Point-in-time only for values we snapshot ourselves. | `accountValue` jumps with deposits. Returns use the deposit-neutral `pnlHistory`. Resolution rules are in 10.1 (BT-17). |
| Account role | `POST /info userRole` | `role` ∈ user / agent / vault / subAccount / missing | snapshot | now | Snapshot per scoring cycle | Used by the vault/HLP gate G13 |
| Leader funding | `POST /info userFunding` | per-hour funding paid | hourly | bounded | yes | Adds weight per 20 items |
| Current positions and account value | `clearinghouseState` (weight 2) | positions, `marginSummary.accountValue` | snapshot | none | Only when we snapshot it | Needed for mirrored sizing at signal time |
| Prices for the copy replay | `candleSnapshot` 1h (about 208 days) and 1m (about 3.5 days) | OHLCV | 1h / 1m | 5,000 candles | yes | 1h bars are coarse for stop checks. On an ambiguous bar, assume the stop hit first (conservative). |
| Books, mids, trades (paper fills, decay, baselines) | WS `l2Book`, `allMids`, `trades`; REST `l2Book` | levels, mid, prints | tick | **none historically via API** | Only what we record | **Recorded from day 1 [PO]** for every coin the followed wallets trade, and for HIP-3 markets (recorded only, not traded [PO]). **No paid S3 data [PO].** |
| Funding rates, OI, mark/oracle | `metaAndAssetCtxs`, `fundingHistory` | `funding`, `openInterest`, `markPx`, `oraclePx` | hourly / snapshot | bounded | Only what we record | Paper funding accrues hourly from actual rates [PO] |
| Exchange rules | `meta` | `szDecimals`, `maxLeverage` | static | now | Snapshot at startup | $10 minimum order value; a reduce-only full close is exempt [T] |
| Macro calendar | Fed, BLS, BEA data file | event, ET time | event | quarterly | yes | Times anchored to America/New_York. Blackouts block entries and adds only [PO]. |

**Survivorship treatment (D2):**
1. The go-live evidence uses only our own point-in-time data: leaderboard snapshots, scores, decisions, books and paper fills, all recorded live.
2. Any replay before our recording started is labelled "indicative only, survivorship-biased" and never counts as evidence. That includes `hl_sample.py`, whose pool is today's leaderboard.
3. A trader who is dropped, blows up or vanishes from the leaderboard stays in the dataset, and their copied trades stay in the stats.
4. Delisting settlements are counted as normal trades at the exchange settlement price [PO].

**Look-ahead (D1):**
- The score at cycle t uses fills with `time ≤ t`, and the portfolio or clearinghouse snapshot fetched at or before t.
- Every cycle's inputs, metrics, score, rank and decision are persisted, so replays read the stored snapshot rather than refetching.
- The ATR for a stop uses candles closed before entry.
- The filter uses only data older than the decision timestamp.
- A leader's account value for a past event is the latest point at or before it, never a later one.

**Known gaps:**
- There is no historical order book, so the replay's slippage is modelled.
- The 10,000-fill cap limits history.
- The coarse all-time equity curve is not used for Sharpe (10.1).
- Brazil-to-Tokyo latency has not been measured.
- The leaderboard endpoint is undocumented and can break.
- **The Hyperliquid API is not reachable from this research environment.** The egress proxy returns 403 by organization policy; re-checked on 2026-09-29, E8. No real sample has been pulled. The PO runs `hl_sample.py` once from their PC [PO] (`scripts/README.md`).

## 4. Metrics

All metrics come from the append-only ledger. They are net of taker fees, spread and book impact, delay and hourly funding, and cover every trade in the sample, including:
- losers
- reconstructed trades
- delisting settlements
- trades around macro events [PO]

| Metric | Definition |
|---|---|
| **R per trade [PO]** | `net_pnl_usd / initial_risk_usd`, where `initial_risk_usd = qty_at_entry × |entry_fill_px − initial_stop_px|` + estimated exit fee. One trade is one trader share, from our entry fill to fully closed [PO]. **This R is the gate statistic.** |
| R_maxrisk (reported) [PO] | `net_pnl_usd / max_committed_risk_usd` over the trade's life, counting the risk added by mirrored adds. Mean R_maxrisk ≤ 0 raises flag FR5. |
| **Net USD P&L [PO]** | Σ `net_pnl_usd` over the sample. It is a PASS condition (P2b). It has the same sign as the risk-weighted mean R `Σ net_pnl_usd / Σ initial_risk_usd` (S2), so S2 needs no separate gate. |
| **Baseline excess D_i [PO + QR]** | `R_i − mean R of trade i's 1,000 direction-matched random-time replications` (B0d, 6.2). Its day-clustered lower bound is P2c. |
| Expectancy | mean R, and mean USD P&L per trade |
| Win rate and payoff ratio | share of trades with R > 0; `mean(R | R>0) / |mean(R | R≤0)|`. Always reported together. |
| Max drawdown | peak-to-trough of **marked-to-market** paper equity (marked every 60 s), as a % of peak |
| Trade count | trades opened. Also counted separately: signals seen, rejected by reason, unexecutable (below $10), conflict-skipped, and opened after the 300th (outside the sample). |
| Exposure time | fraction of wall-clock time with ≥ 1 open position; time-average of open risk as % of equity |
| Turnover | Σ traded notional / mean equity, per day |
| Exit-reason mix | our SL, our TP, trader close, trader reduce to zero, close-all under the $10 remainder rule, delisting settlement, reconstructed, marked at the close-out cap |
| Mirror fidelity | share of leader adds and partials we could not mirror: partial skipped below $10, close-all under the remainder rule, add below $10, add blocked by a risk cap, stop-widening skip |
| **Cost in R** | per trade `c_i = (fees + spread and impact vs mid at decision + delay slippage vs the leader fill) / initial_risk_usd`, excluding funding. Feeds FR3. |
| **Signal-to-fill decay** | `decay(Δ) = mean over signals of s × (mid(t_leader + Δ) − px_leader) / px_leader`, in bps. s = +1 for long and −1 for short; Δ ∈ {0.25, 0.5, 1, 2, 3, 5, 10, 30, 60, 300} s; mids come from our recorded WS stream. **Edge lost per second** = the OLS slope of decay on Δ over 0-5 s (bps/s), also expressed as a % of the mean leader gross round-trip move. Covers taken and rejected signals. |
| Latency breakdown (C6) | leader fill (exchange ts) → WS receive → decision → simulated ack. p50/p95/p99 per stage, clock-offset corrected. |
| Shadow mean R | mean R of rejected signals, simulated with the same exit rules (H3, reported only) |

---

## 5. Frozen pre-registration (D4)

### 5.1 Freeze

- **Frozen on 2026-09-29 in this v2 of the file, before any real result exists.** It covers:
  - this section
  - kill criteria (7)
  - the paper plan (8)
  - the evaluation keys in 9.2
  - **(A1.1)** the B0d construction, its cost model and its admissibility rules in 6.2, because P2c gates on them

  The PO's decisions it encodes are final [PO].
- **At the start of every paper run,** the engine writes a run record into the append-only ledger. The record holds:
  - the run number (1 or 2)
  - the start time (UTC)
  - the sha256 of this file
  - the sha256 of the frozen config
  - the CI level for that run
  - the bootstrap seed: 32 bytes from the OS CSPRNG, generated at run start and stored as hex. It seeds every random draw of the evaluation (A1.3 b). **(A2.7)** The RNG consumes the **32 raw bytes** decoded from that hex string, never the 64 hex characters as text.
  - **(A1.2, A2.2)** the engine's git commit (full 40-hex SHA) and a **dirty flag** computed over the **engine path set** (below). The flag is true if any tracked file in the engine path set differs from that commit, or any untracked file exists inside it. Files outside the set (`docs/**`, `research/**`, the ledger, the recordings) never make it dirty.
  - **(A1.2)** the sha256 of the dependency lockfile, and the Python version
  - **(A2.2)** the sha256 of the **installed-package list**: every distribution installed in the engine's Python environment, as `name==version` with the normalised lowercase name, one per line, sorted, UTF-8 with LF line ends (read with `importlib.metadata`). A package installed or upgraded outside the lockfile therefore changes it.
  - **(A2.2)** the sha256 of **every non-config data input**: each file the engine reads that is not the frozen config, the ledger, or our own recordings and snapshots (for example the macro calendar file). Each is listed by path with its own sha256.
- **(A1.2)** The engine refuses to write a run record, and so to start a run, when the dirty flag is true (fail closed). A run record with dirty = true makes the run ABORTED.
- **(A2.2) Engine path set.** The explicit list of paths the engine executes or reads, committed in the repository as a manifest that the PM's spec names: all engine source, the dependency lockfile, the frozen config file, and every non-config data input. `docs/**`, `research/**`, the ledger and the recording directories are never in it. A file the engine reads that is missing from the manifest is a bug; the backtest-auditor treats its discovery like a mid-run deploy (5.3).
- **(A2.2) Run worktree.** Each run executes from a **dedicated git worktree pinned to the run commit** (detached HEAD, for example `../wt-paper-run<r>`), used for nothing else. Docs commits, run-register appends and development happen in other checkouts, so they never touch the run worktree and are never a deploy. The engine refuses to start a run anywhere else.
- **Edits after run 1 starts** apply only if they are logged as a dated **addendum** before the next run starts. Past runs are always evaluated under the version hashed in their run record. Any other edit is a D4 violation, and the backtest-auditor must treat it as voiding the run.
- **Edits before run 1** also use a dated addendum that quotes the replaced text (A1 in 5.10 is the first). Run 1's record hashes the file with all addenda up to that moment.
- **(A1.4) P2c can't be removed, weakened or made non-gating by any addendum in this epic.** The nominal false-PASS rate of P2 under cross-day correlation depends on it (5.9). **(A2.4)** This binds A2 and every later addendum; section 14 states it for the PO.
- **(A1.3 h)** The run register is not kept in this file, so appending to it never changes the hash in a run record (5.4).

### 5.2 PO answers to the research questions (2026-09-29)

| Q | Question (v1, section 14) | PO answer | Encoded as |
|---|---|---|---|
| Q1 | USD P&L and risk-weighted mean R as co-conditions of PASS? | Net USD P&L > 0 is a PASS condition. **Also:** the trades must beat a direction-matched, random-time baseline, and the CI is clustered by UTC day. | P2b; P2c; the P2 method. Risk-weighted mean R has the same sign as USD P&L, so it stays reported (S2). |
| Q2 | R on max committed risk? | The gate uses R on **initial** risk. R on max committed risk is also reported. | P2 uses R; R_maxrisk reported; flag FR5 |
| Q3 | Single evaluation at N = 300 with a conservative CI? | The sample is the **first 300 opened trades**, evaluated **once, after all have closed**. | 5.3: sample S, `T_eval`, a single evaluation |
| Q4 | `risk_per_trade` 0.5% or 1%? | **0.5%** for paper; the ceiling stays 1%. | `risk.per_trade_fraction = 0.005` |
| Q5 | N < 300 at day 30? | **Extend to 60 days** with the same frozen config and **one evaluation**. | 5.3: sample window `[t0, t0 + 60 days)` |
| Q6 | Mirrored partial exit below $10? | **Skip and log.** If the remainder would fall below $10, **close all**. | `sizing.partial_below_min_action`, `sizing.close_all_if_remainder_below_min` |
| Q7 | Live wallet ≥ $300? | Paper wallet **$300**; live starts at **≥ $300**, never smaller than the paper-tested size. | 8; `paper.wallet_usd`, `live.min_wallet_usd` |
| Q8 | Paid S3 historical data? | **No.** | Data section: replay only from our own recordings |
| Q9 | Run `hl_sample.py` from the PO's PC? | **Yes, once**, after the fixes. | `scripts/README.md` |

**Other research-phase decisions encoded here [PO]:**
- at most **2 paper runs**
- a config change mid-run restarts the run and **counts as a run**
- the PO **sees trades and P&L** during the run
- follow at most 9 wallets
- crypto perps only (`allowed_dexes = core`), with HIP-3 data recorded
- market data recorded from day 1
- blackouts block entries and adds only, and trades around events count toward the sample
- degraded access means alert and pause entries
- funding is charged hourly
- delisting settlements count as normal trades
- no paid S3

### 5.3 The verdict rule (exact)

**Definitions**

| Term | Definition |
|---|---|
| Trade | One trader share, from our entry fill to fully closed [PO]. Rejected or skipped signals are never trades. |
| Run start `t0` | Timestamp of the run record (5.1) |
| Sample S | The **first 300 trades by entry-fill timestamp** opened in `[t0, t0 + 60 days)` [PO]. Ties are broken by client order ID, ascending. Trades opened after the 300th are traded normally but are outside S, and their statistics are reported separately. |
| `t300` | Entry-fill time of the 300th trade |
| **`T_eval`** | The moment the last trade in S closes, or `t300 + 7 days`, whichever comes first [QR, PO-ACK pending: section 14 item 4]. **(A2.1)** For a trade closed by `/flatten`, "closes" means its **shadow exit**, never the moment of the flatten. A trade in S still open at `t300 + 7 days` is marked for the gate at the recorded mid, minus taker fee and half-spread at that moment. It is flagged "marked" and keeps being managed normally. Its later real outcome is reported separately and never changes the verdict. **(A2.1)** A flattened trade whose shadow is still open at `t300 + 7 days` is marked the same way: the shadow is valued with that formula, and the marked shadow R is the shadow R in `min(realised R, shadow R)`. **(A1.3 f)** For a marked trade: `hold_i = T_eval − entry fill time`; funding counts through the last hourly funding at or before `T_eval`; R and R_maxrisk use the marked exit; its holding interval ends at `T_eval` for merged positions. |
| Evaluation window | `[t0, T_eval]`. P3, P4 and P5 apply to this window. |
| Day cluster | The UTC calendar day of the **first entry fill of the merged position** the trade belongs to. Every share of a merged position is therefore in one day cluster. G is the number of distinct day clusters in S. **(A1.3 c)** A merged position is a connected component (transitive closure) of the overlap graph over the trades in S with the same symbol and direction. Two trades are linked when their closed holding intervals `[entry fill, min(evaluation close, T_eval)]` intersect; touching at the same millisecond counts. **(A2.1)** The evaluation close is the full close, or the shadow exit for a flattened trade. If A overlaps B and B overlaps C, then A, B and C are one merged position even when A and C don't overlap. Trades outside S never link trades in S. |
| Run level `L_r` | Run 1: **L_1 = 96%** (two-sided α = 0.04). Run 2: **L_2 = 99%** (α = 0.01). See 5.4. [QR, PO-ACK pending: section 14 item 1] |
| `LB_r(x)` / `UB_r(x)` | For per-trade values x_i over S, the **minimum** of the lower bounds / **maximum** of the upper bounds of three two-sided CIs of the mean, at level `L_r` [QR, PO-ACK pending: section 14 item 2]: (a) the iid t-interval, n − 1 df; (b) a percentile cluster bootstrap resampling day clusters with replacement, B = 10,000, seed from the run record; (c) a cluster-robust t-interval, `V = G/(G−1) · Σ_g (Σ_{i∈g}(x_i − x̄))² / n²`, with G − 1 df. The exact bootstrap is fixed by A1.3 b below. |
| **Bootstrap, exact (A1.3 b)** | **Statistic:** the pooled trade mean of the resample, `Σ_{picked g} Σ_{i∈g} x_i / Σ_{picked g} n_g`, not the mean of cluster means. **Clusters:** indexed 0..G−1 in ascending UTC day. Resample r ∈ [0, B) picks G indices with replacement; pick j ∈ [0, G) is `rng_uint(seed, tag, (r, j), G)`. **RNG `rng_uint(seed, tag, counters, n)`:** for k = 0, 1, …, take the first 8 bytes (big-endian uint64 x) of `SHA-256(seed ‖ ASCII tag ‖ 0x00 ‖ each counter as uint32 big-endian ‖ k as uint32 big-endian)`. **(A2.7)** `seed` is the 32 raw bytes decoded from the run record's hex string (for the E14 test vector, the bytes whose hex is `0b233e78…d64a7cce`), never its ASCII hex text; an input that is not exactly 32 bytes is an error. Return `x mod n` for the first k with `x < ⌊2^64/n⌋·n` (rejection sampling, no modulo bias). Tags are `bootR` for R, `bootD` for D, and `b0d` for baseline draws. **Percentile index:** sort the B means ascending (0-based). `k = ⌊B·(100 − L%)/200⌋` in integer arithmetic. LB = element k, UB = element B − 1 − k. With B = 10,000 that is 200 / 9,799 at 96% and 50 / 9,949 at 99%. **Arithmetic:** R_i is the ledger's Decimal quantised to 1e-6, then converted to IEEE-754 binary64. Sums are accumulated in pick order. t quantiles are accurate to at least 1e-9. **Comparison:** LB_r and UB_r are rounded half-even to 1e-6 before `> 0` / `≤ 0`, so a rounded 0.000000 is not > 0. **Reference:** `scripts/eval_reference.py` implements this text and prints test vectors (E14, which supersedes E13 and asserts every printed vector against golden literals, A2.7). If the two disagree, this text wins. |

**At `T_eval`, the verdict is exactly one of:**

**PASS** requires all of the following:

| ID | Condition |
|---|---|
| P1 [PO] | S is complete: 300 trades opened before `t0 + 60 days` |
| P2 [PO + QR method] | `LB_r(R) > 0`, and G ≥ 5 [QR, PO-ACK pending: section 14 item 3]. Below 5 day clusters the cluster variance is degenerate; E10 shows the rule is conservative from G = 5. |
| P2b [PO] | Σ net USD P&L over S > 0 |
| P2c [PO + QR precision, PO-ACK pending: section 14 item 5] | `LB_r(D) > 0`, where `D_i = R_i − mean_R(B0d replications of trade i)` (6.2), computed on the same day clusters as P2. **(A1.3 g, A2.3 a)** A trade without an admissible B0d window gets `D_i = min(R_i, 0, R_i − B̄_i^partial)`, with `B̄_i^partial` defined in 6.2. If more than 10% of S (more than 30 trades) have no admissible window, P2c fails. **Non-removable (A1.4).** |
| P3 [PO] | Mark-to-market drawdown < 15% at every mark in the evaluation window |
| P4 [PO] | 0 missed exits in the evaluation window |
| P5 [PO] | Downtime < 2% of the evaluation window. Downtime is time when the engine could not open or manage positions (process down, a data gap before resync, the access-degraded pause) plus any manual `/pause`. Rule-based event blackouts are not downtime. |
| P6 [PO] | The point-in-time replay of `[t0, T_eval]`, run through the same engine on recorded data, has a mean R with the **same sign** as the paper mean R over S |

**FAIL** if any of the following holds:

| ID | Condition |
|---|---|
| F1 [PO] | P3 is breached at any time before `T_eval`. The verdict is immediate: the run ends and the bot pauses per the risk rules. |
| F2 [PO] | P4 is breached (a missed exit) at any time before `T_eval`. The verdict is immediate. |
| F3 | At `T_eval`, with G ≥ 5: `UB_r(R) ≤ 0` |

**INCONCLUSIVE** otherwise. That includes:
- fewer than 300 trades opened by `t0 + 60 days` (evaluate nothing; report descriptive statistics labelled "not a verdict")
- G < 5 (F3 is not evaluated; see the precedence below)
- `LB_r(R) ≤ 0 < UB_r(R)`
- P2 holds but any of P2b, P2c, P5 or P6 fails

**ABORTED** (counts as a run, never a PASS):
- a config change before `T_eval`, meaning any change to the frozen config hash [PO]
- a manual stop of the run by the PO
- a ruling by the backtest-auditor that a bug invalidated the run
- **(A1.2)** a mid-run deploy ruled ABORTED, or new engine code executed in the run before the auditor has ruled on it
- **(A1.2)** a run record with dirty = true

**Verdict precedence (A1.3 a).** Exactly one verdict applies. It is the first that matches in this order:
1. **ABORTED.** An ABORTED event happened before `T_eval` and before any F1/F2 breach; the run ends at that moment. Or the backtest-auditor voided the run. A voiding ruling overrides even a FAIL, but it can never produce a PASS, and the run still counts.
2. **FAIL by F1 or F2.** The breach happened before `T_eval`; the run ends at that moment.
3. **INCONCLUSIVE, P1 incomplete.** Fewer than 300 trades opened by `t0 + 60 days`.
4. **INCONCLUSIVE, G < 5.** F3 is not evaluated: with G − 1 < 4 df the cluster-robust interval is degenerate, and a FAIL from it would be as unreliable as a PASS. The three CIs are reported as descriptive only.
5. **FAIL by F3.** `UB_r(R) ≤ 0`.
6. **PASS.** P1 to P6, P2b and P2c all hold.
7. **INCONCLUSIVE.** Everything else.

`scripts/eval_reference.py::verdict` implements this order and asserts every adjacent pair (E13).

**Engine changes during a run (A1.2; replaces the v2 "bug fixes" paragraph).**
- **Deploy record.** Every process start during a run compares six things with the engine version currently in force for the run: the engine commit, the dirty flag (over the engine path set, 5.1), the lockfile hash, the Python version, the installed-package-list hash and the data-input hashes **(A2.2)**. Any difference is a **mid-run deploy**. The ledger gets a deploy record with:
  - the time
  - the old and new commit
  - the full `git diff <old>..<new>`, stored as a patch file with its sha256 in the ledger
  - the lockfile diff
  - the stated reason
- **No new code without a ruling (A2.2).** A deploy can't take effect in the run until the backtest-auditor has ruled on it and the ruling is in the ledger. Until then **only the recorded commit runs**, from the run worktree, for everything: entries, management of open positions, exits and safety actions, whether entries are paused or not. Pausing entries while waiting is allowed, and that time counts as downtime (P5). If the recorded commit can't manage open positions safely, the route is its own safety actions (kill switch, `/flatten`) or a manual stop of the run (ABORTED). Running the new code before the ruling makes the run ABORTED. Money safety comes first, the run second.
- **Rulings.** The auditor rules one of two ways:
  - **CONTINUE:** the ruling lists every trade whose decision, fill or R the change could affect. Those trades stay in S and are listed in the verdict report.
  - **ABORTED.**
- **ABORTED by default.** A change to signal, filter, scoring, sizing, exit, cost or fill logic is ruled ABORTED by default. This includes defaults hard-coded for those parts, data files they read and dependencies they call. The auditor may rule CONTINUE for such a change only if one test holds: replaying the run so far on recorded data through both commits gives identical decisions, fills and R for every trade.
- **Crash restarts.** A restart on the same commit, clean, with the same lockfile, config, **installed-package list and data inputs (A2.2)**, from the run worktree, and a continuous ledger is not a deploy and not a new run. Its downtime counts toward P5.

**`/flatten` inside S (A1.3 d).** `/flatten` (PIN-protected, through the risk gate) is a safety action and is always allowed.
- **Trades stay in S.** The trades it closes stay in S with exit reason `manual_flatten`.
- **Shadow outcome.** The engine keeps managing a **shadow** of each flattened trade on recorded data under the frozen exit rules, until its shadow exit. **(A2.1)** The shadow accrues hourly funding and follows the leader's recorded exits as the real trade would have. Over a gap in our recording, its SL/TP path uses exchange 1h candles, with the stop assumed hit first on an ambiguous bar (section 3).
- **(A2.1) The shadow exit is the trade's close for the evaluation.** `T_eval`, `hold_i`, the merged-position interval (day clusters), the B0d replications' hold and time exit, and P3's shadow equity all use the shadow exit, never the moment of the flatten. A shadow still open at `t300 + 7 days` is marked (`T_eval` row above). A flatten therefore can't end or shorten the evaluation, and choosing when to flatten changes nothing except `min(realised, shadow)`.
- **Gate R.** For the gate, a flattened trade counts with `min(realised R, shadow R)`, and its USD P&L with the same choice. Manual exits can therefore only hurt the verdict.
- **P3.** P3 is checked both on the actual marked equity and on the shadow equity, which has flattened trades replaced by their shadows. A breach on either is F1.
- **Entries after a flatten.** A flatten doesn't pause entries by itself; `/pause` time counts as downtime.
- **Reported:** the number of flattened trades and their realised-minus-shadow R.

**Also computed at `T_eval` and reported with every verdict** (go-live blockers in 5.6, not verdict changes):
- R_maxrisk
- S2, S3, S4, S6 (weekly mean R, A1.6)
- FR1 to FR6
- decay
- mirror fidelity
- the exit-reason mix, including `manual_flatten` and `marked`
- the B0d mean (the "direction + beta + fees and spread" component) and the number of trades with no admissible B0d window
- **(A1.4) cross-day diagnostics, not gating:**
  - the Kaplan–Meier median hold of S, with marked trades censored at `T_eval`
  - the share of trades in S whose holding interval crosses a UTC midnight
  - the P2 interval recomputed with **overlap-component clusters**: connected components of the overlap graph over all trades in S, any coin and any direction, with the same interval rule as A1.3 c. It uses all three CIs and reports G_ov. It is labelled "degenerate" if G_ov < 5.
  - A PASS whose overlap-component `LB_r(R)` is ≤ 0 is reported as "P2 fragile to cross-day correlation". That goes to the PO in the go-live review; it doesn't change the verdict.

### 5.4 Runs and the α split (BT-5)

- **At most 2 paper runs in this epic [PO].** Every run that starts counts, including one that ends ABORTED. There is no run 3.
- **α split:** run 1 is evaluated at L_1 = 96% (two-sided α₁ = 0.04) and run 2 at L_2 = 99% (α₂ = 0.01). Because α₁ + α₂ = 0.05:
  - the family-wise false-PASS probability across both runs is at most (0.04 + 0.01)/2 = **2.5% one-sided**, the same as one look at the PO's original 95% CI
  - α is front-loaded because run 2 only exists if run 1 did not PASS
  - the same levels apply to P2c
  - E6 section G gives the operating characteristics
- **After a FAIL:** a second run is allowed by the cap. My recommendation stays kill or redesign (K3). Any redesign must be written as a dated addendum before run 2 starts, and run 2 is evaluated at 99%.
- **After run 2 without a PASS,** the paper gate of this epic is closed. The recommendation is kill, or redesign as a **new epic** with a new pre-registration and data collected after it, disclosing both earlier runs.
- **Run register (A1.3 h):** every started, ended or aborted run, and every mid-run deploy with its ruling, gets a row in the **ledger's run register**, which is authoritative. It is mirrored for humans in `docs/sdlc/copytrade-v1/research/run-register.md`. Neither is part of this file, so appending a row never changes the hash in a run record. The row holds:
  - the run number, start and end time
  - the config hash, the file hash, and the engine commit with its dirty flag
  - the end reason and the verdict

  (v2 said "and in section 12 of this file"; that would have changed the hashed file.)

### 5.5 What is visible during a run (BT-5)

- **The PO sees trades, positions and USD P&L live**, plus the daily and weekly reports [PO].
- **The system does not compute or display interim mean R, CIs or a running verdict.** The gate statistics are computed once, at `T_eval`. Reports may show trade counts and the progress toward 300.
- **Interim numbers can't justify a config change.** A config change can still be made, but it ends the run as ABORTED and consumes it [PO].
- **Safety actions are always allowed:** the kill switch, `/pause`, `/flatten` and the drawdown pause. `/pause` time counts as downtime (P5). A `/flatten` can only hurt the gate (A1.3 d in 5.3).

### 5.6 Go-live blockers that don't change the verdict

Each item below is computed at `T_eval`. If any is triggered, a PASS **cannot proceed to any live step without a written PO review** of that item.

| ID | Check | Triggered when |
|---|---|---|
| K9 / S4 | Top-9-by-raw-ROI baseline (B1) | Our mean R ≤ B1's mean R over its trades opened in `[t0, T_eval]`. A P2c failure also fires K9, but that already prevents PASS. |
| FR1 | Top-trade concentration | Mean R over S without its 5 highest-R trades ≤ 0 |
| FR2 | Leader concentration | Mean R over S without the trades of the leader with the largest total R ≤ 0 |
| FR3 | **Cost-fragile** (BT-13) | `mean_i(R_i − c_i) ≤ 0`, that is, mean R with all modelled costs doubled |
| FR4 | Short-volatility profile (S5) | Win rate > 70% **and** payoff ratio < 0.5 |
| FR5 | Add-inflated R | Mean R_maxrisk ≤ 0 |
| **FR6 (A1.6)** | One-regime profit | Mean R over S without the trades of its **best UTC-day cluster** ≤ 0. The best cluster has the largest Σ R_i; a tie goes to the earliest day. |
| D6 | Paper vs replay divergence | Any tolerance in 8.2 exceeded. This blocks any live step outright (D6). |

FR6 operating characteristics (E11) [EXPL]:
- **Homogeneous edge:** given a frozen-P2 pass at +0.10R or +0.15R, FR6 fired in 0 of the passing runs in every cell. That covers 8, 21 and 30 days, with and without a day factor, with upper 95% bounds of 0.4-3.6%. It costs essentially no power.
- **Detection is not simulated:** E11 did not model a profit concentrated in one day. FR6 is a coarse guard, like FR1 and FR2.

### 5.7 Reported secondary statistics (never gating)

| ID | Statistic |
|---|---|
| S2 | Risk-weighted mean R. It has the same sign as P2b. |
| S3 | B0: random entry, random direction, matched frequency and holding time; our mean R vs its 95th percentile |
| S4 | B1: top 9 by raw ROI (feeds K9) |
| S5 | Win rate and payoff ratio (feeds FR4) |
| **S6 (A1.6)** | **Weekly mean R:** per 7-day block `[t0 + 7k days, t0 + 7(k+1) days)`, by entry-fill time, over the trades in S. It reports n, mean R, Σ net USD, and the share of S. The last block is partial and is labelled as such. |
| – | R_maxrisk, decay, latency, mirror fidelity, exit mix, B0b, B2, B3, B4 (6.2) |

### 5.8 Variant budget (D4)

- **Paper:** exactly 1 frozen configuration per run, and at most 2 runs (5.4).
- **Pre-paper replay:** at most **8** declared variants. The count is reported with any result.

| ID | Variant |
|---|---|
| V0 | Defaults from section 9 |
| V1 | All filters off (the raw copy of the selected traders) |
| V2 | Equal score weights |
| V3 | Stop 1.5×ATR |
| V4 | Stop 3×ATR |
| V5 | No TP (exit on our SL or the trader's exit only) |
| V6 | Join rank 5 / drop rank 9 |
| V7 | Minimum median hold 60 min |

- **Selection rule:** V0 is kept unless another variant beats it by more than one replay CI half-width. Otherwise the selection is noise.
- **Sensitivity runs** use the chosen variant only and don't count as variants:
  - costs ×1.5 and ×2
  - delays of 1, 3 and 5 s

### 5.9 Operating characteristics of the frozen rule [EXPL, synthetic]

These come from E5 (`feasibility_mc.py` v2, seed 17), E6 (`gate_power.py` v2, seed 23) and E10 (`few_clusters.py`, seed 31). They describe the rule, not the strategy.

| Property | Value | Source |
|---|---|---|
| False PASS at zero edge, run 1 (P2 only), no beta | 1.3% [1.0, 1.7] (nominal one-sided 2%) | E6 D2 |
| False PASS at zero edge, day-factor corr 0.5, 80% long: naive t / v1 rule / frozen P2 / frozen P2 + P2c | 13.3% / 8.0% / 1.2% / **0.1%** | E6 D2 (BT-4, BT-7) |
| Family-wise false PASS across 2 runs (96% then 99%) vs 2 runs at 95% | **1.6%** [1.3, 2.0] vs 3.2% [2.7, 3.8] | E6 G |
| Power at +0.10R, independent trades, 96% / 99% | 43% / 24% (realised SD 0.86R); 30% / 13% (realised SD 1.05R) | E6 B |
| Power at +0.10R with merged positions, no beta: naive t / frozen P2 / frozen P2 + P2c | 41% / 22% / 20%. With day-factor corr 0.3 and 80% long: 43% / 13% / **5.6%** | E6 D2 |
| **Joint P(PASS) in run 1 at a true +0.10R** (reach 300, no 15% DD, USD > 0, LB > 0) | base 0.29, base with correlation 0.24, optimistic 0.22, 3-5 traders 0.14, pessimistic 0.01. These are **upper bounds**: the bootstrap component, P2c, P6 and real costs are not modelled. | E5 (BT-6) |
| Joint P(PASS) at zero edge | 0.001-0.015 across scenarios (A1.7; v2 said 0.004-0.015) | E5 |
| Power at +0.10R when the 300 trades fall on 5 / 8 / 10 / 15 days (no beta) | 13 / 16 / 17 / 19% (frozen P2 at 96%). False PASS stays ≤ 1.6%. | E10 |
| **(A1.4) Frozen P2 alone, continuous market factor, holds crossing UTC days**, zero edge | **Under-covers:** 1.7% (4h median hold), 2.5-3.2% (12h), 3.9% (24h), against the nominal one-sided 2%. P2 + P2c: ≤ 0.8%, and ≤ 1.3% with a trend. | backtest-audit-r2 BT2-4 (the auditor's simulation; not reproduced here) |
| **(A1.1) P2 + P2c at zero net timing value in a trending month**, run 1: corrected B0d cost vs the superseded v2 wording (B0d also charged the copy's delay cost of 0.05R / 0.10R). Day-factor corr 0.3 / 0.5, 80% long, factor trend 0 / +0.25 / +0.50, so beta-only mean copy R is 0 to +0.21R | Corrected: **0.1-0.5%**. Superseded: 0.3-1.8% at 0.05R and 0.8-6.4% at 0.10R. The inflation grows with the trend and the delay cost. The auditor's model gave larger inflation, 2.9-4.7% and 11.6-14.4%. The direction agrees; the size depends on the model. | E11 |
| **(A2.5) Power at +0.10R with merged positions, run 2** (frozen P2 at 99%), **before P2c** | No beta **8.6%**. Day-factor corr 0.2 / 0.3 / 0.5 with 70-80% long: **6.4 / 4.4 / 2.7%**. P2c at 99% was not simulated; it can only lower these. (v2 + A1 section 14 quoted the iid 13-24%, 2-4× too high: BT3-5.) | E6 D2 (`frozen99`) |

**Reading:**
- A real +0.10R edge passes run 1 **at best about 1 time in 3**. With few leaders, or leaders who rarely trade, it almost never does.
- The price of the honest rule is lower power. The day clusters make the effective sample the number of trading days, not 300 trades. At the synthetic median that is about 8 days (optimistic), 21 days (base) or 43 days (3-5 traders).
- **The joint figures from E5 are upper bounds.** They omit the day bootstrap, P2c and P6. E6 D2 shows what those cost relative to the frozen P2 alone:
  - about 10% of the power with no beta (22% falls to 20%)
  - about 60-70% of the power when copy R carries a strong daily market factor (13% falls to 5.6%, and 10% to 2.9%)

  If our copies are mostly beta, a modest edge is essentially undetectable in one run. That is the intended protection (BT-7), and it means a PASS needs a large edge.
- **(A1.4) The nominal false-PASS guarantee rests on P2c, not on P2 alone.**
  - Day clusters assume a trade's market risk sits in its entry day.
  - When holds cross UTC midnight and the market factor is continuous, trades on adjacent days share risk. Then frozen P2 alone is anti-conservative: up to 3.9% against the nominal 2% at 24h holds.
  - P2c removes the shared factor and brings the conjunction back to ≤ 0.8-1.3%. That is why P2c is non-removable (5.1).
  - The cross-day diagnostics at `T_eval` (5.3) show how exposed a given run is.
- **(A1.1) With the corrected B0d cost,** P2c tests net timing value after our delay, not the leader's gross timing (6.2). In E11 the corrected rule keeps P2 + P2c at 0.1-0.5% when the copy's net timing value is zero, even in a trending month.
- **INCONCLUSIVE is the most likely honest outcome** of a run with a modest real edge.
- **(A2.7) B0d in the simulations.** In E6 D2, E10 and E11, each trade's B0d mean comes from k = 20 synthetic replications, not the frozen 1,000 (`gate_power.baseline_means`). That adds noise of SD ≈ 1.2/√20 ≈ 0.27R to each B̄_i (0.04R at 1,000). The noise is mostly independent across trades and enters the estimated variance of D, so it mainly lowers P2c power: the P2 + P2c power figures are slightly pessimistic, and the false-PASS figures are little affected.

### 5.10 Addendum A1 (dated 2026-09-29, before run 1)

**Context:**
- Written after backtest-audit round 2 (`backtest-audit-r2.md`, verdict INCONCLUSIVE).
- Written before any paper run started and before any real-data result. The run register is empty, and 0 strategy variants have been tried on real data.
- No number in A1 was chosen after seeing strategy performance: none exists.

**What it amends:** each item below quotes the v2 text it replaces. The amended text is in place where marked `(A1.n)`. **(A2.6)** Some rows describe the replaced v2 text instead of quoting it (BT3-6). The authoritative v2 text is this file at commit `1eba7c6`, sha256 `36e35a032a6792a6182903e34872d7d0370118647b5789595e4e366e68a26fb1` (check: `git show 1eba7c6:docs/sdlc/copytrade-v1/research/edge-hypothesis.md | sha256sum`).

| Item | Finding | v2 text replaced | Amended rule (where) |
|---|---|---|---|
| **A1.1** | BT2-1 (BLOCKING) | 6.2 B0d: "the same cost model (recorded spread at that time, taker fees, delay slippage from measured decay)"; rationale "Because B0d carries the same costs, P2c is **easier** than P2 when there is no beta" | B0d pays taker fees on both legs, plus the spread and book impact recorded at **its own** entry and exit fill times, plus the ack-delay drift at its own random decision times (≈ 0, measured, not assumed), plus hourly funding. It **never** pays post-signal decay: no `decay(Δ)` term, no slippage against a leader fill, no second delay term at exit. Rationale rewritten (6.2). Evaluation test 10 (10.8). |
| **A1.2** | BT2-2 (BLOCKING) | 5.1 run-record list (no engine version); 5.3 "Bug fixes that don't change the config hash are logged, the run continues, and the affected trades stay in S." | The run record adds the engine commit, a dirty flag, the lockfile hash and the Python version. A dirty tree can't start a run. Every mid-run deploy is logged with its full diff and needs a backtest-auditor ruling (CONTINUE with the affected trades listed, or ABORTED) before its code runs in the run. Changes to signal, filter, scoring, sizing, exit, cost or fill logic are ABORTED by default. (5.1, 5.3, 8.1; evaluation test 11) |
| **A1.3** | BT2-3 | 5.3 left these open: precedence between "G < 5 is INCONCLUSIVE" and F3; the bootstrap statistic, index and RNG; transitivity; `/flatten`; B0d without a window; hold for marked trades. 5.4 put the register in "section 12 of this file". | (a) Verdict precedence list (5.3). (b) Exact bootstrap: statistic, index, SHA-256 counter RNG, rounding (5.3). (c) Transitive merged positions (5.3). (d) `/flatten` counts `min(realised, shadow)` (5.3). (f) Marked-trade hold and funding (5.3). (g) B0d admissible windows, delistings, and missing windows (6.2, P2c). (h) Register in the ledger and `run-register.md` (5.4). Reference implementation with test vectors: `scripts/eval_reference.py` (E13). Evaluation tests 12-18. |
| **A1.4** | BT2-4 | (none; additions) | The under-coverage of P2 alone is stated (5.9). P2c is non-removable (5.1). Non-gating cross-day diagnostics at `T_eval` (5.3). Evaluation test 20. |
| **A1.5** | BT2-5 | 9.2 `eval.ci_level_run1/run2` basis "PO (α split) + QR (split)" | Basis relabelled "QR, PO-ACK pending". Five items need the PO's written acknowledgement before run 1 (section 14). The CTO records the answer in `decisions.md`; D11 there still says 95%. **(A2.5) Correction:** D11 states no level ("CI lower bound > 0"); the 95% is in `01-brief.md:27,127`. |
| **A1.6** | BT2-8 | (none; additions) | FR6, a go-live blocker: mean R without the best UTC-day cluster ≤ 0 (5.6). S6: weekly mean R (5.7). Evaluation test 19. |
| **A1.7** | BT2-9 | 5.9 "0.004-0.015"; section 12 E6 doubled backticks; `gate_power.py` docstring "section 5.0" | 0.001-0.015; the backticks fixed; "section 5.3". The docstring-only change leaves the output byte-identical (E6 row). |

**Not frozen, logged for completeness:**
- `hl_sample.py` v2.1 (BT2-6, BT2-7). See section 12, E12.
- Four new or changed files under `scripts/`, with their sha256 in section 12.

**What A1 costs the verdict:**
- **A1.1 makes P2c harder:** B0d no longer carries the copy's delay cost. When our delay eats most of the leader's timing edge, P2c now fails, as it should.
- **A1.3 d and g can only lower `LB_r(D)` and `LB_r(R)`.**
- **Nothing in A1 makes a PASS easier.**

### 5.11 Addendum A2 (dated 2026-09-29, before run 1)

**Context:**
- Written after backtest-audit round 3 (`backtest-audit-r3.md`, verdict VALID, seven ADVISORY findings BT3-1 to BT3-7).
- Written before any paper run started and before any real-data result. The run register is empty, and 0 strategy variants have been tried on real data.
- No number in A2 was chosen after seeing strategy performance: none exists. The only new numbers are power figures read from the existing E6 output (`research/data/gate_power_seed23.txt`, unchanged) and the golden values of the reference implementation.

**Versions it amends (A2.6):**
- **v2:** this file at commit `1eba7c6`, sha256 `36e35a032a6792a6182903e34872d7d0370118647b5789595e4e366e68a26fb1`.
- **v2 + A1:** this file at commit `75f1fbf` (unchanged at `ce672a7`), sha256 `ce3255e8cbf9b3670874464caa57e7afa530b4c74a38cc6e8faee39dfdf75515`. All quotes below are from this version.
- The sha256 of v2 + A1 + A2 is not written here, because writing it would change it. Run 1's record stores it (5.1).

**Rule followed (5.1):** every replaced text is quoted verbatim below. The amended text is in place, marked `(A2.n)`. Pure additions are listed by location without a quote.

| Item | Finding | Change (where) |
|---|---|---|
| **A2.1** | BT3-1 | A flattened trade's close for the evaluation is its **shadow exit**, for `T_eval`, `hold_i`, merged-position intervals, the B0d hold and P3's shadow equity. A shadow still open at `t300 + 7 days` is marked. (5.3 `T_eval`, day cluster, `/flatten`; 6.2 B0d; 9.2; tests 2 and 15; `eval_reference.py`) |
| **A2.2** | BT3-2 | The **engine path set** (a committed manifest: code, lockfile, config, non-config data inputs) scopes the dirty flag. Each run executes from a **dedicated worktree pinned to the run commit**. Only the recorded commit runs until a ruling, paused or not. The run record adds the sha256 of the installed-package list and of every non-config data input, and deploy detection compares six things. (5.1, 5.3, 8.1, 9.2, test 11, `run-register.md`) |
| **A2.3** | BT3-3 | (a) `D_i = min(R_i, 0, R_i − B̄_i^partial)` for a trade without an admissible window, with a three-step `B̄_i^partial`. The false claim "gaps can't help a run pass" is corrected. The recorder gap rate from the pre-paper dry run is reported before run 1. (b) B0d R is computed from fill prices; drift and spread are a reported decomposition, never added. (5.3 P2c, 6.2, 6.3, 8.1, 9.2, tests 10 and 16) |
| **A2.4** | BT3-4 | Section 14: items 6-8 added, plus a note that A1.4 binds future addenda. Every item gets plain-language wording and an "if you say no" consequence. The header, 8.1 and C14 say eight items. |
| **A2.5** | BT3-5 | Item 1's run-2 power is ≈ 9% (no beta) and ≈ 3-6% (beta), before P2c, not 13-24%. The 95% is cited from `01-brief.md:27,127`, not D11. (14, 13 C14, 9.2, new 5.9 row, A1.5 row) |
| **A2.6** | BT3-6 | v2 recorded as commit `1eba7c6` with its sha256 (5.10 and above). Every A2 replacement is quoted verbatim below. |
| **A2.7** | BT3-7 | `eval_reference.py` v2: labels fixed, golden asserts for every printed vector, new discriminating vectors, 10-mutant check (E14). The seed is the 32 raw bytes (5.1, 5.3, 9.2, test 13). k = 20 B0d replications disclosed for E11, and for E6 D2 and E10 (5.9, section 12, `b0d_cost_fr6.py` v1.0.1 docstring). |

**The E6 figures behind A2.5** (`gate_power_seed23.txt`, section D2, true mean +0.10R, merged positions):

| Setting | Frozen P2 at 96% (run 1) | Frozen P2 + P2c at 96% (run 1) | Frozen P2 at 99% (run 2) |
|---|---|---|---|
| No beta (corr 0, 50% long) | 22.1% | 20.1% | **8.6%** |
| Day-factor corr 0.2, 70% long | 17.3% | 12.5% | **6.4%** |
| Day-factor corr 0.3, 80% long | 13.1% | 5.6% | **4.4%** |
| Day-factor corr 0.5, 80% long | 9.6% | 2.9% | **2.7%** |

P2 + P2c at 99% was not simulated. P2c can only lower the run-2 column.

**Replaced text, verbatim (A2.6).** Each block is the exact v2 + A1 text that A2 replaced, in file order. The new text is in place at the named location, marked `(A2.n)`.

1. **A2, header, version line.** Replaced:

```text
Version: **v2 + Addendum A1** (A1 dated 2026-09-29, written before run 1 and before any real result).
```

2. **A2.4, header, run-1 precondition.** Replaced:

```text
- **Run 1 must not start until the PO has acknowledged the five items in section 14** (pending PO acknowledgement, BT2-5).
```

3. **A2.2, 5.1, run record, engine commit and dirty flag.** Replaced:

```text
  - **(A1.2)** the engine's git commit (full 40-hex SHA) and a **dirty flag**. The flag is true if any tracked file differs from that commit, or any untracked file exists outside the ledger and recording directories.
```

4. **A2.1, 5.3, `T_eval` definition.** Replaced:

```text
| **`T_eval`** | The moment the last trade in S closes, or `t300 + 7 days`, whichever comes first [QR, PO-ACK pending: section 14 item 4]. A trade in S still open at `t300 + 7 days` is marked for the gate at the recorded mid, minus taker fee and half-spread at that moment.
```

5. **A2.1, 5.3, day cluster, link rule.** Replaced:

```text
Two trades are linked when their closed holding intervals `[entry fill, min(full close, T_eval)]` intersect; touching at the same millisecond counts.
```

6. **A2.7, 5.3, bootstrap, reference.** Replaced:

```text
**Reference:** `scripts/eval_reference.py` implements this text and prints test vectors (E13). If the two disagree, this text wins.
```

7. **A2.3, 5.3, P2c.** Replaced:

```text
**(A1.3 g)** A trade without an admissible B0d window gets `D_i = min(R_i, 0)`.
```

8. **A2.2, 5.3, engine changes, deploy record.** Replaced:

```text
- **Deploy record.** Every process start during a run compares four things with the engine version currently in force for the run: the engine commit, the dirty flag, the lockfile hash and the Python version. Any difference is a **mid-run deploy**.
```

9. **A2.2, 5.3, engine changes, no new code without a ruling.** Replaced:

```text
- **No new code without a ruling.** A deploy can't take effect in the run until the backtest-auditor has ruled on it and the ruling is in the ledger. Until then the engine keeps running the recorded commit. Or entries are paused (`/pause`, with open positions still managed) and that time counts as downtime (P5).
```

10. **A2.2, 5.3, engine changes, crash restarts.** Replaced:

```text
- **Crash restarts.** A restart on the same commit, clean, with the same lockfile, config and a continuous ledger is not a deploy and not a new run.
```

11. **A2.1, 6.2, B0d, hold_i.** Replaced:

```text
where hold_i is trade i's actual holding time (for a marked trade, `T_eval − entry`).
```

12. **A2.3, 6.2, B0d, costs.** Replaced:

```text
hourly funding from actual rates. **No post-signal decay:**
```

13. **A2.3, 6.2, missing window.** Replaced:

```text
- **Missing window.** If the admissible set for trade i totals less than 24 hours of start times (or is empty), trade i has no admissible B0d window. It gets `D_i = min(R_i, 0)`: it can count against P2c, never for it.
  - The count is reported.
  - If it exceeds 10% of S, P2c fails (5.3).
  - Gaps in our own recording therefore can't help a run pass.
```

14. **A2.2, 8.1, frozen engine.** Replaced:

```text
- **Frozen engine (A1.2):** the run starts from a clean commit.
```

15. **A2.4, 8.1, precondition.** Replaced:

```text
- **Precondition (BT2-5):** the PO's acknowledgement of the five section-14 items is recorded in `decisions.md`.
```

16. **A2.5, 9.2, `eval.ci_level_run1` / `eval.ci_level_run2` basis.** Replaced:

```text
The PO's decision was ≤ 2 runs and, in D11, a 95% CI.
```

17. **A2.7, 9.2, `eval.bootstrap_seed`.** Replaced:

```text
| `eval.bootstrap_b` / `eval.bootstrap_seed` | 10000 / 32 CSPRNG bytes generated at run start, stored as hex |
```

18. **A2.1, 9.2, `eval.flatten_gate_rule`.** Replaced:

```text
| `eval.flatten_gate_rule` | `min_realised_shadow` | enum | QR (A1.3 d) | FROZEN |
```

19. **A2.3, 9.2, `baseline.dm_costs`.** Replaced:

```text
| `baseline.dm_costs` | fees + own-time spread and impact + own ack drift + funding; **no decay** | | QR (A1.1) | FROZEN |
```

20. **A2.1, 10.8, test 2.** Replaced:

```text
2. `T_eval` = min(last close in S, `t300` + 7 days). Trades still open are marked as specified.
```

21. **A2.2, 10.8, test 11, fourth bullet.** Replaced:

```text
    - A process start on a different commit or lockfile writes a deploy record with the stored diff and its sha256. The new code does not run inside the run until a ruling is in the ledger; until then the engine runs the recorded commit, or entries are paused and that time counts as downtime.
```

22. **A2.7, 10.8, test 13.** Replaced:

```text
13. **(A1.3 b) Bootstrap reproducibility.** For the seed and toy sample in `research/data/eval_reference_vectors.txt` (E13), the implementation reproduces all of these to 1e-6:
```

23. **A2.7, 10.8, test 14.** Replaced:

```text
14. **(A1.3 c) Transitive merged positions.** The E13 vector must be reproduced:
```

24. **A2.1, 10.8, test 15.** Replaced:

```text
15. **(A1.3 d) `/flatten`.** Flattened trades stay in S. Their gate R and USD are the worse of realised and shadow. P3 is checked on both equity curves. A flatten that improved realised R never raises `LB_r`.
```

25. **A2.3, 10.8, test 16.** Replaced:

```text
    - A trade with less than 24 h of admissible starts gets `D_i = min(R_i, 0)`.
```

26. **A2.7, 12, E6 row.** Replaced:

```text
| 5.9 and the key numbers below. Runtime 7 min 46 s wall time on 3 processes.
```

27. **A2.7, 12, E11 row, description.** Replaced:

```text
| E11 | `b0d_cost_fr6.py` (seed 41 inside the script; 2,000 sims, B = 1,000 per cell; 2 processes).
```

28. **A2.7, 12, E11 row, script hash.** Replaced:

```text
| `f0253d92ed29b4d38ce1256741acef126c1a9ef46db2d4fd13901ddc53c20853` | `research/data/b0d_cost_fr6_seed41.txt`
```

29. **A2.7, 12, E11 row, result.** Replaced:

```text
Runtime 1 min 49 s. Run once, with no smoke run before it. | no: a check of the rule, not of the strategy |
```

30. **A2.7, 12, E13 row.** Replaced:

```text
| E13 | `eval_reference.py` (reference implementation of A1.3; test vectors) |
```

31. **A2.5, 13, C14.** Replaced:

```text
| C14 (round 2) | The five precision choices in section 14 were never signed by the PO. Together they roughly halve power: at +0.10R with merged positions, run 1 is 20% against 41% for a naive 95% t, and run 2 is 13-24%. | **Pending PO acknowledgement** (section 14) |
```

32. **A2.4, A2.5, section 14 (whole section).** Replaced:

```text
## 14. Items pending PO acknowledgement (BT2-5)

Q1-Q9 are answered and encoded in 5.2. The five items below were research choices. They interpret or tighten PO decisions, and the PO has not yet signed them.

- **Status of each:** pending PO acknowledgement.
- **Who records the answer:** the CTO, in `docs/product/decisions.md`. D11 there still says 95%.
- **Precondition:** run 1 must not start until all five are acknowledged or replaced (8.1).
- **If the PO rejects an item:** it is changed by a further dated addendum before run 1. The consequence for the false-PASS rate or power is stated next to each item.

| # | Item (exact wording for the PO) | What it replaces or interprets | If the PO says no |
|---|---|---|---|
| 1 | **CI levels 96% then 99%.** Run 1 is judged at a 96% confidence level, and run 2 (if there is one) at 99%, instead of 95% for each run. This keeps the chance that a strategy with no edge passes in either run at 2.5% or less (simulated 1.6%). That is the same as one look at your original 95%. The price is power: a real +0.10R edge passes run 1 about 20% of the time with merged positions, and run 2 about 13-24%. **Status: pending PO acknowledgement.** | D11, "CI lower bound > 0" at 95%, plus the PO's "at most 2 runs" | Two runs at 95% each: family-wise false PASS 3.2% [2.7, 3.8] instead of 1.6% (E6 G) |
| 2 | **The most pessimistic of three confidence intervals.** The lower bound we test is the lowest of three methods: a plain t-interval, a bootstrap that resamples whole UTC days, and a day-clustered t-interval. The upper bound is the highest of the three. Each method alone can be too optimistic in some situations (for example, the day bootstrap with few days). Taking the most pessimistic keeps the false-PASS rate at or below target. **Status: pending PO acknowledgement.** | The PO's "day-clustered CI" (method not specified) | Any single method: false PASS up to 6.4% at 5 days (bootstrap alone, E10) |
| 3 | **At least 5 different trading days.** A PASS needs the 300 trades to fall on at least 5 different UTC days (day clusters). With fewer, the verdict is INCONCLUSIVE: never PASS, and never FAIL by the confidence interval. **Status: pending PO acknowledgement.** | Not covered by a PO decision | No minimum: the clustered interval is degenerate below 5 days, and a verdict there is unreliable in both directions |
| 4 | **7-day close-out cap with marking.** You decided "evaluated once, after all 300 have closed". We propose to evaluate when the last of the 300 closes **or 7 days after the 300th opened, whichever comes first**. Any of the 300 still open then is valued for the verdict at the market mid minus exit fee and half-spread. It keeps being managed normally, and its real outcome is reported separately. Without a cap, one long-held position could delay the verdict without limit. **Status: pending PO acknowledgement.** | "Evaluated once, after all have closed" | No cap: the verdict waits for the last close, however long that takes |
| 5 | **"Beating the baseline" means its lower bound is above zero.** "Beating the direction-matched random-time baseline" is read as: the lower end of the 96% (run 1) or 99% (run 2) interval of our per-trade advantage over the baseline must be above zero. It is not enough for our average to beat the baseline's average. A copy that only rides the market's direction beats the baseline's average about half the time by luck. Under the lower-bound reading, such a copy passed the full gate in at most about 1 run in 200 in our simulations (0.1-0.5%, E11). The baseline pays the same fees and spread as us, but not our copy delay (A1.1). **Status: pending PO acknowledgement.** | The PO's "beating a direction-matched baseline" | Point comparison: a beta-only copy passes P2c about 50% of the time |
```

**Additions (no v2 + A1 text removed):**
- A2: header, inputs
- A2.7: 5.1, run record, bootstrap seed
- A2.2: 5.1, run record, environment hashes
- A2.2: 5.1, engine path set and run worktree
- A2.4: 5.1, A1.4 binds A2 and later addenda
- A2.7: 5.3, bootstrap, RNG seed
- A2.1: 5.3, `/flatten`, shadow
- A2.5: 5.9, operating characteristics table (new row)
- A2.7: 5.9, reading (new bullet)
- A2.6: 5.10, what A1 amends
- A2.5: 5.10, row A1.5
- A2.3: 6.3, random-time baselines
- A2.2: 9.2, new keys after `eval.require_clean_engine_tree`
- A2.3: 9.2, new key after `baseline.dm_max_missing_share`
- A2.3: 10.8, test 10 (new bullet)
- A2.2: 10.8, test 11 (new bullets)
- A2.7: 10.8, test 13 (new bullets)
- A2.7: 12, E10 row
- A2.7: 12, E14 row (new)
- A2: 15, round-3 closure table (new)
- A2.7: 12, a stray blank line between the E10 and E11 rows removed, so rows E11-E14 render inside the table (formatting only; no text removed)

**Outside this file (not hashed in the run record):** `run-register.md` gains columns for the run worktree, the installed-package-list sha256 and the data-inputs sha256, and two rule bullets: only the recorded commit runs until a ruling, and register appends are never a deploy (A2.2). Its replaced header line:

```text
| Run | Start (UTC) | End (UTC) | edge-hypothesis.md sha256 | Config sha256 | Engine commit | Dirty | CI level | End reason | Verdict |
```

**Not frozen, logged for completeness:**
- `scripts/eval_reference.py` v2 and `scripts/b0d_cost_fr6.py` v1.0.1, with their sha256 in section 12 (E14, E11). `scripts/README.md` describes E14.
- `research/data/eval_reference_vectors.txt` was regenerated (E14). `research/data/b0d_cost_fr6_seed41.txt` is byte-identical after the re-run.

**What A2 costs the verdict:**
- **A2.1 removes a PO-controlled stopping time.** The shadow exit is at or after the flatten. So `T_eval` can only stay the same or move later, merged positions can only grow, and the flatten time affects nothing except `min(realised, shadow)`.
  - One side effect goes the other way, stated for honesty: a longer evaluation window slightly lowers the downtime fraction in P5.
- **A2.2 is stricter.** More things count as a deploy, and new code can't run before a ruling in any mode.
- **A2.3 (a) can only lower `D_i`,** so it can only lower `LB_r(D)`.
- **A2.3 (b) removes a reading that made P2c easier.** Under that reading, B0d could pay its drift and spread twice, which lowers B̄ and raises D.
- **A2.4, A2.5 and A2.6 change no rule.** A2.7 changes no rule either: it pins the seed encoding that "32 bytes" already implied, and adds tests.
- **Nothing else in A2 makes a PASS easier.** P2c keeps its gating status (A1.4).

---

## 6. Validation protocol (D5)

### 6.1 Stages, in order

1. **Indicative replay.** It runs before our own recording exists, over the historical fills of today's candidates. It is survivorship-biased and labelled indicative only. It is used only for kill checks (K1), never as evidence of an edge. `hl_sample.py` belongs here.
2. **Point-in-time replay.** It covers the window from our day-1 snapshots to the start of the paper run, using:
   - the same engine
   - the stored snapshots
   - the recorded books

   This is the pre-paper out-of-sample test and the only place variants are compared (5.8).
3. **Paper run(s).** A forward, true out-of-sample test with a frozen configuration, at most 2 runs (5.4).
4. **Walk-forward inside replays.** The score at cycle t is computed from data ≤ t only, and trades after t form the out-of-sample fold. There is no in-sample fit: weights and gates are priors. The only fitting is the variant choice in 5.8.

### 6.2 Baselines

Every baseline runs through the same engine, risk limits, cost model and window.

| ID | Baseline | Construction | Role |
|---|---|---|---|
| **B0d** | **Direction-matched, random-time [PO]** | For each trade i in S: same coin and **same direction**. The decision time t is drawn uniformly from the **admissible** part of `[t0, T_eval − hold_i]` (A1.3 g below), where hold_i = `min(evaluation close, T_eval) − entry fill`: trade i's actual holding time, its shadow's for a flattened trade (A2.1), and `T_eval − entry` for a marked trade or marked shadow. It uses the same risk per trade, and our ATR stop and TP computed from 1h candles closed before t. **Costs (A1.1):** taker fees on both legs; the spread and book impact from walking **the book recorded at the replication's own fill times** (t + `paper_ack_delay_ms` at entry; trigger or time exit + ack delay at exit) with the replication's own size; the mid drift between its own decision and fill times (the ack-delay drift at a random time, ≈ 0 in expectation, measured, not assumed); hourly funding from actual rates. **(A2.3 b) R from fill prices:** a replication's R is computed from its simulated entry and exit fill prices (the book walks above), its fees and its funding, exactly like a paper trade. The ack-delay drift (mid at fill − mid at decision) and the spread and impact (fill − mid at fill) are a **reported decomposition** of those fill prices against the decision-time mid; they are never added to R a second time. **No post-signal decay:** no `decay(Δ)`, no slippage against any leader fill, no second delay term at exit. Exit at our SL/TP (trigger on mark, fill at book + ack delay) or at hold_i, whichever comes first. For a marked trade, the replications' time exit uses the same marking formula (mid − taker fee − half-spread). **1,000 replications** per trade. Draws use `rng_uint` with tag `b0d` and counters (trade index in S, replication), over the admissible set in ms (`eval_reference.py::b0d_start`). The replications are per trade and ignore portfolio state (concurrency, loss halts). `B̄_i` = the mean R over the replications. | **Gating: P2c** on `D_i = R_i − B̄_i`. It removes the direction-profile, beta, regime, fee and spread components shared with random timing. What is left is our **net** timing value after our own delay (see below). |
| B0 | Random entry, random direction | Same coin, uniformly random entry time within the same UTC week, random direction, same holding time and sizing rules. 1,000 replications. | Reported (S3) |
| B0b | Random direction at the same time | Same coin and entry time as the real trade, direction flipped by a coin toss | Reported: does direction carry information beyond timing? |
| B1 | **Top 9 by raw ROI** | Each hour, follow the top 9 of our leaderboard snapshot by 30-day `roi` (accountValue ≥ $10k), with no gates and no filter. Trades opened in `[t0, T_eval]`. | **Go-live blocker (S4, K9)** |
| B2 | Buy-and-hold BTC | $300 in BTC perp at 1× from `t0`, funding included. Compare USD return and max drawdown; also a version scaled to our realised volatility. | Reported |
| B3 | Unfiltered copy of our selected traders | V1 plus the shadow ledger. Isolates the filter's contribution. | Reported (H3) |
| B4 | The leaders' own P&L over the window | An upper bound. The gap between B4 and H1 is the cost of copying. | Reported |

**What P2c measures, and why B0d never pays the copy's delay (A1.1; rewritten from v2).**
- **Decomposition.** Write a copy's R as:
  - `β_i`: the direction and regime exposure over its holding window
  - `+ g_i`: the leader's gross timing value
  - `− d_i`: the post-signal decay we pay because we act 1-5 s after the leader, at entry and at a leader-driven exit
  - `− f_i`: fees, spread and impact at our own fill times
  - `+ noise`
- **What B0d pays.** A random-time entry has no signal to be late to, so it pays no d. Its expectation is `B̄_i ≈ β̄ − f̄`: the same exposure and the same fee, spread and impact costs.
- **Result.** `D_i ≈ (g_i − d_i) + (β_i − β̄) + noise`. P2c asks whether our **net** timing value, after our own delay, is positive beyond what the same direction profile earned at random times.
- **Why v2 was wrong.** v2 also charged B0d the measured decay. That subtracted d from B̄ as well, so D ≈ g: the leader's gross timing. A copier whose delay eats the whole edge (g = d) could then pass P2c. E11 measures that inflation (5.9), and the auditor's model gives a larger one (BT2-1).
- **Why a lower bound and not a point comparison [QR precision of the PO's "beating", PO-ACK pending: section 14 item 5].**
  - Take a pure-beta copy (g = d = 0) with mean R +0.15 in a rising month. Its B0d mean is also about +0.15, so D ≈ 0 ± 0.1.
  - A point comparison ("our mean > B0d mean") would pass it about half the time.
  - The lower bound passes it at about the nominal α. E11 measured 0.1-0.5% for P2 + P2c, and E6 D2 0.1-1.2%.
- **P2c versus P2.** With no beta, P2c is **easier** than P2 by the fee, spread and impact term f (the 6.3 costs minus the delay term), but **not** by our delay cost. With beta, P2c is harder than P2.

**B0d admissible windows, delistings and missing windows (A1.3 g).**
- **Admissible start.** A decision time t is admissible for trade i when all of these hold:
  - the coin is listed and tradable on core throughout `[t, t + hold_i + ack delay]`
  - our recorded L2 book exists within 5 s of each fill time (entry, and the time exit)
  - our recorded mid and mark stream has no gap over 60 s in `[t, t + hold_i + ack delay]`, so the SL/TP path is observable
  - t is not inside a configured entry blackout, because our engine could not have entered then
- **No extension.** Draws are never taken from outside `[t0, T_eval − hold_i]`: no pre-paper period, and no other coin.
- **Delisted coin.** Windows must end before the last trading moment. A trade in S that ended by delisting settlement uses its hold to settlement, and its replications exit by time at hold_i.
- **Missing window (A1.3 g, A2.3 a).** If the admissible set for trade i totals less than 24 hours of start times (or is empty), trade i has no admissible B0d window. It gets **`D_i = min(R_i, 0, R_i − B̄_i^partial)`**, where `B̄_i^partial` is the first of these that exists:
  1. the mean R of 1,000 replications drawn (tag `b0d`, the same counters) from trade i's admissible set, however short;
  2. if that set is empty: the mean R of 1,000 replications drawn from the **relaxed** set, `[t0, T_eval − hold_i]` restricted only by the listing and blackout conditions. Where our book or mid recording is missing, a replication uses the coin's median recorded half-spread without the ×1.5 multiplier (else 2 bps majors, 8 bps alts) and exchange 1h candles for its SL/TP path, with an ambiguous bar resolved in the replication's favour (TP first);
  3. if the relaxed set is also empty: the largest B̄_j (full or partial) of any trade j in S with the same direction, floored at 0; 0 if there is none (`eval_reference.py::b_partial_last_resort`).
- **What this bounds, and what it doesn't (A2.3 a).** v2 + A1 used `min(R_i, 0)` and claimed that gaps can't help a run pass. That was false. When `B̄_i > max(R_i, 0)`, for example a long, high-beta hold in a rising market, the true `D_i = R_i − B̄_i` is below `min(R_i, 0)`, and recording gaps concentrate on such long holds (BT3-3). With A2.3 a a missing-window trade never contributes more than 0, nor more than its excess over the partial baseline. A residual leak remains, because a short or relaxed window can estimate B̄_i with bias; the 10% cap bounds it.
  - The count, and the step (1-3) used for each trade, are reported.
  - If more than 10% of S (more than 30 trades) have no admissible window, P2c fails (5.3).
- **(A2.3 a) Recorder gap rate, reported before run 1.** From the 24h dry run and the ≥ 1 week of pre-paper recording (8.1), report per coin: the share of time with no recorded L2 book within 5 s, the share with a mid or mark gap over 60 s, and the projected share of trades that would lack an admissible window (the point-in-time replay's trades run through the admissibility rule). It goes to the PO with section 14 (item 8). It is not a gate. If the projected share is near 10%, fix the recorder before run 1, because P2c would otherwise fail by construction.

### 6.3 Cost model

- **Fees:** taker 0.045% per side on every paper fill, including SL and TP, which trigger on mark price and fill as market orders. No maker fills or rebates are assumed. HIP-3 markets are not traded in v1 [PO].
- **Spread and impact (paper):** the fill walks the live L2 book captured at decision time plus `paper_ack_delay_ms`. The default is 1,000 ms, from the median order-to-fill of about 884 ms from Tokyo (market-context 2.4).
- **Spread and impact (replay and baselines):** the **spread recorded at signal time** (BT-13). The fallback, when no recording exists, is each coin's median half-spread from our recordings × 1.5, then 2 bps for majors and 8 bps for alts, per side.
- **Delay slippage (replay):** our measured `decay(Δ)` at the p95 detection latency. The fallback is 5 bps for majors and 15 bps for alts. It applies to copies (our trades, replays, B1, B3), never to random-time baselines.
- **Random-time baselines (B0d, B0; A1.1):** fees, plus spread and impact from the book recorded at their own fill times, plus their own ack-delay drift, plus funding. **(A2.3 b)** Their R is computed from their fill prices, fees and funding; the drift and the spread and impact are reported components of those fill prices, never added on top. **No delay slippage and no decay:** they follow no signal.
- **Stops:** fill at the book at trigger plus the ack delay, with no guaranteed stop price (gap-through is modelled).
- **Funding:** accrued hourly from actual rates [PO].
- **Liquidation:** isolated positions use the mark-price and maintenance-margin model.

**Costs expressed in R (BT-13) [EXPL, arithmetic on the fallback costs].**
- A round trip costs 2 × 4.5 bps taker, plus 2 × half-spread, plus one delay term: **18 bps for majors and 40 bps for alts**.
- An exit that follows the leader's close adds a second delay term (up to +5 or +15 bps), which is not in the table.
- R cost = bps ÷ stop distance in bps.

| Stop distance (2×ATR 1h) | Majors ×1 | ×1.5 | ×2 | Alts ×1 | ×1.5 | ×2 |
|---|---|---|---|---|---|---|
| 0.75% | 0.24R | 0.36R | 0.48R | 0.53R | 0.80R | 1.07R |
| 1.0% | 0.18R | 0.27R | 0.36R | 0.40R | 0.60R | 0.80R |
| 1.5% | 0.12R | 0.18R | 0.24R | 0.27R | 0.40R | 0.53R |
| 2.5% | 0.07R | 0.11R | 0.14R | 0.16R | 0.24R | 0.32R |
| 4.0% | 0.04R | 0.07R | 0.09R | 0.10R | 0.15R | 0.20R |

**Reading:**
- At typical stops (majors about 1-1.6%, alts about 2-4%), costs are about **0.1-0.2R per trade**. That is the same size as the prior edge (< 0.10R).
- Tight stops on alts make copying structurally unprofitable. This is why FR3, the cost-fragile flag (5.6), is pre-registered, and why the ×1.5 and ×2 sensitivity runs now have a consequence.

## 7. Kill criteria (stop, don't build further or don't go live)

| ID | Trigger | Action |
|---|---|---|
| K1 | Indicative or point-in-time replay with ≥ 100 trades: mean R CI upper bound < 0 | Stop before paper (the PO's kill criterion) |
| K2 | Point-in-time replay with ≥ 150 trades: point estimate ≤ 0 | Stop and review with the PO before paper |
| K3 | Paper verdict FAIL through F3 (`UB_r ≤ 0`) | Recommend kill or redesign, not a re-run of the same config |
| K4 | Paper verdict INCONCLUSIVE with point estimate ≤ 0 | Recommend kill or redesign rather than run 2 with the same config |
| K5 | Drawdown ≥ 15% at any time | FAIL (F1) [PO] |
| K6 | Decay: median adverse drift at our p50 latency ≥ 50% of the median leader gross round-trip move | Uncopyable: redesign |
| K7 | In the 24h dry run plus the first week, fewer than 5 eligible traders on ≥ 50% of scoring cycles | The premise fails. Redesign the gates as a logged variant **before** a run, never mid-run. |
| K8 | > 50% of filter-passing signals unexecutable at $300 (below $10 after caps) | The $300 mirror model is invalid: PO decision on sizing |
| **K9** | **Either** P2c fails (the trades do not beat the direction-matched random-time baseline) **or** S4 fails (they do not beat top-9 by raw ROI) | No evidence that selection adds value beyond beta or luck. A P2c failure prevents PASS (5.3). An S4 failure with PASS blocks go-live until PO review (5.6). |
| K10 | Hyperliquid data access unavailable or prohibited, including a Brazil geo-block around 2026-10-30 | Alert and pause entries [PO]. Stop if it persists. |
| K11 | Run register exhausted: run 2 ended without PASS | Close the paper gate for this epic (5.4) |
| K12 | FR3 cost-fragile at `T_eval` | Go-live blocked pending PO review. Recommend redesign toward longer holds or majors. |

## 8. Paper-trading plan (D6)

### 8.1 Plan

- **Preconditions:**
  - a 24h dry run with no crash
  - a 1-day latency measurement from the PO's PC
  - at least 1 week of recorded books and leaderboard snapshots, which feeds the point-in-time replay
  - the incremental candidate backfill (12-24h) done before any wallet is followed [PO]
  - K1 and K2 not triggered
  - the run record written (5.1)
- **Duration:** the sample is the first 300 opened trades.
  - If fewer than 300 are opened by day 30, the run continues to day 60 with the same frozen config and a **single evaluation** [PO].
  - With fewer than 300 opened by day 60, the verdict is INCONCLUSIVE.
  - Otherwise the evaluation happens at `T_eval` (5.3).
- **Frozen config:** any change to scoring, filter, sizing, exits, risk or cost parameters ends the run as ABORTED, and the run counts [PO]. At most 2 runs (5.4).
- **Frozen engine (A1.2, A2.2):** the run starts from a clean commit, in a dedicated worktree pinned to it (5.1). Any code or dependency change during the run is a deploy and needs a backtest-auditor ruling before it runs. Logic changes are ABORTED by default (5.3).
- **Precondition (BT2-5, A2.4):** the PO's acknowledgement of the eight section-14 items is recorded in `decisions.md`.
- **Precondition (A2.3 a):** the recorder gap-rate report (6.2) is delivered to the PO with the section-14 items.
- **Visibility:** see 5.5.
- **Wallets:** paper **$300**. Live, in a future epic, starts at **≥ $300**, never smaller than the paper-tested size [PO].

### 8.2 Tolerated divergence

The replay is run over the paper window through the same engine.

| Check | Tolerance |
|---|---|
| Take/skip decision agreement per signal | ≥ 90% |
| Per-trade R, paper vs replay, on matched trades | median absolute difference ≤ 0.05R; mean difference ≤ 0.10R |
| Sign of mean R | Must match [PO] (this is P6) |
| Paper fill price vs the replay cost model | median deviation ≤ 3 bps; p90 ≤ 10 bps |
| Trade count | Replay count within ±10% of paper |

- Exceeding any tolerance is a D6 failure: the replay cannot be trusted, so stop before any live step.
- **After a PASS (future epic):** a small live stage of ≥ 100 trades. The paper-vs-live tolerance is set in that epic, because paper fills are optimistic: no queue position and no rejects.

## 9. Config implications (for the PM's config table)

Flags:
- **OF** = overfitting risk: a prior with few or no data points behind it. It must not be tuned on paper-run data.
- **CAL** = calibrate once from pre-paper recorded data, then freeze.
- **FROZEN** = part of the pre-registration (5). It can change only by addendum before a run (5.1).

### 9.1 Scoring and selection (section 10)

| Key | Default | Unit | Range / ceiling | Basis | Flag |
|---|---|---|---|---|---|
| `scoring.candidates_k` | 200 | wallets | 50-500 | brief | |
| `scoring.interval_min` | 60 | min | 15-1440 | brief | |
| `scoring.window_days` | 180 | days | 90-365 | brainstorm | OF |
| `scoring.dsr_min_daily_days` | 60 | days | ≥ 30 | QR (BT-17) | OF |
| `gate.min_account_age_days` | 180 | days | ≥ 90 | brainstorm | OF |
| `gate.min_round_trips` | 150 | count | ≥ 50 | brainstorm | OF |
| `gate.min_fill_span_days` | 60 | days | ≥ 30 | QR (10k fill cap) | OF |
| `gate.min_positive_blocks` / `gate.n_blocks` / `gate.block_days` | 4 / 6 / 30 | count, days | | QR | OF |
| `gate.max_drawdown` | 0.35 | fraction | ≤ 0.5 | brainstorm | OF |
| `gate.min_profit_factor` | 1.3 | ratio | ≥ 1.0 | brainstorm | OF |
| `gate.min_dsr_prob` | 0.95 | probability | 0.5-0.99 | brainstorm / BLdP | |
| `gate.dsr_n_trials` | 15000 | count | ≥ `candidates_k` | market-context (leaderboard size) | see C11 |
| `gate.min_median_hold_min` | 15 | min | ≥ 20 × p95 latency | brainstorm | OF |
| `gate.max_top_trade_share` | 0.25 | fraction | | brainstorm | OF |
| `gate.max_top_asset_share` | 0.50 | fraction | | brainstorm | OF |
| `gate.min_copy_edge_ratio` | 3.0 | ratio | ≥ 1 | brainstorm | OF |
| `gate.min_account_value_usd` | 10000 | USD | | QR | OF |
| `gate.min_executable_share` | 0.50 | fraction | | QR | OF |
| `gate.max_maker_share` | 0.70 | fraction | | QR (excludes market makers) | OF |
| `gate.max_current_drawdown` | 0.20 | fraction | | QR | OF |
| `gate.exclude_roles` | vault, agent, missing (via `userRole`); plus the HLP address | list | | QR | |
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
| `select.min_followed` / `select.max_followed` | 5 / **9** | count | max ≤ WS user cap − 1 | brief; **PO (9 + 1 swap slot)** | |
| `select.backfill_hours` | 12-24 (incremental) | h | | PO | |
| `select.swap_margin` | 0.10 | score units [0,1] | | QR | OF |
| `select.max_swaps_per_cycle` | 1 | count | | QR | |
| `leader_pause.max_copy_dd` / `leader_pause.max_consec_losses` | 0.10 / 5 | fraction of allocation, count | | brainstorm risk | OF |
| `copyreplay.delay_ms` | measured p95, else 3000 | ms | ≤ 5000 | QR | CAL |
| `copyreplay.half_spread_bps` (majors / alts) | recorded at signal time; else recorded median × 1.5; else 2 / 8 | bps | | QR (BT-13) | CAL |

### 9.2 Evaluation, sizing, costs and the run

| Key | Default | Unit | Basis | Flag |
|---|---|---|---|---|
| `risk.per_trade_fraction` | **0.005** | fraction of equity | **PO** (ceiling 0.01) | FROZEN |
| `sizing.partial_below_min_action` | **skip_and_log** | enum | **PO** | FROZEN |
| `sizing.close_all_if_remainder_below_min` | **true** | bool | **PO** | FROZEN |
| `sizing.min_order_usd` | 10 | USD | exchange | |
| `paper.wallet_usd` | **300** | USD | **PO** | FROZEN |
| `live.min_wallet_usd` | **300** | USD | **PO** | |
| `markets.allowed_dexes` | **core** | list | **PO** (HIP-3 not traded) | FROZEN |
| `recording.markets` | core + HIP-3 | list | **PO** | |
| `eval.sample_basis` | **opened** | enum | **PO** | FROZEN |
| `eval.n_trades` | 300 | trades | PO | FROZEN |
| `eval.calendar_cap_days` / `eval.extension_days` | 30 / **30** (to 60 total) | days | **PO** | FROZEN |
| `eval.closeout_max_days` | 7 | days after the 300th open | QR, **PO-ACK pending** (item 4; the PO said "after all have closed") | FROZEN |
| `eval.ci_level_run1` / `eval.ci_level_run2` | **0.96 / 0.99** | | QR, **PO-ACK pending** (item 1). The PO's decision was ≤ 2 runs and a 95% CI (**A2.5:** the 95% is in `01-brief.md:27,127`; D11 states no level). (A1.5; v2 mislabelled this "PO (α split)".) | FROZEN |
| `eval.max_runs` | **2** | runs | **PO** | FROZEN |
| `eval.ci_method` | min over {iid t, day-cluster bootstrap, day-cluster CR t (G−1 df)} | | PO (day clusters) + QR, **PO-ACK pending** (item 2) | FROZEN |
| `eval.cluster_key` | UTC day of the first entry of the merged position (transitive overlap components, A1.3 c) | | QR (BT-4) | FROZEN |
| `eval.min_day_clusters` | 5 | days | QR (E10), **PO-ACK pending** (item 3) | FROZEN |
| `eval.bootstrap_b` / `eval.bootstrap_seed` | 10000 / 32 CSPRNG bytes generated at run start, stored as hex; the RNG consumes the raw bytes (A2.7) | | QR | FROZEN |
| `eval.bootstrap_statistic` | pooled trade mean of the resample | | QR (A1.3 b) | FROZEN |
| `eval.rng` | `sha256_counter_rejection` (5.3, A1.3 b) | | QR | FROZEN |
| `eval.percentile_index` | `floor(B·(100 − L%)/200)`, 0-based ascending; UB at `B − 1 − index` | | QR (A1.3 b) | FROZEN |
| `eval.gate_round_dp` | 6 | decimal places of R | QR (A1.3 b) | FROZEN |
| `eval.flatten_gate_rule` | `min_realised_shadow`; the shadow exit is the evaluation close (A2.1) | enum | QR (A1.3 d, A2.1) | FROZEN |
| `eval.require_clean_engine_tree` | true | bool | QR (A1.2) | FROZEN |
| `eval.engine_path_manifest` | path of the committed engine-path-set manifest (named in the spec) | path | QR (A2.2) | FROZEN |
| `eval.run_worktree_pinned` | true: each run executes from a dedicated worktree at the run commit | bool | QR (A2.2) | FROZEN |
| `eval.run_record_env_hashes` | installed-package list + every non-config data input | list | QR (A2.2) | FROZEN |
| `eval.deploy_policy` | `auditor_ruling_required`; logic changes `abort_by_default` | enum | QR (A1.2) | FROZEN |
| `eval.require_usd_pnl_positive` | true | bool | **PO** | FROZEN |
| `eval.baseline_gate` | direction_matched_random_time, tested as a lower bound (P2c); non-removable | enum | **PO** (gate) + QR, **PO-ACK pending** (item 5; the lower-bound reading) | FROZEN |
| `baseline.dm_costs` | fees + own-time spread and impact + own ack drift + funding; **no decay**; R from fill prices, drift and spread reported, never added (A2.3 b) | | QR (A1.1, A2.3 b) | FROZEN |
| `baseline.dm_min_admissible_hours` / `baseline.dm_max_missing_share` | 24 / 0.10 | h / fraction of S | QR (A1.3 g) | FROZEN, OF |
| `baseline.dm_missing_rule` | `min(R, 0, R − B̄_partial)`; B̄_partial from the partial set, else the relaxed set, else the largest same-direction B̄ floored at 0 (6.2) | enum | QR (A2.3 a) | FROZEN |
| `baseline.dm_max_book_gap_s` / `baseline.dm_max_mid_gap_s` | 5 / 60 | s | QR (A1.3 g) | FROZEN, OF |
| `eval.max_dd` / `eval.mark_interval_s` | 0.15 / 60 | fraction / s | PO / QR | FROZEN |
| `eval.show_interim_stats` | false (trades and USD P&L are shown) | bool | PO + QR | FROZEN |
| `baseline.dm_reps` | 1000 | replications per trade | QR | FROZEN |
| `baseline.random_reps` | 1000 | | QR | |
| `baseline.top_roi_n` | **9** | wallets | QR (matches `max_followed`) | FROZEN |
| `fragility.top_k_trades` | 5 | trades | QR (BT-12) | FROZEN |
| `fragility.drop_best_day_clusters` | 1 | day clusters | QR (A1.6, FR6) | FROZEN |
| `report.weekly_block_days` | 7 | days from `t0` | QR (A1.6, S6) | |
| `fragility.cost_stress_mult` | 2.0 | x | QR (BT-13) | FROZEN |
| `cost.taker_fee_bps` / `cost.maker_fee_bps` | 4.5 / 1.5 | bps | market-context [T] | |
| `cost.funding_accrual` | hourly, actual rates | | PO | |
| `paper.ack_delay_ms` | 1000 | ms | market-context | CAL |
| `decay.deltas_s` | 0.25, 0.5, 1, 2, 3, 5, 10, 30, 60, 300 | s | QR | |
| `data.paid_s3` | false | bool | PO | |

The risk, filter and exit parameters come from the brief and the risk research, and the PM owns them. They include the ATR multiple, TP, loss limits, slippage and age guards, and event windows (entries and adds only [PO]).

From a research standpoint:
- **OF:** every filter threshold (volatility percentile, funding extreme, spread, OI drop). None has data behind it yet.
- **CAL then freeze:** calibrate each of those thresholds once on pre-paper recorded data, then freeze it before run 1.

---

## 10. Trader scoring model (precise, for the config table and property tests)

### 10.1 Inputs, point-in-time

For wallet w at cycle time t (UTC ms):
- `F_w(t)` = cached fills with `time ≤ t`, within `window_days`
- `P_w(t)` = the latest `portfolio` snapshot fetched at or before t
- `C_w(t)` = the latest `clearinghouseState` fetched at or before t
- `K(t)` = 1h candles with close time ≤ t

Missing or stale inputs (older than `2 × interval_min`) make the wallet **ineligible**: fail closed (A2).

**Round-trip reconstruction.** Implemented in `docs/sdlc/copytrade-v1/research/scripts/hl_sample.py::reconstruct`, which has a self-test.
- A per-coin position goes from 0, to non-zero, and back to 0. A flip splits into a close and a new open.
- A position already open at the first available fill is ignored until it is flat.
- Spot and HIP-3 (`dex:COIN`) fills are skipped.
- Per round trip j, the reconstruction records:
  - coin, direction s_j, open and close times, entry px and size
  - peak notional `N_j = max|pos| × avg_px`
  - the sequence of adds and reduces, with times, prices and sizes
  - adds-while-losing
  - leader net P&L `L_j = Σ closedPnl − Σ fee − funding_j`
  - a liquidation flag

**Daily returns for the Sharpe-based metrics (BT-17).** `r_d = ΔPnL_d / AV_{d−1}`. ΔPnL_d is deposit-neutral and comes from the **finest point-in-time source available for day d**, in this order:
1. Our own hourly `portfolio` snapshots.
2. `perpMonth` `pnlHistory` (the last ~30 days, sub-daily points).
3. For older days, **realised** daily P&L from fills: Σ closedPnl − fee − funding by UTC day.

The coarse `perpAllTime` series (about 93 points) is **not** step-interpolated into daily returns. `AV_{d−1}` is the latest account-value point at or before the end of day d−1.

Every wallet records `dsr_resolution`: the number of days from each source. The DSR metrics (M5-M7, G7, component 1) use T = the number of days with a daily-resolution return. If T < `scoring.dsr_min_daily_days` (60), the wallet is ineligible under G7.

Mixing mark-to-market and realised days understates volatility on the realised days. This is a known limitation, reduced as our own snapshots accumulate.

### 10.2 Metrics (per wallet, per cycle)

| ID | Metric | Formula |
|---|---|---|
| M1 | `n_rt` | closed round trips in the window |
| M2 | `fill_span_days` | (last fill − first fill) / 1 day, within the window |
| M3 | `account_age_days` | t − the first `perpAllTime` point |
| M4 | `profit_factor` | `Σ_{L_j>0} L_j / |Σ_{L_j<0} L_j|`, capped at 10 |
| M5 | `sr_d` | `mean(r_d) / sd(r_d)`, daily, zeros included, over the T daily-resolution days (10.1) |
| M6 | `skew`, `kurt` | sample skewness and (non-excess) kurtosis of r_d |
| M7 | `dsr_prob` | `Φ((sr_d − SR0)·√(T−1) / √(1 − skew·sr_d + (kurt−1)/4·sr_d²))`, where `SR0 = Emax(N)/√T`, `Emax(N) = (1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N·e))`, γ = 0.5772 and N = `dsr_n_trials`. This is Bailey & López de Prado (2014), with the null variance of the Sharpe estimate taken as 1/T. |
| M8 | `pos_blocks` | the number of the last `n_blocks` blocks of `block_days` with Σ ΔPnL > 0. A block with no data counts as not positive. |
| M9 | `max_dd` | max(DD of realised equity `AV_0 + cumΣ L_j`, DD of the mark-to-market curve `AV_0 + pnlHistory`) |
| M10 | `median_hold_min` | median (close − open) over round trips |
| M11 | `top_trade_share` | `max_j L_j / Σ_j L_j` (ineligible if Σ ≤ 0) |
| M12 | `top_asset_share` | `max_coin Σ_{j∈coin} L_j / Σ_j L_j` |
| M13 | `maker_share` | notional of fills with `crossed = false` / total notional |
| M14 | **`copy_mean_r`** | **Copy replay.** Each round trip is re-traded as we would trade it: entry at the leader's open px plus a delay cost, our ATR stop (from `K(t)` before entry), our TP, and mirrored adds and partials under the $10 rules. The exit is the leader's close or our SL/TP, whichever comes first, checked on the high/low of 1h bars; on an ambiguous bar the stop is assumed first. Our costs are included. Gives `R_copy_j` and `copy_mean_r = mean_j R_copy_j`. |
| M15 | `copy_edge_ratio` | `mean_j(gross_bps_j) / mean_j(cost_bps_j)`, where `gross_bps_j = Σ closedPnl_j / N_j × 1e4` and `cost_bps_j = 2·taker + 2·half_spread(coin) + delay_bps(coin)` |
| M16 | `executable_share` | share of opens whose mirrored notional `(open_notional / AV_at_open) × our_equity`, after the risk cap with our stop, is ≥ $10. AV_at_open is the latest point at or before the open. |
| M17 | `recent_sr` | `sr_d` over the last 30 days × 30/(30 + `shrink_k_days_recent`) |
| M18 | `current_dd` | (peak − current) / peak of the mark-to-market curve |
| M19 | `eff_leverage_median` | median over opens of `N_j / AV_at_open` |

### 10.3 Eligibility gates (all must hold; fail closed)

| ID | Gate |
|---|---|
| G1 | `account_age_days ≥ min_account_age_days` (180) |
| G2 | `n_rt ≥ min_round_trips` (150) |
| G3 | `fill_span_days ≥ min_fill_span_days` (60). Very active wallets can't show 60 days under the 10k-fill cap, and they are mostly scalpers anyway. |
| G4 | `pos_blocks ≥ min_positive_blocks` (4 of 6 × 30d) |
| G5 | `max_dd ≤ 0.35` |
| G6 | `profit_factor ≥ 1.3` |
| G7 | `dsr_prob ≥ 0.95` with T ≥ 60 daily-resolution days (**luck correction**) |
| G8 | `median_hold_min ≥ max(15, 20 × p95_latency_min)` |
| G9 | `top_trade_share ≤ 0.25` and `top_asset_share ≤ 0.50` |
| G10 | `copy_edge_ratio ≥ 3` **and** `copy_mean_r × n_rt/(n_rt + shrink_k_trades) > 0` |
| G11 | `AV ≥ $10,000` |
| G12 | `executable_share ≥ 0.50` |
| G13 | `maker_share ≤ 0.70`; `userRole` not vault, agent or missing; not HLP |
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
2. **Safety drop** (immediate; ignores the minimum follow time):
   - Trigger: a followed wallet has any BU flag, fails G15, or our per-leader pause trips (copy DD ≥ 10% of its allocation, or 5 consecutive losses of our copies).
   - Effect: new opens stop at once.
3. **Rank drop:**
   - Trigger: a followed wallet has rank > `drop_rank` (15), or fails a non-safety gate, for `drop_confirm_cycles` (2) consecutive cycles.
   - Condition: it has been followed ≥ `min_follow_hours` (24).
4. **Join:**
   - Trigger: an unfollowed wallet is eligible with rank ≤ `join_rank` (8) in `join_confirm_cycles` (2) consecutive cycles.
   - Condition: its incremental backfill is complete [PO], and there is room (followed < `max_followed` = 9).
5. **Swap:**
   - Trigger: followed = `max_followed`, and a join-qualified candidate has `S_cand ≥ S_weakest + swap_margin` (0.10).
   - Condition: the weakest followed wallet has been followed ≥ 24h.
   - Effect: the candidate replaces the weakest, at most 1 swap per cycle. The 10th WebSocket slot is used during the handover [PO].
6. If fewer than `min_followed` are eligible, follow all eligible wallets. Never pad the list with ineligible wallets; alert. With 0 eligible, take no new entries.
7. **Dropped wallets:** new opens are no longer copied. Existing shares stay managed by our SL/TP and the wallet's exits (C4), through the risk gate, until they close. The WebSocket slot is held until then (see market-context Q1).
8. **Leaderboard unavailable:** keep the current wallets, add none, alert [PO].
9. Persist every cycle's inputs, metrics, u_k, S, rank and decision (B5, and point-in-time replay).

### 10.7 Property tests (for the test designer)

1. For any valid config, the weights are all ≥ 0 and sum to 1 (±1e-9). Otherwise config load fails closed.
2. S ∈ [0, 1], and each u_k is non-decreasing in its "better" direction (monotonicity).
3. S for wallet A does not depend on any other wallet's data or on input order.
4. The same inputs always give the same S, rank and decisions (determinism, including the tie-break).
5. **Point-in-time:** adding fills with `time > t` never changes the score at t.
6. An ineligible wallet is never followed, and a missing input implies ineligible.
7. The followed count never exceeds `max_followed` (9). It is below `min_followed` only when fewer are eligible.
8. A wallet ranked in `(join_rank, drop_rank]` keeps its current status (the hysteresis band).
9. No rank-based drop happens before `min_follow_hours`. A safety drop can happen at any time.
10. There are at most `max_swaps_per_cycle` swaps per cycle.
11. Each BU detector fires exactly at its threshold boundary (inclusive or exclusive, as specified) and not below its minimum sample.
12. DSR: `dsr_prob` is non-increasing in `dsr_n_trials` and non-decreasing in `sr_d` (for fixed skew and kurtosis in the valid domain).
13. `copy_mean_r_shrunk` has the same sign as `copy_mean_r` and a smaller or equal magnitude.
14. **(BT-17) Resolution:** `r_d` never comes from step-interpolated `perpAllTime` points. Adding or removing an all-time point that falls between two daily-resolution days leaves `sr_d` unchanged. T equals the count of daily-resolution days and matches the `dsr_resolution` record. A wallet with T < `dsr_min_daily_days` is ineligible.
15. **(BT-3) Account value:** the account value used for any past event is the latest point at or before it. If no such point exists, the event is excluded, and never valued with a later value.

### 10.8 Evaluation tests (for the test designer; from 5.3)

1. The sample is the first 300 trades by entry-fill time. A trade opened after the 300th never enters S, even if it closes first.
2. `T_eval` = min(last close in S, `t300` + 7 days), where a flattened trade's close is its shadow exit (A2.1). Trades still open, and shadows still open, are marked as specified.
3. `LB_r` is the minimum of the three methods and `UB_r` the maximum. For a fixed seed the result is deterministic.
4. The day cluster of every share equals the UTC day of its merged position's first entry.
5. The run-level CI is 96% for run 1 and 99% for run 2. A third run can't be started.
6. A config-hash change before `T_eval` ends the run as ABORTED and increments the run count.
7. No interim mean R, CI or verdict is exposed before `T_eval`.
8. PASS requires P1-P6 (including P2b and P2c). FAIL requires F1, F2 or F3. Everything else is INCONCLUSIVE.
9. With G < 5 day clusters in S, the verdict is never PASS, and never FAIL by F3. It can still be FAIL by F1/F2, or ABORTED (A1.3 a).
10. **(A1.1, BT2-1) B0d never pays post-signal decay.**
    - **Setup:** a recorded dataset where the mid jumps X bps in the trade's direction in the 5 s after every leader fill and is flat otherwise.
    - Changing X changes R_i but leaves every B̄_i unchanged.
    - A replication decided at t fills at the book recorded at t + `paper_ack_delay_ms`, walked with its own size.
    - Its cost breakdown contains exactly: fees, own-time spread and impact, own ack drift, and funding. No decay or leader-relative term exists.
    - Doubling `copyreplay.delay_ms` or the measured decay never changes B̄_i.
    - **(A2.3 b)** A replication's R equals the R computed from its entry and exit fill prices, fees and funding. Its drift and spread-and-impact components sum to (fill − decision mid) and are not added again: an implementation that adds either on top of the fill price fails this test.
11. **(A1.2, BT2-2) Engine version and deploys.**
    - The run record contains the 40-hex commit, the dirty flag, the lockfile sha256 and the Python version.
    - A dirty tree can't start a run.
    - **(A2.2)** A process start on a different commit, lockfile, installed-package list or data input writes a deploy record with the stored diff and its sha256. The new code does not run inside the run until a ruling is in the ledger; until then only the recorded commit runs, whether or not entries are paused, and paused time counts as downtime.
    - A diff touching signal, filter, scoring, sizing, exit, cost or fill code defaults to ABORTED.
    - Executing new code without a ruling makes the run ABORTED.
    - A same-commit, clean crash restart is not a deploy.
    - **(A2.2)** The run record also holds the installed-package-list sha256 and the per-file sha256 of every non-config data input. Installing or upgrading a package, or changing a data input, is a deploy.
    - **(A2.2)** The dirty flag covers only the engine path set: a commit or untracked file under `docs/**` or `research/**`, or a run-register append, is not a deploy and doesn't make the tree dirty. A file the engine reads that is missing from the manifest fails a startup check.
    - **(A2.2)** The engine refuses to start a run outside a worktree pinned (detached) to the run commit.
    - **(A2.2)** While a deploy awaits a ruling, only the recorded commit executes, including position management and exits, whether entries are paused or not.
12. **(A1.3 a) Precedence.** Every ordered pair in the 5.3 precedence list resolves as listed. The implementation matches `eval_reference.py::verdict` on its asserted cases. Among them: G = 3 with UB_r ≤ 0 is INCONCLUSIVE; a voided run with F1 is ABORTED; an LB rounding to 0.000000 is not > 0.
13. **(A1.3 b, A2.7) Bootstrap reproducibility.** For the seed and samples in `research/data/eval_reference_vectors.txt` (E14), the implementation reproduces all of these to 1e-6 (the RNG outputs exactly):
    - the `rng_uint` sequence
    - the percentile indices
    - each CI
    - `LB_r` and `UB_r`
    - **(A2.7)** the rejection vector (n = 2^63 + 1), the unequal-cluster sample, and the order-statistic neighbours of the distinct 40-cluster sample
    - **(A2.7)** the seed is taken as the 32 raw bytes; passing the hex text is an error

    Swapping cluster order in the input doesn't change the result, because clusters are sorted by day.
14. **(A1.3 c) Transitive merged positions.** The E13 vector, kept unchanged in E14 **(A2.7)**, must be reproduced: A–B–C chained across midnight, and E touching C, form one component; the opposite direction (D) and another coin (F) stay separate. A trade outside S never links two trades in S.
15. **(A1.3 d, A2.1) `/flatten`.** Flattened trades stay in S. Their gate R and USD are the worse of realised and shadow. P3 is checked on both equity curves. A flatten that improved realised R never raises `LB_r`.
    - **(A2.1)** `T_eval`, `hold_i`, the merged-position interval, the B0d replications' hold and P3's shadow equity use the shadow exit. Moving the flatten time, with the shadow unchanged, never changes `T_eval`, the day clusters, G or any B̄_i.
    - **(A2.1)** A shadow still open at `t300 + 7 days` is marked at mid − taker fee − half-spread, `T_eval = t300 + 7 days`, and the trade's gate R is `min(realised R, marked shadow R)`.
    - **(A2.1)** A flattened trade whose shadow overlaps a later same-coin, same-direction trade merges with it, even when its real close did not.
    - The E14 flatten vector is reproduced.
16. **(A1.3 g) B0d admissibility.**
    - No draw falls outside the admissible set, or inside a blackout, or across a delisting.
    - A trade with less than 24 h of admissible starts gets `D_i = min(R_i, 0, R_i − B̄_i^partial)` (A2.3 a), with B̄_i^partial from the first available of the three steps in 6.2. With `B̄_i^partial > max(R_i, 0)`, D_i is below `min(R_i, 0)`. The E14 D vector is reproduced.
    - **(A2.3 a)** The report lists the step used for each missing-window trade, and the pre-paper recorder gap-rate report exists.
    - More than 10% such trades fails P2c.
    - Draws reproduce `eval_reference.py::b0d_start` for the same seed and counters.
17. **(A1.3 f) Marked trades.** `hold_i = T_eval − entry`. Funding stops at the last hourly funding at or before `T_eval`. The replications use the same hold and the marking formula. The trade's merged-position interval ends at `T_eval`. Its later real outcome never changes the stored verdict.
18. **(A1.3 h) Run register.** Appending a run-register or deploy row never changes the sha256 of `edge-hypothesis.md` or the config.
19. **(A1.6) FR6 and S6.** FR6 drops exactly the day cluster with the largest Σ R (earliest day on a tie) and fires at mean ≤ 0. S6 blocks are 7 days from `t0` by entry-fill time and together cover all of S.
20. **(A1.4) P2c non-removable and cross-day diagnostics.** A config without the baseline gate fails to load. The `T_eval` report contains:
    - the KM median hold
    - the share of trades crossing midnight
    - the overlap-component CI with G_ov, marked "degenerate" when G_ov < 5

---

## 11. Feasibility: is 300 opened trades within 30 (or 60) days realistic? [EXPL]

**Short answer:** yes in the base and optimistic synthetic cases, now that risk is 0.5% and there is a 60-day extension. It is not reliable with 3-5 leaders, and near impossible if leaders make about 1.5 opens a day. Whether the run can **pass** is the harder question (5.9).

**Where the estimate comes from:**
- `scripts/feasibility_mc.py` v2 (E5): seed 17, 2,000 runs per cell, **synthetic priors, not Hyperliquid data**.
- All rows use 0.5% risk and at most 9 followed, except the 1% reference row.
- Rejections modelled:
  - filter
  - signal age
  - slippage
  - conflicts
  - caps
  - the $10 minimum
  - 10 concurrent positions
  - net daily (2%) and weekly (5%) loss halts
  - the 15% drawdown stop, which ends the run as a FAIL
- The partial exits follow the PO $10 rule.

| Scenario (followed; opens/trader/day; filter pass) | True mean R | Taken by day 30, p10 / p50 / p90 | P(300 opened by day 30 / 60) | P(DD ≥ 15%) before evaluation: **lower bound** (realised) / **upper bound** (pessimistic MTM) | Joint P(PASS), run 1 (of which evaluated within 30 days) |
|---|---|---|---|---|---|
| Pessimistic (5; 1.5; 0.50) | 0.00 | 45 / 73 / 120 | 0.00 / 0.03 | 0.002 / 0.003 | 0.001 (0.000) |
| Pessimistic | +0.10 | 46 / 74 / 127 | 0.00 / 0.04 | 0.000 / 0.000 | 0.013 (0.000) |
| **3-5 traders, no activity floor** (3-5; 2.0; 0.65) (BT-10) | 0.00 | 73 / 143 / 253 | 0.05 / 0.43 | 0.045 / 0.052 | 0.004 (0.001) |
| 3-5 traders, no floor | +0.10 | 73 / 141 / 259 | 0.06 / 0.45 | 0.000 / 0.000 | 0.144 (0.018) |
| Base (8; 3.0; 0.65) | 0.00 | 259 / 308* / 325* | 0.81 / 0.94 | 0.073 / 0.110 | 0.011 (0.011) |
| Base | +0.10 | 300* / 309* / 331* | 0.90 / 1.00 | 0.001 / 0.001 | **0.292** (0.265) |
| Optimistic (9; 6.0; 0.80) | 0.00 | 300* / 313* / 335* | 0.91 / 0.91 | 0.107 / 0.156 | 0.010 (0.010) |
| Optimistic | +0.10 | 304* / 316* / 344* | 1.00 / 1.00 | 0.001 / 0.004 | 0.223 (0.223) |
| Base, day-factor corr 0.2, 70% long (BT-8) | 0.00 | 251 / 307* / 328* | 0.78 / 0.91 | 0.099 / 0.141 | 0.015 (0.014) |
| Base, day-factor corr 0.2, 70% long | +0.10 | 283 / 308* / 329* | 0.86 / 1.00 | 0.003 / 0.005 | 0.237 (0.201) |
| Reference: base at 1% risk | 0.00 | 128 / 283 / 317* | 0.44 / 0.61 | 0.410 / 0.518 | 0.011 (0.009) |
| Reference: base at 1% risk | +0.10 | 233 / 306* / 326* | 0.72 / 0.95 | 0.054 / 0.086 | 0.303 (0.242) |

\* The sample is complete at 300 opens, so the simulation stops at `T_eval` and counts above 300 are truncated.

**Mirror and rejection rates, with denominators (BT-9).** Per cell, pooled over the 2,000 runs:

| Scenario | Opens below $10 after the cap (of entries reaching the size check) | Loss-halt blocks (of entries reaching the halt check), mean R 0 / +0.10 | Partials skipped, cut < $10 (of all mirrored partials) | Partials closed in full, remainder < $10 |
|---|---|---|---|---|
| Pessimistic | 17.1-17.2% | 0.1% / 0.0% | 23.9% | 16.7% |
| 3-5 traders | 3.1% | 1.8% / 0.6% | 17.1% | 7.4% |
| Base | 3.1% | 9.8% / 3.8% | 17.0-17.2% | 7.3% |
| Optimistic | 0.4% | 32.7% / 12.0% | 13.3% | 3.9% |
| Base, correlated | 3.1% | 12.5% / 5.0% | 17.0% | 7.3% |
| Base at 1% risk | 3.1% | 27.0% / 15.8% | 10.1-10.2% | 5.4% |

**Corrections to v1 (BT-9):**
- v1 said about 1% of opens were rejected below $10 in the base and optimistic cases. The correct figures, with the size-check denominator, were **3.1% (base) and 0.4% (optimistic)**. They are unchanged in v2.
- v1 said halts "remove 5-20% of candidate entries". Measured against the entries that reach the halt check, halts blocked **17-55%** at 1% risk in v1. In v2 at 0.5% risk they block 0-33%.

**Reading:**
1. **The binding constraint is leader activity × pass rate × the number of eligible leaders, not latency.**
   - The eligibility gates only guarantee ≥ 0.83 opens per trader per day. Multi-hour swing traders often make 1-3 trades a day.
   - With 3-5 eligible leaders, which is plausible given G7 (C11), 300 opened trades happens by day 60 in only about 45% of runs.
   - **100-300 opened trades per 30 days is a prior-driven judgement, not a measurement.** `hl_sample.py` measures it.
2. **At 0.5% risk, the drawdown line almost never fails a real +0.10R edge:**
   - 0.1-0.3% (lower bound) to 0.1-0.5% (pessimistic upper bound) in the base and optimistic cases
   - against 5-9% at 1% risk

   Zero-edge strategies still hit 15% in 7-16% of base and optimistic runs. The realised-only figures are **lower bounds** of the gate's mark-to-market drawdown. The pessimistic bound puts every open position at its worst excursion at the same moment.
3. **Faster is not better for the verdict.** In the optimistic case 300 trades arrive in a median of about 8 days (21 in the base case). That gives few day clusters, so the day-clustered CI is wide: joint P(PASS) is 0.22, against 0.29 in the base case.
4. **The $10 rule matters more for partials than for opens.**
   - 13-24% of mirrored partials are skipped, and another 4-17% become full closes.
   - Both change the copy's payoff relative to the leader's, and both are logged per trade (mirror fidelity).
5. More trader shares per merged position inflate N without adding independent information. The day clusters account for this (5.3).

## 12. Exploratory work log (all EXPL; for the backtest-auditor)

sha256 values identify each output. `research/data/` is gitignored, so outputs are not committed (BT-15). Scripts live in `docs/sdlc/copytrade-v1/research/scripts/`.

| # | What | Script (sha256) | Output (sha256) | Result | Counts as a strategy variant? |
|---|---|---|---|---|---|
| E1 | Reach the Hyperliquid API from the research sandbox | n/a | n/a | **Unreachable**: egress proxy CONNECT 403 for `api.hyperliquid.xyz`, `stats-data.hyperliquid.xyz` and `hyperliquid.gitbook.io`. | no |
| E2a | `feasibility_mc.py` v1, first run | superseded | discarded | **Modelling bug**: loss halts summed gross losses instead of net P&L, and the run did not stop at a 15% drawdown. Results discarded, logged here for honesty. | no |
| E2b | `feasibility_mc.py` v1, second run | superseded | discarded | Net-P&L halts fixed; still no drawdown stop. Discarded. | no |
| E2c | `feasibility_mc.py --runs 2000 --seed 7` (v1) | `1b6892986a2bd0fb068f63eea42107f10d595721d41b362ee0a9a949866e42b8` | `research/data/feasibility_mc_seed7.txt` `6c1863609da808e85df99c59f6030995f9e818debeb2232dfc4070b2099945b6` | v1 section 11. **Superseded by E5.** | no |
| E3 | `gate_power.py --sims 4000 --seed 11` (v1) | `b6f006a260be7acfbd6104f224555fba25d46874a83335170812b320a4408e44` | `research/data/gate_power_seed11.txt` `c1e98cf0682bbc0782dd0d381485c052ecaa12a86e50964dad4e59778fe85c77` | v1 C1-C5. **Superseded by E6.** Its section D covered position clustering only (BT-4). | no |
| E4 | `hl_sample.py --selftest` (v1) | `bf059a6d9aa26bcc8797f1e2b1aaff372866df1ca11bc3df2c9034669adb81f2` | stdout | `selftest OK`. The v1 test did not cover BT-1, BT-2 or BT-3. **Superseded by E7.** | no |
| E5 | `feasibility_mc.py --runs 2000 --seed 17` (v2): 6 scenarios × 2 true means | `ed4ef414e3dda9d3f084a6360c7c62985ef96a03dafaa8b0b7147a2a7e60f3eb` | `research/data/feasibility_mc_seed17.txt` `a3b530d22ff1bde9cde4abcf2f537c2f1cfeadf90406b1538e0d70248d9452ad` | Section 11 and 5.9 (joint P(PASS)). Runtime 98 s. | no: 12 sensitivity cells of the synthetic model |
| E6 | `gate_power.py --sims 4000 --boot 1000 --seed 23 --jobs 3` (v2) | v2: `3d2caa0ab8e7ba11aecb4af665ffdba41631d9e0d8833e36cb7ad0e06a75759d`. **Current v2.0.1** (A1.7: the docstring now cites section 5.3 instead of 5.0; no code change): `aa9348eb684f3d19209e56ae03a08266d1171721e1dd8df4b5a78df6113d442a` | `research/data/gate_power_seed23.txt` `5a3a1b5da70d219d3c26780a86762a33174c60fe15213841ad51d0dad820a59b` | 5.9 and the key numbers below. **(A2.7)** Section D2's P2 + P2c rows use k = 20 synthetic B0d replications per trade, not 1,000. Runtime 7 min 46 s wall time on 3 processes. **Re-run 2026-09-29 with v2.0.1 (`--jobs 2`, 10 min 46 s): byte-identical output.** | no |
| E7 | `hl_sample.py --selftest` (v2) | `280af27baaf8394f38020852785d0743440cb1cee948d5de30da80abb3fcfd7e` | stdout | **Superseded by E12.** `selftest OK (13 checks)`. Covers the sparse-wallet rate (BT-1); truncation flag and denominator (BT-1); no prior account value, excluded and counted, never a later value (BT-3); selection sees only fills ≤ t_sel and measurement only opens ≥ t_sel (BT-2); mirrored adds, below-$10 and capped adds (BT-16); the PO $10 partial rule; cheap gates (BT-16); Kaplan-Meier censoring (BT-16); dispersion; ATR without look-ahead; drift sign; rate budget; and an end-to-end offline run with a fake client. **Never run against the live API.** | no |
| E8 | Re-probe the Hyperliquid API, 2026-09-29 ~17:05 UTC | n/a | n/a | Still blocked: CONNECT 403, organization policy. A web search confirmed the `userRole` role values (user, agent, vault, subAccount, missing) in third-party docs. Weights for `userRole` and `portfolio` are assumed at 60 and 20 (conservative). | no |
| E9 | Code smoke tests: `gate_power.py --sims 200 --boot 200 --seed 99`; `feasibility_mc.py --runs 100 --seed 5` | the v2 scripts (before E5/E6) | not kept | Used only to check that the code runs. The numbers were seen but are **not reported and not used**. | no |
| E10 | `few_clusters.py` (seed 31 inside the script; 2,000 sims, B = 1,000 per cell): the frozen rule when the 300 trades fall on 5, 8, 10 or 15 UTC days. Also a 200-run instrumentation of E5's model (seed 123, not kept) measuring the days to the 300th open: median 8 (optimistic), 21 (base), 23 (base correlated), 43 (3-5 traders). | `bf573a2bd973022981c15aae5e3dbdf01b33c6c41fdb5a42e55538fb00409f25` | `research/data/few_clusters_seed31.txt` `bcb404021cbaf9b59e8959fd55dbbd2ef4b60196fc676d8de8e516c6e9cbef16` | Sets `eval.min_day_clusters` = 5, replacing the 10 drafted before this run. **(A2.7)** Its P2c column uses k = 20 synthetic B0d replications per trade. That is a method choice made on synthetic data, before any real result. Key numbers are below. | no |
| E11 | `b0d_cost_fr6.py` (seed 41 inside the script; 2,000 sims, B = 1,000 per cell; 2 processes; **each trade's B0d mean from k = 20 synthetic replications, not 1,000, A2.7**). Two parts: (1) P2 + P2c at zero net timing value in a trending month, with the corrected B0d cost vs the superseded v2 wording (BT2-1); (2) how often FR6 fires given a frozen-P2 pass (BT2-8). | v1.0: `f0253d92ed29b4d38ce1256741acef126c1a9ef46db2d4fd13901ddc53c20853`. **Current v1.0.1** (A2.7: the docstring discloses k = 20; no code change): `8078673aea7684076e919524b14d36bdd062d1ff3fcea16ab117dfbd1ea70d8c` | `research/data/b0d_cost_fr6_seed41.txt` `63813d969ba38d4a5cb91f9a8adb0a880dcb6fce28d39e35638a0251d524606b` | **Corrected rule: P2 + P2c 0.1-0.5%.** Superseded: 0.3-1.8% at a 0.05R delay cost and 0.8-6.4% at 0.10R, rising with the trend (5.9). P2 alone in a trending month: 8-34%. FR6 fired in 0 of the passing runs in all 12 cells (upper 95% bounds 0.4-3.6%). Runtime 1 min 49 s. Run once, with no smoke run before it. **Re-run 2026-09-29 after the A2.7 docstring change, twice (an intermediate docstring draft, then v1.0.1): byte-identical output both times (1 min 46 s).** | no: a check of the rule, not of the strategy |
| E12 | `hl_sample.py --selftest` (v2.1, BT2-6, BT2-7) | `88992c74a8fc85700eb71baa97f2b6a19c4ce8fd2063aa6869dd85ce4cc9616b` | stdout | `selftest OK (18 checks)`. Adds five checks: (14) cursor = max time plus dedupe keeps fills sharing the page-boundary millisecond, a stuck page is flagged and ends, a descending page is detected; (15) the second truncation rule (full page and first fill > start + 1 day); (16) the role gate fails closed (`unknown`, empty; `subAccount` passes); (17) an unknown role is excluded and counted end to end; (18) `summary.json` holds per-wallet first/last fill ms, pages, unique fills, duplicates = full pages, the ascending check, and the leaderboard month check. **Mutation check:** four mutants were each run against the self-test (cursor back to max + 1; role gate fail-open; second truncation rule removed; ascending check forced true). All four fail it. **Never run against the live API.** | no |
| E13 | `eval_reference.py` (reference implementation of A1.3; test vectors). **Superseded by E14 (A2.7).** | `30fc0522a9935310853a7c8d46eeaac05101e0b9242f3ad9d4ae9a526502e932` | `research/data/eval_reference_vectors.txt` `f335b6c2182b01fc21ea5c676d25e47c583b3adb1f3f4b53727978d0d893f294` | `selftest OK`; two runs are byte-identical. The toy sample (30 trades on 6 days) shows the percentile day bootstrap far narrower than t at few clusters, as E10 found, which is why the rule takes the minimum. | no |
| E14 | `eval_reference.py` v2 (A2.1, A2.3 a, A2.7): section labels fixed; the shadow exit as the evaluation close (`eval_close_ms`, `t_eval_ms`, `hold_ms`, `is_marked`); `D_i = min(R_i, 0, R_i − B̄_partial)` with the last-resort step; the seed must be 32 raw bytes; **golden asserts** for every printed vector. New vectors: RNG rejection (n = 2^63 + 1; blocks rejected at i = 0 and 4), the percentile floor at a non-integer B·α/2, unequal cluster sizes, the order-statistic neighbours of a 40-cluster sample, D_i, and `/flatten`. | `570b152ae4b483663154bfa2dabc03863e5134d1bf43566f5bc81c14022859bc` | `research/data/eval_reference_vectors.txt` `fbe80bb0ee65b785ed8fe16743debf250830fd4a9ded883286345c67fe828b8f` | `selftest OK (golden vectors asserted)`; two runs byte-identical; about 5 s. The E13 lines are unchanged and now asserted: the RNG list, day clusters, toy CIs and B0d draws are the values the auditor reproduced independently in round 3. **Mutation check:** 10 mutants, all fail the self-test: bootstrap lower index +1; upper index +1; percentile index rounded up; D reverted to `min(R, 0)`; flattened trade closed at its real close; hex-text seed accepted; open shadow not marked; RNG without rejection; bootstrap mean of cluster means; cluster-robust t without G/(G−1). Before the rejection and non-integer-index vectors were added, the no-rejection and rounded-index mutants survived; the mean-of-cluster-means mutant is equivalent on the equal-size toy sample. That is why those vectors exist. | no |

**Strategy variants tried on real data: 0.** The variant budget in 5.8 is untouched. **Paper runs started: 0.** The run register lives in the ledger and in `run-register.md` (A1.3 h), not in this file.

**Key numbers from E6** [EXPL; clipped-normal R unless stated; brackets are Wilson 95% Monte Carlo intervals]:

| Topic | Result |
|---|---|
| CI half-width at n = 300 (SD 1.0 / 1.2 / 1.5R) | 95%: ±0.113 / 0.136 / 0.170R. 96%: ±0.119 / 0.142 / 0.178R. 99%: ±0.149 / 0.178 / 0.223R. |
| True mean R for 80% power (iid; SD 1.0 / 1.2 / 1.5R) | 96%: 0.17 / 0.20 / 0.25R. 99%: 0.20 / 0.24 / 0.30R. |
| Power at +0.10R, iid trades (realised SD 0.86R / 1.05R) | 96%: 0.431 [0.416, 0.446] / 0.297 [0.283, 0.311]. 99%: 0.238 / 0.133. |
| Peeking (95% t, zero edge) | Single look 1.9% [1.6, 2.4]. Every 10 trades, 30 to 300: **8.9%** [8.1, 9.9]. Every 10 trades, 300 to 600: 5.5%. |
| v1 model, position clusters only, zero edge (section D; 2,000 sims) | Naive t 5.8-7.6%. v1 rule 1.8-2.5% (v1 reported 1.6-2.4% from 500 sims). |
| **D2, zero edge**: day-factor corr 0 / 0.2 with 70% long / 0.3 with 80% long / 0.5 with 80% long | Naive 95%: 4.5 / 6.9 / 9.8 / **13.3%**. v1 rule: 2.2 / 3.1 / 5.1 / **8.0%**. **Frozen P2 at 96%: 1.3 / 1.3 / 1.1 / 1.2%.** Frozen at 99%: 0.2-0.3%. **Frozen P2 + P2c at 96%: 1.2 / 0.7 / 0.3 / 0.1%.** |
| **D2, +0.10R**: same four settings | Naive 95%: 41 / 40 / 43 / 42%. Frozen P2 at 96%: 22 / 17 / 13 / 10%. **Frozen P2 + P2c at 96%: 20 / 13 / 5.6 / 2.9%.** |
| α split (section G; iid, SD 1.2 pre-clip) | Zero edge: run 1 1.2%; within 2 runs **1.6%** [1.3, 2.0], against 3.2% for two runs at 95%. +0.10R: run 1 34%, within 2 runs 45%. +0.15R: 67% and 81%. |
| Heavy tails (section H; 6% loss tail to −2.5R, 6% Pareto win tail to +12R; realised SD 1.74R) | Power at +0.10R (96% t): **10%** [9.1, 11.0], against 44% for the clipped normal. +0.15R: 23%. Zero-edge false PASS 1.1%. |
| Fragility checks FR1 / FR2 (section H) | Given a pass, a flag fires in ≤ 0.1% of homogeneous-edge runs. It fires in 3.5% of runs where one leader with 35% of trades carries all of the edge. The checks cost almost no power, but they catch only extreme concentration. |
| **Few day clusters (E10)**: 300 trades on 5 / 8 / 10 / 15 days | Frozen P2 at 96%, zero edge: 0.9 / 1.5 / 1.1 / 1.6% (no beta); 0.7-1.0% (corr 0.3, 80% long). The percentile day bootstrap **alone** is 6.4% at 5 days (anti-conservative). Power at +0.10R, no beta: 13 / 16 / 17 / 19%. Hence `eval.min_day_clusters` = 5, not 10. |
| Luck (section E) | E[max z] = 2.77 (N = 200), 3.45 (N = 2,000), 4.12 (N = 30,000). SR0 is 0.21-0.31 per day at T = 180 days and 0.51-0.75 per day at T = 30 days. |
| Mean R vs USD (section F toy) | Mean R +0.29R, but USD −$6 and risk-weighted mean R −0.40R |

## 13. Concerns for the PO: status after the PO's decisions

| ID | Concern (v1) | Status |
|---|---|---|
| C1 | Trader shares counted as independent overstate N | **Resolved:** the day-clustered CI (P2 method). Day clusters nest merged positions and also absorb same-day beta (BT-4). |
| C2 | Peeking | **Resolved [PO]:** one evaluation of the first 300 opened; no interim statistics (5.5); at most 2 runs with an α split (5.4). |
| C3 | Mean R positive while the account loses money | **Resolved [PO]:** P2b, USD P&L > 0 |
| C4 | R understates risk when the leader adds | **Resolved [PO]:** initial-risk R gates; R_maxrisk is reported, and FR5 flags it |
| C5 | Low power | **Accepted.** The frozen rule has even lower power (5.9), and INCONCLUSIVE is the most likely honest outcome. |
| C6 | 1% risk plus the 15% DD FAIL | **Resolved [PO]:** 0.5% risk. DD failure at +0.10R is about 0.1-0.5% (E5). |
| C7 | 300 trades in 30 days uncertain | **Resolved [PO]:** extension to 60 days with one evaluation |
| C8 | Paper $300 does not transfer to $100 live | **Resolved [PO]:** live ≥ $300 |
| C9 | Partials below $10 | **Resolved [PO]:** skip and log; close all if the remainder is below $10 |
| C10 | Our stops change the leader's payoff | Method: copy-replay R (M14) |
| C11 | DSR with N = 15,000 may leave fewer than 5 eligible | **Open (awareness).** The 3-5 trader scenario (section 11) shows the consequence. Don't loosen gates mid-run (K7). |
| C12 | Pre-recording replay is survivorship-biased | Method: kill checks only (K1) |
| C13 (new) | **Joint P(PASS) at a true +0.10R is at most about 0.3 in run 1**, and lower with correlated trades, few leaders or fast accumulation | PO awareness. Nothing to decide: this is the price of a gate that is hard to fool. |
| C14 (round 2) | The precision choices in section 14 were never signed by the PO. Together they roughly halve power: at +0.10R with merged positions, run 1 is 20% against 41% for a naive 95% t, and run 2 is about 9% (no beta) and 3-6% (with beta) before P2c **(A2.5; v2 + A1 said 13-24%, the iid figure)**. A2.4 adds three items (6-8). | **Pending PO acknowledgement** (section 14, eight items) |

## 14. Items pending PO acknowledgement (BT2-5; A2.4, A2.5)

Q1-Q9 are answered and encoded in 5.2. The eight items below are research choices, or plain consequences of the rules, that interpret or tighten your decisions. You haven't signed them yet. (A2.4: v2 + A1 listed five; items 6-8 and the closing note are new, and every item is reworded in plain language.)

- **Status of each:** pending PO acknowledgement.
- **Who records the answer:** the CTO, in `docs/product/decisions.md`.
- **Where your "95%" comes from (A2.5):** the brief, `01-brief.md` lines 27 and 127. D11 in `decisions.md` says "CI lower bound > 0" and gives no level.
- **Precondition:** run 1 must not start until all eight are acknowledged or replaced (8.1).
- **If you reject an item:** it is changed by a further dated addendum before run 1. What would change is stated under each item.

**Words used below:**
- **R:** a trade's profit or loss divided by the amount it planned to risk. "+0.10R per trade" means that, on average, each trade earns a tenth of what it risked, after all costs.
- **Run:** one paper-trading test, judged once on its first 300 trades, which must open within 60 days. You allowed at most 2 runs.
- **Pass by luck:** a strategy with no real edge that passes anyway.
- **Market ties:** trades that are open at the same time, or that ride the same market move, win and lose together. That makes 300 such trades worth less evidence than 300 independent ones.

**1. Stricter confidence per run: 96% in run 1, 99% in run 2.** (A2.5 corrects the run-2 figures.)
- **What it means:** You asked for 95% confidence. Because you also allowed two runs, a strategy with no edge gets two chances to pass by luck. Run 1 is judged at 96% and run 2, if there is one, at 99%. That keeps the total chance of passing by luck at 2.5% or less, the same as a single test at your 95%. In our simulations the total came out at 1.6%.
- **The price:** a real but small edge (+0.10R per trade) is hard to prove.
  - Run 1: it passes about 20 times in 100 when the trades have no market ties, and only about 3 to 13 times in 100 when they do.
  - Run 2: about 9 times in 100 without market ties, and about 3 to 6 times in 100 with them. These run-2 figures don't yet include the baseline test in item 5, which can only lower them.
  - Earlier drafts said 13-24% for run 2. That figure assumed fully independent trades and was 2 to 4 times too high.
- **Replaces or interprets:** your 95% from the brief, plus your "at most 2 runs".
- **If you say no:** two runs at 95% each. A no-edge strategy then passes one of them about 3.2 times in 100 instead of 1.6, roughly double. Run 2 becomes as easy to pass as run 1.
- **Status:** pending PO acknowledgement.

**2. Use the most cautious of three ways to measure the uncertainty.**
- **What it means:** The verdict looks at the average R per trade and at how uncertain that average is. There are three standard ways to measure the uncertainty:
  - one treats every trade as independent
  - one reshuffles whole trading days
  - one groups trades by day

  Each can be too optimistic in some situations. For example, reshuffling days is too optimistic when the trades fall on only a few days. We always use the most cautious of the three.
- **The price:** it keeps the chance of passing by luck at or below target, and costs some ability to detect a real edge.
- **Replaces or interprets:** your "confidence interval clustered by UTC day", which didn't say which method.
- **If you say no:** we would use one method. With trades on only 5 days, the day-reshuffling method alone lets a no-edge strategy pass about 6.4 times in 100, instead of about 1.
- **Status:** pending PO acknowledgement.

**3. The 300 trades must fall on at least 5 different days.**
- **What it means:** Trades opened on the same day tend to win or lose together, because they ride the same market. If the 300 trades fall on fewer than 5 different calendar days (UTC), the uncertainty can't be measured reliably. The verdict is then INCONCLUSIVE: never a pass, and never a fail on the numbers. The run can still fail on the 15% drawdown limit or a missed exit.
- **Replaces or interprets:** nothing; your decisions didn't cover this case.
- **If you say no:** no minimum. With 2 to 4 days, a pass or a fail would rest on a measurement that is unreliable in both directions.
- **Status:** pending PO acknowledgement.

**4. Judge the run no later than 7 days after the 300th trade opens.**
- **What it means:** You decided the run is judged once, after all 300 trades have closed. We propose to judge it when the last of the 300 closes, or 7 days after the 300th trade opened, whichever comes first.
  - A trade still open at that moment is valued at the market price minus the exit fee and half the spread, as if it had closed then.
  - The bot keeps managing it normally. Its real result is reported separately and never changes the verdict.
- **Why:** without a cap, one long-held position could delay the verdict without limit.
- **Replaces or interprets:** your "evaluated once, after all have closed".
- **If you say no:** no cap. The verdict waits for the last close, however long that takes.
- **Status:** pending PO acknowledgement.

**5. "Beating the baseline" means clearly beating it, not just on average.**
- **What it means:** You asked that our trades beat a baseline that trades the same coins in the same direction, but at random times. The baseline separates skill at picking the moment from simply riding the market: in a rising month, buying at random times also makes money.
  - We read "beating" strictly: we must be confident (96% in run 1, 99% in run 2) that our advantage per trade over the baseline is above zero.
  - Beating the baseline's average is not enough, because a bot that only rides the market does that about half the time by luck.
- **The effect:** with the strict reading, a bot that only rides the market passed the full test at most about 1 time in 200 in our simulations. The baseline pays the same fees and spreads as we do, but not the cost of our copy delay. So if our delay eats our advantage, this test fails, as it should.
- **Replaces or interprets:** your "beat a direction-matched, random-time baseline".
- **If you say no:** a simple comparison of averages. A bot that only rides the market passes this check about half the time.
- **Status:** pending PO acknowledgement.

**6. An emergency code change during a run usually uses up that run, and waiting for a ruling counts as downtime.** (New, A2.4.)
- **What it means:** If the bot's code has to change during a run, for example to fix a bug, the change is logged and the backtest-auditor decides whether the run can continue.
  - A change to how the bot picks, filters, sizes, exits or prices trades ends the run as ABORTED by default. The auditor lets the run continue only if replaying the run so far through the old and the new code gives exactly the same trades and results.
  - An aborted run counts as one of your 2 runs, as you already decided for a config change.
  - Until the auditor rules, only the old code runs, including for open positions. You may pause new entries while waiting, but paused time counts as downtime.
  - A run with more than 2% downtime can't pass. That is about 14 hours in a 30-day run, less in a shorter one, and about 32 hours at the longest possible run (60 days plus the 7-day close-out).
  - The kill switch and `/flatten` always work.
- **Replaces or interprets:** extends your rule "a config change mid-run restarts the run and counts as a run" to code changes, and your 2% downtime rule to time spent waiting for a ruling.
- **If you say no:**
  - If aborted code changes didn't count as runs, more than 2 runs would be possible. Each extra run is another chance to pass by luck (up to about 0.5 in 100 more per extra run at 99%), so the 2.5% limit in item 1 would no longer hold. The rulebook would then need another change before run 1, with a stricter level for every run.
  - If waiting time didn't count as downtime, the bot could sit out parts of the market and still be judged as if it had traded through them.
- **Status:** pending PO acknowledgement.

**7. A manual `/flatten` can only count against the result.** (New, A2.4; A2.1.)
- **What it means:** `/flatten` closes positions. It is a safety action and is always allowed. For the verdict, each trade closed this way counts at the worse of two results:
  - what it actually made
  - what it would have made if the bot had kept managing it (the "shadow" result, simulated on recorded market data)

  The run is also judged as if those trades had stayed open until their shadow closed, so a flatten never ends or shortens the run. Manual action can protect your money, but it can never improve the verdict.
- **Replaces or interprets:** nothing you decided; it follows from your "safety actions are always allowed".
- **If you say no:** a flattened trade would count at its actual result. You could then close trades while they happen to be in profit, or end the run at a moment of your choosing. The verdict would partly measure your decisions, not the bot's, and the 2.5% limit on passing by luck would no longer hold.
- **Status:** pending PO acknowledgement.

**8. Gaps in our market recordings can make the run INCONCLUSIVE.** (New, A2.4; A2.3.)
- **What it means:** The baseline test in item 5 needs our own recordings of the order book and prices for each trade's coin. If a trade's recordings have too many gaps to build its baseline, that trade can only count against us: at most zero, and lower if a partial baseline shows the market was carrying it.
  - If more than 10% of the 300 trades (more than 30) lack a proper baseline, the baseline test fails. The verdict is then INCONCLUSIVE even if the bot made money, and the run still counts as one of your 2.
  - Before run 1 we report how often the recorder had gaps during the 24-hour dry run and the first week of recording, so you can judge this risk. If the gaps come near the 10% line, the recorder gets fixed before run 1.
- **Replaces or interprets:** your "market data recorded from day 1" and "beat a direction-matched baseline".
- **If you say no:** trades without a proper baseline would simply be dropped. The gaps tend to hit long trades that ride the market, which are exactly the trades this test is meant to catch. A bot that only rides the market would then pass more often than the 1 in 200 stated in item 5.
- **Status:** pending PO acknowledgement.

**Note: the baseline test is permanent in this epic (A1.4, binds future addenda).**
- No later change to this rulebook in this epic can remove, weaken or make optional the baseline test in item 5. That includes a change made before run 1.
- The luck limit in item 1 depends on it. Without it, the main test alone lets a no-edge bot pass up to about 4 times in 100 when trades are held across midnight.
- Acknowledging the items above includes this note.
- **If you say no:** the only honest way to drop the baseline test is a new epic, with a new rulebook and new data.

## 15. Backtest-audit findings: closure

| Finding | Severity | Closed by |
|---|---|---|
| BT-1 | BLOCKING | `hl_sample.py` v2 `measure_wallet`: the rate uses the observation window. When ≥ 9,000 fills suggest cap truncation, it uses first fill → end with `measurement_window_truncated` flagged. Self-test checks 2 and 3 (sparse wallet = 1/30 per day, not 24). |
| BT-2 | BLOCKING | `hl_sample.py` v2 selects at `t_sel = end − 30 d`. The pool uses leaderboard P&L earned before the last 30 days, the gates use portfolio points and fills ≤ t_sel, and measurement uses only opens ≥ t_sel. Win rate and P&L are renamed `fwd_leader_*` and labelled post-selection and survivorship-biased. Self-test checks 5 and 13. |
| BT-3 | BLOCKING | `value_at` returns the latest point ≤ t or None. There is no fallback to the current account value. Opens and adds without a prior point are excluded and counted. Self-test checks 4 and 13 (a wallet that is large now but small at t_sel is excluded). |
| BT-4 | BLOCKING | The P2 method is now min(iid t, UTC-day cluster bootstrap, UTC-day cluster-robust t with G−1 df), with day clusters nesting merged positions (5.3). The small-cluster issue is handled by the CR t with G−1 df, and G ≥ 5. E10 shows false PASS ≤ 1.6% from 5 days, while the percentile bootstrap alone undercovers. The `gate_power.py` docstring is corrected, and section D2 quantifies the fix (5.9, E6). |
| BT-5 | BLOCKING | The pre-registration is frozen with a hash in the run record (5.1), and the Q1-Q9 answers are recorded (5.2). At most 2 runs with α 0.04 / 0.01 (5.4). Aborted runs count, and the run register is logged. No interim statistics, and interim numbers can't justify config changes (5.5). |
| BT-6 | ADVISORY | Joint P(PASS) row in 5.9 and joint columns in section 11 (E5) |
| BT-7 | BLOCKING | B0d, the direction-matched random-time baseline, is pre-registered as P2c, a lower-bound test on the excess (6.2). K9 fires if **either** B0d or S4 fails (7). E6 D2 shows the effect. |
| BT-8 | ADVISORY | Drawdown columns are labelled lower bound (realised) and upper bound (pessimistic MTM). A correlated-R scenario is added (section 11). |
| BT-9 | ADVISORY | $10 and halt figures corrected, with denominators (section 11) |
| BT-10 | ADVISORY | 3-5 trader, no-floor scenario added. 100-300 is labelled a prior-driven judgement (section 11). |
| BT-11 | ADVISORY | E6 runs 4,000 sims per cell (2,000 in the v1-model section D) with B = 1,000, and reports Wilson intervals for every rate |
| BT-12 | ADVISORY | Heavy-tail sensitivity in E6 section H. Fragility checks FR1 and FR2 are pre-registered (5.6). |
| BT-13 | ADVISORY | Cost-in-R table (6.3). Cost-fragile rule FR3 / K12. Spread recorded at signal time used in replays. |
| BT-14 | ADVISORY | First 300 **opened** [PO]. P3 window = `[t0, T_eval]` (5.3). |
| BT-15 | ADVISORY | sha256 of every cited output and script (section 12). Path fixed in 10.1. Outputs not committed. |
| BT-16 | ADVISORY | `hl_sample.py` v2: Kaplan-Meier holds and censored counts; mirrored adds; the PO partial rule; cheap gates (HLP, `userRole`, account value, age, maker share, hold, round trips, liquidation, selection P&L); per-wallet dispersion; 16 wallets (8 top, 8 random); a 2×ATR(1h) stop instead of a fixed 2.5% (fallback flagged); 0.5% risk. Drift remains coarse at 1 minute (labelled). |
| BT-17 | ADVISORY | Daily-return resolution rules and `dsr_resolution` record (10.1); property test 14 (10.7) |

**Round 2 (`backtest-audit-r2.md`), closed by Addendum A1 (5.10) and `hl_sample.py` v2.1:**

| Finding | Severity | Closed by |
|---|---|---|
| BT2-1 | BLOCKING | A1.1. B0d pays fees, plus spread and impact at its own fill times, plus its own ack-delay drift and funding; never post-signal decay (6.2, 6.3). The rationale is rewritten as a decomposition: D ≈ net timing value after our delay. E11 quantifies the old wording's inflation: false PASS 0.3-6.4% against 0.1-0.5% corrected. Evaluation test 10. |
| BT2-2 | BLOCKING | A1.2. The run record gains the engine commit, dirty flag, lockfile hash and Python version; a dirty tree can't start a run (5.1). Every mid-run deploy is logged with its full diff and needs an auditor ruling before its code runs. Logic changes are ABORTED by default, with CONTINUE allowed only on an identical replay (5.3, 8.1, `run-register.md`). Evaluation test 11. |
| BT2-3 | ADVISORY | A1.3 in 5.3, 5.4 and 6.2:<br>(a) the precedence list<br>(b) the bootstrap statistic (pooled mean), the integer percentile index, the SHA-256 counter RNG, and rounding to 1e-6<br>(c) transitive overlap components<br>(d) `/flatten` counts `min(realised, shadow)`, with P3 on both curves<br>(f) marked-trade hold and funding<br>(g) B0d admissibility, delistings, and missing windows as `min(R, 0)`, with P2c failing above 10% missing<br>(h) the register in the ledger and `run-register.md`<br><br>The reference implementation and test vectors are E13. Evaluation tests 12-18. |
| BT2-4 | ADVISORY | A1.4. The under-coverage of P2 alone is stated in 5.9 (the auditor's numbers). P2c is non-removable (5.1). Non-gating cross-day diagnostics at `T_eval` (5.3). Evaluation test 20. |
| BT2-5 | ADVISORY | A1.5. The "PO" label for the α split is corrected (9.2). Five items are marked **pending PO acknowledgement**, with exact wording (section 14), and are a precondition for run 1 (8.1). The CTO records the PO's answer in `decisions.md`. |
| BT2-6 | ADVISORY | `hl_sample.py` v2.1:<br>(a) a second truncation rule: a full page and the first fill more than 1 day after the start<br>(b) cursor = max time, plus dedupe<br>(c) roles other than user/subAccount fail closed as `role_unknown` and are counted<br>(d) per-wallet `fetch` metadata in `summary.json`: first and last fill ms, pages, full pages, returned rows, unique aggregated fills, duplicates, the ascending check, and the stuck-page flag<br><br>Aggregate `fetch_checks`. Self-test checks 14-18 (E12), with a mutation check. README updated. |
| BT2-7 | ADVISORY | `hl_sample.py` v2.1 `month_pnl_check`. For every pool wallet it logs the leaderboard `month.pnl`, the portfolio `perpMonth` and `month` P&L change, the window start and its age in days. The aggregate is `leaderboard_month_check`. The PO's single run will show whether the pool ranking is pre-`t_sel`. |
| BT2-8 | ADVISORY | A1.6. FR6, a go-live blocker: mean R without the best UTC-day cluster ≤ 0 (5.6). S6, weekly mean R (5.7). E11: FR6 costs essentially no power under a homogeneous edge. Evaluation test 19. |
| BT2-9 | ADVISORY | A1.7: 0.001-0.015 (5.9), the E6 backticks, and the `gate_power.py` docstring now citing 5.3 (output re-verified in the E6 row). |

**Round 3 (`backtest-audit-r3.md`, VALID), closed by Addendum A2 (5.11):**

| Finding | Severity | Closed by |
|---|---|---|
| BT3-1 | ADVISORY | A2.1. A flattened trade's shadow exit is its close for `T_eval`, `hold_i`, merged positions, B0d and P3; an open shadow at `t300 + 7 days` is marked (5.3, 6.2, 9.2). Tests 2 and 15; E14 flatten vector and mutant M5/M7. |
| BT3-2 | ADVISORY | A2.2. Engine path set (manifest) scopes the dirty flag; a dedicated worktree pinned to the run commit; only the recorded commit runs until a ruling, paused or not; the run record hashes the installed-package list and every non-config data input; deploys compare six things (5.1, 5.3, 8.1, 9.2, `run-register.md`). Test 11. |
| BT3-3 | ADVISORY | A2.3. (a) `D_i = min(R_i, 0, R_i − B̄_i^partial)` with a three-step B̄_i^partial; the false "gaps can't help" claim corrected; the recorder gap rate reported before run 1 (5.3, 6.2, 8.1, 9.2; test 16; E14). (b) B0d R from fill prices; drift and spread are a reported decomposition, never added (6.2, 6.3, 9.2; test 10). |
| BT3-4 | ADVISORY | A2.4. Section 14 items 6-8 and the A1.4 note, all in plain language with an "if you say no" consequence; header, 8.1 and C14 say eight items. |
| BT3-5 | ADVISORY | A2.5. Run-2 power ≈ 9% (no beta) and ≈ 3-6% (beta), before P2c (section 14 item 1, C14, new 5.9 row); the 95% cited from `01-brief.md:27,127` (section 14, 9.2, A1.5 row). |
| BT3-6 | ADVISORY | A2.6. v2 recorded as commit `1eba7c6`, sha256 `36e35a032a6792a6182903e34872d7d0370118647b5789595e4e366e68a26fb1` (5.10, 5.11); every A2 replacement is quoted verbatim in 5.11. |
| BT3-7 | ADVISORY | A2.7. `eval_reference.py` v2: labels fixed, golden asserts, discriminating vectors, 10-mutant check (E14). The seed is 32 raw bytes (5.1, 5.3, 9.2, test 13). k = 20 disclosed for E11, E6 D2 and E10 (5.9, section 12, `b0d_cost_fr6.py` v1.0.1). |

## Sources

- [Hyperliquid 10,000-trader analysis (73.8% losing, Nov 2024)](https://medium.com/@envyprotocol/i-analyzed-10-000-hyperliquid-traders-the-results-are-brutal-a29adcca8c2a)
- [Only 166 of 1,000 Hyperliquid traders profitable](https://www.thecoinrepublic.com/2025/06/16/hyperliquid-crypto-only-166-of-1000-traders-profitable-whats-going-on/)
- [userFillsByTime limits (Chainstack)](https://docs.chainstack.com/reference/hyperliquid-info-user-fills-by-time)
- [userRole (Chainstack)](https://docs.chainstack.com/reference/hyperliquid-info-user-role)
- [Info endpoint overview incl. userRole (Alchemy)](https://www.alchemy.com/docs/chains/hyperliquid/hyperliquid-info-endpoint)
- [Hyperliquid S3 backfill discussion](https://github.com/tribulnation/sdk/issues/1)
- [portfolio endpoint (QuickNode)](https://www.quicknode.com/docs/hyperliquid/info-endpoints/portfolio)
- [Leaderboard payload (Apify)](https://apify.com/gochujang/hyperliquid-leaderboard)
- [Hyperliquid fees overview](https://hyperliquidguide.com/guides/fees)
- [Order precision and minimum order value (Chainstack)](https://docs.chainstack.com/docs/hyperliquid-order-precision)
- Bailey & López de Prado (2014), "The Deflated Sharpe Ratio"
- Cameron, Gelbach & Miller (2008), "Bootstrap-based improvements for inference with clustered errors"
- Apesteguia, Oechssler & Weidenholzer (2020), Management Science
- Heimer & Imas (2022), Review of Financial Studies
