"""Blow-up detectors BU1-BU8 (F5.AC4), edge-hypothesis 10.5.

Every rule is a strict comparison as written in 10.5, so a value exactly at its threshold does not fire. A detector
never fires below its minimum sample, and one whose input is missing does not fire (the gates already fail closed on
missing metrics). Ratios of counts and sums are compared by cross-multiplication, so they are exact.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

from copytrade.core.config import Config
from copytrade.scoring.models import Metrics, TripRecord
from copytrade.scoring.series import mean, median

_ZERO = Decimal(0)


def _bu1_martingale(records: Sequence[TripRecord], cfg: Config) -> bool:
    adds = sum(r.trip.adds for r in records)
    losing = sum(r.trip.adds_while_losing for r in records)
    return bool(adds >= cfg["blowup.min_adds"] and losing > cfg["blowup.max_adds_while_losing_share"] * adds)


def _bu2_size_up_after_losses(ordered: Sequence[TripRecord], cfg: Config) -> bool:
    after_loss: list[Decimal] = []
    after_win: list[Decimal] = []
    for previous, current in pairwise(ordered):
        av = current.av_at_open
        if av is None or av <= 0 or previous.trip.net_pnl == 0:
            continue
        size = current.trip.peak_notional / av
        (after_loss if previous.trip.net_pnl < 0 else after_win).append(size)
    if min(len(after_loss), len(after_win)) < cfg["blowup.min_each"]:
        return False
    loss_median, win_median = median(after_loss), median(after_win)
    return (
        loss_median is not None
        and win_median is not None
        and loss_median > cfg["blowup.max_size_after_loss_ratio"] * win_median
    )


def _bu3_short_volatility(records: Sequence[TripRecord], cfg: Config) -> bool:
    pnls = [r.trip.net_pnl for r in records]
    wins = [x for x in pnls if x > 0]
    losses = [-x for x in pnls if x < 0]
    mean_win, mean_loss = mean(wins), mean(losses)
    if mean_win is None or mean_loss is None:
        return False
    return bool(
        len(wins) > cfg["blowup.skew_win_rate"] * len(pnls) and mean_loss > cfg["blowup.skew_loss_mult"] * mean_win
    )


def _bu4_tail_loss(records: Sequence[TripRecord], cfg: Config) -> bool:
    losses = [-r.trip.net_pnl for r in records if r.trip.net_pnl < 0]
    if len(losses) < cfg["blowup.min_losses"]:
        return False
    typical = median(losses)
    return typical is not None and max(losses) > cfg["blowup.max_worst_to_median_loss"] * typical


def _bu5_hidden_drawdown(m: Metrics, cfg: Config) -> bool:
    if m.max_dd_mtm is None or m.max_dd_realised is None:
        return False
    return bool(
        m.max_dd_mtm > cfg["blowup.hidden_dd_mult"] * m.max_dd_realised and m.max_dd_mtm > cfg["blowup.hidden_dd_floor"]
    )


def detect_blowups(records: Sequence[TripRecord], m: Metrics, *, cfg: Config) -> tuple[str, ...]:
    """Return the sorted ids (``"BU1"``..``"BU8"``) of every detector that fires, at the section 10.5 boundaries.

    A detector never fires below its minimum sample. Trips are taken in ``open_ms`` order. BU6 fires on a liquidated
    trip or on any liquidation fill in the window (``Metrics.liquidation_fills``, which also covers a position that
    is still open), unless ``blowup.any_liquidation`` is off.
    """
    ordered = sorted(records, key=lambda r: (r.trip.open_ms, r.trip.close_ms or 0))
    fired = {
        "BU1": _bu1_martingale(ordered, cfg),
        "BU2": _bu2_size_up_after_losses(ordered, cfg),
        "BU3": _bu3_short_volatility(ordered, cfg),
        "BU4": _bu4_tail_loss(ordered, cfg),
        "BU5": _bu5_hidden_drawdown(m, cfg),
        "BU6": cfg["blowup.any_liquidation"] and (m.liquidation_fills > 0 or any(r.trip.liquidated for r in ordered)),
        "BU7": m.eff_leverage_median is not None and m.eff_leverage_median > cfg["blowup.max_median_eff_leverage"],
        "BU8": m.open_loss_fraction is not None and m.open_loss_fraction > cfg["blowup.max_open_unrealized_loss"],
    }
    return tuple(bu for bu, hit in fired.items() if hit)
