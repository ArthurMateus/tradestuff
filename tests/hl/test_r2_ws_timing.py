"""F3.AC3 round 2: stale-timer boundary (BLOCKING 2) and advisory timing boundaries of the WebSocket feed.

Stale semantics (SPEC-SEMANTICS DECISION for the CTO to confirm): spec F3.AC3 says a connection with "no message or pong
for feed.stale_after_s" is stale. These tests read that as stale AT exactly N seconds of silence (>=). The current code
uses `>` (stale only after N s + 1 ms), so the two "exactly" stale tests FAIL on purpose until the developer changes
`tick` and `is_stale` in ws.py, or the CTO overrules the reading (then these two are re-pinned to `>`).
"""

from __future__ import annotations

import pytest

from tests.hl.support import SECOND, WALLET_A, FeedRig, make_feed

pytestmark = pytest.mark.integration


def _silent(**overrides: object) -> FeedRig:
    """Connected at T0 and subscribed; no pongs; reconnect attempts fail so nothing else happens."""
    fr = make_feed(auto_pong=False, **overrides)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    assert len(fr.connector.connections) == 1
    fr.connector.fail = True
    return fr


# --- stale boundary (1 ms before, exactly at, 1 ms after) ------------------------------------------------------------


@pytest.mark.parametrize("stale_after", [5, 30])
@pytest.mark.parametrize(("offset_ms", "stale"), [(-1, False), (0, True), (1, True)])
def test_F3_AC3_is_stale_boundary_one_ms_before_exactly_at_and_one_ms_after(
    stale_after: int, offset_ms: int, stale: bool
) -> None:
    fr = _silent(feed__stale_after_s=stale_after)
    fr.clock.advance(stale_after * SECOND + offset_ms)
    assert fr.feed.is_stale(WALLET_A) is stale


@pytest.mark.parametrize("stale_after", [5, 30])
@pytest.mark.parametrize(("offset_ms", "closed"), [(-1, False), (0, True), (1, True)])
def test_F3_AC3_tick_closes_a_silent_connection_one_ms_before_exactly_at_and_one_ms_after(
    stale_after: int, offset_ms: int, closed: bool
) -> None:
    fr = _silent(feed__stale_after_s=stale_after)
    fr.clock.advance(stale_after * SECOND + offset_ms)
    fr.feed.tick()
    assert fr.connector.connections[0].closed is closed


# --- ping trigger ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("offset_ms", "pings"), [(-1, 0), (0, 1), (1, 1)])
def test_F3_AC3_ping_goes_out_exactly_when_the_interval_has_elapsed(offset_ms: int, pings: int) -> None:
    fr = make_feed(auto_pong=False, hl__ws_ping_interval_s=20, feed__stale_after_s=60)  # 3/4 of 60 s is 45 s: no clamp
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    fr.clock.advance(20 * SECOND + offset_ms)
    fr.feed.tick()
    assert fr.connector.current.pings() == pings


@pytest.mark.parametrize(("offset_ms", "pings"), [(-1, 0), (0, 1), (1, 1)])
def test_F3_AC3_ping_interval_is_clamped_to_three_quarters_of_stale_after(offset_ms: int, pings: int) -> None:
    # ping interval 50 s is far above 3/4 of stale_after 10 s (7.5 s): the heartbeat must go at 7 500 ms
    fr = make_feed(auto_pong=False, hl__ws_ping_interval_s=50, feed__stale_after_s=10)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    fr.clock.advance(7_500 + offset_ms)
    fr.feed.tick()
    assert fr.connector.current.pings() == pings


def test_F3_AC3_a_healthy_idle_link_with_a_long_ping_interval_never_goes_stale_thanks_to_the_clamp() -> None:
    fr = make_feed(auto_pong=True, hl__ws_ping_interval_s=50, feed__stale_after_s=10)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()
    for _ in range(120):
        fr.run(1)
        assert not fr.feed.is_stale(WALLET_A)
    assert len(fr.connector.connections) == 1


# --- connect-attempt window ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("offset_ms", "attempts"), [(-1, 1), (0, 2), (1, 2)])
def test_F3_AC3_a_connect_attempt_leaves_the_per_minute_window_after_exactly_60_seconds(
    offset_ms: int, attempts: int
) -> None:
    fr = make_feed(auto_pong=False, hl__ws_max_new_conns_per_min=1)
    fr.feed.subscribe_user(WALLET_A)
    fr.feed.tick()  # attempt 1 at T0
    first = fr.connector.current
    first.dead = True
    fr.clock.advance(SECOND)
    fr.feed.tick()  # the loss is noticed; the reconnect backoff (1-2 s) is long over by T0 + 59.999 s
    assert len(fr.connector.attempt_times) == 1
    fr.clock.advance(59 * SECOND + offset_ms)  # now at T0 + 60 000 + offset_ms
    fr.feed.tick()
    assert len(fr.connector.attempt_times) == attempts
