# Testing the v0 paper bot on your Windows PC (DRAFT: finalised after R0 is merged)
Paper mode only. The bot never places a real order and never needs a Hyperliquid key. Do not put real keys anywhere near it.

## A. One-time setup (about 20 minutes)
1. **Get the code.** Install Git for Windows, then in PowerShell: `git clone https://github.com/arthurmateus/tradestuff C:\tradestuff`, `cd C:\tradestuff`, `git checkout epic/copytrade-v1` (once R0 is merged it is on that branch; until then use `git checkout feat/copytrade-v1/R0-runner`).
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
