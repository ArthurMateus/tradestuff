"""R2.AC7 (selection pacing): when the HL budget refuses with ``would wait X s`` (``HlBudgetError``), the backfill honours
that wait. The shared cooldown equals the STATED wait, not the doubling ``hl.backoff_base_s``, so no request is attempted
before the budget has room (RISK-67 family: the PO's run showed the scoring slice hammering a full budget every 10 s).

Real ``PacedInputs`` + ``Backfiller`` + ``HlRestClient`` + ``RateBudget`` with the runner's REAL fail-fast sleeper
(``wiring._FailFastSleeper``, wrapped only to record each refusal); faked: HTTP (the R1 fake Hyperliquid), the candle
source and the clock. One scoring slice every 10 simulated seconds, as the runner does (``SELECTION_WORK_INTERVAL_S``)."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from copytrade.hl.access import AccessMonitor
from copytrade.hl.budget import RateBudget, request_weight
from copytrade.hl.rest import HlRestClient
from copytrade.hl.schema import SchemaFailureMonitor
from copytrade.runner.sources import PacedInputs
from copytrade.runner.wiring import _FailFastSleeper
from copytrade.selection.backfill import Backfiller
from tests.hl.support import FakeClock, FakeHttp, RecordingAlerts, RecordingLedger, make_config
from tests.selection.helpers import w
from tests.selection.r1_world import FakeCandles, FakeHl, synth_fills

STEP_MS = 10_000
CANDIDATES = 50


class RecordingFailFast(_FailFastSleeper):
    """The runner's real scoring sleeper; records ``(time_ms, stated_wait_s)`` of every refusal, then refuses as before."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.refusals: list[tuple[int, float]] = []

    def sleep(self, seconds: float) -> None:
        self.refusals.append((self.clock.now_ms(), seconds))
        super().sleep(seconds)


@dataclass
class Rig:
    cfg: Any
    clock: FakeClock
    http: FakeHttp
    sleeper: RecordingFailFast
    inputs: PacedInputs
    attempts: list[int] = field(default_factory=list)  # local time of every request that reached the transport


def build(n: int = CANDIDATES) -> Rig:
    cfg = make_config()
    clock = FakeClock()
    hl = FakeHl()
    http = FakeHttp(clock, hl.handle)
    sleeper = RecordingFailFast(clock)
    alerts, ledger = RecordingAlerts(), RecordingLedger()
    budget = RateBudget(
        budget_per_min=cfg["hl.rest_weight_budget_per_min"], scoring_share=cfg["hl.scoring_weight_share"], clock=clock
    )
    client = HlRestClient(
        config=cfg, clock=clock, transport=http, sleeper=sleeper, rng=random.Random(7), budget=budget,
        access=AccessMonitor(config=cfg, clock=clock, alerts=alerts, ledger=ledger),
        schema_monitor=SchemaFailureMonitor(clock=clock, alerts=alerts),
    )
    wallets = [w(i) for i in range(1, n + 1)]
    for i, wallet in enumerate(wallets):
        hl.set_fills(wallet, synth_fills(5, tid0=1 + i * 100))
    paced = PacedInputs(Backfiller(config=cfg, clock=clock, rest=client, candles=FakeCandles()))
    paced.set_candidates(wallets)
    return Rig(cfg=cfg, clock=clock, http=http, sleeper=sleeper, inputs=paced)


def run_slices(rig: Rig, *, steps: int | None = None, until_complete: bool = False, cap_steps: int = 400) -> int:
    """One ``work()`` per 10 s of local time. Returns the number of slices run."""
    done = 0
    for _ in range(cap_steps if until_complete else steps or 0):
        rig.inputs.work()
        done += 1
        if until_complete and rig.inputs.complete:
            break
        rig.clock.advance(STEP_MS)
    return done


def test_R2_AC7_the_cooldown_after_a_budget_refusal_is_the_stated_wait_so_no_request_precedes_it() -> None:
    rig = build()
    run_slices(rig, steps=60)  # 10 simulated minutes
    assert rig.sleeper.refusals, "the scenario must exhaust the scoring share (50 wallets x 102 weight against 450/min)"
    attempts = [c.t_ms for c in rig.http.calls]
    for t_ms, wait_s in rig.sleeper.refusals:
        ready_ms = t_ms + int(wait_s * 1000) - 1  # the wait is stated in seconds; allow a millisecond of rounding
        early = [t for t in attempts if t_ms < t < ready_ms]
        assert not early, f"a request was sent at {early[0] - t_ms} ms after a refusal that said 'would wait {wait_s:.1f} s'"
        later = [r for r in rig.sleeper.refusals if t_ms < r[0] < ready_ms]
        assert not later, "a second request was attempted (and refused again) before the stated wait had passed"


def test_R2_AC7_refused_attempts_over_ten_minutes_are_far_below_one_per_slice() -> None:
    rig = build()
    run_slices(rig, steps=60)
    refused = len(rig.sleeper.refusals)
    # one refusal per 10 s slice would be 60; honouring the stated wait gives about 10
    assert 0 < refused <= 12, f"{refused} refused attempts in 60 slices: the backfill keeps knocking on a full budget"


def test_R2_AC7_a_pass_over_50_candidates_completes_in_about_the_minimum_time_the_budget_allows() -> None:
    rig = build()
    cap = int(rig.cfg["hl.rest_weight_budget_per_min"] * rig.cfg["hl.scoring_weight_share"])
    per_wallet = (
        request_weight("userFillsByTime", 5, rig.cfg)
        + request_weight("portfolio", 0, rig.cfg)
        + request_weight("clearinghouseState", 0, rig.cfg)
        + request_weight("userRole", 0, rig.cfg)
    )
    minimum_s = max(0.0, (CANDIDATES * per_wallet - cap) / cap * 60)  # the first window's share is free
    start = rig.clock.now_ms()
    slices = run_slices(rig, until_complete=True)
    assert rig.inputs.complete, f"the pass did not finish within {slices} slices"
    took_s = (rig.clock.now_ms() - start) / 1000
    assert took_s <= minimum_s * 1.5 + 60, f"took {took_s:.0f} s; the budget allows about {minimum_s:.0f} s"
    assert took_s >= minimum_s - 60, "sanity: the oracle (weights, cap) matches what the run did"

