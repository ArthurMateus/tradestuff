"""The Telegram bot (F14, minimal v0): operator commands, trade posts and the alert sink.

Commands act only through the public API of the risk gate and the position manager (``pause``, ``resume``,
``flatten``, state reads), each under the supervisor's one ``gate_lock``. Fail closed: only ``allowed_user_id`` in
``control_chat_id`` is obeyed; anyone else gets no reply, an audit record and a rate-limited alert. ``/flatten``
needs the PIN. ``send`` only enqueues: Telegram being down, slow or rate limiting can never block trading or exits.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from copytrade.core.clock import Clock
from copytrade.core.config import Config
from copytrade.core.events import Alert
from copytrade.core.secrets import SecretValue
from copytrade.ledger.store import Ledger
from copytrade.positions.book import PositionBook
from copytrade.positions.manager import PositionManager
from copytrade.risk.errors import RiskStateError
from copytrade.risk.gate import RiskGate
from copytrade.telegram.api import TelegramApi, TelegramError, TelegramRateLimited, Update
from copytrade.telegram.outbox import Backoff, Outbox, Outgoing
from copytrade.telegram.pin import PinGuard
from copytrade.telegram.posts import LedgerFacts, Post, live_views, render

_log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 4096
_COMMAND_NAME_CAP = 64
MAX_COMMAND_AGE_S = 60  # a command older than this is never obeyed (replay and backlog guard)
_AUDIT_KIND = "telegram_audit"
_REDACTED = "<redacted>"

_USAGE = {"/flatten": "usage: /flatten <PIN>"}


class TelegramBot:
    def __init__(  # noqa: PLR0913 - the pinned F14 constructor
        self,
        *,
        config: Config,
        api: TelegramApi,
        gate: RiskGate,
        manager: PositionManager,
        book: PositionBook,
        ledger: Ledger,
        clock: Clock,
        gate_lock: AbstractContextManager[Any],
        pin_hash: SecretValue | None,
        pin_salt: SecretValue | None,
        run_id: str,
    ) -> None:
        self._config = config
        self._api = api
        self._gate = gate
        self._manager = manager
        self._book = book
        self._ledger = ledger
        self._clock = clock
        self._gate_lock = gate_lock
        self._run_id = run_id
        self._user_id = int(config["telegram.allowed_user_id"])
        self._control_chat = int(config["telegram.control_chat_id"])
        self._alerts_chat = int(config["telegram.alerts_chat_id"])
        self._edit_interval_ms = int(config["telegram.min_edit_interval_s"]) * 1000
        self._unauth_interval_ms = int(config["telegram.unauthorized_alert_interval_min"]) * 60_000
        self._outbox = Outbox(
            api,
            clock,
            max_messages=int(config["telegram.queue_max_messages"]),
            max_age_ms=int(config["telegram.queue_max_age_h"]) * 3_600_000,
            per_chat_per_min=int(config["telegram.max_msgs_per_min_per_chat"]),
        )
        self._pin = PinGuard(
            pin_hash,
            pin_salt,
            max_attempts=int(config["telegram.pin_max_attempts"]),
            lockout_ms=int(config["telegram.pin_lockout_min"]) * 60_000,
        )
        self._secrets = [s.reveal() for s in (pin_hash, pin_salt) if s is not None]
        self._poll_backoff = Backoff()
        self._offset = 0
        self._backlog_drained = False
        self._last_unauth_alert_ms: int | None = None
        self._facts = LedgerFacts(ledger)
        self._posts: dict[str, Post] = {}
        self._commands: dict[str, Callable[[list[str], Update], tuple[str, str] | None]] = {
            "/status": self._cmd_status,
            "/positions": self._cmd_positions,
            "/pause": self._cmd_pause,
            "/resume": self._cmd_resume,
        }

    @property
    def queue_depth(self) -> int:
        return self._outbox.depth

    # ------------------------------------------------------------------------------------------------ alerts

    def send(self, alert: Alert) -> None:
        """The ``AlertSink`` port: log locally and enqueue for the alerts chat. Never raises, never blocks."""
        try:
            text = self._clean(f"{alert.kind}: {alert.message}")
            _log.warning("alert %s", text, extra={"event": "telegram_alert", "kind": self._clean(str(alert.kind))})
            self._outbox.put(Outgoing("send", self._alerts_chat, text))
        except Exception:
            _log.exception("an alert could not be queued", extra={"event": "telegram_alert_failed"})

    def flush(self) -> None:
        """One delivery pass of the queue."""
        self._outbox.flush()

    # ------------------------------------------------------------------------------------------------ commands

    def poll_once(self) -> int:
        """Take pending commands and run them. Returns the number of updates handled; a Telegram failure returns 0."""
        now = self._clock.now_ms()
        if self._poll_backoff.waiting(now):
            return 0
        try:
            updates = self._api.get_updates(self._offset)
        except TelegramRateLimited as exc:
            self._poll_backoff.failed(now, retry_after_s=exc.retry_after_s)
            return 0
        except TelegramError as exc:
            self._poll_backoff.failed(now)
            _log.warning("telegram poll failed", extra={"event": "telegram_poll_failed", "reason": str(exc)})
            return 0
        self._poll_backoff.succeeded()
        if not self._backlog_drained:
            self._backlog_drained = True
            self._drop_backlog(updates)
            return len(updates)
        if updates:
            self.sync_posts()  # a post for what is already open goes out before any reply that describes it
        handled = 0
        for update in updates:
            if update.update_id < self._offset:
                continue
            self._offset = update.update_id + 1  # at most once: advance before acting, so a crash never replays
            self._handle_safely(update)
            handled += 1
        return handled

    def _drop_backlog(self, updates: list[Update]) -> None:
        """Whatever waited while the bot was down (or was already handled before a restart) is confirmed, not obeyed."""
        for update in updates:
            self._offset = max(self._offset, update.update_id + 1)
            parsed = _parse_command(update.text)
            if parsed is not None:
                self._audit_safely(update, parsed[0], "stale_dropped")

    def _handle_safely(self, update: Update) -> None:
        parsed = _parse_command(update.text)
        name = parsed[0] if parsed is not None else ""
        try:
            self._handle(update)
        except Exception:
            # No argument, token or PIN material in the log: only the command name and the exception type.
            _log.exception("a command failed", extra={"event": "telegram_command_failed", "command": name})
            self._audit_safely(update, name, "error")
            self._reply_safely("command failed")

    def _audit_safely(self, update: Update, name: str, result: str) -> None:
        try:
            self._audit(update, name, result)
        except Exception:
            _log.exception("a telegram audit record could not be written", extra={"event": "telegram_audit_failed"})

    def _reply_safely(self, text: str) -> None:
        try:
            self._reply(text)
        except Exception:
            _log.exception("a telegram reply could not be queued", extra={"event": "telegram_reply_failed"})

    def _handle(self, update: Update) -> None:
        parsed = _parse_command(update.text)
        if parsed is None:
            return
        name, args = parsed
        if self._clock.now_ms() // 1000 - update.date > MAX_COMMAND_AGE_S:
            self._audit(update, name, "stale_command")
            return
        if update.user_id != self._user_id or update.chat_id != self._control_chat:
            self._refuse_stranger(update, name)
            return
        handler = self._commands.get(name)
        if name == "/flatten":
            outcome = self._cmd_flatten(args, update)
        elif handler is None:
            outcome = ("unknown_command", "unknown command")
        else:
            outcome = handler(args, update)
        if outcome is not None:
            self._audit(update, name, outcome[0])
            self._reply(outcome[1])

    def _refuse_stranger(self, update: Update, name: str) -> None:
        self._audit(update, name, "refused_unauthorized")
        now = self._clock.now_ms()
        last = self._last_unauth_alert_ms
        if last is None or now - last >= self._unauth_interval_ms:
            self._last_unauth_alert_ms = now
            self.send(
                Alert(
                    "unauthorized_command",
                    f"unauthorized command refused from user {update.user_id} in chat {update.chat_id}",
                )
            )

    def _audit(self, update: Update, name: str, result: str) -> None:
        self._ledger.append(
            _AUDIT_KIND,
            {
                "user_id": update.user_id,
                "chat_id": update.chat_id,
                "command": name,
                "time": self._clock.now_ms(),
                "result": result,
            },
        )

    def _cmd_status(self, _args: list[str], _update: Update) -> tuple[str, str]:
        with self._gate_lock:
            paused = self._gate.paused
            shares = self._book.open_shares()
        positions = len({s.coin for s in shares})
        text = f"mode: {self._config['mode']}\nstate: {'paused' if paused else 'running'}\nopen positions: {positions}"
        return "ok", text

    def _cmd_positions(self, _args: list[str], _update: Update) -> tuple[str, str]:
        with self._gate_lock:
            shares = self._book.open_shares()
        if not shares:
            return "ok", "no open positions"
        lines = [
            f"PAPER {'LONG' if s.is_long else 'SHORT'} {s.coin} qty {s.qty} entry {s.entry_px} stop {s.stop_px}"
            for s in shares
        ]
        return "ok", "\n".join(lines)

    def _cmd_pause(self, _args: list[str], _update: Update) -> tuple[str, str]:
        try:
            with self._gate_lock:
                self._gate.pause()
        except RiskStateError:
            _log.exception("pause could not be saved", extra={"event": "telegram_pause_unsaved"})
            return "ok", "paused (in memory only: the state could not be saved)"
        return "ok", "paused: new entries are refused"

    def _cmd_resume(self, _args: list[str], _update: Update) -> tuple[str, str]:
        try:
            with self._gate_lock:
                self._gate.resume()
        except RiskStateError:
            _log.exception("resume failed", extra={"event": "telegram_resume_failed"})
            return "error", "resume failed: the risk state could not be read or saved; still paused"
        return "ok", "resumed: new entries are allowed"

    def _cmd_flatten(self, args: list[str], update: Update) -> tuple[str, str] | None:
        if len(args) != 1:
            return "usage", _USAGE["/flatten"]
        result = self._pin.check(args[0], self._clock.now_ms())
        self._outbox.put(Outgoing("delete", update.chat_id, message_id=update.message_id))  # the PIN leaves the chat
        if result == "pin_not_configured":
            return result, "flatten refused: no PIN is configured"
        if result == "pin_locked":
            return result, "flatten refused: too many wrong PINs, locked"
        if result == "bad_pin":
            locked = self._pin.is_locked(self._clock.now_ms())
            self.send(Alert("bad_pin", "flatten refused: wrong PIN" + (" (locked)" if locked else "")))
            return result, "flatten refused: wrong PIN"
        with self._gate_lock:
            report = self._manager.flatten(run_id=self._run_id)
            still_open = len(self._book.open_shares())
        text = (
            f"flatten: entries paused, {len(report)} close order(s) sent, {still_open} share(s) still open, "
            f"{len(report.in_flight)} entry(ies) in flight"
        )
        if still_open or report.in_flight or report.still_open:
            text += "; closing is pending, repeat /flatten until nothing is open"
        if not report.pause_saved:
            text += "; the pause could not be saved to disk"
        return "ok", text

    # ------------------------------------------------------------------------------------------------ posts

    def sync_posts(self) -> None:
        """Diff the share book into trade posts: a new post per new coin position, coalesced edits, a final edit.
        Never raises: a ledger or book failure is logged and the next call tries again."""
        try:
            self._sync_posts()
        except Exception:
            _log.exception("trade posts could not be synced", extra={"event": "telegram_sync_failed"})

    def _sync_posts(self) -> None:
        now = self._clock.now_ms()
        with self._gate_lock:
            states = self._book.states()
        live = live_views(states, self._facts)
        for coin, (view, share_ids) in live.items():
            post = self._posts.get(coin)
            text = self._clean(render(view))
            if post is None:
                post = self._posts[coin] = Post(view, set(share_ids))
                self._enqueue_post_send(post, text, now)
                continue
            post.view = view
            post.share_ids |= share_ids
            if post.message_id is None:
                if not post.send_pending:  # the first send was dropped: send the post again
                    self._enqueue_post_send(post, text, now)
            elif text != post.last_text and self._edit_due(post, now):
                self._enqueue_edit(post, text, now)
        for coin in [c for c in self._posts if c not in live]:
            post = self._posts[coin]
            if post.message_id is None:
                if not post.send_pending:
                    del self._posts[coin]  # never delivered, nothing to close
            elif self._edit_due(post, now):
                closing = self._facts.closing(post.share_ids)
                self._enqueue_edit(post, self._clean(render(post.view, closing)), now)
                del self._posts[coin]

    def _edit_due(self, post: Post, now: int) -> bool:
        return now - post.last_edit_ms >= self._edit_interval_ms

    def _enqueue_post_send(self, post: Post, text: str, now: int) -> None:
        post.send_pending, post.last_text, post.last_edit_ms = True, text, now

        def sent(message_id: int) -> None:
            post.message_id, post.send_pending = message_id, False

        def dropped() -> None:
            post.send_pending = False

        self._outbox.put(Outgoing("send", self._control_chat, text, on_sent=sent, on_dropped=dropped))

    def _enqueue_edit(self, post: Post, text: str, now: int) -> None:
        post.last_text, post.last_edit_ms = text, now
        self._outbox.put(Outgoing("edit", self._control_chat, text, message_id=post.message_id))

    # ------------------------------------------------------------------------------------------------ text

    def _reply(self, text: str) -> None:
        self._outbox.put(Outgoing("send", self._control_chat, self._clean(text)))

    def _clean(self, text: str) -> str:
        """``text`` without the bot token, PIN hash or salt, and within Telegram's message limit."""
        text = self._api.redact(text)
        for secret in self._secrets:
            text = text.replace(secret, _REDACTED)
        return text if len(text) <= MAX_TEXT_CHARS else text[: MAX_TEXT_CHARS - 1] + "…"


def _parse_command(text: str | None) -> tuple[str, list[str]] | None:
    """``("/pause", [])`` for ``/pause@bot``; ``None`` for anything that is not a command. Names are length capped."""
    if not text or not text.startswith("/"):
        return None
    parts = text.split()
    if not parts:
        return None
    name = parts[0].split("@", 1)[0].lower()[:_COMMAND_NAME_CAP]
    return name, parts[1:]
