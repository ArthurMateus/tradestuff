"""Helpers for the F10 review round 1 tests. Real gate, real broker, real ledger; only OS-level failures are injected."""

from __future__ import annotations

import errno
import os
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

import pytest

from copytrade.core.money import Price, Qty
from copytrade.risk.types import Decision, ShareExposure
from tests.risk.conftest import NewRisk
from tests.risk.helpers import RiskEnv, uncorrelated_returns, wide_returns

D = Decimal


def mk(new_risk: NewRisk, **kwargs: object) -> RiskEnv:
    """A gate that has taken its first equity mark (the state every pre-B4 test assumed)."""
    kwargs.setdefault("marked", True)
    return new_risk(**kwargs)


def outside_bucket() -> dict[str, list[Decimal]]:
    """Returns that put ETH and DOGE outside the BTC bucket (so the bucket cap does not apply to them)."""
    return {"BTC": wide_returns(), "ETH": uncorrelated_returns(), "DOGE": uncorrelated_returns()}


def margin_of(decision: Decision) -> Decimal:
    """The isolated margin of the order a decision approved: final notional / leverage (``posted_margin_usd`` is the
    margin the coin's position already had, not this order's)."""
    assert decision.final_notional_usd is not None and decision.leverage is not None
    return decision.final_notional_usd / decision.leverage


def sent(r: RiskEnv) -> int:
    """How many tokens the gate has issued (every order and stop the broker was sent)."""
    return len(r.authority.issued)


def book_share(r: RiskEnv, share_id: str, coin: str, *, qty: str, entry: str = "100", stop: str = "98.5",
               leader: str = "L1", is_long: bool = True) -> None:
    """What F12 would do after an entry filled: list the share in the share book."""
    risk = D(qty) * abs(D(entry) - D(stop))
    r.shares.shares.append(
        ShareExposure(share_id=share_id, trade_id=f"T-{share_id}", coin=coin, leader=leader, is_long=is_long,
                      qty=Qty(qty), entry_px=Price(entry), stop_px=Price(stop), mark_px=Price(entry),
                      open_risk_usd=risk)
    )


def forget_share(r: RiskEnv, share_id: str) -> None:
    """The share book loses a share the broker still holds (F12 bug, restart, reconstruction gap)."""
    r.shares.shares[:] = [s for s in r.shares.shares if s.share_id != share_id]


@contextmanager
def failing_ledger_writes(marker: bytes) -> Iterator[None]:
    """``os.write`` raises ``OSError(EIO)`` for any ledger line containing ``marker`` (the OS boundary, not the Ledger)."""
    real = os.write

    def bad(fd: int, data: bytes | memoryview) -> int:
        if marker in bytes(data):
            raise OSError(errno.EIO, "injected disk failure")
        return real(fd, data)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "write", bad)
        yield
