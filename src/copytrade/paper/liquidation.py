"""The liquidation model (F11.AC5). F10 reuses this one function (F10.AC4, F10.AC10 property 7)."""

from __future__ import annotations

from copytrade.core.money import Price


def liquidation_price(*, side: str, avg_entry_px: Price, leverage: int, max_leverage: int, sz_decimals: int) -> Price:
    """Liquidation price of an isolated position, rounded with ``round_price``.

    Maintenance margin is ``1 / (2 * max_leverage)`` of notional, so the distance from entry, as a fraction of
    entry, is ``1/leverage - 1/(2*max_leverage)``: below entry for ``side == "long"``, above for ``"short"``.
    """
    raise NotImplementedError
