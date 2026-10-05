"""Stage 1 of the candidate screen (R3; docs/sdlc/copytrade-v1/research/candidate-ranking.md sections 2 and 9): which
leaderboard rows are worth a first page of fills, and in which order. A pure function of the rows: no request, no clock.

This module is also the ONE place for the numbers of the whole screen. PO decision 2026-10-03 (option A): they are code
constants, not config keys. Rules that reuse an existing key (``gate.*``, ``scoring.*``, ``paper.wallet_usd``,
``sizing.min_order_usd``) read it from config in ``selection.screen``; nothing here duplicates those values.

Rules (inclusive as written; every comparison is exact, in ``Decimal`` / ``Fraction``, never a float):
    P1 readable   valid address, account value and pnl + vlm of day/week/month/allTime all present and finite;
                  otherwise the row is UNRANKABLE (L4), never rejected. The ``roi`` field is never used.
    P2            address not in ``gate.exclude_addresses``.
    P3            account value >= ``gate.min_account_value_usd``.
    P4 active     week volume > 0 and month volume >= ``MIN_MONTH_TURNOVER`` x account value.
    P5 not hyper  month volume <= ``MAX_MONTH_TURNOVER`` x AV and day volume <= ``MAX_DAY_TURNOVER`` x AV.
    P6 profitable pnl(month) > 0 and pnl(prior) > 0, prior = allTime - month.
    P7 edge       prior volume > 0 and the pnl per traded dollar is >= ``MIN_EDGE_BPS`` in both periods.
    P8 sanity     pnl(month) / AV <= ``MAX_MONTH_RETURN``.
    K1 rank       ``min(bps_month, bps_prior, EDGE_CAP_BPS)`` descending, then all-time pnl descending, then the
                  lower-case address ascending: the list never depends on the order the rows are served in.
    L4            fewer than ``candidates_k`` ranked rows: unrankable rows (P2 and P3 not violated) follow, as served.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from copytrade.recorder.registry import LeaderboardRow
from copytrade.selection.models import CandidateList, ScreenRow

# --- stage 1 (P4-P8, K1, L3) ---------------------------------------------------------------------------------------
MIN_MONTH_TURNOVER = Decimal(2)  # P4: 25 round trips a month (G2) at >= ~3.3% of AV each (G12) is about 1.7 x AV
MAX_MONTH_TURNOVER = Decimal(500)  # P5 (prior, not derived)
MAX_DAY_TURNOVER = Decimal(50)  # P5 (prior, not derived)
MIN_EDGE_BPS = Decimal(10)  # P7: below our ~9-15 bps per traded dollar of costs the edge is gone (G10 asks for 3x)
EDGE_CAP_BPS = Decimal(50)  # K1: above it more is mostly variance
MAX_MONTH_RETURN = Decimal(1)  # P8: over 100% in 30 days is a small-account artefact
KEEP_RANK_MULT = 2  # L3: a slot holder keeps its slot while it ranks within the top KEEP_RANK_MULT x candidates_k

# --- stage 2 (S3, S7/S8 evidence, budget) --------------------------------------------------------------------------
MIN_CORE_PERP_SHARE = Decimal("0.5")  # S3: under half of the notional in our universe: the row's edge is not copyable
SCREEN_MIN_TRIPS = 30  # S7, S8: a true 30 minute median hold is wrongly rejected with p ~ 0.03 at 30 trips
SCREEN_MAX_PER_CYCLE = 100  # screens per cycle: at most 12 000 weight, about 27 minutes of the scoring share

# --- cooldowns by outcome (hours) and rotation ------------------------------------------------------------------------
EMPTY_COOLDOWN_H = 168  # S1: no fill in the window
TOO_ACTIVE_COOLDOWN_H = 24  # S2 / EX1 and R1's other too-active exits
SCREEN_COOLDOWN_H = 72  # S3-S9
ROTATE_AFTER_CYCLES = 3  # RO1: ineligible in this many consecutive scored cycles
ROTATE_COOLDOWN_H = 72  # RO1

_BPS = Fraction(10_000)
_ZERO = Decimal(0)
_WINDOWS = ("day", "week", "month", "allTime")


@dataclass(frozen=True)
class _Figures:
    """The nine figures P1 asks for, all readable."""

    av: Decimal
    pnl: dict[str, Decimal]
    vlm: dict[str, Decimal]


def _figures(row: LeaderboardRow) -> _Figures | None:
    """P1: ``None`` when any figure is missing or unreadable."""
    pnl: dict[str, Decimal] = {}
    vlm: dict[str, Decimal] = {}
    for name in _WINDOWS:
        window = row.windows.get(name)
        if window is None or window.pnl is None or window.vlm is None:
            return None
        pnl[name], vlm[name] = window.pnl, window.vlm
    if row.account_value is None:
        return None
    return _Figures(row.account_value, pnl, vlm)


def _edge_bps(pnl: Decimal, vlm: Decimal) -> Fraction:
    """Basis points of pnl per traded dollar, exact. ``vlm`` must be positive."""
    return _BPS * Fraction(pnl) / Fraction(vlm)


def _rank_key(f: _Figures) -> tuple[Fraction, Decimal] | None:
    """P4-P8 and K1: ``None`` when a rule fails, else ``(K1 edge, all-time pnl)`` (both to be sorted descending)."""
    month_vlm, month_pnl = f.vlm["month"], f.pnl["month"]
    prior_vlm, prior_pnl = f.vlm["allTime"] - month_vlm, f.pnl["allTime"] - month_pnl
    if not (
        f.av > _ZERO  # a turnover needs a positive account value (P3 alone would allow 0 when the minimum is 0)
        and f.vlm["week"] > _ZERO  # P4
        and month_vlm >= MIN_MONTH_TURNOVER * f.av
        and month_vlm <= MAX_MONTH_TURNOVER * f.av  # P5
        and f.vlm["day"] <= MAX_DAY_TURNOVER * f.av
        and month_pnl > _ZERO  # P6
        and prior_pnl > _ZERO
        and prior_vlm > _ZERO  # P7
        and month_pnl <= MAX_MONTH_RETURN * f.av  # P8
    ):
        return None
    edge_month, edge_prior = _edge_bps(month_pnl, month_vlm), _edge_bps(prior_pnl, prior_vlm)
    floor = Fraction(MIN_EDGE_BPS)
    if edge_month < floor or edge_prior < floor:
        return None
    return min(edge_month, edge_prior, Fraction(EDGE_CAP_BPS)), f.pnl["allTime"]


def _screen_row(row: LeaderboardRow) -> ScreenRow:
    return ScreenRow(
        row.address,
        row.account_value,
        row.windows["week"].vlm if "week" in row.windows else None,
        row.windows["month"].vlm if "month" in row.windows else None,
    )


def candidate_list(
    rows: Sequence[LeaderboardRow], *, excluded: Collection[str], min_account_value: Decimal, k: int
) -> CandidateList:
    """Stage 1 over ``rows`` (valid, distinct, lower-cased addresses; ``excluded`` lower-cased): the K1-ranked rows
    that pass P1-P8, then (L4) while fewer than ``k`` are ranked, the unrankable ones in served order. Cooldowns are
    not applied here."""
    ranked: list[tuple[Fraction, Decimal, str, LeaderboardRow]] = []
    unrankable: list[LeaderboardRow] = []
    for row in rows:
        if row.address in excluded or (row.account_value is not None and row.account_value < min_account_value):
            continue  # P2, P3
        figures = _figures(row)
        if figures is None:
            unrankable.append(row)
            continue
        key = _rank_key(figures)
        if key is not None:
            ranked.append((key[0], key[1], row.address, row))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    chosen = [_screen_row(item[3]) for item in ranked]
    appended = [_screen_row(row) for row in unrankable[: max(k - len(ranked), 0)]]
    return CandidateList(rows=(*chosen, *appended), ranked_count=len(ranked))
