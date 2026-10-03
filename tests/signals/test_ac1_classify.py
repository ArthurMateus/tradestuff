"""F7.AC1: classification from ``startPosition``, ``sz`` and ``side``: open, add, reduce (with its fraction), close, flip.

Spec: 04-spec.md F7.AC1 (a 30-case fixture covering each type, including aggregated fills), §5 "Unknown fill format".
The pure classifier is tested directly; the detector tests re-check the same cases through the real ledger and sink.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from copytrade.core.domain import ActionKind
from copytrade.signals.classify import Leg, UnparseableFillError, classify_fill
from tests.signals.helpers import mkfill

pytestmark = pytest.mark.unit

OP, AD, R, C = ActionKind.OPEN, ActionKind.ADD, ActionKind.REDUCE, ActionKind.CLOSE
D = Decimal


def leg(action: ActionKind, long: bool, size: str, pre: str, post: str, frac: Decimal | None = None, flip: bool = False) -> Leg:
    from copytrade.core.money import Qty

    return Leg(action, long, Qty(size), Qty(pre), Qty(post), frac, flip)


# (case id, startPosition, side, sz, expected legs). 30 cases; "agg" cases are fills Hyperliquid aggregated by time.
CASES = [
    ("open long", "0", "B", "1", [leg(OP, True, "1", "0", "1")]),
    ("open short", "0", "A", "2.5", [leg(OP, False, "2.5", "0", "-2.5")]),
    ("open tiny", "0", "B", "0.00001", [leg(OP, True, "0.00001", "0", "0.00001")]),
    ("open huge", "0", "A", "1000000", [leg(OP, False, "1000000", "0", "-1000000")]),
    ("add long", "1", "B", "1", [leg(AD, True, "1", "1", "2")]),
    ("add short", "-2", "A", "3", [leg(AD, False, "3", "-2", "-5")]),
    ("add small long", "0.5", "B", "0.25", [leg(AD, True, "0.25", "0.5", "0.75")]),
    ("add tiny short", "-0.001", "A", "0.002", [leg(AD, False, "0.002", "-0.001", "-0.003")]),
    ("reduce long quarter", "4", "A", "1", [leg(R, True, "1", "4", "3", D("0.25"))]),
    ("reduce short quarter", "-4", "B", "1", [leg(R, False, "1", "-4", "-3", D("0.25"))]),
    ("reduce two thirds", "3", "A", "2", [leg(R, True, "2", "3", "1", D(2) / D(3))]),
    ("reduce almost all", "10", "A", "9.9999", [leg(R, True, "9.9999", "10", "0.0001", D("0.99999"))]),
    ("reduce a sliver", "1", "A", "0.0001", [leg(R, True, "0.0001", "1", "0.9999", D("0.0001"))]),
    ("reduce short eighth", "-0.5", "B", "0.125", [leg(R, False, "0.125", "-0.5", "-0.375", D("0.25"))]),
    ("reduce half", "2", "A", "1", [leg(R, True, "1", "2", "1", D("0.5"))]),
    ("close long", "1", "A", "1", [leg(C, True, "1", "1", "0")]),
    ("close short", "-1", "B", "1", [leg(C, False, "1", "-1", "0")]),
    ("close odd size", "0.123456", "A", "0.123456", [leg(C, True, "0.123456", "0.123456", "0")]),
    ("close big short", "-1000", "B", "1000", [leg(C, False, "1000", "-1000", "0")]),
    ("close trailing zero", "7", "A", "7.0", [leg(C, True, "7", "7", "0")]),
    ("flip long to short", "1", "A", "3", [leg(C, True, "1", "1", "0", None, True), leg(OP, False, "2", "0", "-2", None, True)]),
    ("flip short to long", "-1", "B", "4", [leg(C, False, "1", "-1", "0", None, True), leg(OP, True, "3", "0", "3", None, True)]),
    ("flip fractional", "0.5", "A", "0.6", [leg(C, True, "0.5", "0.5", "0", None, True), leg(OP, False, "0.1", "0", "-0.1", None, True)]),
    ("flip big short", "-10", "B", "10.5", [leg(C, False, "10", "-10", "0", None, True), leg(OP, True, "0.5", "0", "0.5", None, True)]),
    ("agg open (3 fills)", "0", "B", "3.75", [leg(OP, True, "3.75", "0", "3.75")]),
    ("agg add (2 fills)", "2", "B", "1.5", [leg(AD, True, "1.5", "2", "3.5")]),
    ("agg reduce (4 fills)", "5", "A", "2.5", [leg(R, True, "2.5", "5", "2.5", D("0.5"))]),
    ("agg close (3 partials)", "3", "A", "3", [leg(C, True, "3", "3", "0")]),
    ("agg flip (5 fills)", "-2", "B", "5", [leg(C, False, "2", "-2", "0", None, True), leg(OP, True, "3", "0", "3", None, True)]),
    ("open precise", "0", "A", "12.34567", [leg(OP, False, "12.34567", "0", "-12.34567")]),
]


def test_F7_AC1_the_fixture_has_thirty_cases_and_the_classifier_yields_every_type_from_them() -> None:
    assert len(CASES) == 30
    got = [classify_fill(mkfill(i, side=side, sz=sz, start=start)) for i, (_, start, side, sz, _) in enumerate(CASES)]
    assert {leg_.action for legs in got for leg_ in legs} == {OP, AD, R, C}
    assert sum(1 for legs in got if len(legs) == 2) == 5 and any("agg" in name for name, *_ in CASES)


@pytest.mark.parametrize(("name", "start", "side", "sz", "expected"), CASES, ids=[c[0] for c in CASES])
def test_F7_AC1_classification_of_each_fixture_case(name: str, start: str, side: str, sz: str, expected: list[Leg]) -> None:
    got = classify_fill(mkfill(1, side=side, sz=sz, start=start))
    assert got == tuple(expected)
    assert all(str(g.size) == str(e.size) or g.size == e.size for g, e in zip(got, expected, strict=True))


def test_F7_AC1_a_reduce_fraction_is_pre_minus_post_over_pre_exactly() -> None:
    (only,) = classify_fill(mkfill(1, side="A", sz="2", start="3"))
    assert only.reduce_fraction == (D(3) - D(1)) / D(3)
    assert isinstance(only.reduce_fraction, Decimal)


@pytest.mark.parametrize("sz", ["0", "0.0", "-1"])
def test_F7_AC1_a_size_that_is_not_positive_is_unparseable(sz: str) -> None:
    with pytest.raises(UnparseableFillError):
        classify_fill(mkfill(1, side="B", sz=sz, start="1"))


def test_F7_AC1_dir_text_does_not_change_the_classification() -> None:
    a = classify_fill(mkfill(1, side="A", sz="1", start="2", dir="Close Long"))
    b = classify_fill(mkfill(1, side="A", sz="1", start="2", dir="Liquidated Cross Long"))
    assert a == b


signed = st.decimals(min_value=D("-1000"), max_value=D("1000"), places=6, allow_nan=False, allow_infinity=False)
positive = st.decimals(min_value=D("0.000001"), max_value=D("2000"), places=6, allow_nan=False, allow_infinity=False)


def oracle(pre: Decimal, side: str, sz: Decimal) -> list[ActionKind]:
    """The F7.AC1 table restated as an independent test oracle."""
    post = pre + (sz if side == "B" else -sz)
    if pre == 0:
        return [OP]
    if post == 0:
        return [C]
    if (pre > 0) != (post > 0):
        return [C, OP]
    return [AD] if abs(post) > abs(pre) else [R]


@given(pre=signed, side=st.sampled_from(["B", "A"]), sz=positive)
def test_F7_AC1_property_legs_reconstruct_the_position_change_and_match_the_type_table(
    pre: Decimal, side: str, sz: Decimal
) -> None:
    legs = classify_fill(mkfill(1, side=side, sz=str(sz), start=str(pre)))
    assert [leg_.action for leg_ in legs] == oracle(pre, side, sz)
    post = pre + (sz if side == "B" else -sz)
    assert legs[0].pre == pre and legs[-1].post == post
    assert sum(abs(leg_.post - leg_.pre) for leg_ in legs) == sz  # sizes are the whole fill, nothing lost
    assert all(leg_.size > 0 and leg_.size == abs(leg_.post - leg_.pre) for leg_ in legs)
    if len(legs) == 2:
        assert legs[0].post == 0 and legs[1].pre == 0 and all(leg_.from_flip for leg_ in legs)
        assert legs[0].is_long != legs[1].is_long
    else:
        assert legs[0].from_flip is False
    for leg_ in legs:
        if leg_.action is R:
            assert leg_.reduce_fraction is not None and 0 < leg_.reduce_fraction < 1
            assert leg_.reduce_fraction == (abs(leg_.pre) - abs(leg_.post)) / abs(leg_.pre)
        else:
            assert leg_.reduce_fraction is None
        if leg_.action in (OP, AD):
            assert leg_.is_long == (leg_.post > 0)
        else:
            assert leg_.is_long == (leg_.pre > 0)
