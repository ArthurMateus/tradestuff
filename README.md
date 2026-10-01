# tradestuff

AI-filtered copy-trading bot: finds proven Hyperliquid traders, filters their moves with deterministic rules, and copies them with strict risk limits, reporting in Telegram. Paper trading first; real money only after the `/go-live` gate and the PO's written approval.

- Product vision and decisions: `docs/product/`
- Current epic: `docs/sdlc/copytrade-v1/` (see `STATE.md`)
- How this repo is built (agentic SDLC, run from Claude Code): `docs/agentic-sdlc/README.md` and `SETUP.md`

## Development

Requires [uv](https://docs.astral.sh/uv/) (it installs the pinned Python 3.11 from `.python-version` and the locked dependencies). The same commands work on Windows (PowerShell) and Linux; nothing needs the network, keys or services.

| What | Command (from the repo root) |
|---|---|
| Install | `uv sync` |
| Tests | `uv run pytest` (`-m unit` or `-m integration` to select one kind; `uv run pytest tests/core` for one area) |
| Lint | `uv run ruff check .` |
| Format check / apply | `uv run ruff format --check .` / `uv run ruff format src` |
| Type check (mypy, strict on `src/`, relaxed on `tests/`) | `uv run mypy` |
| Startup checks (config, paper-only mode, secrets, engine path set) | `uv run copytrade start` |

Ruff and mypy settings live in `pyproject.toml`. The tests are not reformatted (they are owned by the test designer), so `ruff format` is applied to `src/` only. Secrets are read from `COPYTRADE_*` environment variables only (see `src/copytrade/core/secrets.py`); never put one in a config file.

## Running the paper bot on Windows

This starts the bot in **paper mode only**: it follows leaders on Hyperliquid and copies their moves with fake money. It never places a real order. There is no setting that switches it to live trading, and any other mode in the config is refused at start. Never put real keys anywhere near it.

### 1. Install Python 3.11 and uv (once)

1. Install Python 3.11 from python.org (tick "Add python.exe to PATH"). `uv` also downloads the right Python by itself, so this step is optional.
2. Open **PowerShell** and install uv: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, then close and reopen PowerShell.
3. Go to the folder of this repository (for example `cd C:\tradestuff`) and run `uv sync`. It installs the locked dependencies.

### 2. Put your Telegram numbers in `config\telegram.toml` (once)

The files in `config\` hold every setting (paper mode, risk limits, disk limits). Open `config\telegram.toml` and replace the three `0` placeholders with your own numeric ids: `allowed_user_id` (you), `control_chat_id` (the chat where you send commands and see trade posts) and `alerts_chat_id` (the chat that gets alerts). The bot refuses to start while they are `0`. Do not put the bot token or the PIN in any file.

### 3. Set the secrets for this PowerShell window

The secrets are read from environment variables only. In the same PowerShell window you will start the bot from:

```powershell
$env:COPYTRADE_TELEGRAM_TOKEN = "<the token BotFather gave you>"
$env:COPYTRADE_TELEGRAM_PIN_HASH = "<hash of your /flatten PIN>"
$env:COPYTRADE_TELEGRAM_PIN_SALT = "<the salt used for that hash>"
```

`COPYTRADE_TELEGRAM_TOKEN` is required. Without the PIN hash and salt the bot still runs, but `/flatten` is refused. To keep them across windows, use Windows "Edit the system environment variables" (user variables), not a file in the repository.

### 4. Where the data lives

By default everything is written next to the repository, in a folder `copytrade-data` beside it (`..\copytrade-data` from the repository root; see `storage.ledger_dir`, `storage.recordings_dir` and `storage.cache_dir` in `config\platform.toml` and `config\storage.toml`):

- `copytrade-data\ledger\ledger.jsonl`: the **ledger**, the append-only record of everything the bot decided and did (orders, fills, risk decisions, alerts, checkpoints). Never edit or delete it: a damaged ledger stops the start on purpose. Back it up by copying the folder while the bot is stopped.
- `copytrade-data\state\`: the risk state (pause, drawdown), one small file.
- `copytrade-data\recordings\`: compressed market recordings, kept for 7 days and then pruned (the ledger says what was deleted).

The bot needs at least 10 GB free on that disk to start, warns you below 20 GB (`disk_free_low`) and stops recording below 8 GB (`disk_floor_stopped`; exits keep working).

### 5. Start and stop

```powershell
uv run copytrade run
```

The window prints `copytrade: running in paper mode`. Warnings and errors (the log) appear in this window as plain text; the ledger is the permanent record. **Stop it with Ctrl+C**: it refuses new entries, leaves open positions and their stops as they are, writes a final checkpoint, flushes the ledger, the recordings and the Telegram queue, and exits with code 0. The next start picks up the same positions, stops and followed leaders from the ledger. Closing the window or killing the process also works (the ledger survives), but the next start will tell you if anything could not be proven.

### 6. What to watch in Telegram

- Trade posts in the control chat: one per open position, edited as it moves and closed at the end.
- Commands (only your user id, only in the control chat): `/status`, `/positions`, `/pause` (refuse new entries, persists across restarts), `/resume` (allow them again), `/flatten <PIN>` (pause and close everything; it repeats every few seconds until nothing is open).
- Alerts in the alerts chat:
  - `startup_uncertain`: the start could not prove something (a position without a share, an unknown coin, a missing risk file, ...). New entries are paused until you send `/resume`; open positions and their stops keep working. Read the alert text, then `/resume`.
  - `clock_unsynced` and `clock_jump`: the exchange clock cannot be trusted; entries are refused (exits keep working) until it settles.
  - `loop_stalled`: the trading loop has not finished an iteration for about 30 seconds.
  - `disk_free_low` and `disk_floor_stopped`: free disk space, see above.
  - `flatten_incomplete`: `/flatten` could not close everything after 12 tries: check the positions by hand.
  - `exit_unfilled`: an exit has not filled for a while; it keeps retrying.
  - `feed_stale`, `data_gap`, `access_degraded`, `schema_failure`, `leaderboard_outage`, `no_eligible_leaders`: data problems; the bot refuses new entries while they last and says so.
  - `runner_section_failed`: a non-critical part (feed, recorder, selection) failed; trading goes on.
