# Handoff: copytrade-v1 (for the PM, via `/epic copytrade-v1`)

You are the PM for epic `copytrade-v1` in repo `arthurmateus/tradestuff`. Write `docs/epics/copytrade-v1/requirements.md` (mode A) from the template `docs/sdlc/templates/requirements.md`.

## Read first (in this order)
1. `docs/epics/copytrade-v1/brief.md`: the scope, definitions, success gate and out-of-scope list. This is the source of truth.
2. `docs/epics/copytrade-v1/questions.md`: every open question with the PO's answer. Do not reopen these.
3. `docs/product/decisions.md`: the PO's decisions and reasons.
4. `docs/research/copytrade-v1-domain-research.md`: the numbers behind the defaults.
5. `docs/sdlc/implicit-requirements.md` and `docs/sdlc/testing-policy.md`.

## Goal in one sentence
Build a Python bot on the PO's Windows PC that automatically finds and continuously re-ranks the 5-10 best recurring Hyperliquid traders, filters their moves with deterministic rules, and paper-trades a $300 USD wallet at real mainnet prices. It mirrors entries, adds, partial and full exits, and reports every trade in a private Telegram chat. The build must be complete enough that a later paper run can reach an honest verdict on profitability after costs within about one month.

## What the requirements must pin down
- One feature per brief scope item (12 items). Split an item where it is too large to test.
- Given/When/Then acceptance criteria for each feature, with concrete numbers taken from the brief and research. Examples: the 5s signal age, 0.3%/0.8% slippage, 3x/5x/10x leverage, 2%/5%/15% loss limits, a $300 wallet, the top 200 candidates, a 60-minute re-score, the top-8-in / below-top-15-out / 24h hysteresis, and the event windows.
- Every numeric parameter is config with a default and a hard ceiling. Criteria must verify that the ceilings cannot be exceeded through config.
- Criteria for the edge cases the PO decided: exit authority (whichever happens first), sizing that mirrors the trader and is capped by risk limits, partial percentages, merged posts with per-trader shares, conflicts skipped, pre-existing positions ignored, unexecutable orders logged, a dropped trader's exits still mirrored, a reconstructed downtime gap, a leaderboard outage failing closed, the LLM being down or over budget, and Telegram access restricted to the PO.
- **Paper-fill realism:** criteria defining how fills are simulated from the live order book. This covers fees, spread, depth-walk slippage, copy delay, funding, partial fills, isolated-margin liquidation, and minimum size / lot / tick rules. These are the most important criteria in the epic, because the go-live verdict depends on them.
- **Measurement:** the definitions of "trade" and "R", shadow outcomes for rejected signals, the replay restricted to recorded snapshots, and a report that computes mean R with a 95% CI and gives a PASS / FAIL / INCONCLUSIVE verdict from the ledger.
- Every implicit requirement, applied or marked N/A with a reason. See the list at the end of `questions.md`.
- A "Definition of done" for the epic. It includes a one-day latency measurement from the PO's home connection, and a dry run of the full pipeline for at least 24h without crashes, before the paper run is declared started.

## Hard constraints
- No real money, no exchange API keys, no Hyperliquid testnet.
- USD only.
- $0-50/month running cost.
- Must run on Windows.
- The LLM never votes on trades.

## Out of scope
Everything in the brief's "Out of scope" list.

## Things you must not do
- Invent policy. Put any guess under "Assumptions" for the PO.
- Choose technology. That belongs to the architect.
- Read git history. Use `history-explorer` for lookups.

## Domain reviewers
After you draft, the CTO will run `risk-manager` and `quant-researcher` on your requirements. Make the paper-fill model and the scoring criteria precise enough for them to check.
