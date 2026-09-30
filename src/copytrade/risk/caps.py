"""The open-risk and notional caps of an entry (F10.AC3, AC9). Pure Decimal arithmetic.

A cap is a limit on USD the book may lose if every stop fills (open risk), or on a position's notional. An entry is
reduced to the largest size that fits every cap, and the $10 minimum is then applied to what is left.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Context, Decimal

from copytrade.core.money import Price, Qty
from copytrade.paper.settings import MONEY_CONTEXT
from copytrade.risk.settings import RiskSettings
from copytrade.risk.types import ShareExposure

_FLOOR = Context(prec=60, rounding=ROUND_DOWN)
_ZERO = Decimal(0)

SHARE_RISK = "share_risk"
SYMBOL_RISK = "symbol_risk"
LEADER_RISK = "leader_risk"
TOTAL_RISK = "total_risk"
BTC_BUCKET_RISK = "btc_bucket_risk"
POSITION_NOTIONAL = "position_notional"


@dataclass(frozen=True)
class Cap:
    """One cap: ``limit_usd`` and what is already ``used_usd`` (open risk, or notional for ``position_notional``)."""

    name: str
    limit_usd: Decimal
    used_usd: Decimal

    @property
    def room_usd(self) -> Decimal:
        """What is left under the cap, never negative."""
        return max(_ZERO, MONEY_CONTEXT.subtract(self.limit_usd, self.used_usd))

    def max_notional_usd(self, stop_distance_fraction: Decimal) -> Decimal:
        """The largest notional whose risk at the stop fits the room (``room / stop distance``); a notional cap
        is its own room."""
        if self.name == POSITION_NOTIONAL:
            return self.room_usd
        return _FLOOR.divide(self.room_usd, stop_distance_fraction)


def _fraction_of(equity_usd: Decimal, fraction: Decimal) -> Decimal:
    return MONEY_CONTEXT.multiply(equity_usd, fraction)


def _sum(values: Sequence[Decimal]) -> Decimal:
    total = _ZERO
    for value in values:
        total = MONEY_CONTEXT.add(total, value)
    return total


def entry_caps(  # noqa: PLR0913 - one cap per config key
    *,
    settings: RiskSettings,
    equity_usd: Decimal,
    shares: Sequence[ShareExposure],
    coin: str,
    leader: str,
    share_used_usd: Decimal,
    existing_qty: Qty,
    decision_px: Price,
    bucket_used_usd: Decimal | None,
) -> tuple[Cap, ...]:
    """Every cap an entry on ``coin`` by ``leader`` is held to.

    ``share_used_usd`` is the open risk of the share the order enlarges (0 for a new share). ``bucket_used_usd`` is
    the same-direction open risk of the BTC bucket, or ``None`` when ``coin`` is not in the bucket (no bucket cap).
    ``existing_qty`` is the merged position's current quantity (absolute); its notional at ``decision_px`` is used up.
    """
    caps = [
        Cap(SHARE_RISK, _fraction_of(equity_usd, settings.max_share_risk_fraction), share_used_usd),
        Cap(
            SYMBOL_RISK,
            _fraction_of(equity_usd, settings.max_symbol_open_risk_fraction),
            _sum([s.open_risk_usd for s in shares if s.coin == coin]),
        ),
        Cap(
            LEADER_RISK,
            _fraction_of(equity_usd, settings.max_leader_open_risk_fraction),
            _sum([s.open_risk_usd for s in shares if s.leader == leader]),
        ),
        Cap(
            TOTAL_RISK,
            _fraction_of(equity_usd, settings.max_total_open_risk_fraction),
            _sum([s.open_risk_usd for s in shares]),
        ),
    ]
    if bucket_used_usd is not None:
        caps.append(
            Cap(BTC_BUCKET_RISK, _fraction_of(equity_usd, settings.max_btc_bucket_open_risk_fraction), bucket_used_usd)
        )
    caps.append(
        Cap(
            POSITION_NOTIONAL,
            _fraction_of(equity_usd, settings.max_position_notional_equity_mult),
            MONEY_CONTEXT.multiply(existing_qty, decision_px),
        )
    )
    return tuple(caps)
