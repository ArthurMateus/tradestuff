# mypy: disable-error-code="union-attr"
"""F11.AC6: an open share on a delisted coin closes at the exchange settlement price, flagged
``delisted_force_settle``, and it counts in every statistic (F2.AC5, D2). Pinned: the settlement is a fill and pays
the taker fee (the conservative reading of F11.AC2 "every fill")."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from tests.paper.helpers import NewEnv

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.ledger.export import aggregate_trades
from tests.paper.helpers import D0


@pytest.mark.unit
def test_F11_AC6_long_share_is_force_settled_at_the_settlement_price(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(D0 + 30_000)
    (ev,) = e.broker.on_delist("SOL", Price("95"), D0 + 30_000)
    assert ev.kind == "delisted_force_settle"
    fill = ev.fill
    assert fill.price == Price("95") and fill.side == "sell" and fill.exit_reason == "delisted_force_settle"
    assert fill.fee == D("0.04275")  # 95 x 4.5 bps
    assert fill.time == Timestamp(D0 + 30_000, TimeSource.EXCHANGE)
    assert ev.trade.pnl_usd == D("-5.08775")  # -5 - 0.045 - 0.04275
    assert ev.trade.flags == frozenset({"delisted_force_settle"})
    assert e.broker.position("SOL") is None
    assert e.broker.cash_usd() == D("294.91225")
    assert e.alerts.kinds().count("delisted_force_settle") == 1


@pytest.mark.unit
def test_F11_AC6_short_share_is_settled_by_buying_back(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("sell", "1.0", px="100")
    e.advance(D0 + 30_000)
    (ev,) = e.broker.on_delist("SOL", Price("90"), D0 + 30_000)
    assert ev.fill.side == "buy"
    assert ev.trade.pnl_usd == D("9.9145")  # +10 - 0.045 - 90 x 0.00045


@pytest.mark.unit
def test_F11_AC6_the_forced_settlement_counts_in_every_statistic(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(D0 + 30_000)
    e.broker.on_delist("SOL", Price("95"), D0 + 30_000)
    agg = aggregate_trades(e.ledger_dir)
    assert agg.trade_count == 1 and agg.total_pnl_usd == D("-5.08775")
    assert len(e.fills()) == 2


@pytest.mark.unit
def test_F11_AC6_every_share_on_the_coin_is_settled(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100", coid="o1", share="S1", trade="T1")
    e.open_position("buy", "1.0", px="100", coid="o2", share="S2", trade="T2", decided=D0 + 10_000,
                    action=ActionKind.ADD)
    e.advance(D0 + 30_000)
    events = e.broker.on_delist("SOL", Price("95"), D0 + 30_000)
    assert sorted(ev.trade.share_id for ev in events) == ["S1", "S2"]
    assert all(ev.trade.flags == frozenset({"delisted_force_settle"}) for ev in events)
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_F11_AC6_pending_stops_are_cancelled_and_never_fire_after_settlement(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.stop("sl", "sell", "1.0", "99", coid="sl1")
    e.advance(D0 + 30_000)
    e.broker.on_delist("SOL", Price("95"), D0 + 30_000)
    assert e.mark("SOL", "50", D0 + 40_000) == []
    assert e.broker.cancel_stop("sl1") is False
    assert len(e.fills()) == 2


@pytest.mark.unit
def test_F11_AC6_a_pending_order_on_a_delisted_coin_is_rejected_delisted(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", D0 + 1000, "100")
    e.submit(e.order("buy", "1.0"))
    e.advance(D0 + 500)
    (ev,) = e.broker.on_delist("SOL", Price("95"), D0 + 500)
    assert (ev.kind, ev.reason) == ("reject", "delisted")
    assert e.advance(D0 + 1000) == []
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_F11_AC6_new_orders_on_a_delisted_coin_are_refused(new_env: NewEnv) -> None:
    e = new_env()
    e.advance(D0 + 500)
    e.broker.on_delist("SOL", Price("95"), D0 + 500)
    assert e.submit(e.order("buy", "1.0", decided=D0 + 1000)).reason == "delisted"


@pytest.mark.unit
def test_F11_AC6_delisting_a_coin_with_no_position_or_an_unknown_coin_is_harmless(new_env: NewEnv) -> None:
    e = new_env()
    assert list(e.broker.on_delist("SOL", Price("95"), D0 + 500)) == []
    assert list(e.broker.on_delist("NOPE", Price("1"), D0 + 500)) == []
    assert e.records("fill") == [] and e.records("trade") == []
