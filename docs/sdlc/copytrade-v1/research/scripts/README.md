# Research scripts: copytrade-v1

Every script here is **exploratory**. Its output is never evidence of an edge until the backtest-auditor has reviewed it.

| Script | What it does | Network | Output |
|---|---|---|---|
| `hl_sample.py` | Samples real Hyperliquid wallets (public data) to replace the synthetic priors | yes, public read-only | `research/data/hl_sample/run_<UTC time>/summary.json` |
| `feasibility_mc.py` | Synthetic Monte Carlo of a paper run: trade count, drawdown, joint P(PASS) | no | stdout (logged under `research/data/`) |
| `gate_power.py` | Synthetic power and false-PASS rates of the frozen go-live gate | no | stdout (logged under `research/data/`) |
| `few_clusters.py` | Synthetic: the frozen rule when the 300 trades fall on few UTC days (sets `eval.min_day_clusters`) | no | stdout (logged under `research/data/`) |
| `b0d_cost_fr6.py` | Synthetic (E11): P2 + P2c at zero net timing value with the corrected vs superseded B0d cost; how often FR6 fires given a pass | no | stdout (logged under `research/data/`) |
| `eval_reference.py` | Reference implementation of the frozen evaluation keys (addenda A1.3, A2, A3.1 and A4) with golden-asserted test vectors (E16, supersedes E15): RNG with rejection, bootstrap, percentile index, CIs, merged positions, `/flatten` shadow exits and `T_eval`, B0d draws, D_i without an admissible window, missed exits (gate R, cost versus the mirror, P4 / F2, evaluation close), **A4:** incremental and per-trade missed-exit costs, uncomputable mirrors, fills without a recorded book (1m/1h candle, SL/TP gap-through), the P4 breach time and run end, exit classes (late, orphan, settled after a data gap), B̄ under a discretionary pause; verdict precedence | no | stdout (logged under `research/data/`) |

`research/data/` is gitignored. Outputs are identified by the sha256 values recorded in `edge-hypothesis.md` section 12.

---

## For the PO: running `hl_sample.py` once on your Windows PC

### What it does
- It reads **public** Hyperliquid data: the leaderboard, wallet fills, portfolio history and candles.
- It needs **no keys, no account and no wallet**. It places no orders and cannot trade.
- It picks 16 wallets using only data from 30-60 days ago: 8 top-ranked wallets and 8 random wallets from the ones that pass the gates.
- It then measures how those wallets actually traded over the last 30 days. That covers:
  - trades per day
  - holding time
  - position size relative to their account
  - how often a copy on a $300 wallet would fall below Hyperliquid's $10 minimum order
  - how price moves in the minutes after they open

### 1. Install Python (one time, about 5 minutes)
1. Download **Python 3.12** for Windows (64-bit installer) from https://www.python.org/downloads/windows/. Any version from 3.11 up works. The script was tested with 3.11.15.
2. Run the installer. On the first screen, **tick "Add python.exe to PATH"**, then click "Install Now".
3. Open **PowerShell** (Start menu, type `PowerShell`) and check the version:
   ```powershell
   python --version
   ```
   It should print `Python 3.12.x` or `3.11.x`. If you get "not recognized", close and reopen PowerShell. If it still fails, use `py` instead of `python` in every command below.

You don't need to install any packages: the script uses only the Python standard library.

### 2. Get the code
Use the `epic/copytrade-v1` branch once the CTO has told you it's pushed. Either way works:
- **With git:**
  ```powershell
  cd $HOME
  git clone https://github.com/arthurmateus/tradestuff.git
  cd tradestuff
  git checkout epic/copytrade-v1
  ```
  If you already have the repository: `cd` into it, then run `git fetch` and `git checkout epic/copytrade-v1`, then `git pull`.
- **Without git:**
  1. On GitHub, switch to the branch `epic/copytrade-v1`.
  2. Click **Code**, then **Download ZIP**.
  3. Extract the ZIP.
  4. In PowerShell, `cd` into the extracted `tradestuff-epic-copytrade-v1` folder.

All commands below run from the repository's top folder, the one that contains `docs` and `research`.

### 3. Check that it works (offline, a few seconds)
```powershell
python docs\sdlc\copytrade-v1\research\scripts\hl_sample.py --selftest
```
Expected output: `selftest OK (18 checks)`. If you see anything else, stop and send the full text to the CTO.

### 4. Run it (once)
- **Before you start:**
  - Set Windows to not sleep for the next 2 hours (Settings > System > Power).
  - Don't run the trading bot or any other Hyperliquid tool at the same time. They share one rate limit per IP address.
- **Then run:**
  ```powershell
  python docs\sdlc\copytrade-v1\research\scripts\hl_sample.py
  ```
- **Runtime:**
  - Usually **30-60 minutes**, and up to about 90 minutes if Hyperliquid slows it down.
  - The script paces its own requests (at most 800 of the 1,200 weight units per minute) and waits and retries on its own when rate-limited.
  - Leave the window open.
- **Progress:**
  - It prints steps `[1/5]` to `[5/5]`, then one line per wallet it checks: its account role, how many pages and fills it downloaded, the first fill date, and `PASS` or the reason it was excluded.
  - At the end it prints `Send back this file: ...\summary.json`.
- **Run it only once.** The research plan counts it as a single sample. If it **crashes or is interrupted**, simply run the same command again: an unfinished run doesn't count.

### 5. The output and what to send back
- A new folder: `research\data\hl_sample\run_<date>T<time>Z\`
  - **`summary.json`** is well under 1 MB. **Send this file to the CTO**: attach it, or paste its contents if the chat allows. This is the only file needed.
  - `raw\` holds compressed raw downloads (can be tens of MB). **Keep it; don't send it** unless the backtest-auditor asks for it.
- **What's in it:**
  - public wallet addresses from the Hyperliquid leaderboard
  - your Python version and Windows version
  - the settings used
  - the results
- **What's not in it:** keys, passwords, your IP address or anything personal.
- **Don't commit either file.** `research/data/` is gitignored on purpose.
- **If the run failed,** send the last 30 lines of the PowerShell window instead.

### Troubleshooting
| Symptom | What to do |
|---|---|
| `python` is not recognized | Use `py` instead of `python`, or reinstall Python with "Add python.exe to PATH" ticked |
| `CERTIFICATE_VERIFY_FAILED` | Antivirus or a proxy is intercepting HTTPS. Try another network or pause HTTPS scanning, then rerun. |
| `HTTP Error 403` from `api.hyperliquid.xyz` on every request | Hyperliquid may be blocking your region. **Stop and tell the CTO**: that is kill criterion K10, and a finding in itself. |
| Many `HTTP 429; retrying` lines | Normal under load. It waits and retries by itself. |
| The window closed or the PC slept | Rerun the same command |

Options exist (`--wallets`, `--pool`, `--seed`, and others; see `--help`). **Don't change them** unless the CTO asks: the defaults are what the research plan pre-registered.

### What happens next
1. The CTO passes `summary.json` to the quant-researcher. The first things checked are the data-shape diagnostics, so a surprise in Hyperliquid's API can be diagnosed from this single run:
   - `fetch_checks`: did every page come back in ascending time order, and was any history cut by the 10,000-fill cap?
   - the per-wallet `examined.<address>.fetch` records: first and last fill time, pages, fills
   - `pool.role_counts` and `role_unknown_excluded`: accounts whose role could not be read are excluded and counted
   - `leaderboard_month_check`: is the leaderboard's "month" a rolling 30 days? If not, the wallet pool may have used information from after the selection date, and the result is reported with that caveat.
2. Its measured values replace the synthetic priors in `feasibility_mc.py`: trades per day, holding time, position size, share below $10, and partial exits.
3. The feasibility figures in `edge-hypothesis.md` section 11 are then re-run.
4. The backtest-auditor reviews the result.

It remains **exploratory and survivorship-biased**: the candidates come from today's leaderboard, so wallets that blew up and disappeared are missing. It tells us how copyable these traders are. It is not evidence that copying them makes money.

---

## For agents: reproducing the synthetic outputs
Run from this folder:
```
python3 hl_sample.py --selftest                                          # offline, 18 checks
python3 feasibility_mc.py --runs 2000 --seed 17 > ../../../../../research/data/feasibility_mc_seed17.txt
python3 gate_power.py --sims 4000 --boot 1000 --seed 23 --jobs 3 > ../../../../../research/data/gate_power_seed23.txt
python3 few_clusters.py > ../../../../../research/data/few_clusters_seed31.txt              # uses 4 processes
python3 b0d_cost_fr6.py > ../../../../../research/data/b0d_cost_fr6_seed41.txt              # E11, 2 processes, ~2 min
python3 eval_reference.py > ../../../../../research/data/eval_reference_vectors.txt         # E16 (supersedes E15), ~5 s
```
- `feasibility_mc.py` imports the interval estimators from `gate_power.py`.
- The `gate_power.py` output doesn't depend on `--jobs`.
- Compare the sha256 of each output with the value logged in `edge-hypothesis.md` section 12.
