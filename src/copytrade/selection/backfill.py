"""Incremental candidate backfill under the rate budget (F6.AC4)."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Sequence
from decimal import Decimal

from copytrade.core.clock import Clock
from copytrade.core.config import Config
from copytrade.hl import models as hl
from copytrade.hl.budget import Priority
from copytrade.hl.errors import HlError, HlSchemaError
from copytrade.hl.rest import HlRestClient
from copytrade.recorder.ports import CandleSource
from copytrade.scoring import models as sc
from copytrade.scoring.reconstruct import is_core_perp

_log = logging.getLogger(__name__)

_DAY_MS = 86_400_000
_HOUR_MS = 3_600_000
_CANDLE_INTERVAL = "1h"
_FILLS_PER_PAGE = 2_000  # Hyperliquid returns at most this many fills for one userFillsByTime request
_MAX_FILL_PAGES = 50  # 100 000 fills: a wallet with more in the window is not a copyable one; it stays stale
_MAX_BARS_PER_REQUEST = 4_800  # below the 5 000-candle cap of candleSnapshot
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
        liquidation=_LIQUIDATION_MARK in raw.dir,
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


class Backfiller:
    """Fetches scoring inputs for candidate wallets through the real REST client at SCORING priority (which paces
    itself on the rate budget). Satisfies ``copytrade.selection.models.InputsProvider``.

    Per wallet: fills (``userFillsByTime``; the first fetch starts ``scoring.window_days`` back, later ones after the
    last fill already held, de-duplicated by ``tid``), ``portfolio``, ``clearinghouseState``, ``userRole`` and, for each
    core perp coin seen in the fills, 1h candles through ``candles``. ``hl.Fill`` becomes ``scoring.Fill``; a fill
    whose ``dir`` contains ``iquidat`` has ``liquidation=True``.

    Decisions beyond that contract:
    - A fetch is all or nothing: the wallet's held data is replaced only when every request of the fetch succeeded.
    - ``userFillsByTime`` is paged (2 000 fills a page). A fetch that cannot reach the present (more than
      ``_MAX_FILL_PAGES`` pages, or no progress) keeps what it got but does not advance ``fills_fetched_ms``, so the
      scorer sees the wallet as ``stale_input`` (fail closed) until a later refresh catches up.
    - Candles are shared between wallets: a coin is fetched at most once per UTC hour, because a 1h bar that has closed
      never changes; ``candles_fetched_ms`` is the time the wallet's bars were last confirmed current.
    - ``userRole`` is requested once per wallet (again only after a failed attempt left it unknown).
    - Fills older than ``scoring.window_days`` are dropped (the scorer ignores them). ``funding`` and ``own_snapshots``
      stay empty (the REST client has no ``userFunding``; F5 falls back to ``perpMonth`` and to realised P&L).
    """

    def __init__(self, *, config: Config, clock: Clock, rest: HlRestClient, candles: CandleSource) -> None:
        self._window_ms: int = config["scoring.window_days"] * _DAY_MS
        self._clock = clock
        self._rest = rest
        self._candle_source = candles
        self._held: dict[str, sc.WalletInputs] = {}
        self._undone: deque[str] = deque()
        self._has_candidates = False
        self._complete = False
        self._bars: dict[str, tuple[sc.Candle, ...]] = {}
        self._bars_hour: dict[str, int] = {}

    @property
    def complete(self) -> bool:
        """True once every wallet of the candidate list has been fetched at least once, then latched. False before
        ``set_candidates`` has been called (fail closed)."""
        return self._complete

    def set_candidates(self, wallets: Sequence[str]) -> None:
        """Set the candidate list (lower-cased, de-duplicated, order kept). Data already fetched is kept."""
        candidates = list(dict.fromkeys(wallet.lower() for wallet in wallets))
        self._undone = deque(wallet for wallet in candidates if wallet not in self._held)
        self._has_candidates = bool(candidates)
        self._latch()

    def step(self) -> bool:
        """Fetch the next wallet that has never been fetched (blocking while the budget paces it). A wallet whose
        fetch raises ``HlError`` (or ``OSError`` from the candle source) is left undone and retried after the others.
        Returns False when there is nothing left to fetch."""
        if not self._undone:
            return False
        wallet = self._undone.popleft()
        try:
            self._held[wallet] = self._collect(wallet)
        except (HlError, OSError) as exc:
            _log.warning(
                "backfill of a candidate failed, it will be retried",
                extra={"event": "backfill_failed", "wallet": wallet, "error_type": type(exc).__name__},
            )
            self._undone.append(wallet)
        self._latch()
        return True

    def refresh(self, wallet: str) -> None:
        """Incremental fetch for one wallet. An ``HlError`` leaves the old data in place and propagates."""
        key = wallet.lower()
        self._held[key] = self._collect(key)
        if key in self._undone:
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

    def _collect(self, wallet: str) -> sc.WalletInputs:
        """Every request of one fetch; nothing is stored until all of them have succeeded."""
        previous = self._held.get(wallet)
        window_start = self._clock.now_ms() - self._window_ms
        held_fills = {} if previous is None else {f.tid: f for f in previous.fills if f.time >= window_start}
        start_ms = max((f.time for f in held_fills.values()), default=window_start)

        new_fills, reached_present = self._fetch_fills(wallet, start_ms)
        fills_fetched_ms: int | None = self._clock.now_ms()
        for raw in new_fills:
            held_fills.setdefault(raw.tid, _fill(raw))
        fills = tuple(sorted(held_fills.values(), key=lambda f: (f.time, f.tid)))

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

        if not reached_present:
            _log.warning(
                "fills backfill did not reach the present, the wallet stays stale",
                extra={"event": "backfill_incomplete", "wallet": wallet},
            )
            fills_fetched_ms = previous.fills_fetched_ms if previous is not None else None
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

    def _fetch_fills(self, wallet: str, start_ms: int) -> tuple[list[hl.Fill], bool]:
        """All fills from ``start_ms`` on, paged. The flag is False when the present was not reached."""
        fills: list[hl.Fill] = []
        seen: set[int] = set()
        cursor = start_ms
        for _ in range(_MAX_FILL_PAGES):
            page = self._rest.user_fills_by_time(wallet, cursor, None, priority=Priority.SCORING)
            fills.extend(raw for raw in page if raw.tid not in seen)
            seen.update(raw.tid for raw in page)
            if len(page) < _FILLS_PER_PAGE:
                return fills, True
            last = max(raw.time_ms for raw in page)
            if last <= cursor:
                return fills, False  # a whole page inside one millisecond: the cursor cannot move
            cursor = last
        return fills, False

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
