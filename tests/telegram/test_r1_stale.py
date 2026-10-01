"""F14 review round 1, item 1: a stale or redelivered command is never obeyed (RISK-12: a replayed /resume or
/flatten must not act). Pinned contracts: ``Update.date`` (seconds, from ``message.date``); ``bot.MAX_COMMAND_AGE_S``
= 60; the first successful poll after start takes the backlog without acting (audit ``stale_dropped``); a command
older than the limit is refused (audit ``stale_command``). Only the loopback fake Telegram server is faked.
"""

from __future__ import annotations

from typing import Any

from tests.telegram.helpers import OWNER, PIN, make_bot, tg

STALE_DROPPED = "stale_dropped"
STALE_COMMAND = "stale_command"


def _now_s(env) -> int:  # type: ignore[no-untyped-def]
    return env.clock.now // 1000


def _results(env, command: str | None = None) -> list[str]:  # type: ignore[no-untyped-def]
    return [a["result"] for a in env.audits() if command is None or a["command"] == command]


def _restart(env: Any) -> Any:
    """A new bot process over the same rig and the same Telegram server: offset memory is gone."""
    return make_bot(env.rig, env.base_url, env.clock, env.lock)


def test_R1_1_the_age_limit_is_a_code_constant_of_60_seconds() -> None:
    assert tg("bot").MAX_COMMAND_AGE_S == 60


def test_R1_1_update_carries_the_message_date(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text("/status", date=1_700_000_123)
    updates = env.bot._api.get_updates(0)
    assert [u.date for u in updates] == [1_700_000_123]


def test_R1_1_a_message_without_an_integer_date_is_dropped_fail_closed(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    raw = {"from": {"id": OWNER}, "chat": {"id": OWNER}, "message_id": 7, "text": "/pause"}
    env.server.push_raw({"update_id": 90, "message": dict(raw)})
    env.server.push_raw({"update_id": 91, "message": {**raw, "date": "yesterday"}})
    assert env.bot._api.get_updates(0) == []


def test_R1_1_first_poll_after_start_takes_the_backlog_without_acting(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot(prime=False)
    env.server.push_text("/pause")  # fresh by date, but it was sent before the bot started
    env.pump()
    assert not env.rig.gate.paused
    assert _results(env, "/pause") == [STALE_DROPPED]
    env.command("/pause")  # the next one is live
    assert env.rig.gate.paused
    assert _results(env, "/pause") == [STALE_DROPPED, "ok"]


def test_R1_1_the_backlog_is_confirmed_so_it_is_not_taken_again(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot(prime=False)
    env.server.push_text("/pause")
    env.pump()
    env.pump()
    assert env.server.updates == []  # a later getUpdates carried a higher offset
    assert _results(env) == [STALE_DROPPED]


def test_R1_1_backlog_with_many_updates_drops_all_and_audits_each_command(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot(prime=False)
    env.server.push_text("/pause")
    env.server.push_text("hello, not a command")
    env.server.push_text(f"/flatten {PIN}")
    env.server.push_text("/pause", user_id=222222222, chat_id=222222222)  # a stranger's backlog is dropped too
    env.pump()
    assert not env.rig.gate.paused
    assert _results(env) == [STALE_DROPPED] * 3  # the plain text is not a command: no audit
    assert env.rig.orders() == []


def test_R1_1_a_failed_first_poll_does_not_count_as_the_backlog_drain(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot(prime=False)
    env.server.push_text("/pause")
    env.server.mode = "down"
    env.pump()
    env.server.mode = "ok"
    env.advance(120_000)  # past any poll backoff
    env.pump()
    assert not env.rig.gate.paused
    assert _results(env, "/pause") == [STALE_DROPPED]


def test_R1_1_a_restarted_bot_never_replays_an_old_resume(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.gate.pause()
    env.command("/resume")  # executed once, legitimately; Telegram has not confirmed it yet
    assert not env.rig.gate.paused
    env.rig.gate.pause()  # e.g. the drawdown or manual pause is back on
    assert env.rig.gate.paused
    bot2 = _restart(env)
    bot2.poll_once()
    bot2.sync_posts()
    bot2.flush()
    assert env.rig.gate.paused, "the replayed /resume cleared the pause"
    assert _results(env, "/resume") == ["ok", STALE_DROPPED]


def test_R1_1_a_restarted_bot_never_replays_an_old_flatten(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share(coin="SOL")
    env.command(f"/flatten {PIN}")
    assert env.rig.orders()
    env.rig.gate.resume()
    orders_before = len(env.rig.orders())
    bot2 = _restart(env)
    bot2.poll_once()
    assert not env.rig.gate.paused, "the replayed /flatten paused the gate"
    assert len(env.rig.orders()) == orders_before
    assert _results(env, "/flatten") == ["ok", STALE_DROPPED]


def test_R1_1_a_command_older_than_the_limit_is_refused_and_audited(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text("/pause", date=_now_s(env) - 61)
    env.pump()
    assert not env.rig.gate.paused
    assert _results(env, "/pause") == [STALE_COMMAND]


def test_R1_1_age_boundary_exactly_at_the_limit_runs_one_over_is_refused(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text("/pause", date=_now_s(env) - 60)
    env.pump()
    assert env.rig.gate.paused
    env.rig.gate.resume()
    env.server.push_text("/pause", date=_now_s(env) - 61)
    env.pump()
    assert not env.rig.gate.paused
    assert _results(env, "/pause") == ["ok", STALE_COMMAND]


def test_R1_1_a_fresh_command_runs(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text("/pause", date=_now_s(env) - 5)
    env.pump()
    assert env.rig.gate.paused
    assert _results(env, "/pause") == ["ok"]


def test_R1_1_a_command_that_waited_in_telegram_past_the_limit_is_refused(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text("/pause")
    env.advance(61_000)  # the bot was slow or blocked before taking it
    env.pump()
    assert not env.rig.gate.paused
    assert _results(env, "/pause") == [STALE_COMMAND]


def test_R1_1_a_stale_flatten_with_the_right_pin_closes_nothing(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    env.server.push_text(f"/flatten {PIN}", date=_now_s(env) - 3600)
    env.pump()
    assert env.rig.orders() == []
    assert not env.rig.gate.paused
    assert _results(env, "/flatten") == [STALE_COMMAND]
