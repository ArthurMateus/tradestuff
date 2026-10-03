"""F14 review round 1, items 2 and 3.

Item 2: a handler that fails gives an ``error`` audit and a "command failed" reply, and the poll loop carries on;
``poll_once`` and ``sync_posts`` never raise. The failures are real: a lone-surrogate PIN argument (valid JSON from
Telegram, ``UnicodeEncodeError`` in the PIN hash) and a dead ledger (its file descriptor closed).
Item 3: every PositionBook read the bot makes happens under ``gate_lock`` and the ledger is never read under it.
The book and ledger are wrapped in a delegating observer (real behaviour) that records the lock depth of each call.
"""

from __future__ import annotations

from typing import Any

from copytrade.telegram.bot import TelegramBot
from tests.telegram.helpers import OWNER, PIN

SURROGATE_FLATTEN = "/flatten \ud800"


class DepthSpy:
    """Delegates everything to ``inner`` and records the gate-lock depth at each call of the named methods."""

    def __init__(self, inner: Any, lock: Any, names: tuple[str, ...] | None) -> None:
        self._inner, self._lock, self._names = inner, lock, names
        self.depths: dict[str, list[int]] = {}

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr) or (self._names is not None and name not in self._names):
            return attr

        def call(*a: Any, **kw: Any) -> Any:
            self.depths.setdefault(name, []).append(self._lock.depth)
            return attr(*a, **kw)

        return call


def _rebuild(env: Any, *, book: Any = None, ledger: Any = None) -> Any:
    r = env.rig
    return TelegramBot(
        config=r.config, api=env.bot._api, gate=r.gate, manager=r.mgr, book=book or r.book,
        ledger=ledger or r.env.ledger, clock=env.clock, gate_lock=env.lock, run_id="run1",
        pin_hash=env.bot._pin._hash, pin_salt=env.bot._pin._salt,
    )


# ------------------------------------------------------------------------------------------------ item 2


def test_R1_2_a_failing_handler_audits_error_replies_command_failed_and_the_loop_goes_on(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text(SURROGATE_FLATTEN)
    env.server.push_text("/pause")
    handled = env.bot.poll_once()  # must not raise
    env.bot.flush()
    assert handled == 2
    assert [(a["command"], a["result"]) for a in env.audits()] == [("/flatten", "error"), ("/pause", "ok")]
    assert env.rig.gate.paused  # the later update was still handled
    replies = [t.lower() for t in env.server.sent(OWNER)]
    assert any("command failed" in t for t in replies)
    assert any("paused" in t for t in replies)


def test_R1_2_the_failure_reply_does_not_echo_the_argument_or_secrets(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command(SURROGATE_FLATTEN)
    out = env.server.all_outgoing_text()
    assert "\ud800" not in out
    assert env.bot._pin._hash.reveal() not in out
    assert env.bot._pin._salt.reveal() not in out


def test_R1_2_a_failed_flatten_is_not_replayed_by_the_next_poll(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command(SURROGATE_FLATTEN)
    assert env.bot.poll_once() == 0  # the offset moved past the failed update
    assert [a["result"] for a in env.audits()] == ["error"]


def test_R1_2_poll_once_and_sync_posts_never_raise_with_a_dead_ledger(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    env.rig.env.ledger.close()  # the audit and every ledger read now fail with a real OS error
    env.server.push_text("/status")
    env.server.push_text(f"/flatten {PIN}")
    env.server.push_text("/pause", user_id=222222222, chat_id=222222222)
    assert env.bot.poll_once() == 3
    env.bot.sync_posts()
    env.bot.flush()
    assert env.bot.poll_once() == 0  # nothing was left unconfirmed and nothing re-runs


def test_R1_2_sync_posts_never_raises_when_the_ledger_scan_fails(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    for path in sorted(env.rig.env.ledger._directory.iterdir()):  # tamper with the stored chain (OS level)
        data = path.read_bytes()
        if len(data) > 200:
            path.write_bytes(data[:100] + b"X" + data[101:])
            break
    env.bot.sync_posts()
    env.bot.sync_posts()
    env.bot.poll_once()


# ------------------------------------------------------------------------------------------------ item 3


def test_R1_3_status_positions_and_flatten_read_the_book_under_the_gate_lock(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    spy = DepthSpy(env.rig.book, env.lock, ("open_shares", "states", "state"))
    env.bot = _rebuild(env, book=spy)
    env.bot.poll_once()  # start-up poll (backlog drain) on an empty server: later commands are not drained
    env.command("/status")
    env.command("/positions")
    env.command(f"/flatten {PIN}")
    assert spy.depths["open_shares"], "the bot read no shares: the test observes nothing"
    assert len(spy.depths["open_shares"]) >= 3
    assert all(d >= 1 for d in spy.depths["open_shares"]), spy.depths


def test_R1_3_sync_posts_reads_the_book_states_under_the_gate_lock(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    spy = DepthSpy(env.rig.book, env.lock, ("open_shares", "states", "state"))
    env.bot = _rebuild(env, book=spy)
    env.bot.sync_posts()
    assert spy.depths["states"]
    assert all(d >= 1 for d in spy.depths["states"]), spy.depths


def test_R1_3_GUARD_the_ledger_is_never_read_or_written_by_the_bot_under_the_gate_lock(new_bot) -> None:  # type: ignore[no-untyped-def]
    """Guard (passes today). Kills the mutant that wraps the whole of sync_posts/_handle in gate_lock."""
    env = new_bot()
    env.rig.open_share()
    spy = DepthSpy(env.rig.env.ledger, env.lock, None)
    env.bot = _rebuild(env, ledger=spy)
    env.command("/status")
    env.command("/pause")
    env.rig.mark_and_fill("SOL", "90")  # let the stop path close it so the final post scans the ledger
    env.bot.sync_posts()
    assert spy.depths, "the bot touched no ledger method: the test observes nothing"
    assert all(d == 0 for ds in spy.depths.values() for d in ds), spy.depths
