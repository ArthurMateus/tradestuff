# mypy: disable-error-code="union-attr"
"""F11 round 2, Amendment 8 (RISK-7): the result of a replay does not depend on how often ``advance_to`` is called.

The book port serves recorded snapshots, including ones from the future of the broker's clock (replay). Whatever the
cadence of ``advance_to`` (one big call, coarse, every second, every millisecond, arbitrary), the same data must give
identical events, fills and prices: an exit is retried every ``exits.retry_interval_s`` from its fill time, an attempt
may use the first snapshot at or after it that is at most ``paper.max_book_age_ms`` older than the snapshot, and only an
attempt whose book-age window has closed is dropped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.paper.helpers import D0, fresh_env, make_book
from tests.paper.r2_helpers import LiveBooks, custom_env

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price
from copytrade.hl.models import L2Book
from copytrade.paper.types import BrokerEvent

T = D0 + 10_000  # the exit (or entry) is decided here; the broker's time is T when it is submitted
END = T + 20_000
ACK = 1000
MAX_AGE = 5000

_GOOD = "good"
_ONE_SIDED = "one_sided"
_ZERO_DEPTH = "zero_depth"


@dataclass(frozen=True)
class Scenario:
    name: str
    books: tuple[tuple[int, str, str], ...]  # (offset from T, kind, price)
    kind: str  # "exit" or "entry"
    expected: tuple[int, str] | None  # (fill offset from T, price), or None: nothing fills


def _book(coin: str, at: int, kind: str, px: str) -> L2Book:
    if kind == _GOOD:
        return make_book(coin, at, [(px, "1000")], [(px, "1000")])
    if kind == _ONE_SIDED:
        return make_book(coin, at, [], [(px, "1000")])
    return make_book(coin, at, [("80", "10")], [("120", "10")])  # both sides, nothing inside the 5% band


SCENARIOS = [
    Scenario("one_sided_then_good_at_3500", ((1000, _ONE_SIDED, "100"), (3500, _GOOD, "110")), "exit", (3500, "110")),
    Scenario("one_sided_then_good_at_2500", ((1000, _ONE_SIDED, "100"), (2500, _GOOD, "110")), "exit", (2500, "110")),
    Scenario("only_book_exactly_max_age_after_the_attempt", ((6000, _GOOD, "110"),), "exit", (6000, "110")),
    Scenario("only_book_one_ms_beyond_max_age_of_the_first_attempt", ((6001, _GOOD, "110"),), "exit", (6001, "110")),
    Scenario("stale_for_the_first_attempts_then_used", ((7000, _GOOD, "110"),), "exit", (7000, "110")),
    Scenario(
        "one_sided_then_a_good_book_too_old_for_the_next_attempt",
        ((2500, _ONE_SIDED, "100"), (9000, _GOOD, "110")),
        "exit",
        (9000, "110"),
    ),
    Scenario(
        "zero_depth_exit_that_later_fills",
        ((1000, _ZERO_DEPTH, "100"), (12_000, _GOOD, "110")),
        "exit",
        (12_000, "110"),
    ),
    Scenario("exit_with_no_book_at_all", (), "exit", None),
    Scenario("entry_with_a_book_exactly_at_the_window_end", ((6000, _GOOD, "110"),), "entry", (6000, "110")),
    Scenario("entry_with_a_book_one_ms_past_the_window_end", ((6001, _GOOD, "110"),), "entry", None),
    Scenario("entry_with_a_one_sided_book", ((1000, _ONE_SIDED, "100"), (2000, _GOOD, "110")), "entry", None),
]


def _steps(cadence: str) -> list[int]:
    if cadence == "single":
        return [END]
    if cadence == "coarse":
        return list(range(T + 5000, END, 5000)) + [END]
    if cadence == "second":
        return list(range(T + 1000, END, 1000)) + [END]
    if cadence == "odd":
        return list(range(T + 777, END, 777)) + [END]
    if cadence == "millisecond":  # every ms through the busy part, then one call to the end
        return list(range(T + 1, T + 13_000)) + [END]
    raise AssertionError(cadence)


def _run(scenario: Scenario, steps: Sequence[int], *, live: bool = False) -> tuple[list[BrokerEvent], D, str, int]:
    """Replay (``live=False``: the port also serves snapshots from the broker's future) or live (a snapshot exists only
    once the driver's time has reached it)."""
    books = LiveBooks() if live else None
    with custom_env(books=books) as e:
        if isinstance(e.books, LiveBooks):
            e.books.horizon = T
        e.open_position("buy", "2.0", px="100")
        e.advance(T)
        for offset, kind, px in scenario.books:
            e.books.add(_book("SOL", T + offset, kind, px))
        if scenario.kind == "exit":
            intent = e.order("sell", "2.0", coid="x1", action=ActionKind.CLOSE, decided=T, px="100")
        else:
            intent = e.order("buy", "1.0", coid="x1", action=ActionKind.ADD, decided=T, share="S2", trade="T2")
        assert e.submit(intent).accepted
        events: list[BrokerEvent] = []
        for step in steps:
            if isinstance(e.books, LiveBooks):
                e.books.horizon = step
            events += e.advance(step)
        position = e.broker.position("SOL")
        return events, e.broker.cash_usd(), str(None if position is None else position.qty), len(e.fills())


def _fills(events: list[BrokerEvent]) -> list[tuple[int, Price]]:
    return [(ev.fill.time.ms - T, ev.fill.price) for ev in events if ev.fill is not None and ev.kind == "fill"]


_IDS = [s.name for s in SCENARIOS]
_CADENCES = ["coarse", "second", "odd", "millisecond"]


@pytest.mark.unit
@pytest.mark.parametrize("scenario", SCENARIOS, ids=_IDS)
def test_R2_RISK7_the_single_call_result_is_the_expected_one(scenario: Scenario) -> None:
    events, _cash, _qty, n_fills = _run(scenario, _steps("single"))
    fills = _fills(events)
    if scenario.expected is None:
        assert fills == [] and n_fills == 1  # only the setup fill
    else:
        offset, px = scenario.expected
        assert fills == [(offset, Price(px))]


@pytest.mark.unit
@pytest.mark.parametrize("live", [False, True], ids=["replay_port", "live_port"])
@pytest.mark.parametrize("cadence", _CADENCES)
@pytest.mark.parametrize("scenario", SCENARIOS, ids=_IDS)
def test_R2_RISK7_any_advance_cadence_gives_identical_events_fills_and_cash(
    scenario: Scenario, cadence: str, live: bool
) -> None:
    reference = _run(scenario, _steps("single"))
    stepped = _run(scenario, _steps(cadence), live=live)
    assert stepped[0] == reference[0]  # the same events, in the same order, at the same times
    assert stepped[1:] == reference[1:]  # the same cash, position and number of fills


@pytest.mark.unit
@settings(max_examples=40, deadline=None)
@given(
    index=st.integers(min_value=0, max_value=len(SCENARIOS) - 1),
    cuts=st.lists(st.integers(min_value=T + 1, max_value=END - 1), max_size=25, unique=True),
    live=st.booleans(),
)
def test_R2_RISK7_property_arbitrary_step_times_give_the_same_result_as_one_call(
    index: int, cuts: list[int], live: bool
) -> None:
    scenario = SCENARIOS[index]
    reference = _run(scenario, [END])
    assert _run(scenario, sorted(cuts) + [END], live=live) == reference


@pytest.mark.unit
def test_R2_RISK7_the_unfilled_exit_alert_time_does_not_depend_on_the_cadence() -> None:
    """The zero-depth exit is still unfilled 10 s after its decision: one alert, stamped with its due time."""
    scenario = next(s for s in SCENARIOS if s.name == "zero_depth_exit_that_later_fills")
    for cadence in ("single", "second", "odd"):
        events, *_ = _run(scenario, _steps(cadence))
        alerts = [ev for ev in events if ev.kind == "exit_unfilled_alert"]
        assert [ev.time_ms for ev in alerts] == [T + 10_000]
        assert [ev.kind for ev in events] == ["exit_unfilled_alert", "fill"]


@pytest.mark.unit
def test_R2_RISK7_a_book_that_shows_up_late_is_used_by_the_attempt_it_belongs_to() -> None:
    """One-sided book, and the good book only becomes visible after the broker's time has moved past it."""
    with fresh_env() as e:
        e.open_position("buy", "2.0", px="100")
        e.advance(T)
        e.books.add(_book("SOL", T + 1000, _ONE_SIDED, "100"))
        e.books.add(_book("SOL", T + 3500, _GOOD, "110"))
        assert e.submit(e.order("sell", "2.0", coid="x1", action=ActionKind.CLOSE, decided=T)).accepted
        assert e.advance(T + 3000) == []  # the recorded 3500 snapshot is still in the future
        (ev,) = e.advance(T + 4000)
        assert (ev.fill.time.ms, ev.fill.price) == (T + 3500, Price("110"))
        assert e.broker.position("SOL") is None
