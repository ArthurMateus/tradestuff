# mypy: disable-error-code="union-attr"
"""F11 round 2, Amendment 8: exits and stops never depend on meta (RISK-3); a failing non-money dependency never
latches the broker while a ledger or state error still does (RISK-6, A2), plus the fail-closed latch itself.
"""

from __future__ import annotations

import lzma
from collections.abc import Callable

import pytest
from tests.paper.helpers import BASE, D0, HOUR_MS, Env
from tests.paper.r2_helpers import (
    FlakyAlerts,
    FlakyBooks,
    FlakyFunding,
    FlakyMeta,
    custom_env,
)

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.ledger.errors import LedgerWriteError
from copytrade.paper.errors import PaperBrokerFailedError
from copytrade.paper.types import CoinMeta, MarkUpdate

B1 = BASE + HOUR_MS
LATER = D0 + HOUR_MS + 700_000  # past the 60-minute meta refresh (and past the B1 boundary)


def _meta_drops_sol(e: Env) -> None:
    del e.meta.meta["SOL"]


def _meta_invalid_for_sol(e: Env) -> None:
    e.meta.meta["SOL"] = CoinMeta(sz_decimals=99, max_leverage=0)


def _meta_changes_lot(e: Env) -> None:
    e.meta.meta["SOL"] = CoinMeta(sz_decimals=0, max_leverage=20)  # a coarser lot than the stored 2 decimals


_META_BREAKERS = [_meta_drops_sol, _meta_invalid_for_sol, _meta_changes_lot]
_IDS = ["coin_dropped", "rules_invalid", "lot_changed"]


def _open_then_break_meta(e: Env, breaker: Callable[[Env], None]) -> None:
    e.open_position("buy", "2.0", px="100")
    e.funding.set("SOL", B1, "0.0001", "100")
    breaker(e)
    e.advance(LATER)  # the next meta use will refresh (>= paper.meta_refresh_min after the first fetch)


# ------------------------------------------------------------------------------------------------- RISK-3


@pytest.mark.unit
@pytest.mark.parametrize("breaker", _META_BREAKERS, ids=_IDS)
def test_R2_RISK3_a_close_still_works_after_a_meta_refresh_dropped_or_broke_the_coin(
    new_env: Callable[..., Env], breaker: Callable[[Env], None]
) -> None:
    e = new_env()
    _open_then_break_meta(e, breaker)
    e.flat_book("SOL", LATER + 1000, "101")
    result = e.submit(e.order("sell", "2.0", coid="x1", action=ActionKind.CLOSE, decided=LATER))
    assert (result.accepted, result.reason) == (True, None)
    (ev,) = e.advance(LATER + 1000)
    assert ev.kind == "fill" and ev.trade is not None
    assert e.broker.position("SOL") is None


@pytest.mark.unit
@pytest.mark.parametrize("breaker", _META_BREAKERS, ids=_IDS)
def test_R2_RISK3_a_reduce_uses_the_stored_lot_size_after_meta_broke(
    new_env: Callable[..., Env], breaker: Callable[[Env], None]
) -> None:
    e = new_env()
    _open_then_break_meta(e, breaker)
    e.flat_book("SOL", LATER + 1000, "101")
    result = e.submit(e.order("sell", "0.555", coid="x1", action=ActionKind.REDUCE, decided=LATER))
    assert (result.accepted, result.reason) == (True, None)
    (ev,) = e.advance(LATER + 1000)
    assert ev.fill.qty == Qty("0.55")  # rounded down at the position's stored 2 decimals
    assert e.broker.position("SOL").qty == Qty("1.45")


@pytest.mark.unit
@pytest.mark.parametrize("breaker", _META_BREAKERS, ids=_IDS)
def test_R2_RISK3_a_stop_can_still_be_placed_and_fires_after_meta_broke(
    new_env: Callable[..., Env], breaker: Callable[[Env], None]
) -> None:
    e = new_env()
    _open_then_break_meta(e, breaker)
    assert e.stop("sl", "sell", "2.0", "95").accepted
    e.flat_book("SOL", LATER + 1000, "94")
    e.mark("SOL", "94", LATER)
    events = e.advance(LATER + 1000)
    assert [ev.kind for ev in events] == ["fill"] and events[0].fill.exit_reason == "stop_loss"
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_R2_RISK3_a_stop_registered_before_the_meta_broke_still_fires_after(new_env: Callable[..., Env]) -> None:
    e = new_env()
    e.open_position("buy", "2.0", px="100")
    assert e.stop("sl", "sell", "2.0", "95").accepted
    _meta_drops_sol(e)
    e.advance(LATER)
    e.submit(e.order("buy", "1.0", coid="probe", decided=LATER))  # forces the refresh
    e.flat_book("SOL", LATER + 1000, "94")
    e.mark("SOL", "94", LATER)
    assert [ev.kind for ev in e.advance(LATER + 1000)] == ["fill"]
    assert e.broker.position("SOL") is None


@pytest.mark.unit
def test_R2_RISK3_entries_still_need_meta_a_dropped_coin_refuses_a_new_open(new_env: Callable[..., Env]) -> None:
    """Control: only exits and stops are exempt; a new entry on a coin meta no longer lists is refused."""
    e = new_env()
    e.open_position("buy", "1.0", px="100")
    _meta_drops_sol(e)
    e.advance(LATER)
    result = e.submit(e.order("buy", "1.0", coid="add", action=ActionKind.ADD, decided=LATER, share="S2", trade="T2"))
    assert (result.accepted, result.reason) == (False, "unknown_coin")


@pytest.mark.unit
def test_R2_RISK3_meta_refresh_failures_of_any_kind_do_not_block_an_exit() -> None:
    meta = FlakyMeta()
    with custom_env(meta=meta) as e:
        e.open_position("buy", "2.0", px="100")
        meta.error = ValueError("meta payload is malformed")  # not an OSError
        e.advance(LATER)
        e.flat_book("SOL", LATER + 1000, "100")
        result = e.submit(e.order("sell", "2.0", coid="x1", action=ActionKind.CLOSE, decided=LATER))
        assert (result.accepted, result.reason) == (True, None)
        assert [ev.kind for ev in e.advance(LATER + 1000)] == ["fill"]


# ------------------------------------------------------------------------------------------------- RISK-6

_NON_OS_ERRORS = [RuntimeError("sink down"), ValueError("bad payload"), lzma.LZMAError("corrupt xz stream")]
_ERR_IDS = ["RuntimeError", "ValueError", "LZMAError"]


@pytest.mark.unit
@pytest.mark.parametrize("error", _NON_OS_ERRORS, ids=_ERR_IDS)
def test_R2_RISK6_an_alert_sink_raising_on_the_unfilled_exit_alert_does_not_latch_the_broker(error: Exception) -> None:
    alerts = FlakyAlerts()
    with custom_env(alerts=alerts) as e:
        e.open_position("buy", "2.0", px="100")
        alerts.error = error
        assert e.submit(e.order("sell", "2.0", coid="x1", action=ActionKind.CLOSE, decided=D0 + 10_000)).accepted
        events = e.advance(D0 + 30_000)  # no book: the 10 s alert fires and the sink raises
        assert [ev.kind for ev in events] == ["exit_unfilled_alert"]
        assert alerts.attempts >= 1
        alerts.error = None
        e.flat_book("SOL", D0 + 31_000, "100")
        assert [ev.kind for ev in e.advance(D0 + 31_000)] == ["fill"]  # the broker is alive and the exit still fills


@pytest.mark.unit
@pytest.mark.parametrize("error", _NON_OS_ERRORS, ids=_ERR_IDS)
def test_R2_RISK6_an_alert_sink_raising_on_liquidation_still_liquidates_and_stays_usable(error: Exception) -> None:
    alerts = FlakyAlerts()
    with custom_env(alerts=alerts) as e:
        e.open_position("buy", "1.0", px="100")
        alerts.error = error
        events = e.mark("SOL", "80", D0 + 10_000)
        assert [ev.kind for ev in events] == ["liquidated"]
        assert e.broker.position("SOL") is None
        alerts.error = None
        e.open_position("buy", "1.0", px="100", coid="again", share="S2", trade="T2", decided=D0 + 20_000)
        assert e.broker.position("SOL").qty == Qty("1.0")


@pytest.mark.unit
@pytest.mark.parametrize("error", _NON_OS_ERRORS, ids=_ERR_IDS)
def test_R2_RISK6_an_alert_sink_raising_on_delisting_still_settles_and_stays_usable(error: Exception) -> None:
    alerts = FlakyAlerts()
    with custom_env(alerts=alerts) as e:
        e.open_position("buy", "1.0", px="100")
        alerts.error = error
        e.advance(D0 + 10_000)
        events = e.broker.on_delist("SOL", Price("90"), D0 + 10_000)
        assert [ev.kind for ev in events] == ["delisted_force_settle"]
        assert e.broker.position("SOL") is None
        e.open_position("buy", "1.0", px="100", coin="BTC", coid="b1", share="S2", trade="T2", decided=D0 + 20_000)
        assert e.broker.position("BTC") is not None


@pytest.mark.unit
@pytest.mark.parametrize("error", _NON_OS_ERRORS, ids=_ERR_IDS)
def test_R2_RISK6_an_alert_sink_raising_on_missing_funding_does_not_latch_the_broker(error: Exception) -> None:
    alerts = FlakyAlerts()
    with custom_env(alerts=alerts) as e:
        e.open_position("buy", "2.0", px="100")
        alerts.error = error
        e.advance(B1 + 1000)  # no funding rate for B1: funding_missing is alerted and the sink raises
        assert alerts.attempts >= 1
        alerts.error = None
        e.funding.set("SOL", B1, "0.0001", "100")
        e.advance(B1 + 2000)
        assert [r.payload["hour_ms"] for r in e.records("paper_funding")] == [B1]


@pytest.mark.unit
@pytest.mark.parametrize("error", _NON_OS_ERRORS, ids=_ERR_IDS)
def test_R2_RISK6_a_book_port_raising_a_non_os_error_is_no_data_and_an_exit_still_fills_later(
    error: Exception,
) -> None:
    books = FlakyBooks()
    with custom_env(books=books) as e:
        e.open_position("buy", "2.0", px="100")
        e.flat_book("SOL", D0 + 30_000, "100")
        e.advance(D0 + 10_000)  # broker time reaches the exit's decision time (Amendment 10)
        assert e.submit(e.order("sell", "2.0", coid="x1", action=ActionKind.CLOSE, decided=D0 + 10_000)).accepted
        books.error = error
        e.advance(D0 + 12_000)  # must not raise
        books.error = None
        events = e.advance(D0 + 30_000)
        assert [ev.kind for ev in events] == ["exit_unfilled_alert", "fill"]
        assert e.broker.position("SOL") is None


@pytest.mark.unit
@pytest.mark.parametrize("error", _NON_OS_ERRORS, ids=_ERR_IDS)
def test_R2_RISK6_a_book_port_raising_during_an_entry_does_not_latch_the_broker(error: Exception) -> None:
    books = FlakyBooks()
    with custom_env(books=books) as e:
        assert e.submit(e.order("buy", "1.0", coid="c1")).accepted
        books.error = error
        e.advance(D0 + 20_000)  # the entry's window passes with no usable book: must not raise
        books.error = None
        assert e.broker.position("SOL") is None
        e.open_position("buy", "1.0", px="100", coid="c2", share="S2", trade="T2", decided=D0 + 30_000)
        assert e.broker.position("SOL").qty == Qty("1.0")


@pytest.mark.unit
@pytest.mark.parametrize("error", _NON_OS_ERRORS, ids=_ERR_IDS)
def test_R2_RISK6_a_funding_port_raising_a_non_os_error_is_missing_data_alerted_once_then_retried(
    error: Exception,
) -> None:
    funding = FlakyFunding()
    with custom_env(funding=funding) as e:
        e.open_position("buy", "2.0", px="100")
        funding.set("SOL", B1, "0.0001", "100")
        funding.error = error
        e.advance(B1 + 1000)  # must not raise
        e.advance(B1 + 2000)
        assert e.alerts.kinds().count("funding_missing") == 1
        assert e.records("paper_funding") == []
        funding.error = None
        e.advance(B1 + 3000)
        assert [r.payload["hour_ms"] for r in e.records("paper_funding")] == [B1]


@pytest.mark.unit
@pytest.mark.parametrize("error", _NON_OS_ERRORS, ids=_ERR_IDS)
def test_R2_RISK6_a_meta_port_raising_a_non_os_error_first_time_is_meta_unavailable_not_a_latch(
    error: Exception,
) -> None:
    meta = FlakyMeta()
    meta.error = error
    with custom_env(meta=meta) as e:
        result = e.submit(e.order("buy", "1.0"))
        assert (result.accepted, result.reason) == (False, "meta_unavailable")
        meta.error = None
        e.flat_book("SOL", D0 + 1000, "100")
        assert e.submit(e.order("buy", "1.0", coid="c2")).accepted


# ----------------------------------------------------------------------------------- the fail-closed latch (A2)


def _session(e: Env) -> list[Callable[[], object]]:
    """A scripted run that touches every state-changing entry point and writes to the ledger many times."""
    e.flat_book("SOL", D0 + 1000, "100")
    e.flat_book("SOL", D0 + 12_000, "100")
    e.flat_book("SOL", D0 + 22_000, "100")
    open_intent = e.order("buy", "2.0", coid="o1")
    stop_intent = e.order("sell", "1.0", coid="x1", action=ActionKind.REDUCE, decided=D0 + 10_000)
    return [
        lambda: e.broker.submit(open_intent, e.token(open_intent)),
        lambda: e.broker.advance_to(D0 + 1000),
        lambda: e.stop("sl", "sell", "1.0", "90", coid="s1"),
        lambda: e.broker.cancel_stop("s1"),
        lambda: e.stop("sl", "sell", "1.0", "90", coid="s2"),
        lambda: e.broker.advance_to(D0 + 10_000),  # broker time reaches the exit's decision time (Amendment 10)
        lambda: e.broker.submit(stop_intent, e.token(stop_intent)),
        lambda: e.broker.advance_to(D0 + 12_000),
        lambda: e.broker.on_mark(MarkUpdate("SOL", Price("80"), D0 + 13_000)),
        lambda: e.broker.on_delist("SOL", Price("90"), D0 + 14_000),
    ]


def _total_writes() -> int:
    with custom_env() as e:
        for step in _session(e):
            step()
        ledger = e.ledger
        return ledger.attempts  # type: ignore[attr-defined, no-any-return]


@pytest.mark.unit
def test_R2_fail_closed_the_scripted_session_writes_enough_records_to_make_the_latch_tests_meaningful() -> None:
    assert _total_writes() == 10  # the fail_at range below covers every write


@pytest.mark.unit
@pytest.mark.parametrize("fail_at", list(range(1, 11)))
@pytest.mark.parametrize("error", [LedgerWriteError("disk full"), RuntimeError("state error")], ids=["disk", "state"])
def test_R2_A2_a_ledger_that_fails_on_the_nth_write_latches_every_state_changing_call_and_no_write_follows(
    fail_at: int, error: Exception
) -> None:
    with custom_env(fail_at=fail_at, ledger_error=error) as e:
        steps = _session(e)
        failed_index = None
        for index, step in enumerate(steps):
            try:
                step()
            except type(error):
                failed_index = index
                break
        assert failed_index is not None, "the ledger error must reach the caller"
        ledger = e.ledger
        attempts_at_failure = ledger.attempts  # type: ignore[attr-defined]
        records_at_failure = len(e.records())
        cash = e.broker.cash_usd()
        probe = e.order("buy", "1.0", coid="after", decided=D0 + 50_000)
        calls: list[Callable[[], object]] = [
            lambda: e.broker.submit(probe, e.token(probe)),
            lambda: e.broker.advance_to(D0 + 60_000),
            lambda: e.broker.on_mark(MarkUpdate("SOL", Price("80"), D0 + 61_000)),
            lambda: e.broker.on_delist("SOL", Price("90"), D0 + 62_000),
            lambda: e.broker.cancel_stop("s2"),
            lambda: e.stop("sl", "sell", "1.0", "90", coid="s3"),
        ]
        for call in calls:
            with pytest.raises(PaperBrokerFailedError):
                call()
        assert ledger.attempts == attempts_at_failure  # type: ignore[attr-defined]
        assert len(e.records()) == records_at_failure
        assert e.broker.cash_usd() == cash  # queries stay available and nothing moved
