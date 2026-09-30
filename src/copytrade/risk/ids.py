"""Deterministic client order IDs (F10.AC8, A5)."""

from __future__ import annotations

from collections.abc import Sequence


def client_order_id(  # noqa: PLR0913 - the six fields of the ID are the spec
    *, run_id: str, leader: str, coin: str, tids: Sequence[int], action: str, share_id: str
) -> str:
    """``sha256(run_id || leader || coin || sorted signal tids || action || share_id)`` as lowercase hex, with an
    unambiguous encoding (no two different argument sets share an encoding). The same arguments always give the same
    ID, in any order of ``tids``."""
    raise NotImplementedError
