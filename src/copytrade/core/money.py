"""Money and units (F1.AC4, invariants A6 and A9).

Every money value is a ``Decimal`` subclass. Constructing one from a binary ``float`` (or ``bool``)
raises ``TypeError``; NaN, infinities and malformed strings raise ``ValueError``. Accepted inputs:
``Decimal``, ``int`` and ``str`` (plain ASCII decimal notation, optionally with an exponent).
Arithmetic with a float raises ``TypeError`` (``Decimal`` semantics).

Rounding follows the Hyperliquid perp rule:

- price: at most 5 significant figures and at most ``6 - sz_decimals`` decimals; integer prices
  are always allowed. ``round_price`` returns the nearest valid price (a tie goes to the lower one).
- size: rounded toward zero to ``sz_decimals`` decimals (never increases exposure).
"""

from __future__ import annotations

import re
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    Context,
    Decimal,
    InvalidOperation,
)
from typing import Self

MAX_SZ_DECIMALS = 6
_MAX_SIGNIFICANT_FIGURES = 5
_MAX_PRICE_DECIMALS = 6
_MAX_ADJUSTED = 40  # values at or above 1e41 are certainly bad input and would overflow rounding
_CONTEXT = Context(prec=120, Emax=999, Emin=-999)
_DECIMAL_STR = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def _to_finite_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise TypeError(f"{name} must be built from a Decimal, int or str, not {type(value).__name__}")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        if not _DECIMAL_STR.fullmatch(value):
            raise ValueError(f"{name}: not a decimal number")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{name}: not a decimal number") from exc
    else:
        raise TypeError(f"{name} must be built from a Decimal, int or str, not {type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


class _Money(Decimal):
    """A ``Decimal`` that refuses floats, bools, NaN and infinities at construction."""

    __slots__ = ()

    def __new__(cls, value: Decimal | int | str) -> Self:
        return super().__new__(cls, _to_finite_decimal(value, cls.__name__))


class Price(_Money):
    """A price in USD per unit of the coin (never negative)."""

    __slots__ = ()

    def __new__(cls, value: Decimal | int | str) -> Self:
        price = super().__new__(cls, value)
        if price < 0:
            raise ValueError("Price must not be negative")
        return price


class Qty(_Money):
    """A quantity in coin units (not notional). Signed: the sign is the direction."""

    __slots__ = ()


class Notional(_Money):
    """A notional value in USD (qty x price)."""

    __slots__ = ()


class Fee(_Money):
    """A fee in USD."""

    __slots__ = ()


class Funding(_Money):
    """A funding payment in USD (signed)."""

    __slots__ = ()


class Pnl(_Money):
    """A profit or loss in USD (signed)."""

    __slots__ = ()


def _check_sz_decimals(sz_decimals: int) -> None:
    if isinstance(sz_decimals, bool) or not isinstance(sz_decimals, int):
        raise TypeError("sz_decimals must be an int")
    if not 0 <= sz_decimals <= MAX_SZ_DECIMALS:
        raise ValueError(f"sz_decimals must be between 0 and {MAX_SZ_DECIMALS}")


def _check_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, not {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value.adjusted() > _MAX_ADJUSTED:
        raise ValueError(f"{name} is out of range")
    return value


def _plain(value: Decimal) -> Decimal:
    """Rewrite ``1E+2`` as ``100`` so a rounded value never carries a positive exponent."""
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent > 0:
        return value.quantize(Decimal(1), context=_CONTEXT)
    return value


def round_price(px: Decimal, sz_decimals: int) -> Price:
    """Round a price to the nearest valid exchange price.

    Valid means an integer, or at most 5 significant figures with at most ``6 - sz_decimals``
    decimals. A tie between two valid prices goes to the lower one.

    Raises:
        TypeError: ``px`` is not a ``Decimal`` (floats included).
        ValueError: ``px`` <= 0, NaN, infinite or below the smallest tick (``10 ** -(6 - sz_decimals)``);
            ``sz_decimals`` outside 0..6.
    """
    _check_sz_decimals(sz_decimals)
    price = _check_decimal(px, "price")
    max_decimals = _MAX_PRICE_DECIMALS - sz_decimals
    tick = Decimal(1).scaleb(-max_decimals)
    if price <= 0:
        raise ValueError("price must be positive")
    if price < tick:
        raise ValueError("price is below the smallest tick")

    grid = Decimal(1).scaleb(max(price.adjusted() - (_MAX_SIGNIFICANT_FIGURES - 1), -max_decimals))
    candidates = {
        _plain(price.to_integral_value(rounding=ROUND_FLOOR, context=_CONTEXT)),
        _plain(price.to_integral_value(rounding=ROUND_CEILING, context=_CONTEXT)),
        _plain(price.quantize(grid, rounding=ROUND_FLOOR, context=_CONTEXT)),
        _plain(price.quantize(grid, rounding=ROUND_CEILING, context=_CONTEXT)),
    }
    best = min((c for c in candidates if c > 0), key=lambda c: (abs(c - price), c))
    return Price(best)


def round_size(qty: Decimal, sz_decimals: int) -> Qty:
    """Round a size toward zero to ``sz_decimals`` decimals.

    Raises:
        TypeError: ``qty`` is not a ``Decimal`` (floats included).
        ValueError: NaN or infinite ``qty``; ``sz_decimals`` outside 0..6.
    """
    _check_sz_decimals(sz_decimals)
    size = _check_decimal(qty, "quantity")
    rounded = size.quantize(Decimal(1).scaleb(-sz_decimals), rounding=ROUND_DOWN, context=_CONTEXT)
    return Qty(rounded.copy_abs() if rounded.is_zero() else rounded)
