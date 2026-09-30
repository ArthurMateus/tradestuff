"""Deterministic client order IDs (F10.AC8, A5)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

_DOMAIN = "copytrade.client_order_id.v1"


def client_order_id(  # noqa: PLR0913 - the six fields of the ID are the spec
    *, run_id: str, leader: str, coin: str, tids: Sequence[int], action: str, share_id: str
) -> str:
    """``sha256(run_id || leader || coin || sorted signal tids || action || share_id)`` as lowercase hex, with an
    unambiguous encoding (no two different argument sets share an encoding). The same arguments always give the same
    ID, in any order of ``tids``.

    The fields are encoded as one JSON array (strings and integers only), so a boundary between two fields can never
    be mistaken for a character inside one, and the ID is the full 64-character digest: the paper broker has no
    length rule, so nothing is truncated.

    Raises:
        TypeError: a text field is not a ``str`` or a signal tid is not an ``int`` (a ``bool`` included).
    """
    for name, value in (
        ("run_id", run_id),
        ("leader", leader),
        ("coin", coin),
        ("action", action),
        ("share_id", share_id),
    ):
        if type(value) is not str:
            raise TypeError(f"{name} must be a str")
    if any(type(tid) is not int for tid in tids):
        raise TypeError("signal tids must be ints")
    encoded = json.dumps(
        [_DOMAIN, run_id, leader, coin, sorted(tids), action, share_id],
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()
