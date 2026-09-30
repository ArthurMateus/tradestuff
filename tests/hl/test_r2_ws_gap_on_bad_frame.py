"""F3.AC4 round 2 (senior-dev BLOCKING 1). A malformed or unreadable userFills frame means fills may have been lost, so
it must open a data gap and trigger a userFillsByTime resync: for the identified wallet, or for every wallet on the
connection when the wallet cannot be identified. Opens are refused until the resync completed, exits never, and every
fill is delivered exactly once.

THESE TESTS FAIL ON PURPOSE against the implementation as of 006ba87 (ws.py `_handle_message` only calls
`record_failure` and returns). The developer must make them pass.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from tests.hl.support import WALLET_A, WALLET_B, FeedRig, fill_json, make_feed, raising, ws_fills

pytestmark = pytest.mark.integration


def _rest_calls(fr: FeedRig) -> list[str]:
    return sorted(c.body["user"] for c in fr.rig.http.calls if c.body["type"] == "userFillsByTime")


def _connected() -> FeedRig:
    """Two wallets, live and healthy (pongs answered), A has delivered fills 1..3 and B fill 11. The fake REST server
    holds fills 3, 4, 5 (A's missed ones) and REST is DOWN, so an opened gap stays observable."""
    fr = make_feed(auto_pong=True, hl__retry_max=0)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.subscribe_user(WALLET_B)
    fr.feed.tick()
    fr.run(2)
    fr.connector.current.push(ws_fills(WALLET_A, [1, 2, 3]))
    fr.connector.current.push(ws_fills(WALLET_B, [11]))
    fr.run(1)
    assert fr.sink.tids(WALLET_A) == [1, 2, 3]
    fr.server_fills.extend(fill_json(t) for t in (3, 4, 5))
    fr.rig.http.handler = raising(TimeoutError("rest down"))
    return fr


def _bad_fill_frame() -> dict[str, Any]:
    frame = ws_fills(WALLET_A, [4, 5])
    frame["data"]["fills"][1]["px"] = 1.5  # a JSON float price: the whole message is rejected
    return frame


def _no_user_frame() -> dict[str, Any]:
    frame = ws_fills(WALLET_A, [4])
    del frame["data"]["user"]
    return frame


UNIDENTIFIABLE = {
    "not_json": "not json at all",
    "empty_string": "",
    "json_null": "null",
    "json_list": "[]",
    "channel_not_a_string": '{"channel": 5}',
    "no_channel": '{"data": {"user": "x"}}',
    "userfills_without_data": '{"channel":"userFills"}',
    "userfills_data_not_an_object": '{"channel":"userFills","data":[1,2]}',
    "userfills_without_user": json.dumps(_no_user_frame()),
    "userfills_user_not_a_string": '{"channel":"userFills","data":{"user":123,"fills":[]}}',
}


def test_F3_AC4_a_malformed_fill_message_for_a_known_wallet_opens_a_gap_and_resyncs_only_that_wallet() -> None:
    fr = _connected()
    fr.connector.current.push(_bad_fill_frame())
    fr.run(1)
    assert _rest_calls(fr) == [WALLET_A]  # the resync was attempted, for A only
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) == "feed_stale"
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.ADD) == "feed_stale"
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.CLOSE) is None  # exits are never refused
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.REDUCE) is None
    assert fr.feed.refusal_reason(WALLET_B, ActionKind.OPEN) is None  # B's stream was fine
    assert fr.sink.tids(WALLET_A) == [1, 2, 3]  # nothing from the rejected message


def test_F3_AC4_after_a_malformed_message_the_resync_delivers_each_fill_exactly_once_and_ledgers_the_gap() -> None:
    fr = _connected()
    fr.connector.current.push(_bad_fill_frame())
    fr.connector.current.push(ws_fills(WALLET_A, [6]))  # a good live fill during the gap: held back, not lost
    fr.run(1)
    assert fr.sink.tids(WALLET_A) == [1, 2, 3]  # held until the gap is closed
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) == "feed_stale"
    fr.rig.http.handler = fr.rig.http.serve_fixtures  # REST recovers
    fr.run(90)
    assert fr.sink.tids(WALLET_A) == [1, 2, 3, 4, 5, 6]  # exactly once, resync fills before the held one
    assert fr.sink.tids(WALLET_B) == [11]
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) is None
    (gap,) = fr.rig.ledger.of_kind("data_gap")
    assert gap.wallets == (WALLET_A,)
    assert gap.end_ms > gap.start_ms


def test_F3_AC4_a_malformed_message_with_a_healthy_rest_resyncs_at_once() -> None:
    fr = _connected()
    fr.rig.http.handler = fr.rig.http.serve_fixtures
    fr.connector.current.push(_bad_fill_frame())
    fr.run(2)
    assert _rest_calls(fr) == [WALLET_A]
    assert fr.sink.tids(WALLET_A) == [1, 2, 3, 4, 5]
    assert len(fr.rig.ledger.of_kind("data_gap")) == 1
    assert fr.feed.refusal_reason(WALLET_A, ActionKind.OPEN) is None


@pytest.mark.parametrize("frame", list(UNIDENTIFIABLE.values()), ids=list(UNIDENTIFIABLE))
def test_F3_AC4_an_unreadable_frame_opens_a_gap_for_every_wallet_on_the_connection(frame: str) -> None:
    fr = _connected()
    fr.connector.current.push(frame)
    fr.run(1)
    assert _rest_calls(fr) == [WALLET_A, WALLET_B]  # both resynced: the wallet cannot be identified
    for wallet in (WALLET_A, WALLET_B):
        assert fr.feed.refusal_reason(wallet, ActionKind.OPEN) == "feed_stale"
        assert fr.feed.refusal_reason(wallet, ActionKind.CLOSE) is None
    fr.rig.http.handler = fr.rig.http.serve_fixtures
    fr.run(90)
    assert fr.sink.tids(WALLET_A) == [1, 2, 3, 4, 5]  # 4 and 5 recovered once, 3 not repeated
    assert fr.sink.tids(WALLET_B) == [11]
    assert {w for r in fr.rig.ledger.of_kind("data_gap") for w in r.wallets} == {WALLET_A, WALLET_B}
    assert len(fr.rig.ledger.of_kind("data_gap")) == 2
    for wallet in (WALLET_A, WALLET_B):
        assert fr.feed.refusal_reason(wallet, ActionKind.OPEN) is None
