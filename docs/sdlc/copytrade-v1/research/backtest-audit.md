VERDICT: INCONCLUSIVE

# Backtest audit: copytrade-v1 exploratory research

Auditor: backtest-auditor. Date: 2026-09-29. Branch `epic/copytrade-v1` @ `9d46daf`.

Scope: `edge-hypothesis.md`, `market-context.md`, `01-brief.md`, and the three scripts in `research/scripts/`, checked against trading-invariants section D. No real market data exists, so there is no edge claim to validate.

**Why INCONCLUSIVE:**
- **Sound:**
  - The synthetic work reproduces exactly and is honestly labelled [EXPL].
  - The scripts have no bug that reverses a conclusion.
  - The gate is conservative against a false PASS in the synthetic model: at zero edge, the unconditional false-PASS rate is 1.6–2.1%.
- **Not sound yet:**
  - Several reported numbers are stated more favourably than the model supports.
  - The pre-registration isn't ready to freeze: four items are BLOCKING.
  - `hl_sample.py` has a rate bug and a look-ahead that must be fixed before its output replaces any prior.

## Reproducibility
| Command (Python 3.11.15) | Result |
|---|---|
| `python3 feasibility_mc.py --runs 2000 --seed 7` | Byte-identical to `research/data/feasibility_mc_seed7.txt` (sha256 `6c1863…45b6`) |
| `python3 gate_power.py --sims 4000 --seed 11` | Byte-identical to `research/data/gate_power_seed11.txt` (sha256 `c1e98c…5c77`) |
| `python3 hl_sample.py --selftest` | `selftest OK` |

Script hashes at audit time: `feasibility_mc.py` `1b6892…42b8`, `gate_power.py` `b6f006…8e44`, `hl_sample.py` `bf059a…81f2`.

## Pre-registered criteria vs observed
No real data, so each row shows the criterion's operating characteristics in the synthetic model.

| ID | Criterion | Synthetic check (doc vs audit) |
|---|---|---|
| P1 | N = 300 closed trades | P(≥300 in 30d before a 15% drawdown) = 0.00 / 0.39–0.75 / 0.45–0.91 (pessimistic / base / optimistic). Reproduced. Conditional on 5–10 eligible traders from day 1 (BT-10). |
| P2 | Mean-R 95% CI lower bound > 0 | Doc power at +0.10R: 34–49%. Audit **joint** P(PASS within 30d) at +0.10R: 0.29 base, 0.34 base at 0.5% risk, 0.39 optimistic, 0.00 pessimistic (BT-6). The cluster definition misses cross-position correlation, so false PASS reaches 3.8–9.6% (BT-4). |
| P3 | Max drawdown < 15% | Doc P(DD ≥ 15%) = 0.066 at +0.10R base and 0.004 at 0.5% risk. These are lower bounds: with a daily common factor (ρ = 0.2–0.3) the base rate becomes 0.108 (BT-8). |
| P4 / P5 | 0 missed exits / downtime < 2% | Not modelled (engineering criteria). |
| P6 | Replay/paper same sign | No replay yet. |
| P7 | Single look at N = 300 | Confirmed: false PASS 1.9% with one look vs 10.1% when checked every 10 trades. Restarts and interim display are unbounded (BT-5). |
| Variant budget | ≤ 8 replay variants, 1 paper config | 0 real variants. E2a/E2b were model-bug fixes. No cap on paper restarts (BT-5). |

## Findings
| ID | Severity | Location | Finding | Why it matters | Required fix |
|---|---|---|---|---|---|
| BT-1 | BLOCKING | `hl_sample.py:167,189` | `opens_per_day` divides by the first-to-last-fill span, not by the observation window. One 60-minute round trip in a 30-day window reads as 24.0 opens/day (true value 0.033). | This output is meant to replace the feasibility priors, so feasibility would look far better than it is. | Divide by the requested window. Use first fill → end only when the 10k-fill cap truncated history, flag truncation, and add a sparse-wallet self-test. |
| BT-2 | BLOCKING | `hl_sample.py:272-277,292,195-196` | Selection look-ahead: wallets are chosen by their current-month P&L, then drift, win rate and P&L are measured in that same window. | This inflates the apparent leader edge and the delay cost. Win rate and P&L become selection artefacts. | Measure drift only after the selection time, or select on days −60..−30 and measure on −30..0. Drop or label `win_rate` and `net_pnl_closed`. |
| BT-3 | BLOCKING | `hl_sample.py:154-159,172` | `account_value_at` falls back to the current account value (a D1 look-ahead). | This biases `frac` and the $10-rejection share. | Exclude opens with no prior account-value point and report the count. Never use `acct_now` for a past open. |
| BT-4 | BLOCKING | `edge-hypothesis.md:127`; `gate_power.py:11-13,130-158` | P2 clusters only the shares of one merged position, not correlation across positions (same-day or BTC beta). False PASS: 2.2% at ρ=0, 3.8% at ρ=0.2/70% long, 5.8% at ρ=0.3/80% long, 9.6% at ρ=0.5/80% long. A UTC-day cluster bootstrap brings these to 2.1–3.4%. | A zero-edge, beta-driven strategy can pass up to 4× the nominal rate, and this can't be changed after the run starts. | Add a UTC-day, or day-nested-over-position, cluster bootstrap to the `min()` in P2, with B = 10,000 and a stored seed. Note the small-cluster undercoverage or use a wild or t-based cluster CI. Correct the docstring. |
| BT-5 | BLOCKING | `edge-hypothesis.md:132,220,222,542-554` | The pre-registration isn't frozen. Q1–Q5 change the PASS rule. Any config change restarts the count with no cap on runs, and interim statistics are visible to the PO. | Restarting a run that's going badly is optional stopping; each restart is a variant (D4). | Before day 1: record the Q1–Q5 answers and hash the file into the ledger. Cap paper runs (e.g. at most 2) with α split across them, or require joint beating. Log every started or aborted run. Hide interim mean-R/CI, or fix in writing that interim numbers can't trigger config changes. |
| BT-6 | ADVISORY | `edge-hypothesis.md:516-519,533` | The power figures are conditional on reaching 300 trades. Joint P(PASS) at +0.10R is 0.29–0.39 (0.00 pessimistic). | This overstates month-one pass rates. | Add the joint row. State that about 1 in 3 is the best synthetic case for +0.10R. |
| BT-7 | BLOCKING | `edge-hypothesis.md:181,209` | Beta and regime aren't controlled. B0 randomises direction, B0b isn't gating, K9 fires only if both S3 and S4 fail, and 30 days is one regime. | P2 can pass on market beta in a trending month. | Pre-register a direction-matched, random-time baseline and/or mean R net of a BTC-return regression. K9 fires if **either** the beta-matched baseline or S4 fails. PO decision, taken before the run. |
| BT-8 | ADVISORY | `feasibility_mc.py:142-158,222,99` | Drawdown is modelled on realised closes only, with i.i.d. R and losses clipped at −1.05R. | The C6 drawdown figures are lower bounds. | Label them "lower bound". Add correlated-R and intra-trade MAE sensitivity before Q4. |
| BT-9 | ADVISORY | `edge-hypothesis.md:491,494` | $10 opens: 3.1% base, 0.4% optimistic (not ~1%). Halts block 17–55% of entries that reach the halt check. | These feed K8 and Q6. | Correct them and state the denominators. |
| BT-10 | ADVISORY | `feasibility_mc.py:119-121`; `edge-hypothesis.md:487,539` | The open-rate floor is 0.83/day, all traders are followed from minute 0, and the base case assumes 8 eligible traders while G7 may leave fewer than 5. | The "base" case isn't a central estimate. | Add a 3–5 trader, no-floor scenario. Present 100–300 trades as prior-driven judgement. |
| BT-11 | ADVISORY | `gate_power.py:135,116-127` | 500 sims per cell and B = 400, so the numbers are noisy. The ρ=0 control is 1.4% vs a nominal 2.5%. | Precision is overstated. | Report MC CIs or run ≥ 4,000 per cell. |
| BT-12 | ADVISORY | `gate_power.py:18,36-37`; `feasibility_mc.py:96-99` | R is modelled as a clipped normal. Real R is heavier-tailed (adds, no TP, gap-through). | Power is optimistic. | Add a heavy-tail sensitivity. Pre-register fragility checks: mean R without the top 5 trades and without the best leader. |
| BT-13 | ADVISORY | `edge-hypothesis.md:189-192,167` | Costs are never expressed in R: roughly 0.07–0.27R per trade (0.14–0.53R at ×2 costs). The ×1.5 and ×2 runs have no consequence. | Costs dominate a sub-0.10R prior edge. | Add a cost-in-R table. Pre-register: mean R ≤ 0 at ×2 costs means "cost-fragile" and requires a PO review. Use the spread recorded at signal time. |
| BT-14 | ADVISORY | `edge-hypothesis.md:132,135-137` | "First 300 closed" favours fast-closing trades. The end of the P3 window is ambiguous. | A small selection effect. | Use the first 300 **opened** trades, evaluated once all have closed. P3 window = run start → close of trade 300. |
| BT-15 | ADVISORY | `.gitignore:2`; `edge-hypothesis.md:505-506,326` | The cited outputs are gitignored, and one script path is wrong. | Traceability. | Commit the two `.txt` outputs or record their sha256 values. Fix the path. |
| BT-16 | ADVISORY | `hl_sample.py:168,190,178-184,210-212,272-277` | Right-censored hold times, adds ignored in partial sizing, no vault/HLP/MM exclusion or gates, n = 10, coarse 1-minute drift, fixed 2.5% stop. | Its numbers can be off in either direction. | Label censoring. Mirror adds. Apply the cheap gates. Report per-wallet dispersion. |
| BT-17 | ADVISORY | `edge-hypothesis.md:336-339,352` | DSR over 180 days uses step-interpolated `pnlHistory` (~93 points all-time). | This makes G7 noisy and over-restrictive. | Use `perpMonth` plus our own hourly snapshots. Record the resolution used. Add a property test. |

**Positive observations:**
- The peeking inflation is simulated correctly.
- The E[max z], SR0, PSR and DSR formulas are correct.
- The Section F toy example is correct.
- E2a and E2b were disclosed honestly.
- Survivorship handling is correct: only our own snapshots count, and blown-up leaders are kept.
- K1 errs in the safe direction.
- Scoring inputs are point-in-time and include a property test.

## Summary for the PO
- This is a plan and thought experiments, not evidence. No real data was used.
- A real +0.10R edge passes the gate in month one only about 1 time in 3 (29–39%). At about 1.5 trades per leader per day it never reaches 300 trades.
- The gate is hard to fool by luck (about 2% false passes), so INCONCLUSIVE is the most likely honest outcome.
- **Fix before the paper run:**
  - Freeze Q1–Q5.
  - Use a day-clustered CI.
  - Require beating a beta-matched baseline.
  - Cap restarts.
- **Fix `hl_sample.py`** before running it from the PO's PC.
- **Live risks even after a PASS:**
  - costs of about 0.07–0.27R per trade
  - correlated drawdowns
  - fat tails from adds
  - optimistic paper fills
  - a single market regime
