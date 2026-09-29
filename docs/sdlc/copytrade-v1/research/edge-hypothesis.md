# Edge hypothesis: copytrade-v1

Date: 2026-09-29. Author: quant-researcher. Version: **v2 + Addenda A1, A2, A3 and A4** (all dated 2026-09-29, written before run 1 and before any real result).

Status: **PRE-REGISTRATION FROZEN.** No result on real data exists yet. No paper run has started.
- v2 encodes the PO's research-phase decisions and closes backtest-audit findings BT-1 to BT-17. The closure table is in section 15.
- **Addendum A1 (5.10)** closes round-2 audit findings BT2-1 to BT2-9. It follows the 5.1 addendum rule: every change to frozen text is listed in 5.10 with the v2 wording it replaces, and the amended text is in place, marked `(A1.n)`.
- Section 5 is the frozen pre-registration. Section 5.1 says how it is frozen and how it can legitimately change.
- **Addendum A2 (5.11)** closes round-3 audit findings BT3-1 to BT3-7 (all ADVISORY; the round-3 verdict was VALID). It follows the same rule: every replaced text is quoted verbatim in 5.11, and the amended text is in place, marked `(A2.n)`.
- **Addendum A3 (5.12)** encodes the PO's spec-review decisions A4 (missed exits) and A14 (`/stats`), pins two definitions that the spec-review decisions A6 (liquidity tiers) and A10 (compressed, uploaded recordings) touch, and records that A2 (automatic leverage) needs no rule change. It follows the same rule: every replaced text is quoted verbatim in 5.12, and the amended text is in place, marked `(A3.n)`.
- **Addendum A4 (5.13)** closes round-4 audit findings BT4-1 to BT4-10 (all ADVISORY; the round-4 verdict was VALID) and settles four open points from the PM's spec Amendment 2. It follows the same rule: every replaced text is quoted verbatim in 5.13, and the amended text is in place, marked `(A4.n)`.
- **Run 1 must not start until the PO has acknowledged every item in section 14.** **(A4.9)** Items 1-8 were acknowledged on 2026-09-29 (`docs/product/decisions.md`). Items 9 and 10 were acknowledged on their A3 wording the same day; A4 rewrites them, so they are **pending PO re-acknowledgement**.

Inputs:
- `01-brief.md`, `02-discovery.md`, `03-answers.md` (including "Research-phase decisions")
- `docs/product/decisions.md` (2026-09-29 entries)
- `research/brainstorm-domain-research.md`, `research/market-context.md`
- `research/backtest-audit.md` (BT-1 to BT-17), `research/backtest-audit-r2.md` (BT2-1 to BT2-9), `research/backtest-audit-r3.md` (BT3-1 to BT3-7)
- **(A3)** `04-spec.md` §1 (missed-exit definition) and §11 (assumptions), and the six "Spec review" entries of 2026-09-29 in `docs/product/decisions.md` (A2, A4, A6, A9, A10, A14)
- **(A4)** `research/backtest-audit-r4.md` (BT4-1 to BT4-10), and `04-spec.md` Amendment 2 (§11 A20 and A25, F9.AC8, F12.AC9, F17.AC4)

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
- H1 fails when the frozen rule returns FAIL: the CI upper bound ≤ 0, or drawdown reaches 15%, or **(A3.1)** P4 is breached (more than 3 missed exits, or one that cost more than 1R against its mirrored outcome). A FAIL through P4 is an engineering failure, not evidence about the edge (K13).
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
| **Missed exits (A3.1, A4.3)** | count in `[t0, T_eval]` over all trades (in S or not); per missed exit: its class (late, reconstruction failed, orphan), how it was found (live, reconciliation, fill audit), its lag, the trade's actual (realised) R, its mirrored R (stop-first and TP-first), its **incremental cost** and, per trade, the **trade cost** `mirrored hi R − actual R` (5.3, A4.3). Exits settled after a data gap (A4.5) are listed too. Feeds P4 and the go-live blocker ME. |
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
| **`T_eval`** | The moment the last trade in S closes, or `t300 + 7 days`, whichever comes first [QR, PO-ACK pending: section 14 item 4]. **(A2.1)** For a trade closed by `/flatten`, "closes" means its **shadow exit**, never the moment of the flatten. A trade in S still open at `t300 + 7 days` is marked for the gate at the recorded mid, minus taker fee and half-spread at that moment. It is flagged "marked" and keeps being managed normally. Its later real outcome is reported separately and never changes the verdict. **(A2.1)** A flattened trade whose shadow is still open at `t300 + 7 days` is marked the same way: the shadow is valued with that formula, and the marked shadow R is the shadow R in `min(realised R, shadow R)`. **(A1.3 f)** For a marked trade: `hold_i = T_eval − entry fill time`; funding counts through the last hourly funding at or before `T_eval`; R and R_maxrisk use the marked exit; its holding interval ends at `T_eval` for merged positions. **(A3.1)** For a trade with a missed exit, "closes" means the **later of its real close (its shadow exit if also flattened) and its mirror exit** (missed-exit rules below). A mirror still open at `t300 + 7 days` is marked with the same formula. |
| **Missed exit (A3.1)** | A leader exit event missed as defined in `04-spec.md` §1 and made exact in the missed-exit rules below. Each ledgered `missed_exit` record is one missed exit. |
| Evaluation window | `[t0, T_eval]`. P3, P4 and P5 apply to this window. |
| Day cluster | The UTC calendar day of the **first entry fill of the merged position** the trade belongs to. Every share of a merged position is therefore in one day cluster. G is the number of distinct day clusters in S. **(A1.3 c)** A merged position is a connected component (transitive closure) of the overlap graph over the trades in S with the same symbol and direction. Two trades are linked when their closed holding intervals `[entry fill, min(evaluation close, T_eval)]` intersect; touching at the same millisecond counts. **(A2.1)** The evaluation close is the full close, or the shadow exit for a flattened trade, or **(A3.1)** for a trade with a missed exit the later of that close and its mirror exit. If A overlaps B and B overlaps C, then A, B and C are one merged position even when A and C don't overlap. Trades outside S never link trades in S. |
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
| P4 [PO, A3.1, A4.1-A4.4] | At most 3 missed exits in the evaluation window, counted over all trades; no missed exit and no missed-exit trade cost more than 1R against its mirrored outcome (**(A4.3)** the incremental cost of each missed exit and the trade cost, an uncomputable mirror counting as more than 1R); and **(A4.1)** the leader-fill audit of the window is complete (missed-exit rules below). A trade in S with a missed exit counts at min(actual R, mirrored R) in every other condition. |
| P5 [PO] | Downtime < 2% of the evaluation window. Downtime is time when the engine could not open or manage positions (process down, a data gap before resync, the access-degraded pause) plus any manual `/pause`. Rule-based event blackouts are not downtime. |
| P6 [PO] | The point-in-time replay of `[t0, T_eval]`, run through the same engine on recorded data, has a mean R with the **same sign** as the paper mean R over S |

**FAIL** if any of the following holds:

| ID | Condition |
|---|---|
| F1 [PO] | P3 is breached at any time before `T_eval`. The verdict is immediate: the run ends and the bot pauses per the risk rules. |
| F2 [PO, A3.1, A4.4] | P4 is breached by missed exits whose leader events fall in `[t0, T_eval]`, **whenever the breach is found before the verdict**: live, by a daily fill audit, or by the final audit and recomputation after `T_eval`. Its breach time, which always lies in `[t0, T_eval]`, is defined in the missed-exit rules below. A breach found before `T_eval` gives an immediate verdict. |
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
2. **FAIL by F1 or F2.** The breach happened at or before `T_eval` **(A3.1: F2's cost test on marked values is applied at `T_eval`)**. **(A4.4)** For F2 that means its breach time, which lies in `[t0, T_eval]` even when the breach is found after `T_eval`. Item 1 wins over this item only when the ABORTED event is strictly earlier than the breach time; at equal times this item wins. A breach found before `T_eval` ends the run when it is found (entries stop and the bot pauses); one found later changes the verdict only. **(A3.1)** A missed exit that does not breach P4 never ends the run and never changes this order; it enters the verdict only through its min(actual, mirrored) R and its evaluation close.
3. **INCONCLUSIVE, P1 incomplete.** Fewer than 300 trades opened by `t0 + 60 days`.
4. **INCONCLUSIVE, G < 5.** F3 is not evaluated: with G − 1 < 4 df the cluster-robust interval is degenerate, and a FAIL from it would be as unreliable as a PASS. The three CIs are reported as descriptive only.
5. **FAIL by F3.** `UB_r(R) ≤ 0`.
6. **PASS.** P1 to P6, P2b and P2c all hold.
7. **INCONCLUSIVE.** Everything else.

`scripts/eval_reference.py::verdict` implements this order and asserts every adjacent pair (E13; **(A3.1)** E15 adds `p4_breach`, which defines F2, and its cases; **(A4.4)** E16 adds `p4_breach_time` and `run_end`, which resolve items 1 and 2 by time).

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
- **(A3.1) Fixing the cause of a missed exit during a run** is a mid-run deploy like any other. Nothing above is relaxed for it:
  - Until the auditor's ruling is in the ledger, only the recorded commit runs, the one with the bug, for entries and exits. More missed exits in that time count toward P4.
  - Pausing entries while waiting is allowed, and the paused time counts as downtime (P5).
  - A fix to exit, fill or signal-handling logic is ABORTED by default. The CONTINUE test is unchanged: the replay of the run so far must give identical decisions, fills and R for every trade through both commits. A fix that makes the new commit mirror the missed event on replay changes that trade's fill and R, so it fails the test, and the run ends as ABORTED and counts. A fix confined to code that the replay never exercises (for example a live WebSocket resubscription) can pass it.
  - The alternative is to finish the run on the recorded commit and fix the cause after `T_eval`, before run 2 or any live step. Up to 3 missed exits are tolerated, and each counts at min(actual, mirrored) R.
  - Money safety comes first: if the bug makes open positions unsafe, use the kill switch or `/flatten` (min(realised, shadow)), or stop the run (ABORTED).

**`/flatten` inside S (A1.3 d).** `/flatten` (PIN-protected, through the risk gate) is a safety action and is always allowed.
- **Trades stay in S.** The trades it closes stay in S with exit reason `manual_flatten`.
- **Shadow outcome.** The engine keeps managing a **shadow** of each flattened trade on recorded data under the frozen exit rules, until its shadow exit. **(A2.1)** The shadow accrues hourly funding and follows the leader's recorded exits as the real trade would have. Over a gap in our recording, its SL/TP path uses exchange 1h candles, with the stop assumed hit first on an ambiguous bar (section 3).
- **(A2.1) The shadow exit is the trade's close for the evaluation.** `T_eval`, `hold_i`, the merged-position interval (day clusters), the B0d replications' hold and time exit, and P3's shadow equity all use the shadow exit, never the moment of the flatten. A shadow still open at `t300 + 7 days` is marked (`T_eval` row above). A flatten therefore can't end or shorten the evaluation, and choosing when to flatten changes nothing except `min(realised, shadow)`.
- **Gate R.** For the gate, a flattened trade counts with `min(realised R, shadow R)`, and its USD P&L with the same choice. Manual exits can therefore only hurt the verdict.
- **P3.** P3 is checked both on the actual marked equity and on the shadow equity, which has flattened trades replaced by their shadows **and (A3.1) trades with a missed exit replaced by their stop-first mirrors**. A breach on either is F1.
- **Entries after a flatten.** A flatten doesn't pause entries by itself; `/pause` time counts as downtime.
- **Reported:** the number of flattened trades and their realised-minus-shadow R.

**Missed-exit rules (A3.1; PO spec-review decision A4).** They replace "0 missed exits, and any missed exit is an immediate FAIL". **(A4.10)** A missed exit never raises a trade's R or USD P&L in the gate.
- **Missed exit.** A leader exit event (a close, a reduce or a flip) on a coin where we hold that leader's open share, which is one of:
  1. **late:** its exchange timestamp is outside downtime, and **(A4.1)** it is not handled (below) within `exits.missed_exit_max_lag_s` (60 s, part of the frozen config) of it;
  2. **reconstruction failed:** it is inside downtime and was not settled. **(A4.5)** Inside a process-down interval: the restart reconstruction did not settle it. Inside a data gap before resync: it was not handled within `exits.missed_exit_max_lag_s` after the resync;
  3. **orphan:** **(A4.1)** it is found only by leader reconciliation or by the leader-fill audit (below), outside downtime, and it was not handled within `exits.missed_exit_max_lag_s` of its exchange timestamp.

  **(A4.1) Leader exit event and "handled".** A leader exit event is the leader's fills on one coin at one exchange timestamp (ms), aggregated by time as in section 3, that reduce, close or flip the leader's position. It is **handled** when, within the lag, the ledger holds a mirroring action for it, a rule-based non-mirror record for it (a partial skipped below $10), or the full close of our share for any reason (our SL/TP included). A leader event after our share is fully closed is not an exit event on a share we hold. So rule-based non-mirrors recorded in time are not missed exits, and neither is a leader exit that comes after our own SL/TP closed the share (`04-spec.md` §1); a leader exit that our SL/TP closes more than 60 s later is. **Downtime, for this definition only,** means intervals in which the engine could not manage positions: process down, and a data gap before resync. Entry pauses (`/pause`, the access-degraded pause, the low-disk pause, a deploy-wait pause) keep exits managed, so a late mirror during one of them is a missed exit. Each ledgered `missed_exit` record is one missed exit, and one share can have more than one.
- **(A4.1) Leader-fill audit: detection must be complete.** The live stream and reconciliation can miss a dropped reduce, a close and reopen between two reconciliation passes, or a leader close that our own SL/TP closes minutes later. A silently dead `userFills` subscription misses all of them. So the ledger is checked against the exchange's own record of every leader's fills (`eval_reference.py::exit_class` classifies each event):
  - **Daily audit.** Every `eval.fill_audit_interval_h` (24 h), for every leader on whom we held an open share at any time since the previous audit (followed or dropped), the engine fetches the leader's fills (`userFillsByTime`) from the end of the previous audit to `exits.missed_exit_max_lag_s` before now. It checks every leader exit event on a coin where we held that leader's open share at the event time. An event that was neither handled in time nor settled inside downtime is a missed exit; if the ledger doesn't hold it yet, it is ledgered now as an orphan. Auditing daily keeps every interval within reach: the endpoint serves only a wallet's latest 10,000 fills, and gate G3 already excludes wallets that trade anywhere near that fast. Audits run from `t0` and continue after `T_eval` until every share of the run has closed (for ME).
  - **Final audit.** Before the verdict, the same audit covers every such leader up to `T_eval` (verdict timing below).
  - **Reconciliation compares fills and sizes.** Each reconciliation pass (spec F12.AC5) also fetches every followed leader's fills since the previous pass and checks them the same way. It compares the leader's position size on every coin where we hold that leader's share with the size implied by the last leader fill the ledger has processed (its `startPosition` plus its signed size). An unhandled fill or a size mismatch runs the missed-exit detector at once. The sign check (leader flat or reversed) stays.
  - **Incomplete audit.** An audit interval is complete when every fill in it has been retrieved. One that isn't (the API is unreachable, or a page is truncated under the `hl_sample.py` BT2-6 rules) is retried for up to `eval.missing_data_retry_max_h` (72 h) from its first attempt. If any stretch of `[t0, T_eval]` in which we held that leader's share is still unaudited then, **P4 counts as breached (F2)**, with breach time at the start of that stretch. (An unaudited stretch after `T_eval` is reported with the ME list.) Unknown missed exits could hide a cost, so an unverifiable P4 can't pass.
- **(A4.5) Settled after a data gap.** An exit event inside a data gap before resync that is handled within `exits.missed_exit_max_lag_s` after the resync is **settled**: it is not a missed exit and doesn't count toward P4. Its trade still gets a mirror from that event on (as below), counts at `min(actual R, mirrored lo R)` with the matching USD P&L, and uses the later evaluation close, like a missed-exit trade. It has no cost test. A late fill after a gap therefore never counts better than following on time. An exit inside a process-down interval keeps the restart rule: the reconstruction settles it, and the trade counts at its reconstructed R.
- **Mirrored outcome.** For each share with a missed exit, the engine builds a **mirror** with the `/flatten` shadow machinery (A1.3 d, A2.1): the share managed on recorded data under the frozen exit rules from its first missed leader event on, with that event and every later leader event on the share (adds, reduces, closes, flips) mirrored on time.
  - It uses the same stop, TP, trailing stop, $10 rules and hourly funding as the real share.
  - A mirrored leader action is decided at the leader event's exchange timestamp plus `copyreplay.delay_ms` (the replay's detection delay), and fills at the book recorded at the **fill time** (that decision time plus `paper.ack_delay_ms`), walked with the share's size. **(A4.2)** Without a recorded book within `baseline.dm_max_book_gap_s` (5 s) of the fill time (a recording gap, a lost file, or data not covered by a ledgered hash), the fill uses the candle rule below.
  - Over a gap in our recording, its SL/TP path uses exchange 1h candles, and an ambiguous bar is resolved **both ways**: stop first gives the **mirrored lo R**, TP first the **mirrored hi R**. Without an ambiguous bar, lo = hi.
  - A mirror still open at `t300 + 7 days` is marked at the recorded mid − taker fee − half-spread (the `T_eval` row).
  - **(A4.2) Fills without a recorded book.** The fill uses the exchange candle that contains the fill time: the **1m** candle, or the **1h** candle if the 1m candle is not in our candle store (`eval_reference.py::gap_candle`). The **lo** fill is the candle's worst price for our side (its high for a buy, its low for a sell) moved against us by the alt fallback half-spread (8 bps). The **hi** fill is its best price (low for a buy, high for a sell) moved against us by the major fallback half-spread (2 bps). Both pay the taker fee. There is no separate delay term, because the candle's range already contains every price reachable in that minute or hour (`gap_fill_px`). An SL or TP of a mirror triggered inside a gap fills at its trigger price, or at the bar's open when the bar opened beyond the trigger (gap-through), moved against us by 8 bps (lo) or 2 bps (hi) (`gap_trigger_px`). The two constants don't depend on the tier table, so tier assignments can't move the cost test. `/flatten` shadows use the lo prices of this rule.
  - **(A4.2) Uncomputable mirror.** A mirror is uncomputable if a fill or a gap stretch of its SL/TP path needs a candle that is neither in our candle store nor obtained from the exchange within `eval.missing_data_retry_max_h` (72 h) of the first attempt. Then every cost of that share counts as **above 1R** (F2, breach time = the leader event time of its first missed exit), its mirrored lo R is set to its actual R (so its gate R is its actual R), and its mirror exit is its real close. The verdict never waits for it beyond that bound (`eval_reference.py::missed_exit_costs`, `mirror_lo_for_gate`).
  - **(A4.2) Candle store.** During a run, the recorder fetches, every hour, the exchange 1m and 1h candles of the hour just closed for every coin on which any share, shadow or mirror was open during that hour. It stores them as recording files under the integrity rules (6.2, A3.4, A4.8). The evaluation reads exchange candles only from this store. A candle missing from it may be fetched later, within the retry bound; it is then stored and hashed the same way, with its fetch time. A stored candle is never replaced. The other users of exchange 1h candles (B0d's relaxed set, the restart reconstruction, shadows) read them through the same store; 1h candles they need that aren't there yet are fetched and hashed before the evaluation uses them.
- **Gate R.** A trade in S with a missed exit counts with `min(actual R, mirrored lo R)`, and its USD P&L with the same choice. A trade that is also flattened counts with the minimum of realised, shadow and mirrored lo R (`eval_reference.py::gate_r`). **(A4.10)** A missed exit therefore never raises a trade's R or its USD P&L in the gate. Its effects on D_i (through the longer B0d hold that the later evaluation close gives) and on `LB_r` (through the spread of R, which lowering one R can shrink) can go either way, but only negligibly. **(A4.2)** With an uncomputable mirror, mirrored lo R = actual R. **(A4.5)** An exit settled after a data gap uses the same rule.
- **Evaluation close.** The later of the real close (the shadow exit if flattened) and the mirror exit. It is the trade's close for `T_eval`, hold_i, merged positions, the B0d replications and P3, as in A2.1. It can only move `T_eval` later and make merged positions larger.
- **Cost (A4.3: per missed exit and per trade).** It is computed for every trade with a missed exit whose leader event falls in the evaluation window, in S or not. Number the share's missed exits 1..k by leader event time (ties by missed-exit ID). Mirror **M_j** is the share managed from missed exit 1 on with missed exits 1..j and every other leader event mirrored on time, and missed exits j+1..k handled as the engine actually handled them: at the time of their actual handling record, or not at all if the share closed first. M_k is the mirror above.
  - The **incremental cost** of missed exit j is `hi R(M_j) − hi R(M_{j−1})`, with `hi R(M_0)` = the actual R.
  - The **trade cost** is `hi R(M_k) − actual R`, which is the sum of the increments.
  - Each is in that trade's R and rounded half-even to 1e-6 (`eval_reference.py::missed_exit_costs`; with k = 1 both equal the A3.1 cost of `missed_exit_cost`). Two missed exits can't net each other out: +1.3R and −0.5R is a trade cost of 0.8R, but the first increment of 1.3R breaches P4.
  - **Actual R** is the trade's realised R: its R at its real full close, including a close by `/flatten` (never its shadow), or its marked R if it is still open at `t300 + 7 days`.
  - The TP-first mirror is used so that a recording gap can't hide a cost.
- **P4 and F2 (A4.4).** P4 fails when more than 3 missed exits have a leader event in the evaluation window (counted over all trades, including those opened after the 300th); or when any incremental or trade cost of such a missed exit is above 1.000000R, an uncomputable mirror included (`eval_reference.py::p4_breach`); or when the fill audit is incomplete (A4.1). **Any such breach is F2, whenever it is found before the verdict:** live, by a daily audit, or by the final audit and recomputation after `T_eval`. Its **breach time** is the earliest of:
  - the leader event time of the 4th missed exit in leader-event order (never the order in which they were ledgered)
  - for a cost above 1R, the moment it is established: the later of the trade's real close and its mirror exits, capped at `T_eval` (a side still open then is marked); for an uncomputable mirror, the leader event time of its first missed exit
  - for an incomplete audit, the start of the unaudited stretch

  It always lies in `[t0, T_eval]` (`eval_reference.py::p4_breach_time`). It decides precedence against ABORTED (precedence item 2; `run_end`) and is reported with the time the breach was found. A breach found before `T_eval` ends the run as FAIL when it is found: entries stop and the bot pauses per the risk rules. One found after `T_eval` changes the verdict only.
- **Verdict timing (A4.1).** The verdict is computed no earlier than `T_eval + exits.missed_exit_max_lag_s`, after all of the following:
  - one reconciliation pass over every share open at `T_eval`
  - the final leader-fill audit, from the end of the last daily audit to `T_eval`, for every leader on whom we held a share in the window
  - the recomputation from hash-verified recordings (6.2, A4.8 c)

  Only then is every missed exit whose leader event is at or before `T_eval` in the ledger, as completely as the exchange's own fill history allows. The wait is bounded: after `eval.missing_data_retry_max_h` (72 h), an incomplete audit or an uncomputable mirror counts as a P4 breach (above), and the verdict is computed. A missed exit whose leader event comes after `T_eval` does not enter the verdict; it is still a go-live blocker (ME, 5.6).
- **P5.** A missed exit is not downtime. This rule doesn't pause entries after a missed exit; if the spec adds a safety pause, or the PO uses `/pause`, that time counts as downtime. An exit inside real downtime that the reconstruction settles is not a missed exit, and its downtime counts toward P5 as before. Waiting for a ruling on a fix counts as downtime when entries are paused (engine changes above).
- **Go-live blocker.** Every missed exit, at any time during a run, blocks any live step until it is explained and fixed (ME in 5.6).

**Also computed at `T_eval` and reported with every verdict** (go-live blockers in 5.6, not verdict changes):
- R_maxrisk
- S2, S3, S4, S6 (weekly mean R, A1.6)
- FR1 to FR6
- decay
- mirror fidelity
- the exit-reason mix, including `manual_flatten` and `marked`
- **(A3.1)** every missed exit, in the window and after it: class, lag, actual R, mirrored lo and hi R, cost; and the total change in Σ R over S from the min(actual, mirrored) rule
- **(A4.1-A4.5)** for each missed exit, how it was found (live, reconciliation, daily or final fill audit) and its incremental cost; per trade, the trade cost; uncomputable mirrors; the P4 breach time and the time it was found, if any; the fill-audit coverage per leader (audited intervals, retries, any unaudited stretch); every exit settled after a data gap, with its actual and mirrored R; and every mirror or shadow fill priced by the candle rule, with the candle used
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

### 5.5 What is visible during a run (BT-5; A3.2)

- **The PO sees trades, positions and USD P&L live**, plus the daily and weekly reports [PO].
- **(A3.2) `/stats` (PO spec-review decision A14).** During a run the PO may see, overall and per followed trader:
  - net USD P&L (realised, and marked for open positions)
  - win rate
  - average R: the plain mean of realised R over closed trades, labelled "descriptive, not the verdict"
  - drawdown, marked to market (the P3 quantity)
  - trade counts and progress toward 300

  Operational counters are shown too: downtime used against the 2% budget (P5), missed exits with their costs (P4), and pending deploy rulings. **(A4.11)** Nothing else **of run-result content** is shown before `T_eval`, by any command, report, alert or log. Adding a run-result metric to `/stats` or to a report is a spec change, checked against this section.
- **(A4.11) What "nothing else" covers.**
  - **Run-result content** is any figure computed from the outcomes of our trades, of their `/flatten` shadows or missed-exit mirrors, or of any baseline or comparator: their R, USD P&L, exit prices, exit reasons, or anything aggregated from them. Before `T_eval`, run-result content appears only in two places: the `/stats` list above, and each trade's own post (entry, exit, its R and USD P&L, its exit reason).
  - **Excluded before `T_eval`**, in particular: any other aggregate of outcomes, by any grouping or window (per coin, per week or day, per exit reason, the exit-reason mix, the payoff ratio, R_maxrisk, S2-S6); everything in the list "Also computed at `T_eval`" (5.3) except the missed-exit counter; decay and edge lost per second; and every item of the never-computed list below.
  - **Operational content is not run-result content**, because it is not computed from those outcomes. It may appear in `/status`, `/traders`, alerts and reports: mode and pause state; feed, access, clock and latency health; disk, archive and storage cost; the followed wallets with their score, rank and follow state (computed from the leaders' own data); the leaders' own scoring-window figures in trade posts; counts of signals, entries, exits, refusals and unexecutable or skipped mirrors by reason; followed-set and tier changes; and the three operational counters. It never carries a pass, fail or on-track label for a gate condition.
- **(A3.2) Never computed or shown before `T_eval`,** by any command, report, log or API:
  - any interval, standard error, t-statistic or p-value of the mean of R or of D, by any of the three methods (the gate CI of P2 and F3)
  - B0d replications, B̄_i, D_i, P2c
  - FR1-FR6, K9 / S4 (B1), P6, G and the cross-day diagnostics
  - any verdict preview: "on track", a projected bound, a probability of PASS, a traffic light

  The gate statistics are computed once, at `T_eval`.
- **(A3.2) Why showing more does not raise the chance of passing by luck.** The α split in 5.4 is a Bonferroni (union) bound: P(some run PASSes | no edge) ≤ Σ_r P(run r's single evaluation at `T_eval` passes), and each term is at most its one-sided α_r/2 (2% and 0.5%). Whatever the PO does after seeing `/stats` can only stop the run (ABORTED), change the config (ABORTED), or deploy code (ABORTED by default, CONTINUE only on an identical replay). None of these creates a PASS: an ABORTED run is never a PASS, and every started run counts toward the cap of 2. So a data-dependent abort can only remove PASS outcomes, and the bound stays at 2.5% one-sided (simulated 1.6%, E6 G). This is the round-2 audit's argument ("The Bonferroni 2.5% bound holds for any data-dependent abort, so P&L visible to the PO can't inflate it", `backtest-audit-r2.md`, frozen-rule assessment). Descriptive statistics add information to that decision but don't change the argument.
- **(A3.2) What still costs something, stated plainly:**
  1. **Stopping on noise uses up a run.** Over the first 50 trades, the average R has a 95% range of roughly ±0.3R (at about 1R standard deviation per trade), three times the edge being tested. A run stopped because early numbers look bad is consumed, and run 2 is judged at 99%, where a real +0.10R edge passes only about 3-9% of the time even before the baseline test (5.9). The bound protects against passes by luck, not against wasting a real edge's chances.
  2. **`/pause` can shape which trades enter S.** It is the one lever that changes the sample without ending the run: pausing through a stretch that looks bad lets later trades take those places among the first 300. It is capped by P5 (downtime < 2% of the window, about 14 hours in 30 days). **(A4.6)** A3.2 b's plain exclusion of paused time from B0d cut both ways: pausing through a stretch that was good for the copy's direction removed good baseline start times, lowered B̄ and raised D, by about 0.02-0.04R per affected trade (arithmetic). Now B̄_i for a discretionary pause is the larger of the baseline means with and without the paused start times (6.2). Compared with not pausing, a pause can therefore only raise B̄_i and lower D_i, never the other way. The selection effect on S itself remains. It existed before A3, when trades and USD P&L were already visible; per-trader statistics make it better informed. Rough upper bound [EXPL, arithmetic, not simulated]: 2% of a 21-day window is about 10 hours, or about 6 of 300 trades. With perfect foresight, replacing six −1R trades by zero-mean ones raises the mean by at most 6/300 = 0.02R, about 0.3 standard errors. Real foresight gives much less.
  3. **Hiding the interval is not the protection.** The PO sees every trade's R and could estimate a rough interval by hand. The rule is protected by the single evaluation at `T_eval`, by aborts never passing and by the run cap. Not computing the interval removes a running "verdict" that invites stopping or pausing on noise.
  4. **Deploys prompted by what the PO sees.** The CONTINUE test replays only past trades. A code change aimed at a trader or pattern visible in `/stats` could pass it and still change future trades. Hence the next bullet.
- **Interim numbers can't justify a config change or a code deploy.** A config change can still be made, but it ends the run as ABORTED and consumes it [PO]. **(A3.2)** A mid-run deploy whose stated reason is an interim result, rather than a defect against this file or the spec, is ruled ABORTED.
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
| **ME (A3.1)** | Missed exits [PO] | Any missed exit at any time during a run, including after `T_eval` and in a run that ended ABORTED. Unlike the rows above, a PO review alone does not clear it: each one must be **explained** (a written root cause in the verdict report) and **fixed** (the fix merged with a regression test that reproduces the missed exit and now passes). |

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
- **(A3.1) Missed exits are not in any simulation.** E5, E6, E10 and E11 model a correct engine. A3.1 changes none of their figures: a missed-exit trade counts at or below the R the frozen exits would have produced (its stop-first mirror), so the gate sample is never better than a correct engine's. What the simulations can't bound is a bug that also changed things the mirror doesn't correct (5.12, "What A3 costs the verdict").

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

### 5.12 Addendum A3 (dated 2026-09-29, before run 1)

**Context:**
- Written after the PO's spec review of `04-spec.md` (six "Spec review" entries of 2026-09-29 in `docs/product/decisions.md`). Two of them say "Needs a pre-registration addendum": A4 (missed exits) and A14 (`/stats`).
- Written before any paper run started and before any real-data result. The run register is empty, and 0 strategy variants have been tried on real data.
- No number in A3 was chosen after seeing strategy performance: none exists. The new thresholds (3 missed exits, 1R) are the PO's. The only other new numbers are the golden values of the reference implementation (E15) and a few arithmetic illustrations in 5.5 and in "What A3 costs the verdict" below (the ±0.3R noise at 50 trades, the 0.02R pause bound, the 0.01-0.05R delay bias). None comes from a simulation or from data.

**Version it amends:** v2 + A1 + A2, this file at commit `a7b13ea` (unchanged through `e3175a9`), sha256 `e20ad5edb5d67ea7fa138d9330815af842b3716f8e9eb944a681023252274b40` (check: `git show a7b13ea:docs/sdlc/copytrade-v1/research/edge-hypothesis.md | sha256sum`). All quotes below are from this version. The sha256 of v2 + A1 + A2 + A3 is not written here, because writing it would change it; run 1's record stores it (5.1).

**Rule followed (5.1):** every replaced text is quoted verbatim below. The amended text is in place, marked `(A3.n)`. Pure additions are listed by location without a quote. A1.4 binds A3: P2c is not removed, weakened or made non-gating.

| Item | Source | Change (where) |
|---|---|---|
| **A3.1** | PO spec review A4 | **Missed exits.** "0 missed exits, immediate FAIL" is replaced. A missed-exit trade in S counts at min(actual R, mirrored R), where the mirror is built like the `/flatten` shadow (stop-first on an ambiguous 1h bar). P4 fails, and F2 fires, when more than 3 missed exits fall in the evaluation window (all trades) or any one cost more than 1R against its TP-first mirror. The evaluation close is the later of the real close and the mirror exit. The verdict waits for `T_eval` + the lag and a reconciliation pass. For the definition, downtime means only intervals when positions couldn't be managed. Every missed exit is go-live blocker ME until explained and fixed. A mid-run fix is a deploy under A1.2 and A2.2, unchanged. (1, 4, 5.3 definitions, P4, F2, precedence, engine changes, `/flatten` P3, missed-exit rules, `T_eval` report; 5.6 ME; 5.9; 7 K13; 9.2; tests 21; E15) |
| **A3.2** | PO spec review A14 | **`/stats`.** 5.5 now lists what the PO sees during a run (USD P&L, win rate, average R, drawdown, per-trader stats, progress to 300, operational counters) and what is never computed or shown before `T_eval` (the gate CI by any method, B0d, D, P2c, FR1-FR6, K9 / S4, P6, G, any verdict preview). The justification is the audit-r2 Bonferroni argument; the remaining risks are stated. **(b)** B0d start times exclude recorded downtime, `/pause` included, so a targeted pause can't pull the baseline down (6.2). **(c)** A mid-run deploy justified by an interim result is ABORTED (5.5). (5.5, 6.2, 9.2, test 7, test 22, 13 C2, C16) |
| **A3.3** | PO spec review A6 | **Liquidity tiers.** "Majors" and "alts" in the frozen fallback costs mean the tightest liquidity tier at decision time and every other tier. A coin without a tier record is an alt for copies and a major for random-time baselines, the conservative side in each case. (6.2, 6.3, 9.2, test 23) |
| **A3.4** | PO spec review A10 | **Compressed, uploaded recordings.** Lossless compression, a per-file sha256 in the ledger verified on every evaluation read, local deletion only after a verified upload, a lost file counted as a recording gap, and the recorder treated as engine code that runs the run commit during a run. (6.2, 9.2, test 24) |
| **A3.5** | PO spec review A2 | **Automatic leverage.** No change to this file (below). |
| **A3.6** | – | `eval_reference.py` v3 with golden vectors and a 16-mutant check (E15); `scripts/README.md`. (12) |
| **A3.7** | – | Section 14: items 1-8 marked acknowledged (per `decisions.md`), items 9 and 10 added; the header, 8.1 and C14 follow. |

**The three spec-review config changes (A3.3-A3.5).** The rule used: a change goes into 9.2 and, if needed, section 14 only if it touches the frozen rule. Otherwise it is pre-run config, frozen per run by the config hash in the run record (5.1). Changing it during a run is a config change and ends the run as ABORTED [PO].
- **Leverage raised automatically up to the ceilings (5x alts; 10x BTC, ETH and SOL) while the liquidation distance stays at least 3× the stop distance (A3.5): pre-run config, no rule change.**
  - R, the gate statistic, is set by the stop distance and the risk per trade, not by leverage. Fees and funding are charged on notional, so they don't change either.
  - Isolated margin keeps a trade's loss at its stop unless the price gaps through the stop. With liquidation at least 3× the stop away, a liquidation needs a gap of 3 stop distances. If one happens, it is a normal trade with its realised R, below −1R, and it counts.
  - Leverage changes how many signals are refused for `insufficient_margin`. More trades are taken, which helps P1, and mirror fidelity changes. That is strategy behaviour, not the rule.
  - B0d runs through the same engine and risk limits (6.2), and its replications' R is also set by their stops, so no frozen text changes.
  - No new PO acknowledgement is needed: the PO decided it, and it changes no verdict rule.
- **Liquidity-based coin tiers instead of a BTC/ETH majors list (A3.3): touches the frozen rule only through the word "majors".** The B0d relaxed-set fallback in 6.2 (frozen) and the 6.3 fallback costs use "2 bps majors, 8 bps alts". A3.3 pins that word and adds `cost.fallback_tier_rule` to 9.2. The tier rule, its thresholds and the wider universe (liquid meme perps on core) are pre-run config. No new PO acknowledgement: the definition is conservative on both sides and changes no PO decision. Side effect for the PO's awareness: more thin coins mean higher costs in R (FR3) and more recorder load, so the recorder gap-rate report (item 8) matters more.
- **Compressed recording with cloud upload (A3.4): touches the frozen rule,** because B0d, the shadows, the mirrors, the marking and the P6 replay read the recordings. A3.4 requires them to read exactly what was recorded, and adds `eval.recording_integrity` to 9.2. The compression codec and the local retention window are pre-run config. **(A4.8 d)** The provider, endpoint, bucket and credentials are not: they are outside the config hash (6.2, "Storage destination"). No new PO acknowledgement: a lost file is already covered by item 8 (gaps can fail the baseline test), and the no-early-delete rule makes a loss unlikely.
- The other spec-review entry of 2026-09-29, A9 (no paid news source; the LLM has no vote), doesn't touch this file.

**Replaced text, verbatim.** Each block is the exact v2 + A1 + A2 text that A3 replaced, in file order. The new text is in place at the named location, marked `(A3.n)`.

1. **A3, header, version line.** Replaced:

```text
Date: 2026-09-29. Author: quant-researcher. Version: **v2 + Addenda A1 and A2** (both dated 2026-09-29, written before run 1 and before any real result).
```

2. **A3.7, header, run-1 precondition.** Replaced:

```text
- **Run 1 must not start until the PO has acknowledged the eight items in section 14** (pending PO acknowledgement, BT2-5; items 6-8 added by A2.4).
```

3. **A3.1, 1, falsification.** Replaced:

```text
- H1 fails when the frozen rule returns FAIL: the CI upper bound ≤ 0, or drawdown reaches 15%, or a missed exit.
```

4. **A3.1, 5.3, day cluster, evaluation close.** Replaced:

```text
The evaluation close is the full close, or the shadow exit for a flattened trade.
```

5. **A3.1, 5.3, P4.** Replaced:

```text
| P4 [PO] | 0 missed exits in the evaluation window |
```

6. **A3.1, 5.3, F2.** Replaced:

```text
| F2 [PO] | P4 is breached (a missed exit) at any time before `T_eval`. The verdict is immediate. |
```

7. **A3.1, 5.3, precedence item 2.** Replaced:

```text
2. **FAIL by F1 or F2.** The breach happened before `T_eval`; the run ends at that moment.
```

8. **A3.1, 5.3, reference to `eval_reference.py::verdict`.** Replaced:

```text
`scripts/eval_reference.py::verdict` implements this order and asserts every adjacent pair (E13).
```

9. **A3.1, 5.3, `/flatten`, P3.** Replaced:

```text
- **P3.** P3 is checked both on the actual marked equity and on the shadow equity, which has flattened trades replaced by their shadows. A breach on either is F1.
```

10. **A3.2, 5.5, heading.** Replaced:

```text
### 5.5 What is visible during a run (BT-5)
```

11. **A3.2, 5.5, interim statistics and config changes.** Replaced:

```text
- **The system does not compute or display interim mean R, CIs or a running verdict.** The gate statistics are computed once, at `T_eval`. Reports may show trade counts and the progress toward 300.
- **Interim numbers can't justify a config change.** A config change can still be made, but it ends the run as ABORTED and consumes it [PO].
```

12. **A3.2 b, 6.2, B0d admissible start, blackout condition.** Replaced:

```text
  - t is not inside a configured entry blackout, because our engine could not have entered then
```

13. **A3.2 b and A3.3, 6.2, missing window, relaxed set.** Replaced:

```text
restricted only by the listing and blackout conditions. Where our book or mid recording is missing, a replication uses the coin's median recorded half-spread without the ×1.5 multiplier (else 2 bps majors, 8 bps alts)
```

14. **A3.7, 8.1, precondition.** Replaced:

```text
- **Precondition (BT2-5, A2.4):** the PO's acknowledgement of the eight section-14 items is recorded in `decisions.md`.
```

15. **A3.2, 9.2, `eval.show_interim_stats`.** Replaced:

```text
| `eval.show_interim_stats` | false (trades and USD P&L are shown) | bool | PO + QR | FROZEN |
```

16. **A3.2, 10.8, test 7.** Replaced:

```text
7. No interim mean R, CI or verdict is exposed before `T_eval`.
```

17. **A3.2, 13, C2.** Replaced:

```text
| C2 | Peeking | **Resolved [PO]:** one evaluation of the first 300 opened; no interim statistics (5.5); at most 2 runs with an α split (5.4). |
```

18. **A3.7, 13, C14, status cell.** Replaced:

```text
| **Pending PO acknowledgement** (section 14, eight items) |
```

19. **A3.7, 14, heading.** Replaced:

```text
## 14. Items pending PO acknowledgement (BT2-5; A2.4, A2.5)
```

20. **A3.7, 14, opening paragraph.** Replaced:

```text
Q1-Q9 are answered and encoded in 5.2. The eight items below are research choices, or plain consequences of the rules, that interpret or tighten your decisions. You haven't signed them yet. (A2.4: v2 + A1 listed five; items 6-8 and the closing note are new, and every item is reworded in plain language.)
```

21. **A3.7, 14, status bullet.** Replaced:

```text
- **Status of each:** pending PO acknowledgement.
```

22. **A3.7, 14, precondition bullet.** Replaced:

```text
- **Precondition:** run 1 must not start until all eight are acknowledged or replaced (8.1).
```

23. **A3.1, 14, item 3, last sentence of "What it means".** Replaced:

```text
The run can still fail on the 15% drawdown limit or a missed exit.
```

24. **A3.7, 14, items 1-8, status line (8 identical occurrences, one per item).** Replaced each time:

```text
- **Status:** pending PO acknowledgement.
```

**Additions (no v2 + A1 + A2 text removed):**
- A3: header, status bullet and inputs line
- A3.1: 4, metrics table, "Missed exits" row
- A3.1: 5.3, `T_eval` row, last sentence; new definitions row "Missed exit"
- A3.1: 5.3, engine changes, new bullet "Fixing the cause of a missed exit during a run"
- A3.1: 5.3, new block "Missed-exit rules" after the `/flatten` block
- A3.1: 5.3, "Also computed at `T_eval`", new bullet
- A3.2: 5.5, new bullets (`/stats` list, never-before-`T_eval` list, justification, remaining risks)
- A3.1: 5.6, row ME
- A3.1: 5.9, reading, new bullet
- A3.4: 6.2, new paragraph "Recording integrity"
- A3.3: 6.3, new bullet "Majors and alts"
- A3.1: 7, row K13
- A3.1-A3.4: 9.2, eight new rows after `eval.show_interim_stats`
- A3.1-A3.4: 10.8, tests 21-24
- A3.6: 12, E14 row, "Superseded by E15 (A3.6)." at the start of the description; new E15 row
- A3.1, A3.2: 13, rows C15 and C16
- A3.1, A3.2: 14, items 9 and 10
- A3: 15, note after the round-3 table
- A3: this section, 5.12

**Outside this file (not hashed in the run record):** `scripts/eval_reference.py` v3 (E15) and `scripts/README.md` (E15 references). `research/data/eval_reference_vectors.txt` was regenerated. `run-register.md` is unchanged: F2 appears there as an end reason and a verdict like any other.

**Not frozen, logged for completeness:** the sha256 values of the script and of its output are in section 12 (E15).

**What A3 costs the verdict:**
- **A3.1 is the one change in A3 that makes a PASS possible where it wasn't.** Before, a run with any missed exit was FAIL. Now a run with 1-3 missed exits, each costing at most 1R, can reach PASS. This is the PO's decision.
  - **It does not make the statistical test easier to pass by luck.** Each missed-exit trade counts at or below both its actual R and its stop-first mirrored R. The mirror is what the frozen exits would have produced, under the pessimistic gap convention and the replay's p95 detection delay. So the gate sample is never better than a correct engine's. **(A4.10)** A3.1 never raises a trade's R or its USD P&L; its effects on D_i and `LB_r` are negligible and can go either way. The later evaluation close can only move `T_eval` later and merge more trades into fewer day clusters.
  - **What it can't bound:** a bug that misses exits may also have changed things the mirror doesn't correct, such as entries, sizes or other trades' stops. The cap of 3, the ME go-live blocker and the D6 paper-vs-replay checks are the guard, not the statistics.
  - **Small, stated bias in the cost test:** the mirror uses the p95 detection delay, so it is slightly pessimistic, and the cost can be understated by that delay's decay. That is a few bps, about 0.01-0.05R at typical stops, small against the 1R line. The TP-first gap convention removes the larger bias that recording gaps could cause.
- **A3.2 shows more and computes nothing new before `T_eval`.** The family-wise bound is unchanged (5.5). **(A4.6)** A3.2 b as written cut both ways: excluding a paused stretch that was good for the copy's direction lowered B̄ and raised D_i. A4.6 replaces it for discretionary pauses with B̄_i = max(including, excluding the paused start times); plain exclusion still applies to non-discretionary downtime. It removes up to 2% of the admissible time, which slightly raises the chance of a missing B0d window. A3.2 c only adds ABORTED outcomes.
- **A3.3 and A3.4 pin definitions on the conservative side.** A lost recording file can only fail P2c through the 10% rule or lower D_i.
- **A3.5 changes no rule. A3.6 and A3.7 change no rule.**
- **Nothing else in A3 makes a PASS easier.** P2c keeps its gating status (A1.4).

### 5.13 Addendum A4 (dated 2026-09-29, before run 1)

**Context:**
- Written after backtest-audit round 4 (`backtest-audit-r4.md`, verdict VALID, ten ADVISORY findings BT4-1 to BT4-10), which audited A3 and `eval_reference.py` v3.
- It also settles four open points that the PM raised while aligning the spec with A3 (`04-spec.md` Amendment 2: §11 A20 (a) and (b), F9.AC8 against A3.3, and §11 A25).
- Written before any paper run started and before any real-data result. The run register is empty, and 0 strategy variants have been tried on real data.
- No number in A4 was chosen after seeing strategy performance: none exists. The new numbers are:
  - engineering bounds: a 24-hour audit interval, a 72-hour retry bound and 5-minute hash segments
  - the existing fallback half-spreads of 6.3 (8 bps alts, 2 bps majors)
  - arithmetic illustrations: $1.50 per R at 0.5% of $300; the 0.02R noise bias that two independent B0d draws would add; the auditor's 0.02-0.04R pause effect
  - the golden values of the reference implementation (E16)

**Version it amends:** v2 + A1 + A2 + A3, this file at commit `0109b6f` (unchanged through `a861fb7`), sha256 `b96314dbbd6f567e5131c7a22a4bf5c427ba427a635b2229e7d96445265fbe01` (check: `git show 0109b6f:docs/sdlc/copytrade-v1/research/edge-hypothesis.md | sha256sum`). All quotes below are from this version. The sha256 of v2 + A1-A4 is not written here, because writing it would change it; run 1's record stores it (5.1).

**Rule followed (5.1):** every replaced text is quoted verbatim below. The amended text is in place, marked `(A4.n)`. Pure additions are listed by location without a quote. A1.4 binds A4: P2c is not removed, weakened or made non-gating, and A4.6 makes it stricter.

| Item | Source | Change (where) |
|---|---|---|
| **A4.1** | BT4-1 | **Detection completeness.** A daily leader-fill audit, and a final one before the verdict, check every leader exit event (from `userFillsByTime`) on a coin where we held that leader's share against the ledger. An event not handled within 60 s becomes an orphan missed exit before P4 and gate R. "Handled" is defined: a mirroring action, a rule-based non-mirror record, or the share's full close, within the lag. Reconciliation checks fills and sizes, not only the sign. An audit still incomplete after 72 h is a P4 breach. The verdict waits for the final audit. (5.3 P4, missed-exit rules, verdict timing, "Also computed"; 7 K13; 9.2; test 25; E16) |
| **A4.2** | BT4-2; spec A20 (a), (b) | **Mirror fills over a gap.** Without a recorded book within 5 s of the fill time, a mirrored leader action fills on the 1m candle, else the 1h candle: lo at the worst price + 8 bps, hi at the best price + 2 bps, plus the taker fee. An SL/TP inside a gap fills at its trigger or at a gapped-through open, ± 8 / 2 bps; shadows use the lo prices. With no candle within 72 h, the mirror is uncomputable: its costs count as above 1R, its lo R = actual R. Candles are fetched hourly during the run and hashed. (5.3 missed-exit rules; 6.2 lost file; 9.2; test 26; E16) |
| **A4.3** | BT4-3 | **Incremental and per-trade cost.** Mirrors M_1..M_k fix a share's missed exits one at a time; each incremental cost and the trade cost are tested against 1R. Actual R = realised R, a `/flatten` close included. (4; 5.3 P4, missed-exit rules; 7 K13; 9.2; test 27; E16) |
| **A4.4** | BT4-4 | **F2 timing.** Any P4 breach by missed exits with leader events in `[t0, T_eval]` is F2, whenever found before the verdict. Breach time: the 4th's leader event time, or when a cost is established (capped at `T_eval`), or for missing data the times of A4.1 and A4.2. ABORTED wins only when strictly earlier. (5.3 P4, F2, precedence item 2, missed-exit rules; 9.2; test 28; E16) |
| **A4.5** | BT4-5 | **Settled after a data gap.** An exit inside a data gap handled within 60 s of the resync is settled: not a missed exit, but its trade counts at min(actual R, mirrored lo R). Otherwise it is class 2. (5.3 missed-exit rules; 9.2; test 29; E16) |
| **A4.6** | BT4-6 | **Discretionary pauses and B0d.** For `/pause` and deploy-wait pauses, B̄_i = max(mean including, mean excluding the paused start times), from the same draws. Non-discretionary downtime keeps plain exclusion. The two-sided effect of A3.2 b is disclosed. (5.5; 5.12; 6.2; 9.2; test 22; E16) |
| **A4.7** | BT4-7; spec F9.AC8, F17.AC4 | **Tiers.** An untiered coin is a major in every baseline and comparator (B0d, B0, B0b, B1, B3). The tier rule and thresholds are frozen; assignments are recomputed every 24 h and ledgered, and a recomputed table is not a config change. (6.3; 9.2; test 23) |
| **A4.8** | BT4-8 | **Recording integrity.** (a) A stream sha256 and a transport sha256 per file. (b) A hash-chained segment record every 5 minutes; unhashed data is a gap. (c) Verdict values recomputed from verified data. (d) The storage destination is outside the config hash, with the argument stated; retention stays inside. (5.12; 6.2; 9.2; test 24) |
| **A4.9** | BT4-9 | **Items 9 and 10** rewritten in plain language, correcting (a)-(f), and marked pending PO re-acknowledgement. The header, 8.1 and 13 follow. (header; 8.1; 13 C15, C16; 14) |
| **A4.10** | BT4-10 | "Can only lower" becomes "never raises a trade's R or USD; D_i and `LB_r` are affected only negligibly". (5.3 missed-exit rules; 5.12) |
| **A4.11** | Spec §11 A25 | **What "nothing else is shown" covers:** run-result content, defined; what is excluded; what operational content may be shown. (5.5; 9.2; test 7) |
| **A4.12** | – | `eval_reference.py` v4 with golden vectors and a 31-mutant check (E16); `scripts/README.md`. (5.3 reference line; 10.8 test 21; 12) |

**Decisions on the PM's four open points (spec Amendment 2).** Each is now a frozen rule.
1. **Mirror fill when our book is missing (A20 a).**
   - **Rule (A4.2):** the fill uses the 1m candle, else the 1h candle, from our hashed candle store. lo = the worst price for our side + the alt half-spread (8 bps); hi = the best price for our side + the major half-spread (2 bps); taker fee on both; no delay term.
   - **What changes from the PM default:** the PM's hi side ("major values") survives, but at the candle's best price. The PM's lo side (the candle open with the copy-side tier rule, where tier 1 got 2 bps, plus delay slippage) is replaced by the worst price + 8 bps for every coin.
   - **Why:** where to price inside the candle was the unpinned choice that moves hi by 0.1-0.3R on a 1m candle and by 1R or more on a 1h candle (BT4-2). The candle's extremes bound every price the mirror could have got in that minute or hour. So lo can't flatter the gate R, and hi can't understate a cost. The fixed constants keep the tier table out of the cost test. A delay term would double-count, because the range already contains the delay.
2. **A mirror that can't be built at all (A20 b).**
   - **Rule (A4.2):** after at most 72 h of retries, it counts as a cost above 1R (F2, breach time = the event time of its first missed exit), with mirrored lo R = actual R. The PM's "cost pending, no verdict until it exists" is not adopted.
   - **Why:**
     - The verdict must never wait forever. "Pending" needs a bound anyway, and at the bound something has to be decided.
     - What is decided must not help the run. The unknown cost may be above 1R, and a missing mirror leaves the trade at its actual R, which the bug may have improved.
     - F2 is still defined only through `p4_breach`: an uncomputable cost enters it as +∞, so A3's structure holds.
     - It should be rare. Candles are fetched and hashed hourly during the run, and exchange 1h candles stay available for about 208 days. It takes an exchange outage of more than 72 h, over a recording gap, during a missed exit.
     - Such a FAIL is K13, a data or engineering failure, not evidence about the edge.
3. **Tier table during a run (F9.AC8 and F17.AC4 against A3.3).**
   - **Rule (A4.7):** recompute every 24 h under the frozen rule and thresholds, ledger each table, and put it in force from its ledger time. The whole-table freeze is not adopted. Only a table the rule doesn't reproduce from recorded data is a config change (ABORTED).
   - **Why:**
     - A table frozen before `t0` would price and filter coins on liquidity up to 67 days old. A coin that thins mid-run would keep tier-1 thresholds and the lower fallback cost, which is lenient for copies. A coin that becomes liquid mid-run would stay untiered and untradable.
     - The reassignment is a deterministic rule on point-in-time recorded data, like the hourly re-scoring of traders. Nobody chooses it, so it is not a config change.
     - Every table is ledgered and reproducible, so the replay (P6, D6) and the auditor see exactly what was in force.
     - The conservative side for untiered coins holds on both sides (A4.7).
4. **§5.5 "Nothing else is shown" and test 7 (A25).**
   - **Rule (A4.11):** the PM's reading is confirmed and pinned. The restriction covers **run-result content**: any figure computed from the outcomes (R, USD P&L, exit prices, exit reasons) of our trades, their shadows and mirrors, or any baseline or comparator.
   - **Allowed before `T_eval`:** such content only in the `/stats` list and in each trade's own post. **Excluded:** every other aggregate of outcomes (per coin, per week or day, per exit reason, the exit-reason mix, the payoff ratio, R_maxrisk, S2-S6); every item of 5.3's "Also computed at `T_eval`" list except the missed-exit counter; decay and edge lost per second; and the never-computed list.
   - **Operational content** is not computed from outcomes and may appear in `/status`, `/traders`, alerts and reports, never with a gate label. It covers mode, health, disk, archive and storage cost; the followed wallets with score, rank and follow state; the leaders' own figures in trade posts; counts of signals, entries, exits, refusals and skipped mirrors by reason; followed-set and tier changes; latency; and the operational counters.

**Replaced text, verbatim.** Each block is the exact v2 + A1 + A2 + A3 text that A4 replaced, in file order. The new text is in place at the named location, marked `(A4.n)`.

1. **A4, header, version line.** Replaced:

```text
Date: 2026-09-29. Author: quant-researcher. Version: **v2 + Addenda A1, A2 and A3** (all dated 2026-09-29, written before run 1 and before any real result).
```

2. **A4.9, header, run-1 precondition.** Replaced:

```text
- **Run 1 must not start until the PO has acknowledged every item in section 14.** **(A3.7)** Items 1-8 were acknowledged on 2026-09-29 (`docs/product/decisions.md`). Items 9 and 10, added by A3, are pending.
```

3. **A4.3, 4, metrics table, row "Missed exits".** Replaced:

```text
| **Missed exits (A3.1)** | count in `[t0, T_eval]` over all trades (in S or not); per missed exit: its class (late, reconstruction failed, orphan), its lag, the trade's actual R, its mirrored R (stop-first and TP-first) and its cost `mirrored hi R − actual R` (5.3). Feeds P4 and the go-live blocker ME. |
```

4. **A4.1-A4.4, 5.3, P4.** Replaced:

```text
| P4 [PO, A3.1] | At most 3 missed exits in the evaluation window, counted over all trades, and no missed-exit trade cost more than 1R against its mirrored outcome (missed-exit rules below). A trade in S with a missed exit counts at min(actual R, mirrored R) in every other condition. |
```

5. **A4.4, 5.3, F2.** Replaced:

```text
| F2 [PO, A3.1] | P4 is breached at or before `T_eval`: the 4th missed exit is ledgered, or a missed-exit trade's cost against its mirror is established above 1R (missed-exit rules below). The verdict is immediate. |
```

6. **A4.4, 5.3, precedence item 2.** Replaced:

```text
2. **FAIL by F1 or F2.** The breach happened at or before `T_eval` **(A3.1: F2's cost test on marked values is applied at `T_eval`)**; the run ends at that moment. **(A3.1)** A missed exit that does not breach P4 never ends the run and never changes this order; it enters the verdict only through its min(actual, mirrored) R and its evaluation close.
```

7. **A4.4, 5.3, reference to `eval_reference.py::verdict`.** Replaced:

```text
`scripts/eval_reference.py::verdict` implements this order and asserts every adjacent pair (E13; **(A3.1)** E15 adds `p4_breach`, which defines F2, and its cases).
```

8. **A4.10, 5.3, missed-exit rules, opening line.** Replaced:

```text
**Missed-exit rules (A3.1; PO spec-review decision A4).** They replace "0 missed exits, and any missed exit is an immediate FAIL". A missed exit never helps the verdict.
```

9. **A4.1, 5.3, missed-exit rules, class 1.** Replaced:

```text
  1. **late:** its exchange timestamp is outside downtime, and no mirroring ledger action exists within `exits.missed_exit_max_lag_s` (60 s, part of the frozen config) of it;
```

10. **A4.5, 5.3, missed-exit rules, class 2.** Replaced:

```text
  2. **reconstruction failed:** it is inside downtime, and the restart reconstruction did not settle it;
```

11. **A4.1, 5.3, missed-exit rules, class 3.** Replaced:

```text
  3. **orphan:** it is found only by leader reconciliation, more than `exits.missed_exit_max_lag_s` after its exchange timestamp, outside downtime.
```

12. **A4.1, 5.3, missed-exit rules, first sentence of the paragraph after the classes.** Replaced:

```text
  Rule-based non-mirrors are not missed exits: a partial skipped below $10, or a share already closed by our own SL/TP (`04-spec.md` §1).
```

13. **A4.2, 5.3, missed-exit rules, mirrored outcome, fill of a mirrored leader action.** Replaced:

```text
  - A mirrored leader action is decided at the leader event's exchange timestamp plus `copyreplay.delay_ms` (the replay's detection delay), and fills at the book recorded at that decision time plus `paper.ack_delay_ms`, walked with the share's size.
```

14. **A4.10, A4.2, A4.5, 5.3, missed-exit rules, gate R.** Replaced:

```text
- **Gate R.** A trade in S with a missed exit counts with `min(actual R, mirrored lo R)`, and its USD P&L with the same choice. A trade that is also flattened counts with the minimum of realised, shadow and mirrored lo R (`eval_reference.py::gate_r`). A missed exit can therefore only lower `LB_r(R)`, Σ USD and D_i.
```

15. **A4.3, 5.3, missed-exit rules, cost.** Replaced:

```text
- **Cost.** For every trade with a missed exit whose leader event falls in the evaluation window, in S or not: `cost = mirrored hi R − actual R`, in that trade's R, rounded half-even to 1e-6 (`eval_reference.py::missed_exit_cost`). The TP-first mirror is used so that a recording gap can't hide a cost.
```

16. **A4.4, 5.3, missed-exit rules, P4 and F2.** Replaced:

```text
- **P4 and F2.** P4 fails when more than 3 missed exits have a leader event in the evaluation window (counted over all trades, including those opened after the 300th), or when any cost is above 1.000000R (`eval_reference.py::p4_breach`). F2 fires at the moment the 4th missed exit is ledgered, or, for the cost, at the first moment when the trade and its mirror have both closed, or at `T_eval` with whichever is still open marked. The run then ends as FAIL (precedence item 2).
```

17. **A4.1, 5.3, missed-exit rules, verdict timing.** Replaced:

```text
- **Verdict timing.** The verdict is computed no earlier than `T_eval + exits.missed_exit_max_lag_s`, after one reconciliation pass over every share open at `T_eval`. So every missed exit whose leader event is at or before `T_eval` is in the ledger first. A missed exit whose leader event comes after `T_eval` does not enter the verdict; it is still a go-live blocker (ME, 5.6).
```

18. **A4.11, 5.5, `/stats`, last paragraph.** Replaced:

```text
  Operational counters are shown too: downtime used against the 2% budget (P5), missed exits with their costs (P4), and pending deploy rulings. Nothing else is shown. Adding a metric to `/stats` or to a report is a spec change, checked against this section.
```

19. **A4.6, 5.5, what still costs something, point 2.** Replaced:

```text
  2. **`/pause` can shape which trades enter S.** It is the one lever that changes the sample without ending the run: pausing through a stretch that looks bad lets later trades take those places among the first 300. It is capped by P5 (downtime < 2% of the window, about 14 hours in 30 days). From A3.2 b the B0d baseline no longer draws start times inside paused intervals (6.2), so a pause can't pull the baseline down with periods the copy sat out. The selection effect on S itself remains. It existed before A3, when trades and USD P&L were already visible; per-trader statistics make it better informed. Rough upper bound [EXPL, arithmetic, not simulated]: 2% of a 21-day window is about 10 hours, or about 6 of 300 trades. With perfect foresight, replacing six −1R trades by zero-mean ones raises the mean by at most 6/300 = 0.02R, about 0.3 standard errors. Real foresight gives much less.
```

20. **A4.8 d, 5.12, the three spec-review config changes, compressed recording bullet, one sentence.** Replaced:

```text
The provider, bucket, compression codec and local retention window are pre-run config.
```

21. **A4.10, 5.12, what A3 costs the verdict, A3.1, one sentence.** Replaced:

```text
So the gate sample is never better than a correct engine's, and A3.1 can only lower `LB_r(R)`, Σ USD and D_i.
```

22. **A4.6, 5.12, what A3 costs the verdict, A3.2, one sentence.** Replaced:

```text
A3.2 b can only lower D_i when pauses are aimed at bad stretches, and changes nothing in expectation when they aren't.
```

23. **A4.6, 6.2, B0d admissible start, blackout and downtime condition.** Replaced:

```text
  - t is not inside a configured entry blackout, **(A3.2 b)** nor inside a recorded downtime interval of P5 (process down, a data gap before resync, the access-degraded pause, the low-disk pause, a manual `/pause`, a deploy-wait pause), because our engine could not have entered then
```

24. **A4.6, 6.2, missing window, relaxed set (step 2), one fragment.** Replaced:

```text
restricted only by the listing, blackout and **(A3.2 b)** downtime conditions.
```

25. **A4.8 a, b, 6.2, recording integrity, hashed.** Replaced:

```text
- **Hashed.** Each finished recording file's sha256 is written to the ledger when the file is closed. Every read for the evaluation verifies it.
```

26. **A4.2, 6.2, recording integrity, a lost file is a gap, one sentence.** Replaced:

```text
Its effect goes through the existing rules only: the admissibility and missing-window rules above (P2c), the 1h-candle fallback for shadows and mirrors, and the D6 checks.
```

27. **A4.7, 6.3, majors and alts, untiered coins.** Replaced:

```text
  - a coin with no tier record at that time is an **alt for copies** (our trades, replays, B1, B3), which gives the higher fallback cost, and a **major for random-time baselines** (B0d, B0), which gives the lower one. Each choice can only lower R, or raise B̄ and so lower D.
```

28. **A4.7, 6.3, majors and alts, tier rule during a run.** Replaced:

```text
  - the tier rule and its thresholds are pre-run config, frozen with the config hash. During a run, assignments change only by that rule applied to recorded data.
```

29. **A4.1-A4.3, 7, K13.** Replaced:

```text
| **K13 (A3.1)** | Paper verdict FAIL through F2 (more than 3 missed exits, or one costing more than 1R) | An engineering failure, not evidence about the edge. Explain and fix every missed exit (ME) before run 2. Run 2, if started, is judged at 99% (5.4). |
```

30. **A4.9, 8.1, precondition.** Replaced:

```text
- **Precondition (BT2-5, A2.4, A3.7):** the PO's acknowledgement of every section-14 item is recorded in `decisions.md`. Items 1-8 were recorded on 2026-09-29; items 9 and 10 are pending.
```

31. **A4.11, 9.2, `eval.show_interim_stats`.** Replaced:

```text
| `eval.show_interim_stats` | **(A3.2)** `descriptive_only`: `/stats` and reports show USD P&L, win rate, average R (descriptive), drawdown, per-trader stats, counts, progress to 300 and the operational counters; the gate statistics listed in 5.5 are never computed or shown before `T_eval` | enum | PO (spec A14) + QR (A3.2) | FROZEN |
```

32. **A4.3, 9.2, `eval.missed_exit_max_cost_r`.** Replaced:

```text
| `eval.missed_exit_max_cost_r` | 1.0 (FAIL when `mirrored hi R − actual R` > 1R after rounding to 1e-6) | R | PO (spec A4) | FROZEN |
```

33. **A4.2, 9.2, `eval.missed_exit_gap_rule`.** Replaced:

```text
| `eval.missed_exit_gap_rule` | ambiguous 1h bar: stop first (lo) for the gate and P3, TP first (hi) for the cost | enum | QR (A3.1) | FROZEN |
```

34. **A4.6, 9.2, `baseline.dm_exclude_downtime`.** Replaced:

```text
| `baseline.dm_exclude_downtime` | true: no B0d start time inside a recorded downtime interval, `/pause` included | bool | QR (A3.2 b) | FROZEN |
```

35. **A4.7, 9.2, `cost.fallback_tier_rule`.** Replaced:

```text
| `cost.fallback_tier_rule` | major = the tightest liquidity tier at decision time; no tier record = alt for copies, major for random-time baselines (6.3) | enum | QR (A3.3; PO spec A6) | FROZEN |
```

36. **A4.8, 9.2, `eval.recording_integrity`.** Replaced:

```text
| `eval.recording_integrity` | lossless compression; per-file sha256 in the ledger, verified on every evaluation read; delete locally only after a verified upload; a missing or failed file is a recording gap (6.2) | | QR (A3.4; PO spec A10) | FROZEN |
```

37. **A4.11, 10.8, test 7.** Replaced:

```text
7. **(A3.2) Interim visibility.** Before `T_eval`, every command, report, log and the evaluation API serve only the 5.5 list: USD P&L, win rate, average R labelled descriptive, drawdown, per-trader stats, counts, progress to 300, and the operational counters. A request for any interval, standard error, t-statistic or p-value of R or D, for B0d values, D_i, P2c, FR1-FR6, K9 / S4, P6, G or a verdict preview returns `not_before_T_eval`. Instrumented functions show that none of them is computed before `T_eval`.
```

38. **A4.6, 10.8, test 22.** Replaced:

```text
22. **(A3.2 b) B0d and downtime.** No B0d draw, from the full or the relaxed set, falls inside a recorded downtime interval, `/pause` included.
```

39. **A4.9, 13, C15.** Replaced:

```text
| C15 (A3) | A run can now PASS with up to 3 missed exits. Each counts at its worse outcome, but the bug behind it may have changed things the mirror doesn't correct. | Every missed exit blocks go-live until explained and fixed (ME, 5.6). **Pending PO acknowledgement** (section 14, item 9) |
```

40. **A4.9, 13, C16.** Replaced:

```text
| C16 (A3) | `/stats` shows win rate, average R and per-trader figures during a run. It can't create a pass by luck, but it can prompt aborts on noise and targeted pauses. | Stated in 5.5 (A3.2). **Pending PO acknowledgement** (section 14, item 10) |
```

41. **A4.9, 14, status bullet.** Replaced:

```text
- **Status (A3.7):** items 1-8 acknowledged on 2026-09-29; items 9 and 10 pending.
```

42. **A4.9, 14, items 9 and 10 (whole items).** Replaced:

```text
**9. A missed exit counts at its worse result; more than 3, or one that cost more than 1R, fails the run.** (New, A3.1; your spec-review decision A4.)
- **What it means:** A missed exit is when a trader we copy closes or cuts a position and the bot doesn't follow within 60 seconds, or can't settle it after a restart.
  - For the verdict, that trade counts at the worse of two results: what it actually made, and what it would have made if the bot had followed on time. The second is simulated on our recorded market data, the same way as for `/flatten` (item 7). A bug can therefore never improve the verdict.
  - The run fails if there are more than 3 missed exits, or if any one of them cost more than 1R compared with following on time. We count every trade in the run window, including trades opened after the 300th, and missed exits that happen while new entries are paused.
  - Where our recordings have a gap, the simulated result is worked out the way that hurts the verdict: pessimistically when it counts toward the average, and generously when it decides whether a missed exit cost more than 1R.
  - Every missed exit blocks going live until its cause is written down and fixed with a test that reproduces it. Your review alone can't clear it.
- **Fixing it during a run:** A fix is a code change during the run (item 6). A fix to how the bot follows exits normally ends the run as ABORTED and uses up one of your 2 runs. Until the auditor rules, the old code keeps running, bug included, and pausing new entries while you wait counts as downtime. Usually the better choice is to let the run finish on the old code and fix the bug afterwards, before run 2 or any live step. The kill switch and `/flatten` always work.
- **The price:** a run with a harmless glitch is no longer thrown away. In exchange, a run can now pass even though the bot had up to 3 exit bugs. Those bugs can't raise the average, but a bug that misses exits may also have affected things we can't see, such as entries. That is why each one blocks going live until it is explained and fixed.
- **Replaces or interprets:** your decision A4, and the old rule "any missed exit fails the run at once".
- **If you say no:**
  - to counting at the worse result: a bug that happened to hold a winning trade longer would improve the verdict.
  - to counting trades after the 300th and missed exits during paused entries: some exit bugs would go uncounted, and the 3-bug limit would allow more real bugs.
  - to the whole item: we return to the old rule, where a single missed exit fails the run at once.
- **Status:** pending PO acknowledgement.

**10. `/stats` shows how the run is going, never how the verdict is going.** (New, A3.2; your spec-review decision A14.)
- **What it means:** During a run, `/stats` shows your P&L in dollars, win rate, average R, drawdown, the same figures per trader, and progress toward 300 trades. It also shows downtime used, missed exits and pending code rulings. The bot never computes or shows these before the end: the confidence interval the verdict uses, the baseline test, the fragility checks, or anything like "on track to pass".
- **Why this is safe:** Seeing the numbers can tempt you to stop a run that looks bad, or to change settings. Neither can produce a pass by luck: a stopped or changed run ends as ABORTED, which is never a pass, and it still counts as one of your 2 runs. So the limit in item 1 (at most 2.5% chance of passing by luck across both runs) holds whatever you decide after seeing the numbers. The round-2 audit made this argument.
- **What remains, plainly:**
  - **Early numbers are mostly noise.** After 50 trades the average R can easily be 0.3R off the truth, three times the edge we are looking for. Stopping a run because it looks bad uses it up, and run 2 is much harder to pass: a real +0.10R edge passes it only about 3 to 9 times in 100.
  - **`/pause` changes which trades are counted.** Pausing through a stretch that looks bad lets later trades take those places among the first 300. The 2% downtime limit caps this at about 14 hours in 30 days, and the baseline no longer samples the paused hours. Our rough estimate of the most this could move the average, even if you could see every bad stretch coming, is 0.02R. Small, but not zero.
  - **Hiding the confidence interval is a guard against habit, not a lock.** You could estimate it roughly from the trades you see. What protects the verdict is that it is computed once at the end, that stopping early never passes, and that every run counts.
  - **A code change prompted by the numbers ends the run.** If the stated reason for a mid-run code change is what `/stats` shows, rather than a bug, the auditor rules the run ABORTED.
- **Replaces or interprets:** your decision A14, and the earlier rule "no interim statistics".
- **If you say no:**
  - to the limits (you want the interval or a preview shown): that needs a new addendum. It wouldn't by itself create passes by luck, but it would make stopping or pausing on noise much more tempting, which wastes runs.
  - to showing more: we return to the earlier rule, where you see trades, positions and dollar P&L only. The protection against passing by luck is the same either way.
- **Status:** pending PO acknowledgement.
```

43. **A4, 15, note after the round-3 table, last sentence.** Replaced:

```text
A3 has not yet been audited.
```

**Additions (no v2 + A1 + A2 + A3 text removed):**
- A4: header, the A4 bullet and the inputs line
- A4.1: 5.3, missed-exit rules, the rest of the paragraph after the classes ("Leader exit event and handled"; its replaced first sentence is quoted above)
- A4.1: 5.3, missed-exit rules, new bullet "Leader-fill audit"
- A4.5: 5.3, missed-exit rules, new bullet "Settled after a data gap"
- A4.2: 5.3, missed-exit rules, "Mirrored outcome", three new sub-bullets (fills without a recorded book, uncomputable mirror, candle store)
- A4.1-A4.5: 5.3, "Also computed at `T_eval`", new bullet
- A4.11: 5.5, new bullet "What 'nothing else' covers"
- A4: 5.13 (this section)
- A4.6: 6.2, new bullet "Discretionary pauses: B̄_i = max"
- A4.8 c, d: 6.2, recording integrity, two new bullets
- A4.1-A4.8: 9.2, eight new rows after `eval.recording_integrity`
- A4.12: 10.8, test 21, new bullet; A4.7: test 23, two new bullets; A4.8: test 24, four new bullets; tests 25-29 (new)
- A4.12: 12, E15 row, "Superseded by E16 (A4.12)." at the start of the description; new E16 row
- A4.9: 14, opening paragraph, new sentences after "... and what they cost."
- A4: 15, round-4 closure table (new)

**Outside this file (not hashed in the run record):** `scripts/eval_reference.py` v4 (E16) and `scripts/README.md` (E16 references). `research/data/eval_reference_vectors.txt` was regenerated. `run-register.md` is unchanged.

**Not frozen, logged for completeness:** the sha256 values of the script and of its output are in section 12 (E16).

**What A4 costs the verdict:**
- **A4.1, A4.2 and A4.3 can only add P4 breaches.** More missed exits are found, gaps are priced against us, costs can't net out, and missing data counts as a breach. They make FAIL more likely and never make PASS more likely. A4.2 also pins the gate side: a gap can only lower mirrored lo R.
- **A4.4 moves outcomes between non-PASS verdicts only.** A breach found after `T_eval` is now FAIL instead of INCONCLUSIVE. A breach found after a later abort, with an earlier breach time, is now FAIL instead of ABORTED. No outcome moves to or from PASS.
- **A4.5 is the one item that relaxes something, stated for honesty.** Read literally, A3 made any exit inside a data gap, even one of 5 s, a missed exit counting toward the limit of 3. Now an exit handled within 60 s of the resync doesn't count, so fewer runs FAIL on spurious missed exits. No statistic is relaxed: the trade still counts at min(actual R, mirrored lo R), and the gap is downtime for P5. Against the lenient reading (a late fill counted at its actual R), A4.5 is stricter.
- **A4.6 can only raise B̄_i**, and so lower D_i and `LB_r(D)`: P2c becomes harder when the PO pauses. Without a discretionary pause nothing changes.
- **A4.7 makes K9 harder** (a go-live blocker, not the verdict). The daily recompute moves coins between tiers as their measured liquidity changes, under the frozen rule. That changes fallback costs and tradability in both directions; it is strategy behaviour, not a verdict rule, and every table is in the ledger.
- **A4.8 (a)-(c) only turn unverifiable data into gaps,** which go through the existing gap rules. (d) removes one way to lose a run to an ABORTED config change during a storage outage. It can't change any byte the evaluation reads.
- **A4.9, A4.10 and A4.11 change no statistic.** A4.11 pins which content may be shown and adds no computation before `T_eval`. **A4.12 changes no rule.**
- **No simulated figure in 5.9 changes.** The simulations model a correct engine and no pauses.
- **Nothing in A4 makes a statistical PASS easier.** P2c keeps its gating status (A1.4), and A4.6 tightens it.

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
  - t is not inside a configured entry blackout, **(A3.2 b, A4.6)** nor inside a recorded **non-discretionary** downtime interval of P5 (process down, a data gap before resync, the access-degraded pause, the low-disk pause), because our engine could not have entered then. **Discretionary pauses** (a manual `/pause`, a deploy-wait pause) follow the max rule below.
- **(A4.6) Discretionary pauses: B̄_i = max.** When a discretionary pause interval intersects the range trade i's start times are drawn from, the 1,000 replications (tag `b0d`, counters (trade index, replication), as before) are drawn from the admissible set **without** excluding the discretionary pause intervals. `B̄_i^incl` is the mean R of all of them; `B̄_i^excl` is the mean R of those whose start time lies outside every discretionary pause interval. Then **`B̄_i = max(B̄_i^incl, B̄_i^excl)`**, or `B̄_i^incl` if no replication starts outside (`eval_reference.py::b_bar_discretionary`).
  - Without such an intersection the draw is exactly the A3.2 b draw.
  - Both means come from the same draws, so when the pauses are short (P5 caps them at 2%) the max adds almost no noise bias. Two independent draws would bias B̄ up by about 0.02R per trade from noise alone.
  - The rule applies wherever B̄ is drawn: the full window, the partial set (step 1) and the relaxed set (step 2) below. The 24-hour test for a missing window is still measured with every downtime interval excluded.
  - Why: a pause through a stretch that was good for the copy's direction would otherwise remove good baseline times, lower B̄ and raise D_i (backtest-audit-r4 BT4-6). With the max, compared with not pausing, a pause can only raise B̄_i and lower D_i. The non-discretionary intervals keep plain exclusion, because nobody chooses when they happen. The contrived ways to create them on purpose (shutting down the PC, filling its disk) remain, bounded by P5.
- **No extension.** Draws are never taken from outside `[t0, T_eval − hold_i]`: no pre-paper period, and no other coin.
- **Delisted coin.** Windows must end before the last trading moment. A trade in S that ended by delisting settlement uses its hold to settlement, and its replications exit by time at hold_i.
- **Missing window (A1.3 g, A2.3 a).** If the admissible set for trade i totals less than 24 hours of start times (or is empty), trade i has no admissible B0d window. It gets **`D_i = min(R_i, 0, R_i − B̄_i^partial)`**, where `B̄_i^partial` is the first of these that exists:
  1. the mean R of 1,000 replications drawn (tag `b0d`, the same counters) from trade i's admissible set, however short;
  2. if that set is empty: the mean R of 1,000 replications drawn from the **relaxed** set, `[t0, T_eval − hold_i]` restricted only by the listing, blackout and **(A3.2 b, A4.6)** downtime conditions, with discretionary pauses under the max rule above. Where our book or mid recording is missing, a replication uses the coin's median recorded half-spread without the ×1.5 multiplier (else 2 bps majors, 8 bps alts; majors and alts as defined in 6.3, A3.3) and exchange 1h candles for its SL/TP path, with an ambiguous bar resolved in the replication's favour (TP first);
  3. if the relaxed set is also empty: the largest B̄_j (full or partial) of any trade j in S with the same direction, floored at 0; 0 if there is none (`eval_reference.py::b_partial_last_resort`).
- **What this bounds, and what it doesn't (A2.3 a).** v2 + A1 used `min(R_i, 0)` and claimed that gaps can't help a run pass. That was false. When `B̄_i > max(R_i, 0)`, for example a long, high-beta hold in a rising market, the true `D_i = R_i − B̄_i` is below `min(R_i, 0)`, and recording gaps concentrate on such long holds (BT3-3). With A2.3 a a missing-window trade never contributes more than 0, nor more than its excess over the partial baseline. A residual leak remains, because a short or relaxed window can estimate B̄_i with bias; the 10% cap bounds it.
  - The count, and the step (1-3) used for each trade, are reported.
  - If more than 10% of S (more than 30 trades) have no admissible window, P2c fails (5.3).
- **(A2.3 a) Recorder gap rate, reported before run 1.** From the 24h dry run and the ≥ 1 week of pre-paper recording (8.1), report per coin: the share of time with no recorded L2 book within 5 s, the share with a mid or mark gap over 60 s, and the projected share of trades that would lack an admissible window (the point-in-time replay's trades run through the admissibility rule). It goes to the PO with section 14 (item 8). It is not a gate. If the projected share is near 10%, fix the recorder before run 1, because P2c would otherwise fail by construction.

**Recording integrity (A3.4; PO spec-review decision A10).** Recordings may be stored compressed and uploaded to object storage, with only a rolling window kept on the PC. Everything the evaluation reads from them (B0d, `/flatten` shadows, missed-exit mirrors, marking, P3 marks, the P6 replay) must read what was recorded:
- **Lossless.** Compression is lossless: the decompressed records are byte-identical to what the recorder wrote.
- **Hashed (A4.8 a, b).** Each recording file has two hashes in the ledger: the sha256 of its **uncompressed record stream** (the exact bytes the recorder serialised, in order) and the sha256 of its **transport object** (the compressed file as stored and uploaded).
  - While a file is open, the recorder ledgers a **segment record** every `recording.segment_hash_minutes` (5) minutes. It holds the stream sha256 of the records written since the previous segment, their count, and a chain hash `sha256(previous chain hash ‖ segment stream sha256)`. The first segment chains from the sha256 of the file's path.
  - At close, both whole-file hashes are ledgered.
  - Every read for the evaluation verifies the transport hash of a closed file, and the stream hash after decompression.
  - **Only hashed data exists.** Records not covered by a ledgered segment or file hash are a recording gap, like a lost file: for example the tail after a crash, or a file that was never closed. A file that was never closed is usable up to its last ledgered segment. A crash therefore costs at most the last 5 minutes of recording, and never makes a whole file unusable.
- **No early delete.** A file is deleted from the PC only after its uploaded copy has been read back and its sha256 verified.
- **A lost file is a gap.** A file that is missing, or fails its hash, is a gap in our recording. It is never replaced by re-recording, by another data source, or by a copy that doesn't match its hash. Its effect goes through the existing rules only: the admissibility and missing-window rules above (P2c), the candle fallback for shadows and mirrors **(A4.2: 1m, else 1h, from the candle store)**, and the D6 checks.
- **The recorder is engine code.** The recorder, including compression, upload and retention, is engine source in the engine path set (`src/copytrade/**`, spec F1). During a run, the recording process runs the run commit from the run worktree (A2.2), and a change to it is a mid-run deploy (5.3).
- **(A4.8 c) Verdict values are recomputed from verified files.** Live mirror, gate and cost values (for the alerts and for an immediate F2) may read files that are not closed yet. At the verdict, and at an early end of the run, every mirror, gate R and cost is recomputed from hash-verified data only. The recomputed values decide P4, F2 and gate R.
  - A breach that only the recomputation finds is F2, at its breach time (5.3).
  - A live F2 that the recomputation doesn't confirm means an engine error ended the run. The backtest-auditor rules on it (precedence item 1). The run can't resume, still counts, and can never become a PASS.
- **(A4.8 d) Storage destination.** The object-storage provider, endpoint, bucket and credentials are operational settings **outside the frozen config hash**. (The spec already reads the endpoint, bucket and keys from the environment, F23.AC5; A3.4's text wrongly called them pre-run config.) Each change is ledgered with a destination ID (the sha256 of the endpoint and bucket, no secrets). It is neither a config change nor a deploy. Why this can't change what the evaluation reads:
  1. Every byte the evaluation reads is verified against the ledger's stream hash, so the destination can't change any value read.
  2. A destination change can't create a loss. A local file is deleted only after a verified read-back from the destination in force. The store interface reads locally first, then every destination in the ledger, newest first. A file is lost only when no local copy and no copy in any ledgered destination matches its hash. Deleting an old bucket is a loss like any other: ledgered, alerted, and reviewed by the auditor.
  3. Its only other path is disk space. A failing destination stops pruning, and after days of backlog the disk floor brings downtime and recording gaps. A switch can only shorten such an episode, which is repair, like restarting a crashed process.

  The local retention window, the cache size and the upload timings **stay in the frozen config**. They set local disk use directly, so they could bring the disk floor (downtime, recording gaps) at a chosen time. That is not provably neutral.

### 6.3 Cost model

- **Fees:** taker 0.045% per side on every paper fill, including SL and TP, which trigger on mark price and fill as market orders. No maker fills or rebates are assumed. HIP-3 markets are not traded in v1 [PO].
- **Spread and impact (paper):** the fill walks the live L2 book captured at decision time plus `paper_ack_delay_ms`. The default is 1,000 ms, from the median order-to-fill of about 884 ms from Tokyo (market-context 2.4).
- **Spread and impact (replay and baselines):** the **spread recorded at signal time** (BT-13). The fallback, when no recording exists, is each coin's median half-spread from our recordings × 1.5, then 2 bps for majors and 8 bps for alts, per side.
- **Delay slippage (replay):** our measured `decay(Δ)` at the p95 detection latency. The fallback is 5 bps for majors and 15 bps for alts. It applies to copies (our trades, replays, B1, B3), never to random-time baselines.
- **Random-time baselines (B0d, B0; A1.1):** fees, plus spread and impact from the book recorded at their own fill times, plus their own ack-delay drift, plus funding. **(A2.3 b)** Their R is computed from their fill prices, fees and funding; the drift and the spread and impact are reported components of those fill prices, never added on top. **No delay slippage and no decay:** they follow no signal.
- **Stops:** fill at the book at trigger plus the ack delay, with no guaranteed stop price (gap-through is modelled).
- **Funding:** accrued hourly from actual rates [PO].
- **Liquidation:** isolated positions use the mark-price and maintenance-margin model.
- **(A3.3) Majors and alts (PO spec-review decision A6).** Coin tiers are assigned automatically from measured liquidity, not from a BTC/ETH list. Wherever this file says "majors" and "alts" (the fallback costs in 6.2 and 6.3, and the table below):
  - a **major** is a coin in the tightest liquidity tier (the tier with the tightest slippage and spread thresholds), in the tier assignment in force at the decision time of the trade or replication, read from the ledger's tier records; every other tier is an **alt**
  - **(A4.7)** a coin with no tier record at that time is an **alt for our own trades and their replays** (paper trades, the point-in-time and P6 replays, the restart reconstruction, `/flatten` shadows), which gives the higher fallback cost. It is a **major for every baseline or comparator we are measured against** (B0d, B0, B0b, B1, B3), which gives the lower one. Each choice can only lower our R, or raise a comparator's R (B̄, B1's mean R) and so make P2c and K9 harder. Missed-exit mirrors use the fixed pair of A4.2 (8 bps for lo, 2 bps for hi), whatever the tier.
  - **(A4.7)** the tier rule, its thresholds and its recompute interval are pre-run config, frozen with the config hash. The table in force at `t0` is stored in the run record. During a run, assignments are **recomputed by that rule from recorded data every `tiers.recompute_interval_h` (24 h)**. Each table is ledgered with its sha256, its input window and its computation time, and is in force from its ledger time. The table in force at a decision time is the latest one ledgered at or before it. A recomputed table is not a config change. A table in force that the frozen rule doesn't reproduce from the recorded data (for example, one edited by hand) is a config change: ABORTED.

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
| **K13 (A3.1, A4.1-A4.3)** | Paper verdict FAIL through F2 (more than 3 missed exits, or one costing more than 1R, incrementally or per trade; or an uncomputable mirror or an incomplete fill audit) | An engineering or data failure, not evidence about the edge. Explain and fix every missed exit (ME) before run 2, and the cause of any uncomputable mirror or incomplete audit. Run 2, if started, is judged at 99% (5.4). |

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
- **Precondition (BT2-5, A2.4, A3.7, A4.9):** the PO's acknowledgement of every section-14 item is recorded in `decisions.md`. Items 1-8 were recorded on 2026-09-29. Items 9 and 10 were acknowledged on their A3 wording and rewritten by A4; their re-acknowledgement is pending.
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
| `eval.show_interim_stats` | **(A3.2, A4.11)** `descriptive_only`: before `T_eval`, run-result content is limited to the `/stats` list (USD P&L, win rate, average R labelled descriptive, drawdown, per-trader stats, counts, progress to 300, the operational counters) and each trade's own post; operational content not computed from outcomes may be shown (5.5); the gate statistics listed in 5.5 are never computed or shown before `T_eval` | enum | PO (spec A14) + QR (A3.2, A4.11) | FROZEN |
| `eval.missed_exit_max_count` | 3 (FAIL at the 4th, counted by leader event time in `[t0, T_eval]` over all trades) | missed exits | PO (spec A4) | FROZEN |
| `eval.missed_exit_max_cost_r` | **(A4.3)** 1.0 (FAIL when any incremental cost `hi R(M_j) − hi R(M_{j−1})` or the trade cost `hi R(M_k) − actual R`, with actual = realised R, is > 1R after rounding to 1e-6; an uncomputable mirror counts as > 1R) | R | PO (spec A4) + QR (A4.3) | FROZEN |
| `eval.missed_exit_gate_rule` | `min_actual_mirrored`: gate R = min(actual, mirrored lo); evaluation close = the later of the real close and the mirror exit (5.3) | enum | PO (spec A4) + QR (A3.1) | FROZEN |
| `eval.missed_exit_gap_rule` | ambiguous 1h bar: stop first (lo) for the gate and P3, TP first (hi) for the cost. **(A4.2)** A fill without a recorded book: the 1m candle, else the 1h candle, from the candle store; lo = worst price + 8 bps, hi = best price + 2 bps, plus taker fee; an SL/TP in a gap fills at the trigger or a gapped-through open, ± 8 / 2 bps. No candle within `eval.missing_data_retry_max_h`: uncomputable (> 1R, lo = actual) | enum | QR (A3.1, A4.2) | FROZEN |
| `exits.missed_exit_max_lag_s` | 60 | s | PM (spec A4); it now enters the verdict (A3.1) | FROZEN |
| `baseline.dm_exclude_downtime` | **(A4.6)** true: no B0d start time inside a recorded non-discretionary downtime interval; discretionary pauses (`/pause`, deploy-wait) follow `baseline.dm_discretionary_pause_rule` | bool | QR (A3.2 b, A4.6) | FROZEN |
| `cost.fallback_tier_rule` | **(A4.7)** major = the tightest liquidity tier in the table in force at decision time; no tier record = alt for our trades and their replays, major for every baseline and comparator (B0d, B0, B0b, B1, B3); tier rule and thresholds frozen, assignments recomputed every 24 h and ledgered (6.3) | enum | QR (A3.3, A4.7; PO spec A6) | FROZEN |
| `eval.recording_integrity` | lossless compression; **(A4.8)** per file, a stream sha256 (uncompressed records) and a transport sha256 (compressed object), plus a hash-chained segment record every `recording.segment_hash_minutes`; both verified on every evaluation read; data without a ledgered hash is a gap; delete locally only after a verified read-back; a missing or failed file is a recording gap; verdict values recomputed from verified data (6.2) | | QR (A3.4, A4.8; PO spec A10) | FROZEN |
| `eval.fill_audit_interval_h` | **(A4.1)** 24: a leader-fill audit (`userFillsByTime` against the ledger) every 24 h for every leader with a share open since the previous audit, plus a final audit to `T_eval` before the verdict; reconciliation checks fills and sizes | h | QR (A4.1) | FROZEN |
| `eval.missing_data_retry_max_h` | **(A4.1, A4.2)** 72: retry bound for an audit interval or a needed candle; after it, an unaudited stretch or an uncomputable mirror is a P4 breach | h | QR (A4.1, A4.2) | FROZEN |
| `eval.missed_exit_cost_rule` | **(A4.3)** `incremental_and_trade`: mirrors M_1..M_k, incremental costs and the trade cost, each tested against 1R; actual R = realised R | enum | QR (A4.3) | FROZEN |
| `eval.p4_breach_time` | **(A4.4)** leader event time of the 4th missed exit (event order); for a cost, when it is established, capped at `T_eval`; uncomputable: the first missed exit's event time; incomplete audit: start of the unaudited stretch. ABORTED wins only when strictly earlier | enum | QR (A4.4) | FROZEN |
| `eval.settled_gap_rule` | **(A4.5)** an exit inside a data gap handled within 60 s of the resync is settled: not a missed exit; gate R = min(actual, mirrored lo); otherwise class 2 | enum | QR (A4.5) | FROZEN |
| `baseline.dm_discretionary_pause_rule` | **(A4.6)** `max_incl_excl`: draws over the admissible set with discretionary pauses included; B̄_i = max(mean of all, mean of the draws outside the pauses) | enum | QR (A4.6) | FROZEN |
| `recording.segment_hash_minutes` | **(A4.8)** 5 | min | QR (A4.8) | FROZEN |
| `recording.candle_store` | **(A4.2)** hourly: 1m and 1h exchange candles of the hour just closed, for every coin with an open share, shadow or mirror in that hour; stored and hashed like recordings | | QR (A4.2) | FROZEN |
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
7. **(A3.2, A4.11) Interim visibility.** Before `T_eval`, every command, report, alert, log and the evaluation API serve run-result content (5.5, A4.11) only from the 5.5 list: USD P&L, win rate, average R labelled descriptive, drawdown, per-trader stats, counts, progress to 300, and the operational counters, plus each trade's own post. Operational content that is not computed from outcomes (5.5) may appear in `/status`, `/traders`, alerts and reports, with no gate label. A request for any interval, standard error, t-statistic or p-value of R or D, for B0d values, D_i, P2c, FR1-FR6, K9 / S4, P6, G or a verdict preview returns `not_before_T_eval`. Instrumented functions show that none of them is computed before `T_eval`. A rendering test over every template finds no outcome aggregate outside the 5.5 list (for example a per-coin or weekly mean R, a payoff ratio or an exit-reason mix).
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
21. **(A3.1) Missed exits.**
    - The E15 vectors `GOLDEN_MISSED` and `GOLDEN_MISSED_CLOSE` are reproduced, and each of the six A3.1 mutants (M11-M16, section 12) fails at least one test.
    - A trade in S with a missed exit counts with min(actual R, mirrored lo R), and its USD P&L with the same choice. A trade that is also flattened counts with the minimum of the three. P3's shadow equity uses the stop-first mirror.
    - Three missed exits, each costing at most 1R, don't end the run, and a PASS is still possible. The 4th ends the run as FAIL at the moment it is ledgered. A cost of 1.000000R after rounding doesn't fail; 1.000001R does.
    - A missed exit on a trade opened after the 300th counts toward the 4 and toward the cost test, but its R never enters S.
    - A mirror action is decided at the leader event time plus `copyreplay.delay_ms` and filled at the book recorded at that time plus `paper.ack_delay_ms`. Over a recording gap with an ambiguous 1h bar, the gate uses the stop-first mirror and the cost uses the TP-first mirror.
    - `T_eval`, hold_i, the merged-position interval and the B0d hold use the later of the real close and the mirror exit. A mirror still open at `t300 + 7 days` is marked.
    - A late mirror during `/pause` (entries paused, exits managed) is a missed exit. An exit during process-down that the reconstruction settles is not.
    - The verdict is computed only after `T_eval + exits.missed_exit_max_lag_s` and a reconciliation pass: a leader event at `T_eval − 10 s` that is never mirrored is counted.
    - Every missed exit, including one after `T_eval`, appears as blocker ME in the report.
    - **(A4.12)** The E16 vectors `GOLDEN_A4_COST`, `GOLDEN_A4_GAP_CANDLE`, `GOLDEN_A4_GAP_FILL`, `GOLDEN_A4_BREACH`, `GOLDEN_A4_RUN_END`, `GOLDEN_A4_CLASS` and `GOLDEN_A4_BBAR` are reproduced, and each of the 15 A4 mutants (M17-M31, section 12) fails at least one test.
22. **(A3.2 b, A4.6) B0d and downtime.** No B0d draw, from the full or the relaxed set, falls inside a recorded non-discretionary downtime interval. With a discretionary pause (`/pause`, deploy-wait) in the draw range, the draws come from the set with the pause included, and B̄_i = max(mean of all, mean of the draws outside the pause). On a fixture where the paused stretch is good for the trade's direction, B̄_i equals the mean including it; where it is bad, the mean excluding it. Without a discretionary pause the draws equal the A3.2 b draws.
23. **(A3.3) Fallback tiers.** A coin in the tightest liquidity tier at decision time uses the major fallback costs. A coin with no tier record uses the alt fallback for a copy and the major fallback for a B0d or B0 replication.
    - **(A4.7)** A coin with no tier record also uses the major fallback in B0b, B1 and B3.
    - **(A4.7)** During a run a table is recomputed and ledgered every 24 h and is in force from its ledger time. A decision uses the latest table ledgered at or before it. Recomputing a ledgered table from its recorded inputs reproduces it byte for byte; a table that doesn't reproduce makes the run ABORTED. A recomputed table is never a config change.
24. **(A3.4) Recording integrity.**
    - A decompressed recording file is byte-identical to what was written.
    - A file whose content doesn't match its ledger sha256 is treated as a gap by B0d admissibility, shadows, mirrors and the replay.
    - Deleting a local file before its upload has been verified is refused.
    - During a run, the recording process runs the run commit from the run worktree.
    - **(A4.8)** Each file has a stream sha256 and a transport sha256 in the ledger, and both are verified on read. Recompressing a file with another codec setting changes its transport hash but not its stream hash.
    - **(A4.8)** A segment record is ledgered every 5 minutes while a file is open, and the chain verifies. After a force-kill, records up to the last ledgered segment are read and the rest is a gap; a file never closed is usable up to its last segment.
    - **(A4.8)** On a fixture where a live mirror read an unclosed file whose later bytes differ, the verdict uses the value recomputed from verified data.
    - **(A4.8)** Changing the storage destination during a run is neither a config change nor a deploy; it is ledgered. A file uploaded only to the old destination is still read from it. Local deletion before a verified read-back from the destination in force is refused. The retention window, cache size and upload timings are in the config hash.
25. **(A4.1) Leader-fill audit and reconciliation.**
    - On fixtures with a dropped reduce, a close and reopen between two reconciliation passes, and a leader close that our SL closes 5 minutes later, the daily audit ledgers each as an orphan missed exit before P4 and gate R are computed.
    - A leader close handled 60 s after it is not a missed exit; 61 s is. A partial skipped below $10 and recorded within 60 s is not a missed exit; recorded later, it is.
    - Reconciliation flags a size mismatch (the leader reduced while the sign is unchanged) and runs the detector.
    - With the API unavailable for 72 h after `T_eval` + 60 s over a stretch where we held a leader's share, the verdict is FAIL (F2) with breach time at the start of that stretch.
    - The verdict is not computed before the final audit has covered every leader up to `T_eval`, or the 72 h bound has passed.
    - `exit_class` reproduces `GOLDEN_A4_CLASS`.
26. **(A4.2) Mirror fills without a book.**
    - With no book within 5 s of the fill time, a mirrored buy fills at the 1m candle's high + 8 bps (lo) and its low + 2 bps (hi); a sell at the low − 8 bps and the high − 2 bps. With the 1m candle absent, the 1h candle is used. `GOLDEN_A4_GAP_CANDLE` and `GOLDEN_A4_GAP_FILL` are reproduced.
    - An SL triggered inside a gap fills at the stop, or at the bar's open if the bar opened through it.
    - With neither candle available for 72 h, the mirror is uncomputable: F2 at the missed exit's event time, and gate R = actual R.
    - The candle store holds the 1m and 1h candles of every hour for every coin with an open share, shadow or mirror, each hashed in the ledger; the evaluation reads candles only from it.
27. **(A4.3) Incremental costs.** Two missed exits on one share with incremental costs +1.3R and −0.5R (trade cost 0.8R) breach P4. For a flattened trade, actual R is the realised R at the flatten. `GOLDEN_A4_COST` is reproduced.
28. **(A4.4) Breach time.** Four missed exits whose 4th by event time is at 9 h, three of them ledgered by the audit at 24 h, breach at 9 h. An ABORTED at 10 h is then FAIL, an ABORTED at 8 h is ABORTED, and one at exactly 9 h is FAIL. A 4th missed exit found by the final audit after `T_eval`, with its leader event before `T_eval`, is FAIL. `GOLDEN_A4_BREACH` and `GOLDEN_A4_RUN_END` are reproduced.
29. **(A4.5) Settled after a data gap.** An exit inside a data gap handled at resync + 60 s is settled: it is not counted toward P4, and its trade counts at min(actual R, mirrored lo R). At resync + 61 s it is a missed exit (reconstruction failed).

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
| E14 | **Superseded by E15 (A3.6).** `eval_reference.py` v2 (A2.1, A2.3 a, A2.7): section labels fixed; the shadow exit as the evaluation close (`eval_close_ms`, `t_eval_ms`, `hold_ms`, `is_marked`); `D_i = min(R_i, 0, R_i − B̄_partial)` with the last-resort step; the seed must be 32 raw bytes; **golden asserts** for every printed vector. New vectors: RNG rejection (n = 2^63 + 1; blocks rejected at i = 0 and 4), the percentile floor at a non-integer B·α/2, unequal cluster sizes, the order-statistic neighbours of a 40-cluster sample, D_i, and `/flatten`. | `570b152ae4b483663154bfa2dabc03863e5134d1bf43566f5bc81c14022859bc` | `research/data/eval_reference_vectors.txt` `fbe80bb0ee65b785ed8fe16743debf250830fd4a9ded883286345c67fe828b8f` | `selftest OK (golden vectors asserted)`; two runs byte-identical; about 5 s. The E13 lines are unchanged and now asserted: the RNG list, day clusters, toy CIs and B0d draws are the values the auditor reproduced independently in round 3. **Mutation check:** 10 mutants, all fail the self-test: bootstrap lower index +1; upper index +1; percentile index rounded up; D reverted to `min(R, 0)`; flattened trade closed at its real close; hex-text seed accepted; open shadow not marked; RNG without rejection; bootstrap mean of cluster means; cluster-robust t without G/(G−1). Before the rejection and non-integer-index vectors were added, the no-rejection and rounded-index mutants survived; the mean-of-cluster-means mutant is equivalent on the equal-size toy sample. That is why those vectors exist. | no |
| E15 | **Superseded by E16 (A4.12).** `eval_reference.py` v3 (A3.1, A3.6): `Trade` gains `missed_exit` and `mirror_close_ms`; `eval_close_ms` returns the later of the real (or shadow) close and the mirror exit; new `gate_r` (min of realised, shadow and stop-first mirror), `missed_exit_cost` (TP-first mirror − actual, rounded to 1e-6), `p4_breach` (> 3 missed exits or a cost > 1R, which defines F2); `verdict` unchanged except its docstring. New golden vectors `GOLDEN_MISSED` (gate R, cost, P4, including −2.003 / −1.003R, whose binary64 difference is 1.0000000000000002 but rounds to 1.000000) and `GOLDEN_MISSED_CLOSE` (`T_eval`, hold, marking and day clusters with a mirror exit), plus verdict cases. Every E14 golden literal is unchanged. | `74dfcdb23ae2aa2f13f427af95e49a0c1053e0465f52cdfcdf844c7d87d00fad` | `research/data/eval_reference_vectors.txt` `f5a0dd09c8051e8192b6d8d69cc553d5febab658ba165504250d2036ed3ff55d` | `selftest OK (golden vectors asserted)`; two runs byte-identical; about 5 s. Against the E14 output, the only differences are the first line ("addenda A1, A2 and A3") and two new lines (missed exits, missed-exit evaluation close). **Mutation check, 16 mutants, all fail the self-test:** the 10 E14 mutants, recreated (M1 bootstrap lower index +1, M2 upper index +1, M3 index rounded up, M4 D back to `min(R, 0)`, M5 flattened trade closed at its real close, M6 hex-text seed accepted, M7 open shadow not marked, M8 RNG without rejection, M9 mean of cluster means, M10 cluster-robust t without G/(G−1)), and 6 new ones (M11 missed exit counted at actual R, M12 FAIL at 3 missed exits, M13 cost ≥ 1R fails, M14 cost from the stop-first mirror, M15 evaluation close ignores the mirror, M16 cost compared without rounding). The harness was a throwaway script outside the repository. | no |
| E16 | `eval_reference.py` v4 (A4.1-A4.6, A4.12). New functions: `missed_exit_costs` (incremental costs over the mirror chain M_1..M_k plus the trade cost; an uncomputable mirror costs `Infinity`), `mirror_lo_for_gate` (uncomputable: lo = actual), `gap_candle` (1m, else 1h, else uncomputable), `gap_fill_px` (worst price + 8 bps for lo, best price + 2 bps for hi), `gap_trigger_px` (SL/TP in a gap at the trigger or a gapped-through open), `MissedExit` and `p4_breach_time` (4th by event time; cost established, capped at `T_eval`; incomplete audit), `run_end` (ABORTED only when strictly earlier than the breach), `exit_class` (on time, late, orphan, settled after a restart, settled after a data gap, reconstruction failed), and `b_bar_discretionary` (max of the means with and without the paused starts, from the same draws). `verdict`'s logic is unchanged; its docstring now defines f2 by `p4_breach_time`. New golden vectors: `GOLDEN_A4_COST`, `GOLDEN_A4_GAP_CANDLE`, `GOLDEN_A4_GAP_FILL`, `GOLDEN_A4_BREACH`, `GOLDEN_A4_RUN_END`, `GOLDEN_A4_CLASS` and `GOLDEN_A4_BBAR`, all computed by hand before the first run and reproduced by it unchanged, plus five new verdict cases. Every E15 golden literal is unchanged. | `15522b6040991f51ef6d5f82171cfe06ddde167112f3a8f0a29a070180b1c557` | `research/data/eval_reference_vectors.txt` `e0e3da9f71e18f2dfb1fffe7aef6218de939a5c52d36d2d9035f4477c071dc04` | `selftest OK (golden vectors asserted)`; three runs byte-identical; about 5 s. Against the E15 output, the only differences are the first line ("addenda A1 to A4") and five new lines (missed-exit costs, gap fills, P4 breach time and run end, exit classes, B̄ under `/pause`). **Mutation check, 31 mutants, all fail the self-test:** the 16 E15 mutants, recreated (M1-M16), and 15 new ones: M17 costs netted per trade (no increments), M18 every increment measured against actual R, M19 uncomputable mirror costs nothing, M20 gap fill at the candle open (the spec's A20 a default), M21 gap half-spreads swapped, M22 1h candle preferred over 1m, M23 4th missed exit by ledgering order, M24 cost breach time not capped at `T_eval`, M25 ABORTED wins a tie with the breach, M26 settled-gap lag measured from the gap start, M27 data-gap exit settled without the lag check, M28 on-time boundary exclusive at 60 s, M29 B̄ by plain exclusion of paused starts (A3.2 b), M30 B̄ min instead of max, M31 SL/TP gap fill ignores gap-through. The harness was a throwaway script outside the repository. | no |

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
| C2 | Peeking | **Resolved [PO]:** one evaluation of the first 300 opened; **(A3.2)** descriptive interim statistics only (`/stats`), never the gate statistics (5.5); at most 2 runs with an α split (5.4), which holds for any data-dependent abort. |
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
| C14 (round 2) | The precision choices in section 14 were never signed by the PO. Together they roughly halve power: at +0.10R with merged positions, run 1 is 20% against 41% for a naive 95% t, and run 2 is about 9% (no beta) and 3-6% (with beta) before P2c **(A2.5; v2 + A1 said 13-24%, the iid figure)**. A2.4 adds three items (6-8). | **(A3.7) Acknowledged by the PO on 2026-09-29** (section 14, items 1-8; `decisions.md`) |
| C15 (A3) | A run can now PASS with up to 3 missed exits. Each counts at its worse outcome, but the bug behind it may have changed things the mirror doesn't correct. | Every missed exit blocks go-live until explained and fixed (ME, 5.6). **(A4.9)** Acknowledged on its A3 wording on 2026-09-29; reworded by A4; **pending PO re-acknowledgement** (section 14, item 9) |
| C16 (A3) | `/stats` shows win rate, average R and per-trader figures during a run. It can't create a pass by luck, but it can prompt aborts on noise and targeted pauses. | Stated in 5.5 (A3.2, A4.6, A4.11). **(A4.9)** Acknowledged on its A3 wording on 2026-09-29; reworded by A4; **pending PO re-acknowledgement** (section 14, item 10) |

## 14. Items for PO acknowledgement (BT2-5; A2.4, A2.5; A3.7)

Q1-Q9 are answered and encoded in 5.2. The items below are research choices, or plain consequences of the rules, that interpret or tighten your decisions. (A2.4: v2 + A1 listed five; items 6-8 and the closing note are new, and every item is reworded in plain language.) **(A3.7)** You acknowledged items 1-8 and the closing note on 2026-09-29 (`decisions.md`). Items 9 and 10 are new in A3: they spell out what your spec-review decisions A4 (missed exits) and A14 (`/stats`) mean for the verdict, and what they cost. **(A4.9)** You said "ok" to items 9 and 10 on 2026-09-29. The audit that followed (round 4) found that their wording overstated one guarantee and left out some consequences, and A4 tightened some of the rules behind them. They are rewritten below and need your acknowledgement again. The "PO-ACK pending" labels on items 1-5 in 5.3, 6.2 and 9.2 are left as they were, as a record of where each item came from; read them as acknowledged.

- **Status (A3.7, A4.9):** items 1-8 acknowledged on 2026-09-29. Items 9 and 10 were acknowledged on their A3 wording on 2026-09-29 and rewritten by A4: **pending PO re-acknowledgement**.
- **Who records the answer:** the CTO, in `docs/product/decisions.md`.
- **Where your "95%" comes from (A2.5):** the brief, `01-brief.md` lines 27 and 127. D11 in `decisions.md` says "CI lower bound > 0" and gives no level.
- **Precondition:** run 1 must not start until all ten are acknowledged or replaced (8.1).
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
- **Status:** acknowledged on 2026-09-29 (`decisions.md`; A3.7).

**2. Use the most cautious of three ways to measure the uncertainty.**
- **What it means:** The verdict looks at the average R per trade and at how uncertain that average is. There are three standard ways to measure the uncertainty:
  - one treats every trade as independent
  - one reshuffles whole trading days
  - one groups trades by day

  Each can be too optimistic in some situations. For example, reshuffling days is too optimistic when the trades fall on only a few days. We always use the most cautious of the three.
- **The price:** it keeps the chance of passing by luck at or below target, and costs some ability to detect a real edge.
- **Replaces or interprets:** your "confidence interval clustered by UTC day", which didn't say which method.
- **If you say no:** we would use one method. With trades on only 5 days, the day-reshuffling method alone lets a no-edge strategy pass about 6.4 times in 100, instead of about 1.
- **Status:** acknowledged on 2026-09-29 (`decisions.md`; A3.7).

**3. The 300 trades must fall on at least 5 different days.**
- **What it means:** Trades opened on the same day tend to win or lose together, because they ride the same market. If the 300 trades fall on fewer than 5 different calendar days (UTC), the uncertainty can't be measured reliably. The verdict is then INCONCLUSIVE: never a pass, and never a fail on the numbers. The run can still fail on the 15% drawdown limit or **(A3.1)** the missed-exit rule in item 9.
- **Replaces or interprets:** nothing; your decisions didn't cover this case.
- **If you say no:** no minimum. With 2 to 4 days, a pass or a fail would rest on a measurement that is unreliable in both directions.
- **Status:** acknowledged on 2026-09-29 (`decisions.md`; A3.7).

**4. Judge the run no later than 7 days after the 300th trade opens.**
- **What it means:** You decided the run is judged once, after all 300 trades have closed. We propose to judge it when the last of the 300 closes, or 7 days after the 300th trade opened, whichever comes first.
  - A trade still open at that moment is valued at the market price minus the exit fee and half the spread, as if it had closed then.
  - The bot keeps managing it normally. Its real result is reported separately and never changes the verdict.
- **Why:** without a cap, one long-held position could delay the verdict without limit.
- **Replaces or interprets:** your "evaluated once, after all have closed".
- **If you say no:** no cap. The verdict waits for the last close, however long that takes.
- **Status:** acknowledged on 2026-09-29 (`decisions.md`; A3.7).

**5. "Beating the baseline" means clearly beating it, not just on average.**
- **What it means:** You asked that our trades beat a baseline that trades the same coins in the same direction, but at random times. The baseline separates skill at picking the moment from simply riding the market: in a rising month, buying at random times also makes money.
  - We read "beating" strictly: we must be confident (96% in run 1, 99% in run 2) that our advantage per trade over the baseline is above zero.
  - Beating the baseline's average is not enough, because a bot that only rides the market does that about half the time by luck.
- **The effect:** with the strict reading, a bot that only rides the market passed the full test at most about 1 time in 200 in our simulations. The baseline pays the same fees and spreads as we do, but not the cost of our copy delay. So if our delay eats our advantage, this test fails, as it should.
- **Replaces or interprets:** your "beat a direction-matched, random-time baseline".
- **If you say no:** a simple comparison of averages. A bot that only rides the market passes this check about half the time.
- **Status:** acknowledged on 2026-09-29 (`decisions.md`; A3.7).

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
- **Status:** acknowledged on 2026-09-29 (`decisions.md`; A3.7).

**7. A manual `/flatten` can only count against the result.** (New, A2.4; A2.1.)
- **What it means:** `/flatten` closes positions. It is a safety action and is always allowed. For the verdict, each trade closed this way counts at the worse of two results:
  - what it actually made
  - what it would have made if the bot had kept managing it (the "shadow" result, simulated on recorded market data)

  The run is also judged as if those trades had stayed open until their shadow closed, so a flatten never ends or shortens the run. Manual action can protect your money, but it can never improve the verdict.
- **Replaces or interprets:** nothing you decided; it follows from your "safety actions are always allowed".
- **If you say no:** a flattened trade would count at its actual result. You could then close trades while they happen to be in profit, or end the run at a moment of your choosing. The verdict would partly measure your decisions, not the bot's, and the 2.5% limit on passing by luck would no longer hold.
- **Status:** acknowledged on 2026-09-29 (`decisions.md`; A3.7).

**8. Gaps in our market recordings can make the run INCONCLUSIVE.** (New, A2.4; A2.3.)
- **What it means:** The baseline test in item 5 needs our own recordings of the order book and prices for each trade's coin. If a trade's recordings have too many gaps to build its baseline, that trade can only count against us: at most zero, and lower if a partial baseline shows the market was carrying it.
  - If more than 10% of the 300 trades (more than 30) lack a proper baseline, the baseline test fails. The verdict is then INCONCLUSIVE even if the bot made money, and the run still counts as one of your 2.
  - Before run 1 we report how often the recorder had gaps during the 24-hour dry run and the first week of recording, so you can judge this risk. If the gaps come near the 10% line, the recorder gets fixed before run 1.
- **Replaces or interprets:** your "market data recorded from day 1" and "beat a direction-matched baseline".
- **If you say no:** trades without a proper baseline would simply be dropped. The gaps tend to hit long trades that ride the market, which are exactly the trades this test is meant to catch. A bot that only rides the market would then pass more often than the 1 in 200 stated in item 5.
- **Status:** acknowledged on 2026-09-29 (`decisions.md`; A3.7).

**9. A missed exit counts at its worse result; more than 3, or one that cost more than 1R, fails the run.** (New, A3.1; your spec-review decision A4. **Rewritten by A4.9.**)
- **What it means:** A missed exit is when a trader we copy closes or cuts a position and the bot doesn't follow within 60 seconds, or can't settle it after a restart. 1R is what one trade plans to risk: 0.5% of the wallet, about $1.50 on $300.
  - **The worse result counts.** For the verdict, that trade counts at the worse of two results: what it actually made, and what it would have made if the bot had followed on time. The second is simulated on our recorded market data, the same way as for `/flatten` (item 7). So a missed exit never makes its trade count better than it actually did. For a trade you closed with `/flatten`, "what it actually made" is what the flatten realised.
  - **When the run fails.** The run fails if there are more than 3 missed exits. It also fails if a single missed exit, or all the missed exits of one trade together, cost more than 1R (about $1.50) compared with following on time. Two missed exits on one trade can't cancel each other out: a 1.3R loss on the first fails the run even if the second gained 0.5R. We count every trade in the run window, including trades opened after the 300th, and missed exits that happen while new entries are paused.
  - **Gaps in our recordings count against us.** Where our recordings have a gap, the simulation uses the exchange's one-minute price bars (or one-hour bars if those are missing). It takes the price inside the bar that makes the missed exit look more expensive when we check the 1R limit, and the price that makes the trade look worse when it counts toward the average. If even the exchange's price bars can't be obtained within 72 hours, the missed exit counts as costing more than 1R, and the run fails.
  - **We check against the exchange's own records.** Once a day, and again before the verdict, the bot compares every exit our traders made, taken from the exchange's fill history, with what the bot did. Any exit it didn't follow within 60 seconds counts, including one it never noticed. A missed exit found this way after the end of the run still fails the run if it happened during the run. If the check can't be completed within 72 hours because the exchange won't provide the data, the run fails too, because we can't show there was no costly miss.
  - **Short outages of our data feed.** If our feed drops out and the bot follows a trader's exit within 60 seconds of reconnecting, that isn't a missed exit. The trade still counts at the worse of its actual result and the on-time result.
  - **A failed run is used up.** A fail on missed exits ends the run at once (the bot pauses) and uses up one of your 2 runs, even though it says nothing about whether the strategy works. Before run 2, every missed exit must be explained and fixed.
  - **Going live.** Every missed exit blocks going live until its cause is written down and fixed with a test that reproduces it. Your review alone can't clear it.
  - **What the rule can't promise.** It stops a missed exit from making its own trade look better. It can't undo other effects of the same bug that we can't see, such as a changed entry or size. An exit the bot follows within the 60 seconds counts as it actually happened, which may be slightly luckier or unluckier than on time. That is why every missed exit also blocks going live until fixed.
- **Fixing it during a run:** A fix is a code change during the run (item 6). A fix to how the bot follows exits normally ends the run as ABORTED and uses up one of your 2 runs. Until the auditor rules, the old code keeps running, bug included, and pausing new entries while you wait counts as downtime. Usually the better choice is to let the run finish on the old code and fix the bug afterwards, before run 2 or any live step. The kill switch and `/flatten` always work.
- **The price:** a run with a harmless glitch is no longer thrown away. In exchange, a run can now pass even though the bot had up to 3 exit bugs. Those bugs can't make their own trades count better, but they may have affected things we can't see. That is why each one blocks going live until it is explained and fixed.
- **Replaces or interprets:** your decision A4, and the old rule "any missed exit fails the run at once".
- **If you say no:**
  - to counting at the worse result: a bug that happened to hold a winning trade longer would improve the verdict.
  - to the daily check against the exchange's records: if the bot's feed of trader fills silently died, it could miss many exits without any of them being counted.
  - to judging each missed exit on its own: two missed exits on one trade could hide a 1.3R loss behind a 0.5R gain.
  - to counting trades after the 300th and missed exits during paused entries: some exit bugs would go uncounted, and the 3-bug limit would allow more real bugs.
  - to the whole item: we return to the old rule, where a single missed exit fails the run at once.
- **Status:** acknowledged on its A3 wording on 2026-09-29; rewritten by A4; **pending PO re-acknowledgement**.

**10. `/stats` shows how the run is going, never how the verdict is going.** (New, A3.2; your spec-review decision A14. **Rewritten by A4.9.**)
- **What it means:** During a run, `/stats` shows your P&L in dollars, win rate, average R, drawdown, the same figures per trader, and progress toward 300 trades. It also shows downtime used, missed exits and pending code rulings. The bot never computes or shows these before the end: the confidence interval the verdict uses, the baseline test, the fragility checks, or anything like "on track to pass". No other results-based figure is shown either, such as results per coin or per week. Operational information stays: `/status` (health, disk, archive), `/traders` (who is followed, with score and rank), trade posts, and the counts in the daily reports.
- **`/stats` shows actual results; the verdict can count some trades lower.** `/stats` shows what each trade actually made. The verdict counts some trades at the worse of their actual and simulated results: a trade closed with `/flatten`, a trade with a missed exit, or one whose exit came right after a data outage. So the verdict's figures can be lower than what `/stats` shows, never higher.
- **Why this is safe:** Seeing the numbers can tempt you to stop a run that looks bad, or to change settings. Neither can produce a pass by luck: a stopped or changed run ends as ABORTED, which is never a pass, and it still counts as one of your 2 runs. So the limit in item 1 (at most 2.5% chance of passing by luck across both runs) holds whatever you decide after seeing the numbers. The round-2 audit made this argument.
- **What remains, plainly:**
  - **Early numbers are mostly noise.** After 50 trades the average R can easily be 0.3R (about 45 cents per trade) off the truth, three times the edge we are looking for. Stopping a run because it looks bad uses it up, and run 2 is much harder to pass: a real +0.10R edge passes it only about 3 to 9 times in 100.
  - **`/pause` changes which trades are counted.** Pausing through a stretch that looks bad lets later trades take those places among the first 300. The 2% downtime limit caps this at about 14 hours in 30 days. Our rough estimate of the most this could move the average, even if you could see every bad stretch coming, is 0.02R. Small, but not zero.
  - **`/pause` and the baseline test.** The earlier wording said the baseline simply skips your paused hours. That cut both ways: skipping hours that were good for our trades' direction made the baseline look worse, and our advantage over it better, by about 0.02 to 0.04R per trade affected. Now, for your pauses, the baseline uses whichever result is higher: with the paused hours or without them. A pause can therefore only make the baseline test harder, never easier.
  - **Hiding the confidence interval is a guard against habit, not a lock.** You could estimate it roughly from the trades you see. What protects the verdict is that it is computed once at the end, that stopping early never passes, and that every run counts.
  - **A code change prompted by the numbers ends the run.** If the stated reason for a mid-run code change is what `/stats` shows, rather than a bug, the auditor rules the run ABORTED.
- **Replaces or interprets:** your decision A14, and the earlier rule "no interim statistics".
- **If you say no:**
  - to the limits (you want the interval or a preview shown): that needs a new addendum. It wouldn't by itself create passes by luck, but it would make stopping or pausing on noise much more tempting, which wastes runs.
  - to showing more: we return to the earlier rule, where you see trades, positions and dollar P&L only. The protection against passing by luck is the same either way.
  - to the baseline rule for pauses: pausing through a good stretch could make our advantage over the baseline look slightly larger than it is.
- **Status:** acknowledged on its A3 wording on 2026-09-29; rewritten by A4; **pending PO re-acknowledgement**.

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

**Addendum A3 (5.12)** closes no audit finding. It encodes the PO's spec-review decisions A4 and A14, and it amends part of the BT-5 closure above: descriptive interim statistics are now shown, while the gate statistics still are not (5.5, A3.2). **(A4)** A3 was audited in round 4 (`backtest-audit-r4.md`, VALID).

**Round 4 (`backtest-audit-r4.md`, VALID), closed by Addendum A4 (5.13):**

| Finding | Severity | Closed by |
|---|---|---|
| BT4-1 | ADVISORY (before run 1) | A4.1. Daily and final leader-fill audits of `userFillsByTime` against the ledger for every leader with a share open in the window; an unhandled exit event becomes an orphan missed exit before P4 and gate R; reconciliation checks fills and sizes, not only the sign; an audit incomplete after 72 h is a P4 breach; "handled" defined (5.3, 9.2; tests 25, 29; E16 `exit_class`). Item 9 corrected (A4.9). |
| BT4-2 | ADVISORY (before run 1) | A4.2. Without a recorded book, mirror fills use the 1m candle, else the 1h candle: lo = worst price + 8 bps, hi = best price + 2 bps; SL/TP gap fills at the trigger or a gapped-through open; no candle within 72 h = uncomputable (> 1R, lo = actual); an hourly, hashed candle store (5.3, 6.2, 9.2; test 26; E16 `gap_candle`, `gap_fill_px`, `gap_trigger_px`). |
| BT4-3 | ADVISORY | A4.3. Incremental cost per missed exit over mirrors M_1..M_k, plus the trade cost; both tested against 1R; actual R = realised R (5.3, 9.2; test 27; E16 `missed_exit_costs`). |
| BT4-4 | ADVISORY | A4.4. Any P4 breach with leader events in the window is F2, whenever found; breach time = the 4th's leader event time, or when the cost is established (capped at `T_eval`); ABORTED wins only when strictly earlier (5.3 P4, F2, precedence item 2, missed-exit rules, 9.2; test 28; E16 `p4_breach_time`, `run_end`). |
| BT4-5 | ADVISORY (before run 1) | A4.5. An exit inside a data gap handled within 60 s of resync is settled: not a missed exit, gate R = min(actual, mirrored lo); otherwise class 2 (5.3, 9.2; test 29; E16 `exit_class`). |
| BT4-6 | ADVISORY (before run 1) | A4.6. For discretionary pauses, B̄_i = max(including, excluding the paused starts), from the same draws; plain exclusion for non-discretionary downtime; the two-sided effect disclosed (5.5, 5.12, 6.2, 9.2; test 22; E16 `b_bar_discretionary`). Item 10 corrected (A4.9). |
| BT4-7 | ADVISORY | A4.7. Untiered coins use the major fallback in every baseline and comparator (B0d, B0, B0b, B1, B3); tier rule and thresholds frozen, assignments recomputed every 24 h and ledgered (6.3, 9.2; test 23). |
| BT4-8 | ADVISORY | A4.8. Stream and transport sha256 per file; hash-chained segment records every 5 minutes; unhashed data is a gap; verdict values recomputed from verified data; the storage destination moved out of the config hash with the argument stated, retention kept in it (5.12, 6.2, 9.2; test 24). |
| BT4-9 | ADVISORY (re-ack needed) | A4.9. Items 9 and 10 rewritten, correcting (a)-(f); marked pending PO re-acknowledgement (header, 8.1, 13, 14). |
| BT4-10 | ADVISORY | A4.10. "Never raises a trade's R or USD; D_i and LB_r are affected only negligibly" (5.3 missed-exit rules, 5.12). |

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
