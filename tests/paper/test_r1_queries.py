# mypy: disable-error-code="attr-defined,union-attr"
"""F10 review round 1 (B1, B2, B7): the two small read-only F11 queries the risk gate needs, pinned here.

Pinned contract (the developer adds it to ``PaperBroker``; nothing else about F11 changes):

* ``PaperBroker.pending_entries() -> tuple[PendingEntry, ...]``: every OPEN/ADD order the broker accepted and has not
  yet resolved (filled, rejected or dropped), in the order it was accepted. ``PendingEntry`` is a frozen dataclass with
  ``client_order_id``, ``coin``, ``side`` ("buy"/"sell"), ``action`` (``ActionKind.OPEN``/``ADD``), ``qty`` (positive,
  the lot-rounded quantity still to fill), ``decision_px``, ``leverage`` (int), ``share_id``, ``trade_id`` and
  ``decided_at_ms``. Exits and stops are never listed. The result is a snapshot (a tuple).
* ``PaperBroker.positions() -> tuple[PositionView, ...]``: every open merged position, sorted by coin; each item equals
  ``position(coin)``.
* ``PositionView.share_qtys: tuple[Qty, ...]``: a new field, last, defaulted to ``()``; the ABSOLUTE (positive) open
  quantity of each share, in the order of ``share_ids``.

The tests use the real broker, real ledger and the recorded-book fake; nothing of ours is mocked.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.paper.types import MarkUpdate
from tests.paper.helpers import D0, Env, NewEnv


def _send(
    e: Env,
    coid: str,
    *,
    side: str = "buy",
    coin: str = "SOL",
    qty: str = "1.0",
    share: str = "S1",
    action: ActionKind = ActionKind.OPEN,
    leverage: int = 5,
    decided: int = D0,
) -> None:
    e.broker.advance_to(decided)
    result = e.submit(
        e.order(
            side,
            qty,
            coid=coid,
            coin=coin,
            decided=decided,
            share=share,
            trade=f"T-{share}",
            leverage=leverage,
            action=action,
        )
    )
    assert result.accepted, result


@pytest.mark.unit
def test_F10_B1_pending_entries_is_empty_on_a_fresh_broker(new_env: NewEnv) -> None:
    e = new_env()
    assert e.broker.pending_entries() == ()


@pytest.mark.unit
def test_F10_B1_an_accepted_open_is_listed_with_every_field_the_gate_needs(new_env: NewEnv) -> None:
    e = new_env()
    _send(e, "c1", qty="1.0", leverage=4)
    (p,) = e.broker.pending_entries()
    assert (p.client_order_id, p.coin, p.side, p.action) == ("c1", "SOL", "buy", ActionKind.OPEN)
    assert (p.qty, p.decision_px, p.leverage) == (D("1.0"), Price("100"), 4)
    assert (p.share_id, p.trade_id, p.decided_at_ms) == ("S1", "T-S1", D0)


@pytest.mark.unit
def test_F10_B1_the_listed_quantity_is_the_lot_rounded_quantity_the_broker_will_fill(new_env: NewEnv) -> None:
    e = new_env()
    _send(e, "c1", qty="1.239")  # SOL has 2 size decimals: rounded down to 1.23
    (p,) = e.broker.pending_entries()
    assert p.qty == D("1.23")


@pytest.mark.unit
def test_F10_B1_a_short_entry_is_listed_as_a_sell(new_env: NewEnv) -> None:
    e = new_env()
    _send(e, "c1", side="sell")
    (p,) = e.broker.pending_entries()
    assert (p.side, p.qty) == ("sell", D("1.0"))


@pytest.mark.unit
def test_F10_B1_an_add_is_listed_as_an_add(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    _send(e, "c2", qty="0.5", action=ActionKind.ADD, decided=D0 + 2000)
    (p,) = e.broker.pending_entries()
    assert (p.action, p.qty, p.share_id) == (ActionKind.ADD, D("0.5"), "S1")


@pytest.mark.unit
def test_F10_B1_entries_are_listed_in_the_order_they_were_accepted(new_env: NewEnv) -> None:
    e = new_env()
    _send(e, "b", coin="ETH", share="SB")
    _send(e, "a", coin="SOL", share="SA")
    _send(e, "c", coin="DOGE", qty="5", share="SC")
    assert [p.client_order_id for p in e.broker.pending_entries()] == ["b", "a", "c"]


@pytest.mark.unit
def test_F10_B1_a_refused_order_is_never_listed(new_env: NewEnv) -> None:
    e = new_env()
    e.broker.advance_to(D0)
    result = e.submit(e.order("buy", "1.0", coid="c1", leverage=21))  # SOL allows 20x
    assert result.accepted is False
    assert e.broker.pending_entries() == ()


@pytest.mark.unit
def test_F10_B1_exits_and_stops_are_never_listed(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    e.advance(D0 + 5000)
    assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=D0 + 5000)).accepted
    assert e.stop("sl", "sell", "1.0", "95", coid="st1").accepted
    assert e.broker.pending_entries() == ()


@pytest.mark.unit
def test_F10_B1_a_filled_entry_leaves_the_list(new_env: NewEnv) -> None:
    e = new_env()
    e.flat_book("SOL", D0 + 1000, "100")
    _send(e, "c1")
    assert len(e.broker.pending_entries()) == 1
    e.advance(D0 + 1000)
    assert e.broker.pending_entries() == ()
    assert e.broker.position("SOL") is not None


@pytest.mark.unit
def test_F10_B1_an_entry_with_no_book_leaves_the_list_when_its_window_runs_out(new_env: NewEnv) -> None:
    e = new_env()
    _send(e, "c1")
    e.advance(D0 + 1000 + 5000)  # fill time + paper.max_book_age_ms: the window is still open
    assert len(e.broker.pending_entries()) == 1
    e.advance(D0 + 1000 + 5001)
    assert e.broker.pending_entries() == ()
    assert [ev.reason for ev in e.events if ev.kind == "reject"] == ["no_book"]


@pytest.mark.unit
def test_F10_B1_an_entry_on_a_delisted_coin_leaves_the_list(new_env: NewEnv) -> None:
    e = new_env()
    _send(e, "c1")
    e.broker.on_delist("SOL", Price("90"), D0 + 500)
    assert e.broker.pending_entries() == ()


@pytest.mark.unit
def test_F10_B1_an_entry_rejected_at_fill_time_leaves_the_list(new_env: NewEnv) -> None:
    e = new_env()
    e.book("SOL", D0 + 1000, [("100", "1000")], [])  # one-sided book: no_depth
    _send(e, "c1")
    e.advance(D0 + 1000)
    assert e.broker.pending_entries() == ()
    assert [ev.reason for ev in e.events if ev.kind == "reject"] == ["no_depth"]


@pytest.mark.unit
def test_F10_B1_the_list_is_a_snapshot(new_env: NewEnv) -> None:
    e = new_env()
    _send(e, "c1")
    before = e.broker.pending_entries()
    e.broker.on_delist("SOL", Price("90"), D0 + 500)
    assert isinstance(before, tuple) and len(before) == 1  # the earlier answer does not change
    assert e.broker.pending_entries() == ()


@pytest.mark.unit
def test_F10_B1_the_query_moves_nothing(new_env: NewEnv) -> None:
    e = new_env()
    _send(e, "c1")
    records = len(e.records())
    for _ in range(3):
        e.broker.pending_entries()
        e.broker.positions()
    assert len(e.records()) == records
    assert len(e.broker.pending_entries()) == 1


# ---- positions() (B2) ------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_F10_B2_positions_is_empty_on_a_fresh_broker(new_env: NewEnv) -> None:
    assert new_env().broker.positions() == ()


@pytest.mark.unit
def test_F10_B2_positions_lists_every_open_position_sorted_by_coin(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", coin="SOL", coid="o1", share="S1", decided=D0)
    e.open_position("sell", "0.5", coin="ETH", coid="o2", share="S2", decided=D0 + 2000)
    e.open_position("buy", "3", coin="DOGE", coid="o3", share="S3", decided=D0 + 4000, leverage=2)
    views = e.broker.positions()
    assert isinstance(views, tuple)
    assert [v.coin for v in views] == ["DOGE", "ETH", "SOL"]
    for view in views:
        assert view == e.broker.position(view.coin)


@pytest.mark.unit
def test_F10_B2_a_closed_position_leaves_positions(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", coin="SOL", coid="o1", share="S1")
    e.open_position("buy", "1.0", coin="ETH", coid="o2", share="S2", decided=D0 + 2000)
    e.advance(D0 + 5000)
    e.flat_book("SOL", D0 + 6000, "100")
    assert e.submit(e.order("sell", "1.0", coid="x1", action=ActionKind.CLOSE, decided=D0 + 5000, share="S1")).accepted
    e.advance(D0 + 6000)
    assert [v.coin for v in e.broker.positions()] == ["ETH"]


@pytest.mark.unit
def test_F10_B2_share_qtys_lists_each_share_absolute_quantity_in_share_id_order(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", coid="o1", share="S1")
    e.open_position("buy", "0.5", coid="o2", share="S2", decided=D0 + 2000)
    (view,) = e.broker.positions()
    assert view.share_ids == ("S1", "S2")
    assert view.share_qtys == (D("1.0"), D("0.5"))
    assert view.qty == D("1.5")
    assert e.broker.position("SOL").share_qtys == (D("1.0"), D("0.5"))


@pytest.mark.unit
def test_F10_B2_share_qtys_of_a_short_are_positive(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("sell", "2.0", coid="o1", share="S1")
    (view,) = e.broker.positions()
    assert view.qty == D("-2.0")
    assert view.share_qtys == (D("2.0"),)


@pytest.mark.unit
def test_F10_B2_share_qtys_follow_a_partial_close(new_env: NewEnv) -> None:
    e = new_env()
    e.open_position("buy", "1.0", coid="o1", share="S1")
    e.open_position("buy", "0.5", coid="o2", share="S2", decided=D0 + 2000)
    e.advance(D0 + 5000)
    e.flat_book("SOL", D0 + 6000, "100")
    assert e.submit(e.order("sell", "0.4", coid="x1", action=ActionKind.REDUCE, decided=D0 + 5000, share="S1")).accepted
    e.advance(D0 + 6000)
    (view,) = e.broker.positions()
    assert view.share_qtys == (D("0.6"), D("0.5"))


@pytest.mark.unit
def test_F10_B2_a_position_is_not_reported_until_its_entry_fills(new_env: NewEnv) -> None:
    e = new_env()
    _send(e, "c1")
    assert e.broker.positions() == ()
    e.flat_book("SOL", D0 + 1000, "100")
    e.broker.on_mark(MarkUpdate("SOL", Price("100"), D0))
    assert e.broker.positions() == ()
