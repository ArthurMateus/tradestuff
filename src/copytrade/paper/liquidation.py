"""The liquidation model (F11.AC5). F10 reuses this one function (F10.AC4, F10.AC10 property 7)."""

from __future__ import annotations

from decimal import Context, Decimal

from copytrade.core.money import Price, round_price

_PRECISE = Context(prec=60)
_SIDES = ("long", "short")


def liquidation_price(*, side: str, avg_entry_px: Price, leverage: int, max_leverage: int, sz_decimals: int) -> Price:
    """Liquidation price of an isolated position, rounded with ``round_price``.

    Maintenance margin is ``1 / (2 * max_leverage)`` of notional, so the distance from entry, as a fraction of
    entry, is ``1/leverage - 1/(2*max_leverage)``: below entry for ``side == "long"``, above for ``"short"``.

    Raises:
        ValueError: ``side`` is not ``"long"`` or ``"short"``, ``leverage`` or ``max_leverage`` is not an integer
            with ``1 <= leverage <= max_leverage``, or the price is not representable (``round_price``).
    """
    if side not in _SIDES:
        raise ValueError("side must be 'long' or 'short'")
    for name, value in (("leverage", leverage), ("max_leverage", max_leverage)):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if leverage > max_leverage:
        raise ValueError("leverage must not exceed max_leverage")
    one = Decimal(1)
    distance = _PRECISE.subtract(_PRECISE.divide(one, leverage), _PRECISE.divide(one, 2 * max_leverage))
    factor = _PRECISE.subtract(one, distance) if side == "long" else _PRECISE.add(one, distance)
    return round_price(_PRECISE.multiply(avg_entry_px, factor), sz_decimals)
