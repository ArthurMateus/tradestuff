"""R5.AC3 support: ``HlRestClient.transport_ms`` is the REST time of the transport (what a backfill step budgets on):
answers and timeouts count, retry and rate budget waits do not."""

from __future__ import annotations

import pytest

from copytrade.hl.budget import Priority
from copytrade.hl.errors import HlBudgetError
from tests.selection.helpers import w
from tests.selection.r5_world import make_r5


def test_R5_AC3_transport_ms_counts_the_time_of_every_answer() -> None:
    r = make_r5(latency=0.5)
    r.limit.new_iteration()
    client = r.world.client
    assert client.transport_ms == 0
    client.portfolio(w(1), priority=Priority.SCORING)
    client.user_role(w(1), priority=Priority.SCORING)
    assert client.transport_ms == 1_000


def test_R5_AC3_transport_ms_counts_a_timeout_for_the_time_it_waited_not_the_backoff() -> None:
    r = make_r5(latency=3.0)
    r.limit.new_iteration()
    client = r.world.client
    with pytest.raises(HlBudgetError):  # the fail-fast client refuses the retry back-off after the 2 s timeout
        client.portfolio(w(1), priority=Priority.SCORING)
    assert client.transport_ms == 2_000
