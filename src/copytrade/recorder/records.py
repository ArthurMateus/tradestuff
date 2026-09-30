"""One recorded observation and its canonical serialisation (F4.AC3, F4.AC7).

Contract:
- ``serialize_record`` is deterministic, independent of ``data`` key order, exact for ``Decimal`` (scale kept),
  ASCII-only single-line bytes without a trailing newline (hostile text cannot break the line structure), and
  refuses floats and non-finite numbers (money is Decimal, A6). ``deserialize_record`` is its exact inverse.
- The **stream sha256** of a sequence of records is ``sha256(b"".join(serialize_record(r) + b"\\n" for r in records))``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from copytrade.ledger.codec import decode_value, dumps, encode_value

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

_ENVELOPE_KEYS = frozenset({"coin", "data", "exchange_ts_ms", "receive_ts_ms", "source", "stream"})


def _is_int(value: object) -> bool:
    return type(value) is int


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

    def __post_init__(self) -> None:
        if self.stream not in STREAMS:
            raise ValueError("unknown recording stream")
        if self.coin is not None and (type(self.coin) is not str or not self.coin):
            raise TypeError("coin must be a non-empty str or None")
        if self.exchange_ts_ms is not None and not _is_int(self.exchange_ts_ms):
            raise TypeError("exchange_ts_ms must be an int of epoch milliseconds or None")
        if not _is_int(self.receive_ts_ms):
            raise TypeError("receive_ts_ms must be an int of epoch milliseconds")
        if type(self.source) is not str or not self.source:
            raise TypeError("source must be a non-empty str")
        if not isinstance(self.data, Mapping):
            raise TypeError("data must be a mapping")
        encode_value(self.data)  # the ledger codec refuses floats, non-finite numbers and foreign types


def serialize_record(record: Record) -> bytes:
    """The canonical bytes of ``record`` (see the module docstring)."""
    return dumps(
        {
            "stream": record.stream,
            "coin": record.coin,
            "exchange_ts_ms": record.exchange_ts_ms,
            "receive_ts_ms": record.receive_ts_ms,
            "source": record.source,
            "data": encode_value(record.data),
        }
    )


def deserialize_record(raw: bytes) -> Record:
    """Inverse of ``serialize_record``.

    Raises:
        ValueError: ``raw`` is not a well-formed serialised record.
    """
    try:
        envelope = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError("a serialised record is not JSON") from exc
    if not isinstance(envelope, dict) or envelope.keys() != _ENVELOPE_KEYS:
        raise ValueError("a serialised record does not have the record fields")
    try:
        return Record(
            stream=envelope["stream"],
            coin=envelope["coin"],
            exchange_ts_ms=envelope["exchange_ts_ms"],
            receive_ts_ms=envelope["receive_ts_ms"],
            source=envelope["source"],
            data=decode_value(envelope["data"]),
        )
    except TypeError as exc:
        raise ValueError("a serialised record has a field of the wrong type") from exc


def stream_sha256(records: Iterable[Record]) -> str:
    """Lower-case hex sha256 over the canonical bytes of ``records``, each followed by ``b"\\n"``."""
    digest = hashlib.sha256()
    for record in records:
        digest.update(serialize_record(record))
        digest.update(b"\n")
    return digest.hexdigest()
