"""One recorded observation and its canonical serialisation (F4.AC3, F4.AC7).

Interface stub written by the test designer. The developer owns the implementation.

Contract:
- ``serialize_record`` is deterministic, independent of ``data`` key order, exact for ``Decimal`` (scale kept),
  ASCII-only single-line bytes without a trailing newline (hostile text cannot break the line structure), and
  refuses floats and non-finite numbers (money is Decimal, A6). ``deserialize_record`` is its exact inverse.
- The **stream sha256** of a sequence of records is ``sha256(b"".join(serialize_record(r) + b"\\n" for r in records))``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

STREAM_L2 = "l2"
STREAM_MIDS = "mids"
STREAM_ASSET_CTX = "asset_ctx"
STREAM_FUNDING = "funding"
STREAM_LEADERBOARD = "leaderboard"
STREAM_CANDLE_1M = "candle_1m"
STREAM_CANDLE_1H = "candle_1h"
STREAMS = frozenset(
    {STREAM_L2, STREAM_MIDS, STREAM_ASSET_CTX, STREAM_FUNDING, STREAM_LEADERBOARD, STREAM_CANDLE_1M, STREAM_CANDLE_1H}
)


@dataclass(frozen=True)
class Record:
    """One recorded observation.

    ``receive_ts_ms`` is the local receive time (UTC epoch ms, always present). ``exchange_ts_ms`` is the exchange
    time where the source gives one, else ``None``. ``source`` tags where the record came from (``"ws"``, ``"rest"``).
    ``coin`` is ``None`` for streams that are not per coin (``mids``, ``leaderboard``). ``data`` holds only
    ledger-codec types (str, int, bool, None, finite Decimal, lists, dicts with str keys).

    Raises ``TypeError`` / ``ValueError`` at construction for an unknown ``stream``, a non-int timestamp or a
    ``data`` value the codec refuses (floats included).
    """

    stream: str
    coin: str | None
    exchange_ts_ms: int | None
    receive_ts_ms: int
    source: str
    data: Mapping[str, Any]


def serialize_record(record: Record) -> bytes:
    """The canonical bytes of ``record`` (see the module docstring)."""
    raise NotImplementedError


def deserialize_record(raw: bytes) -> Record:
    """Inverse of ``serialize_record``.

    Raises:
        ValueError: ``raw`` is not a well-formed serialised record.
    """
    raise NotImplementedError


def stream_sha256(records: Iterable[Record]) -> str:
    """Lower-case hex sha256 over the canonical bytes of ``records``, each followed by ``b"\\n"``."""
    raise NotImplementedError
