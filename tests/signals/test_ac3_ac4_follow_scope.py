"""F7.AC3 (pre-existing positions) and F7.AC4 (scope).

Spec: 04-spec.md F7.AC3, F7.AC4, §2 F2.AC2 outcomes ``pre_existing`` and ``out_of_scope`` (logged, never traded),
§3.5 ``markets.allowed_dexes``, invariant C4 (never leave an orphan; never trade what we did not copy from the start).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from copytrade.core.clock import ClockSync
from copytrade.core.domain import ActionKind
from copytrade.hl.errors import HlRequestError
from copytrade.ledger.store import Ledger
from copytrade.signals.detector import SignalDetector
from copytrade.signals.models import OUT_OF_SCOPE, PRE_EXISTING, Signal, WalletNotFollowedError
from tests.signals.helpers import (
    T0,
    WALLET_A,
    WALLET_B,
    FakeOffsetSource,
    Rig,
    RecordingSignals,
    make_rig,
    mkfill,
    state,
)

pytestmark = pytest.mark.unit


def outcomes(signals: Sequence[Signal]) -> list[str | None]:
    return [s.outcome for s in signals]


# --- F7.AC3 -----------------------------------------------------------------------------------------------------------------


def test_F7_AC3_every_fill_on_a_coin_held_at_follow_time_is_pre_existing_until_the_wallet_is_flat_on_it(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory(held={"BTC": "2"})
    got = rig.feed(
        [
            mkfill(1, side="B", sz="1", start="2"),  # add
            mkfill(2, side="A", sz="1", start="3"),  # reduce
            mkfill(3, side="A", sz="2", start="2"),  # close: still the pre-existing position
        ]
    )
    assert outcomes(got) == [PRE_EXISTING] * 3
    assert [s.action for s in got] == [ActionKind.ADD, ActionKind.REDUCE, ActionKind.CLOSE]  # still classified, just not traded
    nxt = rig.feed([mkfill(4, side="B", sz="1", start="0")])
    assert outcomes(nxt) == [None] and nxt[0].action is ActionKind.OPEN  # the next open is a normal signal


def test_F7_AC3_a_coin_the_wallet_did_not_hold_at_follow_time_is_a_normal_signal(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(held={"BTC": "2"})
    got = rig.feed([mkfill(1, coin="ETH", side="B", sz="1", start="0"), mkfill(2, coin="BTC", side="B", sz="1", start="2")])
    assert outcomes(got) == [None, PRE_EXISTING]


def test_F7_AC3_a_short_held_at_follow_time_is_pre_existing_too(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(held={"ETH": "-3"})
    got = rig.feed([mkfill(1, coin="ETH", side="B", sz="1", start="-3"), mkfill(2, coin="ETH", side="B", sz="2", start="-2")])
    assert outcomes(got) == [PRE_EXISTING, PRE_EXISTING]
    assert outcomes(rig.feed([mkfill(3, coin="ETH", side="A", sz="1", start="0")])) == [None]


def test_F7_AC3_a_zero_size_entry_in_the_follow_time_state_is_not_a_held_position(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(held={"BTC": "0"})
    assert outcomes(rig.feed([mkfill(1, coin="BTC", side="B", sz="1", start="0")])) == [None]


def test_F7_AC3_a_flip_of_a_pre_existing_position_closes_it_as_pre_existing_and_opens_a_normal_signal(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory(held={"BTC": "1"})
    got = rig.feed([mkfill(1, side="A", sz="3", start="1")])
    assert [(s.action, s.outcome) for s in got] == [(ActionKind.CLOSE, PRE_EXISTING), (ActionKind.OPEN, None)]


def test_F7_AC3_pre_existing_state_is_per_wallet(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(follow=(WALLET_A,), held={"BTC": "2"})
    rig.detector.begin_follow(WALLET_B, state({}), T0)
    a = rig.feed([mkfill(1, side="B", sz="1", start="2")], WALLET_A)
    b = rig.feed([mkfill(2, side="B", sz="1", start="0")], WALLET_B)
    assert outcomes(a) == [PRE_EXISTING] and outcomes(b) == [None]


def test_F7_AC3_pre_existing_signals_are_ledgered_and_delivered_so_they_can_be_logged_as_decisions(
    rig_factory: Callable[..., Rig],
) -> None:
    rig = rig_factory(held={"BTC": "2"})
    rig.feed([mkfill(1, side="B", sz="1", start="2")])
    (p,) = rig.ledger_signals()
    assert p["outcome"] == "pre_existing" and p["tid"] == 1
    assert [s.outcome for s in rig.sink.signals] == [PRE_EXISTING]


def test_F7_AC3_fills_for_a_wallet_that_was_never_followed_are_refused_loudly(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    with pytest.raises(WalletNotFollowedError):
        rig.detector.on_fills(WALLET_B, [mkfill(1)])
    assert rig.sink.signals == [] and rig.ledger_signals() == []


def test_F7_AC3_begin_follow_is_a_no_op_for_a_wallet_already_followed_and_end_follow_resets_it(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(held={"BTC": "2"})
    rig.detector.begin_follow(WALLET_A, state({}), T0 + 5000)  # a second call must not erase the pre-existing coin
    assert outcomes(rig.feed([mkfill(1, side="B", sz="1", start="2")])) == [PRE_EXISTING]
    rig.detector.end_follow(WALLET_A)
    with pytest.raises(WalletNotFollowedError):
        rig.detector.on_fills(WALLET_A, [mkfill(2)])
    rig.detector.begin_follow(WALLET_A, state({}), T0 + 9000)  # a fresh follow with nothing held
    assert outcomes(rig.feed([mkfill(3, side="B", sz="1", start="2")])) == [None]


def test_F7_AC3_end_follow_of_an_unknown_wallet_is_ignored_and_a_bad_address_is_rejected(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.detector.end_follow(WALLET_B)
    with pytest.raises(HlRequestError):
        rig.detector.begin_follow("not-a-wallet", state({}), T0)


def test_F7_AC3_follow_start_and_end_are_ledgered(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(held={"BTC": "2"})
    rig.detector.end_follow(WALLET_A)
    kinds = [r.kind for r in rig.ledger.records()]
    assert kinds == ["follow_started", "follow_ended"]


def restarted(rig: Rig, tmp_path: Path) -> tuple[SignalDetector, RecordingSignals, Ledger]:
    rig.ledger.close()
    ledger = Ledger.open(tmp_path / "ledger", clock=rig.clock)
    sink = RecordingSignals(ledger)
    sync = ClockSync.from_config(rig.cfg, clock=rig.clock, source=FakeOffsetSource(), alerts=rig.alerts)
    sync.tick()
    return SignalDetector(config=rig.cfg, clock=rig.clock, sync=sync, ledger=ledger, sink=sink, alerts=rig.alerts), sink, ledger


def test_F7_AC3_the_pre_existing_state_survives_a_restart_including_progress_towards_flat(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, held={"BTC": "4", "ETH": "1"})
    rig.feed([mkfill(1, side="A", sz="1", start="4"), mkfill(2, coin="ETH", side="A", sz="1", start="1")])  # ETH is flat now
    detector, sink, ledger = restarted(rig, tmp_path)
    try:
        detector.on_fills(WALLET_A, [mkfill(3, side="A", sz="1", start="3"), mkfill(4, coin="ETH", side="B", sz="1", start="0")])
        assert outcomes(sink.signals) == [PRE_EXISTING, None]  # BTC is still the old position, ETH was flat before the restart
    finally:
        ledger.close()


def test_F7_AC3_a_followed_wallet_is_still_followed_after_a_restart(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    detector, sink, ledger = restarted(rig, tmp_path)
    try:
        detector.on_fills(WALLET_A, [mkfill(1)])
        assert len(sink.signals) == 1
    finally:
        ledger.close()


# --- F7.AC4 -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("coin", ["xyz:AAPL", "flx:TSLA", "vntl:ANTHROPIC", "a:b"])
def test_F7_AC4_fills_on_hip3_dex_markets_are_out_of_scope(rig_factory: Callable[..., Rig], coin: str) -> None:
    rig = rig_factory()
    (s,) = rig.feed([mkfill(1, coin=coin)])
    assert s.outcome == OUT_OF_SCOPE == "out_of_scope"
    assert s.coin == coin and s.action is None
    assert rig.ledger_signals()[0]["outcome"] == "out_of_scope"


@pytest.mark.parametrize("coin", ["@1", "@107", "PURR/USDC", "HYPE/USDC"])
def test_F7_AC4_spot_fills_are_out_of_scope_whatever_their_dir_says(rig_factory: Callable[..., Rig], coin: str) -> None:
    rig = rig_factory()
    got = rig.feed([mkfill(1, coin=coin, dir="Buy"), mkfill(2, coin=coin, side="A", dir="Sell")])
    assert outcomes(got) == [OUT_OF_SCOPE, OUT_OF_SCOPE]  # not "unparseable": scope is decided before dir


@pytest.mark.parametrize("coin", ["BTC", "ETH", "SOL", "kPEPE", "DOGE", "HYPE", "1000SHIB"])
def test_F7_AC4_core_perps_are_in_scope(rig_factory: Callable[..., Rig], coin: str) -> None:
    rig = rig_factory()
    assert outcomes(rig.feed([mkfill(1, coin=coin)])) == [None]


def test_F7_AC4_an_out_of_scope_fill_gives_exactly_one_signal_even_if_it_looks_like_a_flip(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    got = rig.feed([mkfill(1, coin="xyz:AAPL", side="A", sz="3", start="1")])
    assert len(got) == 1 and got[0].outcome == OUT_OF_SCOPE


def test_F7_AC4_scope_wins_over_pre_existing_and_does_not_disturb_it(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory(held={"BTC": "2"})
    got = rig.feed([mkfill(1, coin="xyz:BTC", side="B", sz="1", start="2"), mkfill(2, coin="BTC", side="B", sz="1", start="2")])
    assert outcomes(got) == [OUT_OF_SCOPE, PRE_EXISTING]


def test_F7_AC4_out_of_scope_fills_are_still_deduplicated(rig_factory: Callable[..., Rig]) -> None:
    rig = rig_factory()
    rig.feed([mkfill(1, coin="xyz:AAPL")])
    assert rig.feed([mkfill(1, coin="xyz:AAPL")]) == []
    assert len(rig.ledger_signals()) == 1
