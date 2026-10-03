"""F14 review round 1: item 4 (a 4xx on a send drops the message, no retry loop), item 5 (a half-configured PIN
refuses /flatten), and the 60 s backoff cap. Most of these PASS on the current code: they are guards, each names the
hand mutant it kills (review M5, M13, M21)."""

from __future__ import annotations

import pytest

from copytrade.core.events import Alert
from copytrade.core.secrets import SecretValue
from tests.telegram.helpers import ALERTS_CHAT, OWNER, PIN, PIN_HASH, SALT, make_bot, tg


def _reject(code: int) -> tuple[int, dict[str, object]]:
    return code, {"ok": False, "error_code": code, "description": "Bad Request: chat not found"}


# ------------------------------------------------------------------------------------------------ item 4 (M13)


@pytest.mark.parametrize("code", [400, 403])
def test_R1_4_GUARD_a_4xx_on_a_send_drops_the_message_and_the_next_is_delivered(new_bot, code: int) -> None:  # type: ignore[no-untyped-def]
    """Guard (kills M13: the rejected message is not popped and is retried or blocks the queue)."""
    env = new_bot()
    env.server.script = [_reject(code)]  # without the drop the same message is retried, succeeds, and "first" is delivered
    env.bot.send(Alert("first", "will be rejected"))
    env.bot.send(Alert("second", "must arrive"))
    env.bot.flush()
    sent = env.server.sent(ALERTS_CHAT)
    assert len(sent) == 1 and sent[0].startswith("second")
    assert env.bot.queue_depth == 0
    assert len(env.server.calls("sendMessage")) == 2  # one rejected attempt, one delivery: bounded
    env.bot.flush()
    assert len(env.server.calls("sendMessage")) == 2  # nothing left to retry


def test_R1_4_GUARD_a_4xx_does_not_back_off_the_queue(new_bot) -> None:  # type: ignore[no-untyped-def]
    """Guard (kills M13 variants that treat a 4xx like an outage and wait before the next message)."""
    env = new_bot()
    env.server.script = [_reject(400)]
    env.bot.send(Alert("first", "rejected"))
    env.bot.send(Alert("second", "no wait needed"))
    env.bot.flush()  # no clock advance
    assert [t.split(":")[0] for t in env.server.sent(ALERTS_CHAT)] == ["second"]


def test_R1_4_GUARD_a_rejected_edit_is_dropped_and_later_messages_still_flow(new_bot) -> None:  # type: ignore[no-untyped-def]
    """Guard (kills M13 for edits)."""
    env = new_bot()
    env.rig.open_share()
    env.pump()  # the post is delivered
    assert env.server.sent(OWNER)
    env.server.script = [_reject(400)]
    env.advance(120_000)
    env.rig.mark("SOL", "101")
    env.bot._outbox.put(tg("outbox").Outgoing("edit", OWNER, "changed", message_id=env.bot._posts["SOL"].message_id))
    env.bot.send(Alert("after", "still delivered"))
    env.bot.flush()
    assert any(t.startswith("after") for t in env.server.sent(ALERTS_CHAT))
    assert env.bot.queue_depth == 0


# ------------------------------------------------------------------------------------------------ item 5 (M5)


@pytest.mark.parametrize(
    ("pin_hash", "pin_salt"),
    [(SecretValue(PIN_HASH), None), (None, SecretValue(SALT))],
    ids=["hash_without_salt", "salt_without_hash"],
)
def test_R1_5_GUARD_half_configured_pin_refuses_flatten_as_pin_not_configured(new_bot, pin_hash, pin_salt) -> None:  # type: ignore[no-untyped-def]
    """Guard (kills M5: the None-guard ``or`` -> ``and`` would crash on the missing half or accept)."""
    env = new_bot()
    env.rig.open_share()
    orders_before = len(env.rig.orders())
    env.bot = make_bot(env.rig, env.base_url, env.clock, env.lock, pin_hash=pin_hash, pin_salt=pin_salt)
    env.bot.poll_once()  # the start-up drain
    env.command(f"/flatten {PIN}")  # must not raise
    assert not env.rig.gate.paused
    assert len(env.rig.orders()) == orders_before
    assert [a["result"] for a in env.audits() if a["command"] == "/flatten"] == ["pin_not_configured"]
    assert "no pin" in env.server.sent(OWNER)[-1].lower()
    env.command("/pause")  # other commands still work
    assert env.rig.gate.paused


@pytest.mark.parametrize(("pin_hash", "pin_salt"), [(SecretValue(PIN_HASH), None), (None, SecretValue(SALT))])
def test_R1_5_GUARD_pin_guard_itself_reports_not_configured_for_each_half(pin_hash, pin_salt) -> None:  # type: ignore[no-untyped-def]
    guard = tg("pin").PinGuard(pin_hash, pin_salt, max_attempts=3, lockout_ms=60_000)
    assert guard.check(PIN, 0) == "pin_not_configured"
    assert not guard.is_locked(0)  # it never counts as a failed attempt


# ------------------------------------------------------------------------------------------------ backoff cap (M21)


def test_R1_GUARD_backoff_doubles_from_1_s_and_is_capped_at_60_s() -> None:
    """Guard (kills M21: BACKOFF_CAP 60 -> 600)."""
    backoff = tg("outbox").Backoff()
    waits = []
    for _ in range(12):
        backoff.failed(0)
        waits.append(backoff.until_ms)
    assert waits == [1_000, 2_000, 4_000, 8_000, 16_000, 32_000] + [60_000] * 6
    backoff.succeeded()
    backoff.failed(0)
    assert backoff.until_ms == 1_000


def test_R1_GUARD_a_long_outage_never_makes_the_queue_wait_more_than_60_s(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.mode = "down"
    env.bot.send(Alert("x", "y"))
    for _ in range(10):  # each pass jumps past the current wait and fails again
        env.advance(61_000)
        env.bot.flush()
    env.server.mode = "ok"
    env.advance(61_000)
    env.bot.flush()
    assert len(env.server.sent(ALERTS_CHAT)) == 1
