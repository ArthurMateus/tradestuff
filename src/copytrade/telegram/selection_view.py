"""U4 port: the read-only view of leader selection that the Telegram bot reads (the bot never imports the manager).

The runner wiring supplies an adapter over the follow manager and the backfill progress snapshot.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol


@dataclass(frozen=True)
class LeaderRow:
    """One followed wallet. ``address`` is the full address; the bot shortens it for display."""

    address: str
    rank: int | None
    score: Decimal | None
    follow_start_ms: int
    open_copies: int
    paused: bool


@dataclass(frozen=True)
class PassProgress:
    """Snapshot of the current (or last) selection pass. ``candidates_done`` = wallets whose backfill completed."""

    state: Literal["idle", "running", "complete"]
    candidates_total: int
    candidates_done: int
    screened: int
    screen_ok: int
    rejected: int
    cooling: int
    dropped: int
    followed: int
    started_ms: int | None


@dataclass(frozen=True)
class SelectionEvent:
    """A one-off selection event. ``pass_id`` identifies the pass. kind: pass_complete | leader_followed | leader_dropped."""

    kind: Literal["pass_complete", "leader_followed", "leader_dropped"]
    pass_id: int
    address: str | None = None
    rank: int | None = None
    reason: str | None = None


class SelectionView(Protocol):
    def followed(self) -> Sequence[LeaderRow]:
        """The followed wallets, in rank order."""
        raise NotImplementedError

    def progress(self) -> PassProgress:
        """The pass progress snapshot."""
        raise NotImplementedError

    def drain_events(self) -> Sequence[SelectionEvent]:
        """Events since the last call (the adapter may replay; the bot de-duplicates)."""
        raise NotImplementedError
