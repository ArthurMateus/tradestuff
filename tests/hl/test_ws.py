"""F3.AC3: WebSocket limits, heartbeat, staleness and jittered reconnect. Spec: 04-spec.md F3.AC3, §3.2 hl.ws_* and
feed.stale_after_s, §5 "HL WebSocket disconnect or silent stall", invariants B1, B3, A2.

Integration level: the real feed, REST client, budget and monitors run against a fake connector and a fake HTTP
transport (both external boundaries) on a fake clock. No sleeping: ``FeedRig.run`` steps the clock a second at a time.
"""

from __future__ import annotations

import json

import pytest

from copytrade.core.domain import ActionKind
from copytrade.hl.errors import WsUserLimitError
from tests.hl.support import MINUTE, SECOND, WALLET_A, WALLET_B, FakeConnection, FeedRig, make_feed, ws_fills

pytestmark = pytest.mark.integration


def wallet(i: int) -> str:
    return f"0x{i:040x}"


def stalled(**overrides: object) -> FeedRig:
    """Connected, subscribed to WALLET_A, silent (no pongs), and every reconnect attempt fails: it stays stale."""
    fr = make_feed(auto_pong=False, **overrides)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    fr.connector.fail = True
    return fr


def started(*wallets: str, **overrides: object) -> FeedRig:
    fr = make_feed(**overrides)
    for w in wallets or (WALLET_A,):
        fr.feed.subscribe_user(w)
    fr.feed.tick()
    return fr


# --- user limit ----------------------------------------------------------------------------------------------------

def test_F3_AC3_the_eleventh_distinct_user_is_refused_locally_and_never_sent() -> None:
    fr = make_feed()
    for i in range(10):
        fr.feed.subscribe_user(wallet(i))
    with pytest.raises(WsUserLimitError):
        fr.feed.subscribe_user(wallet(10))
    fr.feed.tick()
    fr.run(3)
    assert sorted(fr.connector.current.subscribed_users()) == sorted(wallet(i) for i in range(10))
    assert wallet(10) not in fr.connector.current.subscribed_users()
    assert wallet(10) not in "".join(m for c in fr.connector.connections for m in c.sent)


def test_F3_AC3_the_eleventh_user_is_refused_after_the_connection_is_already_open() -> None:
    fr = started(*[wallet(i) for i in range(10)])
    sent = list(fr.connector.current.sent)
    with pytest.raises(WsUserLimitError):
        fr.feed.subscribe_user(wallet(99))
    fr.feed.tick()
    assert [m for m in fr.connector.current.sent if m not in sent and "subscribe" in m and wallet(99) in m] == []


def test_F3_AC3_resubscribing_a_known_user_is_a_no_op_not_an_error_and_not_a_second_message() -> None:
    fr = started(*[wallet(i) for i in range(10)])
    fr.feed.subscribe_user(wallet(3))
    fr.feed.tick()
    assert fr.connector.current.subscribed_users().count(wallet(3)) == 1


@pytest.mark.parametrize("limit", [1, 4])
def test_F3_AC3_the_limit_follows_config(limit: int) -> None:
    fr = make_feed(hl__ws_max_unique_users=limit)
    for i in range(limit):
        fr.feed.subscribe_user(wallet(i))
    with pytest.raises(WsUserLimitError):
        fr.feed.subscribe_user(wallet(limit))


def test_F3_AC3_unsubscribing_frees_a_slot() -> None:
    fr = started(wallet(1), wallet(2), hl__ws_max_unique_users=2)
    with pytest.raises(WsUserLimitError):
        fr.feed.subscribe_user(wallet(3))
    fr.feed.unsubscribe_user(wallet(1))
    fr.feed.subscribe_user(wallet(3))
    fr.feed.tick()
    msgs = fr.connector.current.sent_json()
    assert any(m.get("method") == "unsubscribe" and m["subscription"]["user"] == wallet(1) for m in msgs)
    assert wallet(3) in fr.connector.current.subscribed_users()


def test_F3_AC3_subscribe_message_has_the_documented_shape() -> None:
    fr = started(WALLET_A)
    msgs = fr.connector.current.sent_json()
    assert {"method": "subscribe", "subscription": {"type": "userFills", "user": WALLET_A}} in msgs


# --- connection budget ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("limit", [1, 3])
def test_F3_AC3_new_connections_never_exceed_the_per_minute_limit_when_the_link_flaps(limit: int) -> None:
    fr = make_feed(hl__ws_max_new_conns_per_min=limit)
    fr.connector.die_on_connect = True  # every new connection dies at once
    fr.feed.subscribe_user(WALLET_A)
    fr.run(10 * 60)
    times = fr.connector.connect_times
    assert len(times) >= 10  # it keeps trying
    for t in times:
        assert sum(1 for u in times if t <= u < t + MINUTE) <= limit


# --- heartbeat -----------------------------------------------------------------------------------------------------

def test_F3_AC3_pings_are_sent_at_the_configured_interval() -> None:
    fr = started(hl__ws_ping_interval_s=20)
    fr.run(65)
    assert 2 <= fr.connector.current.pings() <= 4  # at about 20 s, 40 s and 60 s


@pytest.mark.parametrize(("interval", "lo", "hi"), [(5, 10, 13), (50, 1, 2)])
def test_F3_AC3_ping_interval_follows_config(interval: int, lo: int, hi: int) -> None:
    fr = started(hl__ws_ping_interval_s=interval)
    fr.run(60)
    assert lo <= fr.connector.current.pings() <= hi


def test_F3_AC3_a_healthy_link_with_pongs_never_goes_stale() -> None:
    fr = started()
    fr.run(300)
    assert not fr.feed.is_stale(WALLET_A)
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) is None
    assert len(fr.connector.connections) == 1


# --- staleness -----------------------------------------------------------------------------------------------------

def test_F3_AC3_a_connection_with_no_message_or_pong_for_stale_after_s_is_marked_stale() -> None:
    fr = stalled(feed__stale_after_s=30)
    fr.run(29)
    assert not fr.feed.is_stale(WALLET_A)  # one second below the threshold
    fr.run(2)
    assert fr.feed.is_stale(WALLET_A)  # one second above


@pytest.mark.parametrize("stale_after", [5, 60])
def test_F3_AC3_stale_after_follows_config(stale_after: int) -> None:
    fr = stalled(feed__stale_after_s=stale_after)
    fr.run(stale_after - 1)
    assert not fr.feed.is_stale(WALLET_A)
    fr.run(2)
    assert fr.feed.is_stale(WALLET_A)


@pytest.mark.parametrize(
    "message",
    [{"channel": "pong"}, {"channel": "subscriptionResponse", "data": {"method": "subscribe"}}, ws_fills(WALLET_A, [1])],
    ids=["pong", "subscriptionResponse", "userFills"],
)
def test_F3_AC3_any_message_or_pong_resets_the_silence_timer(message: object) -> None:
    fr = stalled(feed__stale_after_s=30)
    fr.run(25)
    fr.connector.current.push(message)
    fr.run(29)  # 29 s after the message, 54 s after connecting
    assert not fr.feed.is_stale(WALLET_A)
    fr.run(3)
    assert fr.feed.is_stale(WALLET_A)


def test_F3_AC3_stale_feed_refuses_opens_and_adds_with_feed_stale_but_never_exits() -> None:
    fr = stalled()
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) is None
    fr.run(31)
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) == "feed_stale"
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.ADD) == "feed_stale"
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.REDUCE) is None
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.CLOSE) is None


def test_F3_AC3_a_wallet_with_no_subscription_fails_closed() -> None:
    fr = started(WALLET_A)
    assert fr.feed.refusal_reason(WALLET_B, ActionKind.OPEN) == "feed_stale"
    assert fr.feed.refusal_reason(WALLET_B, ActionKind.CLOSE) is None


def test_F3_AC3_before_the_first_connection_the_wallet_is_stale() -> None:
    fr = make_feed()
    fr.feed.subscribe_user(WALLET_A)
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) == "feed_stale"


def test_F3_AC3_one_alert_per_stale_episode_naming_the_wallets() -> None:
    fr = make_feed(auto_pong=False)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.subscribe_user(WALLET_B)
    fr.feed.tick()
    fr.run(31)
    alerts = fr.rig.alerts.of_kind("feed_stale")
    assert len(alerts) == 1
    assert WALLET_A in alerts[0].message and WALLET_B in alerts[0].message
    fr.connector.fail = True
    fr.run(120)  # still down: no second alert
    assert len(fr.rig.alerts.of_kind("feed_stale")) == 1


def test_F3_AC3_a_hard_disconnect_is_handled_like_a_stall_without_waiting_for_the_timer() -> None:
    fr = started()
    fr.connector.fail = True
    fr.connector.current.dead = True
    fr.run(2)
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) == "feed_stale"


# --- reconnect -----------------------------------------------------------------------------------------------------

def _stall_and_reconnect_gap_ms(fr: FeedRig, first: FakeConnection) -> int:
    closed_at: int | None = None
    for _ in range(200):
        fr.run(1)
        if closed_at is None and first.closed:
            closed_at = fr.clock.now
        if len(fr.connector.connections) > 1:
            assert closed_at is not None
            return fr.connector.connect_times[-1] - closed_at
    raise AssertionError("never reconnected")


def test_F3_AC3_a_stale_connection_is_closed_and_replaced_after_about_one_to_two_seconds() -> None:
    fr = make_feed(auto_pong=False)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    first = fr.connector.current
    gap = _stall_and_reconnect_gap_ms(fr, first)
    assert first.closed
    assert 1 * SECOND <= gap <= 3 * SECOND  # jittered 1-2 s, plus up to one tick
    assert WALLET_A in fr.connector.current.subscribed_users()  # resubscribed


@pytest.mark.parametrize("max_s", [5, 30, 120])
def test_F3_AC3_reconnect_backoff_grows_from_one_second_and_is_capped_at_the_configured_max(max_s: int) -> None:
    fr = make_feed(auto_pong=False, hl__ws_reconnect_backoff_max_s=max_s, hl__ws_max_new_conns_per_min=30)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    fr.connector.current.dead = True
    fr.connector.fail = True
    fr.run(1)
    start = fr.clock.now
    fr.run(8 * max_s)
    attempts = [t for t in fr.connector.attempt_times if t >= start]
    gaps = [b - a for a, b in zip([start, *attempts], attempts, strict=False)]
    assert len(gaps) >= 6
    for n, g in enumerate(gaps[:8]):
        assert g >= min(max_s, 2**n) * SECOND - SECOND  # the un-jittered exponential floor (start may be up to 1 tick early)
        assert g <= max_s * SECOND + SECOND  # never above the maximum (plus one tick of quantisation)
    if max_s == 5:
        assert all(g <= 6 * SECOND for g in gaps)


def test_F3_AC3_reconnect_delays_are_jittered_between_seeds() -> None:
    def attempts(seed: int) -> list[int]:
        fr = make_feed(seed=seed, auto_pong=False)
        fr.feed.subscribe_user(WALLET_A)
        fr.feed.tick()
        fr.connector.current.dead = True
        fr.connector.fail = True
        fr.run(400)
        return fr.connector.attempt_times

    assert len({tuple(attempts(s)) for s in range(1, 7)}) > 1


def test_F3_AC3_backoff_restarts_after_a_successful_reconnect() -> None:
    fr = make_feed(auto_pong=True)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    fr.connector.current.dead = True
    fr.connector.fail = True
    fr.run(40)  # backoff has grown
    fr.connector.fail = False
    fr.run(60)  # reconnects, then stays healthy
    assert len(fr.connector.connections) >= 2 and not fr.feed.is_stale(WALLET_A)
    fr.connector.current.dead = True
    n = len(fr.connector.connections)
    fr.run(4)
    assert len(fr.connector.connections) == n + 1  # back within one to two seconds (plus a tick)


def test_F3_AC3_after_reconnect_the_wallet_is_served_again_and_opens_are_allowed() -> None:
    fr = make_feed(auto_pong=True)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    fr.connector.current.dead = True
    fr.run(10)
    assert len(fr.connector.connections) >= 2
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) is None


def test_F3_AC3_the_ping_message_is_valid_json() -> None:
    fr = started()
    fr.run(25)
    assert all(isinstance(json.loads(m), dict) for m in fr.connector.current.sent)
