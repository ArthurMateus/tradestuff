"""R4.AC4 [unit]: trips in a coin WITHOUT bars do not count toward the copy-R shrinkage n (CTO ruling on R4.AC3).

``replay_r`` is None for such a trip, so it has no R. The shrinkage of ``copy_mean_r`` must use the MEASURED trips (those
with an R), so confidence matches evidence. G2's ``n_rt`` gate keeps its definition (all closed trips). No config key.

(a) a wallet with extra zero-P&L trips in a bar-less coin scores exactly like the same wallet without them;
(b) a wallet none of whose trips can be measured stays ineligible through the existing gates (G10, G12), no new rule;
(c) golden values from the current source for wallets with every bar present (must not change).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from copytrade.core.config import Config
from copytrade.scoring.cycle import score_wallet
from copytrade.scoring.models import WalletInputs
from tests.scoring import wallets as W
from tests.scoring.helpers import H, PAPER_COSTS, round_trip_fills

D = Decimal
A = W.HIGH_WALLET


def one(cfg: Config, w: WalletInputs):  # type: ignore[no-untyped-def]
    return score_wallet(w, cfg=cfg, t_ms=W.T, costs=PAPER_COSTS, p95_latency_s=W.P95_LATENCY_S)


def with_barless_trips(w: WalletInputs, n: int, coin: str = "SOL") -> WalletInputs:
    """``n`` flat (zero P&L, zero fee) closed round trips in ``coin``, which has no bars in the wallet's inputs."""
    extra = []
    for k in range(n):
        extra += round_trip_fills(W._d(216 + k * 3, 5 * H), 2 * H, coin=coin, sz=10, px=100, exit_px=100, fee=0)
    assert coin not in w.candles_1h
    return replace(w, fills=(*w.fills, *extra))


def test_R4_AC4_barless_trips_do_not_enter_the_shrinkage_n(cfg_permissive: Config) -> None:
    base = W.healthy(A)
    noisy = with_barless_trips(base, 20)
    clean, with_extra = one(cfg_permissive, base), one(cfg_permissive, noisy)
    assert clean.metrics is not None and with_extra.metrics is not None
    assert with_extra.metrics.n_rt == 100 and clean.metrics.n_rt == 80  # G2's n_rt is unchanged: all closed trips
    assert with_extra.eligible and clean.eligible
    assert with_extra.components == clean.components
    assert with_extra.score == clean.score


def test_R4_AC4_more_barless_trips_still_change_nothing(cfg_permissive: Config) -> None:
    base = W.healthy(A)
    clean = one(cfg_permissive, base)
    for n in (1, 7, 25):
        assert one(cfg_permissive, with_barless_trips(base, n)).score == clean.score


def test_R4_AC4_a_wallet_with_no_measurable_trip_stays_ineligible_by_the_existing_gates(cfg_permissive: Config) -> None:
    s = one(cfg_permissive, replace(W.healthy(A), candles_1h={}))
    assert not s.eligible and s.score is None
    assert "G10" in s.reasons and "G12" in s.reasons
    assert set(s.reasons) <= {f"G{i}" for i in range(1, 16)}  # only existing gates, no new rule


def test_R4_AC4_all_bars_present_scores_are_unchanged_golden(cfg_permissive: Config) -> None:
    s = one(cfg_permissive, W.healthy(A))
    assert s.eligible and s.metrics is not None and s.components is not None
    assert s.score == D("0.6573571825925925925925925926")
    assert s.components.x["copy_mean_r"] == D("0.06882861911111111111111111111")
    assert s.components.u["copy_mean_r"] == D("0.2294287303703703703703703704")
    assert s.metrics.n_rt == 80 and s.metrics.copy_edge_ratio == D("4.444444444444444444444444444")
