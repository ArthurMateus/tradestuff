"""R1.AC5 [integration]: realistic ``userFillsByTime`` payloads (SYNTHETIC-PENDING-RECORDING, tests/fixtures/hl/).

The real field set (coin, px, sz, side, time, startPosition, dir, closedPnl, hash, oid, crossed, fee, tid, feeToken and
the optional twapId, cloid, liquidation object, builderFee, plus unknown extra keys) must parse, and a missing, null or
odd OPTIONAL field must never fail a wallet. Most of these are regression pins and pass today; the liquidation-object
test is a data-fidelity pin and fails today (``hl.Fill`` drops the object, and ``dir`` alone decides the flag).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import pytest

from copytrade.hl.budget import Priority
from tests.hl.support import T0
from tests.selection.helpers import w
from tests.selection.r1_logs import BACKFILL_LOGGER, events
from tests.selection.r1_world import make_world, r1_fixture, synth_fills

WALLET = w(1)
OPTIONAL = ["feeToken", "twapId", "cloid", "liquidation", "builderFee"]


def fetch(rows: list[dict[str, Any]], caplog: pytest.LogCaptureFixture | None = None):  # type: ignore[no-untyped-def]
    world = make_world()
    world.hl.set_fills(WALLET, rows)
    world.backfiller.set_candidates([WALLET])
    if caplog is not None:
        with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
            world.backfiller.step()
    else:
        world.backfiller.step()
    return world


def test_R1_AC5_the_rest_client_parses_the_full_real_field_set_with_extras() -> None:
    world = make_world()
    world.hl.set_fills(WALLET, r1_fixture())
    got = world.client.user_fills_by_time(WALLET, T0 - 30 * 86_400_000, None, priority=Priority.SCORING)
    assert len(got) == len(r1_fixture()) == 9
    assert got[0].px == Decimal("67000.5") and got[0].fee == Decimal("0.0123") and got[0].dir == "Open Long"
    assert got[5].fee == Decimal("-0.0042")  # a maker rebate is a negative fee


def test_R1_AC5_a_wallet_with_the_full_real_field_set_completes(caplog: pytest.LogCaptureFixture) -> None:
    world = fetch(r1_fixture(), caplog)
    got = world.backfiller.inputs(WALLET, T0)
    assert got is not None and len(got.fills) == 9 and got.fills_fetched_ms is not None
    assert world.backfiller.complete is True
    assert events(caplog, "backfill_failed") == [] and events(caplog, "backfill_incomplete") == []


@pytest.mark.parametrize("field", OPTIONAL)
def test_R1_AC5_a_missing_optional_field_does_not_fail_the_wallet(field: str, caplog: pytest.LogCaptureFixture) -> None:
    rows = synth_fills(4)
    for row in rows:
        row.pop(field, None)
    got = fetch(rows, caplog).backfiller.inputs(WALLET, T0)
    assert got is not None and len(got.fills) == 4
    assert events(caplog, "backfill_failed") == []


@pytest.mark.parametrize("field", ["twapId", "cloid", "liquidation", "builderFee"])
def test_R1_AC5_a_null_optional_field_does_not_fail_the_wallet(field: str, caplog: pytest.LogCaptureFixture) -> None:
    rows = synth_fills(4)
    for row in rows:
        row[field] = None
    got = fetch(rows, caplog).backfiller.inputs(WALLET, T0)
    assert got is not None and len(got.fills) == 4
    assert events(caplog, "backfill_failed") == []


@pytest.mark.parametrize(
    "odd",
    [
        {"twapId": 10**15},
        {"cloid": "0x" + "0" * 32},
        {"builderFee": "0.0"},
        {"feeToken": "HYPE"},
        {"fee": "-0.0001"},
        {"closedPnl": "-0.0"},
        {"startPosition": "-12.5"},
        {"dir": "Auto-Deleveraging"},
        {"dir": "Spot Dust Conversion"},
        {"liquidation": {"liquidatedUser": "0x" + "3" * 40, "markPx": "1.0"}},
        {"liquidation": {}},
        {"aNewFieldFromTheExchange": [1, {"x": None}], "anotherOne": "text"},
    ],
    ids=lambda d: next(iter(d)) + "=" + str(next(iter(d.values())))[:20],
)
def test_R1_AC5_an_odd_optional_value_or_unknown_extra_key_does_not_fail_the_wallet(
    odd: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    rows = synth_fills(4)
    rows[2].update(odd)
    got = fetch(rows, caplog).backfiller.inputs(WALLET, T0)
    assert got is not None and len(got.fills) == 4
    assert events(caplog, "backfill_failed") == []


def test_R1_AC5_a_liquidation_by_dir_text_is_flagged() -> None:
    got = fetch(r1_fixture()).backfiller.inputs(WALLET, T0)
    assert got is not None
    by_tid = {f.tid: f for f in got.fills}
    assert by_tid[900000000000005].liquidation is True  # "Liquidated Cross Long"
    assert by_tid[900000000000001].liquidation is False


def test_R1_AC5_a_fill_carrying_a_liquidation_object_is_flagged_whatever_its_dir_says() -> None:
    """Fail closed for the any_liquidation blow-up gate: fill 9 is a plain "Close Long" with a ``liquidation`` object."""
    got = fetch(r1_fixture()).backfiller.inputs(WALLET, T0)
    assert got is not None
    by_tid = {f.tid: f for f in got.fills}
    assert by_tid[900000000000009].liquidation is True
    assert by_tid[900000000000004].liquidation is False  # ``"liquidation": null`` is not a liquidation
    assert by_tid[900000000000002].liquidation is False


def test_R1_AC5_a_required_field_missing_fails_that_wallet_only_and_others_proceed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make_world()
    broken = synth_fills(3)
    del broken[0]["dir"]
    world.hl.set_fills(WALLET, broken)
    world.hl.set_fills(w(2), synth_fills(3, tid0=900))
    world.backfiller.set_candidates([WALLET, w(2)])
    with caplog.at_level(logging.WARNING, logger=BACKFILL_LOGGER):
        world.backfiller.step()
        world.backfiller.step()
    assert world.backfiller.inputs(w(2), T0) is not None
    assert world.backfiller.inputs(WALLET, T0) is None
    assert len(events(caplog, "backfill_failed")) == 1
