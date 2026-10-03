"""Builders and boundary doubles for the F6 tests.

Real code in every test: F1 config, F2 ledger, F3 REST client + budget + WebSocket feed, F5 scoring data types (and, in
the run_cycle tests, F5's scorer over its hand-built ``healthy`` wallets), F7 signal detector. Only true boundaries are
faked: the clock, HTTP, the WebSocket connector, the alert sink, the leaderboard source, the candle source, the
clearinghouse-state source, the open-share source (F12) and the score store.

Nothing here decides a selection outcome: ``score``/``result`` only build the data F5 would produce.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from copytrade.core.config import Config
from copytrade.core.domain import ActionKind
from copytrade.core.events import Alert
from copytrade.hl.errors import WsUserLimitError
from copytrade.hl.models import ClearinghouseState
from copytrade.ledger.store import Ledger
from copytrade.scoring.models import CycleResult, Metrics, WalletInputs, WalletScore
from copytrade.selection.manager import FollowManager
from copytrade.selection.models import Decision, Follow, SelectionState
from tests.hl.support import T0, FeedRig, RecordingAlerts, make_config, make_feed
from tests.scoring.helpers import PAPER_COSTS, MemoryStore
from tests.scoring.wallets import PERMISSIVE_CFG, T, healthy
from tests.signals.helpers import Rig as DetectorRig
from tests.signals.helpers import make_rig as make_detector_rig
from tests.signals.helpers import state as clearinghouse_state

D = Decimal
HOUR = 3_600_000
MINUTE = 60_000
SECOND = 1_000
NOW = 1_800_000_000_000  # an arbitrary epoch ms for policy-level tests


def w(i: int) -> str:
    """A valid lower-case wallet address, distinct per ``i`` (``w(1) < w(2)`` as text, which is the tie-break order)."""
    return "0x" + f"{i:040x}"


# --------------------------------------------------------------------------------------------------
# F5 data (what the scorer would hand us)
# --------------------------------------------------------------------------------------------------


def score(
    i: int,
    rank: int | None,
    value: str | None = None,
    *,
    eligible: bool = True,
    reasons: Sequence[str] = (),
    flags: Sequence[str] = (),
) -> WalletScore:
    """A ``WalletScore``. An eligible wallet with no ``value`` gets a score falling 0.01 per rank from 0.90."""
    if eligible and value is None:
        assert rank is not None
        value = str(D("0.90") - D("0.01") * rank)
    return WalletScore(
        address=w(i),
        eligible=eligible,
        reasons=tuple(reasons),
        blowup_flags=tuple(flags),
        metrics=None,
        components=None,
        score=D(value) if (eligible and value is not None) else None,
        rank=rank if eligible else None,
        input_hashes={},
        dsr_resolution=None,
    )


def ranked(*ids: int, t_ms: int = NOW) -> list[WalletScore]:
    """Eligible wallets ``ids`` ranked 1..n in the order given, scores falling 0.01 per rank from 0.89."""
    return [score(i, r) for r, i in enumerate(ids, start=1)]


def cycle(scores: Sequence[WalletScore], t_ms: int = NOW) -> CycleResult:
    """Eligible first in rank order, then the ineligible by address (F5's ordering)."""
    eligible = sorted((s for s in scores if s.eligible), key=lambda s: s.rank or 0)
    rest = sorted((s for s in scores if not s.eligible), key=lambda s: s.address)
    return CycleResult(t_ms=t_ms, scores=(*eligible, *rest))


def state(followed: dict[int, tuple[int, int]] | None = None, joins: dict[int, int] | None = None) -> SelectionState:
    """``followed``: wallet id -> (followed_at_ms, drop_streak). ``joins``: wallet id -> join streak."""
    return SelectionState(
        followed={w(i): Follow(followed_at_ms=at, drop_streak=streak) for i, (at, streak) in (followed or {}).items()},
        join_streaks={w(i): n for i, n in (joins or {}).items()},
    )


def kinds(decisions: Sequence[Decision]) -> list[tuple[str, str]]:
    return [(d.kind, d.wallet) for d in decisions]


def of_kind(decisions: Sequence[Decision], kind: str) -> list[Decision]:
    return [d for d in decisions if d.kind == kind]


def cfg(**overrides: Any) -> Config:
    """The valid fixture config, really loaded by F1; dotted keys are written with ``__`` (``select__join_rank=9``)."""
    return make_config(**overrides)


# --------------------------------------------------------------------------------------------------
# leaderboard
# --------------------------------------------------------------------------------------------------


def leaderboard_body(rows: int, first: Sequence[str] = ()) -> bytes:
    """A leaderboard JSON (recorded shape, see tests/fixtures/exchange/hl/leaderboard.json) with ``rows`` rows whose
    first rows are ``first``."""
    addresses = list(first)
    i = 1_000_000
    while len(addresses) < rows:
        addresses.append(w(i))
        i += 1
    template = json.loads((Path(__file__).resolve().parent.parent / "fixtures/exchange/hl/leaderboard.json").read_text())
    # the recorded row's accountValue (1000.25) is below the G11 prefilter minimum; rows here must pass it, so use the
    # configured default minimum (not a hardcoded number)
    row = {**template["leaderboardRows"][0], "accountValue": str(cfg()["gate.min_account_value_usd"])}
    return json.dumps({"leaderboardRows": [{**row, "ethAddress": a} for a in addresses[:rows]]}).encode()


class FakeLeaderboard:
    """LeaderboardSource. ``outcome`` is the next response: bytes, or an exception to raise."""

    def __init__(self, body: bytes | Exception) -> None:
        self.outcome: bytes | Exception = body
        self.calls = 0

    def fetch(self) -> bytes:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


# --------------------------------------------------------------------------------------------------
# other boundaries
# --------------------------------------------------------------------------------------------------


class FakeStates:
    """StateSource: the wallet's clearinghouse state (``held`` coin -> signed size). ``fail`` raises OSError."""

    def __init__(self) -> None:
        self.fail: set[str] = set()
        self.held: dict[str, dict[str, str]] = {}
        self.calls: list[str] = []

    def clearinghouse_state(self, wallet: str) -> ClearinghouseState:
        self.calls.append(wallet)
        if wallet in self.fail or "*" in self.fail:
            raise OSError("clearinghouseState unavailable")
        return clearinghouse_state(self.held.get(wallet), time_ms=T0)


class FakeShares:
    """OpenShareSource (F12 owns the real one): the wallets that still have an open share."""

    def __init__(self) -> None:
        self.open: set[str] = set()

    def has_open_shares(self, wallet: str) -> bool:
        return wallet in self.open


class FakeInputs:
    """InputsProvider over hand-built wallets (F5 ``healthy``). ``complete`` is under the test's control."""

    def __init__(self, wallets: Sequence[WalletInputs], *, complete: bool = True) -> None:
        self.wallets: dict[str, WalletInputs] = {x.address.lower(): x for x in wallets}
        self.complete = complete
        self.candidates: list[str] = []
        self.refreshed: list[str] = []

    def set_candidates(self, wallets: Sequence[str]) -> None:
        self.candidates = list(wallets)

    def refresh(self, wallet: str) -> None:
        self.refreshed.append(wallet)

    def inputs(self, wallet: str, t_ms: int) -> WalletInputs | None:
        return self.wallets.get(wallet.lower())


class AdvancingStore(MemoryStore):
    """ScoreStore that makes the (fake) clock move while a cycle is being persisted, to simulate a slow cycle."""

    def __init__(self, advance: Callable[[int], None]) -> None:
        super().__init__()
        self._advance = advance
        self.next_ms = 0

    def append_cycle(self, result: CycleResult) -> None:
        super().append_cycle(result)
        if self.next_ms:
            self._advance(self.next_ms)


class Spy:
    """Observes calls to the real feed and the real detector and forwards them. It decides nothing."""

    def __init__(self, feed: Any, registry: Any) -> None:
        self.feed = feed
        self.registry = registry
        self.log: list[tuple[str, str]] = []
        self.subscribed: set[str] = set()
        self.max_subscribed = 0
        self.limit_errors = 0

    # WalletFeed
    def subscribe_user(self, wallet: str) -> None:
        self.log.append(("subscribe", wallet))
        try:
            self.feed.subscribe_user(wallet)
        except WsUserLimitError:
            self.limit_errors += 1
            raise
        self.subscribed.add(wallet)
        self.max_subscribed = max(self.max_subscribed, len(self.subscribed))

    def unsubscribe_user(self, wallet: str) -> None:
        self.log.append(("unsubscribe", wallet))
        self.feed.unsubscribe_user(wallet)
        self.subscribed.discard(wallet)

    # FollowRegistry
    def begin_follow(self, wallet: str, state: ClearinghouseState, followed_at_ms: int) -> None:
        self.log.append(("begin_follow", wallet))
        self.registry.begin_follow(wallet, state, followed_at_ms)

    def end_follow(self, wallet: str) -> None:
        self.log.append(("end_follow", wallet))
        self.registry.end_follow(wallet)

    def calls(self, name: str) -> list[str]:
        return [wallet for call, wallet in self.log if call == name]

    def index(self, name: str, wallet: str) -> int:
        return self.log.index((name, wallet))


@dataclass
class Rig:
    cfg: Config
    feed_rig: FeedRig
    detector: DetectorRig
    spy: Spy
    manager: FollowManager
    alerts: RecordingAlerts
    states: FakeStates
    shares: FakeShares
    board: FakeLeaderboard
    inputs: Any
    store: MemoryStore
    ledger: Ledger
    now: int = field(default=0)

    @property
    def clock(self) -> Any:
        return self.feed_rig.clock

    def records(self, kind: str) -> list[dict[str, Any]]:
        return [dict(r.payload) for r in self.ledger.records() if r.kind == kind]

    def advance(self, ms: int) -> None:
        self.clock.advance(ms)


def make_rig(
    directory: Path,
    *,
    inputs: Any = None,
    board: FakeLeaderboard | None = None,
    store: MemoryStore | None = None,
    start_ms: int | None = None,
    **overrides: Any,
) -> Rig:
    """Real feed (over a fake connector), real detector and ledger, real manager. The clock is shared."""
    feed_rig = make_feed(**overrides)
    if start_ms is not None:
        feed_rig.clock.now = start_ms
    detector = make_detector_rig(directory, follow=(), clock=feed_rig.clock, **overrides)
    spy = Spy(feed_rig.feed, detector.detector)
    alerts, states, shares = RecordingAlerts(), FakeStates(), FakeShares()
    board = board or FakeLeaderboard(leaderboard_body(1000))
    inputs = inputs if inputs is not None else FakeInputs([])
    store = store or MemoryStore()
    config = feed_rig.rig.cfg
    manager = FollowManager(
        config=config,
        clock=feed_rig.clock,
        ledger=detector.ledger,
        alerts=alerts,
        feed=spy,
        registry=spy,
        states=states,
        shares=shares,
        leaderboard=board,
        inputs=inputs,
        scores=store,
        costs=PAPER_COSTS,
    )
    return Rig(config, feed_rig, detector, spy, manager, alerts, states, shares, board, inputs, store, detector.ledger)


@contextmanager
def rig_in_tmp(**kwargs: Any) -> Iterator[Rig]:
    """A rig under a throw-away directory (for Hypothesis tests, which cannot use function-scoped fixtures)."""
    with tempfile.TemporaryDirectory(prefix="f6rig") as tmp:
        r = make_rig(Path(tmp), **kwargs)
        try:
            yield r
        finally:
            r.ledger.close()


def join_all(rig: Rig, ids: Sequence[int], *, now_ms: int = NOW, cycles: int = 2) -> int:
    """Run ``cycles`` applied cycles in which wallets ``ids`` are ranked 1..n; return the time of the last one."""
    t = now_ms
    for _ in range(cycles):
        rig.manager.apply_cycle(cycle(ranked(*ids), t), now_ms=t)
        t += MINUTE
    return t - MINUTE


def healthy_wallets(n: int) -> list[WalletInputs]:
    """``n`` eligible wallets (F5's ``healthy``, equal scores, so the rank order is the address order)."""
    return [healthy(w(i)) for i in range(1, n + 1)]


# Config that makes F5's hand-built ``healthy`` wallets eligible (cycle time T = day 300).
HEALTHY_OVERRIDES: dict[str, Any] = {k.replace(".", "__"): v for k, v in PERMISSIVE_CFG.items()}
HEALTHY_START_MS = T
ENTRY_ACTIONS = (ActionKind.OPEN, ActionKind.ADD)
EXIT_ACTIONS = (ActionKind.REDUCE, ActionKind.CLOSE)


def alert_kinds(alerts: RecordingAlerts) -> list[str]:
    return [a.kind for a in alerts.sent]


__all__ = [
    "D", "HOUR", "MINUTE", "SECOND", "NOW", "Alert", "T0", "w", "score", "ranked", "cycle", "state", "kinds",
    "of_kind", "cfg", "leaderboard_body", "FakeLeaderboard", "FakeStates", "FakeShares", "FakeInputs",
    "AdvancingStore", "Spy", "Rig", "make_rig", "rig_in_tmp", "join_all", "healthy_wallets", "HEALTHY_OVERRIDES",
    "HEALTHY_START_MS", "ENTRY_ACTIONS", "EXIT_ACTIONS", "alert_kinds", "Metrics",
]


def established(directory: Path, *, n: int = 8, extra: Sequence[WalletInputs] = (), **kwargs: Any) -> Rig:
    """A rig whose provider holds ``n`` eligible wallets w1..wn (plus ``extra``), which are already followed.

    The clock stands at F5's cycle time, the backfill is complete, the leaderboard is healthy (1000 rows, w1..wn and
    the extras first). Each ``run_cycle`` here is at the same instant, so no input goes stale.
    """
    provider = FakeInputs([*healthy_wallets(n), *extra], complete=True)
    rig = make_rig(directory, inputs=provider, start_ms=HEALTHY_START_MS, **HEALTHY_OVERRIDES, **kwargs)
    rig.board.outcome = leaderboard_body(1000, first=[w(i) for i in range(1, n + 1)])
    for _ in range(2):
        rig.manager.run_cycle(p95_latency_s=D(3))
    assert rig.manager.followed == frozenset(w(i) for i in range(1, n + 1))
    return rig
