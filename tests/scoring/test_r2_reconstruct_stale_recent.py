"""F5 round 2: reconstruct edges (AC2), stale-input marking (AC3/AC7) and the recent-Sharpe hole (AC5)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from copytrade.core.config import Config
from copytrade.scoring.cycle import STALE_REASON, score_wallet
from copytrade.scoring.reconstruct import reconstruct
from tests.scoring import wallets as W
from copytrade.scoring.models import Fill, WalletInputs, WalletScore
from tests.scoring.helpers import DAY, PAPER_COSTS, fill, funding, make_cfg

pytestmark = pytest.mark.unit
D = Decimal


# --- reconstruct: the funding payment on the flip millisecond -----------------------------------------------------------
def _flip_fills() -> list[Fill]:
    # long 10 @100 at 1000; at 2000 sell 25 @102 (closes the long: closedPnl 20; opens a short of 15); buy 15 @101 at 3000
    return [
        fill(1000, "BTC", "B", 10, 100, 0),
        fill(2000, "BTC", "A", 25, 102, 10, pnl=20),
        fill(3000, "BTC", "B", 15, 101, -15, pnl=15),
    ]


def test_F5_AC2_funding_on_the_flip_millisecond_belongs_to_the_closing_trip() -> None:
    r = reconstruct(_flip_fills(), [funding(2000, "BTC", 5)])
    closing, opened = r.closed
    assert closing.close_ms == 2000 and closing.net_pnl == D(15)  # 20 - 5
    assert opened.open_ms == 2000 and opened.net_pnl == D(15)  # not charged twice


def test_F5_AC2_funding_after_the_flip_millisecond_belongs_to_the_new_trip() -> None:
    r = reconstruct(_flip_fills(), [funding(2001, "BTC", 5)])
    closing, opened = r.closed
    assert closing.net_pnl == D(20) and opened.net_pnl == D(10)


def test_F5_AC2_funding_before_the_flip_millisecond_belongs_to_the_closing_trip_only() -> None:
    r = reconstruct(_flip_fills(), [funding(1999, "BTC", 5)])
    closing, opened = r.closed
    assert closing.net_pnl == D(15) and opened.net_pnl == D(15)


def test_F5_AC2_funding_on_the_closing_millisecond_of_an_ordinary_trip_is_charged_to_it() -> None:
    fills = [fill(1000, "BTC", "B", 10, 100, 0), fill(2000, "BTC", "A", 10, 102, 10, pnl=20)]
    (only,) = reconstruct(fills, [funding(2000, "BTC", 3), funding(1000, "BTC", 2), funding(2001, "BTC", 99)]).closed
    assert only.net_pnl == D(15)  # 20 - 3 (at close) - 2 (at open); the payment after the close is not its


def test_F5_AC2_a_flip_millisecond_funding_is_charged_once_for_both_the_long_to_short_and_short_to_long_flip() -> None:
    fills = [
        fill(1000, "ETH", "A", 10, 100, 0),
        fill(2000, "ETH", "B", 25, 98, -10, pnl=20),
        fill(3000, "ETH", "A", 15, 99, 15, pnl=-15),
    ]
    closing, opened = reconstruct(fills, [funding(2000, "ETH", 7)]).closed
    assert closing.net_pnl == D(13) and opened.net_pnl == D(-15)


# --- reconstruct: an add at exactly the average price is not an add while losing --------------------------------------------
def test_F5_AC2_a_long_add_at_exactly_the_average_price_is_not_losing() -> None:
    fills = [
        fill(1000, "BTC", "B", 10, 100, 0),
        fill(2000, "BTC", "B", 10, 100, 10),
        fill(3000, "BTC", "A", 20, 100, 20),
    ]
    (rt,) = reconstruct(fills, []).closed
    assert rt.adds == 1 and rt.adds_while_losing == 0


def test_F5_AC2_a_short_add_at_exactly_the_average_price_is_not_losing() -> None:
    fills = [
        fill(1000, "BTC", "A", 10, 100, 0),
        fill(2000, "BTC", "A", 10, 100, -10),
        fill(3000, "BTC", "B", 20, 100, -20),
    ]
    (rt,) = reconstruct(fills, []).closed
    assert rt.adds == 1 and rt.adds_while_losing == 0


def test_F5_AC2_an_add_at_the_moved_average_is_not_losing_but_the_add_below_it_was() -> None:
    fills = [
        fill(1000, "BTC", "B", 10, 100, 0),
        fill(2000, "BTC", "B", 10, 98, 10),  # below 100: losing; average becomes 99
        fill(3000, "BTC", "B", 10, 99, 20),  # exactly the average: not losing
        fill(4000, "BTC", "A", 30, 99, 30),
    ]
    (rt,) = reconstruct(fills, []).closed
    assert rt.adds == 2 and rt.adds_while_losing == 1


def test_F5_AC2_a_long_add_one_tick_below_the_average_is_losing_and_one_tick_above_is_not() -> None:
    def adds(px: str) -> tuple[int, int]:
        (rt,) = reconstruct(
            [fill(1000, "BTC", "B", 10, 100, 0), fill(2000, "BTC", "B", 10, px, 10), fill(3000, "BTC", "A", 20, 100, 20)], []
        ).closed
        return rt.adds, rt.adds_while_losing

    assert adds("99.99") == (1, 1) and adds("100.01") == (1, 0)


# --- stale input: a fetch time after t is stale ------------------------------------------------------------------------------
ADDR = "0xaaa0000000000000000000000000000000000009"


def _score(w: WalletInputs, cfg: Config) -> WalletScore:
    return score_wallet(w, cfg=cfg, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)


def test_F5_AC7_the_fixture_wallet_is_eligible_and_fresh(cfg_permissive: Config) -> None:
    s = _score(W.healthy(ADDR), cfg_permissive)
    assert s.eligible and STALE_REASON not in s.reasons


@pytest.mark.parametrize("field", ["fills_fetched_ms", "candles_fetched_ms"])
def test_F5_AC7_a_fills_or_candles_fetch_time_after_t_marks_the_wallet_stale(cfg_permissive: Config, field: str) -> None:
    w = replace(W.healthy(ADDR), **{field: W.T + 1})
    s = _score(w, cfg_permissive)
    assert s.eligible is False and s.reasons[0] == STALE_REASON and s.score is None and s.components is None


@pytest.mark.parametrize("field", ["fills_fetched_ms", "candles_fetched_ms"])
def test_F5_AC7_a_fills_or_candles_fetch_exactly_at_t_is_fresh(cfg_permissive: Config, field: str) -> None:
    s = _score(replace(W.healthy(ADDR), **{field: W.T}), cfg_permissive)
    assert s.eligible and STALE_REASON not in s.reasons


@pytest.mark.parametrize("field", ["fills_fetched_ms", "candles_fetched_ms"])
def test_F5_AC7_a_fetch_far_in_the_future_is_stale(cfg_permissive: Config, field: str) -> None:
    s = _score(replace(W.healthy(ADDR), **{field: W.T + 10**12}), cfg_permissive)
    assert STALE_REASON in s.reasons and not s.eligible


# --- recent_sr None on an otherwise eligible wallet --------------------------------------------------------------------------
QUIET = {**W.PERMISSIVE_CFG, "gate.min_fill_span_days": 30}  # 55 trips over 54 days, none in the last 30


def _quiet_recent_wallet() -> WalletInputs:
    """80-day healthy history cut to days 215..269: no fills (so a zero return every day) in the last 30 days."""
    w = W.healthy(ADDR)
    return replace(w, fills=tuple(f for f in w.fills if f.time < 270 * DAY))


def test_F5_AC5_recent_sr_none_wallet_is_eligible_with_its_metric_kept_none(tmp_path: Path) -> None:
    s = _score(_quiet_recent_wallet(), make_cfg(tmp_path, **QUIET))
    assert s.metrics is not None and s.metrics.recent_sr is None
    assert s.eligible, s.reasons
    assert s.components is not None


def test_F5_AC5_recent_sr_none_scores_zero_on_that_component_at_the_default_anchor(tmp_path: Path) -> None:
    s = _score(_quiet_recent_wallet(), make_cfg(tmp_path, **QUIET))
    assert s.components is not None and s.components.u["recent_sr"] == D(0)


def test_F5_AC5_recent_sr_none_scores_zero_on_that_component_even_when_the_anchor_lo_is_negative(tmp_path: Path) -> None:
    """INTENDED TO FAIL until the developer sets u = 0 explicitly: x = 0 gives u = (0 - lo) / (hi - lo) = 0.5 at lo = -1.

    "No measurable recent variance" is the worst outcome for this component, not the neutral one, whatever the anchors.
    """
    cfg = make_cfg(
        tmp_path,
        **{**QUIET, "score.anchors.recent_sr.lo": "-1", "score.anchors.recent_sr.hi": "1"},
    )
    s = _score(_quiet_recent_wallet(), cfg)
    assert s.metrics is not None and s.metrics.recent_sr is None and s.eligible, s.reasons
    assert s.components is not None and s.components.u["recent_sr"] == D(0)


def test_F5_AC5_recent_sr_none_gives_the_same_score_as_the_weighted_sum_without_that_component(tmp_path: Path) -> None:
    """INTENDED TO FAIL with the negative anchor until the developer sets u = 0 explicitly (the score is inflated)."""
    cfg = make_cfg(tmp_path, **{**QUIET, "score.anchors.recent_sr.lo": "-1", "score.anchors.recent_sr.hi": "1"})
    s = _score(_quiet_recent_wallet(), cfg)
    assert s.components is not None
    c = s.components
    others = sum((cfg[f"score.weights.{n}"] * c.u[n] for n in c.u if n != "recent_sr"), D(0))
    assert c.score == others
