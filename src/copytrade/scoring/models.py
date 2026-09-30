"""Data types and boundary protocols for scoring (F5): plain data holders, no logic.

Conventions (decisions recorded in docs/sdlc/copytrade-v1/05-test-plan-F5.md):
- Money, prices, sizes and every ratio the gates compare are ``Decimal`` (never ``float``). ``None`` in a metric
  means "cannot be computed from the inputs"; a gate that needs it fails closed.
- Times are UTC milliseconds (``int``). A "day" is a UTC calendar day (index = ``ms // 86_400_000``).
- HL wire names are kept where they exist (``perpAllTime``, ``perpMonth``, ``startPosition``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

MINUTE_MS = 60_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000


@dataclass(frozen=True)
class Fill:
    """One verified leader fill (F3 supplies these; the leaderboard's own P&L fields never do)."""

    tid: int
    time: int
    coin: str
    side: str  # "B" buy or "A" sell
    sz: Decimal
    px: Decimal
    start_position: Decimal
    closed_pnl: Decimal
    fee: Decimal
    crossed: bool  # True = taker; False = maker
    liquidation: bool


@dataclass(frozen=True)
class FundingPayment:
    """Funding for one coin. ``paid`` is USD paid by the wallet (positive = a cost, negative = received)."""

    time: int
    coin: str
    paid: Decimal


@dataclass(frozen=True)
class TripEvent:
    """An add or a partial reduce inside a round trip."""

    time: int
    kind: str  # "add" | "reduce"
    px: Decimal
    sz_before: Decimal  # |position| before the fill
    sz_after: Decimal  # |position| after the fill


@dataclass(frozen=True)
class RoundTrip:
    """A per-coin position from flat to flat (10.1). ``close_ms`` is None while open."""

    coin: str
    direction: int  # +1 long, -1 short
    open_ms: int
    close_ms: int | None
    open_px: Decimal
    open_sz: Decimal
    avg_px: Decimal  # size-weighted average entry after the adds
    max_abs_sz: Decimal
    peak_notional: Decimal  # N_j = max|pos| x avg_px
    events: tuple[TripEvent, ...]
    adds: int
    adds_while_losing: int
    reduces: tuple[Decimal, ...]  # fraction of the position cut, per partial reduce
    gross_pnl: Decimal  # sum of closedPnl
    net_pnl: Decimal  # L_j = sum closedPnl - sum fee - funding_j
    liquidated: bool
    close_px: Decimal | None = None  # price of the fill that closed the trip; None while open


@dataclass(frozen=True)
class Reconstruction:
    """Result of round-trip reconstruction: (closed round trips, still-open round trips)."""

    closed: tuple[RoundTrip, ...]
    open: tuple[RoundTrip, ...]


@dataclass(frozen=True)
class Candle:
    """A 1h candle. ``close_ms`` is the last millisecond of the bar (Hyperliquid ``T``)."""

    open_ms: int
    close_ms: int
    o: Decimal
    hi: Decimal
    lo: Decimal
    c: Decimal


@dataclass(frozen=True)
class PortfolioWindow:
    """One window of a ``portfolio`` payload: (ms, value) points in ascending time order."""

    account_value_history: tuple[tuple[int, Decimal], ...]
    pnl_history: tuple[tuple[int, Decimal], ...]


@dataclass(frozen=True)
class PortfolioSnapshot:
    """A ``portfolio`` response fetched at ``fetched_ms``; ``windows`` is keyed by ``perpAllTime``, ..."""

    fetched_ms: int
    windows: Mapping[str, PortfolioWindow]


@dataclass(frozen=True)
class OpenPosition:
    """An open position from ``clearinghouseState``."""

    coin: str
    unrealized_pnl: Decimal


@dataclass(frozen=True)
class ClearinghouseState:
    """A ``clearinghouseState`` response fetched at ``fetched_ms``."""

    fetched_ms: int
    account_value: Decimal
    positions: tuple[OpenPosition, ...]


@dataclass(frozen=True)
class OwnSnapshot:
    """One of our own hourly ``portfolio`` observations (the finest daily-return source)."""

    ms: int
    account_value: Decimal
    pnl: Decimal


@dataclass(frozen=True)
class LeaderboardRow:
    """Leaderboard self-reported fields. Never an input to any metric or to S (C1)."""

    pnl: Decimal
    roi: Decimal
    account_value: Decimal


@dataclass(frozen=True)
class WalletInputs:
    """Everything the scorer may read about one wallet. Point-in-time filtering is the scorer's job (10.1)."""

    address: str
    fills: tuple[Fill, ...]
    fills_fetched_ms: int | None
    funding: tuple[FundingPayment, ...]
    portfolios: tuple[PortfolioSnapshot, ...]  # history of fetched snapshots; the latest at or before t is used
    clearinghouse: tuple[ClearinghouseState, ...]  # same rule
    own_snapshots: tuple[OwnSnapshot, ...]
    candles_1h: Mapping[str, tuple[Candle, ...]]  # per coin; only bars with close_ms <= t are used
    candles_fetched_ms: int | None
    role: str | None  # userRole; None = could not be fetched
    leaderboard_row: LeaderboardRow | None


@dataclass(frozen=True)
class DsrResolution:
    """Number of daily-return days taken from each source (10.1). ``t_days`` is their sum."""

    own_hourly_days: int
    perp_month_days: int
    fill_days: int


@dataclass(frozen=True)
class Metrics:
    """M1-M19 plus the helper quantities the gates and detectors read. ``None`` = cannot be computed."""

    n_rt: int  # M1
    fill_span_days: Decimal | None  # M2
    account_age_days: Decimal | None  # M3
    profit_factor: Decimal | None  # M4, capped at 10
    sr_d: Decimal | None  # M5
    skew: Decimal | None  # M6
    kurt: Decimal | None  # M6, non-excess
    dsr_prob: Decimal | None  # M7
    sr0: Decimal | None  # M7 benchmark
    dsr_excess: Decimal | None  # sr_d - SR0 (score component 1)
    t_days: int  # daily-resolution days
    pos_blocks: int  # M8
    max_dd: Decimal | None  # M9
    max_dd_realised: Decimal | None
    max_dd_mtm: Decimal | None
    median_hold_min: Decimal | None  # M10
    top_trade_share: Decimal | None  # M11 (None when the sum of L_j <= 0)
    top_asset_share: Decimal | None  # M12 (None when the sum of L_j <= 0)
    maker_share: Decimal | None  # M13
    copy_mean_r: Decimal | None  # M14
    copy_edge_ratio: Decimal | None  # M15
    executable_share: Decimal | None  # M16
    recent_sr: Decimal | None  # M17
    current_dd: Decimal | None  # M18
    eff_leverage_median: Decimal | None  # M19
    account_value: Decimal | None  # AV from clearinghouseState (G11)
    open_loss_fraction: Decimal | None  # open unrealised loss / AV (BU8)
    liquidation_fills: int = 0  # liquidation fills on core perps in the window (BU6)


@dataclass(frozen=True)
class TripRecord:
    """A closed round trip with the leader's account value at its open (latest point at or before it; None if none)."""

    trip: RoundTrip
    av_at_open: Decimal | None


@dataclass(frozen=True)
class Components:
    """Score components: raw x_k, clipped u_k and S, keyed by ``dsr_excess``, ``copy_mean_r``, ``pos_blocks``,
    ``max_dd``, ``recent_sr``, ``executable``."""

    x: Mapping[str, Decimal]
    u: Mapping[str, Decimal]
    score: Decimal


@dataclass(frozen=True)
class WalletScore:
    """One wallet's result for a cycle. Ineligible wallets have ``score`` and ``rank`` None."""

    address: str  # lowercase
    eligible: bool
    reasons: tuple[str, ...]  # ineligibility reasons: "stale_input", "G1".."G15" (sorted)
    blowup_flags: tuple[str, ...]  # "BU1".."BU8" (sorted)
    metrics: Metrics | None
    components: Components | None
    score: Decimal | None
    rank: int | None
    input_hashes: Mapping[str, str]  # sha256 hex per input kind
    dsr_resolution: DsrResolution | None


@dataclass(frozen=True)
class CycleResult:
    """A scoring cycle: eligible wallets first in rank order, then ineligible ones by address."""

    t_ms: int
    scores: tuple[WalletScore, ...]


@dataclass(frozen=True)
class RankEntry:
    """A (wallet, score, n_rt) triple for the deterministic ranking."""

    address: str
    score: Decimal
    n_rt: int


class CostModel(Protocol):
    """Recorded-data boundary (F4 / paper cost model): the costs used by M14 and M15."""

    def taker_fee_bps(self) -> Decimal:
        """Taker fee per leg, in bps."""
        ...

    def half_spread_bps(self, coin: str, t_ms: int) -> Decimal:
        """Half spread of ``coin`` at ``t_ms`` (recorded, else the config fallback), in bps."""
        ...

    def delay_bps(self, coin: str, t_ms: int) -> Decimal:
        """Adverse move over the copy delay for ``coin`` at ``t_ms``, in bps."""
        ...


class ScoreStore(Protocol):
    """Persistence boundary (B5); F2's ledger implements it later."""

    def append_cycle(self, result: CycleResult) -> None:
        """Durably append one cycle. Raises on failure."""
        ...
