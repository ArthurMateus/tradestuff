# mypy: disable-error-code="union-attr"
"""F11 round 3 mutation holes: (g) the gate digest and (h) the exit cadence with a long retry interval.

(g) The digest is canonical: 1.0 and 1.00 (any trailing zeros or exponent form) give one digest, and a value with
    more than 120 significant digits cannot be digested (it raises rather than lose a digit); ``verify`` answers
    ``False`` for it and never raises. 120 digits still work.
(h) ``exits.retry_interval_s`` (5 s) may be longer than ``paper.max_book_age_ms`` (1 s) inside the F1 bounds. Then an
    attempt at ``a`` (every 5 s from the fill time) may use the first snapshot at or after ``a`` if it is at most 1 s
    later; whatever the ``advance_to`` cadence, on a replay port and a live port, the fills are the same.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal as D
from pathlib import Path

import pytest
from tests.paper.helpers import (
    D0,
    KEY,
    Env,
    FakeAlerts,
    FakeBooks,
    FakeClock,
    FakeFunding,
    FakeMeta,
    make_book,
    make_config,
)
from tests.paper.r2_helpers import LiveBooks

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.ledger.store import Ledger
from copytrade.paper.broker import PaperBroker
from copytrade.paper.gate import GateAuthority, intent_digest
from copytrade.paper.types import BrokerEvent, OrderIntent, StopIntent

# ----------------------------------------------------------------------------------------------- (g) gate


def _order(qty: str = "1.0", px: str = "100") -> OrderIntent:
    return OrderIntent(
        client_order_id="c1", coin="SOL", side="buy", qty=Qty(qty), action=ActionKind.OPEN, decided_at_ms=D0,
        decision_px=Price(px), trade_id="T1", share_id="S1", leverage=5, exit_reason=None,
    )


def _stop(qty: str = "1.0", trigger: str = "95") -> StopIntent:
    return StopIntent(
        client_order_id="s1", coin="SOL", kind="sl", side="sell", qty=Qty(qty), trigger_px=Price(trigger),
        trade_id="T1", share_id="S1",
    )


DIGITS_120 = "0." + "1" * 120  # 120 significant digits
DIGITS_121 = "0." + "1" * 121


@pytest.mark.unit
@pytest.mark.parametrize(("a", "b"), [("1.0", "1.00"), ("10", "1E+1"), ("0.50", "0.5"), ("100", "1.00E+2"),
                                       ("2.5000", "2.5")])
def test_R3_hole_g_equal_values_with_different_trailing_zeros_share_one_digest(a: str, b: str) -> None:
    assert intent_digest(_order(qty=a)) == intent_digest(_order(qty=b))
    assert intent_digest(_order(px=a)) == intent_digest(_order(px=b))
    assert intent_digest(_stop(qty=a)) == intent_digest(_stop(qty=b))
    assert intent_digest(_stop(trigger=a)) == intent_digest(_stop(trigger=b))


@pytest.mark.unit
def test_R3_hole_g_a_token_for_1_0_verifies_for_1_00_and_a_different_value_does_not() -> None:
    authority = GateAuthority(KEY)
    token = authority.issue(_order(qty="1.0"))
    assert authority.verify(token, _order(qty="1.00"))
    assert not authority.verify(token, _order(qty="1.01"))
    assert intent_digest(_order(qty="1.0")) != intent_digest(_order(qty="1.01"))


@pytest.mark.unit
def test_R3_hole_g_120_significant_digits_can_be_digested_and_verified() -> None:
    authority = GateAuthority(KEY)
    for intent in (_order(qty=DIGITS_120), _order(px=DIGITS_120), _stop(qty=DIGITS_120), _stop(trigger=DIGITS_120)):
        assert authority.verify(authority.issue(intent), intent)


@pytest.mark.unit
@pytest.mark.parametrize("make", [lambda: _order(qty=DIGITS_121), lambda: _order(px=DIGITS_121),
                                  lambda: _stop(qty=DIGITS_121), lambda: _stop(trigger=DIGITS_121)],
                         ids=["order_qty", "order_px", "stop_qty", "stop_trigger"])
def test_R3_hole_g_more_than_120_significant_digits_cannot_be_approved_and_verify_is_false(make) -> None:  # type: ignore[no-untyped-def]  # noqa: ANN001
    authority = GateAuthority(KEY)
    intent = make()
    with pytest.raises((ArithmeticError, ValueError, TypeError)):
        intent_digest(intent)
    with pytest.raises((ArithmeticError, ValueError, TypeError)):
        authority.issue(intent)
    # a token issued for something else never verifies for it, and verify does not raise
    other = authority.issue(_order())
    assert authority.verify(other, intent) is False


@pytest.mark.unit
def test_R3_hole_g_two_values_that_differ_only_at_the_120th_digit_have_different_digests() -> None:
    a = "0." + "1" * 119 + "1"
    b = "0." + "1" * 119 + "2"
    assert intent_digest(_order(qty=a)) != intent_digest(_order(qty=b))
    assert D(a) != D(b)


# ------------------------------------------------------------------------------------------- (h) cadence

RETRY_S = 5
MAX_AGE = 1000
ACK = 1000
T = D0 + 10_000
END = T + 20_000
CONFIG = dict(exits__retry_interval_s=RETRY_S, paper__max_book_age_ms=MAX_AGE)

# (book offsets from T with their price, expected fill offset or None). Attempts happen at T + 1000 (the fill time),
# T + 6000, T + 11000, ...; an attempt at a takes the first snapshot at or after a if it is at most 1000 ms later.
CADENCE_CASES = [
    pytest.param(((4000, "105"), (6500, "110")), (6500, "110"), id="stale_first_window_then_used_by_second_attempt"),
    pytest.param(((2000, "110"),), (2000, "110"), id="exactly_at_the_end_of_the_first_window"),
    pytest.param(((2001, "110"),), None, id="one_ms_past_the_first_window_and_before_the_second_attempt"),
    pytest.param(((7000, "110"),), (7000, "110"), id="exactly_at_the_end_of_the_second_window"),
    pytest.param(((7001, "110"),), None, id="one_ms_past_the_second_window"),
    pytest.param(((3000, "105"),), None, id="a_book_between_the_attempts_is_never_used"),
    pytest.param(((11_500, "110"),), (11_500, "110"), id="third_attempt"),
]


def _steps(cadence: str) -> list[int]:
    if cadence == "single":
        return [END]
    if cadence == "second":
        return list(range(T + 1000, END, 1000)) + [END]
    if cadence == "odd":
        return list(range(T + 777, END, 777)) + [END]
    if cadence == "millisecond":
        return list(range(T + 1, T + 12_600)) + [END]
    raise AssertionError(cadence)


@contextmanager
def _env(*, live: bool) -> Iterator[Env]:
    """The real broker with a replay or a live book port and a config with a retry interval above the book age."""
    clock = FakeClock()
    with tempfile.TemporaryDirectory() as tmp:
        ledger_dir = Path(tmp) / "ledger"
        ledger = Ledger.open(ledger_dir, clock=clock)
        books = LiveBooks() if live else FakeBooks()
        if isinstance(books, LiveBooks):
            books.horizon = T
        meta, funding, alerts, authority = FakeMeta(), FakeFunding(), FakeAlerts(), GateAuthority(KEY)
        config = make_config(**CONFIG)
        try:
            broker = PaperBroker(
                config=config, books=books, meta=meta, funding=funding, ledger=ledger, clock=clock, alerts=alerts,
                authority=authority,
            )
            yield Env(broker, authority, books, meta, funding, alerts, clock, ledger, ledger_dir, config)
        finally:
            ledger.close()


def _run(books: Sequence[tuple[int, str]], cadence: str, *, live: bool) -> tuple[list[tuple[int, str]], D, int]:
    with _env(live=live) as e:
        e.open_position("buy", "2.0", px="100")
        e.advance(T)
        for offset, px in books:
            e.books.add(make_book("SOL", T + offset, [(px, "1000")], [(px, "1000")]))
        assert e.submit(e.order("sell", "2.0", coid="x1", action=ActionKind.CLOSE, decided=T, px="100")).accepted
        events: list[BrokerEvent] = []
        for step in _steps(cadence):
            if isinstance(e.books, LiveBooks):
                e.books.horizon = step
            events += e.advance(step)
        fills = [(ev.fill.time.ms - T, str(ev.fill.price)) for ev in events if ev.kind == "fill"]
        return fills, e.broker.cash_usd(), len(e.records("paper_alert"))


@pytest.mark.unit
@pytest.mark.parametrize(("books", "expected"), CADENCE_CASES)
def test_R3_hole_h_a_retry_interval_longer_than_the_book_age_window_single_call(
    books: tuple[tuple[int, str], ...], expected: tuple[int, str] | None
) -> None:
    fills, _cash, _alerts = _run(books, "single", live=False)
    assert fills == ([] if expected is None else [(expected[0], expected[1])])


@pytest.mark.unit
@pytest.mark.parametrize("live", [False, True], ids=["replay_port", "live_port"])
@pytest.mark.parametrize("cadence", ["second", "odd", "millisecond"])
@pytest.mark.parametrize(("books", "expected"), CADENCE_CASES)
def test_R3_hole_h_the_result_does_not_depend_on_the_advance_cadence(
    books: tuple[tuple[int, str], ...], expected: tuple[int, str] | None, cadence: str, live: bool
) -> None:
    reference = _run(books, "single", live=False)
    assert _run(books, cadence, live=live) == reference
    assert reference[0] == ([] if expected is None else [(expected[0], expected[1])])
