"""Incremental candidate backfill under the rate budget (F6.AC4)."""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from copytrade.core.clock import Clock
from copytrade.core.config import Config
from copytrade.hl import models as hl
from copytrade.hl.budget import Priority
from copytrade.hl.errors import HlBudgetError, HlError, HlRateLimitedError, HlSchemaError
from copytrade.hl.rest import HlRestClient
from copytrade.recorder.ports import CandleSource
from copytrade.scoring import models as sc
from copytrade.scoring.reconstruct import is_core_perp

_log = logging.getLogger(__name__)

_DAY_MS = 86_400_000
_HOUR_MS = 3_600_000
_CANDLE_INTERVAL = "1h"
_FILLS_PER_PAGE = 2_000  # Hyperliquid returns at most this many fills for one userFillsByTime request
_MAX_FILL_PAGES = 50  # 100 000 fills: a wallet with more in the window is too active to copy: dropped for a day
_FIRST_SLICE_PAGES = 2  # first slice of a wallet with others waiting: 240 of the 450 share, the light ones still fit
_MAX_PAGES_PER_STEP = 3  # 3 full pages (weight 120 each) fit one minute of the 450 scoring weight share
_MAX_BARS_PER_REQUEST = 4_800  # below the 5 000-candle cap of candleSnapshot
HL_FILLS_LIMIT = 10_000  # API fact: userFillsByTime makes only the 10 000 most recent fills of a wallet retrievable
_BUDGET_KEY = ""  # the cooldown after a budget refusal belongs to no wallet
_LIQUIDATION_MARK = "iquidat"  # "Liquidated Cross Long", "Liquidated Isolated Short", ...


def _fill(raw: hl.Fill) -> sc.Fill:
    return sc.Fill(
        tid=raw.tid,
        time=raw.time_ms,
        coin=raw.coin,
        side=raw.side,
        sz=Decimal(raw.sz),
        px=Decimal(raw.px),
        start_position=Decimal(raw.start_position),
        closed_pnl=Decimal(raw.closed_pnl),
        fee=Decimal(raw.fee),
        crossed=raw.crossed,
        liquidation=raw.liquidation or _LIQUIDATION_MARK in raw.dir,
    )


def _candle(raw: hl.Candle) -> sc.Candle:
    return sc.Candle(
        open_ms=raw.open_ms,
        close_ms=raw.close_ms,
        o=Decimal(raw.open),
        hi=Decimal(raw.high),
        lo=Decimal(raw.low),
        c=Decimal(raw.close),
    )


def _portfolio(raw: dict[str, hl.PortfolioWindow], fetched_ms: int) -> sc.PortfolioSnapshot:
    return sc.PortfolioSnapshot(
        fetched_ms=fetched_ms,
        windows={
            name: sc.PortfolioWindow(
                account_value_history=tuple((ms, Decimal(v)) for ms, v in window.account_value_history),
                pnl_history=tuple((ms, Decimal(v)) for ms, v in window.pnl_history),
            )
            for name, window in raw.items()
        },
    )


def _clearinghouse(raw: hl.ClearinghouseState, fetched_ms: int) -> sc.ClearinghouseState:
    """``fetched_ms`` is our own clock (the scorer compares it with the cycle time). An open position whose
    unrealised P&L is not in the payload cannot feed the open-loss blow-up check, so the whole response is refused
    (fail closed)."""
    positions: list[sc.OpenPosition] = []
    for position in raw.positions:
        if position.unrealized_pnl is None:
            raise HlSchemaError(
                "an open position has no unrealizedPnl", endpoint="clearinghouseState", field="assetPositions"
            )
        positions.append(sc.OpenPosition(coin=position.coin, unrealized_pnl=Decimal(position.unrealized_pnl)))
    return sc.ClearinghouseState(
        fetched_ms=fetched_ms, account_value=Decimal(raw.account_value), positions=tuple(positions)
    )


class _FillsOutcome(Enum):
    DONE = "done"  # the present was reached
    PAUSED = "paused"  # this step's page allowance is used up; the progress is kept
    STUCK = "stuck"  # a whole page inside one millisecond: the cursor cannot move
    CAPPED = "capped"  # ``_MAX_FILL_PAGES`` pages without reaching the present


@dataclass
class _Progress:
    """One wallet's unfinished fills fetch, kept across steps and failures: where to ask next, what was got."""

    cursor: int
    window_start: int  # the scoring window start when the fetch began: the truncation test must not drift with paging
    held: dict[int, sc.Fill]
    fetched: dict[int, hl.Fill] = field(default_factory=dict)
    pages: int = 0
    requests: int = 0  # every page asked for in this fetch, for the log (``pages`` restarts at the end of a fetch)


class Backfiller:
    """Fetches scoring inputs for candidate wallets through the real REST client at SCORING priority (which paces
    itself on the rate budget). Satisfies ``copytrade.selection.models.InputsProvider``.

    Per wallet: fills (``userFillsByTime``; the first fetch starts ``scoring.window_days`` back, later ones after the
    last fill already held, de-duplicated by ``tid``), ``portfolio``, ``clearinghouseState``, ``userRole`` and, for each
    core perp coin seen in the fills, 1h candles through ``candles``. ``hl.Fill`` becomes ``scoring.Fill``; a fill
    whose ``dir`` contains ``iquidat`` has ``liquidation=True``.

    Decisions beyond that contract:
    - The other requests of a fetch are all or nothing: the wallet's held data is replaced only when every request of
      the fetch succeeded.
    - ``userFillsByTime`` is paged (2 000 fills a page) and resumable: one step or refresh requests at most
      ``_MAX_PAGES_PER_STEP`` pages of one wallet (``_FIRST_SLICE_PAGES`` on its first slice while others wait behind
      it, so a heavy wallet leaves room in the share for the light ones). The cursor and the fills got so far are kept
      across steps and failures, so a wallet of many pages finishes in about its own page count of requests and never
      restarts. An unfinished wallet goes behind the others in the queue and blocks ``complete`` until finished or
      dropped.
    - A fetch that reaches ``_MAX_FILL_PAGES`` pages without the present means the wallet is too active to copy: it is
      logged once (``backfill_too_active``), dropped from the candidates (the backfill can complete without it) and not
      fetched again for one day. A fetch whose cursor cannot move keeps what it got but does not advance
      ``fills_fetched_ms``, so the scorer sees the wallet as ``stale_input`` (fail closed) until a later refresh.
    - A fetch that ends cleanly with exactly ``HL_FILLS_LIMIT`` fills whose oldest is more than a day after the window
      start was cut by the API (only its 10 000 most recent fills are retrievable): the window is partial, so it is
      treated as too active (``reason`` ``too_active_truncated``), never scored.
    - Any other ``HlError`` starts a per-wallet cooldown of ``hl.backoff_base_s``, doubled for each consecutive failure
      up to ``hl.backoff_max_s`` (a budget refusal cools every wallet down); a skipped ``refresh`` is logged once per
      cooldown (``backfill_refresh_skipped``).
    - A wallet whose fetch ended in a persistent HTTP 429 is not asked again for ``hl.backoff_max_s`` seconds; the
      others go on meanwhile.
    - Candles are shared between wallets: a coin is fetched at most once per UTC hour, because a 1h bar that has closed
      never changes; ``candles_fetched_ms`` is the time the wallet's bars were last confirmed current.
    - ``userRole`` is requested once per wallet (again only after a failed attempt left it unknown).
    - Fills older than ``scoring.window_days`` are dropped (the scorer ignores them). ``funding`` and ``own_snapshots``
      stay empty (the REST client has no ``userFunding``; F5 falls back to ``perpMonth`` and to realised P&L).
    """

    def __init__(self, *, config: Config, clock: Clock, rest: HlRestClient, candles: CandleSource) -> None:
        self._window_ms: int = config["scoring.window_days"] * _DAY_MS
        self._rate_limit_cooldown_ms = math.ceil(config["hl.backoff_max_s"] * 1000)
        self._error_base_ms = math.ceil(config["hl.backoff_base_s"] * 1000)
        self._clock = clock
        self._rest = rest
        self._candle_source = candles
        self._held: dict[str, sc.WalletInputs] = {}
        self._undone: deque[str] = deque()
        self._progress: dict[str, _Progress] = {}
        self._rate_limited_until: dict[str, int] = {}
        self._too_active_until: dict[str, int] = {}
        self._error_until: dict[str, int] = {}
        self._error_streak: dict[str, int] = {}  # consecutive failed attempts (not 429) of a wallet
        self._skip_logged: dict[
            str, int
        ] = {}  # wallet -> ``until_ms`` of the cooldown whose skipped refresh was logged
        self._has_candidates = False
        self._complete = False
        self._bars: dict[str, tuple[sc.Candle, ...]] = {}
        self._bars_hour: dict[str, int] = {}

    @property
    def complete(self) -> bool:
        """True once every wallet of the candidate list has been fetched at least once (or dropped as too active), then
        latched. False before ``set_candidates`` has been called (fail closed)."""
        return self._complete

    def set_candidates(self, wallets: Sequence[str]) -> None:
        """Set the candidate list (lower-cased, de-duplicated, order kept). Data already fetched is kept, and so is the
        progress of a wallet still listed; a wallet dropped as too active returns one day after it was dropped."""
        now = self._clock.now_ms()
        candidates = list(dict.fromkeys(wallet.lower() for wallet in wallets))
        self._too_active_until = {w: until for w, until in self._too_active_until.items() if until > now}
        self._progress = {w: progress for w, progress in self._progress.items() if w in candidates}
        self._undone = deque(
            wallet for wallet in candidates if wallet not in self._held and wallet not in self._too_active_until
        )
        self._has_candidates = bool(candidates)
        self._latch()

    def step(self) -> bool:
        """Fetch the next wallet that has never been fetched (blocking while the budget paces it), at most
        ``_MAX_PAGES_PER_STEP`` fill pages of it. A wallet whose fetch raises ``HlError`` (or ``OSError`` from the
        candle source), or that is not finished yet, is left undone and retried after the others; one rate limited
        (HTTP 429) waits out its cooldown. Returns False when no wallet can be fetched now."""
        wallet = self._next_ready()
        if wallet is None:
            return False
        try:
            inputs = self._collect(wallet, _MAX_PAGES_PER_STEP)
        except (HlError, OSError) as exc:
            self._start_cooldown(wallet, exc)
            self._log_failure(wallet, exc)
            self._undone.append(wallet)
        else:
            self._reset_errors(wallet)
            if inputs is not None:
                self._held[wallet] = inputs
            elif wallet not in self._too_active_until:
                self._undone.append(wallet)  # unfinished: its progress is kept, it goes behind the others
        self._latch()
        return True

    def refresh(self, wallet: str) -> None:
        """Incremental fetch for one wallet (at most ``_MAX_PAGES_PER_STEP`` fill pages; the rest follows on the next
        call). Nothing is sent for a wallet in a cooldown (too active, rate limited or after an error); the first
        skipped refresh of a cooldown is logged. An ``HlError`` leaves the old data in place, starts the wallet's
        cooldown and propagates."""
        key = wallet.lower()
        cooldown = self._cooldown(key)
        if cooldown is not None:
            self._log_refresh_skipped(key, *cooldown)
            return
        try:
            inputs = self._collect(key, _MAX_PAGES_PER_STEP)
        except HlError as exc:
            self._start_cooldown(key, exc)
            raise
        self._reset_errors(key)
        if inputs is not None:
            self._held[key] = inputs
        if (inputs is not None or key in self._too_active_until) and key in self._undone:
            self._undone.remove(key)
            self._latch()

    def inputs(self, wallet: str, t_ms: int) -> sc.WalletInputs | None:
        """The held inputs, or ``None`` when nothing has been fetched for ``wallet``. The scorer does the point-in-time
        filtering against the cycle time (10.1), so ``t_ms`` does not select anything here."""
        del t_ms
        return self._held.get(wallet.lower())

    # --- internals ---------------------------------------------------------------------------------------------

    def _latch(self) -> None:
        if self._has_candidates and not self._undone:
            self._complete = True

    def _cooldown(self, wallet: str) -> tuple[str, int] | None:
        """The cooldown the wallet is in now as ``(reason, until_ms)``, the one that lasts longest; None when free."""
        now = self._clock.now_ms()
        active = [
            (reason, until)
            for reason, table, key in (
                ("too_active", self._too_active_until, wallet),
                ("rate_limited", self._rate_limited_until, wallet),
                ("error_cooldown", self._error_until, wallet),
                ("error_cooldown", self._error_until, _BUDGET_KEY),
            )
            if (until := table.get(key, 0)) > now
        ]
        return max(active, key=lambda item: item[1], default=None)

    def _cooling_down(self, wallet: str) -> bool:
        return self._cooldown(wallet) is not None

    def _start_cooldown(self, wallet: str, exc: Exception) -> None:
        """A 429 waits ``hl.backoff_max_s``; any other failure waits ``hl.backoff_base_s`` doubled for every consecutive
        failure of the wallet, up to ``hl.backoff_max_s``. A budget refusal is not about one wallet (the scoring
        share is shared): it cools every wallet down, so one refusal is one record, not one per candidate."""
        now = self._clock.now_ms()
        if isinstance(exc, HlRateLimitedError):
            self._rate_limited_until[wallet] = now + self._rate_limit_cooldown_ms
            return
        key = _BUDGET_KEY if isinstance(exc, HlBudgetError) else wallet
        streak = self._error_streak.get(key, 0) + 1
        self._error_streak[key] = streak
        wait_ms = min(self._error_base_ms * 2 ** min(streak - 1, 62), self._rate_limit_cooldown_ms)
        self._error_until[key] = now + wait_ms

    def _reset_errors(self, wallet: str) -> None:
        """A request cycle that went through: the wallet's failure streak (and the shared budget one) starts over."""
        self._error_streak.pop(wallet, None)
        self._error_streak.pop(_BUDGET_KEY, None)

    def _log_refresh_skipped(self, wallet: str, reason: str, until_ms: int) -> None:
        if self._skip_logged.get(wallet) == until_ms:
            return
        self._skip_logged[wallet] = until_ms
        _log.info(
            "refresh of a candidate skipped, it is cooling down",
            extra={"event": "backfill_refresh_skipped", "wallet": wallet, "reason": reason, "until_ms": until_ms},
        )

    def _next_ready(self) -> str | None:
        """Take the first undone wallet that is not cooling down (the others keep their order); None when none is."""
        for _ in range(len(self._undone)):
            wallet = self._undone.popleft()
            if not self._cooling_down(wallet):
                return wallet
            self._undone.append(wallet)
        return None

    def _log_failure(self, wallet: str, exc: Exception) -> None:
        """One record per failed attempt: the message of an HL error names the request type and status, never the URL
        or the response body."""
        _log.warning(
            "backfill of a candidate failed, it will be retried",
            extra={
                "event": "backfill_failed",
                "wallet": wallet,
                "status": getattr(exc, "status", None),
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )

    def _collect(self, wallet: str, max_pages: int) -> sc.WalletInputs | None:
        """One fetch of one wallet, resuming its fills progress. ``None`` when the fills are not finished (progress
        kept) or the wallet was dropped as too active. Nothing is stored until every request has succeeded."""
        previous = self._held.get(wallet)
        progress = self._progress.get(wallet)
        if progress is None:
            window_start = self._clock.now_ms() - self._window_ms
            held_fills = {} if previous is None else {f.tid: f for f in previous.fills if f.time >= window_start}
            progress = _Progress(
                cursor=max((f.time for f in held_fills.values()), default=window_start),
                window_start=window_start,
                held=held_fills,
            )
            self._progress[wallet] = progress

        outcome = self._fetch_fills(wallet, progress, max_pages)
        if outcome is _FillsOutcome.PAUSED:
            return None
        if outcome is _FillsOutcome.CAPPED:
            self._drop_too_active(wallet, progress.pages)
            return None
        if outcome is _FillsOutcome.DONE and self._truncated(progress):
            self._drop_too_active(wallet, progress.requests, reason="too_active_truncated")
            return None
        fetched_ms = self._clock.now_ms()
        fills_fetched_ms: int | None = fetched_ms
        window_start = fetched_ms - self._window_ms
        held_fills = dict(progress.held)
        for raw in progress.fetched.values():
            held_fills.setdefault(raw.tid, _fill(raw))
        fills = tuple(sorted((f for f in held_fills.values() if f.time >= window_start), key=lambda f: (f.time, f.tid)))

        portfolio = _portfolio(self._rest.portfolio(wallet, priority=Priority.SCORING), self._clock.now_ms())
        clearinghouse = _clearinghouse(
            self._rest.clearinghouse_state(wallet, priority=Priority.SCORING), self._clock.now_ms()
        )
        role = previous.role if previous is not None else None
        if role is None:
            role = self._rest.user_role(wallet, priority=Priority.SCORING)
        coins = sorted({f.coin for f in fills if is_core_perp(f.coin)})
        candles = {coin: self._bars_for(coin) for coin in coins}
        candles_fetched_ms = self._clock.now_ms()

        if outcome is _FillsOutcome.STUCK:
            _log.warning(
                "fills backfill did not reach the present, the wallet stays stale",
                extra={
                    "event": "backfill_incomplete",
                    "wallet": wallet,
                    "pages": progress.pages,
                    "fills": len(progress.fetched),
                },
            )
            fills_fetched_ms = previous.fills_fetched_ms if previous is not None else None
        del self._progress[wallet]
        return sc.WalletInputs(
            address=wallet,
            fills=fills,
            fills_fetched_ms=fills_fetched_ms,
            funding=(),
            portfolios=(portfolio,),
            clearinghouse=(clearinghouse,),
            own_snapshots=(),
            candles_1h=candles,
            candles_fetched_ms=candles_fetched_ms,
            role=role,
            leaderboard_row=None,
        )

    @staticmethod
    def _truncated(progress: _Progress) -> bool:
        """The API kept only its ``HL_FILLS_LIMIT`` most recent fills (exactly that many came back, never more) and the
        oldest of them starts well inside the window (more than a day after its start): the window is partial although
        the paging ended cleanly."""
        if len(progress.fetched) != HL_FILLS_LIMIT:  # more than the limit came back: nothing was cut off
            return False
        return min(raw.time_ms for raw in progress.fetched.values()) > progress.window_start + _DAY_MS

    def _drop_too_active(self, wallet: str, pages: int, *, reason: str = "too_active") -> None:
        _log.warning(
            "wallet has more fills in the window than can be fetched, dropped for a day",
            extra={"event": "backfill_too_active", "wallet": wallet, "reason": reason, "pages": pages},
        )
        self._too_active_until[wallet] = self._clock.now_ms() + _DAY_MS
        self._error_streak.pop(wallet, None)
        del self._progress[wallet]

    def _fetch_fills(self, wallet: str, progress: _Progress, max_pages: int) -> _FillsOutcome:
        """Pages of fills from the progress cursor on, at most ``max_pages`` requests; every page is recorded in
        ``progress`` as it arrives, so a failure or a pause loses nothing."""
        requested = 0
        allowance = max_pages if progress.pages or not self._undone else min(max_pages, _FIRST_SLICE_PAGES)
        while progress.pages < _MAX_FILL_PAGES:
            if requested == allowance:
                return _FillsOutcome.PAUSED
            page = self._rest.user_fills_by_time(wallet, progress.cursor, None, priority=Priority.SCORING)
            requested += 1
            progress.pages += 1
            progress.requests += 1
            for raw in page:
                progress.fetched.setdefault(raw.tid, raw)
            if len(page) < _FILLS_PER_PAGE:
                progress.pages = 0  # the next fetch of this wallet (an incremental one) starts counting afresh
                return _FillsOutcome.DONE
            last = max(raw.time_ms for raw in page)
            if last <= progress.cursor:
                return _FillsOutcome.STUCK
            progress.cursor = last
        return _FillsOutcome.CAPPED

    def _bars_for(self, coin: str) -> tuple[sc.Candle, ...]:
        """The coin's 1h bars of the window, fetched when the coin has not been fetched in the current UTC hour."""
        now = self._clock.now_ms()
        if self._bars_hour.get(coin) != now // _HOUR_MS:
            window_start = now - self._window_ms
            held = {b.open_ms: b for b in self._bars.get(coin, ()) if b.open_ms >= window_start}
            start = max((b.open_ms for b in held.values()), default=window_start)  # the last bar may have been partial
            for chunk_start in range(start, now + 1, _MAX_BARS_PER_REQUEST * _HOUR_MS):
                chunk_end = min(chunk_start + _MAX_BARS_PER_REQUEST * _HOUR_MS - 1, now)
                for raw in self._candle_source.fetch(coin, _CANDLE_INTERVAL, chunk_start, chunk_end):
                    held[raw.open_ms] = _candle(raw)
            self._bars[coin] = tuple(sorted(held.values(), key=lambda b: b.open_ms))
            self._bars_hour[coin] = now // _HOUR_MS
        return self._bars[coin]
