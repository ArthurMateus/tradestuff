"""F12.AC2 stops, take-profit and the trailing stop: the pure rules and the placed orders."""

from __future__ import annotations

from decimal import Decimal as D

from hypothesis import given, settings
from hypothesis import strategies as st

from copytrade.core.domain import ActionKind
from copytrade.core.money import Price, Qty
from copytrade.hl.models import Candle
from copytrade.paper.types import StopIntent
from tests.paper.helpers import BASE, HOUR_MS
from tests.positions.conftest import NewRig
from tests.positions.helpers import fresh_rig, make_signal, pos


def bar(i: int, hi: str, lo: str, close: str, *, coin: str = "SOL") -> Candle:
    close_ms = BASE - 100 * HOUR_MS + (i + 1) * HOUR_MS
    return Candle(open_ms=close_ms - HOUR_MS, close_ms=close_ms, coin=coin, interval="1h", open=Price(close),
                  high=Price(hi), low=Price(lo), close=Price(close), volume=Qty("1"), trades=1)


# ---------------------------------------------------------------------------------------------- pure rules

def test_F12_AC2_atr_is_the_mean_true_range_over_the_period_with_gaps_counted() -> None:
    rules = pos("rules")
    bars = [bar(0, "101", "99", "100"), bar(1, "103", "102", "102.5"), bar(2, "102", "100", "101")]
    # true ranges: bar1 = max(1, |103-100|, |102-100|) = 3 ; bar2 = max(2, |102-102.5|, |100-102.5|) = 2.5
    assert rules.atr(bars, period=2, before_ms=bars[-1].close_ms) == D("2.75")


def test_F12_AC2_atr_needs_period_plus_one_closed_bars_and_ignores_later_bars() -> None:
    rules = pos("rules")
    bars = [bar(i, "101", "99", "100") for i in range(15)]
    assert rules.atr(bars, period=14, before_ms=bars[-1].close_ms) == D("2")
    assert rules.atr(bars[1:], period=14, before_ms=bars[-1].close_ms) is None  # 14 bars: one short
    bars.append(bar(15, "200", "0", "100"))
    assert rules.atr(bars, period=14, before_ms=bars[14].close_ms) == D("2")  # the later bar is not used


def test_F12_AC2_atr_of_zero_range_is_unusable() -> None:
    rules = pos("rules")
    flat = [bar(i, "100", "100", "100") for i in range(15)]
    assert rules.atr(flat, period=14, before_ms=flat[-1].close_ms) is None


def _trail(**kw: object) -> D:
    base: dict[str, object] = dict(is_long=True, current_stop_px=D("98.5"), entry_px=D("100"),
                                   initial_stop_px=D("98.5"), best_px=D("100"), atr=D("0.75"),
                                   trail_start_r=D("1"), trail_atr_mult=D("2"))
    base.update(kw)
    return pos("rules").trailed_stop(**base)  # type: ignore[no-any-return]


def test_F12_AC2_trail_starts_at_exactly_plus_trail_start_r() -> None:
    assert _trail(best_px=D("101.49")) == D("98.5")  # one tick below +1R: no trail
    assert _trail(best_px=D("101.5")) == D("100")  # exactly +1R: best - 2 x ATR
    assert _trail(best_px=D("101.51")) == D("100.01")


def test_F12_AC2_trail_for_shorts_is_the_mirror_image() -> None:
    short = dict(is_long=False, current_stop_px=D("101.5"), initial_stop_px=D("101.5"))
    assert _trail(best_px=D("98.51"), **short) == D("101.5")
    assert _trail(best_px=D("98.5"), **short) == D("100")


def test_F12_AC2_trail_never_loosens_when_best_distance_is_below_the_current_stop() -> None:
    assert _trail(current_stop_px=D("105"), best_px=D("106")) == D("105")
    assert _trail(is_long=False, current_stop_px=D("95"), initial_stop_px=D("101.5"), best_px=D("94")) == D("95")


_PX = st.integers(min_value=5_000, max_value=15_000).map(lambda c: D(c) / 100)


@settings(max_examples=10_000)
@given(path=st.lists(_PX, min_size=1, max_size=12), long=st.booleans(), start_r=st.sampled_from(["0.25", "1", "5"]),
       mult=st.sampled_from(["0.5", "2", "5"]))
def test_F12_AC2_stop_never_widens_over_random_paths(path: list[D], long: bool, start_r: str, mult: str) -> None:
    entry, dist = D("100"), D("1.5")
    stop = entry - dist if long else entry + dist
    best = entry
    for px in path:
        best = max(best, px) if long else min(best, px)
        new = _trail(is_long=long, current_stop_px=stop, entry_px=entry, initial_stop_px=entry - dist if long else
                     entry + dist, best_px=best, trail_start_r=D(start_r), trail_atr_mult=D(mult))
        assert new >= stop if long else new <= stop
        stop = new
    initial = entry - dist if long else entry + dist
    assert stop == initial or (stop < best if long else stop > best)


# ------------------------------------------------------------------------------------------ placed orders

def test_F12_AC2_initial_stop_is_placed_through_the_gate_after_the_entry_fills(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    (stop,) = [s for s in rig.active_stops(share.share_id) if s["kind"] == "sl"]
    assert (D(str(stop["trigger_px"])), D(str(stop["qty"])), stop["side"]) == (D("98.5"), D("1.00"), "sell")
    assert any(isinstance(intent, StopIntent) and intent.kind == "sl" for intent, _ in rig.authority.issued)


def test_F12_AC2_no_stop_is_sent_before_the_entry_fills(new_rig: NewRig) -> None:
    rig = new_rig()
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(1, ActionKind.OPEN, ts=now - 100))
    assert rig.records("paper_stop") == []


def test_F12_AC2_short_stop_is_above_the_entry_and_buys(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1, is_long=False)
    (stop,) = [s for s in rig.active_stops(share.share_id) if s["kind"] == "sl"]
    assert (D(str(stop["trigger_px"])), stop["side"]) == (D("101.5"), "buy")


def test_F12_AC2_stop_multiplier_comes_from_config(new_rig: NewRig) -> None:
    rig = new_rig(exits__stop_atr_mult=D("3"))
    assert rig.open_share(1).initial_stop_px == D("97.75")


def test_F12_AC2_atr_ignores_the_bar_still_forming_at_entry(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.candles.add_bar(Candle(open_ms=BASE, close_ms=BASE + HOUR_MS, coin="SOL", interval="1h", open=Price("100"),
                               high=Price("300"), low=Price("1"), close=Price("100"), volume=Qty("1"), trades=1))
    assert rig.open_share(1).initial_stop_px == D("98.5")


def test_F12_AC2_atr_uses_the_configured_interval_and_period(new_rig: NewRig) -> None:
    rig = new_rig(exits__atr_candle_interval="1m", exits__atr_period=5)
    rig.candles.bars.clear()
    for i in range(6):  # period + 1 closed 1m bars: exactly enough
        close_ms = BASE - (5 - i) * 60_000
        rig.candles.add_bar(Candle(open_ms=close_ms - 60_000, close_ms=close_ms, coin="SOL", interval="1m",
                                   open=Price("100"), high=Price("100.375"), low=Price("99.625"), close=Price("100"),
                                   volume=Qty("1"), trades=1))
    assert rig.open_share(1).initial_stop_px == D("98.5")
    assert {c[1] for c in rig.candles.calls} == {"1m"}


def test_F12_AC2_one_bar_short_of_the_period_skips_the_open(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.candles.set_flat("SOL", n=14)  # needs 15
    now = rig.xtime.now
    rig.book_at("SOL", "100", now + 1000)
    rig.feed(make_signal(1, ActionKind.OPEN, ts=now - 100))
    rig.step(now + 1000)
    assert rig.orders() == [] and rig.book.states() == ()
    assert [s["reason"] for s in rig.records("signal_skip")] == ["no_atr"]


def test_F12_AC2_candle_source_failure_skips_the_open_without_raising(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.candles.fail = True
    rig.feed(make_signal(1, ActionKind.OPEN, ts=rig.xtime.now - 100))
    assert rig.orders() == [] and rig.book.states() == ()
    assert [s["reason"] for s in rig.records("signal_skip")] == ["no_atr"]


def test_F12_AC2_take_profit_is_placed_for_the_tp_fraction_at_plus_tp_r(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    stops = {s["kind"]: s for s in rig.active_stops(share.share_id)}
    assert (D(str(stops["tp"]["trigger_px"])), D(str(stops["tp"]["qty"]))) == (D("103"), D("0.50"))
    assert D(str(stops["sl"]["qty"])) == D("1.00")


def test_F12_AC2_no_take_profit_when_disabled(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    assert [s["kind"] for s in rig.active_stops(share.share_id)] == ["sl"]


def test_F12_AC2_take_profit_part_of_exactly_ten_dollars_is_placed(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.leader_state.account_value = D("600")
    share = rig.open_share(1, notional="40")  # mirror = 40 / 600 x 300 = $20 -> 0.20 SOL
    assert share.qty == D("0.20")
    assert {s["kind"] for s in rig.active_stops(share.share_id)} == {"sl", "tp"}
    (tp,) = [s for s in rig.active_stops(share.share_id) if s["kind"] == "tp"]
    assert D(str(tp["qty"])) == D("0.10")


def test_F12_AC2_take_profit_part_below_ten_dollars_is_skipped_and_ledgered(new_rig: NewRig) -> None:
    rig = new_rig()
    rig.leader_state.account_value = D("600")
    share = rig.open_share(1, notional="38")  # $19 -> 0.19 SOL; half rounds down to 0.09 = $9
    assert share.qty == D("0.19")
    assert [s["kind"] for s in rig.active_stops(share.share_id)] == ["sl"]
    assert "tp_skipped" in [e["event"] for e in rig.share_events(share.share_id)]


def test_F12_AC2_take_profit_fill_reduces_the_share_and_rearms_the_stop_for_the_rest(new_rig: NewRig) -> None:
    rig = new_rig(exits__trail_start_r=D("5"))
    share = rig.open_share(1)
    rig.mark_and_fill("SOL", "103")
    after = rig.book.state(share.share_id)
    assert (after.status, after.qty, after.tp_done) == ("open", D("0.50"), True)
    assert rig.held("SOL").share_qtys == (D("0.50"),)
    (sl,) = rig.active_stops(share.share_id)
    assert (sl["kind"], D(str(sl["qty"])), D(str(sl["trigger_px"]))) == ("sl", D("0.50"), D("98.5"))
    assert after.open_risk_usd == D("0.75")
    assert "tp_filled" in [e["event"] for e in rig.share_events(share.share_id)]
    assert [s.share_id for s in rig.book.open_shares()] == [share.share_id]


def test_F12_AC2_stop_loss_fill_closes_the_share_and_frees_the_book(new_rig: NewRig) -> None:
    rig = new_rig()
    share = rig.open_share(1)
    rig.mark_and_fill("SOL", "98.4")
    assert rig.book.state(share.share_id).status == "closed"
    assert rig.book.open_shares() == ()
    assert rig.env.broker.position("SOL") is None
    assert rig.active_stops() == []  # the take-profit left behind is cancelled


def test_F12_AC2_trailing_stop_follows_the_best_mark_through_the_gate(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    issued = len(rig.authority.issued)
    rig.mark("SOL", "104")
    assert rig.book.state(share.share_id).current_stop_px == D("102.5")
    (sl,) = rig.active_stops(share.share_id)
    assert (D(str(sl["trigger_px"])), D(str(sl["qty"]))) == (D("102.5"), D("1.00"))
    assert len(rig.authority.issued) > issued  # the new stop went through the gate
    rig.mark("SOL", "103")  # a pull-back never lowers it
    assert rig.book.state(share.share_id).current_stop_px == D("102.5")
    assert D(str(rig.active_stops(share.share_id)[0]["trigger_px"])) == D("102.5")


def test_F12_AC2_trailing_starts_at_plus_one_r_not_below(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    rig.mark("SOL", "101.49")
    assert rig.book.state(share.share_id).current_stop_px == D("98.5")
    rig.mark("SOL", "101.5")
    assert rig.book.state(share.share_id).current_stop_px == D("100")


def test_F12_AC2_short_trailing_stop_only_moves_down(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1, is_long=False)
    rig.mark("SOL", "96")
    assert rig.book.state(share.share_id).current_stop_px == D("97.5")
    rig.mark("SOL", "99")
    assert rig.book.state(share.share_id).current_stop_px == D("97.5")


def test_F12_AC2_trailed_stop_triggers_and_closes_the_share_in_profit(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    rig.mark("SOL", "104")
    rig.mark_and_fill("SOL", "102.4")
    assert rig.book.state(share.share_id).status == "closed"
    (trade,) = rig.env.trades()
    assert trade.share_id == share.share_id


def test_F12_AC2_trailing_never_needs_the_candle_source(new_rig: NewRig) -> None:
    rig = new_rig(exits__tp_enabled=False)
    share = rig.open_share(1)
    rig.candles.fail = True
    rig.mark("SOL", "104")
    assert rig.book.state(share.share_id).current_stop_px == D("102.5")


@settings(max_examples=25)
@given(path=st.lists(st.integers(min_value=9_000, max_value=11_500).map(lambda c: D(c) / 100), min_size=1,
                     max_size=8), long=st.booleans())
def test_F12_AC2_the_stored_stop_never_widens_through_the_real_stack(path: list[D], long: bool) -> None:
    with fresh_rig(exits__tp_enabled=False) as rig:
        share = rig.open_share(1, is_long=long)
        last = share.current_stop_px
        for px in path:
            rig.env.flat_book("SOL", rig.xtime.now + 1000, str(px))
            rig.mark("SOL", str(px))
            state = rig.book.state(share.share_id)
            if state.status != "open":
                break
            assert state.current_stop_px >= last if long else state.current_stop_px <= last
            last = state.current_stop_px
            rig.step(rig.xtime.now + 1000)


