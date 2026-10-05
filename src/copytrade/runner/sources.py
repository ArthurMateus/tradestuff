"""The remaining ports of F3/F4/F6/F10/F12 over the REST client, the share book, the broker and the ledger.

Read-only toward Hyperliquid (info requests only). Everything that touches the broker or the book only READS."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from decimal import Decimal
from itertools import pairwise
from typing import Any

from copytrade.core.clock import Clock
from copytrade.hl.budget import Priority
from copytrade.hl.errors import HlError
from copytrade.hl.ledger_port import DowntimeRecord
from copytrade.hl.models import Candle, ClearinghouseState, Fill
from copytrade.hl.rest import HlRestClient
from copytrade.ledger.store import Ledger
from copytrade.paper.broker import PaperBroker
from copytrade.positions.book import PositionBook
from copytrade.positions.types import CLOSED, ShareState
from copytrade.recorder.ports import Backlog
from copytrade.scoring.models import CycleResult, WalletInputs
from copytrade.selection.backfill import Backfiller
from copytrade.selection.models import CandidateList

KIND_DOWNTIME = "downtime"
KIND_SCORE_CYCLE = "score_cycle"
_DAY_MS = 86_400_000
_HOUR_MS = 3_600_000
_FILLS_PER_REQUEST = 2_000


class LedgerDowntime:
    """``hl.ledger_port.DowntimeSink``: the feed's and the access monitor's downtime intervals (kind ``downtime``)."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def record_downtime(self, record: DowntimeRecord) -> None:
        self._ledger.append(
            KIND_DOWNTIME,
            {
                "kind": record.kind,
                "start_ms": record.start_ms,
                "end_ms": record.end_ms,
                "wallets": list(record.wallets),
            },
        )


class RestLeaderData:
    """``selection.StateSource``, ``positions.LeaderState`` and ``positions.LeaderFills`` over the REST client at one
    priority (CRITICAL for what an open or a reconciliation needs, SCORING for the selection cycle's joins)."""

    def __init__(self, rest: HlRestClient, priority: Priority) -> None:
        self._rest = rest
        self._priority = priority

    def clearinghouse_state(self, wallet: str) -> ClearinghouseState:
        return self._rest.clearinghouse_state(wallet, priority=self._priority)

    def user_fills_by_time(self, wallet: str, start_ms: int, end_ms: int) -> Sequence[Fill]:
        return self._rest.user_fills_by_time(wallet, start_ms, end_ms, priority=self._priority)


class RestCandles:
    """``recorder.ports.CandleSource`` over ``candleSnapshot`` at CRITICAL priority."""

    def __init__(self, rest: HlRestClient) -> None:
        self._rest = rest

    def fetch(self, coin: str, interval: str, start_ms: int, end_ms: int) -> Sequence[Candle]:
        return self._rest.candles(coin, interval, start_ms, end_ms, priority=Priority.CRITICAL)


class FollowedUniverse:
    """``recorder.ports.UniverseSource`` (F4.AC1): the core perps the wallets we follow or hold shares of traded over
    the lookback (``userFillsByTime``, SCORING priority), plus the coins of our open shares. HIP-3 markets are none
    in v0; the volume ranking only matters above ``recording.max_coins`` and is empty (always-recorded coins stay)."""

    def __init__(
        self,
        *,
        rest: HlRestClient,
        clock: Clock,
        wallets: Callable[[], frozenset[str]],
        held_coins: Callable[[], frozenset[str]],
    ) -> None:
        self._rest = rest
        self._clock = clock
        self._wallets = wallets
        self._held_coins = held_coins

    def traded_coins(self, lookback_days: int) -> frozenset[str]:
        now = self._clock.now_ms()
        coins = set(self._held_coins())
        for wallet in sorted(self._wallets()):
            start = now - lookback_days * _DAY_MS
            while True:
                page = self._rest.user_fills_by_time(wallet, start, None, priority=Priority.SCORING)
                coins.update(fill.coin for fill in page)
                if len(page) < _FILLS_PER_REQUEST:
                    break
                start = max(fill.time_ms for fill in page) + 1
        return frozenset(coins)

    def hip3_markets(self) -> Sequence[str]:
        return ()

    def volume_24h_usd(self) -> Mapping[str, Decimal]:
        return {}


class NoBacklog:
    """``recorder.ports.BacklogSource``: nothing is archived in v0 (F23 is not built), so nothing is waiting."""

    def unarchived_backlog(self) -> Backlog:
        return Backlog(days=0, gb=Decimal(0))


class MarkedAccount:
    """``risk.ports.AccountView``: paper equity = broker cash + unrealised P&L of every open position at the live mid.
    Unknown (``None``, A2) when a held coin has no mid or the mids are older than ``feed.stale_after_s``."""

    def __init__(
        self,
        *,
        broker: PaperBroker,
        mids: Callable[[], Mapping[str, Decimal]],
        mid_time_ms: Callable[[], int | None],
        clock: Clock,
        max_age_ms: int,
    ) -> None:
        self._broker = broker
        self._mids = mids
        self._mid_time_ms = mid_time_ms
        self._clock = clock
        self._max_age_ms = max_age_ms

    def equity_usd(self) -> Decimal | None:
        equity = self._broker.cash_usd()
        positions = self._broker.positions()
        if not positions:
            return equity
        stamped = self._mid_time_ms()
        if stamped is None or self._clock.now_ms() - stamped > self._max_age_ms:
            return None
        mids = self._mids()
        for position in positions:
            mid = mids.get(position.coin)
            if mid is None:
                return None
            equity += (mid - position.avg_entry_px) * position.qty
        return equity


class StoredReturns:
    """``risk.ports.ReturnsSource`` from the stored hourly candles (the F4 candle store): ``days * 24`` hourly close to
    close returns, oldest first, ending at the last closed hour; ``None`` when any of the hours is missing (the gate
    then counts the coin as correlated: fail closed)."""

    def __init__(self, *, get: Callable[[str, str, int, int], Sequence[Candle]], clock: Clock) -> None:
        self._get = get
        self._clock = clock

    def hourly_returns(self, coin: str, days: int) -> Sequence[Decimal] | None:
        hours = days * 24
        end_ms = self._clock.now_ms() // _HOUR_MS * _HOUR_MS
        start_ms = end_ms - (hours + 1) * _HOUR_MS
        try:
            candles = self._get(coin, "1h", start_ms, end_ms)
        except OSError:
            return None
        closes = {candle.open_ms: Decimal(candle.close) for candle in candles}
        series = [closes.get(start_ms + i * _HOUR_MS) for i in range(hours + 1)]
        if any(close is None or close <= 0 for close in series):
            return None
        values = [close for close in series if close is not None]
        return [later / earlier - 1 for earlier, later in pairwise(values)]


class BookShares:
    """``selection.OpenShareSource`` and ``recorder.ports.OpenCoinsSource`` over the share book: a wallet has open
    shares while any of its shares is not closed; the coins of those shares (pending entries included) are the ones
    whose candles and books matter. The book is read under the gate lock (the Telegram thread books flatten fills)."""

    def __init__(self, book: PositionBook, lock: AbstractContextManager[Any]) -> None:
        self._book = book
        self._lock = lock

    def _live(self) -> tuple[ShareState, ...]:
        with self._lock:
            return tuple(s for s in self._book.states() if s.status != CLOSED)

    def has_open_shares(self, wallet: str) -> bool:
        key = wallet.lower()
        return any(s.leader.lower() == key for s in self._live())

    def wallets(self) -> frozenset[str]:
        return frozenset(s.leader.lower() for s in self._live())

    def coins(self) -> frozenset[str]:
        return frozenset(s.coin for s in self._live())

    def coins_open_between(self, start_ms: int, end_ms: int) -> frozenset[str]:  # noqa: ARG002 - the port's window
        return self.coins()


class LedgerScores:
    """``scoring.models.ScoreStore``: one summary ``score_cycle`` ledger record per cycle (the full tables are in
    memory only in v0: replay and evaluation are not built)."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def append_cycle(self, result: CycleResult) -> None:
        self._ledger.append(
            KIND_SCORE_CYCLE,
            {
                "t_ms": result.t_ms,
                "wallets": len(result.scores),
                "eligible": [s.address for s in result.scores if s.eligible],
            },
        )


class PacedInputs:
    """``selection.InputsProvider`` that keeps the scoring inputs fresh in small paced slices instead of one blocking
    burst per cycle. The cycle's own ``refresh`` calls do nothing; ``work()`` (the loop calls it every
    ``SELECTION_WORK_INTERVAL_S``) fetches the next wallet that was never fetched and, once the first backfill is
    complete, refreshes the candidates in turn. The REST client behind it never sleeps (a request that does not fit the
    rate budget fails at once and is tried again later), so one ``work()`` blocks for network latency only."""

    def __init__(self, backfiller: Backfiller) -> None:
        self._backfiller = backfiller
        self._candidates: list[str] = []
        self._screening = False
        self._turn = 0

    @property
    def complete(self) -> bool:
        return self._backfiller.complete

    def set_candidates(self, wallets: Sequence[str]) -> None:
        self._screening = False
        self._candidates = list(dict.fromkeys(wallet.lower() for wallet in wallets))
        self._turn = 0
        self._backfiller.set_candidates(self._candidates)

    def set_screen_plan(self, plan: CandidateList, *, keep: Iterable[str]) -> None:
        """Start a cycle of the candidate screen: ``work`` screens the list in order (one wallet a slice), and refreshes
        the wallets that are kept or screened OK."""
        self._screening = True
        self._turn = 0
        self._backfiller.set_screen_plan(plan, keep=keep)

    def candidates(self) -> list[str]:
        """The wallets to refresh and score: the kept ones plus those screened OK."""
        return self._backfiller.candidates()

    def rotate(self, wallets: Iterable[str]) -> None:
        self._backfiller.rotate(wallets)

    def refresh(self, wallet: str) -> None:
        """The cycle's per-wallet refresh: nothing to do, ``work`` keeps the data fresh."""

    def inputs(self, wallet: str, t_ms: int) -> WalletInputs | None:
        return self._backfiller.inputs(wallet, t_ms)

    def work(self) -> None:
        """One slice: the next unfetched candidate, else the next candidate in turn. Never raises for a failed fetch."""
        if self._backfiller.step():
            return
        candidates = self._backfiller.candidates() if self._screening else self._candidates
        if not candidates:
            return
        wallet = candidates[self._turn % len(candidates)]
        self._turn += 1
        try:
            self._backfiller.refresh(wallet)
        except (HlError, OSError):
            return
