"""F14.AC2 trade posts (v0 subset), F14.AC3 edit rate and F14.AC8 alerts and outage.

Deferred (not v0): leader win rate and P&L in the post (needs F6 scoring port), the "why" text beyond the fixed
"why unavailable" (F15 on hold), reports (AC7), /stats (AC9).
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from copytrade.core.events import Alert
from copytrade.core.money import Price
from tests.positions.helpers import WALLET_A, WALLET_B
from tests.telegram.helpers import ALERTS_CHAT, MIN_MS, OWNER, TOKEN

SEC = 1000


def _posts(env) -> list[str]:  # type: ignore[no-untyped-def]
    return env.server.sent(OWNER)


# ------------------------------------------------------------------------------------------------ AC2 posts


def test_F14_AC2_entry_post_shows_paper_direction_and_trade_fields(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    share = env.rig.open_share(coin="SOL", is_long=True)
    env.pump()
    assert len(_posts(env)) == 1
    text = _posts(env)[0]
    assert "PAPER" in text
    assert "\U0001f7e2" in text and "LONG" in text
    assert "SOL" in text
    assert str(share.entry_px) in text
    assert str(share.current_stop_px) in text
    assert "leverage" in text.lower()
    assert "why unavailable" in text.lower()
    assert "0xaaaa...aaaa" in text  # label: first 6 and last 4 characters of the address


def test_F14_AC2_short_post_has_the_red_marker(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share(coin="SOL", is_long=False)
    env.pump()
    assert "\U0001f534" in _posts(env)[0] and "SHORT" in _posts(env)[0]


def test_F14_AC2_a_second_pump_without_change_sends_nothing_more(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    for _ in range(3):
        env.pump()
        env.advance(30 * SEC)
    assert len(_posts(env)) == 1
    assert env.server.edits() == []


def test_F14_AC2_a_merged_position_has_one_post_that_is_edited_on_the_add(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share(tid=1, wallet=WALLET_A, coin="SOL")
    assert len(env.rig.held("SOL").share_ids) == 1
    env.pump()
    env.rig.at(env.rig.xtime.now + 5000)
    env.rig.open_share(tid=2, wallet=WALLET_B, coin="SOL")
    assert len(env.rig.held("SOL").share_ids) == 2, "rig precondition: two leaders merged into one position"
    env.advance(6 * SEC)
    env.pump()
    assert len(_posts(env)) == 1
    assert len(env.server.edits()) == 1


def test_F14_AC2_final_post_shows_realised_pnl_and_exit_reason(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    env.pump()
    env.rig.mark_and_fill("SOL", "98")
    env.advance(6 * SEC)
    env.pump()
    pnl = Decimal(str(env.rig.records("trade")[-1]["pnl_usd"])).quantize(Decimal("0.01"))
    reason = [e for e in env.rig.share_events() if e["event"] == "closed" or e.get("reason")][-1]["reason"]
    final = env.server.edits()[-1]["text"]
    assert "CLOSED" in final
    assert f"{pnl:+.2f}" in final
    assert str(reason) in final


# ------------------------------------------------------------------------------------------------ AC3 rate


def _move_stop(env, share, stop: str) -> None:  # type: ignore[no-untyped-def]
    env.rig.book.update(share.share_id, current_stop_px=Price(stop))


def test_F14_AC3_edits_are_coalesced_to_one_per_min_edit_interval(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()  # telegram.min_edit_interval_s = 5
    share = env.rig.open_share()
    env.pump()
    for stop in ("98.6", "98.7", "98.8"):
        env.advance(SEC)
        _move_stop(env, share, stop)
        env.pump()
    assert env.server.edits() == []  # still inside the interval since the post
    env.advance(5 * SEC)
    env.pump()
    assert len(env.server.edits()) == 1
    assert "98.8" in env.server.edits()[0]["text"]  # the latest state only


def test_F14_AC3_the_edit_interval_boundary(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    share = env.rig.open_share()
    env.pump()
    _move_stop(env, share, "98.9")
    env.advance(5 * SEC - 1)
    env.pump()
    assert env.server.edits() == []
    env.advance(1)
    env.pump()
    assert len(env.server.edits()) == 1


def test_F14_AC3_latest_state_is_visible_within_10_s_of_the_last_change(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    share = env.rig.open_share()
    env.pump()
    env.advance(20 * SEC)
    _move_stop(env, share, "99.1")
    env.pump()
    env.advance(10 * SEC)
    env.pump()
    assert any("99.1" in e["text"] for e in env.server.edits())


def test_F14_AC3_per_chat_message_cap_per_minute_and_order_kept(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()  # telegram.max_msgs_per_min_per_chat = 20
    for i in range(25):
        env.bot.send(Alert(kind="k", message=f"m{i:02d}"))
    env.bot.flush()
    assert len(env.server.sent(ALERTS_CHAT)) == 20
    env.advance(MIN_MS)
    env.bot.flush()
    sent = env.server.sent(ALERTS_CHAT)
    assert len(sent) == 25
    assert [t for t in sent if "m00" in t][0] == sent[0]
    assert "m24" in sent[-1]


def test_F14_AC3_a_429_retry_after_is_honoured_and_nothing_is_lost(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.script.append((429, {"ok": False, "error_code": 429, "description": "Too Many Requests",
                                    "parameters": {"retry_after": 30}}))
    env.bot.send(Alert(kind="k", message="first"))
    env.bot.flush()
    assert env.bot.queue_depth == 1
    count = env.server.request_count()
    env.advance(29 * SEC)
    env.bot.flush()
    assert env.server.request_count() == count  # no request before retry_after has passed
    env.advance(1 * SEC)
    env.bot.flush()
    assert env.bot.queue_depth == 0
    assert any("first" in t for t in env.server.sent(ALERTS_CHAT))


# ------------------------------------------------------------------------------------------------ AC8 alerts


def test_F14_AC8_alerts_go_only_to_the_alerts_chat_and_carry_kind_and_message(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.bot.send(Alert(kind="daily_loss_halt", message="daily_loss limit hit at equity 280"))
    env.bot.flush()
    assert env.server.sent(OWNER) == []
    (text,) = env.server.sent(ALERTS_CHAT)
    assert "daily_loss_halt" in text and "equity 280" in text


def test_F14_AC8_alert_text_never_contains_the_bot_token_or_pin_material(new_bot) -> None:  # type: ignore[no-untyped-def]
    from tests.telegram.helpers import PIN_HASH, SALT

    env = new_bot()
    env.bot.send(Alert(kind="k", message=f"boom {TOKEN} {PIN_HASH} {SALT}"))
    env.bot.flush()
    out = env.server.all_outgoing_text()
    assert TOKEN not in out and PIN_HASH not in out and SALT not in out


def test_F14_AC8_outage_never_blocks_or_raises_and_alerts_reach_the_local_log(new_bot, caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.WARNING)
    env = new_bot()
    env.server.mode = "down"
    started = time.monotonic()
    env.bot.send(Alert(kind="clock_unsynced", message="the exchange clock is unsynced"))
    env.bot.flush()
    env.bot.poll_once()
    env.bot.sync_posts()
    assert time.monotonic() - started < 5
    assert "clock_unsynced" in caplog.text
    assert env.bot.queue_depth == 1


def test_F14_AC8_trading_continues_during_an_outage(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.mode = "down"
    env.rig.open_share()  # the gate, broker and book work without Telegram
    env.pump()
    env.rig.mark_and_fill("SOL", "98")  # the stop still fires and the exit books
    assert env.rig.env.broker.position("SOL") is None


def test_F14_AC8_failed_delivery_backs_off_and_drains_in_order_on_recovery(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.mode = "down"
    for i in range(3):
        env.bot.send(Alert(kind="k", message=f"q{i}"))
    env.bot.flush()
    attempts = env.server.request_count()
    assert attempts >= 1
    env.bot.flush()
    assert env.server.request_count() == attempts  # backing off: no hammering
    env.server.mode = "ok"
    env.advance(61 * SEC)  # past the 60 s backoff cap
    env.bot.flush()
    sent = env.server.sent(ALERTS_CHAT)
    assert [t[-2:] for t in sent] == ["q0", "q1", "q2"]
    assert env.bot.queue_depth == 0


def test_F14_AC8_queue_is_capped_at_queue_max_messages_dropping_the_oldest(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot(telegram__queue_max_messages=10)
    env.server.mode = "down"
    for i in range(15):
        env.bot.send(Alert(kind="k", message=f"n{i:02d}"))
    assert env.bot.queue_depth == 10
    env.server.mode = "ok"
    env.advance(61 * SEC)
    for _ in range(3):
        env.bot.flush()
    sent = env.server.sent(ALERTS_CHAT)
    assert sent[0].endswith("n05") and sent[-1].endswith("n14")


def test_F14_AC8_queue_age_boundary_drops_only_messages_older_than_queue_max_age(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot(telegram__queue_max_age_h=1)
    env.server.mode = "down"
    env.bot.send(Alert(kind="k", message="old"))
    env.bot.flush()
    env.advance(3600 * SEC)  # exactly the age limit: still kept
    env.server.mode = "ok"
    env.bot.flush()
    assert any(t.endswith("old") for t in env.server.sent(ALERTS_CHAT))

    env2 = new_bot(telegram__queue_max_age_h=1)
    env2.server.mode = "down"
    env2.bot.send(Alert(kind="k", message="stale"))
    env2.bot.flush()
    env2.advance(3600 * SEC + 1)
    env2.server.mode = "ok"
    env2.bot.flush()
    assert not any(t.endswith("stale") for t in env2.server.sent(ALERTS_CHAT))
    assert env2.bot.queue_depth == 0


def test_F14_AC8_send_never_raises_even_for_odd_alerts(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.bot.send(Alert(kind="", message=""))
    env.bot.send(Alert(kind="k", message="x" * 100_000))
    env.bot.send(Alert(kind="k", message="\u0000‮ 中\U0001f600"))
    env.bot.flush()
    assert all(len(t) <= 4096 for t in env.server.sent(ALERTS_CHAT))  # Telegram's message limit
