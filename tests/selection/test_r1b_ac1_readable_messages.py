"""R1b.AC1 [integration]: the FORMATTED text (record.getMessage()) of the backfill records carries the facts.

The PO's console showed only the bare message because the facts were logging ``extra`` fields. Pinned on the message
itself: backfill_failed (wallet, status, error text, error type), backfill_incomplete (wallet, pages, fills),
backfill_too_active (wallet, reason), backfill_refresh_skipped (wallet, reason, until). No URL, no response body.
"""

from __future__ import annotations

import logging

import pytest

from tests.hl.support import T0, status
from tests.selection.helpers import w
from tests.selection.r1_logs import BACKFILL_LOGGER, events
from tests.selection.r1_world import HL_FILLS_LIMIT, make_world, synth_fills

BAD = w(1)


def _step(world, caplog: pytest.LogCaptureFixture, *, n: int = 1) -> None:
    world.backfiller.set_candidates([BAD])
    with caplog.at_level(logging.INFO, logger=BACKFILL_LOGGER):
        for _ in range(n):
            world.backfiller.step()


def _has_wallet(message: str, wallet: str) -> bool:
    return wallet in message or (wallet[:6] in message and wallet[-4:] in message)


@pytest.mark.parametrize("code", [403, 500])
def test_R1b_AC1_backfill_failed_message_names_wallet_status_error_and_type(
    code: int, caplog: pytest.LogCaptureFixture
) -> None:
    world = make_world()
    world.hl.rules[(BAD, "userFillsByTime")] = lambda call: status(code)
    _step(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    message = rec.getMessage()
    assert _has_wallet(message, BAD)
    assert str(code) in message
    assert "HlHttpError" in message
    assert "userFillsByTime" in message  # the request type from the error text
    assert "://" not in message  # never a URL


def test_R1b_AC1_backfill_failed_message_is_not_the_bare_legacy_text(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.rules[(BAD, "portfolio")] = lambda call: status(503)
    _step(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert rec.getMessage() != "backfill of a candidate failed, it will be retried"
    assert "503" in rec.getMessage() and "portfolio" in rec.getMessage()


def test_R1b_AC1_a_rate_limited_failure_message_carries_status_429(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.rules[(BAD, "userFillsByTime")] = lambda call: status(429)
    _step(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert "429" in rec.getMessage() and _has_wallet(rec.getMessage(), BAD)


def test_R1b_AC1_backfill_refresh_skipped_message_names_wallet_reason_and_until(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make_world()
    world.hl.rules[(BAD, "userFillsByTime")] = lambda call: status(500)
    _step(world, caplog, n=2)
    (rec,) = events(caplog, "backfill_refresh_skipped")
    message = rec.getMessage()
    assert _has_wallet(message, BAD)
    assert str(getattr(rec, "reason")) in message
    assert str(getattr(rec, "until_ms")) in message


def test_R1b_AC1_backfill_too_active_message_names_wallet_and_reason(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world(fills_limit=HL_FILLS_LIMIT)
    world.hl.set_fills(BAD, synth_fills(20_000))
    world.backfiller.set_candidates([BAD])
    with caplog.at_level(logging.INFO, logger=BACKFILL_LOGGER):
        for _ in range(30):
            if world.backfiller.complete:
                break
            world.backfiller.step()
    (rec,) = events(caplog, "backfill_too_active")
    message = rec.getMessage()
    assert _has_wallet(message, BAD)
    assert str(getattr(rec, "reason")) in message


def test_R1b_AC1_backfill_incomplete_message_names_wallet_pages_and_fills(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world()
    world.hl.set_fills(BAD, synth_fills(2_500, start_ms=T0 - 3_600_000, step_ms=0))
    _step(world, caplog)
    (rec,) = events(caplog, "backfill_incomplete")
    message = rec.getMessage()
    assert _has_wallet(message, BAD)
    assert "2000" in message.replace(",", "").replace("_", "")  # fills fetched
    assert any(tok in ("2", "2,") for tok in message.replace("=", " ").replace(":", " ").split())  # pages


def test_R1b_AC1_the_message_never_carries_the_response_body(caplog: pytest.LogCaptureFixture) -> None:
    import json

    world = make_world()
    world.hl.rules[(BAD, "userFillsByTime")] = lambda call: status(403, json.dumps({"detail": "token=SECRET123"}))
    _step(world, caplog)
    (rec,) = events(caplog, "backfill_failed")
    assert "SECRET123" not in rec.getMessage()
    assert "403" in rec.getMessage()  # and it is not empty of facts
