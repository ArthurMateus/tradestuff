# Market context for copytrade-v1 (REQUIREMENTS mode)

Date: 2026-09-29. Author: market-analyst. Builds on `brainstorm-domain-research.md` (not repeated here).

Method note and limits of this document:
- Primary docs (hyperliquid.gitbook.io, federalreserve.gov, bls.gov, bea.gov) were **blocked by the sandbox egress proxy**. Every Hyperliquid and calendar figure below comes from web-search snippets that quote or mirror the primary docs. Status per row: `[S]` = seen in search snippet quoting the official doc or agency page; `[T]` = third-party only; `not found` = not located.
- Before the PM freezes any number into a config default, an agent with network access should re-verify the `[S]`/`[T]` items against the primary page. Section 6 lists which.
- Interpretation is labelled as such. No trade calls.
- Times: UTC and America/Sao_Paulo (BRT, UTC-3, no DST since 2019). US Eastern moves to EST on 2026-11-01, so **US event times shift 1 hour in UTC and BRT terms after that date**.

## 1. Market structure the feature must respect

### 1.1 Hyperliquid perps: facts

| Topic | Fact | Source / status |
|---|---|---|
| Trading hours | Perps trade 24/7. No session close for core crypto perps. | [S] Hyperliquid docs (general); no schedule found |
| Funding interval | Funding accrues and is paid **every hour** (not 8h). | [S] docs "Funding" page, via search 2026-09-29 |
| Funding formula | `F = avg premium index (P) + clamp(interest rate - P, -0.0005, +0.0005)`. Premium sampled every 5 s, averaged over the hour. | [S] docs "Funding" page, via search |
| Funding interest component | Fixed 0.01% per 8h-equivalent (i.e. 0.00125%/h). | [T] Dwellir guide, via search (the formula itself is [S]) |
| Funding cap | 4% per hour cap in extreme conditions; typical range about -0.01% to +0.01% per hour. | [T] Dwellir guide, via search. Re-verify vs docs. |
| Base perp fees (tier 0) | Maker 0.015%, taker 0.045%. | [T] multiple guides; consistent across 5+ results |
| Volume tiers (14-day, perps + 2x spot volume) | $5M: 0.012/0.040; $25M: 0.008/0.035; $100M: 0.004/0.030; $500M: 0.000/0.028; $2B: 0/0.026; $7B: 0/0.024 (maker/taker %). | [T] HyperMirror/OneKey-type guides via search. Irrelevant at our $300 size: **tier 0 applies**. |
| Staking discount | Up to 40% for HYPE stakers; referral discount 4%. | [T] |
| HIP-3 fees | About 2x standard perp fee on builder-deployed markets. | [T] Datawallet via search |
| Minimum order value | $10 notional (exception: exactly closing a position with reduce-only). | [T] Chainstack / guide snippet. Re-verify vs docs. |
| Price tick rule | Max 5 significant figures **and** at most `MAX_DECIMALS - szDecimals` decimals; `MAX_DECIMALS = 6` for perps. Integer prices always allowed. | [S] docs "Tick and lot size" via search |
| Lot (size) rule | Size is rounded to the asset's `szDecimals` (from `meta` / `metaAndAssetCtxs`). Per-asset values: not enumerated here; read from `meta` at startup. | [S] |
| Max leverage | Per asset, from `meta` (`maxLeverage`). Not enumerated here. | [S] field name; values `not found` in this pass |
| Margin modes | Cross and isolated. HIP-3 markets are isolated-only. | [T] HIP-3 guides via search |
| Maintenance margin | Half of the initial margin at the asset's max leverage (e.g. 2.5% of notional when max leverage is 20x). Tiered by notional per asset. | [S] docs via search |
| Isolated liquidation | The whole isolated position is liquidated when its collateral hits maintenance margin (no partial-liquidation step). On backstop liquidation the isolated margin is transferred to the liquidator and the maintenance margin is not returned. | [S] docs "Liquidations" via search |
| ADL | Exists. First ADL in over two years occurred on 2025-10-10. | [T] CoinDesk / CoinShares via search |
| Delisting behaviour | Validators vote; since Mar 2025 the vote is on-chain and executes automatically at quorum. JELLY (2025-03-26) was force-settled at $0.0095 and delisted. | [T] Cryptopolitan, CryptoRank via search |
| Coin naming | Builder-deployed (HIP-3) markets carry a dex prefix (e.g. `xyz:`); a wallet's fills can therefore include instruments outside the core universe. Exact naming: `not found` in this pass. | [T] partial |

### 1.2 Implications for the spec (interpretation, labelled as such)

- **Paper fees must use tier 0 taker/maker 0.045%/0.015%**, configurable, with a separate HIP-3 multiplier (interpretation: roughly 2x).
- **Funding is hourly**, so paper PnL must accrue funding per hour boundary (UTC top of hour), using the actual funding rate history (`fundingHistory`), not a daily estimate. Position held across the hour pays or receives; a position closed before the boundary does not.
- **$10 minimum notional at $300 equity and 1% risk**: at 1% risk of $300 = $3 at risk. With a stop 2% away, notional = $150; with a stop 5% away, notional = $60. Interpretation: small-account copies are executable for most signals, but tight-stop or 0.3% sized copies will not be, and the "unexecutable" log will be non-trivial. Leader-fraction sizing on a $300 wallet may routinely land under $10 for small leader positions. The PM should specify the rounding rule (round down to lot, reject below $10) and count these as a reportable metric.
- **Price rounding**: 5 significant figures rule means BTC-like prices tick at $1, low-priced alts finer. Paper fills must round to the same rule so a live port does not change behaviour (A6).
- **Isolated liquidation is total loss of the position margin.** At 3x default, liquidation is roughly 33% adverse minus maintenance (interpretation), far outside a 2xATR stop, so liquidation should occur only through gaps or halted books. The paper engine still needs a liquidation model (A8) using mark price and per-asset maintenance margin, because 5x/10x ceilings shrink that distance.
- **Liquidation price and mark price**: liquidation is triggered on mark price, not last trade. Paper engine must store mark price alongside last price. `not found`: the exact mark-price formula in this pass.
- **Delisting**: a followed wallet can hold a delisted coin. The paper engine needs a "force-settled at exchange price" close reason, distinct from SL/TP and from trader exit (A8, C4).

### 1.3 Incident and maintenance history (dated)

| Date (UTC) | Event | Effect | Source |
|---|---|---|---|
| 2025-03-26 | JELLY manipulation, validator delist vote, force-settle at $0.0095 | Positions settled off-market | [T] X post by Hyperliquid quoted in search; Cryptopolitan |
| 2025-07-29/30, 14:10-14:47 UTC | API server overload from traffic spike (about 37 min of trading downtime); chain and consensus kept producing blocks; automated refunds | API errors while the chain was up | [T] The Block, CoinMarketCap via search |
| 2025-10-10 | $19B market-wide liquidation event. Hyperliquid OI fell from about $14B to about $6B; over $10B force-closed; ADL used ($2.1B in 12 min); about $64M reached the book in the worst minute | Books thin, spreads wide, price gaps | [T] CoinDesk, CoinShares, CryptoSlate via search |
| 2025-10-13 | HIP-3 builder-deployed perps live on mainnet | New instruments appear in wallets' fills | [T] |
| 2026-09-26, 08:30 UTC (05:30 BRT) | Scheduled network upgrade, about 10 min expected downtime | Planned downtime | [T] incidenthub.cloud via search; primary status page `hyperliquid.statuspage.io` not fetched |
| 2026 (other) | `not found` beyond the above | | |

Interpretation: the July 2025 event shows the API can fail while the chain is healthy, so the feed-loss logic (freeze entries, reconcile on reconnect) must key off data freshness, not only socket state. The October 2025 event is the stress scenario the paper engine's slippage and liquidation model should be tested against (stress fixture: Oct 10 2025 ~21:00 UTC onward; exact minute range `not found`).

## 2. Hyperliquid API facts that gate replay and scoring

### 2.1 Leaderboard

| Item | Fact | Status |
|---|---|---|
| Endpoint | `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard` (GET, JSON, unauthenticated). Not in the official docs. | [S/T] Hyperliquid client code and scrapers referenced via search |
| Payload | Array of up to about 15,000 rows: `ethAddress`, `accountValue`, `displayName` (optional), `prize`, `windowPerformances` = pairs for `day`, `week`, `month`, `allTime`, each with `pnl`, `roi`, `vlm`. | [T] Apify scraper docs via search |
| Windows | 24h, 7d, 30d, allTime only. **No 90d/180d window.** | [T] |
| Limits | Not documented. Stability, update cadence and rate limit: `not found`. No 2026 breaking-change report found in this pass. | not found |
| Self-reported? | `pnl`/`roi` are exchange-computed account figures, not fills. Invariant C1 says score on verified fills; the leaderboard is a **candidate list only**. | interpretation |

Implications:
- The leaderboard cannot give the 90-180 day track record the brainstorm research wants. The scorer must build it from fills (below), so the 200-candidate scan costs API weight (see 2.3).
- Snapshot the full leaderboard JSON hourly from day 1 (about 15,000 rows; size per snapshot `not found`, plan on a few MB compressed) so replay stays point-in-time (Q6). `allTime` `roi` is survivorship-laden; ranking on it alone is the "top N by raw ROI" naive baseline (D5).
- Third-party leaderboard APIs exist (Nansen, HyperTracker/CoinMarketMan) but are paid; not needed for v1.

### 2.2 Fill history depth

| Item | Fact | Status |
|---|---|---|
| `userFills` | Returns at most **2,000** most recent fills per response. | [S] docs via search |
| `userFillsByTime` | `startTime` ms inclusive, optional `endTime`; **max 2,000 fills per response; only the 10,000 most recent fills per address are available.** | [S] docs + Chainstack via search |
| Consequence | History depth is fill-count-bound, not time-bound. A busy scalper's 10,000 fills may cover days; a swing trader's may cover years. A wallet's window is measured in fills. | interpretation |
| Older history | S3 archive `s3://hl-mainnet-node-data/` (`node_fills`, `node_fills_by_block`, `node_trades`, `explorer_blocks`) and `s3://hyperliquid-archive/` (`market_data` L2 snapshots, `asset_ctxs`). **Requester-pays**, uploaded about monthly, "no guarantee of timely updates and data may be missing". | [S] docs "Historical data" via search |
| Third party | Hydromancer offers a free S3 archive reservoir and a historical API (pricing `not found`). | [T] |
| Fill fields | Per fill: coin, px, sz, side, time, startPosition, dir (e.g. Open Long / Close Short / Long > Short), closedPnl, hash, oid, crossed, fee, tid, feeToken. Verbatim field list not re-verified (Chainstack blocked). | [T] |
| Candles | `candleSnapshot`: only the most recent **5,000** candles per interval (1m gives about 3.5 days; 1h about 208 days; 1d about 13.7 years). | [S] |
| Funding history | `fundingHistory` (market) and `userFunding` (wallet) exist; extra weight per 20 items. | [S] |

Implications:
- Reconstruction after downtime (flow 9) at 1m resolution is safe only for gaps under about 3.5 days; longer needs 5m/15m candles or the S3 archive. Cap the gap at a config value and flag "unreconstructable" beyond it.
- Replay of leader fills before our own recording began can use `userFillsByTime` per wallet (bounded by 10,000 fills) and candles for prices, labelled "indicative only" (brief flow 8). The replay cannot know which wallets were ranked top at that time (survivorship), so that label is correct.
- Order-book depth for replay slippage is not available historically through the API; only S3 `l2Book` snapshots (monthly, requester-pays, may be missing). Interpretation: replay slippage will be model-based (spread + fixed bps) unless we record our own L2 snapshots from day 1. That is a data-collection requirement for the PM: **record top-of-book/L2 snapshots for traded coins from day 1.**

### 2.3 REST and WebSocket limits (rate budget)

| Limit | Value | Status |
|---|---|---|
| REST aggregate | **1,200 weight per minute per IP** | [S] docs "Rate limits" via search |
| Info weights | `l2Book`, `allMids`, `clearinghouseState`, `orderStatus`, `spotClearinghouseState`, `exchangeStatus` = 2. **All other documented info requests = 20**, including `userFills`. | [S] |
| Extra weight | `userFills`, `userFillsByTime`, `fundingHistory`, `userFunding`: +1 per 20 items returned; `candleSnapshot`: +1 per 60 items. | [S] |
| WS connections | **10 per IP**; **30 new connections per minute**. | [S] |
| WS subscriptions | **1,000 total across all connections from one IP** (opening more connections does not raise it). | [S] |
| WS unique users | **10 unique users across user-specific subscriptions** (per IP, per the docs' phrasing; the brainstorm note "10 users per connection" is a paraphrase of this). | [S]; the per-IP vs per-connection scope should be re-checked against docs |
| WS messages | 2,000 messages sent to Hyperliquid per minute across all connections; 100 simultaneous in-flight POSTs over WS. | [S] |
| Reconnect | Disconnects "may happen periodically and without announcement"; data missed during a reconnect is included in the snapshot ack on resubscribe (`isSnapshot: true`), except `orderUpdates`/`userEvents`, which do not replay a snapshot. Manually query the info endpoint for gaps. | [S] docs + SDK issues via search |
| Heartbeat | Inactivity timeout (about 60 s) and `{"method":"ping"}`: not confirmed in this pass. | not found |

Budget arithmetic for the PM (facts + arithmetic):
- **Following 10 wallets fits the 10-unique-user cap exactly, with zero headroom.** The 10 followed wallets consume all user-specific slots, so any additional per-user WS subscription (for example a candidate wallet, or a wallet being swapped in at the moment another is still subscribed) fails. The hysteresis swap must **unsubscribe the outgoing wallet before subscribing the incoming one**, or the design must cap follows at 9 with 1 slot reserved for the swap. That is a spec decision (Question 1).
- Subscriptions used: 10 wallets x (`userFills`, optionally `userEvents`/`orderUpdates`) = 10-30; order books: `l2Book` per traded coin (perhaps 20-40 coins) plus `allMids` (1) and possibly `trades`. Total is well under 1,000. Subscription count is not the binding limit; the 10-user cap is.
- Only the followed wallets need the WS. The 200 candidates are polled over REST.
- Candidate scan cost: one `userFills` call = 20 weight + 1 per 20 fills. A full 10,000-fill history = 5 pages of 2,000 = 5 x (20 + 100) = 600 weight. Scanning 200 candidates once = about 120,000 weight = **100 minutes of the full 1,200/min budget** if every candidate is fetched in full. Hourly re-scoring of all 200 is therefore impossible with full pulls. Design consequence (interpretation): incremental fetch (`userFillsByTime` from the last seen `time`, usually 1 page = about 20-21 weight), giving 200 x 21 = 4,200 weight per hourly cycle = 3.5 minutes of budget; plus a first-time backfill amortised over many hours; cap REST use at a config fraction (for example 50%) to leave headroom for the followed wallets' reconciliation and the `l2Book` snapshots.
- REST budget is per IP and shared with everything else on the PC's IP. Home CGNAT or a shared IP in Brazil can be shared with other Hyperliquid users (`not found`, flag as risk).

### 2.4 Latency from Brazil

- Validators and API sit in AWS Tokyo (`ap-northeast-1`), API fronted by CloudFront. Tokyo-local raw latency 2-3 ms; users in Europe and North America reportedly see about 200 ms more. [T] Glassnode latency monitor, CryptoNomist 2026-03-30 via search.
- **Brazil-specific latency: not found.** Interpretation: Brazil to Tokyo is one of the longest great-circle paths, so 250-350 ms one-way is plausible but unmeasured. This is the 1-day latency measurement the PO already planned; Glassnode's latency monitor is a free cross-check. The 5 s freshness cut-off is not threatened by network latency on the order of 0.3 s; the risk is bursts and reconnects, not steady-state RTT.
- Median order-to-fill latency from Tokyo is about 884 ms per Glassnode (mostly server-side). Paper trading avoids this, but the paper fill model should include a configurable synthetic delay (detection latency + our decision + simulated ack), because live would pay it. Interpretation: a copy fill has at least "leader fill time + detection latency" of slippage exposure; the 3x-cost edge rule from the quant research applies.

## 3. Events that change risk

Facts (scheduled) and requirements for configurable blackout windows. Requirement-level only; no strategy.

### 3.1 Scheduled macro events, next 60 days (from today, 2026-09-29)

| Event | Date and time | UTC | BRT | Status |
|---|---|---|---|---|
| CPI (Sept data) | Thu 2026-10-08, 08:30 ET (EDT) | 12:30 | 09:30 | [S] BLS schedule page snippet (`bls.gov/schedule/2026/10_sched_list.htm`) via search; primary not fetched |
| Employment Situation / NFP (Sept data) | Fri 2026-10-09, 08:30 ET | 12:30 | 09:30 | [S] same |
| FOMC decision (Oct meeting is Oct 27-28) | Wed 2026-10-28, 14:00 ET (EDT) | 18:00 | 15:00 | Meeting dates [S] federalreserve.gov snippet; 14:00 ET statement time [S]. Press conference about 14:30 ET: not confirmed. |
| PCE (Sept data) | date `not found` (BEA schedule not seen; typically end of month) | | | not found |
| PCE (Oct data) | Wed 2026-11-25, 08:30 ET (EST) | 13:30 | 10:30 | [T] financecalendar.com via search; verify at bea.gov |
| CPI (Oct data), NFP (Oct data, early Nov) | `not found` in this pass | | | not found |
| FOMC decision (Dec meeting is Dec 8-9, with SEP) | Wed 2026-12-09, 14:00 ET (EST) | 19:00 | 16:00 | Dates [S]; times derived |

US clocks fall back on 2026-11-01. Any blackout config must anchor events to `America/New_York` and convert at runtime, not store fixed UTC offsets.

Recommended blackout windows (from the brief; window sizes are the PO's; this doc only recommends which events drive them):

| Event class | Window (brief default) | Note |
|---|---|---|
| FOMC decision | -30 / +60 min | Also consider the press conference (+30 min after the statement) inside the +60 |
| CPI, PCE, NFP | -15 / +30 min | |
| PPI, GDP (advance), retail sales | -5 / +15 min, **size reduction only** rather than a full pause | Lower-tier; brainstorm research listed PPI/GDP |
| Fed chair speeches, FOMC minutes | not a blackout; optional size reduction | Minutes are published 3 weeks after each meeting: date `not found` |

Interpretation: BTC reacted negatively after 7 of 8 FOMC meetings in 2025 (from the brainstorm research; not re-verified here). The point is that the leader's trade could be a headline trade, so the blackout is applied to **our** entry, not to closes. Requirement for the PM: blackout **blocks new entries and adds only**; closes, reductions, SL/TP and reconstruct paths remain live (C4 and "never leave an orphaned position").

### 3.2 Crypto-specific events

| Event | Facts | Recommended treatment |
|---|---|---|
| HYPE team token unlock | Core-contributor vesting: about 238M HYPE over 24 monthly tranches (about 9.92M/month) on the **6th of each month** (first credited 2026-01-06; scheduled full emission 2024-11-29 to 2029-11-29). Claim rate has been very low in prior months. [T] Tokenomist, CoinSpot via search. Next: 2026-10-06 (about 15:00 UTC assumed; time `not found`). | Optional per-symbol size reduction on HYPE only; not a global blackout. Interpretation: low priority. |
| Other coin unlocks affecting copied alts | Depends on which coins the leaders trade. Source: Tokenomist / DefiLlama unlocks (free). | Optional per-symbol config list `symbol_blackouts` loaded from a data file; do not build an unlock feed in v1. |
| Exchange incidents (Hyperliquid API outage, scheduled upgrade) | See 1.3. Scheduled upgrades announced on the status page; automation of that feed: `not found`. | Requirement: a **feed-freshness circuit breaker** (B1/B3) plus an operator-set manual `maintenance_window` config. |
| Delisting votes | On-chain validator vote; the notice period is `not found`. | On a delist event for a held coin: close reason `delisted_force_settle`. |
| Mass-liquidation / ADL cascades (2025-10-10) | See 1.3 | Handled by regime filters (section 4), not a calendar. |
| Spot BTC/ETH ETF flow days | Daily flow data exist (Farside, free); no scheduled event. | Not recommended as a blackout: it is a data series, not an event. |
| Weekend and holiday thin liquidity | Perps trade 24/7 but US-hours-driven depth thins on weekends and US holidays (interpretation, not measured here). | Use the spread/depth filters instead of a calendar. |
| HIP-3 equity perps | Equity and commodity perps trade 24/7 but oracle prices can lag outside US market hours [T]. | If followed wallets trade HIP-3 markets: **recommend excluding HIP-3 markets in v1** via an `allowed_dexes` config defaulting to core only (see Question 3). |

### 3.3 Brazil-specific

- **2026-10-30**: BCB deadline for unauthorised foreign crypto providers to stop (from the brainstorm research; not re-verified here). Interpretation: it does not change Hyperliquid's data access for a paper run, but it is 31 days after today, and the paper month straddles it. Kill criterion "data access becomes unavailable or prohibited" applies. Recommend a manual check of Hyperliquid's geo-blocking on 2026-10-30 and after, and an alert if the API returns 403/451 or a region block page (`not found`: Hyperliquid's current Brazil status).
- BRL exposure is out of scope (USD everywhere), so COPOM and IPCA blackouts are **not recommended** for v1. COPOM dates: `not found`; not needed.

## 4. Regime signals worth tracking (filters)

All are available from Hyperliquid's own endpoints at $0 unless noted. Use as **filters** (skip/size-down), not as signals.

| Signal | Source (Hyperliquid) | Filter use | Caveat |
|---|---|---|---|
| Realised volatility (e.g. 1h/24h on 1m/5m returns; ATR(14)) | `candleSnapshot` (5,000-candle cap) or our own trade/mid recording | Percentile vs trailing window; size x 0.5 above a config percentile (brief); ATR drives the stop | Percentile lookback is limited by the candle cap for 1m; use 1h candles for long lookbacks |
| Implied vol | Deribit DVOL for BTC/ETH (public API, free) | Optional stress flag for majors | Not available for most alts; `not found` for HL-specific IV |
| Funding rate | `metaAndAssetCtxs` (current), `fundingHistory` | Skip or size-down when funding is extreme in the direction of the copied trade (cost), and treat extreme funding as crowding | Hourly funding: compare on a per-hour basis. Extreme threshold per asset: `not found`, needs calibration from our data |
| Open interest | `metaAndAssetCtxs` (`openInterest`) | Sudden OI collapse = liquidation cascade regime (Oct 2025: -57% in a day); pause entries | Snapshot cadence must be recorded by us; no history API (S3 `asset_ctxs` monthly) |
| Liquidity and spread | `l2Book` (weight 2) or WS | Reject if spread or depth-within-0.5% fails (brainstorm limits: spread <= 0.1%/0.3%, order <= 1% of depth) | At $300, order size is negligible vs depth on majors; matters for thin alts |
| Mark-oracle divergence / premium | `metaAndAssetCtxs` (`markPx`, `oraclePx`, `premium`) | Skip when premium spikes (squeeze conditions like JELLY) | Threshold: `not found`, calibrate |
| Leader's own fill vs mid | fills vs `allMids` | Slippage guard (already in brief) | |

Interpretation: with a 5 s copy cutoff, most regime filters serve as a **coarse "stressed" flag** (vol percentile, OI drop, spread blowout) to feed the brief's "calm/normal/stressed" label and size reduction. Thresholds must be config with values calibrated from the first week of recorded data, not hard-coded from folklore. Record every one of these series from day 1 (a data-collection requirement, cheap).

## 5. Data sources ($0-50/month)

| Need | Source | Access | Latency | Rate limits | Reliability notes |
|---|---|---|---|---|---|
| Leader fills, live | Hyperliquid WS `userFills` (`wss://api.hyperliquid.xyz/ws`) | Free, no key | Sub-second inside Tokyo; Brazil unmeasured | 10 unique users; 1,000 subs; 10 conns per IP | Silent disconnects; snapshot-on-resubscribe replays gaps for `userFills`; API can fail while the chain is up (2025-07-29/30) |
| Leader fills, history | `POST https://api.hyperliquid.xyz/info` `userFillsByTime` | Free | ~100s ms | 1,200 weight/min/IP; 20 + 1 per 20 items | Max 2,000 per response, 10,000 most recent per wallet |
| Leaderboard (candidates) | `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard` | Free, undocumented | Not measured | Not documented | Can change without notice; fail-closed per brief. Hourly snapshot to our own DB. |
| Leader account value / positions | `clearinghouseState` (weight 2) | Free | | Counts in the 1,200 | Needed for the leader-fraction sizing (position / account). Note: account value from `clearinghouseState` vs leaderboard `accountValue` may differ in timing. |
| Order book, mids | WS `l2Book`, `allMids`; REST `l2Book` (weight 2) | Free | | Subs count towards 1,000 | Snapshots only via S3, so record ourselves |
| Asset contexts (funding, OI, mark, oracle) | `metaAndAssetCtxs` (REST) | Free | | Counts in the 1,200 | Record every N seconds from day 1 |
| Funding history | `fundingHistory`, `userFunding` | Free | | +1 per 20 items | Needed for the paper funding accrual and reconstruction |
| Candles / ATR | `candleSnapshot` | Free | | +1 per 60 items | 5,000-candle cap per interval |
| Deep history (L2, fills, asset ctxs) | S3 `hyperliquid-archive`, `hl-mainnet-node-data` | Free bucket, **requester pays** egress (AWS) | Batch | n/a | Updated about monthly, may be missing. Cost not estimated (`not found`); a 1-month L2 pull may exceed a $0-50 budget without care, so budget-cap it. |
| Third-party HL data | Hydromancer (free S3 reservoir + API), HyperTracker/CoinMarketMan, Nansen | Free tiers exist; paid `not found` | | `not found` | Optional; adds vendor dependency. Not needed for v1. |
| Funding / OI cross-exchange | CoinGlass API | **Paid: $29 / $79 / $299 / $699 per month**; 30 / 80 / 300 / 1,200 req/min (per dev.to review and pricing pages as of 2026-07-08) | | | Not needed for v1: HL's own data are the venue's truth. Skip. |
| Implied vol (BTC/ETH) | Deribit public API (DVOL) | Free | | Public limits `not found` | Optional stress flag |
| Macro calendar | Fed (federalreserve.gov FOMC calendar), BLS schedule, BEA schedule | Free; static data file updated quarterly (brief) | n/a | n/a | Primary sources; re-verify each quarter. Finnhub economic calendar: free tier exists but the calendar may sit on a paid plan: `not found` |
| Token unlocks | Tokenomist, DefiLlama Unlocks | Free web/API tier `not found` | | | Optional |
| HL status | `hyperliquid.statuspage.io` | Free | | | Announce scheduled upgrades; automation `not found` |
| Latency reference | Glassnode Latency Monitor (`latency.glassnode.com/hyperliquid`) | Free | | | Cross-check only, not from Brazil |
| FX (not needed) | | | | | USD everywhere per Q19; no source needed |

Budget note (facts and arithmetic): every mandatory source above is $0. The LLM cap and any S3 egress are the only variable costs. Nothing in this table needs the $50 headroom.

## 6. Verification backlog (for an agent with network access)

Items that are `[T]` or `not found` and would change a config default or a spec decision:
1. Primary rate-limits page: WS unique-user scope (per IP vs per connection), heartbeat timeout and ping message.
2. Funding cap (4%/h) and interest component value in the primary Funding page.
3. $10 minimum order value in primary docs; per-asset `szDecimals` and `maxLeverage` table via `meta`.
4. BLS/BEA pages for CPI/PPI/NFP/PCE dates through Dec 2026 (and PCE for Sept data); FOMC press-conference timing.
5. Leaderboard endpoint payload verified with one live GET (schema, size, update cadence).
6. Brazil-to-Tokyo RTT and CloudFront edge selection from the PO's PC.
7. Hyperliquid terms and geo-block status for Brazil around 2026-10-30.
8. Mark-price formula and per-asset margin tiers, for the paper liquidation model.

## 7. Questions for the PO (market perspective)

1. **Wallet cap of 10 and swapping.** The 10-unique-user WS limit equals your "hard max 10". Do you accept following at most 9 at steady state (1 slot reserved for the hysteresis swap), or a brief gap in coverage of the outgoing wallet during a swap?
2. **Candidate scan budget.** A full history pull for 200 candidates costs about 100 minutes of the whole REST budget. Are you OK with a slow first-time backfill (for example spread over 12-24 h before the bot follows anyone), and with re-scoring done incrementally?
3. **HIP-3 markets (equities, commodities, FX perps).** Leaders may trade them, at roughly 2x fees and with 24/7 pricing off an oracle that can lag outside US hours. Exclude in v1 (recommended, default `allowed_dexes = core`), or copy them?
4. **Wallets with fewer than 10,000 fills of history vs more.** History is fill-count-bound. Should high-frequency wallets (10,000 fills = a few days) be excluded as uncopyable, or scored on their recent window only? Minimum required calendar span and fill count for eligibility?
5. **Tiny positions.** With $300 and the $10 minimum, many mirrored sizes will be unexecutable. Should the bot **round up to $10** when risk allows, or always log "unexecutable" (brief says the latter)? And how many unexecutable signals are acceptable before you call the wallet-size assumption invalid?
6. **Record-from-day-1 data.** Do you approve recording L2 snapshots, mark/oracle/funding/OI contexts and mids for all coins the followed wallets touch (and the leaderboard hourly)? Needed for honest replay slippage; adds disk and some REST weight.
7. **Blackout scope.** Do blackouts block only new entries and adds (recommended), or should they also block copies of closes? And should minor releases (PPI, GDP, retail sales) reduce size rather than pause? Should the Fed press conference and the FOMC minutes (3 weeks later) have windows?
8. **Blackouts at the Oct 8-9 and Oct 28 events.** These fall inside the first month of the paper run if it starts in early October. Do you want the first week's data excluded from the go-live sample, or included with blackouts applied? (This changes the trade count for the 300-trade gate.)
9. **2026-10-30 Brazil deadline.** Do you want an automatic check and alert if Hyperliquid API access degrades or geo-blocks around that date, and should that pause the run or only alert?
10. **Home connection.** Is the PC on a fixed home broadband or CGNAT/shared IP? Shared IPs share the 1,200 weight per minute with other Hyperliquid users, and a VPN or a small VPS in Tokyo would change the latency picture (the brief excludes cloud hosting; is a $5 VPS for the market-data feed only acceptable within the $0-50 budget?).
11. **Delisting and force-settle.** If a followed wallet holds a coin that gets delisted, force-settle at the exchange price and count it as a normal trade, or exclude it from the R statistics? (Brief says never exclude losers, so recommended: include.)
12. **Funding treatment in R.** Confirm funding is charged hourly in the ledger, using the actual funding history, and included in R (brief says net of funding).

Informational only. Not investment advice.
