"""Trading invariants for F12 (A1 chokepoint, A2 fail closed, A5 idempotency, A6 Decimal, A8 rejects) and nasty cases."""

from __future__ import annotations

import re
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from copytrade.core.domain import ActionKind
from tests.positions.conftest import NewRig
from tests.positions.helpers import SEC, WALLET_A, make_signal

SRC = Path(__file__).resolve().parents[2] / "src" / "copytrade" / "positions"


def sources() -> dict[str, str]:
    files = sorted(SRC.glob("*.py"))
    assert files, "src/copytrade/positions does not exist yet"
    return {f.name: f.read_text(encoding="utf-8") for f in files}


def test_F12_A1_the_package_never_reaches_the_broker_around_the_gate() -> None:
    for name, text in sources().items():
        direct = re.sub(r"\b[\w.]*gate[\w.]*\.(submit|place_stop)\(", "", text)  # calls on the risk gate are the way
        for banned in (".submit(", ".place_stop(", ".issue(", "GateAuthority", "GateToken"):
            assert banned not in direct, f"{name} uses {banned}: every order must go through the risk gate"


def test_F12_A6_the_package_uses_no_floats_for_money() -> None:
    for name, text in sources().items():
        assert "float(" not in text and ": float" not in text and "-> float" not in text, name


def test_F12_A1_every_order_and_stop_a_lifecycle_produces_carries_a_gate_token(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    rig.mark("SOL", "104")
    now = rig.xtime.now
    rig.book_at("SOL", "104", now + 1000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 100))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"
    sent = len(rig.records("paper_order")) + len(rig.records("paper_stop"))
    assert sent == len(rig.authority.issued) > 3


def test_F12_A2_stop_on_or_below_zero_is_refused_before_any_order(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.env.flat_book("SOL", rig.xtime.now + 1000, "1")
    rig.feed(make_signal(1, ActionKind.OPEN, size="500", px="1", ts=rig.xtime.now - 100))  # 2 x ATR = 1.5 > price
    assert rig.orders() == [] and rig.book.states() == ()
    assert [s["reason"] for s in rig.records("signal_skip")] == ["invalid_stop"]


def test_F12_A8_entry_rejected_at_fill_time_leaves_no_share_and_no_stop(new_rig: NewRig) -> None:
    rig = new_rig()
    now = rig.xtime.now
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))  # no book at all: rejected at the fill
    rig.step(now + 6001)
    assert rig.book.open_shares() == ()
    assert rig.share_of(WALLET_A, "SOL") is None
    assert rig.records("paper_stop") == []
    rejected = [e for e in rig.share_events() if e["event"] == "entry_rejected"]
    assert len(rejected) == 1 and rejected[0]["reason"] == "no_book"


@pytest.mark.parametrize("fraction", [None, "0", "-0.1", "1.01"])
def test_F12_A2_malformed_reduce_fraction_is_skipped_and_alerted_never_traded(
    new_rig: NewRig, fraction: str | None
) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    orders = len(rig.orders())
    rig.feed(make_signal(2, ActionKind.REDUCE, size="1", pre="5", post="4", fraction=fraction, ts=rig.xtime.now - 100))
    assert len(rig.orders()) == orders and rig.book.state(share.share_id).qty == share.qty
    assert [s["reason"] for s in rig.records("signal_skip")] == ["invalid_signal"]
    assert "bad_signal" in rig.alert_kinds()


def test_F12_AC3_reduce_fraction_of_exactly_one_closes_the_share(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.REDUCE, size="5", pre="5", post="0.0", fraction="1", ts=now - 100))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"


def test_F12_A2_a_failing_alert_sink_never_blocks_an_exit_or_the_missed_exit_record(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)

    def boom(alert: Any) -> None:
        raise OSError("telegram down")

    rig.env.alerts.send = boom  # type: ignore[method-assign]
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(2, ActionKind.CLOSE, ts=now - 61 * SEC))
    rig.step(now + 1000)
    assert rig.book.state(share.share_id).status == "closed"
    assert len(rig.records("missed_exit")) == 1 and len(rig.records("go_live_blocker")) == 1


def test_F12_A2_stop_is_never_wider_than_the_stored_initial_stop_after_candles_change(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    rig.candles.set_flat("SOL", tr=D("20"))  # a volatility spike after entry must not move the stored stop
    rig.mark("SOL", "100.1")
    assert rig.book.state(share.share_id).current_stop_px == D("98.5")
    assert rig.book.state(share.share_id).initial_stop_px == D("98.5")


def test_F12_A5_the_same_signal_batch_replayed_after_the_fill_sends_nothing_new(new_rig: NewRig) -> None:
    rig = new_rig()
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    opening = make_signal(1, ActionKind.OPEN, size="5", ts=now - 100)
    rig.feed(opening)
    rig.step(now + 1000)
    before = (len(rig.orders()), len(rig.records("paper_stop")))
    rig.feed(opening)  # a reconnect replays the open
    rig.step(now + 2000)
    assert (len(rig.orders()), len(rig.records("paper_stop"))) == before
    assert len(rig.book.states()) == 1


def test_F12_A8_a_leader_signal_for_a_coin_with_a_pending_entry_is_not_double_sent(new_rig: NewRig) -> None:
    rig = new_rig()
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(1, ActionKind.OPEN, size="5", ts=now - 100))
    rig.feed(make_signal(2, ActionKind.ADD, size="2.5", pre="5", post="7.5", ts=now - 100))  # before the open filled
    rig.step(now + 1000)
    share = rig.share_of(WALLET_A, "SOL")
    assert share.qty <= D("1.00") + D("0.50")
    assert len([o for o in rig.orders() if o["action"] in ("open", "add")]) <= 2
    assert rig.held("SOL").share_qtys == (share.qty,)  # the book equals the broker, whatever was sent
