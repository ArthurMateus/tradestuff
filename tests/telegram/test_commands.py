"""F14.AC4 (v0 subset: /status /positions /pause /resume /flatten) and F14.AC6 (visibility lock, v0 part).

The commands act on the REAL gate, broker, book and ledger. Deferred (stage 2 / not v0): /pnl, /traders, /stats,
reports (F14.AC7, AC9), the free-disk and archive lines of /status.
"""

from __future__ import annotations

import re

from copytrade.core.domain import ActionKind
from tests.positions.helpers import WALLET_A, WALLET_B, make_signal
from tests.telegram.helpers import OWNER, PIN

FORBIDDEN = (
    "p-value", "p value", "t statistic", "standard error", "bootstrap", "LB_r", "UB_r", "on track", "on-track",
    "verdict", "traffic light", "probability of pass", "P2c", "B0d", "K9", "S4",
)


def _last_reply(env) -> str:  # type: ignore[no-untyped-def]
    texts = env.server.sent(OWNER)
    assert texts, "no reply reached the control chat"
    return texts[-1]


def test_F14_AC4_status_shows_mode_state_and_open_positions(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command("/status")
    text = _last_reply(env).lower()
    assert "mode: paper" in text
    assert "state: running" in text
    assert "open positions: 0" in text
    env.rig.open_share()
    env.command("/status")
    assert "open positions: 1" in _last_reply(env).lower()


def test_F14_AC4_status_shows_paused_after_pause(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command("/pause")
    env.command("/status")
    assert "state: paused" in _last_reply(env).lower()


def test_F14_AC4_pause_and_resume_drive_the_real_gate_under_the_lock(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    gate, lock = env.rig.gate, env.lock
    depths: dict[str, list[int]] = {"pause": [], "resume": []}
    for name in depths:
        real = getattr(gate, name)

        def observed(*a, _real=real, _name=name, **kw):  # type: ignore[no-untyped-def]
            depths[_name].append(lock.depth)  # the lock depth at the moment the real gate is driven
            return _real(*a, **kw)

        setattr(gate, name, observed)
    env.command("/pause")
    assert env.rig.gate.paused
    assert depths["pause"] == [1], "the real gate pause must run exactly once, inside the shared gate_lock"
    assert lock.entered >= 1
    assert "paused" in _last_reply(env).lower()
    env.command("/resume")
    assert not env.rig.gate.paused
    assert depths["resume"] == [1], "the real gate resume must run exactly once, inside the shared gate_lock"
    assert "resumed" in _last_reply(env).lower()
    assert [a["result"] for a in env.audits()] == ["ok", "ok"]
    assert [a["command"] for a in env.audits()] == ["/pause", "/resume"]


def test_F14_AC4_a_paused_gate_really_refuses_new_entries(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command("/pause")
    now = env.rig.xtime.now
    env.rig.book_at("SOL", "100", now + 1000)
    env.rig.feed(make_signal(1, ActionKind.OPEN, ts=now - 100))
    env.rig.step(now + 1000)
    assert env.rig.share_of(WALLET_A, "SOL") is None
    env.command("/resume")
    env.rig.feed(make_signal(2, ActionKind.OPEN, ts=now + 900))
    env.rig.step(now + 2000)
    assert env.rig.share_of(WALLET_A, "SOL") is not None


def test_F14_AC4_positions_lists_each_open_share(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command("/positions")
    assert "no open positions" in _last_reply(env).lower()
    env.rig.open_share(coin="SOL", is_long=True)
    env.command("/positions")
    text = _last_reply(env)
    assert "SOL" in text and "LONG" in text
    assert "PAPER" in text


def test_F14_AC4_flatten_closes_every_share_through_the_gate_and_pauses(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    share = env.rig.open_share()
    env.command(f"/flatten {PIN}")
    assert env.rig.gate.paused
    assert env.lock.entered >= 1
    reasons = [o["reason"] for o in env.rig.orders() if o.get("reason")]
    assert "flatten" in reasons or env.rig.env.broker.pending_exits()
    now = env.rig.xtime.now
    env.rig.book_at("SOL", "100", now + 1000)
    env.rig.step(now + 1000)
    assert env.rig.env.broker.position("SOL") is None
    assert share.share_id
    assert "flatten" in _last_reply(env).lower()


def test_F14_AC4_flatten_with_nothing_open_still_pauses_and_replies(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command(f"/flatten {PIN}")
    assert env.rig.gate.paused
    assert env.server.sent(OWNER)


def test_F14_AC4_flatten_twice_in_a_row_sends_no_second_order_per_share(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    env.command(f"/flatten {PIN}")
    first = len(env.rig.orders())
    env.command(f"/flatten {PIN}")
    assert len(env.rig.orders()) == first


def test_F14_AC4_flatten_reports_what_is_still_open_instead_of_claiming_success(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share()
    env.command(f"/flatten {PIN}")
    text = _last_reply(env).lower()
    assert "pending" in text or "still open" in text or "closing" in text  # the exit has not filled yet


def test_F14_AC4_unknown_command_is_audited_and_changes_nothing(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command("/dance now")
    assert not env.rig.gate.paused
    assert env.audits()[-1]["result"] == "unknown_command"
    assert env.audits()[-1]["command"] == "/dance"


def test_F14_AC4_a_command_with_the_bot_suffix_is_understood(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command("/pause@copytrade_bot")
    assert env.rig.gate.paused


def test_F14_AC4_commands_survive_a_telegram_reply_outage(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.push_text("/pause")
    env.bot.poll_once()
    env.server.mode = "down"
    env.bot.flush()
    assert env.rig.gate.paused  # the action does not depend on the reply getting out


def test_F14_AC4_poll_failure_never_raises_and_changes_nothing(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.server.mode = "down"
    assert env.bot.poll_once() == 0
    assert not env.rig.gate.paused


def test_F14_AC4_commands_reply_to_the_control_chat_only(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.command("/status")
    assert env.server.sent(OWNER)
    assert all(c["chat_id"] == OWNER for c in env.server.calls("sendMessage"))


def test_F14_AC6_status_and_positions_carry_no_forbidden_or_outcome_content(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()
    env.rig.open_share(wallet=WALLET_A)
    env.rig.open_share(tid=2, wallet=WALLET_B, coin="ETH")
    env.rig.mark_and_fill("SOL", "98")  # a stop-out: a realised loss now exists
    env.command("/status")
    env.command("/positions")
    for text in env.server.sent(OWNER):
        low = text.lower()
        assert not any(f.lower() in low for f in FORBIDDEN)
        assert "pnl" not in low and "p&l" not in low and "realised" not in low and "win rate" not in low
        assert not re.search(r"\b(pass|fail)\b", low)
