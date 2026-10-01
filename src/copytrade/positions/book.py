"""The share book (F12): every share the manager has ever held, in insertion order, and the F10 ``ShareBook`` port.

The book is built first and passed to ``RiskGate(shares=book)``, then to the manager (the two are circular otherwise).
Only the manager writes to it. State is in memory only (a restart rebuilds it from the ledger: F13/R0).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from copytrade.core.money import Price
from copytrade.positions.rules import open_risk_usd
from copytrade.positions.types import CLOSED, OPEN, ShareState
from copytrade.risk.types import ShareExposure


class PositionBook:
    """Implements ``risk.ports.ShareBook``: ``open_shares`` lists the shares with status ``open`` (a pending entry is
    not listed, the gate counts those itself) with ``open_risk_usd >= 0``."""

    def __init__(self) -> None:
        self._states: dict[str, ShareState] = {}
        self._marks: dict[str, Price] = {}

    # ------------------------------------------------------------------------------------------------ reads

    def open_shares(self) -> tuple[ShareExposure, ...]:
        return tuple(
            ShareExposure(
                share_id=state.share_id,
                trade_id=state.trade_id,
                coin=state.coin,
                leader=state.leader,
                is_long=state.is_long,
                qty=state.qty,
                entry_px=state.entry_px,
                stop_px=state.current_stop_px,
                mark_px=self._marks.get(state.coin, state.entry_px),
                open_risk_usd=state.open_risk_usd,
            )
            for state in self._states.values()
            if state.status == OPEN
        )

    def state(self, share_id: str) -> ShareState | None:
        return self._states.get(share_id)

    def states(self) -> tuple[ShareState, ...]:
        """Every share ever booked, in the order it was added."""
        return tuple(self._states.values())

    def active(self, leader: str, coin: str) -> ShareState | None:
        """The leader's share on ``coin`` that is not closed (pending entry or open); a leader has one position per
        coin, so there is at most one."""
        for state in self._states.values():
            if state.leader == leader and state.coin == coin and state.status != CLOSED:
                return state
        return None

    def mark_px(self, coin: str) -> Price | None:
        return self._marks.get(coin)

    # ------------------------------------------------------------------------------------- writes (manager)

    def add(self, state: ShareState) -> None:
        """Book a new share.

        Raises:
            ValueError: the share id is already booked (share ids are unique per signal).
        """
        if state.share_id in self._states:
            raise ValueError("share id already booked")
        self._states[state.share_id] = state

    def update(self, share_id: str, **changes: Any) -> ShareState:
        """Change fields of a booked share and recompute what follows from them: ``open_risk_usd`` (0 unless the
        share is open) and ``max_committed_risk_usd`` (never lowered).

        Raises:
            KeyError: no such share.
        """
        current = self._states[share_id]
        state = replace(current, **changes)
        risk = (
            open_risk_usd(is_long=state.is_long, qty=state.qty, entry_px=state.entry_px, stop_px=state.current_stop_px)
            if state.status == OPEN
            else Decimal(0)
        )
        state = replace(state, open_risk_usd=risk, max_committed_risk_usd=max(current.max_committed_risk_usd, risk))
        self._states[share_id] = state
        return state

    def set_mark(self, coin: str, px: Price) -> None:
        self._marks[coin] = px


__all__ = ["PositionBook"]
