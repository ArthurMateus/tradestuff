"""Gap statistics from recorded data (F4.AC4)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Context, Decimal
from itertools import pairwise

from copytrade.recorder.records import STREAM_ASSET_CTX, STREAM_L2, STREAM_MIDS
from copytrade.recorder.store import RecordingReader

L2_GAP_MS = 5_000
MID_GAP_MS = 60_000
_SHARE_CONTEXT = Context(prec=28)  # the division does not depend on the calling thread's decimal context


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
    if to_ms <= from_ms:
        raise ValueError("the window must end after it starts")
    view = reader.pinned()  # one reading of the ledger for every coin
    end = to_ms + 1  # the window is closed: a record stamped ``to_ms`` is inside it
    chosen = view.coins(STREAM_L2, from_ms, end) if coins is None else coins
    mids_times: dict[str, list[int]] = {coin: [] for coin in chosen}
    for record in view.scan(STREAM_MIDS, None, from_ms, end):
        mids = record.data.get("mids")
        if isinstance(mids, Mapping):
            for coin in mids_times.keys() & mids.keys():
                mids_times[coin].append(record.receive_ts_ms)
    stats: dict[str, GapStats] = {}
    for coin in chosen:
        l2_times = (record.receive_ts_ms for record in view.scan(STREAM_L2, coin, from_ms, end))
        mark_times = (record.receive_ts_ms for record in view.scan(STREAM_ASSET_CTX, coin, from_ms, end))
        stats[coin] = GapStats(
            l2_gap_share=_gap_share(l2_times, L2_GAP_MS, from_ms, to_ms),
            mid_gap_share=_gap_share([*mids_times[coin], *mark_times], MID_GAP_MS, from_ms, to_ms),
        )
    return stats


def _gap_share(times: Iterable[int], threshold_ms: int, from_ms: int, to_ms: int) -> Decimal:
    """The share of ``[from_ms, to_ms]`` lying in intervals longer than ``threshold_ms`` between consecutive points
    (the window's edges count as points, so a missing head or tail is a gap)."""
    points = [from_ms, *sorted(times), to_ms]
    gap_ms = sum(later - earlier for earlier, later in pairwise(points) if later - earlier > threshold_ms)
    return _SHARE_CONTEXT.divide(Decimal(gap_ms), Decimal(to_ms - from_ms))
