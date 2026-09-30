"""F7.AC6: throughput (a burst of 100 fills/s for 10 s across 9 wallets, p99 receive-to-signal <= 50 ms, 0 dropped) and
``latency measure``, which records stages S1 and S2 per signal without trading and can run before F9 to F12 exist.

Spec: 04-spec.md F7.AC6, §4 latency table (S1, S2), §3.8 ``latency.min_signals``, invariant C6.
The measurement runs the real F3 feed and REST client, the real detector and the real ledger over fake boundaries
(clock, sleeping, connector, HTTP transport, offset source).
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

import copytrade.cli.latency as latency_cli
import copytrade.signals as signals_pkg
from copytrade.core.clock import ClockSync, SystemClock
from copytrade.core.errors import CopytradeError
from copytrade.ledger.store import Ledger, verify_ledger
from copytrade.signals.detector import SignalDetector
from copytrade.signals.latency import LatencyBoundaries, LatencyReport, StageSummary, measure_latency, percentile
from tests.core.helpers import make_root, run_cli
from tests.hl.support import (
    SECOND,
    FakeClock,
    FakeConnector,
    FakeHttp,
    FakeSleeper,
    RecordingAlerts,
    fill_json,
    make_config,
)
from tests.signals.helpers import T0, WALLET_A, WALLET_B, FakeOffsetSource, RecordingSignals, mkfill, state

pytestmark = pytest.mark.integration

FORBIDDEN_IMPORTS = ("risk", "paper", "positions", "filters", "selection", "telegram", "reports", "evaluation", "baselines", "replay", "recovery", "calendar")


# --- throughput -------------------------------------------------------------------------------------------------------------


def wired_real_clock(base: Path) -> tuple[SignalDetector, RecordingSignals, Ledger]:
    clock = SystemClock()
    config = make_config()
    alerts = RecordingAlerts()
    sync = ClockSync.from_config(config, clock=clock, source=FakeOffsetSource(0, 20), alerts=alerts)
    sync.tick()
    ledger = Ledger.open(base / "ledger", clock=clock)
    sink = RecordingSignals(ledger)
    return SignalDetector(config=config, clock=clock, sync=sync, ledger=ledger, sink=sink, alerts=alerts), sink, ledger


def test_F7_AC6_a_burst_of_100_fills_per_second_for_10_seconds_across_9_wallets_has_p99_s2_under_50_ms_and_drops_nothing(
    tmp_path: Path,
) -> None:
    detector, sink, ledger = wired_real_clock(tmp_path)
    try:
        wallets = [f"0x{i:040x}" for i in range(1, 10)]
        for w in wallets:
            detector.begin_follow(w, state({}), T0)
        rnd = random.Random(60)
        tid = 0
        expected: set[tuple[str, int]] = set()
        now = SystemClock().now_ms()
        for _ in range(10):  # ten simulated seconds, 100 fills each, delivered as fast as they can be processed
            per_wallet: dict[str, list[Any]] = {w: [] for w in wallets}
            for _ in range(100):
                tid += 1
                w = rnd.choice(wallets)
                per_wallet[w].append(mkfill(tid, coin=rnd.choice(["BTC", "ETH", "SOL", "kPEPE"]), time_ms=now - 300))
                expected.add((w, tid))
            for w, fills in per_wallet.items():
                if fills:
                    detector.on_fills(w, fills)
        got = {(s.wallet, s.tid) for s in sink.signals}
        assert got == expected and len(sink.signals) == 1000  # 0 fills dropped
        assert sum(1 for r in ledger.records() if r.kind == "signal") == 1000
        s2 = sorted(s.s2_ms for s in sink.signals)
        assert s2[math.ceil(0.99 * len(s2)) - 1] <= 50
    finally:
        ledger.close()


def test_F7_AC6_a_single_wallet_burst_of_100_fills_in_one_message_is_classified_within_the_budget(tmp_path: Path) -> None:
    detector, sink, ledger = wired_real_clock(tmp_path)
    try:
        detector.begin_follow(WALLET_A, state({}), T0)
        now = SystemClock().now_ms()
        detector.on_fills(WALLET_A, [mkfill(i, coin=f"C{i % 7}", time_ms=now - 100) for i in range(1, 101)])
        assert [s.tid for s in sink.signals] == list(range(1, 101))
        assert max(s.s2_ms for s in sink.signals) <= 50
    finally:
        ledger.close()


# --- percentile -------------------------------------------------------------------------------------------------------------


def test_F7_AC6_percentile_is_the_nearest_rank_value() -> None:
    values = list(range(1, 101))
    assert (percentile(values, 50), percentile(values, 95), percentile(values, 99), percentile(values, 100)) == (50, 95, 99, 100)
    assert percentile([10, 20, 30, 40], 50) == 20 and percentile([10, 20, 30, 40], 51) == 30
    assert percentile([7], 1) == percentile([7], 99) == 7
    assert percentile([30, 10, 20], 100) == 30  # input order does not matter


@pytest.mark.parametrize(("values", "q"), [([], 50), ([1], 0), ([1], 101), ([1], -5)])
def test_F7_AC6_percentile_rejects_empty_input_and_a_rank_outside_1_to_100(values: list[int], q: int) -> None:
    with pytest.raises(ValueError):
        percentile(values, q)


@given(values=st.lists(st.integers(-10_000, 10_000), min_size=1, max_size=60), q1=st.integers(1, 100), q2=st.integers(1, 100))
def test_F7_AC6_property_percentile_is_a_member_of_the_input_and_monotone_in_q(values: list[int], q1: int, q2: int) -> None:
    lo, hi = sorted((q1, q2))
    a, b = percentile(values, lo), percentile(values, hi)
    assert a in values and b in values and a <= b
    assert min(values) <= a <= max(values)


# --- the measurement run ------------------------------------------------------------------------------------------------------


class HookSleeper(FakeSleeper):
    """Sleeping advances the fake clock; after each sleep the test may deliver WebSocket messages that are due."""

    def __init__(self, clock: FakeClock, on_wake: Callable[[], None]) -> None:
        super().__init__(clock)
        self.on_wake = on_wake

    def sleep(self, seconds: float) -> None:
        super().sleep(seconds)
        self.on_wake()


class Harness:
    """Fake boundaries for ``measure_latency`` plus a schedule of leader fills: ``(second, wallet, age_ms, ...)``."""

    def __init__(self, *, wallets: tuple[str, ...] = (WALLET_A, WALLET_B), min_signals: int | None = None) -> None:
        self.cfg = make_config(**({"latency__min_signals": min_signals} if min_signals else {}))
        self.clock = FakeClock(T0)
        self.alerts = RecordingAlerts()
        self.offset = FakeOffsetSource(0, 20)
        self.sync = ClockSync.from_config(self.cfg, clock=self.clock, source=self.offset, alerts=self.alerts)
        self.sync.tick()
        self.connector = FakeConnector(self.clock, auto_pong=True)
        self.http = FakeHttp(self.clock)
        self.http.overrides["userFillsByTime"] = lambda call: []
        self.schedule: list[tuple[int, dict[str, Any]]] = []
        self.sleeper = HookSleeper(self.clock, self._wake)
        self.next_tid = 1
        self.wallets = wallets

    def leader_fill(self, second: int, wallet: str, age_ms: int, *, coin: str = "ETH", n: int = 1) -> None:
        fills = []
        for _ in range(n):
            fills.append(
                fill_json(
                    self.next_tid,
                    time_ms=T0 + second * SECOND - age_ms,
                    coin=coin,
                    side="B",
                    sz="1.0",
                    startPosition="0.0",
                    dir="Open Long",
                )
            )
            self.next_tid += 1
        self.schedule.append((T0 + second * SECOND, {"channel": "userFills", "data": {"user": wallet, "fills": fills}}))

    def _wake(self) -> None:
        due = [m for t, m in self.schedule if t <= self.clock.now_ms()]
        self.schedule = [(t, m) for t, m in self.schedule if t > self.clock.now_ms()]
        for message in due:
            self.connector.current.push(message)

    def boundaries(self) -> LatencyBoundaries:
        return LatencyBoundaries(
            clock=self.clock, sleeper=self.sleeper, connector=self.connector, transport=self.http, rng=random.Random(5), sync=self.sync
        )

    def run(self, base: Path, *, hours: int = 1, wallets: tuple[str, ...] | None = None) -> tuple[LatencyReport, Ledger]:
        ledger = Ledger.open(base / "ledger", clock=self.clock)
        report = measure_latency(
            hours=hours,
            wallets=wallets or self.wallets,
            config=self.cfg,
            boundaries=self.boundaries(),
            ledger=ledger,
            alerts=self.alerts,
        )
        return report, ledger


def kinds(ledger: Ledger) -> list[str]:
    return [r.kind for r in ledger.records()]


def samples(ledger: Ledger) -> list[dict[str, Any]]:
    return [dict(r.payload) for r in ledger.records() if r.kind == "latency_sample"]


AGES = [500, 700, 900, 1100, 2000, 3000]


def six_fills(h: Harness) -> None:
    for i, age in enumerate(AGES):
        h.leader_fill(60 + 60 * i, WALLET_A if i % 2 == 0 else WALLET_B, age)


def test_F7_AC6_latency_measure_ledgers_one_sample_per_signal_with_stages_s1_and_s2(tmp_path: Path) -> None:
    h = Harness()
    six_fills(h)
    report, ledger = h.run(tmp_path)
    try:
        rows = samples(ledger)
        assert [r["s1_ms"] for r in rows] == AGES  # S1: leader fill to receive
        assert [r["s2_ms"] for r in rows] == [0] * 6  # S2: receive to classified, on a frozen-per-call fake clock
        assert [r["wallet"] for r in rows] == [WALLET_A, WALLET_B] * 3
        assert all(r["coin"] == "ETH" and r["exchange_ts_ms"] < r["receive_ts_ms"] for r in rows)
        assert len({r["signal_id"] for r in rows}) == 6
    finally:
        ledger.close()


def test_F7_AC6_the_report_summarises_both_stages_with_nearest_rank_percentiles(tmp_path: Path) -> None:
    h = Harness()
    six_fills(h)
    report, ledger = h.run(tmp_path)
    ledger.close()
    assert isinstance(report, LatencyReport) and isinstance(report.s1, StageSummary)
    assert report.hours == 1 and report.wallets == (WALLET_A, WALLET_B) and report.signals == 6
    assert report.s1 == StageSummary(count=6, p50_ms=900, p95_ms=3000, p99_ms=3000)
    assert report.s2 == StageSummary(count=6, p50_ms=0, p95_ms=0, p99_ms=0)
    assert report.enough_samples is False  # latency.min_signals = 100


def test_F7_AC6_the_run_lasts_the_requested_hours_of_the_boundary_clock(tmp_path: Path) -> None:
    h = Harness()
    report, ledger = h.run(tmp_path, hours=2)
    ledger.close()
    assert report.started_ms == T0
    assert 2 * 3_600_000 <= report.ended_ms - report.started_ms <= 2 * 3_600_000 + 2 * SECOND
    assert report.signals == 0 and report.s1 is None and report.s2 is None and report.enough_samples is False


def test_F7_AC6_nothing_is_traded_only_info_requests_are_made_and_no_decision_or_order_record_exists(tmp_path: Path) -> None:
    h = Harness()
    six_fills(h)
    _, ledger = h.run(tmp_path)
    try:
        assert set(kinds(ledger)) <= {"signal", "latency_sample", "follow_started", "follow_ended", "downtime"}
        assert not {"decision", "fill", "trade", "order"} & set(kinds(ledger))
        assert h.http.calls and all(c.url.endswith("/info") for c in h.http.calls)
        assert {c.body["type"] for c in h.http.calls} <= {"clearinghouseState", "userFillsByTime", "userFills"}
        assert sorted(c.body["user"] for c in h.http.calls if c.body["type"] == "clearinghouseState") == [WALLET_A, WALLET_B]
        assert verify_ledger(tmp_path / "ledger").ok
    finally:
        ledger.close()


def test_F7_AC6_every_signal_is_sampled_including_pre_existing_and_out_of_scope_and_duplicates_are_not(tmp_path: Path) -> None:
    h = Harness()
    h.leader_fill(60, WALLET_A, 800, coin="BTC")  # the fixture state holds BTC: pre_existing
    h.leader_fill(120, WALLET_A, 900, coin="xyz:AAPL")  # HIP-3: out_of_scope
    h.leader_fill(180, WALLET_A, 1000, coin="ETH")
    dup = fill_json(1, time_ms=T0 + 60 * SECOND - 800, coin="BTC", side="B", sz="1.0", startPosition="0.0", dir="Open Long")
    h.schedule.append((T0 + 240 * SECOND, {"channel": "userFills", "data": {"user": WALLET_A, "fills": [dup]}}))
    report, ledger = h.run(tmp_path)
    try:
        assert report.signals == 3 and [r["s1_ms"] for r in samples(ledger)] == [800, 900, 1000]
        assert [r.payload["outcome"] for r in ledger.records() if r.kind == "signal"] == ["pre_existing", "out_of_scope", None]
    finally:
        ledger.close()


@pytest.mark.parametrize(("n", "enough"), [(49, False), (50, True), (51, True)])
def test_F7_AC6_enough_samples_is_signals_at_least_the_configured_minimum(tmp_path: Path, n: int, enough: bool) -> None:
    h = Harness(min_signals=50)
    h.leader_fill(60, WALLET_A, 500, n=n)
    report, ledger = h.run(tmp_path)
    ledger.close()
    assert report.signals == n and report.enough_samples is enough


def test_F7_AC6_a_wallet_list_with_duplicates_in_two_spellings_follows_it_once(tmp_path: Path) -> None:
    h = Harness()
    upper = WALLET_A.upper().replace("0X", "0x")
    report, ledger = h.run(tmp_path, wallets=(WALLET_A, upper, WALLET_B))
    ledger.close()
    assert report.wallets == (WALLET_A, WALLET_B)
    assert [c.body["user"] for c in h.http.calls if c.body["type"] == "clearinghouseState"].count(WALLET_A) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"hours": 0},
        {"hours": -1},
        {"wallets": ()},
        {"wallets": ("nope",)},
        {"wallets": (WALLET_A, "0x" + "g" * 40)},
        {"wallets": tuple(f"0x{i:040x}" for i in range(1, 12))},
    ],
)
def test_F7_AC6_bad_arguments_are_a_value_error_before_any_request_or_sleep(tmp_path: Path, bad: dict[str, Any]) -> None:
    h = Harness()
    args: dict[str, Any] = {"hours": 1, "wallets": (WALLET_A,)} | bad
    ledger = Ledger.open(tmp_path / "ledger", clock=h.clock)
    try:
        with pytest.raises(ValueError):
            measure_latency(config=h.cfg, boundaries=h.boundaries(), ledger=ledger, alerts=h.alerts, **args)
        assert h.http.calls == [] and h.sleeper.sleeps == [] and kinds(ledger) == []
    finally:
        ledger.close()


def test_F7_AC6_exactly_ten_distinct_wallets_are_accepted(tmp_path: Path) -> None:
    h = Harness()
    wallets = tuple(f"0x{i:040x}" for i in range(1, 11))
    report, ledger = h.run(tmp_path, wallets=wallets)
    ledger.close()
    assert report.wallets == wallets


def test_F7_AC6_the_measurement_modules_do_not_import_any_trading_module() -> None:
    root = Path(signals_pkg.__file__).parent
    files = [*root.glob("*.py"), Path(latency_cli.__file__)]
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_IMPORTS:
            if re.search(rf"^\s*(from|import)\s+copytrade\.{name}\b", text, re.M):
                offenders.append((path.name, name))
    assert offenders == []
    assert len(files) >= 5


# --- the command ------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def cli_root(tmp_path: Path) -> Path:
    return make_root(tmp_path / "root").root


def install(monkeypatch: pytest.MonkeyPatch, h: Harness | None) -> None:
    def build(config: Any) -> LatencyBoundaries:
        if h is None:
            raise AssertionError("boundaries must not be built for bad arguments")
        return h.boundaries()

    monkeypatch.setattr(latency_cli, "build_boundaries", build)


def cli(root: Path, ledger_dir: Path, *args: str) -> Any:
    return run_cli(["latency", "measure", "--root", str(root), "--ledger-dir", str(ledger_dir), *args])


def test_F7_AC6_latency_measure_runs_prints_both_stages_and_leaves_a_verifiable_ledger(
    tmp_path: Path, cli_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = Harness()
    six_fills(h)
    install(monkeypatch, h)
    result = cli(cli_root, tmp_path / "lat", "--hours", "1", "--wallets", f"{WALLET_A},{WALLET_B}")
    assert result.code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert "S1 n=6 p50=900 p95=3000 p99=3000" in lines
    assert "S2 n=6 p50=0 p95=0 p99=0" in lines
    assert "signals=6" in lines and "enough_samples=false" in lines
    assert verify_ledger(tmp_path / "lat").ok
    assert len([r for r in ledger_kinds(tmp_path / "lat") if r == "latency_sample"]) == 6


def ledger_kinds(directory: Path) -> list[str]:
    from copytrade.ledger.store import read_records

    return [r.kind for r in read_records(directory)]


@pytest.mark.parametrize(
    "extra",
    [
        ["--hours", "0", "--wallets", WALLET_A],
        ["--hours", "-2", "--wallets", WALLET_A],
        ["--hours", "1.5", "--wallets", WALLET_A],
        ["--hours", "abc", "--wallets", WALLET_A],
        ["--hours", "1", "--wallets", ""],
        ["--hours", "1", "--wallets", f"{WALLET_A},,{WALLET_B}"],
        ["--hours", "1", "--wallets", "0xnothex"],
        ["--hours", "1", "--wallets", ",".join(f"0x{i:040x}" for i in range(1, 12))],
        ["--wallets", WALLET_A],
        ["--hours", "1"],
    ],
)
def test_F7_AC6_bad_command_arguments_exit_2_without_building_any_boundary(
    tmp_path: Path, cli_root: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str]
) -> None:
    install(monkeypatch, None)
    assert cli(cli_root, tmp_path / "lat", *extra).code == 2


def test_F7_AC6_ten_wallets_with_a_repeat_in_another_spelling_is_accepted(
    tmp_path: Path, cli_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = Harness()
    install(monkeypatch, h)
    ten = [f"0x{i:040x}" for i in range(1, 11)]
    result = cli(cli_root, tmp_path / "lat", "--hours", "1", "--wallets", ",".join([*ten, ten[0].upper().replace("0X", "0x")]))
    assert result.code == 0, result.stderr


def test_F7_AC6_a_copytrade_error_while_measuring_exits_1_with_its_message(
    tmp_path: Path, cli_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build(config: Any) -> LatencyBoundaries:
        raise CopytradeError("no websocket connector is available")

    monkeypatch.setattr(latency_cli, "build_boundaries", build)
    result = cli(cli_root, tmp_path / "lat", "--hours", "1", "--wallets", WALLET_A)
    assert result.code == 1 and "no websocket connector is available" in result.stderr


def test_F7_AC6_an_invalid_config_root_exits_1_naming_the_problem_and_measures_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, None)
    (tmp_path / "empty").mkdir()
    result = cli(tmp_path / "empty", tmp_path / "lat", "--hours", "1", "--wallets", WALLET_A)
    assert result.code == 1 and result.stderr.strip() != ""


def test_F7_AC6_the_measurement_run_leaves_a_ledger_the_engine_can_ignore_and_uses_no_network(
    tmp_path: Path, cli_root: Path, monkeypatch: pytest.MonkeyPatch, network_guard: Any
) -> None:
    h = Harness()
    install(monkeypatch, h)
    result = cli(cli_root, tmp_path / "lat", "--hours", "1", "--wallets", WALLET_A)
    assert result.code == 0, result.stderr
    assert network_guard.attempts == []
