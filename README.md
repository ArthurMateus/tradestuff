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
