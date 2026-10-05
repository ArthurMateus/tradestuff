# Testing the v0 paper bot on your Windows PC
Paper mode only. The bot never places a real order and never needs a Hyperliquid key. Do not put real keys anywhere near it.

## A. One-time setup (about 20 minutes)
1. **Get the code.** Install Git for Windows, then in PowerShell: `git clone https://github.com/arthurmateus/tradestuff C:\tradestuff`, `cd C:\tradestuff`, `git checkout epic/copytrade-v1`.
2. **Install uv** (it also installs Python 3.11): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, close and reopen PowerShell, `cd C:\tradestuff`, `uv sync`.
3. **Make a Telegram bot.** In Telegram talk to @BotFather: `/newbot`, copy the token. Open a chat with your new bot and send it any message. Find your numeric user id (talk to @userinfobot). For simplicity use one private chat with the bot for both control and alerts: its chat id equals your user id.
4. **Edit `config\telegram.toml`:** replace the three `0` values: `allowed_user_id` (your id), `control_chat_id` (same number for a private chat), `alerts_chat_id` (same number). Never put the token or PIN in a file.
5. **Choose a /flatten PIN and compute its hash** (run once in PowerShell, replace both quoted values; keep the salt, you need it below):
   `uv run python -c "import hashlib; print(hashlib.pbkdf2_hmac('sha256', b'YOUR-PIN', b'YOUR-SALT', 200000).hex())"`
   (PBKDF2-HMAC-SHA256, 200,000 iterations, PIN and salt as UTF-8, hex digest.)
6. **Set the secrets** in the PowerShell window you will run the bot from:
   `$env:COPYTRADE_TELEGRAM_TOKEN = "<token>"`, `$env:COPYTRADE_TELEGRAM_PIN_HASH = "<hash>"`, `$env:COPYTRADE_TELEGRAM_PIN_SALT = "YOUR-SALT"`.
7. **Disk:** the bot needs at least 10 GB free on the drive holding `..\copytrade-data` (beside the repo); it warns under 20 GB and stops recording under 8 GB.

## B. First run: a 30-minute smoke test (do this before leaving it running)
1. `uv run copytrade run`. Expected: the window prints `copytrade: running in paper mode`. If it prints one `copytrade: ...` line and exits, read it (usually a missing variable, a `0` id, or disk space).
2. In Telegram send `/status` (expect a reply), `/positions` (empty at first), `/pause` (confirmation), `/resume`, `/flatten 0000` with a WRONG PIN (must be refused), then `/flatten <your PIN>` (nothing to close: harmless).
3. Watch the alerts chat. Normal on a fresh start: possibly `startup_uncertain` (send `/resume` after reading it), a brief `clock_unsynced`. Not normal: repeated `runner_section_failed`, `loop_stalled`, `feed_stale` lasting minutes.
4. Press **Ctrl+C once**. Expect a clean exit (code 0). Start it again: it should say what it restored and carry on. Never close the console window with the X (it can cut the clean stop short): use Ctrl+C.

## C. Leave it running (2-4 weeks)
- Keep the PC awake (Windows: Settings > System > Power > Screen and sleep > "Never" for plugged in) and stop automatic restarts at night if you can (Active hours).
- Check Telegram once or twice a day: trade posts appear when a followed leader trades and the bot copies; `/status` shows equity and open positions.
- After any restart (Windows Update, crash) just start it again from step B1; it reloads from the ledger.
- Every few days: free disk space (`copytrade-data`), and copy `copytrade-data\ledger\` somewhere safe while the bot is stopped.
- Do NOT edit or delete files in `copytrade-data\ledger`. A damaged ledger stops the start on purpose.

## D. When to stop and tell me
Stop with Ctrl+C and keep the `copytrade-data` folder and the console text if you see: a position open with the leader flat for more than a few minutes; `flatten_incomplete`; `startup_uncertain` that repeats on every start; `loop_stalled` repeating; any message mentioning a position without a stop; disk alerts; anything in Telegram you do not understand. Send me the alert text, the console output and the ledger folder (zipped) when my usage is back.

## E. Also needed from you (separate, once)
Run `hl_sample.py` as described in `docs/sdlc/copytrade-v1/research/scripts/README.md` and send back `summary.json`: it checks the Hyperliquid response formats the bot was written from the docs, and feeds the remaining config values.

## F. What the paper run measures (for the decision after 2-4 weeks)
Trade count (aim for 50-100), missed exits (must be zero), position mismatches (none unexplained), whether every limit and kill switch worked, and paper P&L after fees, funding and slippage compared with just holding BTC. Spreadsheet or short script: I will help read the ledger when I am back.

---
# UPDATE 2026-10-05 (epic with R1-R5): what is different now, read this before section B
**Update the code:** `git stash` (keeps your local config edits), `git checkout epic/copytrade-v1`, `git pull`, `git stash pop`, `uv sync`. Set the three COPYTRADE_TELEGRAM_* variables again in each new PowerShell window. Check that your **Windows clock is accurate** (Settings > Time & language > Sync now): a PC clock more than 30 s off delays simulated stop-losses after a restart.
**Config edits that are OK for the test (local, never committed):** `config\telegram.toml` (your three ids); `config\platform.toml` `max_offset_uncertainty_ms = 250` (from Brazil 100 is often too tight); optional speed-ups: `config\hl.toml` `rest_weight_budget_per_min = 1100` and `scoring_weight_share = 0.8` (maximum allowed; leaves exits only 220/min: switch back to 0.5 once a position is open); `config\scoring.toml` `candidates_k = 50` (the minimum). Do NOT change `window_days` unless you accept judging leaders on less history (90 is the minimum allowed).
**What the bot does at start (new):** it downloads the leaderboard (about 47,000 rows), keeps only rows that look like real, active, non-HFT accounts (stage 1, ranked by profit per dollar traded), then screens the first 2,000 fills of each candidate in rank order (stage 2: maker share <= 0.70, core-perp share >= 0.50, fewer than ~56 fills/day, >= 60 days of history, hold time, size) and only downloads the full history of wallets that pass, until it has `candidates_k` of them. Only then does scoring run and `followed=N` appear.
**How long (estimates, not promises):** about 1 to 1.5 hours for the first pass of 50 wallets (each full wallet needs about 51 requests: 2 to 4 minutes; screens interleaved; candles cached per coin). A trade post in Telegram only appears after a followed leader opens a trade. Zero followed leaders (`no_eligible_leaders`) is a legitimate result, not a bug.
**Log lines to watch (console and `copytrade-data\logs\copytrade.log`):**
- `candidate prefilter: rows=47xxx ranked=2xxx` once per cycle.
- `candidate screened: wallet=... outcome=ok|rejected failed=S3,S4 not_evaluable=...` one per wallet (rejections are normal: about 85-90% of wallets fail).
- `backfill progress: done=X of 50 candidates, screened=S, screen_ok=K, screen_rejected=R, dropped=D, cooling=C, next retry in N s` about once a minute: `done` must grow.
- `backfill of a candidate complete: wallet=... fills=N pages=P`, then `backfill pass complete`, then `selection cycle ... followed=N`.
- Normal noise: `rate budget has no room ... would wait X s` (the bot pacing itself), `refresh ... skipped, it is cooling down`.
- Real problems: `loop_stalled` (should NOT appear any more), `coin=... window=... status=NNN` repeating for REAL coins, `feed_stale` lasting minutes, `runner_crashed`, any Telegram alert you do not understand.
**Stop it with Ctrl+C ONCE.** To check progress without reading the console: `Get-Content "..\copytrade-data\logs\copytrade.log" -Tail 40`.
**What to send back after 30 and after 90 minutes:** the latest `backfill progress` line, the latest `selection cycle` line, your Telegram `/status` reply and any alert text.
**Known limits (v0):** no `/leaders` command yet (followed wallets are not listed in Telegram); alerts for repeated backfill failures are console-only; do not leave the bot unattended for weeks until the first watched pass has completed and a restart (Ctrl+C then start again) has been tested once.
