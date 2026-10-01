# F14 test plan (Telegram bot, minimal v0)

Scope: only what the PO needs to watch and stop a paper run. Deferred (stage 2 or later gate): `/pnl`, `/traders`, `/stats` (AC9), reports (AC7), LLM "why" (F15), leader win rate and P&L in the post, free-disk and archive lines of `/status`, run number n/300.
Tests: `tests/telegram/` (real RiskGate, paper broker, ledger, PositionBook and PositionManager from the F12 rig; only the Telegram server is faked, as a loopback HTTP server on 127.0.0.1 with real sockets in `fake_server.py`). Payload shapes follow the Bot API docs; no recorded real Telegram sample exists (note for the PO/QA).

## Pinned public API (`src/copytrade/telegram/`, stdlib only, no new dependency)
- `api.py`: `TelegramApi(base_url: str, token: SecretValue, *, timeout_s: float = 5.0)`; `send_message(chat_id, text) -> int`; `edit_message_text(chat_id, message_id, text)`; `delete_message(chat_id, message_id)`; `get_updates(offset, *, timeout_s=0) -> list[Update]`; `Update(update_id, user_id, chat_id, message_id, text|None)`; updates without a `message` are skipped. Errors: `TelegramError` > `TelegramUnavailable` (network, timeout, 5xx), `TelegramRateLimited(retry_after_s)`, `TelegramRejected` (other 4xx). No retries in the API; messages and `repr` never contain the token. Real use is `https://api.telegram.org` through urllib.
- `bot.py`: `TelegramBot(*, config, api, gate, manager, book, ledger, clock, gate_lock, pin_hash: SecretValue | None, pin_salt: SecretValue | None, run_id)`; `clock.now_ms()`; `gate_lock` is the supervisor's single context-manager lock taken around every gate call (pause, resume, flatten; R0 contract RISK-25). Methods: `send(alert)` (the `AlertSink` port: enqueue, local log, never raises or blocks), `poll_once() -> int` (handled updates, never raises on Telegram failure), `sync_posts()` (diff `PositionBook` into trade posts), `flush()` (one non-blocking delivery pass), `queue_depth`.
- Config keys used (all exist in F1): `telegram.allowed_user_id`, `control_chat_id`, `alerts_chat_id`, `min_edit_interval_s`, `max_msgs_per_min_per_chat`, `queue_max_messages`, `queue_max_age_h`, `pin_max_attempts`, `pin_lockout_min`, `unauthorized_alert_interval_min`. **No new config key needed.** Backoff (1 s doubling to a 60 s cap), HTTP timeout and the 4096-char message cap are code constants.
- Ledger audit kind `telegram_audit`: `user_id, chat_id, command (name only, never arguments), time, result` with result in `ok, refused_unauthorized, bad_pin, pin_locked, pin_not_configured, usage, unknown_command`.
- PIN hash: PBKDF2-HMAC-SHA256, 200,000 iterations, salt and PIN as UTF-8, hex digest (env `COPYTRADE_TELEGRAM_PIN_HASH`/`_SALT`; the runner passes `SecretValue`s, the bot never reads the environment).

## Pinned ambiguities (defaults stand until the PO/PM says otherwise)
1. Trade posts go to `control_chat_id`; alerts only to `alerts_chat_id`; command replies to the control chat only. Unauthorised senders get no reply.
2. Post format: marker green circle (long) / red circle (short), `PAPER`, `LONG`/`SHORT`, coin, entry, stop, leverage, leader label `0xaaaa...aaaa` (first 6 + last 4), fixed `why unavailable`; one post per coin position, edited on add/stop move/close; final edit has `CLOSED`, realised USD P&L `{:+.2f}` (from the ledger `trade` record) and the exit reason (from the closing `share_state`).
3. `/status` text lines: `mode: paper`, `state: running|paused`, `open positions: N`. `/pause` `/resume` need no PIN; `/flatten <PIN>` does. Missing PIN = `usage`, not counted as a failure. Bot suffix `/pause@name` accepted.
4. Lockout: failures counted inside a sliding `pin_lockout_min` window; at `pin_max_attempts` the lock lasts until last failure + `pin_lockout_min` (free exactly at the boundary). Missing hash or salt = fail closed (`pin_not_configured`).
5. Unauthorised alert: one per interval, allowed again exactly at the interval boundary; the first one is immediate.
6. Queue: oldest dropped when over `queue_max_messages`; a message older than `queue_max_age_h` (strictly) is dropped; backoff after a failure; HTTP 429 `retry_after` honoured; per-chat cap in a 60 s window; strict FIFO.
7. Outgoing text is redacted of the token, PIN hash and salt; the PIN message is deleted after processing (right or wrong).
8. `/flatten` calls `PositionManager.flatten(run_id=...)` once and reports what is pending. **Re-running flatten while `in_flight`/`still_open` is R0's contract (F10)**; the bot does not loop.
9. Edits of a state change are coalesced (<= 1 edit per `min_edit_interval_s` per message, latest state wins).

## AC -> tests
| AC | Tests |
|---|---|
| F14.AC1 | test_auth: five_unauthorised_commands..., unauthorised_senders_get_no_reply..., unauthorised_alert_is_rate_limited_boundaries, non_message_updates_are_ignored (x4), text_less_huge_and_unicode..., duplicate_update_id..., unknown_user_audit_is_written_even_when_telegram_replies_fail; test_api: get_updates_parses..., get_updates_skips... |
| F14.AC2 (v0 subset) | test_posts_and_queue: entry_post_shows..., short_post_has_the_red_marker, a_second_pump_without_change..., a_merged_position_has_one_post..., final_post_shows_realised_pnl_and_exit_reason |
| F14.AC3 | edits_are_coalesced..., the_edit_interval_boundary, latest_state_is_visible_within_10_s..., per_chat_message_cap..., a_429_retry_after_is_honoured...; test_api: edit_and_delete..., 429_raises_rate_limited... |
| F14.AC4 (v0 subset) | test_commands: status (x2), pause_and_resume_drive_the_real_gate_under_the_lock, a_paused_gate_really_refuses_new_entries, positions_lists..., flatten (x4), unknown_command, bot_suffix, commands_survive_a_telegram_reply_outage, poll_failure..., replies_to_control_chat_only |
| F14.AC5 | test_auth: correct_pin..., wrong_pin..., without_a_pin..., lockout..., one_below_max..., failures_older_than_the_window..., pause_and_status_stay_available..., unconfigured_pin_fails_closed, the_pin_never_appears...; test_api: errors_and_logs_never_contain_the_token; test_invariants: a_full_session_never_logs_the_token, token_and_pin_come_only_from_injected_secrets |
| F14.AC6 (v0 part) | test_commands: status_and_positions_carry_no_forbidden_or_outcome_content; test_invariants: never_imports_evaluation_baselines_or_reports |
| F14.AC8 | test_posts_and_queue: alerts_go_only_to_the_alerts_chat, alert_text_never_contains..., outage_never_blocks..., trading_continues_during_an_outage, failed_delivery_backs_off_and_drains_in_order, queue_is_capped..., queue_age_boundary..., send_never_raises_even_for_odd_alerts; test_api: outage (down, 500), hang timeout, connection refused, rejected 4xx |
| A1 / deps | test_invariants: no_path_to_order_apis, only_stdlib_and_copytrade_are_imported |
| AC7, AC9, /pnl, /traders, /stats | deferred (stage 2) |

## Run summary
68 new tests (64 functions, 6 parametrised cases); at this commit every new test fails on the missing `copytrade.telegram` module (ModuleNotFoundError), existing suites pass.
Not covered here: real HTTPS/TLS to api.telegram.org (QA with a throwaway bot on the PO's machine), p95 latency (QA), the R0 flatten re-run loop and the real alert wiring into F3/F4/F6/F10/F12 (R0).

## Revision: fake server bookkeeping fix [F14.AC8]
`FakeTelegram` recorded every `sendMessage` request before applying mode `down`/`http500`, so `sent()` counted failed delivery attempts as delivered. That made `test_F14_AC8_failed_delivery_backs_off_and_drains_in_order_on_recovery` and `test_F14_AC8_queue_age_boundary_drops_only_messages_older_than_queue_max_age` unsatisfiable (the required attempt while down appeared as a duplicate/stale "send"). Fix: `Req.delivered` is set only on a 2xx reply; `sent()` and new `delivered_calls()` return delivered requests only; `calls()`, `requests` and `request_count()` still include all attempts. No assertion was changed or weakened. All 68 tests pass.

## Round 1 addendum (review r1 batch `reviews/F14-r1-batch.md`)

New files: `tests/telegram/test_r1_stale.py` (item 1), `test_r1_failures.py` (items 2, 3), `test_r1_outbox_pin.py` (items 4, 5, backoff cap). 32 new tests: 20 fail on purpose on d2db7af (AttributeError/assert on missing behaviour, `UnicodeEncodeError` and `LedgerWriteError` escaping `poll_once`, `LedgerCorruptError` escaping `sync_posts`, book reads at lock depth 0), 12 are guards that pass today. Existing telegram suite: 68/68 still pass; no existing assertion changed.

### Pinned contracts (the developer implements exactly these)
- `Update.date: int`, seconds, parsed from `message.date`. A message whose `date` is missing or not an int is dropped by `_parse_update` (fail closed).
- `copytrade.telegram.bot.MAX_COMMAND_AGE_S = 60` (code constant, no config key). Age = `clock.now_ms() // 1000 - update.date`. Age 60 runs, 61 is refused.
- First SUCCESSFUL `getUpdates` after start (a failed poll does not count) is the backlog drain: every update in it is confirmed (offset advanced, so the next call carries a higher offset) and none acts. One `telegram_audit` record per COMMAND update (text starting with `/`, any sender): `result == "stale_dropped"`, `command` = the parsed name. Non-command updates: no audit.
- Later polls: a command older than the limit is not executed; audit `result == "stale_command"`. Fresh commands behave as before. Replies to stale updates are unspecified (not asserted).
- A handler that raises (incl. `_pin.check`; test uses `"/flatten \ud800"`, a lone-surrogate argument, and a closed ledger): audit `result == "error"` with the command name, reply text containing "command failed" (case-insensitive, no argument/secret echoed), offset already advanced so it is never replayed, later updates in the same batch still run. `poll_once` returns the number of updates taken (a failed one counts) and never raises, also when the audit append itself fails (closed ledger); `sync_posts` never raises (ledger scan failure = `LedgerCorruptError`).
- Every `PositionBook` call the bot makes (`open_shares` in /status, /positions, /flatten; `states` in `sync_posts`) runs at gate_lock depth >= 1; the bot never calls the ledger at depth > 0 (guard).
- 4xx on send/edit: message dropped, no backoff, next delivered, one call per rejected message. Half-configured PIN (hash only or salt only): audit `pin_not_configured`, reply contains "no PIN", nothing closed, other commands keep working. Backoff waits 1,2,4,8,16,32 then 60 s (cap).
- `/resume` stays PIN-less (PO decision pending; tests unchanged).

### Harness changes (backward compatible, no assertion touched)
- `fake_server.py`: `FakeTelegram.date_fn` (optional callable) and `push_text(..., date=None)`. Default date is still `1_700_000_000` unless `date_fn` is set. The fake already keeps unconfirmed updates until a later `getUpdates` carries a higher offset (needed for restart/redelivery tests).
- `helpers.py` `bot_env`: sets `server.date_fn` to the bot clock in seconds (so a message pushed "now" is fresh), and primes the bot with one `poll_once()` on an empty server (the new start-up drain) unless `prime=False` (`new_bot(prime=False)`). Without this every existing test would lose its first command to the backlog drain.

### Guards (pass today; mutant killed)
`test_R1_4_GUARD_*` (3 tests, 400/403 drop, no backoff, rejected edit) kill M13 (no pop); `test_R1_5_GUARD_*` (4) kill M5 (`or`->`and`); `test_R1_GUARD_backoff_*` (2) kill M21 (cap 600); `test_R1_3_GUARD_the_ledger_is_never_read...` kills "whole of sync_posts/_handle under gate_lock"; `test_R1_1_a_fresh_command_runs` kills "age check refuses everything". M5, M13, M21 were each re-applied by hand: the guards fail. M16 (send never-raise guard) stays skipped (needs mocking our own code).

### Not covered here
Concurrent book mutation under a real lock (lock depth observed instead); Telegram's real redelivery semantics beyond the fake (QA/simulation); advisory items 7-13.
