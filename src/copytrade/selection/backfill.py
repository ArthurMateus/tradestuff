"""Incremental candidate backfill under the rate budget (F6.AC4)."""

from __future__ import annotations

from collections.abc import Sequence

from copytrade.core.clock import Clock
from copytrade.core.config import Config
from copytrade.hl.rest import HlRestClient
from copytrade.recorder.ports import CandleSource
from copytrade.scoring.models import WalletInputs


class Backfiller:
    """Fetches scoring inputs for candidate wallets through the real REST client at SCORING priority (which paces
    itself on the rate budget). Satisfies ``copytrade.selection.models.InputsProvider``.

    Per wallet: fills (``userFillsByTime``; the first fetch starts ``scoring.window_days`` back, later ones after the
    last fill already held, de-duplicated by ``tid``), ``portfolio``, ``clearinghouseState``, ``userRole`` and, for each
    core perp coin seen in the fills, 1h candles through ``candles``. ``hl.Fill`` becomes ``scoring.Fill``; a fill
    whose ``dir`` contains ``iquidat`` has ``liquidation=True``.
    """

    def __init__(self, *, config: Config, clock: Clock, rest: HlRestClient, candles: CandleSource) -> None:
        raise NotImplementedError

    @property
    def complete(self) -> bool:
        """True once every wallet of the candidate list has been fetched at least once, then latched. False before
        ``set_candidates`` has been called (fail closed)."""
        raise NotImplementedError

    def set_candidates(self, wallets: Sequence[str]) -> None:
        """Set the candidate list (lower-cased, de-duplicated, order kept). Data already fetched is kept."""
        raise NotImplementedError

    def step(self) -> bool:
        """Fetch the next wallet that has never been fetched (blocking while the budget paces it). A wallet whose
        fetch raises ``HlError`` is left undone and retried after the others. Returns False when there is nothing
        left to fetch."""
        raise NotImplementedError

    def refresh(self, wallet: str) -> None:
        """Incremental fetch for one wallet. An ``HlError`` leaves the old data in place and propagates."""
        raise NotImplementedError

    def inputs(self, wallet: str, t_ms: int) -> WalletInputs | None:
        raise NotImplementedError
