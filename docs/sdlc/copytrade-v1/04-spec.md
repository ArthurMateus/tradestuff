# Spec: copytrade-v1 (AI-filtered copy-trading bot, Hyperliquid + Telegram, paper)

Author: pm (SPEC mode) · Date: 2026-09-29 · Status: draft for /tests, Amendment 1 applied

## Amendment 1 (2026-09-29)

**Source.** The six "Spec review" decisions dated 2026-09-29 in `docs/product/decisions.md`: A2 (leverage), A4 (missed exits), A6 (coin tiers), A9 (news source), A10 (storage) and A14 (`/stats`). The same entries accept every other §11 assumption as a default, and §11 records that.

**Dependency on edge-hypothesis A3.** The quant-researcher is writing the pre-registration Addendum A3 in `research/edge-hypothesis.md` in parallel. A3 is **normative** for the missed-exit rule (gate R, USD P&L and the FAIL thresholds) and for what may be shown during a run. Where this spec paraphrases A3, A3 wins. Until A3 is committed, these ACs are provisional, and /tests takes their exact vectors from A3: F12.AC6, F12.AC9, F14.AC6, F14.AC9, F18.AC7 and F18.AC11.

**Changed ACs** (the old text is replaced in place):

| AC | Change | Decision |
|---|---|---|
| F1.AC2 | Required ceiling cases now cover the new leverage keys, the high-leverage coin list and the liquidation-multiple floor | A2 |
| F1.AC5 | Storage credentials and the backup encryption key join the env-only secrets and the canary test | A10 |
| F1.AC7 | The manifest also never lists `storage.cache_dir` | A10 |
| F4.AC1 | The recording universe always includes SOL | A2, A6 |
| F4.AC2 | Leaderboard snapshots are never deleted **from the archive**; local copies are pruned like recordings | A10 |
| F4.AC5 | Disk guard: alert threshold, then a hard floor that stops recording safely; exits are never blocked | A10 |
| F4.AC6 | Recording continues in every trading state, except below the disk floor | A10 |
| F9.AC1 | Slippage and spread thresholds apply by liquidity tier, not by a majors list | A6 |
| F10.AC4 | Leverage is the lowest value that fits the margin, up to the ceilings (5x alts; 10x BTC, ETH and SOL), subject to the liquidation-distance rule | A2 |
| F12.AC6 | A missed exit alerts with a running count and is a go-live blocker; it no longer fails the run by itself | A4 |
| F14.AC4 | `/stats` is added to the command table; `/status` shows free disk, archive state and projected storage cost | A14, A10 |
| F14.AC6 | The visibility lock now allows the `/stats` figures and forbids the gate CI, P2c, FR checks and any verdict preview | A14 |
| F14.AC7 | Daily and weekly reports add missed exits, coin-tier changes, archive state and projected storage cost | A4, A6, A10 |
| F17.AC1 | The run record stores the frozen coin-tier table and its sha256 | A6 |
| F17.AC2 | `run start` also refuses on a missing or stale tier table, or an unhealthy archive | A6, A10 |
| F17.AC4 | A tier table differing from the run record is treated as a config change | A6 |
| F18.AC6 | The F2 input to the precedence grid is now the output of F18.AC11 | A4 |
| F18.AC7 | Immediate FAIL by F2 follows the A3 thresholds, not "any missed exit" | A4 |
| F18.AC10 | The API also refuses D, B0d, P2c, FR and per-condition results before `T_eval`; `/stats` never uses it | A14 |
| F20.AC1 | The report lists every missed exit with its actual, mirrored and gate R and its cost | A4 |
| F20.AC4 | Any missed exit also blocks a PASS from going live | A4 |
| F20.AC5 | The readiness report adds the tier table and archive health | A6, A10 |
| F21.AC2 | The 24h dry run also checks compressed recording size and one verified archive day | A10 |

**Added ACs:**

| AC | Content | Decision |
|---|---|---|
| F4.AC7 | Compressed, day-partitioned, atomically written recordings | A10 |
| F9.AC7 | Coin tiers assigned automatically from measured liquidity | A6 |
| F9.AC8 | Tier recompute schedule, freeze at run start, meme-perp fixtures | A6 |
| F10.AC10 | Property tests for automatic leverage | A2 |
| F12.AC9 | Mirrored counterfactual and cost of each missed exit | A4 |
| F14.AC9 | `/stats` content and labelling | A14 |
| F18.AC11 | Missed-exit rule: count and cost thresholds, gate R | A4 |
| F23.AC1–AC7 | **New feature F23**: archive, cloud offload, pruning, transparent reads, ledger backup, credentials, budget | A10 |

**Other sections changed:** §1 (definitions of tiers and the missed-exit rule, outcomes), §3 (new, renamed and removed keys), §4 (storage and cost budgets), §5 (disk, archive, missed-exit, tier and leverage rows), §7 (mappings), §8 (J7 Tracker), §9 (DoD items 1, 5, 7, 11 and new 13), §10 (F23 wave and ownership, tier and leverage ownership), §11 (A2, A4, A6, A9, A10, A14 rewritten; A17–A23 added; acceptance status recorded).

**Config keys removed or renamed:** `markets.majors` (removed; tiers replace it), `risk.leverage_default` (removed; replaced by `risk.leverage_min`), `risk.max_leverage_btc_eth` → `risk.max_leverage_high_tier`, `filter.max_slippage_pct_major`/`_alt` → `_tier1`/`_tier2`, `filter.max_spread_pct_major`/`_alt` → `_tier1`/`_tier2`, `recording.disk_pause_free_gb` → `recording.disk_floor_free_gb`.

**Config keys added:**
- **Leverage (§3.6):** `risk.leverage_min`, `risk.max_leverage_high_tier`, `risk.high_leverage_coins`. The floor of `risk.min_liq_distance_stop_mult` is raised from 2 to 3.
- **Tiers (§3.5):** `tiers.lookback_days`, `tiers.recompute_interval_h`, `tiers.max_age_h`, `tiers.depth_band_pct`, `tiers.tier1_min_depth_usd`, `tiers.tier1_min_volume_usd`, `tiers.floor_min_depth_usd`, `tiers.floor_min_volume_usd`, `tiers.min_coverage_fraction`, and the renamed `filter.max_slippage_pct_tier1/2` and `filter.max_spread_pct_tier1/2`.
- **Recorder (§3.3):** `recording.disk_check_interval_s`, `recording.disk_floor_free_gb`, `recording.disk_resume_margin_gb`, `recording.max_gb_per_day`.
- **Storage (§3.1):** `storage.cache_dir`, `storage.upload_delay_min`, `storage.upload_deadline_h`, `storage.local_retention_days`, `storage.max_unarchived_days`, `storage.cache_max_gb`, `storage.read_retry_max_min`, `storage.retry_interval_min`, `storage.alert_interval_h`, `storage.ledger_backup_time_utc`, `storage.monthly_budget_usd`, `storage.budget_alert_fraction`, `storage.price_usd_per_gb_month`, `storage.price_usd_per_10k_ops`.
- **Evaluation (§3.9, FROZEN via edge-hypothesis A3):** `eval.missed_exit_max_count` (3), `eval.missed_exit_max_cost_r` (1.0). The meaning of `eval.show_interim_stats` is narrowed to gate statistics.
- **New config flag:** VAL-R, meaning "validate against our recordings before freezing".

**Feature count:** 23 (F1–F23).

---

**Inputs.**
- `01-brief.md`, `02-discovery.md` and `03-answers.md`.
- `research/edge-hypothesis.md` (frozen v2 + A1 + A2; A3 in preparation, see Amendment 1).
- `research/backtest-audit-r3.md` (VALID), `research/run-register.md`, `research/market-context.md` and `research/brainstorm-domain-research.md`.
- `docs/product/decisions.md` and `.claude/knowledge/trading-invariants.md`.

**Precedence.**
- Where `01-brief.md` conflicts with a later decision in `decisions.md`, the later decision wins:
  - risk per trade is 0.5%, not 1%
  - we follow at most 9 wallets, not 5–10 with a maximum of 10
  - the CI level is 96% for run 1 and 99% for run 2, not 95%
  - leverage is chosen automatically up to 5x alts and 10x BTC, ETH and SOL (Spec review A2), not a 3x default with a BTC/ETH-only 10x tier (D3)
  - liquid Hyperliquid meme perps are tradable when they qualify by liquidity tier (Spec review A6); D4's deferral now covers on-chain memecoins only
- `edge-hypothesis.md` §5 (the frozen pre-registration) and its addenda, including A3, are **normative** for everything under evaluation. Where this spec paraphrases it, the frozen text wins.
- `research/scripts/eval_reference.py` (E14) is the **conformance oracle**. If it disagrees with the frozen text, the frozen text wins and the oracle is a bug.

**Notation.**
- ACs are written `Fn.ACm [tag]`. The tag is one of `unit`, `integration`, `qa-ui` or `simulation`. `simulation` means the AC is run in paper mode or replay against recorded data.
- "Equity" is marked-to-market paper equity in USD.
- "Share" means one trader share, as defined in §1.
- All times are UTC epoch milliseconds, unless a time zone is named.

---

## 1. Problem and goals

**Problem.** Naive copy trading loses money:
- leaders are often lucky
- copy delay, fees and spread eat the edge
- leverage liquidates followers
- leaderboards reward survivorship

The PO wants to know, **honestly and cheaply**, whether automatically copying evidence-selected Hyperliquid traders is profitable after real costs. The PO wants this known before any real money or subscriber is involved.

**What the PO wants (intent):**
1. A bot that finds and keeps re-checking a small set (at most 9) of Hyperliquid wallets with evidence of real, copyable skill. It swaps in better ones as they appear.
2. The bot copies those wallets' moves automatically into a **$300 paper wallet at real mainnet prices**. It mirrors opens, adds, partial exits and full exits, with deterministic filters and hard risk caps that always win.
3. It reports every trade in a private Telegram chat, and the PO keeps full control through a small set of authenticated commands.
4. After a paper run judged once on its first 300 opened trades, it gives a verdict computed exactly as pre-registered: `PASS`, `FAIL`, `INCONCLUSIVE` or `ABORTED`. That verdict must be one the PO can trust not to be fooled by luck, beta, costs, survivorship or optional stopping.

**User-visible outcomes:**
- From day 1, the PO's PC records the market data and leaderboard snapshots needed for honest, point-in-time replays. Recordings are compressed, each finished UTC day is archived to cheap object storage and verified, and only a rolling window stays on the PC's ~100 GB of free disk. Storage costs ≤ $5/month.
- The full pipeline runs unattended on the PO's Windows PC in paper mode. It survives restarts without leaving a position open, and without faking results.
- During a run the PO sees trades, positions and USD P&L, and `/stats` shows descriptive figures: P&L, win rate, average R, drawdown, per-trader stats and progress to 300. The PO never sees the gate CI, P2c, FR checks or any verdict preview before `T_eval` (edge-hypothesis §5.5 as amended by A3).
- At `T_eval` a report states the verdict, every gate value and every go-live blocker.
- The epic's deliverable is a **run-1-ready system** (see §9). The paper run itself, and its verdict, happen after this epic ships and are tracked in the run register.

**Definitions** (binding for every AC):
- **Trade / share:** one copied position per leader, from our entry fill to fully closed, including adds and partials. Only taken signals count.
- **Merged position:** every open share on one coin in one direction.
- **R:** `net_pnl_usd / initial_risk_usd`, where `initial_risk_usd = qty_at_entry × |entry_fill_px − initial_stop_px| + estimated exit fee` (edge-hypothesis §4).
- **Liquidity tier:** each allowed core coin is assigned automatically, from measured liquidity in our own recordings (F9.AC7), to **tier 1** (most liquid), **tier 2**, or **below floor** (not tradable). There is no hand-written coin list for tiers. The tier table in force at run start is frozen for the run (F9.AC8). "Majors" and "alts" in earlier text and in edge-hypothesis §6.3 are read as tier 1 and tier 2 (Assumption A17).
- **High-leverage coins:** the coins in `risk.high_leverage_coins` (BTC, ETH and SOL), which may use up to 10x. This list is about leverage only and is independent of the liquidity tiers.
- **Missed exit:** a leader exit event (a close, a reduce or a flip) on a coin where we hold that leader's open share, which meets any of the following:
  1. **Late:** the event's exchange timestamp is outside recorded downtime, and no mirroring ledger action exists within `exits.missed_exit_max_lag_s` of it.
  2. **Reconstruction failed:** the event is inside recorded downtime, and the restart reconstruction (F13) did not settle it.
  3. **Orphan:** it is discovered only by reconciliation (F12.AC5) more than `exits.missed_exit_max_lag_s` after its exchange timestamp, outside downtime.

  Rule-based non-mirrors are not missed exits: a partial skipped below $10, or a share already closed by our own SL/TP (Assumption A4).
- **Missed-exit rule** (edge-hypothesis A3 is normative; this is a paraphrase):
  - A missed exit counts in the gate at **min(actual, mirrored) R**, where "mirrored" is the share's outcome had the leader event been mirrored on time (F12.AC9). A bug can therefore never help the verdict.
  - A missed exit does not by itself fail the run. The run FAILs (F2) only if the missed exits in the evaluation window **exceed 3**, or if **any single one cost more than 1R** versus mirroring (F18.AC11).
  - Every missed exit alerts at once (F12.AC6) and is a **go-live blocker** until it is explained and fixed (F20.AC4), whatever the verdict.

---

## 2. Features and acceptance criteria

### F1 Platform core (config, ceilings, mode, money, secrets, clock, engine path set)
- **Value:** every other feature gets validated configuration, paper-only operation, exact money arithmetic and secret hygiene. Without it, nothing else is safe to build.
- **Dependencies:** none. F1 also scaffolds the project, the lockfile and the package layout used by the §10 ownership map.

- **F1.AC1 [unit]**
  - *Given* a config tree under `config/` where any key in §3 is missing, has the wrong type, or has a value outside [Min, Max],
  - *when* the engine starts,
  - *then* it exits non-zero with an error naming the key, and it opens no network connection.
  - The engine has **no code defaults**: every §3 key must be present in the config files.
- **F1.AC2 [unit]** Hard ceilings are constants in code and can't be raised by config.
  - *Given* each §3 key with a Max: a value equal to Max loads, and a value one step above it is rejected.
  - Required cases: `risk.per_trade_fraction` = 0.0101, `risk.max_leverage_alt` = 6, `risk.max_leverage_high_tier` = 11, `select.max_followed` = 10, `filter.max_signal_age_ms` = 5001 are each rejected.
  - `risk.high_leverage_coins` accepts any subset of {BTC, ETH, SOL}, and a list containing any other coin (for example DOGE) is rejected.
  - Floors work the same way: `cost.taker_fee_bps` = 4.4, `risk.min_liq_distance_stop_mult` = 2.9, `recording.disk_floor_free_gb` = 4 and `tiers.floor_min_depth_usd` = 19,999 are each rejected.
- **F1.AC3 [integration]** Paper only.
  - *Given* no `mode` key value other than `paper`: `mode` = `live` or `testnet` makes startup fail with `mode not permitted in this build`.
  - *Given* any test run, with a network stub that fails the test on any request to the Hyperliquid `/exchange` endpoint: 0 such requests are made.
  - No module imports an order-signing client, which a static test checks.
- **F1.AC4 [unit]** Money is Decimal.
  - Constructing a price, quantity, notional, fee, funding or P&L value from a binary float raises.
  - Price rounding follows the exchange rule: ≤ 5 significant figures, ≤ (6 − `szDecimals`) decimals, and integers are always allowed.
  - Size rounds **down** to `szDecimals`.
  - Vectors: (67123.45, sz 5) → 67123; (0.01234567, sz 0) → 0.012346; size 0.123456 at sz 3 → 0.123.
- **F1.AC5 [unit]** Secrets come only from environment variables: the Telegram token, the PIN hash and salt, the LLM key, the object-storage endpoint, bucket, key ID and secret key, and the ledger-backup encryption key.
  - *Given* canary secret values injected for the whole test suite: 0 occurrences appear in logs, ledger records, Telegram payloads, LLM prompts or exception traces.
  - A config file that contains a key matching `(?i)(token|secret|api_key|pin)` with a non-empty value fails to load.
- **F1.AC6 [unit]** Every timestamp is UTC epoch ms and carries a source tag: `exchange`, `local` or `derived`.
  - The clock offset is re-estimated every `clock.offset_interval_s`.
  - *Given* offset uncertainty above `clock.max_offset_uncertainty_ms`, or no estimate for more than `clock.max_estimate_age_s`, *then*:
    - opens and adds are refused with reason `clock_unsynced` within 1 s
    - one alert is sent
    - exits continue
- **F1.AC7 [integration]** The engine path set.
  - The committed manifest `engine-path-set.txt` lists: `src/copytrade/**`, the lockfile, the project metadata file, `config/**`, `data/inputs/**` and itself.
  - It never lists `docs/**`, `research/**`, `tests/**`, `storage.ledger_dir`, `storage.recordings_dir` or `storage.cache_dir`. A test enforces this.
  - At startup, the engine fails closed and names the file if any imported engine module, or any file opened as config or data input, is outside the manifest.

### F2 Append-only ledger and audit trail
- **Value:** a single, tamper-evident source for every decision, fill, run record and statistic. It gives honest numbers (B5, D4) and tax export (E5).
- **Dependencies:** F1.

- **F2.AC1 [unit]** Tamper evidence.
  - Records carry a strictly increasing sequence number and a hash chain, `h_n = sha256(h_{n−1} ‖ canonical_bytes(record_n))`.
  - The API offers no update or delete.
  - *Given* any single byte of a stored record is altered, *when* the ledger is verified (at startup and via CLI), *then*:
    - verification fails at that sequence number
    - the engine refuses to start
    - an alert is written to the local log
- **F2.AC2 [unit]** One decision record per signal (B5). It holds:
  - the signal id, leader, coin, event type
  - the exchange timestamp, local receive timestamp and clock offset
  - each filter rule's input value, threshold and result, and each risk check's result
  - the mirror, risk-cap and final sizes, and the price used
  - the latency per stage (§4)
  - the outcome: `taken`, `rejected:<reason>`, `unexecutable`, `conflict`, `duplicate`, `out_of_scope` or `pre_existing`

  A fixture of 50 signals yields exactly 50 decision records, with no required field null.
- **F2.AC3 [integration]** Crash durability.
  - *Given* the process is force-killed at 100 random points during a replay of 1,000 signals, *when* it restarts, *then*:
    - the ledger verifies
    - there are 0 partial records
    - each client order ID appears at most once
- **F2.AC4 [unit]** Fill export.
  - `export fills --from --to` writes CSV with one row per paper fill: ISO-8601 UTC time, coin, side, qty, price, fee, funding, client order ID, trade ID, share ID and exit reason.
  - The row count equals the number of fill records, and Decimal strings round-trip exactly.
- **F2.AC5 [unit]** Honest aggregates. No aggregate API has a parameter that excludes records by outcome or flag.
  - *Given* a fixture that includes losers and trades flagged `reconstructed`, `unreconstructable`, `delisted_force_settle`, `liquidated`, `marked` and `manual_flatten`, *then* the aggregate USD P&L and trade count equal the hand-computed totals over all of them.
- **F2.AC6 [unit]** A ledger append that fails (I/O error, disk full) raises to the caller. The engine then enters the fail-closed state in §5 and never continues silently.

### F3 Hyperliquid client (REST, WebSocket, rate budget, access detection)
- **Value:** reliable, rate-safe access to public Hyperliquid data, with gap detection. This is the basis for every signal and every price.
- **Dependencies:** F1 and F2.

- **F3.AC1 [unit]** Rate budget.
  - Weights: 20 per info request; 2 for `l2Book`, `allMids` and `clearinghouseState`; +1 per 20 items for fills and funding, and +1 per 60 for candles. `userRole` and `portfolio` take `hl.weight_userRole` and `hl.weight_portfolio`.
  - *Given* those weights, then over a 2-hour simulated load:
    - every sliding 60 s window stays ≤ `hl.rest_weight_budget_per_min`
    - scoring traffic stays ≤ `hl.scoring_weight_share` of the budget
    - reconciliation and exit-related requests are always served before scoring requests
- **F3.AC2 [unit]** HTTP 429 and timeouts.
  - Every REST call has a `hl.rest_timeout_s` timeout.
  - A 429 or a timeout backs off exponentially with jitter, from `hl.backoff_base_s` to `hl.backoff_max_s`, for at most `hl.retry_max` retries.
  - A test with a server that always returns 429 observes ≤ `hl.retry_max` + 1 requests per call and ≤ 1 request/s to that endpoint.
- **F3.AC3 [integration]** WebSocket limits and heartbeat.
  - Subscribing a user beyond `hl.ws_max_unique_users` distinct users is refused locally and never sent.
  - New connections stay ≤ `hl.ws_max_new_conns_per_min`.
  - When a connection gets no message or pong for `feed.stale_after_s`, *then*:
    - it is marked stale
    - opens and adds for the wallets it serves are refused with `feed_stale`
    - it reconnects with jittered backoff of 1 s up to `hl.ws_reconnect_backoff_max_s`
- **F3.AC4 [integration]** Gap resync.
  - *Given* a disconnect of N seconds, *when* the feed reconnects, *then*, before any new decision for an affected wallet:
    - fills in `[last seen exchange ts, now]` are fetched with `userFillsByTime` and merged by `tid`, with 0 duplicates
    - the gap is written to the ledger as `data_gap` downtime
  - *Given* a snapshot message (`isSnapshot: true`), it is deduplicated the same way.
- **F3.AC5 [unit]** Access degraded (K10).
  - *Given* either of these within `access.degraded_window_min`:
    - at least `access.degraded_error_count` responses with HTTP 403 or 451, or a region-block body
    - a REST success rate below `access.degraded_min_success_rate`

    *then* all of the following happen:
    - the state becomes `access_degraded`
    - opens and adds are refused
    - one alert is sent within 60 s
    - exits, reconciliation and recording keep retrying
    - the time counts as downtime
  - The state clears after `access.recover_min` consecutive minutes with a success rate of at least 95%.
- **F3.AC6 [unit]** Schema validation (failure case).
  - A response that is missing a field or has a wrong type is rejected as a whole and never partially used.
  - At least 3 schema failures in 10 minutes on one endpoint raise one alert.

### F4 Market-data recorder and leaderboard snapshots
- **Value:** point-in-time data from day 1. It is the only source for honest replay, B0d, reconstruction and HIP-3 research [PO].
- **Dependencies:** F2 and F3.

- **F4.AC1 [integration]** Coverage.
  - The recording universe:
    - every core perp traded in the last `recording.universe_lookback_days` by any followed or top-`scoring.candidates_k` wallet
    - plus BTC, ETH and SOL
    - plus all HIP-3 markets (recorded, never traded)
    - capped at `recording.max_coins`, by 24h volume
  - For each coin, these are recorded:
    - L2 book, top `recording.l2_levels` levels, at least every `recording.l2_interval_ms`
    - `allMids` updates
    - mark, oracle, funding and OI every `recording.asset_ctx_interval_s`
    - hourly funding history
  - Over a 1-hour run against a stub feed, the gap between consecutive L2 snapshots is ≤ 5 s in ≥ 99.9% of intervals, for every coin.
- **F4.AC2 [integration]** Leaderboard snapshots.
  - The full leaderboard JSON is stored every `recording.leaderboard_interval_min` (± 5 min), compressed, with its fetch timestamp and sha256.
  - Snapshots are never deleted from the archive (F23.AC2). Local copies are pruned only under the F23.AC2 rule. Every wallet ever seen stays in the local wallet registry (D2).
  - A failed fetch is retried 3 times within the hour, then recorded as `missing` with one alert.
- **F4.AC3 [unit]** Point-in-time reads.
  - Every record stores the exchange timestamp (where one exists) and the local receive timestamp.
  - `as_of(t)` returns no record received after `t`. The test inserts future records and asserts they are excluded.
- **F4.AC4 [unit]** Gap statistics.
  - `recorder gaps --from --to` reports, per coin:
    - the share of time with no L2 snapshot within 5 s
    - the share of time with a mid or mark gap over 60 s
  - On a 1-hour fixture with one injected 10-minute gap, the reported share is 16.7% ± 0.1%.
- **F4.AC5 [integration]** Disk guard (failure case).
  - Free space on every volume holding `storage.recordings_dir`, `storage.ledger_dir` or `storage.cache_dir` is checked every `recording.disk_check_interval_s`.
  - **Alert:** below `recording.disk_alert_free_gb`, one alert per 6 h states the free GB and the unarchived backlog (days and GB, from F23).
  - **Floor:** below `recording.disk_floor_free_gb`, within 2 check intervals:
    - the recorder flushes and closes its open files atomically (no partial file), stops writing, and sends one alert
    - opens and adds are refused with `disk_low`, and the time counts as downtime (F18.AC8)
    - exits, SL/TP, reconciliation, `/flatten`, ledger appends and archive uploads continue. A fixture at the floor shows a leader close still produces our close within the §4 exit budget.
  - Recording resumes automatically once free space is ≥ `recording.disk_floor_free_gb` + `recording.disk_resume_margin_gb`. The stopped interval is a recorder gap (F4.AC4) and is never back-filled with synthetic data.
- **F4.AC6 [simulation]** Recording is independent of trading state. With `/pause`, the kill switch, a loss halt or `access_degraded` active, snapshots continue at the configured rates. The only thing that stops recording is the disk floor (F4.AC5).
- **F4.AC7 [integration]** Compressed storage format.
  - Recordings and leaderboard snapshots are written compressed, in a columnar format with zstd or an equivalent, partitioned by UTC day (and by coin for market data).
  - Files are written atomically (temporary file, then rename). After a force-kill at 20 random points, every file present reads back complete, and no reader ever sees a partial file.
  - A 1-hour fixture reads back exactly equal to what was written: Decimal strings, both timestamps and source tags.
  - On a representative 1-hour fixture of 250 coins, the compressed bytes are ≤ 25% of the same data as uncompressed JSON lines.
  - A finished UTC day's files are closed and marked `day_complete` within `storage.upload_delay_min` after 00:00 UTC, so F23 can archive them.

### F5 Trader scoring (metrics, gates, blow-up detectors, score)
- **Value:** traders are picked on verified-fill evidence, with luck correction (C1). This is edge-hypothesis §10.1–10.5, exactly.
- **Dependencies:** F1. It uses the fills, portfolio and candle interfaces from F3 and F4, stubbed in tests.

- **F5.AC1 [unit]** Metrics.
  - M1–M19 follow the edge-hypothesis §10.2 formulas.
  - On 6 hand-computed fixture wallets, each metric matches the expected value: exactly for Decimal money fields, and to 1e-9 for ratios.
- **F5.AC2 [unit]** Round-trip reconstruction matches `research/scripts/hl_sample.py::reconstruct` on its self-test fixtures:
  - a flip splits into a close and an open
  - a position open at the first fill is ignored until flat
  - spot and `dex:`-prefixed fills are skipped
- **F5.AC3 [unit]** Gates G1–G15, at their boundaries.
  - Required examples:
    - `n_rt` = 149 is ineligible and 150 is eligible
    - `median_hold_min` = 14.99 is ineligible when p95 latency ≤ 45 s
    - `max_dd` = 0.3500 is eligible and 0.3501 is ineligible
  - A missing input, or one older than `scoring.stale_input_mult × scoring.interval_min`, makes the wallet ineligible with reason `stale_input` (fail closed).
- **F5.AC4 [unit]** BU1–BU8 fire exactly at their §10.5 thresholds, and never below their minimum samples. For example, BU1 at 9 adds never fires, and at 10 adds it fires at a share of 0.21 but not at 0.20.
- **F5.AC5 [unit]** Score properties (edge-hypothesis §10.7, tests 1–5 and 12–15).
  - Weights that don't sum to 1 (± 1e-9) fail config load.
  - `S` ∈ [0, 1], and each component is monotone.
  - A wallet's `S` is independent of other wallets and of input order.
  - Results are deterministic, including the tie-break.
  - Fills with `time > t` never change the score at `t`.
  - DSR is monotone.
  - The shrinkage keeps the sign.
  - `perpAllTime` is never interpolated.
  - Account value is taken at or before the event, never after.
- **F5.AC6 [unit]** Verified fills only (C1, abuse case). Setting the leaderboard `pnl`, `roi` and `accountValue` fields to arbitrary values leaves every metric and `S` unchanged.
- **F5.AC7 [unit]** Persistence (B5). Every cycle persists, per wallet:
  - input hashes, metrics, `u_k`, `S` and rank
  - eligibility reasons
  - `dsr_resolution`

### F6 Trader selection and follow manager
- **Value:** automatically follows the best eligible wallets, with hysteresis, within WebSocket limits [PO].
- **Dependencies:** F3, F4 and F5.

- **F6.AC1 [unit]** Hysteresis (edge-hypothesis §10.6 and §10.7 tests 6–10).
  - A wallet joins at rank ≤ `select.join_rank` for `select.join_confirm_cycles` consecutive cycles.
  - It is dropped at rank > `select.drop_rank` for `select.drop_confirm_cycles` cycles, and only once it has been followed ≥ `select.min_follow_hours`.
  - A wallet in the band `(join, drop]` keeps its status.
  - There are ≤ `select.max_swaps_per_cycle` swaps per cycle, each with `S_cand ≥ S_weakest + select.swap_margin`.
  - The followed count is always ≤ `select.max_followed` (9).
- **F6.AC2 [unit]** Safety drop, immediate.
  - Triggers: any BU flag, a G15 failure, a copy drawdown ≥ `leader_pause.max_copy_dd × risk.leader_allocation_fraction × equity`, or `leader_pause.max_consec_losses` consecutive copy losses.
  - From the next signal (within 1 s), the wallet's opens and adds are refused with `leader_paused`, whatever its follow time.
- **F6.AC3 [integration]** WebSocket slots.
  - Distinct subscribed users stay ≤ 10: followed wallets, plus dropped wallets that still have open shares, plus an incoming wallet.
  - A join or swap without a free slot is deferred and logged `no_ws_slot`.
  - A dropped wallet keeps its subscription until its last share closes, and releases it ≤ 60 s later.
- **F6.AC4 [integration]** Backfill first [PO]. No wallet is followed until the incremental backfill of all `scoring.candidates_k` candidates has completed. At default config against a rate-budget simulator, that finishes in ≤ `select.backfill_max_hours`.
- **F6.AC5 [unit]** Leaderboard outage (failure case).
  - Triggers: an HTTP error, a timeout, a schema failure, or fewer than 1,000 rows.
  - Effect: the current followed set is kept, 0 wallets are added, and one alert is sent per outage. Followed wallets keep being re-scored from fills.
- **F6.AC6 [unit]** Few eligible.
  - With fewer than `select.min_followed` eligible, all eligible wallets are followed, and the list is never padded with ineligible ones.
  - With 0 eligible, opens are refused with `no_eligible_leaders` and one alert is sent.
- **F6.AC7 [unit]** Cadence.
  - A cycle starts every `scoring.interval_min` ± 2 min.
  - A cycle that has not finished within `select.max_cycle_duration_min` keeps the previous followed set, and is logged `cycle_overrun`.

### F7 Signal detection
- **Value:** turns followed wallets' fills into typed, deduplicated, timestamped signals.
- **Dependencies:** F2 and F3.

- **F7.AC1 [unit]** Classification.
  - From `startPosition`, `sz` and `side`:
    - open: 0 → non-zero
    - add: same sign, |post| > |pre|
    - reduce: same sign, 0 < |post| < |pre|, with fraction `(|pre| − |post|) / |pre|`
    - close: post = 0
    - flip: sign change, which gives a close plus an open
  - A 30-case fixture covers each type, including aggregated fills.
- **F7.AC2 [unit]** Idempotency (A5).
  - A fill whose `tid` was already processed, whether it arrives from the WebSocket, a snapshot or a REST resync, creates no signal.
  - A 1,000-event fixture with 30% duplicates yields exactly the unique count.
- **F7.AC3 [unit]** Pre-existing positions.
  - *Given* wallet W is followed at `t_f` and holds coin X at `t_f`, according to `clearinghouseState` at follow time,
  - *then* every W fill on X is `pre_existing` (logged, not traded) until W is flat on X.
  - The next open is a normal signal.
- **F7.AC4 [unit]** Scope. These produce outcome `out_of_scope` and are never traded:
  - fills on `dex:`-prefixed (HIP-3) markets
  - spot fills
  - coins outside `markets.allowed_dexes`
- **F7.AC5 [unit]** Age.
  - Each signal carries the exchange timestamp, the local receive timestamp and `age_ms = (receive_local + offset) − exchange_ts`.
  - An `age_ms` below −`clock.max_offset_uncertainty_ms` is flagged `clock_anomaly` and refused for opens.
- **F7.AC6 [integration]** Throughput and latency mode.
  - A burst of 100 fills/s for 10 s across 9 wallets is classified with p99 receive-to-signal ≤ 50 ms, and 0 fills are dropped.
  - `latency measure --hours N --wallets <list>` records the per-signal stages S1–S2 (§4) without trading. It can run before F9–F12 exist.

### F8 Economic calendar and blackouts
- **Value:** no new exposure into scheduled macro releases [PO D10].
- **Dependencies:** F1.

- **F8.AC1 [unit]** Windows are computed in `calendar.timezone` and converted at runtime:
  - FOMC 2026-10-28 14:00 EDT → blackout 17:30–19:00 UTC
  - FOMC 2026-12-09 14:00 EST → 18:30–20:00 UTC
  - CPI 2026-10-08 08:30 EDT → 12:15–13:00 UTC
- **F8.AC2 [unit]** A blackout refuses opens and adds only, with `event_blackout`. It never blocks reduces, closes, SL/TP, `/flatten` or reconstruction.
- **F8.AC3 [unit]** Fail closed (failure case). If the calendar file is missing, fails to parse, or covers fewer than `calendar.min_coverage_days` from now, *then*:
  - opens and adds are refused with `calendar_invalid`
  - one alert is sent
  - F17 refuses to start a run
- **F8.AC4 [unit]** Events whose class is not in `calendar.blocking_classes` (PPI, GDP, retail sales, minutes) never block.
- **F8.AC5 [unit]** Blackout intervals are ledgered as `rule_blackout` and are never counted as downtime.

### F9 Filter and decision
- **Value:** deterministic yes/no per signal with a full audit trail, plus shadow outcomes so the filter's value can be measured later (H3). Coins qualify for trading, and get their thresholds, from measured liquidity, so liquid meme perps can trade and thin coins can't.
- **Dependencies:** F4, F7 and F8. Tier computation reads recordings through the store interface (F4, with F23's archive fallback when present).

- **F9.AC1 [unit]** Boundaries of the enforced rules. The first value passes, the second is refused with the reason given. Tiers come from the tier table in force (F9.AC8).

  | Rule | Passes | Refused | Reason |
  |---|---|---|---|
  | Signal age | 5,000 ms | 5,001 ms | `stale_signal` |
  | Adverse slippage vs the leader's fill price, for our expected VWAP from the book at decision, tier-1 coin | 0.300% | 0.301% | `slippage` |
  | Same, tier-2 coin | 0.800% | 0.801% | `slippage` |
  | Spread, tier-1 coin | 0.100% | 0.101% | `spread` |
  | Spread, tier-2 coin | 0.300% | 0.301% | `spread` |
  | Order share of depth within `filter.depth_band_pct` of mid | 1.00% | 1.01% | `depth` |
  | Book or mark age | 2,000 ms | 2,001 ms | `stale_price` |
  | Coin tier | tier 1 or tier 2 | below floor | `illiquid_coin` |
  | Coin present in the tier table in force | present | absent | `untiered` |

  The same tier-1 thresholds apply to a coin whatever its name: a fixture where DOGE is tier 1 applies 0.300% / 0.100% to DOGE, and one where BTC is tier 2 applies 0.800% / 0.300% to BTC.

- **F9.AC2 [unit]** Determinism and point-in-time (D1).
  - The same inputs give the same verdict.
  - Adding data received after the decision timestamp doesn't change it.
- **F9.AC3 [unit]** Conflicts.
  - An open on coin X in direction d, while any of our open shares on X has direction −d, is refused with `conflict`.
  - The same direction is accepted as a new share of the merged position, subject to F10 caps.
- **F9.AC4 [unit]** Volatility regime.
  - Realised volatility is the standard deviation of 1h log returns over the last `filter.vol_window_h`.
  - When its percentile against a trailing `filter.vol_lookback_days` of 1h candles is ≥ `filter.vol_halving_percentile`, the size multiplier is `filter.vol_size_mult`. Otherwise it is 1.0.
  - At the 90th percentile exactly, the multiplier is 0.5. At the 89.9th, it is 1.0.
- **F9.AC5 [unit]** Record-only rules.
  - Trend, funding, OI drop and premium compute and log their value on every decision.
  - While their mode is `record_only`, they never change the verdict.
  - With mode `enforce` and a threshold set, the veto applies at the threshold boundary.
- **F9.AC6 [simulation]** Shadow outcomes.
  - Every refused open, except `duplicate`, `out_of_scope` and `pre_existing`, gets a shadow trade with the same sizing, exits and cost model.
  - Shadows are flagged `shadow` and are never in equity, risk state, the trade count or S.
- **F9.AC7 [unit]** Automatic tier assignment (A6).
  - For each allowed core coin in the recording universe, two metrics are computed over the last `tiers.lookback_days` of our own recordings, using only records received at or before the computation time:
    - **depth:** the median, over L2 snapshots, of min(bid notional, ask notional) in USD within `tiers.depth_band_pct` of mid
    - **volume:** the median of the recorded 24h notional volume, sampled once per UTC hour
  - **Tier 1** iff depth ≥ `tiers.tier1_min_depth_usd` **and** volume ≥ `tiers.tier1_min_volume_usd`.
  - **Tier 2** iff not tier 1, and depth ≥ `tiers.floor_min_depth_usd` **and** volume ≥ `tiers.floor_min_volume_usd`.
  - **Below floor** otherwise, and also when recorded coverage over the lookback is < `tiers.min_coverage_fraction` (fail closed).
  - Boundaries, with defaults: depth $1,000,000 and volume $200,000,000 is tier 1; depth $999,999 with the same volume is tier 2; depth $50,000 and volume $10,000,000 is tier 2; depth $49,999 is below floor; coverage 0.79 is below floor.
  - Load-time check: a tier-1 threshold below its floor counterpart fails config load.
  - The tier code reads no coin-name list; a static test finds no coin symbol literal in the tier module. HIP-3 (`dex:`), spot and non-core coins are never tiered.
  - Each computed table (coin, metrics, tier, coverage, computation time, data window) is ledgered with its sha256. The same inputs give a byte-identical table.
- **F9.AC8 [unit]** Tier schedule and freeze (A6).
  - Outside a run, the table is recomputed every `tiers.recompute_interval_h` (± 10 min) and the new table comes into force at once. Changes (coin, old tier, new tier) go into the next daily report.
  - At run start, the table in force is frozen into the run record with its sha256 (F17.AC1) and used unchanged until the run ends. Recomputations during a run are ledgered as `tiers_candidate` and are never applied.
  - With no table in force, or one older than `tiers.max_age_h` outside a run, every open is refused with `untiered`, and one alert is sent.
  - Meme-perp fixtures: with recordings where DOGE, kPEPE and WIF meet the tier-2 thresholds, their opens pass the tier rule. With WIF below the floor, a WIF open is refused `illiquid_coin`, and DOGE and kPEPE are unaffected.
  - A coin that drops below the floor while a share is open keeps being managed: exits, SL/TP and reconciliation are never refused for tier reasons.

### F10 Risk gate and sizing
- **Value:** a single chokepoint that sizes every order from our risk budget and enforces every hard limit. The cap always wins.
- **Dependencies:** F2 and F11. F11 exposes a broker interface that requires a gate token.

- **F10.AC1 [integration]** Single chokepoint (A1).
  - Every order intent passes `risk_gate.check()`: open, add, reduce, close, SL/TP, `/flatten`, a dropped leader's exit, and a reconstruction settlement.
  - The broker rejects and logs any order without a valid, single-use gate approval.
  - A static test asserts that only the risk gate module calls broker submit.
- **F10.AC2 [unit]** Sizing.
  - `mirror_notional = (leader post-fill position notional / leader account value at or before the fill) × equity`
  - `risk_notional = equity × risk.per_trade_fraction × vol_mult / stop_distance_fraction`
  - `final = min(mirror, risk, every cap in AC3)`, rounded down to the lot.
  - Worked example: equity $300, stop 1.5%, leader at 50% of their account. Mirror is $150, risk is $100, so final is $100.
  - A final below `sizing.min_order_usd` is `unexecutable`: logged, with no order and no trade.
  - A leader account value that is missing, or older than `follow.max_leader_av_age_s`, gives `no_leader_av`.
- **F10.AC3 [unit]** Caps. The size is reduced to fit, then the $10 check is re-applied. Each cap is tested at its boundary:
  - open merged positions ≤ `risk.max_open_positions`
  - total open risk ≤ `risk.max_total_open_risk_fraction`
  - per coin ≤ `risk.max_symbol_open_risk_fraction`
  - BTC bucket, same direction ≤ `risk.max_btc_bucket_open_risk_fraction`. The bucket is BTC plus every coin with a correlation of 1h returns to BTC ≥ `risk.btc_bucket_corr_threshold` over `risk.btc_bucket_corr_window_days`.
  - per leader ≤ `risk.max_leader_open_risk_fraction`
  - notional ≤ `risk.max_position_notional_equity_mult × equity`
  - orders ≤ `risk.max_orders_per_min`
- **F10.AC4 [unit]** Automatic leverage and margin (A2).
  - Margin is isolated, one position per coin (the merged position). Size and initial risk are fixed first by AC2 and AC3; leverage never changes them.
  - **Ceiling:** `C = min(risk.max_leverage_high_tier if the coin is in risk.high_leverage_coins else risk.max_leverage_alt, the exchange maxLeverage for the coin)`.
  - **Choice:** at each open or add, L is the **lowest integer** in [`risk.leverage_min`, C] for which the merged position's required isolated margin (post-order notional / L) ≤ its currently posted margin + free equity. Free equity is equity minus all posted isolated margin.
  - No integer in the range fits → refused `insufficient_margin`.
  - **Liquidation rule:** at the chosen L, for **every** share of the merged position, the distance from the decision price to the liquidation price (the F11.AC5 model) must be ≥ `risk.min_liq_distance_stop_mult` × the distance from the decision price to that share's current stop. Otherwise the order is refused `liq_too_close`. No higher L is tried, because a higher L only moves liquidation closer.
  - Vectors, on a fixture where the liquidation distance is `1/L − 1/(2 × maxLeverage)` and the decision price equals the entry:
    - equity $300, no open positions, BTC $100 notional → 1x
    - free equity $40, ETH $100 → 3x
    - free equity $15, alt $100 (ceiling 5x needs $20) → `insufficient_margin`
    - free equity $12, SOL $100, exchange maxLeverage 20 → 9x (liquidation distance 8.611%); stop 2.8% passes (8.4% ≤ 8.611%); stop 2.9% is refused `liq_too_close` (8.7%)
    - free equity $12, DOGE $100 (not a high-leverage coin) → `insufficient_margin` (5x needs $20)
  - The chosen L, the ceiling C, the posted margin and the liquidation price go into the decision record (F2.AC2) and the trade post (F14.AC2).
  - Exits (reduce, close, SL/TP, `/flatten`, reconstruction settlement) are never refused for margin or leverage.
- **F10.AC5 [unit]** Loss limits and drawdown.
  - **Daily:** equity change since 00:00 UTC ≤ −`risk.daily_loss_limit` of that day's opening equity halts opens and adds until the next 00:00 UTC. At −1.99% nothing halts; at −2.00% it halts.
  - **Weekly:** from Monday 00:00 UTC, ≤ −`risk.weekly_loss_limit` halts until the next Monday.
  - **Drawdown:** mark-to-market equity is marked every `eval.mark_interval_s`. A drawdown from peak ≥ `eval.max_dd` does all of the following:
    - pauses until `/resume`
    - writes an F1 event
    - alerts
  - Loss halts are rule-based and are not downtime.
- **F10.AC6 [integration]** Kill switch (A4).
  - Telegram `/pause` or the CLI `pause` refuses new opens and adds within 1 s.
  - The state persists: after a restart the engine is still paused.
  - `/resume` or the CLI `resume` clears it.
  - `/flatten <PIN>` or the CLI `flatten --pin` closes every share through the gate.
  - All of this works with market-data feeds down.
- **F10.AC7 [unit]** Fail closed (A2, failure case).
  - Any exception in a check, an unknown equity or risk state, an unverified ledger, or config that failed validation each refuse opens and adds, with the reason logged.
  - Exits are **never** refused by caps, limits, blackouts or pauses. The gate only validates reduce-only, a quantity ≤ the share and idempotency.
- **F10.AC8 [unit]** Idempotency (A5).
  - The client order ID is `sha256(run_id ‖ leader ‖ coin ‖ sorted signal tids ‖ action ‖ share_id)`, truncated as the broker requires.
  - Re-submitting the same intent after a restart produces 0 extra fills.
- **F10.AC9 [unit]** Adds.
  - The add quantity is our share qty × (leader add size / leader pre-add |position|).
  - The add is skipped as `stop_widening` when its own ATR stop would sit beyond the current stop: below it for a long, above it for a short.
  - It is capped so the share's open risk is ≤ `risk.max_share_risk_fraction × equity`, and by the AC3 caps.
  - Below $10, it is skipped as `add_below_min`.
- **F10.AC10 [unit]** Leverage property tests (A2). Over ≥ 10,000 generated cases (coin in or out of the high-leverage list, equity, free equity, open shares, stops, exchange maxLeverage, notional), for every accepted open or add:
  1. **Ceiling:** 1 ≤ L ≤ C, and L ≤ 10 for high-leverage coins and ≤ 5 for every other coin, whatever the config.
  2. **Minimality:** L = `risk.leverage_min`, or L − 1 does not fit the margin.
  3. **Liquidation:** every share of the resulting merged position meets the liquidation rule.
  4. **Risk unchanged:** the final size and `initial_risk_usd` are identical to those computed with free equity set to infinity. Leverage never changes risk per trade.
  5. **Monotone:** raising free equity, all else equal, never raises L.
  6. **Refusal is exact:** an order is refused `insufficient_margin` iff no L in range fits, and `liq_too_close` iff the minimal fitting L fails the liquidation rule.
  7. **Single model:** the liquidation price used by the gate equals the F11.AC5 liquidation price for the same position, to the tick.
  8. **Exits:** no exit is ever refused for margin, leverage or liquidation distance.

### F11 Paper broker (fills, costs, funding, liquidation, delisting)
- **Value:** paper fills at real mainnet prices, with realistic costs, so the results transfer (D3).
- **Dependencies:** F1 and F2. It reads the book, mark and funding interfaces from F3 and F4.

- **F11.AC1 [unit]** Fill model.
  - A market order decided at `t` fills by walking the book at `t + paper.ack_delay_ms`: the first snapshot at or after that time within `paper.max_book_age_ms`.
  - The price is the VWAP across the levels needed.
  - Example: asks [100.0 × 0.5, 100.1 × 1.0], buy 1.0 → VWAP 100.05.
  - Depth insufficient within 5% of mid gives a partial fill, recorded as `partial_fill` (A8), with the remainder cancelled.
- **F11.AC2 [unit]** Fees.
  - Every fill, including SL, TP and liquidation, pays `cost.taker_fee_bps` of its notional.
  - No maker fills or rebates are simulated.
- **F11.AC3 [unit]** Funding.
  - At each UTC hour boundary, each open share pays or receives `qty × oracle_px × hourly rate`, signed by side, at that hour's actual rate.
  - A share closed before the boundary, or opened after it, pays nothing for that hour.
- **F11.AC4 [unit]** Exchange rules.
  - Orders below `sizing.min_order_usd` are refused with `below_min_notional`, except a reduce-only full close.
  - Tick and lot rules come from `meta`, refreshed every `paper.meta_refresh_min`.
  - A coin missing from `meta` is refused with `unknown_coin`.
- **F11.AC5 [unit]** Liquidation (A8).
  - An isolated position whose mark reaches its liquidation price closes at that price. It loses its margin and is flagged `liquidated`, and an alert is sent. Maintenance margin is half the initial margin at the asset's max leverage.
  - A fixture where the mark gaps through both the stop and the liquidation price gives `liquidated`.
- **F11.AC6 [unit]** Delisting. An open share on a delisted coin closes at the exchange settlement price, flagged `delisted_force_settle`, and it counts in every statistic.
- **F11.AC7 [unit]** Stops.
  - SL and TP trigger on mark and fill at the book at trigger time + `paper.ack_delay_ms`, never at a guaranteed price.
  - Example: long stop at 99, next book bid 97.0 → the fill is ≤ 97.0.
- **F11.AC8 [unit]** Rejects (A8, failure case).
  - With no book within `paper.max_book_age_ms`, an open is refused with `no_book` and not retried.
  - An exit is retried every `exits.retry_interval_s` until it fills, with one alert after `exits.alert_after_s`.

### F12 Position manager (shares, exits, mirroring, reconciliation, shadows)
- **Value:** first-exit-wins management that mirrors the leader's adds and partials, and never leaves an orphaned copy (C4).
- **Dependencies:** F7, F10 and F11.

- **F12.AC1 [unit]** Per-leader shares.
  - Each share has its own qty, entry, initial stop, current stop, TP state, initial risk and max committed risk.
  - A leader's event changes only that leader's share.
  - With leaders A and B both long ETH, A's close leaves B's share unchanged.
- **F12.AC2 [unit]** Stops and TP.
  - **Stop:** `entry_fill_px ∓ exits.stop_atr_mult × ATR(exits.atr_period)` on `exits.atr_candle_interval` candles that closed before entry.
  - **Take-profit:** with `exits.tp_enabled`, close `exits.tp1_fraction` of the share at `+exits.tp1_r` R, applying the $10 rules.
  - **Trailing stop:** after `+exits.trail_start_r` R, trail at `exits.trail_atr_mult × ATR` from the best mark since entry.
  - **Never widens:** a property test over 10,000 random paths shows the stop is non-decreasing for longs and non-increasing for shorts.
- **F12.AC3 [unit]** Partials [PO].
  - A leader reduce of fraction f reduces our share by f × its qty, rounded down to the lot.
  - A reduce notional below $10 is skipped as `partial_below_min`.
  - A remainder below $10 closes everything, as `close_all_remainder_below_min`.
  - Vectors: share $50 at f 0.4 reduces $20. Share $20 at f 0.4 is skipped ($8). Share $30 at f 0.7 closes all ($9 remainder).
- **F12.AC4 [unit]** First exit wins [PO].
  - A leader close closes our share.
  - After our SL or TP closes a share, that leader's later adds, reduces and close on that position are ignored until the leader is flat. The leader's next open is a new signal.
  - A leader flip closes our share and emits a new open signal.
- **F12.AC5 [integration]** Leader reconciliation (C4 and A7 analogue).
  - It runs every `reconcile.interval_s` and after every resync.
  - For each open share, it reads the leader's `clearinghouseState`. If the leader is flat or reversed on that coin, *then*:
    - our share closes at once with `reconcile_close`
    - an alert is sent
    - F12.AC6 runs
- **F12.AC6 [unit]** Missed-exit detector (P4 / F2, edge-hypothesis A3).
  - Each §1 case is detected and ledgered as `missed_exit` with: leader, coin, share ID, event type, the event's exchange timestamp, the detection timestamp, the lag and the case (late, reconstruction failed or orphan).
  - The share is brought in line with the leader at once (the late reduce or close, through the gate).
  - One alert is sent within 60 s of detection. It states the running count as `n/3` and that the event is a go-live blocker.
  - Each missed exit writes a `go_live_blocker` record that no later record can clear within this epic (F20.AC4).
  - A missed exit does **not** by itself end the run. The FAIL decision belongs to F18.AC11.
  - On fixtures:
    - a dropped exit event, found by reconciliation 61 s later, is a missed exit
    - one found 60 s later is not
    - an exit inside recorded downtime that F13 settles is not
    - a partial skipped under the $10 rule is not
- **F12.AC7 [simulation]** `/flatten` shadows (edge-hypothesis A1.3 d and A2.1).
  - Each flattened share gets a shadow, managed on recorded data under the frozen exit rules: leader exits, SL/TP and hourly funding. Over recording gaps it uses 1h candles, with the stop assumed hit first.
  - The shadow runs until the shadow exit, whose time and R are stored.
  - Moving the flatten time while the shadow path is unchanged leaves the shadow exit unchanged.
- **F12.AC8 [unit]** A dropped leader's shares stay managed by our SL/TP and that leader's exits, through the gate, until they close.
- **F12.AC9 [simulation]** Mirrored counterfactual (edge-hypothesis A3; fill basis in Assumption A20).
  - For every missed exit, the engine computes the share's **mirrored** outcome: its outcome had the leader event been mirrored on time, with every other event unchanged, under the frozen exit and cost rules.
  - **Cost** = mirrored R − actual R, in units of the share's initial risk. Everything after the actual path has acted on the missed event is identical on both paths, so the cost is known once that fill exists. That fill is the late reduce or close, or an SL/TP fill that came first. The cost is stored within 5 min of it.
  - When the share fully closes, it stores actual R, mirrored R and gate R = min(actual, mirrored), with the USD equivalents chosen the same way.
  - Every value is Decimal, quantised to 1e-6.
  - Vectors:
    - actual −1.400000R, mirrored −0.200000R → gate −1.400000R, cost 1.200000R
    - actual +0.800000R, mirrored +0.500000R (the late exit was luckier) → gate +0.500000R, cost −0.300000R
  - If no mirrored outcome can be computed from recorded books or exchange candles, cost is recorded as `uncomputable` and treated as exceeding 1R (fail closed, Assumption A20).
  - The same inputs give byte-identical counterfactual records.

### F13 Restart reconstruction
- **Value:** downtime on a home PC never leaves a position unmanaged, and never fakes a result.
- **Dependencies:** F3, F4 and F12.

- **F13.AC1 [simulation]** Reconstruction.
  - Scope: shares open at the last heartbeat `t_s`, with a restart at `t_r` where `t_r − t_s` ≤ `restart.max_reconstruct_gap_h`.
  - Before any new decision, the engine walks the leader fills from `userFillsByTime` over `[t_s, t_r]` and the `restart.candle_interval` candles, in time order:
    - the first of SL, TP or a leader exit acts; the stop is assumed first on an ambiguous bar, and partials are mirrored
    - fills are at the trigger or leader price ± `cost.fallback_half_spread_bps` and `cost.fallback_delay_slippage_bps`, plus taker fees
    - hourly funding is accrued
    - these shares are flagged `reconstructed`
- **F13.AC2 [unit]** Leader opens during the gap are never taken. They are logged `missed_during_downtime` and are not trades.
- **F13.AC3 [unit]** Gap too long (failure case).
  - A gap over `restart.max_reconstruct_gap_h`, or candles that can't be fetched, closes each share at the first fresh book after restart.
  - Those shares are flagged `unreconstructable`, an alert is sent, and they are included in every statistic.
- **F13.AC4 [integration]** Downtime and speed.
  - `[t_s, t_r]` is ledgered as `process_down` downtime.
  - The kill-switch state is restored before any other component starts.
  - For a gap of ≤ 1 h, the engine is trading-ready ≤ 120 s after process start.
- **F13.AC5 [unit]** A second restart during reconstruction gives an identical result, with 0 duplicated closes.

### F14 Telegram bot, reports and alerts
- **Value:** the PO sees every trade and controls the bot securely from their phone.
- **Dependencies:** F2, F10 and F12. It uses F15's interface optionally.

- **F14.AC1 [integration]** Authentication (E3, abuse case).
  - Only updates from `telegram.allowed_user_id` in `telegram.control_chat_id` are executed.
  - 5 commands from another user or chat cause 0 state changes and write 5 ledger audit records: user ID, chat ID, command name, time and result.
  - At most one alert is sent per `telegram.unauthorized_alert_interval_min`.
- **F14.AC2 [qa-ui]** Trade posts.
  - On entry, a post arrives within 5 s (p95) and shows:
    - a direction marker (green for long, red for short) and a `PAPER` label
    - coin, direction, entry price, SL, TP, size (qty and USD) and leverage
    - each leader's label (display name or shortened address) with that leader's scoring-window win rate and P&L
    - the "why" text, or "why unavailable"
  - A merged position has exactly one post, which is edited on each add, partial, stop move and close.
  - The final post shows the realised USD P&L and the exit reason.
- **F14.AC3 [unit]** Edit rate.
  - Each message gets ≤ 1 edit per `telegram.min_edit_interval_s`, and intermediate states are coalesced.
  - The latest state is visible ≤ 10 s after the last change.
  - Each chat gets ≤ `telegram.max_msgs_per_min_per_chat`.
  - An HTTP 429 `retry_after` is honoured.
- **F14.AC4 [qa-ui]** Commands, each answering within 3 s (p95):

  | Command | Shows or does |
  |---|---|
  | `/status` | Mode, running or paused (with reasons), followed count, open positions, feed health, run number and n/300, free disk, archive state (backlog days, last verified day and backup, or `archive: not configured`) and the projected monthly storage cost |
  | `/pnl` | USD realised and unrealised: today, this week, and this run |
  | `/traders` | Followed wallets with score, rank and follow start |
  | `/stats` | Descriptive run statistics (F14.AC9) |
  | `/pause`, `/resume` | Pause or resume new opens and adds |
  | `/flatten <PIN>` | Close every share |

- **F14.AC5 [unit]** PIN (abuse case).
  - The PIN is checked against a salted hash from the environment, and the PIN itself is never stored.
  - A wrong PIN is refused, audited and alerted.
  - `telegram.pin_max_attempts` failures within `telegram.pin_lockout_min` lock `/flatten` for `telegram.pin_lockout_min`. The CLI flatten stays available.
  - The bot deletes the message containing the PIN after processing.
- **F14.AC6 [unit]** Visibility lock (edge-hypothesis §5.5 as amended by A3).
  - While a run is active and before `T_eval`, no message, command, report or alert shows:
    - any confidence interval, bound (`LB_r`, `UB_r`), t statistic or bootstrap output, for R or D
    - any D value, B0d mean or P2c status
    - FR1–FR6, K-checks or D6 checks
    - the status of any gate condition (P1–P6, P2b, P2c, F1–F3) as pass, fail or "on track", or any verdict preview, projection or implied probability
  - Allowed: per-trade outcomes, USD P&L, counts, progress toward 300, raw downtime, and the `/stats` descriptive figures (F14.AC9).
  - A test renders every template, including `/stats`, with a run fixture and finds 0 forbidden fields or phrases.
  - A static dependency test shows that `telegram` and `reports` never import `evaluation` or `baselines`.
- **F14.AC7 [qa-ui]** Reports.
  - The daily report goes out at `report.daily_time_utc` and the weekly one at `report.weekly_time_utc`.
  - Each covers: USD P&L, trades opened and closed, refusals by reason, unexecutable count, downtime, followed-set changes, missed exits (count and IDs), coin-tier changes (F9.AC8), archive state and the projected monthly storage cost (F23.AC7).
  - Each ends with `report.disclaimer`.
- **F14.AC8 [integration]** Alerts and outage (failure case).
  - Alerts go only to `telegram.alerts_chat_id`.
  - If the Telegram API is unreachable:
    - messages queue up to `telegram.queue_max_messages` or `telegram.queue_max_age_h`
    - trading continues
    - alerts are also written to the local log
    - the queue drains in order on recovery
- **F14.AC9 [qa-ui]** `/stats` (A14). It answers within 3 s (p95) from ledger aggregates (F2) only, and shows, for the active run (or, with no run active, since the dry-run start or the last run end, with that scope labelled):
  - USD P&L: realised, unrealised and total
  - closed-trade count, win rate (the share of closed trades with realised R > 0) and average realised R per closed trade
  - the current drawdown from the equity peak and the largest drawdown so far, on marked-to-market equity
  - per leader (followed, or dropped with trades this run): trades, win rate, average realised R and USD P&L
  - progress: n/300 opened, closed count, and days elapsed against the 30-day cap and the 60-day extension
  - a fixed footer: "Descriptive only, realised results. Not the gate statistic and not a verdict. The verdict is computed once at T_eval."
  - On a 12-trade fixture (7 winners, R values summing to +1.800000, USD +$4.20), `/stats` shows 12 closed, 58.3% win rate, average +0.150R and +$4.20.
  - With 0 closed trades, it shows "no closed trades yet" and no ratios (no division by zero).
  - From an unauthorised user or chat it behaves as F14.AC1: 0 output and one audit record.

### F15 LLM explainer ("why" text and summary)
- **Value:** readable context for each trade, with zero influence on trading [PO D5].
- **Dependencies:** F2 and F14's interface.

- **F15.AC1 [unit]** Off the hot path (F1 invariant).
  - The trade post is sent without waiting for the LLM.
  - The "why" text is added by an edit if it returns within `llm.timeout_s`. Otherwise the post stays "why unavailable".
- **F15.AC2 [unit]** Budget.
  - When the tracked month-to-date spend reaches `llm.monthly_budget_usd`, cloud calls stop until 00:00 UTC on the 1st of the next month.
  - `llm.fallback` (Ollama) is tried next. If both are unavailable, there is no "why" text.
  - Spend never exceeds the cap by more than one call's cost.
- **F15.AC3 [unit]** Logging (F3 invariant). Each prompt and output is logged with its decision ID, and prompts contain 0 secrets (canary test).
- **F15.AC4 [unit]** No vote (F2 invariant). A static dependency test shows that `filters`, `risk` and `positions` never import `llm`. An LLM stub returning "reject" or "double the size" changes 0 decisions.
- **F15.AC5 [unit]** Injection (abuse case).
  - A leader display name or an output containing Markdown or HTML, or text like "ignore previous instructions", is escaped in Telegram.
  - Output is truncated to `llm.max_output_chars`.
  - Inputs are limited to the trade record, the calendar events within ±24 h and the coin's recorded regime metrics. No web fetch.

### F16 Replay engine
- **Value:** point-in-time replays through the **same** engine, for the kill checks, variant choice, P6 and D6.
- **Dependencies:** F4, F9, F10, F11 and F12.

- **F16.AC1 [simulation]** Same code. Replay drives the same signal → filter → gate → broker → position modules, with a replay clock. A static test finds no replay-only decision code.
- **F16.AC2 [simulation]** Point-in-time (D1 and D2).
  - At replay time t, it uses only recordings received ≤ t and our own leaderboard snapshots.
  - Injecting future data changes 0 decisions.
- **F16.AC3 [simulation]** Determinism. Two replays of the same window and config give byte-identical ledgers.
- **F16.AC4 [unit]** Indicative mode.
  - Any replay that uses data from before our recording start (API history) labels every output `indicative_only_survivorship_biased`.
  - The evaluation API refuses it as input.
- **F16.AC5 [simulation]** Variant budget (D4).
  - Only V0–V7 (edge-hypothesis §5.8) can be run, and the ledger counts distinct variants. A 9th is refused.
  - Sensitivity runs (`replay.sensitivity_cost_mults`, `replay.sensitivity_delays_s`) run on the selected variant and are not counted.
- **F16.AC6 [simulation]** Cost model.
  - Spread: recorded at signal time; otherwise the coin's median half-spread × `cost.fallback_half_spread_mult`; otherwise `cost.fallback_half_spread_bps`.
  - Delay: measured decay at the p95 detection latency; otherwise `cost.fallback_delay_slippage_bps`.
  - Ambiguous bars: the stop is assumed first.
- **F16.AC7 [simulation]** Speed. A replay of 7 recorded days for 9 wallets finishes in ≤ 60 min on the PO's PC.

### F17 Run control (run record, freeze, deploys, run register)
- **Value:** runs that can't be quietly altered. This implements edge-hypothesis §5.1, §5.3 (engine changes) and §5.4.
- **Dependencies:** F1 and F2. F8 supplies the calendar-coverage check.

- **F17.AC1 [integration]** Run record. `run start` writes:
  - the run number and `t0`
  - the sha256 of `docs/sdlc/copytrade-v1/research/edge-hypothesis.md`
  - the config hash: sha256 over the sorted (path, bytes) of `config/**`
  - the CI level: `eval.ci_level_run1` or `eval.ci_level_run2`
  - a 32-byte CSPRNG seed as hex
  - the 40-hex engine commit and the dirty flag
  - the lockfile sha256 and the Python version
  - the installed-package-list sha256: `name==version` with normalised lowercase names, sorted, UTF-8, LF line endings
  - the per-file sha256 of every non-config data input
  - the coin-tier table in force at `t0` (F9.AC8), stored in full with its sha256

  A fixture checks each field and the canonical package-list bytes.
- **F17.AC2 [integration]** Refusals (fail closed). `run start` refuses when any of these holds:
  - the dirty flag is true: a tracked engine-path-set file differs from the commit, or an untracked file exists inside the set
  - the checkout is not a worktree detached at the run commit
  - the ledger doesn't verify
  - the calendar covers fewer than `calendar.min_coverage_days`
  - the candidate backfill is incomplete
  - `eval.max_runs` runs are already registered
  - no tier table is in force, or it is older than `tiers.max_age_h`
  - the archive is unhealthy: storage credentials are missing, a finished UTC day older than `storage.max_unarchived_days` is not archived, or no ledger backup has verified in the last 48 h (F23)

  A commit or untracked file under `docs/**` or `research/**` does **not** make the tree dirty.
- **F17.AC3 [integration]** Mid-run deploys. At each process start during a run, the engine compares six things with the run's version in force: the commit, the dirty flag, the lockfile hash, the Python version, the installed-package-list hash and the data-input hashes. Any difference means:
  - a deploy record is written: time, old and new commit, the full `git diff` stored as a patch with its sha256, the lockfile diff and a stated reason
  - the new code exits non-zero, without trading or managing positions, until a ruling (`CONTINUE` with the affected trade IDs, or `ABORTED`) is in the ledger
  - the recorded commit keeps running from the run worktree
  - any paused time counts as downtime
- **F17.AC4 [unit]** Config change. A config hash that differs from the run record, checked at start and every 60 s, makes the run `ABORTED` at that moment. The run count increments, and a 3rd run can't start. A tier table in force whose sha256 differs from the run record's is treated the same way.
- **F17.AC5 [unit]** Manual end.
  - `run stop --confirm` ends the run as `ABORTED`.
  - An auditor void-ruling record makes it `ABORTED` even after an F1 or F2 breach, and it can never produce `PASS`.
- **F17.AC6 [unit]** Run register.
  - Start, end, deploy and ruling rows are appended to the ledger's run register.
  - `run register export` prints rows in the `research/run-register.md` column order.
  - Appending never changes the edge-hypothesis or config hash (evaluation test 18).
- **F17.AC7 [unit]** Dry-run mode. It runs the full pipeline without writing a run record, and none of its trades can ever enter any run's sample.
- **F17.AC8 [unit]** A crash restart is not a deploy: same commit, a clean tree, the same lockfile, config, package list and data inputs, from the run worktree. It writes only downtime.

### F18 Evaluation: verdict core (edge-hypothesis §5.3, exact)
- **Value:** the pre-registered PASS / FAIL / INCONCLUSIVE / ABORTED verdict, computed reproducibly across implementations.
- **Dependencies:** F2. F18 is pure over ledger records; B0d inputs come from F19, and the P6 input from F16.

- **F18.AC1 [unit]** Conformance oracle.
  - The implementation reproduces every golden literal in `research/scripts/eval_reference.py` (E14) exactly for RNG outputs, and to 1e-6 otherwise:
    - `GOLDEN_RNG` and `GOLDEN_REJ`, including the rejection case n = 2^63 + 1
    - the percentile indices: 200 and 9,799 at 96%, 50 and 9,949 at 99%
    - `GOLDEN_TOY`, `GOLDEN_UNEQUAL`, `GOLDEN_DISTINCT` and `GOLDEN_DC`
    - `GOLDEN_FLATTEN` and `GOLDEN_D`
  - Each of the 10 E14 mutants, applied to the implementation, fails at least one test.
- **F18.AC2 [unit]** Sample S.
  - S is the first `eval.n_trades` shares by entry-fill time in `[t0, t0 + eval.calendar_cap_days + eval.extension_days)`. Ties are broken by client order ID, ascending.
  - Trade 301 is never in S, even when it closes first.
  - Refused, shadow and unexecutable signals are never trades.
- **F18.AC3 [unit]** `T_eval` and marking.
  - `T_eval = min(last evaluation close in S, t300 + eval.closeout_max_days)`. A flattened trade's evaluation close is its shadow exit.
  - Trades or shadows still open at the cap are marked at the recorded mid − taker fee − half-spread.
  - Funding counts through the last hourly funding ≤ `T_eval`.
  - A later real outcome is reported separately, and the stored verdict never changes.
- **F18.AC4 [unit]** Day clusters.
  - Clusters are transitive merged components (same coin and direction, closed intervals, touching counts, shadow exits for flattened trades).
  - A trade's cluster is the UTC day of the component's first entry. G is the number of distinct clusters.
  - This reproduces `GOLDEN_DC`.
- **F18.AC5 [unit]** Intervals.
  - `LB_r` and `UB_r` are the min and max of three intervals:
    - the iid t-interval, with n − 1 df
    - the day-cluster percentile bootstrap: B = `eval.bootstrap_b`, pooled mean, tags `bootR` and `bootD`, seeded with the 32 raw bytes of the run seed
    - the cluster-robust t-interval, with G − 1 df and the G/(G − 1) factor
  - Results are rounded half-even to 1e-6 before comparison.
  - A hex-text seed, or a seed that isn't exactly 32 bytes, is an error.
- **F18.AC6 [unit]** Precedence.
  - The order is: ABORTED → FAIL (F1/F2) → INCONCLUSIVE (P1) → INCONCLUSIVE (G < 5) → FAIL (F3) → PASS (P1–P6, P2b, P2c) → INCONCLUSIVE.
  - Over a generated grid of every boolean combination, with G ∈ {3, 4, 5, 6} and LB/UB ∈ {−0.000001, 0.000000, 0.000001}, the result equals `eval_reference.verdict` for 100% of cases.
  - The F2 boolean in that grid is the output of F18.AC11, never "at least one missed exit".
- **F18.AC7 [unit]** Immediate FAIL. Either of these before `T_eval` records FAIL at that moment, ends the run and pauses the bot:
  - an F1 breach: drawdown ≥ `eval.max_dd` at any mark, on either the actual or the shadow equity curve
  - an F2 breach under the missed-exit rule (F18.AC11)

  A missed exit that does not breach F2 leaves the run running.
- **F18.AC8 [unit]** P5 downtime.
  - Downtime is the union of: `process_down`, `data_gap` before resync, `access_degraded`, `disk_low`, manual `/pause`, and deploy-wait pauses.
  - `rule_blackout` and loss halts are excluded.
  - P5 holds iff downtime < `eval.max_downtime_fraction` of `[t0, T_eval]`. At exactly 2.000%, P5 fails.
- **F18.AC9 [unit]** P2b, P6 and the flatten rule.
  - P2b: Σ net USD over S > 0.
  - P6: the replay mean R over `[t0, T_eval]` and the paper mean R over S are both > 0 or both < 0. A zero on either side fails.
  - A flattened trade uses min(realised R, shadow R), and USD P&L from the same choice.
- **F18.AC10 [unit]** No interim gate statistics (edge-hypothesis §5.5 as amended by A3).
  - For an active run before `T_eval`, the evaluation API returns `not_before_T_eval` for: the gate mean R, any CI or bound, any D or B0d value, P2c, FR1–FR6, D6, the status of any gate condition, and any verdict.
  - Only counts and progress are served.
  - `/stats` (F14.AC9) never calls this API; its descriptive figures come from ledger aggregates.
- **F18.AC11 [unit]** Missed-exit rule (edge-hypothesis A3 is normative; its vectors supersede these where they differ).
  - Over the evaluation window, F2 holds iff the number of missed exits is > `eval.missed_exit_max_count`, **or** any missed exit's cost (F12.AC9), rounded half-even to 1e-6, is > `eval.missed_exit_max_cost_r`. An `uncomputable` cost counts as exceeding it.
  - F2 is recorded at the first moment it becomes true: the detection of the 4th missed exit, or the storing of a cost above 1R.
  - Boundaries:
    - 3 missed exits, each with cost 1.000000R → no F2
    - a 4th missed exit with cost 0.000000R → F2 at its detection time
    - one missed exit with cost 1.000001R → F2 at the moment its cost is stored
    - one missed exit with cost 1.0000004R (rounds to 1.000000) → no F2
  - **Gate values:** a trade in S with a missed exit enters R, D and P2b's USD sum at its gate R = min(actual, mirrored) and the matching USD, never at its actual values when those are better. Any other statistic follows A3.
  - **A bug never helps:** on a fixture where a late exit beat mirroring, mean gate R over S is lower than the mean computed with actual R, and never higher on any fixture.
  - If the E14 oracle gains A3 golden vectors, the implementation reproduces them exactly (F18.AC1).

### F19 B0d baseline and P2c inputs (edge-hypothesis §6.2, exact)
- **Value:** the gating test that the trades beat a direction-matched, random-time baseline. This is P2c, and it is non-removable.
- **Dependencies:** F4, F11 (its fill model is reused) and F18.

- **F19.AC1 [unit]** Draws. Start times come from `rng_uint` with tag `b0d`, counters (trade index in S, replication) and uniform ms over the admissible set. The draws reproduce `eval_reference.b0d_start` for the golden seed.
- **F19.AC2 [unit]** Admissibility. A start `t` is admissible only if all of these hold:
  - the coin is listed on core throughout `[t, t + hold_i + ack]`
  - a book exists within `baseline.dm_max_book_gap_s` of the entry and time-exit fills
  - there is no mid or mark gap over `baseline.dm_max_mid_gap_s`
  - `t` is not in a blackout
  - `t ∈ [t0, T_eval − hold_i]`

  A test with 10,000 draws finds 0 draws outside the set.
- **F19.AC3 [simulation]** Replication. Each replication:
  - uses the same risk per trade, with its ATR stop and TP from 1h candles that closed before `t`
  - fills at the book recorded at `t + paper.ack_delay_ms`, with its own size
  - pays taker fees on both legs and hourly funding
  - exits at SL or TP (trigger on mark) or at `hold_i`; a marked trade uses the marking formula
  - takes its R from fill prices only

  Evaluation test 10: when the mid jumps X bps after every leader fill, changing X changes `R_i` and leaves every `B̄_i` unchanged, and doubling `copyreplay.delay_ms` leaves `B̄_i` unchanged.
- **F19.AC4 [unit]** Missing windows.
  - A trade with less than `baseline.dm_min_admissible_hours` of admissible starts gets `D_i = min(R_i, 0, R_i − B̄_i^partial)`, using the 3-step chain. The step used is recorded.
  - When more than `baseline.dm_max_missing_share` of S (more than 30 trades) is missing a window, P2c fails.
  - This reproduces `GOLDEN_D`.
- **F19.AC5 [unit]** P2c.
  - P2c is `LB_r(D) > 0` on the same day clusters as P2, with tag `bootD`.
  - A config without `eval.baseline_gate`, or with it disabled, fails to load (non-removable, A1.4).
- **F19.AC6 [simulation]** Scale and determinism. 300 trades × `baseline.dm_reps` replications finish in ≤ 4 h on the PO's PC, and two runs give a byte-identical D vector.

### F20 Evaluation report and pre-run readiness report
- **Value:** every verdict comes with its go-live blockers and diagnostics, and the PO gets the pre-run kill checks before run 1.
- **Dependencies:** F16, F18 and F19.

- **F20.AC1 [unit]** The `T_eval` report contains all of the following:
  - **Verdict:** the verdict; each of P1–P6, P2b and P2c with its value; `LB_r`, `UB_r` and all three intervals for R and D; n and G.
  - **Secondary statistics:** S2, S3 (B0), S4 (B1, top 9 by raw ROI), S5, S6 (weekly blocks), R_maxrisk, FR1–FR6, K9 and the D6 checks.
  - **Execution:** decay(Δ) and edge lost per second, latency p50/p95/p99 per stage, mirror fidelity, and the exit-reason mix.
  - **Baseline detail:** the B0d mean, and the count of missing windows by step.
  - **Cross-day diagnostics:** the KM median hold, the midnight-crossing share, and the overlap-component CI with G_ov (labelled "degenerate" below 5, and "P2 fragile" when applicable).
  - **Flattened and marked trades:** the flattened count with realised-minus-shadow R, and the marked trades' later outcomes.
  - **Missed exits:** the count against `eval.missed_exit_max_count`, and for each one: share ID, leader, coin, case, lag, actual R, mirrored R, gate R and cost (F12.AC9).
  - **Outside S:** trades after the 300th, shown separately.
  - **Other baselines:** B0b, B2, B3 and B4, plus the shadow mean R labelled exploratory (H3).
- **F20.AC2 [unit]** Fragility boundaries.
  - FR1: without the top 5 R trades, mean ≤ 0.
  - FR2: without the leader with the largest ΣR, mean ≤ 0.
  - FR3: `mean(R_i − c_i)` ≤ 0.
  - FR4: win rate > 70% **and** payoff < 0.5.
  - FR5: mean R_maxrisk ≤ 0.
  - FR6: drop the day with the largest ΣR (earliest on a tie), then mean ≤ 0.

  Each fires at its boundary and not one step inside it.
- **F20.AC3 [unit]** D6 (edge-hypothesis §8.2). The check flags D6 when any of these holds:
  - decision agreement < `d6.min_decision_agreement`
  - median |ΔR| > `d6.max_median_abs_r_diff`
  - |mean ΔR| > `d6.max_mean_r_diff`
  - fill deviation median > `d6.max_median_fill_dev_bps` or p90 > `d6.max_p90_fill_dev_bps`
  - trade-count deviation > `d6.max_trade_count_dev`
- **F20.AC4 [unit]** Blocked PASS and go-live blockers.
  - A PASS with any of K9/S4, FR1–FR6 or D6 triggered, **or with at least one missed exit** in the run, is headed `PASS: live blocked pending PO review of <items>`. Missed exits are listed as `missed exit <share ID>: explain and fix`.
  - Every report, whatever the verdict, lists every missed exit as an open go-live blocker. The report offers no field or flag that clears one; clearing happens at /go-live with an explanation and a fix.
- **F20.AC5 [simulation]** Readiness report. It is built from the dry run, ≥ 7 days of recording, and the point-in-time replay. It states:
  - the recorder gap rate per coin, and the projected share of trades without an admissible B0d window
  - K1 (`kill.k1_min_trades`), K2 (`kill.k2_min_trades`), K6, K7 and K8, each as `triggered`, `not triggered` or `not evaluable (n = x)`
  - the latency summary (§4)
  - the tier table in force, with each coin's depth, volume and tier, and the tier-1, tier-2 and below-floor counts (F9.AC7)
  - archive health: compressed GB per day (mean and max), days archived and verified, local window size, the last verified ledger backup, and the projected monthly storage cost (F23)
- **F20.AC6 [simulation]** Reproducibility and honesty.
  - Regenerating either report from the same ledger gives byte-identical output.
  - Removing any trade record from the fixture changes the output. No outcome-based exclusion exists.

### F21 Integration, supervisor, 24h dry run and latency measurement
- **Value:** the whole pipeline runs unattended on the PO's Windows PC, proven by a 24h dry run and a 1-day latency measurement.
- **Dependencies:** F1–F20 and F23.

- **F21.AC1 [integration]** Supervisor.
  - One command starts every component in paper mode on Windows 10/11.
  - A ledger heartbeat is written every `ledger.heartbeat_interval_s`.
  - A crashed component restarts after `supervisor.restart_delay_s`.
  - More than `supervisor.max_restarts_per_hour` restarts in an hour means: stay down with opens refused, and alert.
  - A heartbeat gap over `feed.stale_after_s` (sleep, wake or freeze) is ledgered as downtime and triggers a resync.
- **F21.AC2 [simulation]** 24h dry run. The full pipeline runs in dry-run mode on live mainnet data for ≥ 24 h continuous, with:
  - 0 unhandled exceptions, 0 missed exits and 0 ledger verification failures
  - downtime < 2%
  - every Telegram command answered
  - process RSS at hour 24 ≤ 1.2 × RSS at hour 1
  - compressed recording written for the 24 h ≤ `recording.max_gb_per_day`
  - at least one finished UTC day archived and verified (F23.AC1) and one ledger backup verified (F23.AC4)

  0 missed exits is deliberately stricter than the run rule (F18.AC11): any missed exit in the dry run is a bug to fix before run 1.
- **F21.AC3 [simulation]** Latency measurement.
  - It runs for ≥ `latency.measure_hours` on the PO's connection, with n ≥ `latency.min_signals` signals, clock-offset corrected.
  - It reports p50/p95/p99 for each §4 stage, and the share of signals older than 1, 2, 3 and 5 s at decision.
  - If n is below `latency.min_signals`, the measurement is extended until it is reached.
- **F21.AC4 [integration]** No inbound surface (E4). The running engine opens 0 listening sockets, as a socket enumeration test confirms. Telegram uses outbound polling.
- **F21.AC5 [integration]** The full test suite passes on Windows 10/11 with the pinned Python and lockfile.

### F22 OKX lead-trader recorder (record-only, lowest priority)
- **Value:** collects fallback candidate data for a later epic, with no effect on the pre-registered run (H1 is Hyperliquid wallets only).
- **Dependencies:** F2.

- **F22.AC1 [integration]** With `okx.enabled` = true, public lead-trader endpoints are polled every `okx.poll_interval_s` and stored point-in-time.
- **F22.AC2 [unit]** OKX data never produces a signal, score, share or trade. A static import test and a runtime test confirm it.
- **F22.AC3 [unit]** Failure case: an endpoint error backs off and sends ≤ 1 alert per day, with 0 effect on any other component.

### F23 Recording archive, cloud offload and ledger backup (A10)
- **Value:** recording fits on the PO's ~100 GB of free disk, run data gets an off-site copy, and replay, B0d and evaluation still see every recorded day. Storage costs ≤ $5/month.
- **Dependencies:** F1 and F2, plus F4's day-partitioned files and store interface (F4.AC3, F4.AC7). The bucket is any S3-compatible store (Backblaze B2 or Cloudflare R2), reached over outbound HTTPS only.
- **Split rationale:** F4 was too big for one developer with this added. F4 keeps writing and the disk guard; F23 owns everything after a day is complete.

- **F23.AC1 [integration]** Daily upload and verification.
  - After a UTC day is `day_complete` (F4.AC7), every recording and leaderboard file for that day is uploaded, followed by a day manifest listing each object's path, bytes and sha256. The manifest goes last.
  - Each object is verified by reading it back (or its store-side checksum, where the store provides sha256) and comparing it with the local sha256.
  - A day becomes `archived` only when every object and the manifest verify. The ledger then gets `archive_verified` with the day and the manifest sha256.
  - Against an S3-compatible stub, a 1-day fixture is archived with 0 mismatches. With a stub that corrupts one object, the day stays not archived, the object is re-uploaded, and one alert is sent.
  - A normal day is archived ≤ `storage.upload_deadline_h` after 00:00 UTC.
- **F23.AC2 [integration]** Pruning (D2).
  - A local day is deleted only when it is `archived` **and** older than the newest `storage.local_retention_days` finished days.
  - A day that is not archived is never deleted, whatever its age and whatever the free disk.
  - The engine never deletes or overwrites a verified object, and never changes bucket lifecycle rules. The stub records 0 such calls over the whole test suite.
  - Fixture: 10 finished days, with days 1 and 2 not archived and retention 7. After pruning, days 1, 2 and 4–10 are local, and day 3 is deleted.
- **F23.AC3 [simulation]** Transparent reads.
  - Replay (F16), B0d (F19), evaluation and reports (F18, F20), reconstruction (F13) and tier computation (F9) read recordings through one store interface. It serves local files first; otherwise it downloads the day from the archive into `storage.cache_dir`, verifies each object's sha256 against the day manifest, then serves it.
  - The cache is bounded by `storage.cache_max_gb`, with least-recently-used eviction, and never evicts a file in use.
  - Reading a 3-day fixture through the interface gives byte-identical records whether the days are local or only in the archive.
  - End to end, once F16 and F19 exist (run in F21's integration suite): a 3-day replay run once fully local and once with all 3 days only in the archive gives byte-identical ledgers. The same holds for a B0d D vector (F19.AC6).
  - The point-in-time rule (F4.AC3) holds for archived data.
  - **Corruption (failure case):** a downloaded object whose sha256 does not match the manifest is never used. The read raises `archive_corrupt`, one alert is sent, and the calling batch job exits non-zero. It is never silently treated as a gap.
  - **Archive unreachable:** a read that needs a non-local day retries for `storage.read_retry_max_min`, then the batch job exits non-zero naming the day. It never proceeds with the day missing.
- **F23.AC4 [integration]** Ledger backup.
  - Daily at `storage.ledger_backup_time_utc`, the ledger is backed up to the bucket, fully or incrementally since the last verified backup.
  - It is encrypted on the PC with authenticated encryption, using a key from the environment, before upload. It is then verified by checksum, and `ledger_backup_verified` is ledgered with the head sequence number and head hash.
  - The uploaded bytes contain 0 occurrences of a canary record string planted in the ledger.
  - **Restore drill:** `archive restore-ledger --to <dir>` rebuilds a ledger that verifies (F2.AC1) with the same head sequence number and hash as the backup record.
  - A backup with a wrong key or a tampered object fails to restore with an error; it never yields a partial ledger.
- **F23.AC5 [unit]** Credentials and transport (E2, abuse case).
  - The endpoint, bucket, key ID, secret key and backup encryption key come only from the environment (F1.AC5). With canary values, 0 occurrences appear in logs, the ledger, Telegram payloads, exception traces, object names or object metadata.
  - A non-HTTPS endpoint fails config validation.
  - With any credential missing: recording continues locally, nothing is uploaded or pruned, one alert is sent per `storage.alert_interval_h`, `/status` shows `archive: not configured`, and `run start` refuses (F17.AC2).
- **F23.AC6 [integration]** Upload failure and backlog (failure case).
  - On an upload or verification failure, local data is kept, the upload is retried every `storage.retry_interval_min`, and one alert is sent per `storage.alert_interval_h` stating the backlog in days and GB.
  - Recording continues. Only the disk floor (F4.AC5) stops it.
  - Gaps caused by a floor stop count in the recorder gap statistics (F4.AC4) and in B0d admissibility under edge-hypothesis §14 item 8. They are never back-filled with synthetic data.
  - Trading, exits and the ledger are unaffected by any archive failure.
- **F23.AC7 [unit]** Storage budget.
  - Once a day, the projected monthly cost is computed as stored GB × `storage.price_usd_per_gb_month` + the month's operation count × `storage.price_usd_per_10k_ops` / 10,000. It is ledgered and shown in `/status` and the daily report.
  - When the projection reaches `storage.budget_alert_fraction` × `storage.monthly_budget_usd`, one alert per day is sent. Uploads continue (Assumption A21).
  - Fixture: 60 GB at $0.006/GB-month plus 100,000 operations at $0.004 per 10,000 → $0.40. At 700 GB → $4.24, which trips the 0.8 × $5 = $4.00 alert.

---

## 3. Config table

**Rules.**
- Every key must be present, because there are no code defaults (F1.AC1).
- **Max** is a hard ceiling compiled into code. Where safety needs a floor, **Min** is a hard floor, as for fees.
- "fixed" means Min = Max = Default.

**Source codes.**

| Code | Source |
|---|---|
| PO | `decisions.md` or `03-answers.md` |
| EH§ | `edge-hypothesis.md` |
| MC | `market-context.md` |
| BR | `brainstorm-domain-research.md` |
| BRF | `01-brief.md` |
| HL | exchange limit |
| PM | this spec, with an assumption ref where one applies |

**Flags.**

| Flag | Meaning |
|---|---|
| **FROZEN** | Pre-registered. It can change only by addendum before a run. |
| **CAL** | Calibrate once on pre-paper recorded data, then freeze before run 1. |
| **OF** | A prior; overfitting risk. Never tuned on paper-run data. |
| **VAL-S** | Validate with the PO's `hl_sample.py` `summary.json` (not yet available). |
| **VAL-L** | Validate with the 1-day latency measurement (F21.AC3). |
| **VAL-R** | A prior. Validate against ≥ 7 days of our own recordings (shown in the readiness report, F20.AC5) and adjust before the config is frozen for run 1. |

### 3.1 Platform, storage, supervisor
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `mode` | Trading mode | enum | paper | paper | paper (live/testnet refused in this epic) | PO, A10 |
| `storage.ledger_dir` | Ledger location, outside any worktree | path | required | – | – | PM (EH 5.1 A2.2) |
| `storage.recordings_dir` | Recordings location, outside any worktree | path | required | – | – | PM |
| `storage.cache_dir` | Download cache for archived days, outside any worktree | path | required | – | – | PM (A10) |
| `storage.upload_delay_min` | Wait after 00:00 UTC before a day is closed and uploaded | min | 15 | 5 | 120 | PM (A10) |
| `storage.upload_deadline_h` | A normal day is archived within this after 00:00 UTC | h | 6 | 1 | 24 | PM (A10) |
| `storage.local_retention_days` | Rolling window of finished days kept locally | days | 7 | 2 | 30 | PO (A10) |
| `storage.max_unarchived_days` | `run start` refuses if an older finished day is not archived | days | 2 | 1 | 7 | PM (A21) |
| `storage.cache_max_gb` | Download cache size | GB | 20 | 2 | 50 | PM (A10) |
| `storage.read_retry_max_min` | Retry window for an archive read before the batch job fails | min | 30 | 1 | 240 | PM |
| `storage.retry_interval_min` | Upload and backup retry period | min | 15 | 1 | 120 | PM |
| `storage.alert_interval_h` | Throttle for archive and backup alerts | h | 6 | 1 | 24 | PM |
| `storage.ledger_backup_time_utc` | Daily encrypted ledger backup | HH:MM | 00:30 | – | – | PM (A10) |
| `storage.monthly_budget_usd` | Object-storage budget | USD/month | 5 | 0 | 5 | PO (A10) |
| `storage.budget_alert_fraction` | Projected cost share that alerts | fraction | 0.8 | 0.1 | 1.0 | PM (A21) |
| `storage.price_usd_per_gb_month` | Provider storage price, for the projection | USD/GB-month | 0.006 (B2; 0.015 if R2) | > 0 | – | PM (A10) |
| `storage.price_usd_per_10k_ops` | Provider operation price, for the projection | USD | 0.004 | 0 | – | PM (A10) |
| `clock.offset_interval_s` | Clock-offset re-estimation period | s | 600 | 60 | 3600 | PM (B2) |
| `clock.max_offset_uncertainty_ms` | Above this, entries pause | ms | 100 | 10 | 500 | PM · VAL-L |
| `clock.max_estimate_age_s` | Maximum age of the offset estimate | s | 1800 | 600 | 3600 | PM |
| `ledger.heartbeat_interval_s` | Liveness heartbeat | s | 10 | 1 | 60 | PM |
| `supervisor.restart_delay_s` | Delay before restarting a crashed component | s | 30 | 5 | 120 | PM |
| `supervisor.max_restarts_per_hour` | Restart cap before staying down | count | 5 | 1 | 10 | PM |

### 3.2 Hyperliquid client and feeds
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `hl.rest_weight_budget_per_min` | Our REST weight budget | weight/min | 900 | 100 | 1100 (HL limit 1,200) | MC 2.3 |
| `hl.scoring_weight_share` | Share of the budget available to scoring | fraction | 0.5 | 0.1 | 0.8 | MC 2.3 |
| `hl.weight_userRole` / `hl.weight_portfolio` | Assumed weights | weight | 60 / 20 | 20 / 20 | – | EH E8 |
| `hl.rest_timeout_s` | REST timeout | s | 10 | 2 | 30 | PM |
| `hl.retry_max` | Retries per request | count | 5 | 0 | 8 | PM (B4) |
| `hl.backoff_base_s` / `hl.backoff_max_s` | Exponential backoff range | s | 1 / 60 | 1 / 10 | 10 / 300 | PM |
| `hl.ws_max_unique_users` | Distinct WS users | users | 10 | 1 | 10 (HL) | MC 2.3 |
| `hl.ws_max_new_conns_per_min` | New WS connections | per min | 20 | 1 | 30 (HL) | MC 2.3 |
| `hl.ws_ping_interval_s` | Ping cadence | s | 20 | 5 | 50 | PM (MC: heartbeat unconfirmed) |
| `hl.ws_reconnect_backoff_max_s` | Maximum reconnect backoff | s | 30 | 5 | 120 | BR |
| `feed.stale_after_s` | No message → stale; entries pause | s | 30 | 5 | 60 | BR · VAL-L |
| `access.degraded_error_count` | 403/451 count that trips `access_degraded` | count | 3 | 1 | 20 | PM (PO K10) |
| `access.degraded_window_min` | Detection window | min | 5 | 1 | 30 | PM |
| `access.degraded_min_success_rate` | Below this → degraded | fraction | 0.5 | 0.1 | 0.9 | PM |
| `access.recover_min` | Healthy minutes needed to clear | min | 10 | 1 | 60 | PM |
| `follow.clearinghouse_poll_s` | Leader account-value poll | s | 60 | 10 | 300 | PM |
| `follow.max_leader_av_age_s` | Oldest leader account value usable for sizing | s | 300 | 60 | 900 | PM |

### 3.3 Recorder
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `recording.markets` | Recorded markets | list | core + HIP-3 | – | – | PO |
| `recording.max_coins` | Recording universe cap | coins | 250 | 10 | 400 | PM (A10; 1,000 subscriptions per IP) |
| `recording.universe_lookback_days` | Coins traded by followed or candidate wallets in the last N days | days | 30 | 7 | 90 | PM |
| `recording.l2_levels` | Book levels per side | levels | 10 | 5 | 20 | PM (A10) |
| `recording.l2_interval_ms` | Minimum L2 snapshot rate | ms | 2000 | 500 | 4000 (must stay < 5 s B0d rule) | PM |
| `recording.asset_ctx_interval_s` | Mark/oracle/funding/OI cadence | s | 60 | 10 | 300 | MC 5 |
| `recording.leaderboard_interval_min` | Leaderboard snapshot period | min | 60 | 15 | 60 | PO |
| `recording.disk_check_interval_s` | Free-disk check period | s | 60 | 10 | 300 | PM (A10) |
| `recording.disk_alert_free_gb` | Free-disk alert threshold; must exceed the floor | GB | 20 | 6 | – | PM (A10) |
| `recording.disk_floor_free_gb` | Hard floor: recording stops, opens and adds refused; room kept for the ledger | GB | 8 | 5 (hard floor) | – | PM (A10, A18) |
| `recording.disk_resume_margin_gb` | Free space above the floor needed to resume recording | GB | 2 | 1 | 20 | PM |
| `recording.max_gb_per_day` | Compressed recording budget, checked in the 24h dry run | GB/day | 1.5 | 0.1 | 5 | PM (A10) · VAL-R |

### 3.4 Scoring and selection (EH §9.1, §10)
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `scoring.candidates_k` | Candidates scored | wallets | 200 | 50 | 500 | BRF · VAL-S |
| `scoring.interval_min` | Scoring cycle | min | 60 | 15 | 1440 | BRF |
| `scoring.window_days` | Fill window | days | 180 | 90 | 365 | BR · OF |
| `scoring.dsr_min_daily_days` | Minimum daily-resolution days (T) | days | 60 | 30 | – | EH · OF |
| `scoring.stale_input_mult` | Input older than mult × interval → ineligible | × | 2 | 1 | 4 | EH 10.1 |
| `gate.min_account_age_days` | G1 | days | 180 | 90 | – | BR · OF |
| `gate.min_round_trips` | G2 | count | 150 | 50 | – | BR · OF · VAL-S |
| `gate.min_fill_span_days` | G3 | days | 60 | 30 | – | EH · OF · VAL-S |
| `gate.min_positive_blocks` / `gate.n_blocks` / `gate.block_days` | G4 | count / count / days | 4 / 6 / 30 | 1 / 2 / 7 | n_blocks / 12 / 90 | EH · OF |
| `gate.max_drawdown` | G5 | fraction | 0.35 | 0.05 | 0.50 | BR · OF |
| `gate.min_profit_factor` | G6 | ratio | 1.3 | 1.0 | – | BR · OF |
| `gate.min_dsr_prob` | G7 | prob | 0.95 | 0.50 | 0.99 | BR |
| `gate.dsr_n_trials` | DSR trial count | count | 15000 | = `scoring.candidates_k` | – | MC 2.1 |
| `gate.min_median_hold_min` | G8 floor | min | 15 | 5 | – | BR · OF · VAL-S |
| `gate.hold_latency_mult` | G8: hold ≥ mult × p95 latency | × | 20 | 5 | – | BR · VAL-L |
| `gate.max_top_trade_share` | G9 | fraction | 0.25 | 0.05 | 1.0 | BR · OF |
| `gate.max_top_asset_share` | G9 | fraction | 0.50 | 0.10 | 1.0 | BR · OF |
| `gate.min_copy_edge_ratio` | G10 | ratio | 3.0 | 1.0 | – | BR · OF |
| `gate.min_account_value_usd` | G11 | USD | 10000 | 1000 | – | EH · OF · VAL-S |
| `gate.min_executable_share` | G12 | fraction | 0.50 | 0.10 | 1.0 | EH · OF · VAL-S |
| `gate.max_maker_share` | G13 | fraction | 0.70 | 0.10 | 1.0 | EH · OF · VAL-S |
| `gate.max_current_drawdown` | G15 | fraction | 0.20 | 0.05 | 0.50 | EH · OF |
| `gate.exclude_roles` | G13 roles | list | vault, agent, missing | – | – | EH |
| `gate.exclude_addresses` | G13 addresses | list | [HLP vault address] | – | – | EH |
| `blowup.max_adds_while_losing_share` / `blowup.min_adds` | BU1 | fraction / count | 0.20 / 10 | 0 / 1 | 1 / – | BR · OF |
| `blowup.max_size_after_loss_ratio` / `blowup.min_each` | BU2 | ratio / count | 1.5 / 20 | 1.0 / 5 | – | EH · OF |
| `blowup.skew_win_rate` / `blowup.skew_loss_mult` | BU3 | fraction / × | 0.85 / 3.0 | 0.5 / 1 | 1 / – | BR · OF |
| `blowup.max_worst_to_median_loss` / `blowup.min_losses` | BU4 | ratio / count | 10 / 10 | 2 / 3 | – | BR · OF |
| `blowup.hidden_dd_mult` / `blowup.hidden_dd_floor` | BU5 | ratio / fraction | 2.0 / 0.15 | 1 / 0 | – / 1 | EH · OF |
| `blowup.max_median_eff_leverage` | BU7 | × | 10 | 1 | 50 | EH · OF |
| `blowup.max_open_unrealized_loss` | BU8 | fraction of account value | 0.10 | 0.01 | 1.0 | EH · OF |
| `blowup.any_liquidation` | BU6 | bool | true | – | – | EH |
| `score.weights` | dsr_excess, copy_mean_r, pos_blocks, max_dd, recent_sr, executable | each 0–1, Σ = 1 | 0.30, 0.25, 0.15, 0.15, 0.10, 0.05 | 0 each | 1 each | EH · OF |
| `score.anchors` | lo/hi per component (EH 10.4) | mixed | 0/0.15; 0/0.30R; 0.5/1.0; 0.35/0.05; 0/0.30; 0.5/1.0 | lo ≠ hi | – | EH · OF |
| `score.shrink_k_trades` | Shrinkage of copy_mean_r | trades | 100 | 0 | – | EH · OF |
| `score.shrink_k_days_recent` | Shrinkage of recent_sr | days | 30 | 0 | – | EH · OF |
| `select.join_rank` / `select.drop_rank` | Hysteresis | rank | 8 / 15 | 1 / join + 1 | – | BRF · OF |
| `select.join_confirm_cycles` / `select.drop_confirm_cycles` | Confirmations | cycles | 2 / 2 | 1 / 1 | 6 / 6 | EH |
| `select.min_follow_hours` | Minimum follow before a rank drop | h | 24 | 1 | – | BRF |
| `select.min_followed` | Target minimum followed | count | 5 | 1 | = max_followed | BRF · VAL-S |
| `select.max_followed` | Followed wallets | count | 9 | 1 | 9 (WS users − 1) | PO |
| `select.backfill_max_hours` | Initial backfill deadline | h | 24 | 1 | 48 | PO |
| `select.swap_margin` | Score margin for a swap | score units | 0.10 | 0 | 1 | EH · OF |
| `select.max_swaps_per_cycle` | Swaps per cycle | count | 1 | 0 | 1 | EH |
| `select.max_cycle_duration_min` | Longer cycle → keep the previous set | min | 45 | 10 | = interval | PM |
| `leader_pause.max_copy_dd` | Leader pause: copy drawdown | fraction of the leader allocation | 0.10 | 0.02 | 0.50 | BR · OF |
| `leader_pause.max_consec_losses` | Leader pause: consecutive copy losses | count | 5 | 2 | 20 | BR · OF |
| `risk.leader_allocation_fraction` | Leader allocation, the base of `max_copy_dd` | fraction of equity | 0.30 | 0.05 | 0.50 | BR (per-leader 30%) |
| `copyreplay.delay_ms` | Copy-replay delay | ms | measured p95, else 3000 | 250 | 5000 | EH · CAL · VAL-L |
| `copyreplay.half_spread_bps` | Copy-replay spread fallback (tier 1 / tier 2; "majors / alts" in EH, A17) | bps | recorded, else 2 / 8 | 2 / 8 (floor) | – | EH · CAL |

### 3.5 Markets, filter, calendar
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `markets.allowed_dexes` | Tradable dexes | list | core | core | core (fixed) | PO · FROZEN |
| `tiers.lookback_days` | Recorded window for the tier metrics | days | 7 | 3 | 30 | PM (A6) · VAL-R |
| `tiers.recompute_interval_h` | Tier recompute period outside a run | h | 24 | 1 | 168 | PM (A6) |
| `tiers.max_age_h` | Oldest usable tier table outside a run, and at run start | h | 48 | 2 | 336 | PM (A6) |
| `tiers.depth_band_pct` | Band around mid for the depth metric | % | 0.5 | 0.1 | 2.0 | PM (A6) · VAL-R |
| `tiers.tier1_min_depth_usd` | Tier 1: median min-side depth within the band; must be ≥ the floor value | USD | 1,000,000 | = floor value | – | PM (A6) · VAL-R · OF |
| `tiers.tier1_min_volume_usd` | Tier 1: median 24h notional volume; must be ≥ the floor value | USD | 200,000,000 | = floor value | – | PM (A6) · VAL-R · OF |
| `tiers.floor_min_depth_usd` | Tradable floor: median min-side depth within the band | USD | 50,000 | 20,000 (hard floor) | – | PM (A6) · VAL-R · OF |
| `tiers.floor_min_volume_usd` | Tradable floor: median 24h notional volume | USD | 10,000,000 | 2,000,000 (hard floor) | – | PM (A6) · VAL-R · OF |
| `tiers.min_coverage_fraction` | Recorded coverage of the lookback needed to be tiered | fraction | 0.8 | 0.5 | 1.0 | PM (A6) |
| `filter.max_signal_age_ms` | Signal age cut-off | ms | 5000 | 500 | 5000 | PO D7 · VAL-L |
| `filter.max_slippage_pct_tier1` | Adverse slippage vs the leader fill, tier 1 | % | 0.30 | 0.05 | 0.30 | PO D7, A6 |
| `filter.max_slippage_pct_tier2` | Same, tier 2 | % | 0.80 | 0.10 | 0.80 | PO D7, A6 |
| `filter.max_spread_pct_tier1` | Spread, tier 1 | % | 0.10 | 0.01 | 0.30 | BR · CAL |
| `filter.max_spread_pct_tier2` | Spread, tier 2 | % | 0.30 | 0.02 | 0.80 | BR · CAL |
| `filter.max_depth_share` | Order / depth within the band | fraction | 0.01 | 0.001 | 0.05 | BR |
| `filter.depth_band_pct` | Depth band around mid | % | 0.5 | 0.1 | 2.0 | BR |
| `filter.max_price_age_ms` | Book or mark staleness | ms | 2000 | 250 | 5000 | BR (B1) |
| `filter.vol_window_h` | Realised-vol window | h | 24 | 4 | 72 | PM · CAL |
| `filter.vol_lookback_days` | Percentile lookback, 1h candles | days | 90 | 30 | 200 (candle cap) | PM · CAL |
| `filter.vol_halving_percentile` | Size-halving threshold | percentile | 90 | 50 | 99 | PO D10 · PM · CAL · OF |
| `filter.vol_size_mult` | Size multiplier in high vol | × | 0.5 | 0.1 | 1.0 (never raises size) | PO D10 |
| `filter.trend.mode` | Trend rule | enum | record_only | – | – | PM (A5) · CAL |
| `filter.trend.ema_period_h` | Trend EMA on 1h | h | 50 | 10 | 200 | PM · CAL · OF |
| `filter.trend.min_aligned_atr` | Veto if (close − EMA)·dir / ATR < x | ATR | unset (record_only) | −5 | 5 | PM · CAL · OF |
| `filter.funding.mode` / `filter.funding.max_adverse_rate_per_h` | Funding-extreme rule | enum / fraction per h | record_only / unset | – / 0 | – / 0.04 | MC 4 · CAL · OF |
| `filter.oi_drop.mode` / `filter.oi_drop.max_drop_pct_24h` | OI-collapse rule | enum / % | record_only / unset | – / 5 | – / 90 | MC 4 · CAL · OF |
| `filter.premium.mode` / `filter.premium.max_abs_pct` | Mark–oracle premium rule | enum / % | record_only / unset | – / 0.05 | – / 10 | MC 4 · CAL · OF |
| `shadow.enabled` | Shadow outcomes for refused opens | bool | true | – | – | BRF (H3) |
| `calendar.file` | Macro calendar data input | path | `data/inputs/macro_calendar` | – | – | BRF |
| `calendar.timezone` | Event time zone | tz | America/New_York | fixed | fixed | MC 3.1 |
| `calendar.blocking_classes` | Classes that block | list | FOMC, CPI, PCE, NFP | – | – | PO |
| `calendar.window_fomc_min` | Before / after an FOMC decision | min | −30 / +60 | 0 | 240 | PO D10 |
| `calendar.window_tier1_min` | Before / after CPI, PCE, NFP | min | −15 / +30 | 0 | 240 | PO D10 |
| `calendar.min_coverage_days` | Required forward coverage | days | 67 | 67 | 120 | PM (60 + 7-day run cap) |

### 3.6 Risk, sizing, exits
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `risk.per_trade_fraction` | Initial risk per share | fraction of equity | 0.005 | 0.001 | 0.01 | PO · FROZEN |
| `risk.max_share_risk_fraction` | Share open risk after adds | fraction of equity | 0.01 | 0.005 | 0.02 | PM (A7) |
| `risk.max_total_open_risk_fraction` | Portfolio open risk | fraction of equity | 0.05 | 0.005 | 0.10 | PM (A7) |
| `risk.max_symbol_open_risk_fraction` | Per-coin open risk | fraction of equity | 0.015 | 0.005 | 0.03 | BR |
| `risk.max_btc_bucket_open_risk_fraction` | BTC-correlated, same direction | fraction of equity | 0.03 | 0.005 | 0.05 | BR |
| `risk.btc_bucket_corr_threshold` | Bucket membership | correlation | 0.6 | 0.3 | 0.9 | PM (A7) |
| `risk.btc_bucket_corr_window_days` | Correlation window, 1h returns | days | 30 | 7 | 90 | PM |
| `risk.max_leader_open_risk_fraction` | Per-leader open risk | fraction of equity | 0.015 | 0.005 | 0.03 | BR (30% of total) |
| `risk.max_open_positions` | Concurrent merged positions | count | 10 | 1 | 10 | BRF |
| `risk.max_position_notional_equity_mult` | Notional per merged position | × equity | 1.0 | 0.1 | 3.0 | PM (A3) |
| `risk.leverage_min` | Lowest leverage tried by the automatic choice | × | 1 | 1 | 3 | PO (A2) |
| `risk.max_leverage_alt` | Ceiling for coins not in the high-leverage list | × | 5 | 1 | 5 | PO D3, A2 |
| `risk.max_leverage_high_tier` | Ceiling for coins in `risk.high_leverage_coins` | × | 10 | 1 | 10 | PO D3, A2 |
| `risk.high_leverage_coins` | Coins allowed up to the high-tier ceiling | list | BTC, ETH, SOL | – | subset of {BTC, ETH, SOL} (compiled) | PO (A2) |
| `risk.min_liq_distance_stop_mult` | Liquidation distance ≥ mult × stop distance, every share | × | 3 | 3 (hard floor) | – | PO (A2) |
| `risk.daily_loss_limit` | Daily halt | fraction of opening equity | 0.02 | 0.005 | 0.05 | PO D6 |
| `risk.weekly_loss_limit` | Weekly halt | fraction of opening equity | 0.05 | 0.01 | 0.10 | PO D6 |
| `risk.max_orders_per_min` | Order rate | orders/min | 30 | 1 | 60 | PM (A3) |
| `sizing.min_order_usd` | Exchange minimum notional | USD | 10 | 10 | – | MC 1.1 |
| `sizing.partial_below_min_action` | Partial below $10 | enum | skip_and_log | fixed | fixed | PO · FROZEN |
| `sizing.close_all_if_remainder_below_min` | Remainder below $10 → close all | bool | true | fixed | fixed | PO · FROZEN |
| `paper.wallet_usd` | Paper wallet | USD | 300 | fixed | fixed | PO · FROZEN |
| `live.min_wallet_usd` | Future live floor (not used in this epic) | USD | 300 | 300 | – | PO |
| `exits.stop_atr_mult` | Initial stop | × ATR | 2.0 | 1.0 | 4.0 | BR · EH (V3/V4) · OF |
| `exits.atr_period` / `exits.atr_candle_interval` | ATR definition | bars / interval | 14 / 1h | 5 / – | 50 / – | BR |
| `exits.tp_enabled` | Take-profit on | bool | true | – | – | PM (A1; V5 = false) |
| `exits.tp1_r` / `exits.tp1_fraction` | Partial TP | R / fraction | 2.0 / 0.5 | 0.5 / 0.1 | 10 / 1.0 | BR · PM (A1) · OF |
| `exits.trail_start_r` / `exits.trail_atr_mult` | Trailing stop | R / × ATR | 1.0 / 2.0 | 0.25 / 0.5 | 5 / 5 | BR · PM (A1) · OF |
| `exits.missed_exit_max_lag_s` | Missed-exit threshold | s | 60 | 10 | 120 | PM (A4) |
| `exits.retry_interval_s` / `exits.alert_after_s` | Exit retry and alert | s | 1 / 10 | 1 / 5 | 5 / 60 | PM |
| `reconcile.interval_s` | Leader reconciliation | s | 300 | 60 | 600 | PM (A7, C4) |

### 3.7 Paper costs and restart
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `cost.taker_fee_bps` | Taker fee | bps | 4.5 | 4.5 (floor) | 20 | MC 1.1 |
| `cost.maker_fee_bps` | Maker fee (not used; no maker fills) | bps | 1.5 | 1.5 | 20 | MC |
| `cost.funding_accrual` | Funding method | enum | hourly_actual | fixed | fixed | PO |
| `paper.ack_delay_ms` | Simulated order ack | ms | 1000 | 500 (floor) | 5000 | MC 2.4 · CAL |
| `paper.max_book_age_ms` | Oldest book usable for a fill | ms | 5000 | 1000 | 5000 | EH 6.2 |
| `paper.meta_refresh_min` | Tick/lot/leverage refresh | min | 60 | 5 | 1440 | PM |
| `cost.fallback_half_spread_bps` | Tier 1 / tier 2 (EH "majors / alts", A17) | bps | 2 / 8 | 2 / 8 (floor) | – | EH 6.3 |
| `cost.fallback_half_spread_mult` | × recorded median | × | 1.5 | 1.5 (floor) | – | EH 6.3 |
| `cost.fallback_delay_slippage_bps` | Tier 1 / tier 2 (EH "majors / alts", A17) | bps | 5 / 15 | 5 / 15 (floor) | – | EH 6.3 |
| `restart.max_reconstruct_gap_h` | Longest reconstructable gap | h | 72 | 1 | 84 (1m candle cap) | MC 2.2 |
| `restart.candle_interval` | Reconstruction candles | interval | 1m | fixed | fixed | MC 2.2 |

### 3.8 Telegram, reports, LLM, OKX, latency
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `telegram.allowed_user_id` | PO user | int | required | – | – | BRF |
| `telegram.control_chat_id` / `telegram.alerts_chat_id` | Chats | int | required | – | – | BRF |
| `telegram.min_edit_interval_s` | Edits per message | s | 5 | 3 | 60 | PM (Q22) |
| `telegram.max_msgs_per_min_per_chat` | Send rate | msg/min | 20 | 1 | 20 | PM (Telegram limit) |
| `telegram.queue_max_messages` / `telegram.queue_max_age_h` | Outage queue | count / h | 1000 / 24 | 10 / 1 | 10000 / 72 | PM |
| `telegram.pin_max_attempts` / `telegram.pin_lockout_min` | PIN lockout | count / min | 3 / 15 | 1 / 5 | 5 / 1440 | PM (A12) |
| `telegram.unauthorized_alert_interval_min` | Alert throttle | min | 10 | 1 | 60 | PM |
| `report.daily_time_utc` / `report.weekly_time_utc` | Report times | HH:MM | 00:05 / Mon 00:10 | – | – | PM (A13) |
| `report.disclaimer` | Report footer | text | "Paper trading. Not investment advice. Past results do not guarantee future results." | – | – | BRF |
| `report.weekly_block_days` | S6 blocks | days | 7 | fixed | fixed | EH |
| `llm.enabled` | Why-text on | bool | true | – | – | BRF |
| `llm.monthly_budget_usd` | Hard spend cap | USD/month | 5 | 0 | 20 | BRF · PM (A9) |
| `llm.timeout_s` | LLM timeout | s | 20 | 1 | 30 | PM (F1 invariant) |
| `llm.max_output_chars` | Output length | chars | 600 | 100 | 1500 | PM |
| `llm.fallback` | Offline fallback | enum | ollama | – | – | BRF |
| `llm.price_usd_per_1k_tokens` | Spend accounting (input / output) | USD | model price, set at build | >0 | – | PM |
| `okx.enabled` / `okx.poll_interval_s` | OKX recorder | bool / s | false / 60 | – / 30 | – / 3600 | BRF · PM (A8) |
| `latency.measure_hours` / `latency.min_signals` | Latency measurement | h / count | 24 / 100 | 24 / 50 | – | BRF |

### 3.9 Replay, run and evaluation (EH §9.2; FROZEN unless noted)
| Key | Meaning | Unit | Default | Min | Max (hard ceiling) | Source |
|---|---|---|---|---|---|---|
| `replay.max_variants` | Pre-paper variant budget | count | 8 | fixed | fixed | EH 5.8 · FROZEN |
| `replay.sensitivity_cost_mults` / `replay.sensitivity_delays_s` | Sensitivity runs | list | 1.5, 2.0 / 1, 3, 5 | – | – | EH 5.8 |
| `eval.sample_basis` | Sample basis | enum | opened | fixed | fixed | PO · FROZEN |
| `eval.n_trades` | Sample size | trades | 300 | fixed | fixed | PO · FROZEN |
| `eval.calendar_cap_days` / `eval.extension_days` | Run length | days | 30 / 30 | fixed | fixed | PO · FROZEN |
| `eval.closeout_max_days` | Close-out cap after t300 | days | 7 | fixed | fixed | EH (PO-ack) · FROZEN |
| `eval.ci_level_run1` / `eval.ci_level_run2` | CI levels | level | 0.96 / 0.99 | fixed | fixed | EH (PO-ack) · FROZEN |
| `eval.max_runs` | Paper runs | runs | 2 | fixed | fixed | PO · FROZEN |
| `eval.ci_method` | min of {iid t, day-cluster bootstrap, day-cluster CR t (G−1 df)} | enum | min3 | fixed | fixed | EH (PO-ack) · FROZEN |
| `eval.cluster_key` | UTC day of the merged component's first entry (transitive) | enum | merged_first_entry_day | fixed | fixed | EH · FROZEN |
| `eval.min_day_clusters` | G minimum | clusters | 5 | fixed | fixed | EH (PO-ack) · FROZEN |
| `eval.bootstrap_b` | Bootstrap resamples | count | 10000 | fixed | fixed | EH · FROZEN |
| `eval.bootstrap_seed` | 32 CSPRNG bytes at run start, stored as hex, consumed raw | bytes | generated | fixed | fixed | EH A2.7 · FROZEN |
| `eval.bootstrap_statistic` | Pooled trade mean | enum | pooled_mean | fixed | fixed | EH · FROZEN |
| `eval.rng` | SHA-256 counter with rejection | enum | sha256_counter_rejection | fixed | fixed | EH · FROZEN |
| `eval.percentile_index` | ⌊B·(100−L)/200⌋; UB at B−1−index | enum | floor_index | fixed | fixed | EH · FROZEN |
| `eval.gate_round_dp` | Rounding of LB/UB | dp | 6 | fixed | fixed | EH · FROZEN |
| `eval.flatten_gate_rule` | min(realised, shadow); shadow exit = evaluation close | enum | min_realised_shadow | fixed | fixed | EH A2.1 · FROZEN |
| `eval.require_clean_engine_tree` | Dirty → refuse | bool | true | fixed | fixed | EH A1.2 · FROZEN |
| `eval.engine_path_manifest` | Manifest path | path | `engine-path-set.txt` | fixed | fixed | EH A2.2 · FROZEN |
| `eval.run_worktree_pinned` | Detached worktree at the run commit | bool | true | fixed | fixed | EH A2.2 · FROZEN |
| `eval.run_record_env_hashes` | Package list + data inputs | list | packages, data_inputs | fixed | fixed | EH A2.2 · FROZEN |
| `eval.deploy_policy` | Ruling required; logic changes abort by default | enum | auditor_ruling_required | fixed | fixed | EH A1.2 · FROZEN |
| `eval.require_usd_pnl_positive` | P2b | bool | true | fixed | fixed | PO · FROZEN |
| `eval.baseline_gate` | B0d lower-bound gate, non-removable | enum | direction_matched_random_time | fixed | fixed | PO + EH · FROZEN |
| `eval.max_dd` / `eval.mark_interval_s` | P3 threshold and mark cadence (also the risk pause) | fraction / s | 0.15 / 60 | fixed | fixed | PO · FROZEN |
| `eval.max_downtime_fraction` | P5 | fraction | 0.02 | fixed | fixed | PO · FROZEN |
| `eval.show_interim_stats` | Interim **gate** statistics: CI, D/P2c, FR, condition status, verdict preview. `/stats` descriptive figures are not gate statistics (F14.AC9). | bool | false | fixed | fixed | PO · EH A3 · FROZEN |
| `eval.missed_exit_max_count` | F2 fires when missed exits exceed this | count | 3 | fixed | fixed | PO (A4) · EH A3 · FROZEN |
| `eval.missed_exit_max_cost_r` | F2 fires when any single missed exit costs more than this versus mirroring | R | 1.0 | fixed | fixed | PO (A4) · EH A3 · FROZEN |
| `baseline.dm_costs` | Fees + own-time book + own ack drift + funding; no decay; R from fills | enum | own_time_no_decay | fixed | fixed | EH A1.1/A2.3 · FROZEN |
| `baseline.dm_min_admissible_hours` / `baseline.dm_max_missing_share` | Missing-window rule | h / fraction | 24 / 0.10 | fixed | fixed | EH · FROZEN |
| `baseline.dm_missing_rule` | min(R, 0, R − B̄_partial) with the 3-step chain | enum | min_r_0_partial | fixed | fixed | EH A2.3 · FROZEN |
| `baseline.dm_max_book_gap_s` / `baseline.dm_max_mid_gap_s` | Admissibility | s | 5 / 60 | fixed | fixed | EH · FROZEN |
| `baseline.dm_reps` / `baseline.random_reps` | Replications | count | 1000 / 1000 | fixed | fixed | EH · FROZEN (dm) |
| `baseline.top_roi_n` | B1 size | wallets | 9 | fixed | fixed | EH · FROZEN |
| `fragility.top_k_trades` / `fragility.drop_best_day_clusters` / `fragility.cost_stress_mult` | FR1 / FR6 / FR3 | count / count / × | 5 / 1 / 2.0 | fixed | fixed | EH · FROZEN |
| `decay.deltas_s` | Decay horizons | s | 0.25, 0.5, 1, 2, 3, 5, 10, 30, 60, 300 | – | – | EH |
| `data.paid_s3` | Paid S3 data | bool | false | fixed | fixed | PO |
| `d6.min_decision_agreement` | D6 | fraction | 0.90 | fixed | fixed | EH 8.2 |
| `d6.max_median_abs_r_diff` / `d6.max_mean_r_diff` | D6 | R | 0.05 / 0.10 | fixed | fixed | EH 8.2 |
| `d6.max_median_fill_dev_bps` / `d6.max_p90_fill_dev_bps` | D6 | bps | 3 / 10 | fixed | fixed | EH 8.2 |
| `d6.max_trade_count_dev` | D6 | fraction | 0.10 | fixed | fixed | EH 8.2 |
| `kill.k1_min_trades` / `kill.k2_min_trades` | K1 / K2 sample floors | trades | 100 / 150 | fixed | fixed | EH 7 |
| `kill.k6_decay_share` | K6 | fraction | 0.50 | fixed | fixed | EH 7 |
| `kill.k7_min_eligible` / `kill.k7_cycle_share` | K7 | count / fraction | 5 / 0.50 | fixed | fixed | EH 7 |
| `kill.k8_unexecutable_share` | K8 | fraction | 0.50 | fixed | fixed | EH 7 |

**Values that the PO's `hl_sample.py` run must validate (VAL-S).** These are all research priors today:
- `scoring.candidates_k` and `select.min_followed`
- `gate.min_round_trips`, `gate.min_fill_span_days`, `gate.min_median_hold_min`, `gate.min_account_value_usd`, `gate.min_executable_share` and `gate.max_maker_share`

The quant-researcher reviews them against `summary.json` before the config is frozen. A change goes into the config before run 1; it never needs an addendum, because none of these keys is FROZEN.

**Values that the latency measurement must validate (VAL-L):** `filter.max_signal_age_ms` (it can only go down: the ceiling is 5,000 [PO]), `copyreplay.delay_ms`, `feed.stale_after_s`, `clock.max_offset_uncertainty_ms` and `gate.hold_latency_mult`.

**Values that our recordings must validate (VAL-R):** `tiers.lookback_days`, `tiers.depth_band_pct`, the four tier thresholds and `recording.max_gb_per_day`. The tier defaults are priors, not measurements. They are checked against ≥ 7 days of recordings in the readiness report, then adjusted within their bounds and frozen. None is FROZEN, so no addendum is needed; the hard floors on the tradable floor can't be lowered.

---

## 4. Non-functional requirements

**Latency budgets per stage.** Leader timestamps are exchange time, corrected by the clock offset.

| Stage | p50 | p95 | p99 | Note |
|---|---|---|---|---|
| S1: leader fill (exchange) → WS receive | ≤ 700 ms | ≤ 1,500 ms | ≤ 3,000 ms | Network and exchange; a **measured target** (VAL-L), not a code budget |
| S2: WS receive → signal classified | ≤ 5 ms | ≤ 20 ms | ≤ 50 ms | F7 |
| S3: signal → decision (filter, gate, sizing) | ≤ 20 ms | ≤ 60 ms | ≤ 150 ms | F9 and F10 |
| S4: decision → paper fill computed | ≤ 10 ms | ≤ 30 ms | ≤ 100 ms | Plus the simulated `paper.ack_delay_ms` (1,000 ms) |
| Leader fill → decision (S1 + S2 + S3) | ≤ 800 ms | ≤ 1,700 ms | ≤ 3,300 ms | At least 95% of signals decided within 5 s |
| Leader exit receive → our close decision | ≤ 20 ms | ≤ 60 ms | ≤ 150 ms | The exit path |
| Missed exit detected → alert sent | ≤ 5 s | ≤ 30 s | ≤ 60 s | F12.AC6; the counterfactual cost follows within 5 min of the actual fill (F12.AC9) |
| Mark crossing SL/TP → close decision | ≤ 50 ms | ≤ 200 ms | ≤ 1,000 ms | |
| Entry fill → Telegram post sent | ≤ 2 s | ≤ 5 s | ≤ 15 s | Subject to Telegram limits |
| Telegram command → reply | ≤ 1 s | ≤ 3 s | ≤ 10 s | |
| Scoring cycle, incremental, 200 candidates + followed | ≤ 10 min | ≤ 20 min | ≤ 45 min | |
| Restart → trading-ready, gap ≤ 1 h | ≤ 60 s | ≤ 120 s | ≤ 300 s | |

**Throughput:**
- 9 followed wallets, with bursts of 100 fills/s sustained for 10 s.
- Recording of ≤ 250 coins at `recording.l2_interval_ms`.
- REST ≤ 900 weight/min.
- The recorder and the trading path together use ≤ 500 WS subscriptions.

**Availability:**
- Downtime < 2% of the evaluation window (P5): about 14 h in 30 days and about 32 h at the 67-day maximum.
- In the 24h dry run, the target is ≥ 99.5% uptime, with no single outage over 15 min.

**Resources** (PO's Windows PC):
- RAM ≤ 2 GB RSS.
- Average CPU ≤ 25% of one core, excluding the evaluation and replay batch jobs. Compression and upload are included.
- Recording ≤ `recording.max_gb_per_day` (1.5 GB/day) compressed on disk, measured in the 24h dry run (A10).
- The ledger grows ≤ 200 MB/day.
- **Local disk footprint** at steady state ≤ 50 GB of the PO's ~100 GB free: the local window plus the current day (8 days × ≤ 1.5 GB), the download cache (≤ 20 GB) and the ledger (≤ 200 MB/day, about 15 GB over 74 days).
- Archive upload ≤ 1 day of recording per `storage.upload_deadline_h` (6 h), and upstream use ≤ 2 GB/day.

**Batch jobs:**
- The `T_eval` verdict plus 300,000 B0d replications take ≤ 4 h.
- A replay of 7 days × 9 wallets takes ≤ 60 min.
- The report regenerates in ≤ 10 min from computed baselines.
- These budgets hold with every input day local. When days must first be downloaded from the archive, the download time is extra and is reported separately.

**Cost:**
- Total ≤ $50/month.
- LLM ≤ `llm.monthly_budget_usd` ($5 default).
- Object storage ≤ `storage.monthly_budget_usd` ($5/month), including operations and egress (F23.AC7). At an expected ≤ 1.5 GB/day, 74 days is ≤ 111 GB: about $0.70/month on B2, or $1.70 on R2.
- Every data source is $0. No paid S3 **data** (`data.paid_s3`); the object-storage bucket is our own archive, not a data purchase.

**Security:**
- 0 inbound listening ports.
- Secrets only from the environment.
- The Telegram allow-list is one user and one chat.
- The object-storage key should be scoped to the one bucket, without delete rights. The engine needs read, write and list only (F23.AC2).
- The ledger backup is encrypted on the PC before upload (F23.AC4). Recordings are public market data and are not encrypted.

---

## 5. Failure behaviour

The default is **fail closed for opens and adds, never for exits**.

| Dependency / event | Detection | Behaviour | User-visible effect | Recovery |
|---|---|---|---|---|
| HL WebSocket disconnect or silent stall | No message or pong for `feed.stale_after_s` | Refuse opens and adds for affected wallets; the gap is ledgered as `data_gap` downtime | Alert "feed stale: <wallets>"; `/status` shows it | Jittered reconnect; REST resync by `tid` before any decision; missed leader exits are mirrored immediately; gap positions are reconstructed (F13) |
| Book or mark stale | Age > `filter.max_price_age_ms` | Refuse opens; SL/TP evaluation waits for fresh data; over `feed.stale_after_s` it becomes a data gap | Refusal reason `stale_price` | On fresh data, evaluate triggers; gap → reconstruct from 1m candles |
| REST 429 | HTTP 429 | Backoff (F3.AC2); scoring deferred; exits and reconciliation first | None unless it lasts > 10 min (then alert) | Automatic |
| HL 403/451 or geo-block (BCB deadline 2026-10-30) | F3.AC5 | `access_degraded`: refuse opens and adds; keep retrying; counts as downtime (K10) | Alert; `/status` shows the reason | Clears after `access.recover_min` healthy; if it persists, PO decides (K10) |
| Leaderboard endpoint fails or changes schema | HTTP error, timeout, schema failure, < 1,000 rows | Keep the followed set; add none | One alert per outage | Automatic on success |
| Wallet history truncated at 10k fills | Truncation rules (hl_sample BT2-6) | Flag the wallet; G3 decides eligibility | None | – |
| Clock offset unknown or too large | F1.AC6 | Refuse opens and adds | Alert `clock_unsynced` | Clears when the offset is back within bounds |
| Invalid config at start | F1.AC1 | Refuse to start | Non-zero exit with the key named | Fix the config (in a run, that is ABORTED) |
| Config hash change mid-run | F17.AC4 | Run → ABORTED; the engine keeps managing positions | Alert "run ABORTED: config change" | Run 2 needs a new run record |
| Dirty tree or wrong worktree at run start | F17.AC2 | Refuse run start | Error message | Clean or re-pin, then start |
| Mid-run code or dependency change | F17.AC3 | New code refuses to run for the run; the recorded commit continues | Alert "deploy pending ruling" | Auditor ruling: CONTINUE or ABORTED |
| Ledger append or verification failure | F2.AC1 / F2.AC6 | Halt all actions; paper positions freeze; counts as downtime | Alert (Telegram if possible, and the local log) | Restart after repair; reconstruction settles the gap |
| Free disk below the alert threshold | F4.AC5 | Keep running; report the unarchived backlog | Alert once per 6 h | Archive catches up (F23), or the PO frees space |
| Free disk below the hard floor | F4.AC5 | Recorder flushes and stops safely; opens and adds refused `disk_low` (downtime); exits, ledger and uploads continue | Alert "recording stopped: disk floor" | Automatic resume above floor + margin; the gap counts under edge-hypothesis §14 item 8 |
| Archive upload or verification fails | F23.AC1 / F23.AC6 | Keep local data; retry; never prune the day | Alert with the backlog (days, GB) | Automatic on success; if the backlog reaches the disk floor, see the row above |
| Storage credentials missing | F23.AC5 | Record locally; no upload or pruning; `run start` refused | Alert; `/status` shows `archive: not configured` | PO sets the env variables |
| Archived object corrupt on read | F23.AC3 | Never use it; the batch job exits non-zero | Alert `archive_corrupt` with the day | Re-upload from the local copy if still present; otherwise the day is a recorder gap under §14 item 8 (auditor informed) |
| Archive unreachable during a batch read | F23.AC3 | Retry for `storage.read_retry_max_min`, then the batch job exits non-zero | Error naming the day | Re-run when reachable; trading is unaffected |
| Ledger backup fails | F23.AC4 | Retry; trading continues | Alert | Automatic; `run start` refused after 48 h without a verified backup |
| Projected storage cost ≥ 80% of $5/month | F23.AC7 | Keep uploading | Daily alert | PO decides (A21) |
| Tier table missing or stale | F9.AC8 | Refuse opens with `untiered`; exits continue; `run start` refused | Alert | Next recompute with enough coverage |
| No leverage within the ceiling fits the margin, or liquidation too close | F10.AC4 | Refuse the open or add (`insufficient_margin` / `liq_too_close`); never an exit | Logged refusal; counted in the daily report | None needed |
| Telegram API down | Send errors | Queue messages (F14.AC8); trading continues; the kill switch stays available on the CLI | Delayed posts | Queue drains in order |
| LLM down, timeout or over budget | F15 | Post without "why"; try Ollama | "why unavailable" | Automatic; the budget resets monthly |
| Calendar missing, invalid or expiring | F8.AC3 | Refuse opens and adds; refuse run start | Alert `calendar_invalid` | Update the data file (a data-input change: a deploy if mid-run) |
| Process crash, Windows update reboot, PC sleep or power loss | Supervisor, or a heartbeat gap | Restart; reconstruct; downtime | Alert on restart with the gap duration | F13 |
| Coin delisted with an open share | Exchange delist or settlement | Close at the settlement price | Post with `delisted_force_settle` | – |
| Mark reaches liquidation | F11.AC5 | Liquidate the share | Post with `liquidated`; alert | – |
| Leader flat or reversed but our share open | Reconciliation | Close the share; missed-exit check | Alert; possibly a missed exit (row below) | – |
| Unknown fill format or `dir` value | Schema or classifier failure | Signal `unparseable`, not traded; immediate reconciliation if it involves an open share | Alert | Code fix (a deploy if mid-run) |
| Drawdown ≥ 15% | F10.AC5 | Pause until `/resume`; FAIL (F1) | Alert "drawdown stop, run FAIL" | PO `/resume`; the run is over |
| Daily or weekly loss limit | F10.AC5 | Halt opens and adds until reset (not downtime) | Alert once | Automatic at reset |
| Missed exit detected | F12.AC6 | Bring the share in line with the leader; compute the mirrored counterfactual and cost (F12.AC9); count it at min(actual, mirrored) R; go-live blocker | Alert "missed exit n/3" with the cost when known | The run continues unless F2 fires (next row); the blocker stays until explained and fixed at /go-live |
| 4th missed exit, or one costing > 1R versus mirroring (edge-hypothesis A3) | F18.AC11 | FAIL (F2) at that moment; the run ends; the bot pauses | Alert "missed-exit limit, run FAIL" | The run is over |
| Unauthorized Telegram command | F14.AC1 | Refuse; audit | Throttled alert | – |
| Repeated wrong PIN | F14.AC5 | Lock `/flatten` in Telegram | Alert | Lockout expires; CLI flatten still works |
| NTP or offset source unreachable | Estimate age grows | After `clock.max_estimate_age_s`, refuse opens and adds | Alert | Automatic |
| OKX endpoint error | F22.AC3 | Back off; no effect elsewhere | ≤ 1 alert per day | Automatic |

---

## 6. Flags

- `touches_money_path`: **yes**. Sizing, the risk gate, paper execution, positions and exits are the money path, and they port to live later.
- `touches_strategy`: **yes**. Trader scoring and selection, filters, exits and the pre-registered evaluation are all in scope.
- `has_ui`: **no**. There is no web UI. Telegram is the only interface; `qa` tests it as `integration` and `qa-ui`.

---

## 7. Implicit requirements

**Trading invariants (`.claude/knowledge/trading-invariants.md`):**

| Invariant | Enforced by |
|---|---|
| A1 single chokepoint | F10.AC1 |
| A2 fail closed | F1.AC1, F10.AC7, F5.AC3, F8.AC3, F3.AC5, F4.AC5, F9.AC7–AC8 (below floor, untiered), F10.AC4 (no fitting leverage), F12.AC9 (uncomputable cost), F23.AC3 (corrupt archive), §5 |
| A3 hard limits in config (notional, leverage, open positions, per-symbol exposure, daily loss, orders/min) | F1.AC2, F10.AC3–AC5, F10.AC10 (leverage ceilings 5x/10x and the compiled high-leverage coin set); §3.6 |
| A4 kill switch (CLI + Telegram, persistent, tested) | F10.AC6, F14.AC4–AC5, F13.AC4 |
| A5 idempotency / deterministic client order IDs | F10.AC8, F7.AC2, F2.AC3, F13.AC5 |
| A6 Decimal money, tick/step rounding, minimum notional | F1.AC4, F11.AC4, F2.AC4 |
| A7 exchange is the source of truth | **Paper analogue:** our "exchange" is the paper broker, whose state is rebuilt from the verified ledger at startup (F2.AC1, F13). The leader's positions are reconciled against `clearinghouseState` (F12.AC5). Real exchange reconciliation is N/A: there is no exchange account in this epic. |
| A8 partial fills, rejects, cancels, liquidations, ADL | F11.AC1, AC5, AC8; F10.AC4 keeps liquidation ≥ 3 × the stop distance. **ADL: N/A.** A paper position can't be auto-deleveraged, and no per-account ADL data exists; revisit at /go-live. |
| A9 explicit units | F1.AC4; §3 unit column. Naming is enforced in review. |
| A10 explicit mode, paper default, live refused | F1.AC3 |
| B1 staleness guard | F9.AC1, F3.AC3, F7.AC5 |
| B2 UTC timestamps with source and clock skew | F1.AC6, F7.AC5 |
| B3 heartbeats, reconnect with jitter, gap resync | F3.AC3, F3.AC4, F21.AC1 |
| B4 rate budget and 429 backoff | F3.AC1, F3.AC2 |
| B5 append-only audit of every decision | F2.AC1, F2.AC2, F5.AC7 |
| C1 verified fills and minimum sample | F5.AC3, F5.AC6 |
| C2 size by our risk budget | F10.AC2 (the mirror is only an upper bound; the risk cap always applies) |
| C3 slippage guard | F9.AC1 (thresholds by liquidity tier), F9.AC7 |
| C4 mirror closes, reductions and flips; no orphans | F12.AC3, AC4, AC5, AC6, AC8, AC9; a missed exit is always a go-live blocker (F20.AC4) |
| C5 independent leaders in consensus | **N/A:** no consensus voting exists. Each leader is a separate share. Correlated leaders' stacking is bounded by the per-coin, BTC-bucket and per-leader caps (F10.AC3). |
| C6 end-to-end latency measured and exported | F7.AC6, F21.AC3, F20.AC1, §4 |
| D1 no look-ahead | F4.AC3, F5.AC5, F9.AC2, F9.AC7 (tiers from data received ≤ computation time), F16.AC2, F23.AC3 |
| D2 no survivorship | F4.AC2, F16.AC4, F2.AC5, F23.AC2 (the archive is never deleted from) |
| D3 fees, funding, spread and slippage | F11.AC1–AC3, AC7, F16.AC6, F19.AC3 |
| D4 criteria before results; variants counted | F17 (frozen hashes, including the tier table), F16.AC5, F18.AC10, F18.AC11, F14.AC6, F14.AC9; edge-hypothesis A3 is dated before run 1 |
| D5 out-of-sample and naive baselines | F16 (point-in-time replay), F19 (B0d), F20.AC1 (B0, B0b, B1–B4) |
| D6 paper confirms replay | F18.AC9 (P6), F20.AC3 |
| E1 trade-only keys | **N/A:** no exchange keys exist in this epic (F1.AC3). |
| E2 secrets from env, never logged | F1.AC5, F15.AC3, F23.AC5 |
| E3 authenticated control surface | F14.AC1, F14.AC5 |
| E4 no public admin ports | F21.AC4 |
| E5 every fill exportable | F2.AC4; the encrypted ledger backup (F23.AC4) protects the records against loss of the PC |
| E6 third-party offering → legal review | **N/A in this epic.** Phase 2 is out of scope and gated by D12. Reports carry a disclaimer (F14.AC7). |
| F1 LLM hard timeout and fallback, off the hot path | F15.AC1, F15.AC2 |
| F2 LLM can't raise size or bypass limits | F15.AC4 (it has no vote at all [PO D5]) |
| F3 LLM inputs and outputs logged | F15.AC3 |

**CLAUDE.md implicit requirements:**

| Requirement | Enforced by |
|---|---|
| Secure by default; secrets never read, logged or committed | F1.AC5, F14.AC1, F14.AC5, F21.AC4, F23.AC4 (encrypted backup), F23.AC5 (env-only storage credentials, HTTPS only) |
| Anything data-driven is data-driven | F1.AC1 (no code defaults), §3; the calendar is a data file (F8); coin tiers come from measured liquidity, not a hand list (F9.AC7); leverage is computed per order (F10.AC4) |
| Money-safety invariants are BLOCKING | This section; every reviewer treats a violation as BLOCKING |
| No agent places a live order or touches live keys; tests use paper or replay | F1.AC3; every `simulation` AC runs in paper or replay |
| Real money only after /go-live and a written PO go | F1.AC3 (live refused in this build); out of scope (§8) |

**Frozen pre-registration** (edge-hypothesis §5), mapped to ACs:
- Run record: F17.AC1
- Engine path set: F1.AC7 and F17.AC2
- Deploy rules: F17.AC3
- Verdict rule and precedence: F18
- B0d and P2c: F19
- Go-live blockers and diagnostics: F20
- Visibility (§5.5 as amended by A3): F14.AC6, F14.AC9 and F18.AC10
- Missed-exit rule (P4/F2 as amended by A3): F12.AC6, F12.AC9, F18.AC7, F18.AC11 and F20.AC4
- `/flatten` shadow: F12.AC7 and F18.AC3
- Run register: F17.AC6
- Evaluation tests 1–20 (§10.8): covered across F17, F18, F19 and F20; the test plan maps each

---

## 8. Out of scope

- Real-money execution, live keys, the Hyperliquid testnet, and exchange-side SL/TP placement (D9 applies when live).
- Running the paper runs themselves, and their verdicts. They start after /ship, on the PO's go, and are tracked in the run register (A11).
- HIP-3 **trading**; its data is recorded. On-chain memecoins, on-chain spot, Binance, and any other execution venue. Liquid Hyperliquid meme perps (for example DOGE, kPEPE, WIF) are **in** scope when they qualify by liquidity tier (F9.AC7).
- OKX **signals or trading**. F22 records only.
- An ML-trained filter. Data is collected; the model is a later epic.
- Web UI, WhatsApp, subscribers, payments, KYC, a Telegram channel or Mini App, and all phase-2 legal work (D12).
- Cloud compute hosting, a VPS and paid data (paid S3 data, CoinGlass, Nansen). Object storage for our own archive and ledger backup is **in** scope (F23, ≤ $5/month).
- Automatic restore of the whole recording archive to a new PC. Only the ledger restore drill (F23.AC4) and on-demand reads of archived days (F23.AC3) are in scope.
- BRL conversion and tax exports beyond the USD fill CSV (F2.AC4).
- Any news source, paid or free, for the LLM summary (A9). **J7 Tracker was not evaluated**; the PO may send a link for a later epic. The LLM has no vote either way.
- Strategy changes after run 1 starts, other than by a dated addendum (edge-hypothesis §5.1).

---

## 9. Definition of done

The epic is done, meaning **run-1-ready**, when all of the following hold:
1. **ACs met.** Every AC in F1–F21 and F23 is `MET` in `07-verification.md`, with evidence. F22 is `MET` too, or has been moved to out-of-scope by the PO (A8).
2. **Tests.**
   - The full test suite passes on Windows 10/11 with the pinned lockfile (F21.AC5).
   - Every test that proves an AC fails before its implementation.
   - The mutation threshold set by /onboard is met for `risk`, `paper`, `positions`, `evaluation`, `baselines` and `archive`.
3. **Conformance.** The evaluation reproduces every E14 golden vector, and all 10 E14 mutants are killed (F18.AC1).
4. **Reviews.** No BLOCKING finding is open from /review or /qa.
5. **24h dry run.**
   - ≥ 24 h continuous, full pipeline, live mainnet data, dry-run mode, on the PO's PC (F21.AC2).
   - 0 crashes, 0 missed exits, downtime < 2%, and the ledger verifies.
   - "0 missed exits" is stricter than the run rule on purpose (F21.AC2): in the dry run any missed exit is a bug to fix before run 1, not something to absorb under the edge-hypothesis A3 limits.
   - Compressed recording ≤ `recording.max_gb_per_day`, one day archived and verified, and one ledger backup verified.
   - It starts once ≥ `tiers.lookback_days` × `tiers.min_coverage_fraction` days of recording exist, so a tier table is in force.
6. **Latency measurement.**
   - ≥ 24 h, n ≥ 100 signals (F21.AC3), on the PO's connection.
   - The VAL-L keys are set from it before freezing: `filter.max_signal_age_ms` ≤ 5,000, and `copyreplay.delay_ms` = measured p95.
7. **Recording and archive.**
   - ≥ 7 days of continuous, compressed recording and hourly leaderboard snapshots exist before run 1.
   - Every finished day older than `storage.max_unarchived_days` is archived and verified, and local pruning has run at least once under F23.AC2.
   - The ledger restore drill (F23.AC4) has passed on the PO's PC.
   - A replay of ≥ 1 archived-only day has matched its local replay byte for byte (F23.AC3).
8. **Readiness report** (F20.AC5), delivered to the PO. It includes:
   - the recorder gap rate and the projected share of trades without a B0d window
   - K1, K2, K6, K7 and K8 statuses
   - the point-in-time replay result

   If K1 or K2 is triggered, the epic stops for PO review (edge-hypothesis §7).
9. **Config frozen.**
   - `hl_sample.py` `summary.json` has been received, and the quant-researcher has reviewed the VAL-S keys.
   - The CAL keys are calibrated on pre-paper data.
   - The complete config is committed, and its hash is recorded in the readiness report.
10. **Run-control artifacts.**
    - `engine-path-set.txt` is committed.
    - The run-worktree procedure is documented in `docs/sdlc/copytrade-v1/`.
    - `run start` refuses on a dirty tree (demonstrated).
11. **Acknowledgements.**
    - The PO's acknowledgement of the 8 section-14 items is recorded. It already is: `decisions.md`, 2026-09-29.
    - Edge-hypothesis Addendum A3 (the missed-exit rule and `/stats` visibility) is committed, dated before run 1, and its final wording is acknowledged by the PO in `decisions.md`. The ACs marked provisional in Amendment 1 have been reconciled with it.
12. **No live path.** No live order path exists in the build (F1.AC3).
13. **Tiers validated.** The VAL-R tier thresholds have been reviewed against recorded data in the readiness report, and the tier table in force at config freeze is shown to the PO with its tier-1, tier-2 and below-floor coins.

---

## 10. Epic plan

**Order and parallelism.** Each feature is sized for one developer on `feat/copytrade-v1/<Fn>-<name>`. A wave starts when its dependencies have passed /verify into `epic/copytrade-v1`.

| Wave | Features (parallel within a wave) | Depends on | Note |
|---|---|---|---|
| 0 | F1 | – | Scaffolds the stack, lockfile, `engine-path-set.txt`, config loader, shared domain types and CLI registry |
| 1 | F2, F3, F8, F5, F18 | F1 | F5 and F18 are pure logic over interfaces and fixtures |
| 2 | F4, F7, F11, F15, F22 | F2, F3 | **F4 ships to a recording worktree right after /verify**, so day-1 recording and leaderboard snapshots start early (the ≥ 7-day precondition). F7 enables the early 1-day latency measurement (F7.AC6). |
| 3 | F6, F9, F10, F17, F19, F23 | F4 + F5 → F6; F4 + F7 + F8 → F9; F11 → F10; F2 → F17; F4 + F11 + F18 → F19; F2 + F4 → F23 | **F23 also ships to the recording worktree right after /verify**, so archiving and pruning start well before the local disk fills (at ≤ 1.5 GB/day, the ~100 GB lasts ~50 days without it). F10's leverage choice uses F11's liquidation model through its interface. |
| 4 | F12, F14 | F7, F10, F11 → F12; F10 (+ F12 events) → F14 | F14 may start on F10 alone and wire F12 events when they land. `/stats` needs only F2 aggregates. |
| 5 | F13, F16 | F12 | |
| 6 | F20, F21 | F16, F18, F19, F23 → F20; all → F21 | F21 runs the 24h dry run and the final latency run |

**Critical path:** F1 → F3 → F4/F7 → F9/F10/F11 → F12 → F16 → F20/F21. F23 is off the critical path but must pass before the recording worktree nears the disk alert threshold, and before run 1. F22 is off the critical path and is the first to be dropped under schedule pressure.

**Features gated by edge-hypothesis A3:** F12.AC6/AC9, F14.AC6/AC9 and F18.AC7/AC11 may be built on this spec, but /tests freezes their vectors only after A3 is committed.

**File-ownership map.**
- A feature may create or modify only the paths it owns.
- Shared files have one owner, and other features change them only through a small CTO-serialized commit on the epic branch before cutting or rebasing their branch.
- Tests live under `tests/<area>/`, owned by the same feature.

| Feature | Owns (create or modify) | Reads, or uses through interfaces only |
|---|---|---|
| F1 | Project metadata file and lockfile (**shared**; dependency additions are CTO-serialized); `engine-path-set.txt`; `src/copytrade/core/**` (config loader, ceilings, mode, money/units, clock, secrets, domain types, events); `src/copytrade/cli/main.*` (subcommand registry); `config/platform.*`; `tests/core/**` | – |
| F2 | `src/copytrade/ledger/**`; `src/copytrade/cli/ledger.*`; `config/ledger.*`; `tests/ledger/**` | core |
| F3 | `src/copytrade/hl/**`; `config/hl.*`; `tests/hl/**` | core, ledger |
| F4 | `src/copytrade/recorder/**` (writers, compressed day-partitioned format, disk guard, and the store **interface** with its local implementation); `src/copytrade/cli/recorder.*`; `config/recording.*`; `tests/recorder/**` | hl, ledger |
| F5 | `src/copytrade/scoring/**`; `config/scoring.*`; `tests/scoring/**` | core; hl and recorder interfaces |
| F6 | `src/copytrade/selection/**`; `config/selection.*`; `tests/selection/**` | scoring, hl, recorder, ledger |
| F7 | `src/copytrade/signals/**`; `src/copytrade/cli/latency.*`; `config/markets.*`; `tests/signals/**` | hl, ledger |
| F8 | `src/copytrade/calendar/**`; `data/inputs/macro_calendar.*`; `config/calendar.*`; `tests/calendar/**` | core |
| F9 | `src/copytrade/filters/**` (including the liquidity-tier computation and the tier table in force); `config/filter.*`; `config/tiers.*`; `tests/filters/**` | signals, calendar, recorder (store interface) |
| F10 | `src/copytrade/risk/**` (gate, sizing, caps, automatic leverage, kill-switch state); `src/copytrade/cli/killswitch.*`; `config/risk.*`; `tests/risk/**` | paper (broker interface and liquidation model), ledger |
| F11 | `src/copytrade/paper/**`; `config/paper.*`; `tests/paper/**` | recorder, hl, ledger |
| F12 | `src/copytrade/positions/**` (shares, exits, mirroring, reconciliation, missed-exit detector, shadows); `config/exits.*`; `tests/positions/**` | risk, paper, signals |
| F13 | `src/copytrade/recovery/**`; `config/restart.*`; `tests/recovery/**` | positions, hl, recorder |
| F14 | `src/copytrade/telegram/**` (including `/stats`); `src/copytrade/reports/**`; `config/telegram.*`; `tests/telegram/**` | risk, positions, ledger, llm interface. **Never** evaluation or baselines (F14.AC6). |
| F15 | `src/copytrade/llm/**`; `config/llm.*`; `tests/llm/**` | ledger |
| F16 | `src/copytrade/replay/**`; `src/copytrade/cli/replay.*`; `config/replay.*`; `tests/replay/**` | signals, filters, risk, paper, positions, recorder |
| F17 | `src/copytrade/run/**`; `src/copytrade/cli/run.*`; `tests/run/**` | core, ledger, calendar, filters (tier table), archive (health) |
| F18 | `src/copytrade/evaluation/**`; `config/eval.*`; `tests/evaluation/**` (including golden literals copied from E14) | ledger |
| F19 | `src/copytrade/baselines/**`; `config/baseline.*`; `tests/baselines/**` | evaluation, paper (fill model), recorder |
| F20 | `src/copytrade/reporting/**`; `src/copytrade/cli/report.*`; `config/report.*`; `tests/reporting/**` | evaluation, baselines, replay |
| F21 | `src/copytrade/app/**` (supervisor and wiring); `src/copytrade/cli/app.*`; `tests/app/**`; `docs/sdlc/copytrade-v1/run-worktree.md` | everything |
| F22 | `src/copytrade/okx/**`; `config/okx.*`; `tests/okx/**` | ledger |
| F23 | `src/copytrade/archive/**` (uploader, verifier, pruner, archive-backed store implementation, ledger backup and restore, cost projection); `src/copytrade/cli/archive.*`; `config/storage.*`; `tests/archive/**` (including the S3-compatible stub) | recorder (store interface, day files), ledger, core |

**Collision rules.**
1. The config tree is split one file per area, so parallel features never edit the same config file. The config hash covers all of `config/**`.
2. `src/copytrade/core/` domain types belong to F1. A later change is a CTO-serialized commit.
3. The CLI registry (`cli/main.*`) discovers `cli/<area>.*` files, so features don't edit it.
4. `engine-path-set.txt` lists directory globs, so new modules under `src/copytrade/**` and `data/inputs/**` don't require editing it.
5. `storage.ledger_dir` and `storage.recordings_dir` stay in `config/platform.*` (F1). Every other `storage.*` key lives in `config/storage.*` (F23).
6. Readers of recordings (F9, F13, F16, F19, F20) depend only on F4's store interface. F23 provides the archive-backed implementation, and F21 wires it in, so no reader changes when F23 lands.

---

## 11. Assumptions for the PO to confirm

None of these contradicts a PO decision. Each fills a gap the PO hasn't ruled on. Defaults apply unless the PO says otherwise before /tests closes.

**Status (Amendment 1, 2026-09-29):**
- **Accepted by the PO** ("Other points OK"): A1, A3, A5, A7, A8, A11, A12, A13, A15 and A16.
- **Replaced by PO decisions** (Spec review, `decisions.md`), rewritten below: A2, A4, A6, A9, A10 and A14.
- **New, pending PO confirmation:** A17 to A23. Each follows from applying the Spec review decisions.

| # | Assumption | Why it matters | Alternative |
|---|---|---|---|
| A1 | **Exits:** initial stop = 2 × ATR(14) on 1h candles (no "structure" stop). TP closes 50% at +2R. After +1R the stop trails at 2 × ATR from the best mark and never widens. | "TP is config" in the brief; this is the risk-research default, and V3, V4 and V5 vary it | A single full TP at a fixed R, or no TP (V5) |
| A2 | **[PO decision, Spec review A2]** **Leverage** is chosen automatically per open or add: the lowest value that fits the margin, up to 5x for alts and 10x for BTC, ETH and SOL, and only while the liquidation distance stays ≥ 3 × the stop distance for every share. Otherwise the signal is refused. Risk per trade is unchanged, because it is set by the stop (F10.AC4, F10.AC10). | More room for positions on $300 | – (decided) |
| A3 | **Loss limits** use marked-to-market equity. The daily limit resets at 00:00 UTC (21:00 BRT); the weekly one on Monday 00:00 UTC. Loss halts are rule-based and are **not** downtime for P5. | Defines when halts start and whether they cost the run | Count halts as downtime (stricter on P5) |
| A4 | **[PO decision, Spec review A4]** A **missed exit** is defined as in §1, with a 60 s lag threshold; exits in downtime that are reconstructed are not missed. It counts at min(actual, mirrored) R. The run FAILs only if missed exits exceed 3, or any single one cost more than 1R versus mirroring. Every missed exit alerts and is a go-live blocker until explained and fixed. The exact rule is edge-hypothesis A3. | The PO wants a FAIL only when it costs money; a bug must never help the verdict | – (decided; the 60 s lag stays a PM default) |
| A5 | **Trend, funding, OI-drop and premium filters start as record-only.** Before run 1 they are either calibrated on ≥ 1 week of recorded data and switched to enforce, or left record-only; then frozen. Volatility halving at the 90th percentile is enforced from the start. | There is no data behind any threshold (OF); inventing them would be strategy by folklore | Enforce hand-picked thresholds now |
| A6 | **[PO decision, Spec review A6]** **Coin tiers** are assigned automatically from measured liquidity (book depth within a band and 24h volume, from our recordings). Tier 1 gets 0.3% slippage / 0.1% spread, tier 2 gets 0.8% / 0.3%, and coins below the floor are skipped. Liquid meme perps (DOGE, kPEPE, WIF) trade when they qualify. The table is recomputed daily and frozen at run start with the config hash. Default thresholds are in A22. | The PO wants more coins, including big meme perps, without trading thin books | – (decided) |
| A7 | **Exposure caps:** total open risk 5%; per coin 1.5%; BTC bucket (correlation ≥ 0.6) 3% same direction; per leader 1.5%; share risk after adds ≤ 1%; notional per position ≤ 1 × equity; ≤ 30 orders/min. | The brief names these caps without numbers except "≤ 10 positions" | Other values within the ceilings |
| A8 | **OKX** is record-only and off by default. H1 is pre-registered on Hyperliquid wallets only, so OKX signals can't enter run 1. F22 may be dropped. | Brief: "lowest priority" | Drop F22 now |
| A9 | **[PO decision, Spec review A9]** **LLM** cap is $5/month (ceiling $20). There is no news source, paid or free, in v1. The "news summary" is built from the calendar and our recorded market metrics. J7 Tracker was not evaluated (§8). The LLM has no vote. | News would only affect the explanation text | – (decided) |
| A10 | **[PO decision, Spec review A10]** **Disk and storage.** The PC has ~100 GB free. Recordings are compressed (estimate ≤ 1.5 GB/day, VAL-R). Each finished UTC day is uploaded to Backblaze B2 or Cloudflare R2, verified by checksum, and only then pruned locally, keeping 7 days. The ledger stays local, with a daily encrypted cloud backup. Replay, B0d and evaluation read local or cloud transparently. A disk guard alerts, then stops recording at a floor without blocking exits. Budget ≤ $5/month (F4, F23). **The PO chooses B2 or R2 and sets the bucket and credentials as environment variables.** B2 pricing is the default for the cost projection. | ~350 GB of raw recording would not fit | – (decided) |
| A11 | **Epic done = run-1-ready** (§9). Paper runs start after /ship, on your go, and are tracked in the run register. | A run takes 30–67 days | Keep the epic open until the run-1 verdict |
| A12 | **`/flatten` PIN:** 3 wrong attempts in 15 min lock the Telegram flatten for 15 min (the CLI still works). The bot deletes the PIN message. | Abuse protection | Other limits |
| A13 | **Reports** are sent daily at 00:05 UTC (21:05 BRT) and weekly on Monday at 00:10 UTC. | Timing | Other times |
| A14 | **[PO decision, Spec review A14]** **Interim visibility.** During a run you see per-trade results, USD P&L, counts and progress to 300, and `/stats` shows P&L, win rate, average R, drawdown and per-trader stats. You never see the gate CI, P2c, FR checks or any verdict preview before `T_eval` (edge-hypothesis §5.5 as amended by A3; F14.AC6, F14.AC9, F18.AC10). | Full visibility for the PO; the 2-run α split keeps the family-wise false-PASS rate | – (decided) |
| A15 | **Signal age** can be lowered after the latency measurement, never raised above 5 s. If the measured p95 is above 5 s, that comes back to you as a decision, not a config change. | "Never chase" [PO D7] | – |
| A16 | **Recorder runs early.** After F4 passes /verify, it runs continuously from its own worktree on the epic branch, before /ship, to start day-1 recording. F23 joins it there after its own /verify. | ≥ 7 days of recording is a run-1 precondition | Wait for /ship, which delays run 1 by ≥ 7 days |
| A17 | **"Majors / alts" in the edge-hypothesis cost fallbacks** (§6.3: half-spread 2 / 8 bps, delay slippage 5 / 15 bps) are read as **tier 1 / tier 2**. A coin that qualifies as tier 1 by measured liquidity gets the major fallbacks. Fallbacks apply only where our recording is missing. **For the quant-researcher to confirm in A3, or by a later dated addendum before run 1.** | EH §6.3 never lists the majors, and the §1 majors list is gone | Keep the major fallbacks for BTC and ETH only, and use alt fallbacks for every other coin (more conservative) |
| A18 | **Below the disk floor, opens and adds are refused** (`disk_low`, counted as downtime), as well as recording stopping. Exits always continue. | A trade opened while nothing is recorded has no B0d window or replay data, so it could only hurt P2c and P6 | Keep trading while recording is stopped |
| A19 | **Leverage starts at 1x** (`risk.leverage_min` = 1). At each open or add, the merged position's leverage is re-chosen as the lowest that fits the whole position. Early positions therefore use more margin, and later ones may need higher leverage or be refused `insufficient_margin`. | "Lowest value that fits" read literally; lower leverage keeps liquidation furthest away | Start at 2x or 3x, which leaves more free margin for later signals |
| A20 | **Mirrored counterfactual basis** (F12.AC9), unless A3 says otherwise: the leader event is mirrored at its exchange timestamp + `paper.ack_delay_ms`, filled by our paper fill model on the recorded book. Without a book, it uses exchange 1m candles at that minute with the fallback costs. If neither exists, the cost is `uncomputable` and counts as > 1R (fail closed). | A3 defines the rule; the spec needs a testable basis now | Treat an uncomputable cost as 0 (it would let a data gap help the verdict) |
| A21 | **Storage policy details.** (a) At ≥ 80% of the $5 projected monthly cost, alert daily but **keep uploading**: losing run data costs more than a small overage, and at ≤ 1.5 GB/day the projection is under $2. (b) `run start` refuses while a finished day older than 2 days is unarchived, or no ledger backup has verified in 48 h. | Never lose run data silently; start a run only with a working backup | (a) Stop uploading at the cap. (b) Allow a run to start without a verified backup. |
| A22 | **Tier default thresholds** (VAL-R priors, not measurements): tier 1 = median thinner-side depth ≥ $1,000,000 within 0.5% of mid **and** median 24h volume ≥ $200M; tradable floor = ≥ $50,000 **and** ≥ $10M; 7-day lookback; ≥ 80% coverage; recomputed every 24 h. Expected, but not measured: BTC and ETH in tier 1, SOL around the line, and DOGE, kPEPE and WIF in tier 2. Our orders are ≤ $300, so the floor keeps each order ≤ 1% of depth. | Thresholds need numbers before recordings exist; the readiness report replaces the guess with data | Other thresholds within the bounds in §3.5 |
| A23 | **`/stats` shows realised figures**, not gate-adjusted values (not min(realised, shadow) for flattened trades, and not min(actual, mirrored) for missed exits). It is labelled "descriptive only". With no run active, it covers the time since the dry-run start or the last run end. | Gate-adjusted numbers would move `/stats` closer to a verdict preview | Show gate-adjusted R, labelled as such |
