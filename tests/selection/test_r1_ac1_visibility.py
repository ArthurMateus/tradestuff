"""R1.AC1 [integration]: a failed backfill step is visible.

The PO's console said only "backfill of a candidate failed, it will be retried" (error TYPE only). Pinned: the warning
record (event ``backfill_failed``) carries ``wallet``, ``status`` (the HTTP status when there is one, else absent/None),
``error`` (the error message: no secrets, no URL) and keeps ``error_type``; the incomplete record (event
``backfill_incomplete``) carries ``wallet``, ``pages`` and ``fills``. Countable: exactly one ``backfill_failed`` record
per failed attempt (the stable ``event`` key is the count; the code has no alert or ledger path for backfill, see the
test plan: none is invented here).
"""

from __future__ import annotations

import json
import logging

import pytest

from copytrade.hl.budget import Priority
from tests.hl.support import T0, status
from tests.selection.helpers import w
from tests.selection.r1_logs import BACKFILL_LOGGER, attr, events
from tests.selection.r1_world import World, make_world, stuck_fills, synth_fills

BAD = w(1)


def step_once(world: World, caplog: pytest.LogCaptureFixture) -> None:
    world.backfiller.set_candidates([BAD])
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        world.backfiller.step()


@pytest.mark.parametrize("code", [403, 451, 500, 502])
def test_R1_AC1_an_http_error_on_fills_logs_the_status_and_the_message(
    code: int, caplog: pytest.LogCaptureFixture
) -> None:
    world = make_world()
    world.hl.rules[(BAD, "userFillsByTime")] = lambda call: status(code)
    step_once(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert attr(rec, "wallet") == BAD
    assert attr(rec, "status") == code
    assert str(code) in str(attr(rec, "error"))
    assert "://" not in str(attr(rec, "error"))  # a message, never a URL
    assert attr(rec, "error_type") == "HlHttpError"


def test_R1_AC1_an_http_error_on_a_later_request_of_the_same_wallet_is_visible_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make_world()
    world.hl.set_fills(BAD, synth_fills(1))  # R3: a wallet without a fill is dropped after one request
    world.hl.rules[(BAD, "portfolio")] = lambda call: status(503)
    step_once(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert attr(rec, "status") == 503 and "portfolio" in str(attr(rec, "error"))


def test_R1_AC1_a_persistent_429_logs_status_429(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.rules[(BAD, "userFillsByTime")] = lambda call: status(429)
    step_once(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert attr(rec, "status") == 429
    assert "429" in str(attr(rec, "error"))
    assert attr(rec, "error_type") == "HlRateLimitedError"


def test_R1_AC1_a_timeout_logs_the_message_and_no_status(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()

    def timeout(call: object) -> None:
        raise TimeoutError("slow")

    world.hl.rules[(BAD, "userFillsByTime")] = timeout  # type: ignore[assignment]
    step_once(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert attr(rec, "status") is None
    assert "userFillsByTime" in str(attr(rec, "error"))
    assert attr(rec, "error_type") == "HlTimeoutError"


def test_R1_AC1_a_schema_failure_names_the_offending_field(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    broken = synth_fills(3)
    del broken[1]["tid"]
    world.hl.set_fills(BAD, broken)
    step_once(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert attr(rec, "status") is None
    assert "tid" in str(attr(rec, "error"))
    assert attr(rec, "error_type") == "HlSchemaError"


def test_R1_AC1_an_os_error_from_the_candle_source_logs_its_message(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.set_fills(BAD, synth_fills(3))
    world.candles.error = OSError("candle store unreadable")
    step_once(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert attr(rec, "status") is None
    assert "candle store unreadable" in str(attr(rec, "error"))
    assert attr(rec, "error_type") == "OSError"


def test_R1_AC1_a_budget_refusal_is_visible_with_its_message(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world(fail_fast=True)
    world.hl.set_fills(BAD, synth_fills(1))  # R3: a wallet without a fill is dropped after one request
    for _ in range(6):  # exhaust the scoring share so the next request does not fit
        world.client.user_role(BAD, priority=Priority.SCORING)
    step_once(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert attr(rec, "status") is None
    assert "rate budget" in str(attr(rec, "error"))


def test_R1_AC1_no_secret_or_url_in_any_record(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.rules[(BAD, "userFillsByTime")] = lambda call: status(403, json.dumps({"detail": "token=SECRET123"}))
    step_once(world, caplog)
    for rec in caplog.records:
        text = rec.getMessage() + json.dumps({k: str(v) for k, v in rec.__dict__.items()})
        assert "SECRET123" not in text  # the response body is never copied into the log


def test_R1_AC1_the_incomplete_case_logs_pages_and_fills_fetched(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    stuck = stuck_fills()  # 2 500 fills in ONE millisecond (after one older fill): the cursor cannot move
    world.hl.set_fills(BAD, stuck)
    step_once(world, caplog)
    (rec,) = events(caplog, "backfill_incomplete")
    assert attr(rec, "wallet") == BAD
    assert attr(rec, "pages") == 2  # one full page, then a page with no progress
    assert attr(rec, "fills") == 2_001  # the distinct fills got (the old fill + the same 2 000 of the pile twice)


def test_R1_AC1_every_failed_attempt_is_exactly_one_countable_record(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.rules[(BAD, "userFillsByTime")] = lambda call: status(500)
    world.backfiller.set_candidates([BAD])
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        for _ in range(4):
            world.backfiller.step()
            world.tick(3_600)  # far past any cooldown: every step really attempts
    assert len(events(caplog, "backfill_failed")) == 4
    assert all(attr(r, "wallet") == BAD for r in events(caplog, "backfill_failed"))


def test_R1_AC1_a_wallet_that_succeeds_logs_no_failure(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.set_fills(BAD, synth_fills(5))
    step_once(world, caplog)
    assert events(caplog, "backfill_failed") == [] and events(caplog, "backfill_incomplete") == []
    assert world.backfiller.inputs(BAD, T0) is not None
