"""Stage 2 of the candidate screen (R3; research/candidate-ranking.md section 9, V3-V5): the rules S1-S9 on the FIRST
page of a wallet's fills in the scoring window. Pure functions: no request, no clock, no log.

The screen only decides who gets the full backfill. It changes no metric, gate, score or frozen rule: the gates still
decide on the full history. A rule that cannot be evaluated from this page is *not evaluable*, never a failure.

    S1 the page has a fill.                        S2 not (a full page spanning under a day).
    S3 core notional share >= MIN_CORE_PERP_SHARE.
    S4 maker share of the core fills <= gate.max_maker_share (no core notional = fail).
    S5 first core fill at least gate.min_fill_span_days back (no core fill = fail).
    S6 full page only: 2 000 fills / span x scoring.window_days < HL_FILLS_LIMIT.
    S7 median hold >= gate.min_median_hold_min; a trip still open at the page end counts as an infinite hold.
    S8 share of trips whose scaled open reaches sizing.min_order_usd >= gate.min_executable_share.
       S7 and S8 need SCREEN_MIN_TRIPS trips (closed or open).
    S9 non-full page only (it holds the whole window): closed round trips >= gate.min_round_trips.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from copytrade.core.config import Config
from copytrade.scoring.metrics import maker_share
from copytrade.scoring.models import DAY_MS, MINUTE_MS, Fill, Reconstruction
from copytrade.scoring.reconstruct import dedupe_fills, is_core_perp, reconstruct
from copytrade.scoring.series import median
from copytrade.selection.models import FILLS_PER_PAGE, HL_FILLS_LIMIT
from copytrade.selection.prefilter import MIN_CORE_PERP_SHARE, SCREEN_MIN_TRIPS

_ZERO = Decimal(0)
_INFINITE_HOLD = Decimal("Infinity")  # a trip still open at the page end: its hold is only known to be longer


@dataclass(frozen=True)
class ScreenThresholds:
    """The reused config keys the rules read (values as configured)."""

    max_maker_share: Decimal
    min_fill_span_days: int
    min_median_hold_min: int
    min_executable_share: Decimal
    min_round_trips: int
    window_days: int
    wallet_usd: Decimal
    min_order_usd: Decimal

    @classmethod
    def from_config(cls, cfg: Config) -> ScreenThresholds:
        return cls(
            max_maker_share=cfg["gate.max_maker_share"],
            min_fill_span_days=cfg["gate.min_fill_span_days"],
            min_median_hold_min=cfg["gate.min_median_hold_min"],
            min_executable_share=cfg["gate.min_executable_share"],
            min_round_trips=cfg["gate.min_round_trips"],
            window_days=cfg["scoring.window_days"],
            wallet_usd=cfg["paper.wallet_usd"],
            min_order_usd=cfg["sizing.min_order_usd"],
        )


@dataclass(frozen=True)
class ScreenResult:
    """The rules that failed and the rules that could not be evaluated, as ids (``S1``..``S9``) in ascending order."""

    failed: tuple[str, ...]
    not_evaluable: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.failed


def _notional(fills: Sequence[Fill]) -> Decimal:
    return sum((f.sz * f.px for f in fills), _ZERO)


def _trip_rules(
    trips: Reconstruction, account_value: Decimal | None, th: ScreenThresholds
) -> tuple[list[str], list[str]]:
    """S7 and S8 over the closed and the still open trips: ``(failed, not evaluable)``."""
    failed: list[str] = []
    not_evaluable: list[str] = []
    n_trips = len(trips.closed) + len(trips.open)
    if n_trips < SCREEN_MIN_TRIPS:
        return failed, ["S7", "S8"]
    holds = [Decimal(t.close_ms - t.open_ms) for t in trips.closed if t.close_ms is not None]
    holds += [_INFINITE_HOLD] * len(trips.open)
    median_hold = median(holds)
    if median_hold is None or median_hold < th.min_median_hold_min * MINUTE_MS:
        failed.append("S7")
    if account_value is None or account_value <= _ZERO:
        not_evaluable.append("S8")
        return failed, not_evaluable
    executable = sum(
        1
        for t in (*trips.closed, *trips.open)
        if t.open_sz * t.open_px * th.wallet_usd >= th.min_order_usd * account_value
    )
    if executable < th.min_executable_share * n_trips:
        failed.append("S8")
    return failed, not_evaluable


def screen_page(
    fills: Sequence[Fill],
    *,
    full: bool,
    now_ms: int,
    account_value: Decimal | None,
    thresholds: ScreenThresholds,
) -> ScreenResult:
    """Judge one first page (``fills`` as served, ``full`` = it has the maximum number of rows) at screen time
    ``now_ms``. ``account_value`` is the leaderboard row's (``None`` when unreadable: S8 is then not evaluable).

    Fills are de-duplicated like F5 does; every rule is computed whatever the others say.
    """
    th = thresholds
    page = dedupe_fills(fills)
    core = [f for f in page if is_core_perp(f.coin)]
    span_ms = page[-1].time - page[0].time if page else 0
    total, core_total = _notional(page), _notional(core)
    maker = maker_share(core)
    trips = reconstruct(core, ())
    failed_trips, not_evaluable = _trip_rules(trips, account_value, th)

    failed = [
        rule
        for rule, broken in (
            ("S1", not page),
            ("S2", full and span_ms < DAY_MS),
            ("S3", total <= _ZERO or core_total < MIN_CORE_PERP_SHARE * total),
            ("S4", maker is None or maker > th.max_maker_share),
            ("S5", not core or now_ms - core[0].time < th.min_fill_span_days * DAY_MS),
            # rate x window >= the limit, with rate = FILLS_PER_PAGE / span (exact, no division)
            ("S6", full and FILLS_PER_PAGE * th.window_days * DAY_MS >= HL_FILLS_LIMIT * span_ms),
            ("S9", not full and len(trips.closed) < th.min_round_trips),
        )
        if broken
    ]
    not_evaluable += ["S9" if full else "S6"]
    return ScreenResult(tuple(sorted([*failed, *failed_trips])), tuple(sorted(not_evaluable)))
