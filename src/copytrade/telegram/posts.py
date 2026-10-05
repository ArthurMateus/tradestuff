"""Trade posts (F14.AC2, AC3): one Telegram post per coin position, edited as it changes and closed with its result.

The text is rendered from the share book; the leverage, the realised P&L and the exit reason come from the ledger
(the book has none of them), read once per share or once per closing position.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal

from copytrade.ledger.store import Ledger
from copytrade.positions.types import OPEN, ShareState

GREEN, RED = "\U0001f7e2", "\U0001f534"
_CLOSING_EVENTS = frozenset({"closed", "liquidated", "delisted"})
_LEVERAGE_UNKNOWN = "n/a"
_FACT_KINDS = frozenset({"paper_order", "trade", "share_state"})


def leader_label(address: str) -> str:
    """``0xaaaa...aaaa``: the first 6 and last 4 characters."""
    return f"{address[:6]}...{address[-4:]}" if len(address) > 10 else address


@dataclass(frozen=True)
class ShareLine:
    leader: str
    entry_px: str
    stop_px: str


@dataclass(frozen=True)
class PostView:
    coin: str
    is_long: bool
    leverage: str
    shares: tuple[ShareLine, ...]


@dataclass(frozen=True)
class Closing:
    pnl_usd: Decimal
    reason: str


@dataclass
class Post:
    """What we know about the Telegram message of one coin position."""

    view: PostView
    share_ids: set[str]
    message_id: int | None = None
    send_pending: bool = True
    last_text: str = ""
    last_edit_ms: int = 0


def render(view: PostView, closing: Closing | None = None) -> str:
    side = "LONG" if view.is_long else "SHORT"
    head = f"{GREEN if view.is_long else RED} PAPER {side} {view.coin}" + (" CLOSED" if closing else "")
    lines = [head, f"leverage: {view.leverage}"]
    lines += [f"{leader_label(s.leader)} entry {s.entry_px} stop {s.stop_px}" for s in view.shares]
    if closing is not None:
        lines += [f"realised P&L: {closing.pnl_usd:+.2f} USD", f"exit reason: {closing.reason}"]
    lines.append("why unavailable")
    return "\n".join(lines)


class LedgerFacts:
    """The few ledger facts a post needs: the leverage of a share, and a closed position's realised P&L and exit reason.

    Kept in memory and fed from the ledger FILE incrementally: the first call reads what is stored (once, on the
    calling thread, only the lines of the three kinds it needs are decoded), every later call reads only what was
    appended since. Never a hash-verified walk of the whole ledger, so a post costs the same after weeks of trading."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger
        self._lock = threading.Lock()
        self._offset = 0
        self._leverage: dict[str, str] = {}
        self._pnl: dict[str, Decimal] = {}
        self._reason: dict[str, tuple[int, str]] = {}

    def leverage(self, share_id: str) -> str:
        with self._lock:
            self._catch_up()
            return self._leverage.get(share_id, _LEVERAGE_UNKNOWN)

    def closing(self, share_ids: set[str]) -> Closing:
        with self._lock:
            self._catch_up()
            pnl = sum((self._pnl.get(share_id, Decimal(0)) for share_id in share_ids), Decimal(0))
            # the last closing event of any of the shares that carried a reason (ledger order)
            reasons = [self._reason[share_id] for share_id in share_ids if share_id in self._reason]
            return Closing(pnl, max(reasons)[1] if reasons else "unknown")

    def _catch_up(self) -> None:
        records, self._offset = self._ledger.read_from(self._offset, kinds=_FACT_KINDS)
        for record in records:
            payload = record.payload
            share_id = payload.get("share_id")
            if share_id is None:
                continue
            if record.kind == "paper_order":
                lev = payload.get("leverage")
                if lev and share_id not in self._leverage:
                    self._leverage[share_id] = f"{lev}x"
            elif record.kind == "trade":
                self._pnl[share_id] = self._pnl.get(share_id, Decimal(0)) + Decimal(str(payload["pnl_usd"]))
            elif record.kind == "share_state" and payload.get("event") in _CLOSING_EVENTS and payload.get("reason"):
                self._reason[share_id] = (record.seq, str(payload["reason"]))


def live_views(states: tuple[ShareState, ...], facts: LedgerFacts) -> dict[str, tuple[PostView, set[str]]]:
    """Open shares grouped by coin: the view of each coin position and the ids of its shares."""
    grouped: dict[str, list[ShareState]] = {}
    for state in states:
        if state.status == OPEN:
            grouped.setdefault(state.coin, []).append(state)
    return {
        coin: (
            PostView(
                coin=coin,
                is_long=shares[0].is_long,
                leverage=facts.leverage(shares[0].share_id),
                shares=tuple(ShareLine(s.leader, str(s.entry_px), str(s.current_stop_px)) for s in shares),
            ),
            {s.share_id for s in shares},
        )
        for coin, shares in grouped.items()
    }


__all__ = ["Closing", "LedgerFacts", "Post", "PostView", "leader_label", "live_views", "render"]
