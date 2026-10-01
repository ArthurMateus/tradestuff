"""F14.AC1 authorisation and F14.AC5 PIN: fail closed, audited, alerted, rate limited, never leaking state."""

from __future__ import annotations

import logging

import pytest

from tests.telegram.helpers import ALERTS_CHAT, MIN_MS, OWNER, PIN, SALT, WRONG_PIN

STRANGER = 999


def _orders(env: object) -> int:
    return len(env.rig.orders())  # type: ignore[attr-defined]


def test_F14_AC1_five_unauthorised_commands_change_nothing_and_write_five_audits(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    before = _orders(env)
    cases = [
        ("/pause", STRANGER, OWNER), ("/flatten " + PIN, STRANGER, STRANGER), ("/pause", OWNER, STRANGER),
        ("/resume", STRANGER, STRANGER), ("/flatten " + PIN, OWNER, ALERTS_CHAT),
    ]
    for text, user, chat in cases:
        env.server.push_text(text, user_id=user, chat_id=chat)
    env.pump()
    assert not env.rig.gate.paused
    assert _orders(env) == before
    assert env.rig.held("SOL") is not None
    audits = env.audits()
    assert len(audits) == 5
    for a, (text, user, chat) in zip(audits, cases, strict=True):
        assert (a["user_id"], a["chat_id"], a["command"]) == (user, chat, text.split()[0])
        assert a["result"] == "refused_unauthorized"
        assert "time" in a
    assert PIN not in str([a for a in audits])


def test_F14_AC1_unauthorised_senders_get_no_reply_and_state_never_leaks(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    env.server.push_text("/status", user_id=STRANGER, chat_id=STRANGER)
    env.server.push_text("/positions", user_id=STRANGER, chat_id=STRANGER)
    env.pump()
    assert env.server.sent(STRANGER) == []
    assert "SOL" not in "\n".join(env.server.sent(STRANGER))


def test_F14_AC1_unauthorised_alert_is_rate_limited_boundaries(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()  # telegram.unauthorized_alert_interval_min = 10 in the fixture

    def unauthorised_alerts() -> int:
        return len([t for t in env.server.sent(ALERTS_CHAT) if "unauthor" in t.lower()])

    for _ in range(5):
        env.server.push_text("/pause", user_id=STRANGER, chat_id=STRANGER)
    env.pump()
    assert unauthorised_alerts() == 1
    env.advance(10 * MIN_MS - 1)
    env.command("/pause", user_id=STRANGER, chat_id=STRANGER)
    assert unauthorised_alerts() == 1
    env.advance(1)
    env.command("/pause", user_id=STRANGER, chat_id=STRANGER)
    assert unauthorised_alerts() == 2
    assert env.server.sent(OWNER) == []  # alerts never go to the control chat


@pytest.mark.parametrize("update", [
    {"update_id": 50, "edited_message": {"message_id": 1, "chat": {"id": 111111111}, "from": {"id": 111111111}}},
    {"update_id": 51, "channel_post": {"message_id": 2, "chat": {"id": -100}, "text": "/pause"}},
    {"update_id": 52, "callback_query": {"id": "x", "from": {"id": 111111111}, "data": "/pause"}},
    {"update_id": 53},
])
def test_F14_AC1_non_message_updates_are_ignored_without_state_change(new_bot, update) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_raw(update)
    env.pump()
    assert not env.rig.gate.paused


def test_F14_AC1_text_less_huge_and_unicode_updates_do_not_crash_or_execute(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text(None)
    env.server.push_text("/pause" + "x" * 10_000)
    env.server.push_text("‮/pause\u0000")
    env.server.push_text("")
    env.pump()
    assert not env.rig.gate.paused


def test_F14_AC1_duplicate_update_id_is_executed_once(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text("/pause", update_id=7)
    env.pump()
    env.server.push_text("/pause", update_id=7)  # the server redelivers the same update
    env.pump()
    assert len([a for a in env.audits() if a["command"] == "/pause"]) == 1


def test_F14_AC1_unknown_user_audit_is_written_even_when_telegram_replies_fail(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text("/pause", user_id=STRANGER, chat_id=STRANGER)
    env.bot.poll_once()
    env.server.mode = "down"
    env.bot.flush()
    assert len(env.audits()) == 1


# ---------------------------------------------------------------------------------------------------- PIN


def test_F14_AC5_correct_pin_flattens_and_the_pin_message_is_deleted(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    mid = env.command(f"/flatten {PIN}")
    assert env.rig.gate.paused
    assert env.lock.entered >= 1
    assert {"chat_id": OWNER, "message_id": mid} in env.server.deletes()
    assert [a["result"] for a in env.audits() if a["command"] == "/flatten"] == ["ok"]


def test_F14_AC5_wrong_pin_is_refused_audited_alerted_deleted_and_changes_nothing(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    before = _orders(env)
    mid = env.command(f"/flatten {WRONG_PIN}")
    assert _orders(env) == before
    assert not env.rig.gate.paused
    assert [a["result"] for a in env.audits()] == ["bad_pin"]
    assert any("pin" in t.lower() for t in env.server.sent(ALERTS_CHAT))
    assert any(m["message_id"] == mid for m in env.server.deletes())


def test_F14_AC5_flatten_without_a_pin_is_refused_with_usage(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    env.command("/flatten")
    assert not env.rig.gate.paused
    assert env.audits()[-1]["result"] == "usage"


def test_F14_AC5_lockout_after_max_attempts_blocks_even_the_right_pin_until_it_ends(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()  # pin_max_attempts 3, pin_lockout_min 15
    env.rig.open_share()
    for _ in range(3):
        env.command(f"/flatten {WRONG_PIN}")
    env.advance(15 * MIN_MS - 1)
    env.command(f"/flatten {PIN}")
    assert not env.rig.gate.paused
    assert env.audits()[-1]["result"] == "pin_locked"
    env.advance(1)
    env.command(f"/flatten {PIN}")
    assert env.rig.gate.paused
    assert env.audits()[-1]["result"] == "ok"


def test_F14_AC5_one_below_max_attempts_does_not_lock(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    for _ in range(2):
        env.command(f"/flatten {WRONG_PIN}")
    env.command(f"/flatten {PIN}")
    assert env.rig.gate.paused


def test_F14_AC5_failures_older_than_the_window_do_not_count(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    for _ in range(2):
        env.command(f"/flatten {WRONG_PIN}")
    env.advance(15 * MIN_MS + 1000)
    env.command(f"/flatten {WRONG_PIN}")
    env.command(f"/flatten {PIN}")
    assert env.rig.gate.paused


def test_F14_AC5_pause_and_status_stay_available_while_flatten_is_locked(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    for _ in range(3):
        env.command(f"/flatten {WRONG_PIN}")
    env.command("/pause")
    assert env.rig.gate.paused


def test_F14_AC5_unconfigured_pin_fails_closed(new_bot) -> None:  # type: ignore[no-untyped-def]
    from tests.telegram.helpers import make_bot

    env = new_bot()
    env.bot = make_bot(env.rig, env.base_url, env.clock, env.lock, pin_hash=None, pin_salt=None)
    env.rig.open_share()
    env.command(f"/flatten {PIN}")
    assert not env.rig.gate.paused
    assert env.audits()[-1]["result"] == "pin_not_configured"


def test_F14_AC5_the_pin_never_appears_in_messages_ledger_or_logs(new_bot, caplog: pytest.LogCaptureFixture) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG)
    env = new_bot()
    env.rig.open_share()
    env.command(f"/flatten {WRONG_PIN}")
    env.command(f"/flatten {PIN}")
    haystack = env.server.all_outgoing_text() + caplog.text + str([r.payload for r in env.rig.env.ledger.records()])
    for secret in (PIN, WRONG_PIN, SALT):
        assert secret not in haystack
