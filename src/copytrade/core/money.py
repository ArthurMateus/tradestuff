"""Money and units (F1.AC4, invariants A6 and A9).

Every money value is a ``Decimal`` subclass. Constructing one from a binary ``float`` (or ``bool``)
raises ``TypeError``; NaN and infinities raise ``ValueError`` (or ``decimal.InvalidOperation``).
Accepted inputs: ``Decimal``, ``int`` and ``str``.

Rounding follows the Hyperliquid perp rule:
- price: at most 5 significant figures and at most ``6 - sz_decimals`` decimals; integer prices
  are always allowed. ``round_price`` returns the nearest valid price.
- size: rounded toward zero to ``sz_decimals`` decimals (never increases exposure).

Interface stub written by the test designer. The developer owns the implementation.
"""

from __future__ import annotations

from decimal import Decimal


class Price(Decimal):
    """A price in USD per unit of the coin."""

    def __new__(cls, value: Decimal | int | str) -> Price:
        raise NotImplementedError


class Qty(Decimal):
    """A quantity in coin units (not notional)."""

    def __new__(cls, value: Decimal | int | str) -> Qty:
        raise NotImplementedError


class Notional(Decimal):
    """A notional value in USD (qty x price)."""

    def __new__(cls, value: Decimal | int | str) -> Notional:
        raise NotImplementedError


class Fee(Decimal):
    """A fee in USD."""

    def __new__(cls, value: Decimal | int | str) -> Fee:
        raise NotImplementedError


class Funding(Decimal):
    """A funding payment in USD (signed)."""

    def __new__(cls, value: Decimal | int | str) -> Funding:
        raise NotImplementedError


class Pnl(Decimal):
    """A profit or loss in USD (signed)."""

    def __new__(cls, value: Decimal | int | str) -> Pnl:
        raise NotImplementedError


def round_price(px: Decimal, sz_decimals: int) -> Price:
    """Round a positive price to the nearest valid exchange price.

    Raises:
        TypeError: ``px`` is a float.
        ValueError: ``px`` <= 0, NaN or infinite; ``sz_decimals`` outside 0..6.
    """
    raise NotImplementedError


def round_size(qty: Decimal, sz_decimals: int) -> Qty:
    """Round a size toward zero to ``sz_decimals`` decimals.

    Raises:
        TypeError: ``qty`` is a float.
        ValueError: NaN or infinite ``qty``; ``sz_decimals`` outside 0..6.
    """
    raise NotImplementedError
