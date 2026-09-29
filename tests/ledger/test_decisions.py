"""F2.AC2: one decision record per signal (B5): signal id, leader, coin, event type; exchange timestamp, local
receive timestamp and clock offset; each filter rule's input, threshold and result; each risk check; the
mirror, risk-cap and final sizes; the price used; latency per stage; and the outcome. 50 signals give exactly
50 decision records with no required field null.

Spec: 04-spec.md F2.AC2, invariants B5, B2, A9.
"""

from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal
from pathlib import Path

import pytest

from copytrade.core.clock import TimeSource, Timestamp
from copytrade.core.money import Price, Qty
from copytrade.ledger.records import (
    KIND_DECISION,
    OUTCOMES,
    DecisionRecord,
    RiskCheckResult,
    RuleResult,
    decode_decision,
)
from copytrade.ledger.store import Ledger, verify_ledger
from tests.ledger.helpers import OUTCOME_CYCLE, T0, make_decision

pytestmark = pytest.mark.unit

REQUIRED = [f.name for f in fields(DecisionRecord)]


def test_F2_AC2_fifty_signals_yield_exactly_fifty_decision_records_with_no_null_field(ledger: Ledger) -> None:
    decisions = [make_decision(i) for i in range(50)]
    for d in decisions:
        ledger.append_decision(d)
    stored = [r for r in ledger.records() if r.kind == KIND_DECISION]
    assert len(stored) == 50
    assert len(list(ledger.records())) == 50  # and nothing else was written
    decoded = [decode_decision(r) for r in stored]
    assert decoded == decisions  # every field, in order, exact (Decimals included)
    for d in decoded:
        assert all(getattr(d, name) is not None for name in REQUIRED)


def test_F2_AC2_all_eight_outcomes_are_accepted_and_round_trip(ledger: Ledger) -> None:
    seen = set()
    for i, outcome in enumerate(OUTCOME_CYCLE):
        record = ledger.append_decision(make_decision(i, outcome))
        seen.add(decode_decision(record).outcome)
    assert seen == set(OUTCOME_CYCLE)
    assert {o for o in OUTCOME_CYCLE if not o.startswith("rejected:")} == set(OUTCOMES)


@pytest.mark.parametrize("name", REQUIRED)
def test_F2_AC2_a_missing_required_field_is_refused(name: str) -> None:
    good = make_decision(1)
    with pytest.raises((TypeError, ValueError)):
        replace(good, **{name: None})


@pytest.mark.parametrize("name", ["signal_id", "leader", "coin", "event_type"])
def test_F2_AC2_empty_identity_text_is_refused(name: str) -> None:
    with pytest.raises(ValueError):
        replace(make_decision(1), **{name: ""})


@pytest.mark.parametrize(
    "outcome", ["", "rejected", "rejected:", "Taken", "taken ", "error", "rejected: ", "skipped:slippage"], ids=repr
)
def test_F2_AC2_unknown_outcomes_are_refused(outcome: str) -> None:
    with pytest.raises(ValueError):
        replace(make_decision(1), outcome=outcome)


def test_F2_AC2_rejected_outcome_keeps_its_reason(ledger: Ledger) -> None:
    decision = make_decision(1, "rejected:max_open_positions")
    assert decode_decision(ledger.append_decision(decision)).outcome == "rejected:max_open_positions"


def test_F2_AC2_timestamps_carry_the_right_source() -> None:
    with pytest.raises(ValueError):
        replace(make_decision(1), exchange_ts=Timestamp(T0, TimeSource.LOCAL))
    with pytest.raises(ValueError):
        replace(make_decision(1), local_receive_ts=Timestamp(T0, TimeSource.EXCHANGE))


@pytest.mark.parametrize("offset", [1.5, "12", True], ids=repr)
def test_F2_AC2_clock_offset_must_be_an_int_of_milliseconds(offset: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(make_decision(1), clock_offset_ms=offset)


def test_F2_AC2_negative_and_zero_clock_offsets_are_recorded_faithfully(ledger: Ledger) -> None:
    for offset in (-2_500, 0, 40):
        decision = replace(make_decision(1), clock_offset_ms=offset)
        assert decode_decision(ledger.append_decision(decision)).clock_offset_ms == offset


@pytest.mark.parametrize("latency", [{}, {"S1": -1}, {"S1": 1.5}, {"S1": "3"}, {"S1": True}], ids=repr)
def test_F2_AC2_latency_per_stage_must_be_non_empty_non_negative_ints(latency: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(make_decision(1), latency_ms=latency)


def test_F2_AC2_filter_and_risk_results_keep_input_threshold_and_result_exactly(ledger: Ledger) -> None:
    decision = replace(
        make_decision(1),
        filter_results=(
            RuleResult("slippage_pct", Decimal("0.3000"), Decimal("0.30"), True),  # exactly at the threshold
            RuleResult("spread_pct", Decimal("0.0000001"), Decimal("0.05"), True),
            RuleResult("funding", Decimal("-0.01"), Decimal("0.02"), False),
        ),
        risk_checks=(RiskCheckResult("max_leverage", False, "12x > 10x"), RiskCheckResult("kill_switch", True, "")),
    )
    back = decode_decision(ledger.append_decision(decision))
    assert back.filter_results == decision.filter_results
    assert [str(r.input_value) for r in back.filter_results] == [str(r.input_value) for r in decision.filter_results]
    assert str(back.filter_results[0].input_value) == "0.3000"  # scale kept
    assert back.risk_checks == decision.risk_checks


def test_F2_AC2_a_signal_with_no_rules_evaluated_still_records_with_empty_lists(ledger: Ledger) -> None:
    decision = replace(make_decision(1, "out_of_scope"), filter_results=(), risk_checks=())
    back = decode_decision(ledger.append_decision(decision))
    assert back.filter_results == () and back.risk_checks == ()


def test_F2_AC2_sizes_and_price_are_exact_decimals_not_floats(ledger: Ledger) -> None:
    decision = replace(
        make_decision(1), mirror_size=Qty("0.1"), risk_cap_size=Qty("0.07"), final_size=Qty("0.07"), price_used=Price("0.1")
    )
    back = decode_decision(ledger.append_decision(decision))
    for name in ("mirror_size", "risk_cap_size", "final_size", "price_used"):
        assert isinstance(getattr(back, name), Decimal)
    assert (back.mirror_size, back.risk_cap_size, back.price_used) == (Decimal("0.1"), Decimal("0.07"), Decimal("0.1"))


def test_F2_AC2_unicode_ids_and_reasons_round_trip(ledger: Ledger) -> None:
    decision = replace(make_decision(1, "rejected:sinal_antigo_ção"), coin="k×PEPE", leader="متداول")
    assert decode_decision(ledger.append_decision(decision)) == decision


def test_F2_AC2_decode_refuses_records_of_another_kind(ledger: Ledger) -> None:
    record = ledger.append("note", {"a": 1})
    with pytest.raises(ValueError):
        decode_decision(record)


def test_F2_AC2_decisions_verify_and_are_kept_in_arrival_order_even_when_signal_times_go_backwards(
    ledger: Ledger, ledger_dir: Path
) -> None:
    order = [5, 1, 9, 2]
    for i in order:
        ledger.append_decision(make_decision(i))
    assert [decode_decision(r).signal_id for r in ledger.records()] == [f"sig-{i}" for i in order]
    assert verify_ledger(ledger_dir).ok


def test_F2_AC2_the_same_signal_seen_twice_is_two_records_the_ledger_never_drops_or_merges(ledger: Ledger) -> None:
    ledger.append_decision(make_decision(1, "taken"))
    ledger.append_decision(make_decision(1, "duplicate"))
    assert [decode_decision(r).outcome for r in ledger.records()] == ["taken", "duplicate"]
