# mypy: disable-error-code="union-attr"
"""F11 round 2, Amendment 8 (RISK-5) and the funding mutation holes.

Each funding hour settles on its own: a missing hour never blocks later hours, and is alerted once per stretch
(``funding_missing``), re-armed once the rate arrives. A snapshot for the wrong hour or coin, a non-finite rate or a
zero oracle price is not a rate.
"""

from __future__ import annotations

from decimal import Decimal as D
from typing import Any

import pytest
from tests.paper.helpers import BASE, D0, HOUR_MS, Env, NewEnv
from tests.paper.r2_helpers import FlakyFunding, custom_env

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.paper.types import FundingSnapshot

B1 = BASE + HOUR_MS
B2 = BASE + 2 * HOUR_MS
B3 = BASE + 3 * HOUR_MS
B4 = BASE + 4 * HOUR_MS


def _hours(e: Env) -> list[Any]:
    return [(r.payload["coin"], r.payload["share_id"], r.payload["hour_ms"]) for r in e.records("paper_funding")]


def _missing_alert_records(e: Env) -> list[Any]:
    return [r for r in e.records("paper_alert") if r.payload["kind"] == "funding_missing"]


# ------------------------------------------------------------------------------------------------- RISK-5


@pytest.mark.unit
def test_R2_RISK5_a_missing_first_hour_does_not_block_the_known_second_and_third_hours(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")  # 300 - 0.09 = 299.91
    e.funding.set("SOL", B2, "0.0001", "100")
    e.funding.set("SOL", B3, "0.0002", "110")
    e.advance(B3 + 1000)
    assert _hours(e) == [("SOL", "S1", B2), ("SOL", "S1", B3)]
    amounts = [r.payload["amount"] for r in e.records("paper_funding")]
    assert amounts == [D("-0.02"), D("-0.044")]  # 2 x 100 x 0.0001 and 2 x 110 x 0.0002, paid by the long
    assert e.broker.cash_usd() == D("299.846")


@pytest.mark.unit
def test_R2_RISK5_the_missing_hour_is_alerted_once_and_settles_late_when_its_rate_arrives(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B2, "0.0001", "100")
    e.funding.set("SOL", B3, "0.0001", "100")
    e.advance(B3 + 1000)
    e.advance(B3 + 2000)
    e.advance(B3 + 3000)
    assert sorted(h for _, _, h in _hours(e)) == [B2, B3]  # they settled without waiting for B1
    assert e.broker.cash_usd() == D("299.87")
    assert e.alerts.kinds().count("funding_missing") == 1
    assert [r.payload["hour_ms"] for r in _missing_alert_records(e)] == [B1]
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B3 + 4000)
    assert sorted(h for _, _, h in _hours(e)) == [B1, B2, B3]
    assert e.broker.cash_usd() == D("299.85")  # 299.91 less three hours of 0.02
    e.advance(B3 + 5000)
    assert len(_hours(e)) == 3  # nothing is charged twice


@pytest.mark.unit
def test_R2_RISK5_the_alert_is_re_armed_after_a_rate_arrives(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B2, "0.0001", "100")
    e.advance(B2 + 1000)  # B1 missing (B2 known and settled): one alert
    e.advance(B2 + 2000)
    assert e.alerts.kinds().count("funding_missing") == 1 and [h for _, _, h in _hours(e)] == [B2]
    e.funding.set("SOL", B1, "0.0001", "100")
    e.advance(B2 + 3000)
    assert e.alerts.kinds().count("funding_missing") == 1 and len(_hours(e)) == 2
    e.advance(B4 + 1000)  # B3 and B4 are missing now: a new stretch, alerted again (once)
    e.advance(B4 + 2000)
    assert e.alerts.kinds().count("funding_missing") == 2
    assert len(_missing_alert_records(e)) == 2


@pytest.mark.unit
def test_R2_RISK5_a_missing_hour_of_one_coin_does_not_block_another_coin(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.open_position("buy", "0.1", px="1000", coin="BTC", coid="o2", share="S2", trade="T2", decided=D0 + 10_000)
    e.funding.set("BTC", B1, "0.0001", "1000")
    e.advance(B1 + 1000)
    assert _hours(e) == [("BTC", "S2", B1)]
    assert e.alerts.kinds().count("funding_missing") == 1


# ------------------------------------------------------------------------------ what counts as a rate (d)


def _wrong_snapshots() -> list[tuple[str, FundingSnapshot]]:
    return [
        ("wrong_hour", FundingSnapshot("SOL", B2, D("0.0001"), Price("100"))),
        ("wrong_coin", FundingSnapshot("BTC", B1, D("0.0001"), Price("100"))),
        ("zero_oracle_px", FundingSnapshot("SOL", B1, D("0.0001"), Price("0"))),
        ("nan_rate", FundingSnapshot("SOL", B1, D("NaN"), Price("100"))),
        ("infinite_rate", FundingSnapshot("SOL", B1, D("Infinity"), Price("100"))),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(("name", "snapshot"), _wrong_snapshots(), ids=[n for n, _ in _wrong_snapshots()])
def test_R2_AC3_a_snapshot_that_is_not_the_hour_the_coin_and_a_usable_rate_is_not_accepted(
    name: str, snapshot: FundingSnapshot
) -> None:
    funding = FlakyFunding()
    with custom_env(funding=funding) as e:
        e.open_position("buy", "2.0", px="100")
        funding.override = snapshot
        e.advance(B1 + 1000)
        assert e.records("paper_funding") == []
        assert e.broker.cash_usd() == D("299.91")
        assert e.alerts.kinds().count("funding_missing") == 1
        funding.override = None
        funding.set("SOL", B1, "0.0001", "100")  # the real snapshot arrives and is then accepted
        e.advance(B1 + 2000)
        assert _hours(e) == [("SOL", "S1", B1)] and e.broker.cash_usd() == D("299.89")


@pytest.mark.unit
def test_R2_AC3_a_negative_oracle_price_is_not_a_rate_either() -> None:
    funding = FlakyFunding()
    with custom_env(funding=funding) as e:
        e.open_position("buy", "2.0", px="100")
        funding.override = FundingSnapshot("SOL", B1, D("0.0001"), D("-100"))  # type: ignore[arg-type]
        e.advance(B1 + 1000)
        assert e.records("paper_funding") == [] and e.broker.cash_usd() == D("299.91")


# ------------------------------------ a fill at exactly the boundary while ANOTHER coin is held (mutation holes)


def _two_coin_env(e: Env) -> None:
    e.open_position("buy", "2.0", px="100")  # SOL S1 long, opened at D0 + 1000
    e.open_position("buy", "0.1", px="1000", coin="BTC", coid="o2", share="S2", trade="T2", decided=D0 + 1000)
    for hour in (B1, B2):
        e.funding.set("SOL", hour, "0.0001", "100")
        e.funding.set("BTC", hour, "0.0001", "1000")


@pytest.mark.unit
def test_R2_AC3_an_entry_filling_exactly_at_the_boundary_pays_nothing_for_it_while_another_coin_is_held(
    new_env: NewEnv,
) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B1, "0.0001", "100")
    e.funding.set("SOL", B2, "0.0001", "100")
    e.funding.set("BTC", B1, "0.0001", "1000")
    e.funding.set("BTC", B2, "0.0001", "1000")
    e.flat_book("BTC", B1, "1000")
    e.advance(B1 - 1000)  # Amendment 11: broker time only moves through advance_to (RISK-23: entry not far ahead)
    assert e.submit(
        e.order("buy", "0.1", coid="b1", coin="BTC", decided=B1 - 1000, px="1000", share="S2", trade="T2")
    ).accepted
    events = e.advance(B1)
    assert [(ev.kind, ev.coin, ev.fill.time.ms) for ev in events if ev.fill] == [("fill", "BTC", B1)]
    e.advance(B1 + 1000)
    assert _hours(e) == [("SOL", "S1", B1)]  # the BTC share was not held over B1
    e.advance(B2 + 1000)
    assert sorted(_hours(e)) == [("BTC", "S2", B2), ("SOL", "S1", B1), ("SOL", "S1", B2)]


@pytest.mark.unit
def test_R2_AC3_an_exit_filling_exactly_at_the_boundary_pays_nothing_for_it_while_another_coin_is_held(
    new_env: NewEnv,
) -> None:
    e = new_env()
    _two_coin_env(e)
    e.flat_book("BTC", B1, "1000")
    assert e.submit(
        e.order(
            "sell",
            "0.1",
            coid="x1",
            coin="BTC",
            action=ActionKind.CLOSE,
            decided=B1 - 1000,
            px="1000",
            share="S2",
            trade="T2",
        )
    ).accepted
    events = e.advance(B1)
    assert [(ev.kind, ev.coin) for ev in events if ev.fill] == [("fill", "BTC")]
    assert events[-1].trade.pnl_usd == D("-0.09")  # 0.045 entry fee + 0.045 exit fee, and no funding at all
    e.advance(B1 + 1000)
    assert _hours(e) == [("SOL", "S1", B1)]
    assert e.broker.position("BTC") is None and e.broker.position("SOL") is not None
    e.advance(B2 + 1000)
    assert _hours(e) == [("SOL", "S1", B1), ("SOL", "S1", B2)]  # the next hour is still tracked for SOL


@pytest.mark.unit
def test_R2_AC3_an_exit_one_ms_after_the_boundary_pays_the_hour_while_another_coin_is_held(new_env: NewEnv) -> None:
    e = new_env()
    _two_coin_env(e)
    e.flat_book("BTC", B1 + 1, "1000")
    assert e.submit(
        e.order(
            "sell",
            "0.1",
            coid="x1",
            coin="BTC",
            action=ActionKind.CLOSE,
            decided=B1 - 999,
            px="1000",
            share="S2",
            trade="T2",
        )
    ).accepted
    e.advance(B1 + 1)
    assert sorted(_hours(e)) == [("BTC", "S2", B1), ("SOL", "S1", B1)]
