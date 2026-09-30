"""Pure fill classification (F7.AC1)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from copytrade.core.domain import ActionKind
from copytrade.core.errors import CopytradeError
from copytrade.core.money import Qty
from copytrade.hl.models import Fill


class UnparseableFillError(CopytradeError):
    """The fill cannot be classified (a size that is not positive)."""


@dataclass(frozen=True)
class Leg:
    """One typed piece of a fill. ``pre`` and ``post`` are signed positions (long > 0) before and after this leg."""

    action: ActionKind
    is_long: bool
    size: Qty
    pre: Qty
    post: Qty
    reduce_fraction: Decimal | None
    from_flip: bool


def classify_fill(fill: Fill) -> tuple[Leg, ...]:
    """Classify from ``fill.start_position``, ``fill.sz`` and ``fill.side`` (``"B"`` adds ``sz``, ``"A"`` subtracts it).

    - open: 0 to non-zero. add: same sign and ``|post| > |pre|``. reduce: same sign and ``0 < |post| < |pre|``, with
      ``reduce_fraction = (|pre| - |post|) / |pre|``. close: ``post = 0``.
    - flip (sign change): two legs, the close of the old position (size ``|pre|``, ``pre -> 0``) then the open of
      the new one (size ``|post|``, ``0 -> post``), both with ``from_flip`` True.
    - Only a reduce has a ``reduce_fraction``. ``dir`` is not used.

    Raises:
        UnparseableFillError: ``fill.sz`` is not positive.
    """
    raise NotImplementedError
