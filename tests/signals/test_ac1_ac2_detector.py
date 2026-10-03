"""F7.AC1 and F7.AC2 through the real detector, ledger and sink: typed signals, the ledger record before delivery,
deterministic signal ids, and idempotency by ``tid`` (A5) whatever the source, order, batch shape or restart.

Spec: 04-spec.md F7.AC1, F7.AC2, §5 "Unknown fill format or dir value", invariants A2, A5, B5.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from copytrade.core.domain import ActionKind
from copytrade.ledger.errors import LedgerWriteError
from copytrade.signals.detector import ALERT_UNPARSEABLE, SignalDetector
from copytrade.signals.models import UNPARSEABLE
from tests.signals.helpers import (
    T0,
    WALLET_A,
    WALLET_B,
    Rig,
    make_rig,
    mkfill,
)

pytestmark = pytest.mark.unit


def test_F7_AC1_each_fill_type_becomes_the_typed_signal_with_direction_size_and_fraction(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    got = rig.feed(
        [
            mkfill(1, side="B", sz="2", start="0"),  # open long
            mkfill(2, side="B", sz="1", start="2"),  # add
            mkfill(3, side="A", sz="1", start="3"),  # reduce 1/3
            mkfill(4, side="A", sz="2", start="2"),  # close
        ]
    )
    assert [s.action for s in got] == [ActionKind.OPEN, ActionKind.ADD, ActionKind.REDUCE, ActionKind.CLOSE]
    assert [s.is_long for s in got] == [True] * 4
    assert [str(s.size) for s in got] == ["2", "1", "1", "2"]
    assert [(str(s.pre_position), str(s.post_position)) for s in got] == [("0", "2"), ("2", "3"), ("3", "2"), ("2", "0")]
    assert [s.reduce_fraction for s in got] == [None, None, Decimal(1) / Decimal(3), None]
    assert all(s.outcome is None and s.wallet == WALLET_A and s.coin == "BTC" for s in got)
    assert [s.tid for s in got] == [1, 2, 3, 4]


def test_F7_AC1_a_flip_gives_a_close_then_an_open_with_distinct_ids_and_one_ledger_record_each(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    got = rig.feed([mkfill(7, side="A", sz="3", start="1")])
    assert [s.action for s in got] == [ActionKind.CLOSE, ActionKind.OPEN]
    assert [s.is_long for s in got] == [True, False]
    assert [str(s.size) for s in got] == ["1", "2"]
    assert [s.leg for s in got] == [0, 1] and all(s.from_flip for s in got) and all(s.tid == 7 for s in got)
    assert got[0].signal_id != got[1].signal_id
    assert len(rig.ledger_signals()) == 2


def test_F7_AC1_every_signal_is_in_the_ledger_before_the_batch_is_delivered(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.feed([mkfill(1), mkfill(2, side="A", sz="3", start="1"), mkfill(3, coin="ETH")])
    assert rig.sink.ledgered_at_delivery == [4]  # 1 + 2 (flip) + 1 signals already ledgered when the sink was called
    payloads = rig.ledger_signals()
    assert [(p["tid"], p["action"]) for p in payloads] == [(1, "open"), (2, "close"), (2, "open"), (3, "open")]
    for p, s in zip(payloads, rig.sink.signals, strict=True):
        assert p["signal_id"] == s.signal_id and p["wallet"] == WALLET_A and p["coin"] == s.coin
        assert p["outcome"] is None and p["age_ms"] == s.age_ms and p["s2_ms"] == s.s2_ms


def test_F7_AC1_one_batch_is_delivered_once_in_fill_order_and_an_empty_batch_delivers_nothing(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    rig.feed([mkfill(3), mkfill(1, coin="ETH"), mkfill(2, coin="SOL")])
    assert len(rig.sink.batches) == 1 and [s.tid for s in rig.sink.batches[0]] == [3, 1, 2]
    rig.feed([])
    assert len(rig.sink.batches) == 1


def test_F7_AC1_prices_and_sizes_stay_decimal_and_exact(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    (s,) = rig.feed([mkfill(1, sz="0.123456789", px="67123.5")])
    assert isinstance(s.px, Decimal) and isinstance(s.size, Decimal)
    assert str(s.px) == "67123.5" and str(s.size) == "0.123456789"
    (p,) = rig.ledger_signals()
    assert str(p["px"]) == "67123.5" and str(p["size"]) == "0.123456789"


def test_F7_AC1_the_leader_liquidation_dir_values_are_classified_by_size_like_any_close(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    got = rig.feed(
        [
            mkfill(1, side="A", sz="2", start="2", dir="Liquidated Cross Long"),
            mkfill(2, coin="ETH", side="B", sz="1", start="-1", dir="Auto-Deleveraging"),
        ]
    )
    assert [(s.action, s.outcome) for s in got] == [(ActionKind.CLOSE, None), (ActionKind.CLOSE, None)]


@pytest.mark.parametrize("bad_dir", ["", "Teleport", "open long", "Buy"])
def test_F7_AC1_an_unknown_dir_value_is_an_unparseable_signal_and_an_alert_and_is_never_traded(
    rig_factory: Callable[..., Rig], bad_dir: str
) -> None:
    rig = rig_factory()
    (s,) = rig.feed([mkfill(1, dir=bad_dir)])
    assert s.outcome == UNPARSEABLE == "unparseable"
    assert s.action is None and s.is_long is None and s.reduce_fraction is None
    assert len(rig.alerts.of_kind(ALERT_UNPARSEABLE)) >= 1
    assert ALERT_UNPARSEABLE == "unparseable_fill"
    assert rig.ledger_signals()[0]["outcome"] == "unparseable"


def test_F7_AC1_a_zero_size_fill_is_unparseable_not_an_exception(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    got = rig.feed([mkfill(1, sz="0", start="1", dir="Close Long"), mkfill(2)])
    assert [s.outcome for s in got] == ["unparseable", None]  # the bad fill does not stop the good one behind it


def test_F7_AC1_a_ledger_that_cannot_be_written_stops_the_batch_and_nothing_is_delivered(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory()
    rig.ledger.close()
    with pytest.raises(LedgerWriteError):
        rig.detector.on_fills(WALLET_A, [mkfill(1)])
    assert rig.sink.signals == []


# --- F7.AC2: idempotency ------------------------------------------------------------------------------------------------------


def test_F7_AC2_the_same_fill_through_websocket_snapshot_and_resync_creates_one_signal(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    fill = mkfill(11)
    for _ in ("websocket", "snapshot", "rest resync"):
        rig.detector.on_fills(WALLET_A, [fill])
    assert [s.tid for s in rig.sink.signals] == [11]
    assert len(rig.ledger_signals()) == 1


def test_F7_AC2_a_duplicate_creates_no_signal_and_no_ledger_record_and_no_empty_delivery(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.feed([mkfill(1)])
    seq = rig.ledger.last_seq
    rig.feed([mkfill(1)])
    assert rig.ledger.last_seq == seq
    assert len(rig.sink.batches) == 1


def test_F7_AC2_duplicates_inside_one_batch_and_across_batches_count_once(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    got = rig.feed([mkfill(1), mkfill(1), mkfill(2), mkfill(1)])
    assert [s.tid for s in got] == [1, 2]
    assert [s.tid for s in rig.feed([mkfill(2), mkfill(3)])] == [3]


def test_F7_AC2_a_1000_event_fixture_with_30_percent_duplicates_yields_exactly_the_unique_count(
    rig_factory: Callable[..., Rig],
) -> None:
    rnd = random.Random(70)
    rig = rig_factory()
    unique = [mkfill(i, coin=("BTC", "ETH", "SOL")[i % 3]) for i in range(700)]
    events = list(unique) + [rnd.choice(unique) for _ in range(300)]
    rnd.shuffle(events)
    assert len(events) == 1000
    i = 0
    while i < len(events):
        n = rnd.randint(1, 20)
        rig.detector.on_fills(WALLET_A, events[i : i + n])
        i += n
    assert len(rig.sink.signals) == 700
    assert len({s.signal_id for s in rig.sink.signals}) == 700
    assert len(rig.ledger_signals()) == 700
    assert {s.tid for s in rig.sink.signals} == set(range(700))


def test_F7_AC2_the_same_tid_on_two_different_wallets_is_two_fills(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(follow=(WALLET_A, WALLET_B))
    rig.detector.on_fills(WALLET_A, [mkfill(5)])
    rig.detector.on_fills(WALLET_B, [mkfill(5)])
    assert [(s.wallet, s.tid) for s in rig.sink.signals] == [(WALLET_A, 5), (WALLET_B, 5)]
    assert rig.sink.signals[0].signal_id != rig.sink.signals[1].signal_id


def test_F7_AC2_fills_arriving_out_of_order_are_all_signalled_in_delivery_order(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    got = rig.feed([mkfill(9, time_ms=T0), mkfill(3, time_ms=T0 - 5000), mkfill(6, time_ms=T0 - 1000)])
    assert [s.tid for s in got] == [9, 3, 6]


def test_F7_AC2_signal_ids_are_deterministic_across_runs_and_unique_across_fills_and_legs(tmp_path: Path) -> None:
    fills = [mkfill(1), mkfill(2, side="A", sz="3", start="1"), mkfill(3, coin="ETH")]
    ids = []
    for name in ("one", "two"):
        base = tmp_path / name
        base.mkdir()
        rig = make_rig(base)
        try:
            ids.append([s.signal_id for s in rig.feed(fills)])
        finally:
            rig.ledger.close()
    assert ids[0] == ids[1]
    assert len(set(ids[0])) == 4 and all(isinstance(i, str) and i for i in ids[0])


def test_F7_AC2_after_a_restart_a_replayed_fill_is_still_a_duplicate(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    rig.feed([mkfill(1), mkfill(2, side="A", sz="3", start="1")])
    rig.ledger.close()
    from copytrade.core.clock import ClockSync
    from copytrade.ledger.store import Ledger
    from tests.signals.helpers import FakeOffsetSource, RecordingSignals

    ledger = Ledger.open(tmp_path / "ledger", clock=rig.clock)
    try:
        sink = RecordingSignals(ledger)
        sync = ClockSync.from_config(rig.cfg, clock=rig.clock, source=FakeOffsetSource(), alerts=rig.alerts)
        sync.tick()
        again = SignalDetector(config=rig.cfg, clock=rig.clock, sync=sync, ledger=ledger, sink=sink, alerts=rig.alerts)
        again.on_fills(WALLET_A, [mkfill(1), mkfill(2, side="A", sz="3", start="1")])  # a snapshot after the restart
        assert sink.signals == []
        again.on_fills(WALLET_A, [mkfill(3)])
        assert [s.tid for s in sink.signals] == [3]
    finally:
        ledger.close()


def test_F7_AC2_a_wallet_written_in_upper_case_shares_the_state_of_its_lower_case_form(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.detector.on_fills(WALLET_A.upper().replace("0X", "0x"), [mkfill(1)])
    rig.detector.on_fills(WALLET_A, [mkfill(1)])
    assert len(rig.sink.signals) == 1 and rig.sink.signals[0].wallet == WALLET_A
