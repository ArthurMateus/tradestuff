# v0 rethink brief (PO answers, 2026-10-05)
Written so an agent with ZERO context can act on it. Epic branch: epic/copytrade-v1 (no new epic: the rethink is an addendum). Paper mode only; no agent ever places a live order or touches live keys.

## Goal
Prove, in PAPER mode, that copy-trading a small set of automatically chosen Hyperliquid wallets can profit after fees, funding and slippage. Success = a viable, working v0 the PO can leave running 2-4 weeks. The PO has spent a lot on this app already: it must WORK; the priority is a working end-to-end loop, not more machinery.
## What the PO wants from v0 (verbatim intent)
- At most 7 followed wallets at any time, chosen and ranked by the BOT by scoring each wallet individually (win rate, PnL, number of trades, consistency across the main coins and some memecoins).
- Follow every trade of a followed wallet, sized as a small % of the PO's wallet, ideally by a script that computes how much % of the wallet each trade is worth, minimising risk.
- Daily/weekly re-scoring of the followed set; underperformers are kicked out and replaced.
- Long and short, leverage up to 10x depending on coin, trader and profitability/risk.
- Open and close copies with at most 5 s gap (less is better); track when the leader adds to or reduces a position.
- Venue: Hyperliquid (the PO wrote "hypertrade"; Hyperliquid assumed). Capital: $300 at the start. Risk wanted: "10/20% per trade, 5% of the whole wallet per day". Paper for 2-4 weeks first.
- The bot picks the leaders (no manual list). The PO does not care whether ranking is a script or an LLM, but asked which is better (answer below).
## Answer: script or Claude for ranking wallets (CTO recommendation)
A deterministic Python script decides (it already exists: F5 scoring + F6 selection): reproducible, testable, free per run, auditable, no run-to-run drift, and it feeds the risk gate. Claude/LLM is allowed as an OPTIONAL read-only analyst (weekly report/explanations of why a wallet was kicked) that never changes the followed set or places orders: non-deterministic and costs usage. Decision to confirm with the PO.
## What already exists (epic/copytrade-v1, verified together: 5652 tests passed)
Risk gate (F10), paper broker with restart safety (F11), position manager with adds/reductions, stop/TP, flatten (F12), Telegram bot (/status /positions /pause /resume /flatten, trade posts, alerts) (F14), runner `uv run copytrade run` with ledger replay and clean stop (R0), websocket connector (W0), recorder, scoring F5 and selection F6 (leaderboard -> prefilter -> first-page screen -> backfill -> scoring -> follow), R1-R5 live-run fixes. The ledger is JSON lines in copytrade-data\ledger.
## Mapping of the PO's wants to the existing config (config/*.toml): GAPS TO DECIDE
- Max followed wallets: select.max_followed = 9, min_followed = 5 -> set 7 (config change only).
- Rescoring cadence: scoring.interval_min = 60 (hourly), hysteresis join/drop rank 8/15, confirm cycles 2, min_follow_hours 24, leader_pause max_copy_dd 0.10 / max_consec_losses 5 -> daily/weekly drop of underperformers must be confirmed against these rules (a weekly performance review rule may need an addition).
- Long and short: supported by the paper broker/manager (both sides).
- Leverage: risk.max_leverage_high_tier = 10 for BTC/ETH/SOL, max_leverage_alt = 5 for other coins (PO wants up to 10x by coin/trader/profitability: decide whether to raise alt to 10 for memecoins or keep 5; leverage never exceeds the stop-liquidation-distance rule min_liq_distance_stop_mult = 3).
- RISK MISMATCH (PO must clarify): current limits are per_trade_fraction 0.5%, max_share_risk_fraction 1% (ceiling 2%), max_total_open_risk 5%, daily_loss_limit 2%, weekly 5%, leader_allocation 30%. The PO asked for "10/20% risk per trade and 5% per day". 10-20% of the wallet at risk PER TRADE is 10-40x the current setting and beyond the config ceiling (risk.max_share_risk_fraction allowed 0.5-2%): with a 5% daily limit a single stopped-out trade would breach the day. Probable meaning (to confirm): position size = 10-20% of the wallet (notional or margin), with the stop-loss risk much smaller, and a 5% daily loss limit. Pushback recorded: a stop-loss risk of 10-20% per trade on $300 is a ruin path; recommend risk per trade 1-2% of the wallet.
- $300 wallet: minimum order on Hyperliquid is $10 notional (sizing.min_order_usd = 10, partial_below_min_action skip_and_log): copies smaller than $10 are skipped and logged: with $300 and 1% risk that is common; the PO should expect skipped copies.
- Latency <= 5 s open/close: not yet measured on the PO's PC (Brazil); the detector/latency instrumentation exists (F7); must be measured in the smoke test and reported.
- Adds/reduces by the leader: handled by F12 (ADD/REDUCE fills, flip handling); verify in the first live copies.
## Out of scope for v0
Real money, the stage-2 evaluation/verdict machinery, economic-event pause (F8), reports beyond Telegram basics, any UI, an LLM in the decision path.
## Success metrics (to agree with the PO)
Proposed: trade count 50-100 over 2-4 weeks; 0 missed exits; 0 unexplained position mismatches; kill switches verified; paper P&L after fees/funding/slippage vs holding BTC; median open/close lag <= 5 s. Caveat to keep in the brief: a few dozen paper trades prove the bot works and that profit is plausible; they do NOT prove an edge.
## Kill criteria (proposed, PO to confirm)
Stop and rethink if: after 4 weeks of paper P&L after costs is clearly negative on >= 50 trades; or any missed exit / stop-less position / mismatch that is not explained; or the median lag exceeds 5 s consistently.
## Known unknowns
Whether any wallet will pass the quality gates (no_eligible_leaders is possible); real latency from Brazil; real fill slippage vs the paper model; clock offset uncertainty from Brazil (max_offset_uncertainty_ms 250 vs measured 340: set 500 for the test).
## PO decisions made during this brainstorm
1. v0 question = does copy-trading the chosen wallets profit in paper (2-4 weeks, $300). 2. Bot picks leaders (no manual list). 3. Max 7 followed wallets. 4. Daily/weekly re-scoring with kick-out of underperformers. 5. Long+short, leverage up to 10x depending on coin/trader. 6. <= 5 s gap. 7. Venue Hyperliquid. 8. Paper first 2-4 weeks. 9. Risk wording (10/20% per trade, 5%/day) needs clarification: see mismatch above. 10. Script vs Claude for ranking: CTO recommends a script with an optional read-only Claude weekly analyst: awaiting confirmation.
