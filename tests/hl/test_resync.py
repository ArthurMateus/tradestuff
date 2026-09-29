"""F3.AC4: gap resync. After a disconnect, before any new decision for an affected wallet, fills in
[last seen exchange ts, now] are fetched with userFillsByTime and merged by tid with 0 duplicates, and the gap is
ledgered as ``data_gap`` downtime. A snapshot message (isSnapshot: true) is deduplicated the same way.

Spec: 04-spec.md F3.AC4, §5 (WebSocket row), invariants B3, A2, A5-style idempotence. Integration level: real feed, REST
client, budget and monitors over the fake connector and fake HTTP transport.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.domain import ActionKind
from tests.hl.support import (
    SECOND,
    WALLET_A,
    WALLET_B,
    FakeConnection,
    FeedRig,
    fill_json,
    make_feed,
    raising,
    ws_fills,
)

pytestmark = pytest.mark.integration


def _fill_time(tid: int) -> int:
    return int(fill_json(tid)["time"])


def connected_with_history(
    *tids: int, wallets: tuple[str, ...] = (WALLET_A,), **overrides: Any
) -> tuple[FeedRig, int]:
    """A feed connected and subscribed, having received ``tids`` live for the first wallet. Returns the rig and the
    local time of the last message received (the moment the link went quiet)."""
    fr = make_feed(auto_pong=False, **overrides)
    for w in wallets:
        fr.feed.subscribe_user(w)
    fr.feed.tick()
    fr.run(2)
    if tids:
        fr.connector.current.push(ws_fills(wallets[0], list(tids)))
    fr.run(1)
    return fr, fr.clock.now


def drop_and_reconnect(fr: FeedRig, *, down_s: int = 40, on_reconnect: Any = None) -> int:
    """Kill the link, stay disconnected for ``down_s`` seconds, then allow reconnection. Returns the reconnect time."""
    first = fr.connector.current
    first.dead = True
    fr.connector.fail = True
    fr.run(down_s)
    fr.connector.on_connect = on_reconnect
    fr.connector.fail = False
    n = len(fr.connector.connections)
    for _ in range(120):
        fr.run(1)
        if len(fr.connector.connections) > n:
            break
    assert len(fr.connector.connections) > n, "never reconnected"
    fr.run(1)
    return fr.connector.connect_times[-1]


# --- the resync request ---------------------------------------------------------------------------------------------

def test_F3_AC4_reconnect_fetches_fills_since_the_last_seen_exchange_timestamp_and_merges_by_tid() -> None:
    fr, _ = connected_with_history(1, 2, 3)
    assert fr.sink.tids() == [1, 2, 3]
    fr.server_fills.extend(fill_json(t) for t in (2, 3, 4, 5, 6))  # 2 and 3 were already seen live
    reconnected_at = drop_and_reconnect(fr)
    calls = [c for c in fr.rig.http.calls if c.body["type"] == "userFillsByTime"]
    assert len(calls) == 1
    body = calls[0].body
    assert body["user"] == WALLET_A
    assert body["startTime"] == _fill_time(3)  # the last exchange timestamp seen for the wallet
    assert body.get("endTime") is None or body["endTime"] >= reconnected_at
    assert fr.sink.tids() == [1, 2, 3, 4, 5, 6]  # 0 duplicates, in order


def test_F3_AC4_resync_uses_the_critical_class_never_the_scoring_share() -> None:
    fr, _ = connected_with_history(1)
    fr.server_fills.extend(fill_json(t) for t in (1, 2))
    drop_and_reconnect(fr)
    assert fr.rig.budget.scoring_used() == 0
    assert fr.rig.budget.used() > 0


def test_F3_AC4_the_gap_is_ledgered_as_data_gap_downtime() -> None:
    fr, t_last = connected_with_history(1, 2, 3)
    fr.server_fills.extend(fill_json(t) for t in (3, 4))
    reconnected_at = drop_and_reconnect(fr, down_s=40)
    (rec,) = fr.rig.ledger.of_kind("data_gap")
    assert rec.wallets == (WALLET_A,)
    assert _fill_time(3) <= rec.start_ms <= t_last  # from when the feed last heard from the exchange
    assert reconnected_at <= rec.end_ms <= fr.clock.now
    assert rec.end_ms - rec.start_ms >= 40 * SECOND


def test_F3_AC4_a_gap_with_no_missed_fills_is_still_ledgered_and_delivers_nothing_new() -> None:
    fr, _ = connected_with_history(1, 2)
    fr.server_fills.extend(fill_json(t) for t in (2,))
    drop_and_reconnect(fr)
    assert fr.sink.tids() == [1, 2]
    assert len(fr.rig.ledger.of_kind("data_gap")) == 1


def test_F3_AC4_a_stall_without_a_disconnect_is_resynced_too() -> None:
    fr, t_last = connected_with_history(1, 2)
    fr.server_fills.extend(fill_json(t) for t in (2, 3, 4))
    fr.run(35)  # silent for longer than feed.stale_after_s: marked stale, closed, reconnected
    fr.run(10)
    assert len(fr.connector.connections) >= 2
    assert fr.sink.tids() == [1, 2, 3, 4]
    assert len(fr.rig.ledger.of_kind("data_gap")) == 1


def test_F3_AC4_no_gap_and_no_resync_on_the_first_connection() -> None:
    fr, _ = connected_with_history(1, 2)
    assert [c for c in fr.rig.http.calls if c.body["type"] == "userFillsByTime"] == []
    assert fr.rig.ledger.records == []


# --- before any new decision ------------------------------------------------------------------------------------------

def test_F3_AC4_resync_fills_reach_the_consumer_before_any_fill_from_the_new_connection() -> None:
    fr, _ = connected_with_history(1, 2, 3)
    fr.server_fills.extend(fill_json(t) for t in (3, 4, 5, 6))

    def on_reconnect(conn: FakeConnection) -> None:
        conn.push(ws_fills(WALLET_A, [5, 6], snapshot=True))  # already in the REST result: duplicates
        conn.push(ws_fills(WALLET_A, [7]))  # genuinely new, live

    drop_and_reconnect(fr, on_reconnect=on_reconnect)
    assert fr.sink.tids() == [1, 2, 3, 4, 5, 6, 7]
    assert len(fr.sink.tids()) == len(set(fr.sink.tids()))


def test_F3_AC4_opens_stay_refused_and_nothing_new_is_delivered_until_the_resync_succeeded() -> None:
    fr, _ = connected_with_history(1, 2, 3, hl__retry_max=0)
    fr.server_fills.extend(fill_json(t) for t in (3, 4, 5))
    fr.rig.http.handler = raising(TimeoutError("rest down"))

    def on_reconnect(conn: FakeConnection) -> None:
        conn.push(ws_fills(WALLET_A, [6]))

    drop_and_reconnect(fr, on_reconnect=on_reconnect)
    fr.run(10)
    assert len(fr.connector.connections) >= 2
    assert fr.sink.tids() == [1, 2, 3]  # the live fill 6 is held back: the gap before it is unresolved
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) == "feed_stale"
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.CLOSE) is None
    fr.rig.http.handler = fr.rig.http.serve_fixtures  # REST recovers
    fr.run(90)
    assert fr.sink.tids() == [1, 2, 3, 4, 5, 6]
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) is None


def test_F3_AC4_every_affected_wallet_is_resynced_and_ledgered() -> None:
    fr, _ = connected_with_history(1, 2, wallets=(WALLET_A, WALLET_B))
    fr.connector.current.push(ws_fills(WALLET_B, [11, 12]))
    fr.run(1)
    fr.server_fills.extend(fill_json(t) for t in (2, 3, 12, 13))  # the fake server returns them for every wallet
    drop_and_reconnect(fr)
    assert fr.sink.tids(WALLET_A) == [1, 2, 3, 12, 13]
    assert fr.sink.tids(WALLET_B) == [11, 12, 13]
    resynced = sorted(c.body["user"] for c in fr.rig.http.calls if c.body["type"] == "userFillsByTime")
    assert resynced == sorted([WALLET_A, WALLET_B])
    assert {w for r in fr.rig.ledger.of_kind("data_gap") for w in r.wallets} == {WALLET_A, WALLET_B}


# --- de-duplication -----------------------------------------------------------------------------------------------------

def test_F3_AC4_a_snapshot_is_deduplicated_against_what_was_already_delivered() -> None:
    fr, _ = connected_with_history(1, 2, 3)
    fr.connector.current.push(ws_fills(WALLET_A, [2, 3, 4], snapshot=True))
    fr.run(1)
    assert fr.sink.tids() == [1, 2, 3, 4]


def test_F3_AC4_the_first_snapshot_delivers_every_fill_once() -> None:
    fr = make_feed(auto_pong=False)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    fr.connector.current.push(ws_fills(WALLET_A, [5, 6, 7], snapshot=True))
    fr.connector.current.push(ws_fills(WALLET_A, [5, 6, 7], snapshot=True))
    fr.run(1)
    assert fr.sink.tids() == [5, 6, 7]


def test_F3_AC4_a_repeated_live_message_and_overlapping_batches_deliver_each_tid_once() -> None:
    fr, _ = connected_with_history(1)
    for batch in ([2], [2], [2, 3], [3, 4]):
        fr.connector.current.push(ws_fills(WALLET_A, batch))
    fr.run(1)
    assert fr.sink.tids() == [1, 2, 3, 4]


def test_F3_AC4_an_out_of_order_fill_with_a_new_tid_is_still_delivered() -> None:
    fr, _ = connected_with_history()
    fr.connector.current.push(ws_fills(WALLET_A, [10]))
    fr.connector.current.push(ws_fills(WALLET_A, [9]))
    fr.run(1)
    assert sorted(fr.sink.tids()) == [9, 10] and len(fr.sink.tids()) == 2


def test_F3_AC4_a_wallet_is_deduplicated_independently_of_another() -> None:
    fr, _ = connected_with_history(wallets=(WALLET_A, WALLET_B))
    fr.connector.current.push(ws_fills(WALLET_A, [1]))
    fr.connector.current.push(ws_fills(WALLET_B, [1]))  # the same tid number under another wallet is another fill
    fr.run(1)
    assert fr.sink.tids(WALLET_A) == [1] and fr.sink.tids(WALLET_B) == [1]


# --- hostile input -------------------------------------------------------------------------------------------------------

def test_F3_AC4_a_message_with_a_bad_fill_is_rejected_whole_and_later_messages_still_flow() -> None:
    fr, _ = connected_with_history()
    bad = ws_fills(WALLET_A, [1, 2, 3])
    del bad["data"]["fills"][1]["tid"]
    fr.connector.current.push(bad)
    fr.connector.current.push(ws_fills(WALLET_A, [20]))
    fr.run(1)
    assert fr.sink.tids() == [20]  # nothing from the rejected message, not even its valid fills


def test_F3_AC4_three_bad_messages_raise_one_schema_alert() -> None:
    fr, _ = connected_with_history()
    for _ in range(3):
        bad = ws_fills(WALLET_A, [1])
        bad["data"]["fills"][0]["px"] = 1.5
        fr.connector.current.push(bad)
    fr.run(2)
    alerts = fr.rig.alerts.of_kind("schema_failure")
    assert len(alerts) == 1 and "ws:userFills" in alerts[0].message


@pytest.mark.parametrize("junk", ["not json at all", "", "null", "[]", '{"channel": 5}', '{"channel":"someNewChannel","data":1}'])
def test_F3_AC4_junk_and_unknown_messages_do_not_crash_the_tick(junk: str) -> None:
    fr, _ = connected_with_history()
    fr.connector.current.push(junk)
    fr.connector.current.push(ws_fills(WALLET_A, [30]))
    fr.run(1)
    assert fr.sink.tids() == [30]


def test_F3_AC4_fills_for_a_wallet_we_did_not_subscribe_to_are_ignored() -> None:
    fr, _ = connected_with_history()
    fr.connector.current.push(ws_fills(WALLET_B, [40]))
    fr.run(1)
    assert fr.sink.tids() == []


# --- property: no duplicates, nothing lost --------------------------------------------------------------------------------

@settings(max_examples=40)
@given(
    pre=st.lists(st.integers(1, 30), min_size=1, max_size=10, unique=True),
    missed=st.lists(st.integers(31, 60), max_size=10, unique=True),
    snap=st.lists(st.integers(1, 80), max_size=10, unique=True),
    post=st.lists(st.integers(1, 90), max_size=12),
)
def test_F3_AC4_property_across_a_gap_every_fill_is_delivered_exactly_once(
    pre: list[int], missed: list[int], snap: list[int], post: list[int]
) -> None:
    fr, _ = connected_with_history(*pre)
    fr.server_fills.extend(fill_json(t) for t in [max(pre), *missed])

    def on_reconnect(conn: FakeConnection) -> None:
        if snap:
            conn.push(ws_fills(WALLET_A, snap, snapshot=True))
        for t in post:
            conn.push(ws_fills(WALLET_A, [t]))

    drop_and_reconnect(fr, down_s=5, on_reconnect=on_reconnect)
    delivered = fr.sink.tids()
    assert len(delivered) == len(set(delivered))
    assert set(delivered) == set(pre) | set(missed) | set(snap) | set(post)
