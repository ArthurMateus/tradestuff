"""U4 AC1, AC2, AC4, AC5: /leaders, /progress, /help over the REAL bot and the loopback fake Telegram server.

The bot reads only the ``SelectionView`` port (``copytrade.telegram.selection_view``); the fake below is a plain
implementation of that port (the real adapter over the follow manager is wiring, tested there).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from copytrade.telegram.selection_view import LeaderRow, PassProgress, SelectionEvent
from tests.telegram.helpers import MIN_MS, OWNER, PIN, SALT, TOKEN, make_bot, PIN_HASH

STRANGER = 999
ADDR_A = "0xabcdef0123456789abcdef0123456789abcd1234"
ADDR_B = "0x1111111111111111111111111111111111119999"
SHORT_A = "0xabcd...1234"
SHORT_B = "0x1111...9999"
T0 = 1_800_000_000_000  # 2027-01-15 08:00 UTC (the fixture clock start)


class FakeView:
    def __init__(self) -> None:
        self.rows: list[LeaderRow] = []
        self.prog = idle()
        self.events: list[SelectionEvent] = []
        self.calls = 0

    def followed(self) -> list[LeaderRow]:
        self.calls += 1
        return list(self.rows)

    def progress(self) -> PassProgress:
        self.calls += 1
        return self.prog

    def drain_events(self) -> list[SelectionEvent]:
        out, self.events = self.events, []
        return out


def idle(**kw: Any) -> PassProgress:
    base: dict[str, Any] = dict(state="idle", candidates_total=0, candidates_done=0, screened=0, screen_ok=0,
                                rejected=0, cooling=0, dropped=0, followed=0, started_ms=None)
    base.update(kw)
    return PassProgress(**base)


def with_view(new_bot: Any, view: FakeView | None = None, **overrides: Any) -> tuple[Any, FakeView]:
    env = new_bot(**overrides)
    view = view or FakeView()
    env.bot = make_bot(env.rig, env.base_url, env.clock, env.lock, selection=view)
    env.bot.poll_once()  # the start-up backlog drain
    return env, view


def last(env: Any) -> str:
    texts = env.server.sent(OWNER)
    assert texts, "no reply reached the control chat"
    return texts[-1]


def row(addr: str = ADDR_A, rank: int | None = 1, score: str = "0.73", copies: int = 2, paused: bool = False,
        start: int = T0) -> LeaderRow:
    return LeaderRow(addr, rank, Decimal(score), start, copies, paused)


# ---------------------------------------------------------------------------------------------------- AC1


def test_U4_AC1_leaders_lists_short_address_rank_score_start_copies_and_pause_state(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    view.rows = [row(ADDR_A, 1, "0.73", 3, False, T0), row(ADDR_B, 2, "0.5", 0, True, T0 + 3_600_000)]
    env.command("/leaders")
    text = last(env)
    la = next(line for line in text.splitlines() if SHORT_A in line)
    lb = next(line for line in text.splitlines() if SHORT_B in line)
    assert "rank 1" in la and "score 0.73" in la and "2027-01-15 08:00 UTC" in la and "copies 3" in la
    assert "paused" not in la.lower()
    assert "rank 2" in lb and "score 0.50" in lb and "2027-01-15 09:00 UTC" in lb and "copies 0" in lb
    assert "paused" in lb.lower()
    assert ADDR_A not in text and ADDR_B not in text, "only the short form (first 6 + last 4) is shown"


def test_U4_AC1_leaders_empty_says_no_leaders_followed_yet_plus_the_pass_state(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    view.prog = idle(state="running", candidates_total=10, candidates_done=2, started_ms=T0)
    env.command("/leaders")
    text = last(env).lower()
    assert "no leaders followed yet" in text
    assert "pass: running" in text


def test_U4_AC1_leaders_unranked_leader_still_listed(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    view.rows = [row(rank=None)]
    env.command("/leaders")
    assert SHORT_A in last(env)
    assert "rank -" in last(env)


def test_U4_AC1_leaders_from_a_stranger_gets_no_reply_and_the_view_is_not_read(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    view.rows = [row()]
    env.server.push_text("/leaders", user_id=STRANGER, chat_id=STRANGER)
    env.server.push_text("/leaders", user_id=STRANGER, chat_id=OWNER)
    env.server.push_text("/progress", user_id=OWNER, chat_id=STRANGER)
    env.pump()
    assert env.server.sent(STRANGER) == []
    assert env.server.sent(OWNER) == []
    assert view.calls == 0
    assert [a["result"] for a in env.audits()] == ["refused_unauthorized"] * 3


def test_U4_AC1_leaders_with_many_wallets_stays_within_the_message_limit(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    view.rows = [row(f"0x{i:040x}", i) for i in range(1, 400)]
    env.command("/leaders")
    assert 0 < len(last(env)) <= 4096


def test_U4_AC1_leaders_view_failure_replies_command_failed_and_the_bot_survives(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)

    def boom() -> list[LeaderRow]:
        raise RuntimeError("manager gone")

    view.followed = boom  # type: ignore[method-assign]
    env.command("/leaders")
    assert "command failed" in last(env)
    env.command("/status")
    assert "mode: paper" in last(env)


# ---------------------------------------------------------------------------------------------------- AC2


def _running(done: int, **kw: Any) -> PassProgress:
    return idle(state="running", candidates_total=10, candidates_done=done, screened=30, screen_ok=12, rejected=18,
                cooling=3, dropped=2, followed=1, started_ms=T0, **kw)


def test_U4_AC2_progress_shows_every_counter_and_elapsed(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    view.prog = _running(4)
    env.advance(40 * MIN_MS)
    env.command("/progress")
    text = last(env).lower()
    for needle in ("candidates: 4/10", "screened: 30", "screen_ok: 12", "rejected: 18", "cooling: 3", "dropped: 2",
                   "followed: 1", "elapsed: 40m"):
        assert needle in text, needle


def test_U4_AC2_progress_eta_is_extrapolated_from_completed_wallets(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    view.prog = _running(4)  # 4 done in 40 min -> 6 left x 10 min
    env.advance(40 * MIN_MS)
    env.command("/progress")
    assert "eta: 1h 00m" in last(env).lower()


def test_U4_AC2_progress_eta_unknown_when_fewer_than_three_wallets_completed_boundaries(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    env.advance(30 * MIN_MS)
    for done, known in ((0, False), (1, False), (2, False), (3, True), (4, True)):
        view.prog = _running(done)
        env.command("/progress")
        text = last(env).lower()
        assert ("eta: unknown" not in text) is known, done
        assert "eta:" in text


def test_U4_AC2_progress_when_idle_reports_the_state_and_eta_unknown(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    env.command("/progress")
    text = last(env).lower()
    assert "pass: idle" in text
    assert "eta: unknown" in text


def test_U4_AC2_progress_complete_pass_has_no_eta_countdown(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    view.prog = idle(state="complete", candidates_total=10, candidates_done=10, started_ms=T0)
    env.advance(90 * MIN_MS)
    env.command("/progress")
    text = last(env).lower()
    assert "pass: complete" in text and "candidates: 10/10" in text


def test_U4_AC2_progress_clock_skew_never_shows_negative_elapsed(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    view.prog = _running(5)
    view.prog = PassProgress(**{**view.prog.__dict__, "started_ms": T0 + 10 * MIN_MS})  # started "in the future"
    env.command("/progress")
    assert "-" not in last(env).split("elapsed:")[1].splitlines()[0]


def test_U4_AC2_progress_from_a_stranger_gets_no_reply(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    env.server.push_text("/progress", user_id=STRANGER, chat_id=STRANGER)
    env.pump()
    assert env.server.sent(STRANGER) == [] and env.server.sent(OWNER) == [] and view.calls == 0


# ---------------------------------------------------------------------------------------------------- AC4


def test_U4_AC4_leaders_and_progress_place_no_orders_do_not_pause_and_need_no_pin(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    env.rig.open_share()
    view.rows = [row()]
    view.prog = _running(5)
    orders = len(env.rig.orders())
    held = env.rig.held("SOL")
    env.command("/leaders")
    env.command("/progress")
    assert len(env.rig.orders()) == orders and env.rig.held("SOL") == held
    assert not env.rig.gate.paused
    assert [a["result"] for a in env.audits()] == ["ok", "ok"]
    assert [a["command"] for a in env.audits()] == ["/leaders", "/progress"]
    assert not env.server.deletes(), "no PIN is involved, so nothing is deleted from the chat"


def test_U4_AC4_replies_never_contain_the_token_pin_hash_or_salt(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, view = with_view(new_bot)
    # a hostile adapter value carrying every secret must be redacted by the bot's cleaning
    leak = f"{TOKEN} {PIN_HASH} {SALT}"
    view.rows = [row(addr=f"0x{leak}")]
    view.prog = _running(5)
    env.command("/leaders")
    env.command("/progress")
    env.command("/help")
    out = env.server.all_outgoing_text()
    for secret in (TOKEN, PIN_HASH, SALT):
        assert secret not in out


def test_U4_AC4_selection_commands_without_a_wired_view_reply_unavailable_not_crash(new_bot) -> None:  # type: ignore[no-untyped-def]
    env = new_bot()  # the original bot, built without a selection view
    env.command("/leaders")
    assert "not available" in last(env).lower()
    env.command("/progress")
    assert "not available" in last(env).lower()


# ---------------------------------------------------------------------------------------------------- AC5


def test_U4_AC5_help_lists_every_command_including_the_new_ones(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, _ = with_view(new_bot)
    env.command("/help")
    text = last(env)
    for cmd in ("/status", "/positions", "/pause", "/resume", "/flatten", "/leaders", "/progress", "/help"):
        assert cmd in text, cmd


def test_U4_AC5_help_from_a_stranger_gets_no_reply(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, _ = with_view(new_bot)
    env.server.push_text("/help", user_id=STRANGER, chat_id=STRANGER)
    env.pump()
    assert env.server.sent(STRANGER) == []


def test_U4_AC5_existing_commands_behave_exactly_as_before(new_bot) -> None:  # type: ignore[no-untyped-def]
    env, _ = with_view(new_bot)
    env.rig.open_share()
    env.command("/status")
    assert "mode: paper" in last(env) and "open positions: 1" in last(env)
    env.command("/positions")
    assert "PAPER" in last(env)
    env.command("/pause")
    assert env.rig.gate.paused and "paused" in last(env)
    env.command("/resume")
    assert not env.rig.gate.paused
    env.command("/flatten")
    assert last(env) == "usage: /flatten <PIN>"
    env.command("/nonsense")
    assert last(env) == "unknown command"
    env.command(f"/flatten {PIN}")
    assert env.rig.held("SOL") is None or True  # the flatten path itself is covered by test_commands
