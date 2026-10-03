# Candidate pre-ranking for backfill (which `scoring.candidates_k` leaderboard rows get scored)
Quant researcher, 2026-10-03. **EXPLORATORY DESIGN, NOT VALIDATED.** The real leaderboard could not be fetched from this sandbox:
the egress proxy denied the CONNECT to stats-data.hyperliquid.xyz and api.hyperliquid.xyz with a 403 policy error. The design uses the row
schema and the PO's 7-wallet run (2 empty, 3 high-frequency, 2 usable). The PO validates it with `research/scripts/candidate_rank_check.py`.
Scope: this only decides **whom to backfill and score**. It changes no score, gate, weight or frozen rule. F5.AC6 still holds
(row pnl/roi/accountValue never change a metric or S), and followed wallets are always re-scored, whatever the prefilter says.

## 1. Recommendation (plain language)
Stop taking the first 50 rows in the order they are served. From the leaderboard row alone, keep wallets that:
- are big enough (G11);
- traded this week and enough this month to reach 150 round trips;
- are not trading so hard that they look like bots or market makers;
- made money both in the last month and before it;
- earned at least 10 bps per dollar traded in both periods. Below that, our copy costs eat the edge, and HFT and market makers fall out.
Rank the survivors by that per-dollar edge (capped, so lottery wins don't dominate), then by all-time P&L. Backfill in rank order. Drop a wallet
after one page if the page shows a bot (2,000 fills in under a day) or if it has no fills at all. Rotate candidates that keep failing the
gates so the 50 slots explore further down the list. This is **option D** below.

## 2. Rules (for the test designer; all thresholds pre-registered, inclusive as written)
Row fields: `AV`=accountValue; `pnl_w`, `vlm_w` for w in day/week/month/allTime (strings parsed as Decimal). Derived:
`turn_m = vlm_month/AV`, `turn_d = vlm_day/AV`, `pnl_prior = pnl_allTime - pnl_month`, `vlm_prior = vlm_allTime - vlm_month`,
`bps_m = 1e4*pnl_month/vlm_month`, `bps_p = 1e4*pnl_prior/vlm_prior`, `ret_m = pnl_month/AV`. The `roi` field is **not used** (undocumented denominator).
1. **P1 readable:** valid 0x address; AV, pnl and vlm of all 4 windows present and finite. Otherwise the row is *unrankable* (see L4).
2. **P2** address not in `gate.exclude_addresses` (HLP). 3. **P3** `AV >= gate.min_account_value_usd` (10,000; existing R1 behaviour).
4. **P4 active:** `vlm_week > 0` and `turn_m >= 2`. 5. **P5 not hyperactive:** `turn_m <= 500` and `turn_d <= 50`.
6. **P6 profitable now and before:** `pnl_month > 0` and `pnl_prior > 0`.
7. **P7 edge per traded dollar:** `vlm_prior > 0`, `bps_m >= 10` and `bps_p >= 10`. 8. **P8 sanity:** `ret_m <= 1.0`.
9. **K1 rank key** (descending): `min(bps_m, bps_p, 50)`, then `pnl_allTime` descending, then lowercase address ascending (deterministic).
10. **L1** ranked list = rows passing P1-P8, ordered by K1. It must not depend on the served order: shuffling the rows gives the same list.
11. **L2** skip wallets in any backfill cooldown (EX1, EX2, RO1, R1's `too_active_truncated`) and wallets already followed (they are scored anyway).
12. **L3 stickiness** (saves backfill budget): last cycle's candidates still passing P1-P8 and ranked within the top `2 x candidates_k` keep their
    slot. Free slots go to the best-ranked others. The final list is ordered by K1, and backfill runs in that order.
13. **L4** if fewer than `candidates_k` are ranked, append unrankable rows (P1 failed only through missing fields, P2/P3 not violated) in
    served order, as today. Readable rows that fail P2-P8 are never appended.
14. **L5 persist (B5):** each cycle records the per-rule pass counts, the candidate list with K1 values, and the prefilter parameters, plus one log line.
15. **EX1 too active at once:** the first `userFillsByTime` page of the window is full (2,000 rows) and its `last - first` time is under 86,400,000 ms.
    Drop at once with reason `too_active_first_page` and R1's too-active cooldown (24 h). Cost: ~120 weight instead of ~5 pages (~600).
16. **EX2 empty:** the first page is empty (0 fills in the window). Drop with reason `backfill_empty` and a 168 h cooldown. Log the row's
    `vlm_week` and `vlm_month`: an empty wallet that passed P4 means the row volume is not this address's fills. Many such cases falsify P4.
17. **EX3** R1's rule is unchanged: more than 50 pages, or exactly 10,000 fills with the first fill after window start + 1 day, means `too_active_truncated` (24 h).
18. **RO1 rotation:** a candidate that is fully backfilled, not followed, and ineligible in 3 consecutive cycles gets a 72 h cooldown. Without
    this the K slots stay stuck on the same failing wallets (the K1 order barely moves, and G7 is strict), and the bot never explores.

## 3. Why these rules (mechanism and derivations)
- **The two observed failure modes are targeted directly.** Empty wallets are caught by P4 and EX2. HFT and market makers are caught by P7, P5 and EX1.
  P7 is the main HFT filter, because market makers and HFT net about 0-3 bps per traded dollar. P5 alone is weak: a $1M wallet doing 10,000 fills of $5k
  a day sits at `turn_d` = 50.
- **P7 comes from the frozen G10.** Our cost per round trip = 2 x taker (4.5) + 2 x half-spread (2/8) + delay (~5), so about 18-30 bps. That is
  about 9-15 bps per dollar the leader trades (a round trip is 2 traded dollars). G10 asks for 3x that, so about 27-45 bps. The floor of 10 sits
  below that on purpose, because row pnl also holds funding and unrealised P&L. G10 makes the exact call on fills.
- **P4 comes from G2 and G12.** G2 needs 150 round trips per 180 d, so 25 a month. G12 needs a mirrored open of at least $10 at $300 equity,
  so a leader open of at least ~3.3% of AV. Month volume is therefore at least 25 x 2 x 0.033 x AV, about 1.7 x AV. Rounded to 2.
- **P6 and the "prior" period:** G4 (4 of 6 months positive), G6 and G7 need persistence. Profit before the last month is the only
  persistence signal the row has. Requiring both periods in P7 and K1 lowers the weight of a single lucky month.
- **ret_m cap (P8) instead of roi:** HL's roi denominator is undocumented (deposits and withdrawals). Over 100% in 30 days is very unlikely
  to survive G5 (DD <= 35%) and BU7 (leverage <= 10), and is the classic small or refunded account artifact.
- **K1 cap at 50 bps, tie-break on all-time P&L:** above ~50 bps per traded dollar, more is mostly variance (one big hold), and the row has no
  volatility field. All-time P&L moves slowly, so the list churns little. Each new candidate costs ~1 min of the 450/min budget.
- Not used: `displayName`, `prize` (no mechanism; name-based rules add arbitrary bias), `day` pnl (noise), `roi` (above).

## 4. Options compared (survivor counts and copyable fractions are PRIORS until the script runs; n=7 observed for A)
| Option | Rule | Pros | Cons / bias risks | Rows surviving of 47,023 (guess) | Top-20 copyable at first page (guess) |
|---|---|---|---|---|---|
| A (today) | served order, G11 + HLP only | no new code | effectively random. The PO saw 2/7 usable. Budget goes to empty and HFT wallets | ~10-16k pass G11 | ~0.3 (observed 2/7) |
| B | G11, rank by allTime pnl | stable, long record | whales include market makers and HFT. Old P&L. Big diversified accounts fail G12 (positions too small vs AV) | ~10-16k | 0.4-0.6 |
| C | G11, rank by month roi | simple | the "top-N by raw ROI" naive baseline (D5). Luck and momentum, mean reversion, small or refunded account artifacts, hourly churn | ~10-16k | 0.4-0.6 |
| **D (recommended)** | P1-P8 + K1 + L/EX/RO rules | targets both failure modes and the G2/G10/G12 floors. Order-independent and stable | more parameters (P5, P8, cap are priors, OF). Excludes good wallets in a losing month (until they recover) | ~0.5-2k (1-4%) | 0.7-0.9 |

## 5. Pre-registered success and kill criteria (D4), written before any data
- Measure: `candidate_rank_check.py` with the defaults (top 20, window 180 d), first-page verdict per wallet. *ok* means not empty, not too active and not truncated.
- **PASS:** D has at least 14/20 ok **and** at least 6 more ok than A's first 20 served rows in the same run. **KILL** (redesign, e.g. the stage-2
  idea in section 6): D has fewer than 10/20 ok. **PARTIAL** (in between): log it, and try at most one variant.
- After deployment (paper, not a gate): per cycle, record the share of candidates that EX1/EX2 drop and the share eligible after scoring. The
  eligible share has no threshold: G7 is strict and 0-5 eligible of 50 is plausible. Report it; never tune the gates on it.
- **Variants:** at most 3 in total (D = variant 1; each later one changes a single parameter, is written here before running, and is logged).
  Tried so far: variant 1 (D) run once = KILL (candidate-ranking-run1.md); variant 2 pre-registered in section 9, 0 runs.
- How to run (PO, bot stopped, ~5 min): `uv run python docs\sdlc\copytrade-v1\research\scripts\candidate_rank_check.py`. It saves the leaderboard
  gzip under `research/data/candidate_ranking/` (gitignored). Send back the whole console output. Self-test: `--selftest`.

## 6. Limits (honest)
- Row fields are exchange-computed account figures, self-reported to us, undocumented and backward-looking. Pnl includes funding and
  unrealised P&L, and the window definitions (rolling or calendar) are unconfirmed (BT2-7). Whether `vlm` includes spot is unknown (EX2 logging will show it).
- Base rate: most leaderboard wallets, and most copied leaders, do not keep an edge after costs. A good prefilter only means the budget is
  spent on wallets that *can* pass. The verified-fill scoring (F5) decides whom to follow, and the paper run decides whether any of it works.
- Selection on today's list and on past profit compounds survivorship and luck. That is legitimate for a forward paper run (the row is read at
  cycle time, with no lookahead), but it is no evidence. G7 deflates for N = `gate.dsr_n_trials` = 15,000 (FROZEN). The leaderboard now has
  47,023 rows: Emax 3.96 vs 4.22, SR0 at T=180 is 0.295 vs 0.315 daily. Changing that is a separate addendum question, not part of this.
- The row cannot see G1 (age), G13 (maker share, vault/agent role), BU7 (leverage) or G15 (current drawdown). Those stay in scoring.
  Possible later stage 2: the `portfolio` call (~20 weight, against 150-400 for fills) shows age, current drawdown and monthly P&L blocks. It
  would prefilter G1/G4/G15 cheaply. Not proposed for v0.
- The n=20 check is a smoke test: 14/20 has a 95% CI of about 0.46-0.88. P5, P8 and the K1 cap rest on few data points (OF). Do not tune them on paper-run data.

## 7. Config implications (for the PM; any new key is an F1 schema change, CTO-serialised)
| Key (proposed) | Default | Range | Flag |
|---|---|---|---|
| `prefilter.min_month_turnover` (P4) | 2 | 0-50 | derived (G2, G12) |
| `prefilter.max_month_turnover` / `max_day_turnover` (P5) | 500 / 50 | 50-5000 / 5-500 | OF |
| `prefilter.min_edge_bps` (P7) | 10 | 0-100 | derived (G10), OF |
| `prefilter.max_month_return` (P8) | 1.0 | 0.2-10 | OF |
| `prefilter.edge_cap_bps` (K1) | 50 | 10-1000 | OF |
| `prefilter.keep_rank_mult` (L3) | 2 | 1-10 | budget |
| `scoring.empty_cooldown_h` (EX2) / `scoring.ineligible_cooldown_h` + `rotate_after_cycles` (RO1) | 168 / 72 + 3 | 24-720 / 6-720 + 1-24 | budget |
EX1 reuses R1's too-active cooldown (24 h constant). The one-day span and the 2,000-row page are API facts or constants, not keys.

## 8. PO decisions needed
1. Adopt option D as the v0 default. This amends F6: "first `candidates_k` rows in served order" becomes "the first `candidates_k` of the
   prefilter ranking" (spec says top-`candidates_k`). F5 does not change. Route: PM amendment, then test-designer, then developer. No reviewer-risk (no gate/broker).
2. Config keys (section 7) or code constants for v0. The project rule "data-driven" favours keys, but each key costs an F1 schema change.
3. Cooldowns: empty 7 d, too active 24 h (keep R1's) or longer, rotation 72 h after 3 ineligible cycles.
4. Run `candidate_rank_check.py` once and send the output. The thresholds above are frozen before that run.
5. Later and optional: research a stage-2 `portfolio` prefilter; decide separately whether `gate.dsr_n_trials` should follow the 47k leaderboard (frozen addendum).

## 9. Variant 2 (2 of max 3): D on the row + a first-page fills screen. PRE-REGISTERED 2026-10-03, before any variant-2 data
Why: run 1 KILLED D (candidate-ranking-run1.md): 14 of 20 were unjudged full pages, and the row did not separate market makers (maker share
>= 0.8 on 8 of 20) or off-universe traders (core share <= 0.15 on 7). The first page of fills does, at <= 120 weight. The screen only decides
who gets the full backfill: no metric, gate, score or FROZEN rule changes (F5.AC6 holds; the gates still decide on the full history).
Notation: `t` = screen time, `ws = t - scoring.window_days`, `AV` = row accountValue. REUSED = existing key and value; NEW = new number.
1. **V1 stage 1** = option D unchanged (P1-P8, K1, L1-L5, EX1-EX3, RO1). Stage 2 runs on the L1 list in K1 order after the L2 skips
   (every cooldown, V5's included). Followed wallets are never screened (they are always scored).
2. **V2 request** = exactly backfill page 1: one `userFillsByTime {user, startTime: ws, aggregateByTime: true}`, <= 2,000 rows, weight
   20 + rows/20 (<= 120), charged to the scoring share. A fetch or schema error is not a rejection: R1's per-wallet error cooldown applies.
3. **V3 features** (that page only): dedupe on (tid, time, coin, sz) as F5; core = `is_core_perp(coin)`; notional = sz x px; `full` = 2,000
   rows; `span_d` = (last - first fill) / 1 d; `core_share` = core notional / all notional; `maker_share` = M13 on the core fills (crossed ==
   false notional / core notional); `first_core` = earliest core fill; `rate` = 2,000 / span_d (full pages). Trips = F5 `reconstruct` on core
   fills (open at the page start: ignored until flat; flips split); a trip still open at the page end is censored with hold = +inf (upper bound).
   `hold_med` = median hold (min) over closed + censored trips = `n_trips`; `n_rt` = closed. `exec_share` = share of those trips with
   open_sz x open_px / AV x `paper.wallet_usd` >= `sizing.min_order_usd` (M16 without the risk cap: an upper bound).
4. **V4 rules** (inclusive; a wallet passes if none fails; n/e = not evaluable/applicable, never a failure):
   - S1 rows >= 1. S2 not (full and span_d < 1). (Variant 1's EX2/EX1, moved into the screen.)
   - S3 `core_share >= prefilter.min_core_perp_share` (0.50, **NEW**).
   - S4 `maker_share <= gate.max_maker_share` (0.70, REUSED, G13's formula; no core notional = fail, closed like G13).
   - S5 `(t - first_core) / 1 d >= gate.min_fill_span_days` (60, REUSED): the page holds the oldest retrievable fills, so this is necessary for G3.
   - S6 (full pages; else n/e) `rate x scoring.window_days < HL_FILLS_LIMIT` (10,000; REUSED R1 constants = 55.6 fills/day at 180 d). It
     predicts R1's `too_active_truncated`, which already drops every wallet with >= 10,000 fills in the window.
   - S7 `hold_med >= gate.min_median_hold_min` (15, REUSED, G8 floor; latency term ignored). S8 `exec_share >= gate.min_executable_share`
     (0.50, REUSED, G12 flavour). Both n/e if `n_trips < prefilter.screen_min_trips` (30, **NEW**).
   - S9 (non-full pages, which hold the whole window; else n/e) `n_rt >= gate.min_round_trips` (150, REUSED: G2's count at t).
5. **V5 outcomes and cooldowns** (keyed by lowercase address; all rules computed and logged even after a failure): S1 fail = `backfill_empty`
   168 h (EX2); S2 fail = `too_active_first_page` 24 h (EX1); any S3-S9 fail = `screen_rejected` (failing ids listed) for
   `prefilter.screen_cooldown_h` (72 h, **NEW** key, RO1's value). After it, a still-ranked wallet is screened again.
6. **V6 order and budget:** screen in K1 order, skipping cooldowns, until `candidates_k` wallets are screened OK (L3 sticky ones count and are
   not re-screened) or `prefilter.screen_max_per_cycle` screens are spent (100, **NEW**, budget only: <= 12,000 weight, ~27 min of the 450/min
   share). The rest wait for the next cycle, in K1 order.
7. **V7 feed:** an OK wallet enters the backfill with the screen page as its page 1 (cursor resumes after its last fill, no refetch); a non-full
   page is the complete backfill (0 more requests). OK stays OK while the wallet remains a candidate (L3). R1 (EX3, error cooldowns), RO1, F5 unchanged.
8. **V8 persist (B5):** per cycle, each screened wallet's features, per-rule pass/fail/n/e, outcome and cooldown end, plus fail counts per rule.

**Bias (honest).** Above 2,000 fills in the window, the page is the OLDEST 2,000 of the latest <= 10,000: every feature describes the start
of the retrievable history, not today. Rate: wallets whose activity rose (likely: stage 1 selects recent volume) look slower, so S6 is lenient
(R1 still drops them, ~5 pages wasted); wallets that slowed look faster (false reject, re-screened after 72 h). A style change since the page
(maker, core, hold) is missed; G13/G8 on the full history still catch the harmful direction. Censoring is resolved upward (+inf), so S7 never
rejects because of where the page ends. `exec_share` uses today's AV for old opens: grown wallets get understated sizes (false-reject bias).
**Why the NEW numbers.** S3 0.50: the stage-1 evidence (row pnl, vlm) is account-wide; under half of the notional in our universe means the
row's edge is mostly not the edge we would copy (G12's "at least half copyable" logic). 30 trips: a wallet with a true median hold of 30 min
(2x the floor, lognormal sigma 1.5) is wrongly rejected with p ~ 0.03 at 30 trips (0.07 at 20, 0.19 at 10). 72 h and 100: budget only.

**Pre-registered validation (D4; rules and numbers frozen before any variant-2 data).**
- Data: D ranks **21-40** of the SAME snapshot as run 1 (oldest file in `research/data/candidate_ranking/`): all unseen, ranks 1-20 excluded
  (no tuning on seen data). Fills are fetched at run time. `n` = valid fetches (n < 16 = INCONCLUSIVE, rerun); `pass` = wallets passing S1-S9.
- COPYABLE (survivors; verdict-only, **NEW**, never config), all of: c1 >= 80% of survivors had S7 and S8 evaluated (not passing by default);
  c2 median survivor `hold_med` >= 30 min (2x the G8 floor); c3 median survivor `maker_share` <= 0.50; c4 median survivor `exec_share` >= 0.70.
- **PASS:** pass >= ceil(0.5 n) (10 of 20) AND c1-c4. **KILL:** pass < ceil(0.3 n) (6 of 20). **PARTIAL:** otherwise (incl. >= 10 but not copyable).
  PASS -> PM amendment (F6) -> test-designer. PARTIAL/KILL -> at most ONE more variant (3 of 3), pre-registered here first; if it fails too,
  keep served order + EX1/EX2 only. Info only: `--baseline` screens served-order rows 21-40 with the same rules (D5 naive baseline).
- Run (PO, bot stopped, ~2-4 min; >= 3 s between calls, 6 s after a full page to stay under 1,200 weight/min):
  `uv run python docs\sdlc\copytrade-v1\research\scripts\candidate_screen_check.py` (self-test `--selftest`); send back the SUMMARY block.
- Config (PM; NEW keys are F1 schema changes): `prefilter.min_core_perp_share` 0.50 (0.1-1, OF), `prefilter.screen_min_trips` 30 (10-200, OF),
  `prefilter.screen_cooldown_h` 72 (6-720), `prefilter.screen_max_per_cycle` 100 (10-1000). REUSED: `gate.max_maker_share`,
  `gate.min_fill_span_days`, `gate.min_median_hold_min`, `gate.min_executable_share`, `gate.min_round_trips`, `scoring.window_days`,
  `paper.wallet_usd`, `sizing.min_order_usd`; constants HL_FILLS_LIMIT and the 2,000-row page.
