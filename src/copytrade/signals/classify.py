"""Pure fill classification (F7.AC1)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal

from copytrade.core.domain import ActionKind
from copytrade.core.errors import CopytradeError
from copytrade.core.money import Qty
from copytrade.hl.models import Fill

_BUY = "B"
_SELL = "A"
# Position arithmetic is exact for any size an exchange can send; the one division (the reduce fraction) rounds to 28
# significant digits, half-even, independent of whatever context the calling thread has set.
_EXACT = Context(prec=80)
_FRACTION = Context(prec=28)


class UnparseableFillError(CopytradeError):
    """The fill cannot be classified (a size that is not positive, or a side that is not ``"B"`` or ``"A"``)."""


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
        UnparseableFillError: ``fill.sz`` is not positive, or ``fill.side`` is neither ``"B"`` nor ``"A"``.
    """
    if fill.side not in (_BUY, _SELL):
        raise UnparseableFillError("fill side is neither B nor A")
    if not fill.sz > 0:
        raise UnparseableFillError("fill size is not positive")
    pre = Decimal(fill.start_position)
    delta = Decimal(fill.sz) if fill.side == _BUY else -Decimal(fill.sz)
    post = _EXACT.add(pre, delta)
    if pre == 0:
        return (_leg(ActionKind.OPEN, fill.sz, pre, post),)
    if post == 0:
        return (_leg(ActionKind.CLOSE, fill.sz, pre, post),)
    if (pre > 0) != (post > 0):
        zero = Decimal(0)
        return (
            _leg(ActionKind.CLOSE, abs(pre), pre, zero, from_flip=True),
            _leg(ActionKind.OPEN, abs(post), zero, post, from_flip=True),
        )
    if abs(post) > abs(pre):
        return (_leg(ActionKind.ADD, fill.sz, pre, post),)
    return (_leg(ActionKind.REDUCE, fill.sz, pre, post),)


def _leg(action: ActionKind, size: Decimal, pre: Decimal, post: Decimal, *, from_flip: bool = False) -> Leg:
    """Build one leg. ``is_long`` is the direction of the position the leg opens or adds to, or reduces or closes."""
    entry = action in (ActionKind.OPEN, ActionKind.ADD)
    fraction = None
    if action is ActionKind.REDUCE:
        fraction = _FRACTION.divide(_EXACT.subtract(abs(pre), abs(post)), abs(pre))
    return Leg(
        action=action,
        is_long=(post if entry else pre) > 0,
        size=Qty(size),
        pre=Qty(pre),
        post=Qty(post),
        reduce_fraction=fraction,
        from_flip=from_flip,
    )
