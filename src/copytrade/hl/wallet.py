"""Wallet address validation shared by the REST client and the WebSocket feed (F3)."""

from __future__ import annotations

import re

from copytrade.hl.errors import HlRequestError

_WALLET = re.compile(r"0x[0-9a-fA-F]{40}")


def normalize_wallet(value: str) -> str:
    """Return ``value`` lower-cased if it is a 0x-prefixed 20-byte hex address.

    Raises:
        HlRequestError: anything else (the request is refused before it is built or sent).
    """
    if type(value) is not str or _WALLET.fullmatch(value) is None:
        raise HlRequestError("a wallet address must be 0x followed by 40 hex digits")
    return value.lower()
