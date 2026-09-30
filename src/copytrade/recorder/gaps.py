"""Gap statistics from recorded data (F4.AC4)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from copytrade.recorder.store import RecordingReader

L2_GAP_MS = 5_000
MID_GAP_MS = 60_000


@dataclass(frozen=True)
class GapStats:
    """Shares of the window as Decimal fractions in [0, 1]."""

    l2_gap_share: Decimal
    mid_gap_share: Decimal


def gap_stats(
    reader: RecordingReader, from_ms: int, to_ms: int, coins: tuple[str, ...] | None = None
) -> dict[str, GapStats]:
    """Per coin, over ``[from_ms, to_ms]`` (hashed data only):

    - ``l2_gap_share``: total length of the intervals between consecutive L2 snapshots (window edges count as
      snapshots) that are longer than ``L2_GAP_MS``, divided by the window length. An interval of exactly 5 s is
      not a gap.
    - ``mid_gap_share``: the same over the union of ``mids`` records that contain the coin and its ``asset_ctx``
      records, with ``MID_GAP_MS``.

    ``coins`` defaults to every coin with any L2 record in the window.

    Raises:
        ValueError: ``to_ms <= from_ms``.
    """
    raise NotImplementedError
