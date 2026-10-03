"""F1 edge cases the designed tests do not reach: secret value handling, money bounds, manifest patterns,
path-guard symlinks and the clock guard's clock-step and alert-delivery behaviour.

Added by the developer, not the test designer.
"""

from __future__ import annotations

import copy
import pickle
from decimal import Decimal
from pathlib import Path

import pytest

from copytrade.core.clock import ClockSync, OffsetEstimate, Timestamp, TimeSource
from copytrade.core.domain import ActionKind
from copytrade.core.errors import ClockUnsyncedError, EnginePathError
from copytrade.core.events import Alert
from copytrade.core.manifest import EnginePathSet, PathGuard
from copytrade.core.money import Price, round_price, round_size
from copytrade.core.secrets import SecretValue, load_secrets
from tests.core.test_clock import T0, FakeClock, RecordingAlerts, ScriptedOffsetSource, make_sync

pytestmark = pytest.mark.unit


# --- secrets (F1.AC5) ---------------------------------------------------------------------------------

def test_F1_AC5_secret_value_cannot_be_pickled_copied_into_text_or_mutated() -> None:
    secret = SecretValue("s3cr3t-value-for-the-test")
    with pytest.raises(TypeError):
        pickle.dumps(secret)
    assert copy.copy(secret) is secret and copy.deepcopy(secret) is secret
    assert f"{secret:>40}".strip() == "SecretValue(<redacted>)"
    with pytest.raises(AttributeError):
        secret._value = "other"  # type: ignore[misc]
    assert secret.reveal() == "s3cr3t-value-for-the-test"


def test_F1_AC5_secret_value_rejects_non_text_and_empty() -> None:
    with pytest.raises(TypeError):
        SecretValue(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SecretValue("")


def test_F1_AC5_secrets_are_immutable_and_report_only_which_are_set() -> None:
    secrets = load_secrets({"COPYTRADE_LLM_API_KEY": "k-not-real-0123456789"})
    assert "llm_api_key=set" in repr(secrets) and "telegram_token=unset" in repr(secrets)
    with pytest.raises(AttributeError):
        secrets.llm_api_key = None  # type: ignore[misc]


# --- money (F1.AC4) -------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["1_000", " 1", "1 ", "١٢٣", "1e", "--1", "0x10", "1,5"])
def test_F1_AC4_malformed_money_strings_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        Price(text)


def test_F1_AC4_a_negative_price_is_rejected_but_zero_is_constructible() -> None:
    with pytest.raises(ValueError):
        Price("-0.01")
    assert Price("0") == 0


@pytest.mark.parametrize(("px", "sz"), [("0.0000009", 0), ("0.00009", 2), ("1e-30", 0)])
def test_F1_AC4_a_price_below_the_smallest_tick_is_rejected(px: str, sz: int) -> None:
    with pytest.raises(ValueError):
        round_price(Decimal(px), sz)


@pytest.mark.parametrize("value", [Decimal("1e60"), Decimal("-1e60")])
def test_F1_AC4_absurd_magnitudes_are_rejected_not_silently_rounded(value: Decimal) -> None:
    with pytest.raises(ValueError):
        round_size(value, 3)
    with pytest.raises(ValueError):
        round_price(abs(value), 3)


def test_F1_AC4_a_tie_between_two_valid_prices_goes_to_the_lower() -> None:
    assert round_price(Decimal("1.23455"), 0) == Decimal("1.2345")


def test_F1_AC4_a_negative_size_that_rounds_to_zero_is_plain_zero() -> None:
    assert str(round_size(Decimal("-0.0001"), 2)) == "0.00"


def test_F1_AC4_rounded_prices_and_sizes_never_carry_a_positive_exponent() -> None:
    assert str(round_price(Decimal("1E+2"), 0)) == "100"


# --- engine path set (F1.AC7) ---------------------------------------------------------------------------

@pytest.mark.parametrize("pattern", ["**", "/src/**", "../x/**", "src/**/x.py", "C:/src/**", "src/../../x"])
def test_F1_AC7_malformed_manifest_patterns_fail_closed(pattern: str) -> None:
    with pytest.raises(EnginePathError):
        EnginePathSet.from_lines([pattern])


def test_F1_AC7_a_directory_glob_does_not_cover_the_directory_itself() -> None:
    assert EnginePathSet.from_lines(["config/**"]).covers("config") is False


def test_F1_AC7_a_symlink_out_of_the_root_is_refused_by_the_path_guard(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    outside = tmp_path / "outside.toml"
    outside.write_text("x = 1\n", encoding="utf-8")
    link = root / "config" / "risk.toml"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available on this platform")
    with pytest.raises(EnginePathError) as info:
        PathGuard(EnginePathSet.from_lines(["config/**"]), root).check(link)
    assert "outside.toml" in str(info.value)


def test_F1_AC7_an_unreadable_manifest_names_the_file_and_never_echoes_its_content(tmp_path: Path) -> None:
    manifest = tmp_path / "engine-path-set.txt"
    manifest.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(EnginePathError) as info:
        EnginePathSet.from_file(manifest)
    assert "engine-path-set.txt" in str(info.value)


# --- clock (F1.AC6) -------------------------------------------------------------------------------------

def test_F1_AC6_exchange_now_before_any_estimate_raises_a_typed_error() -> None:
    sync, _, _, _ = make_sync()
    with pytest.raises(ClockUnsyncedError):
        sync.exchange_now()


def test_F1_AC6_a_local_clock_that_steps_backwards_refuses_entries_until_the_next_estimate() -> None:
    sync, clock, _, _ = make_sync(interval_s=600)
    sync.tick()
    clock.advance(-5_000)
    assert sync.refusal_reason(ActionKind.OPEN) == "clock_unsynced"
    assert sync.refusal_reason(ActionKind.CLOSE) is None
    sync.tick()  # the step also makes a re-estimate due at once
    assert sync.refusal_reason(ActionKind.OPEN) is None


def test_F1_AC6_a_failed_alert_delivery_is_retried_on_the_next_tick_until_sent() -> None:
    class FlakyAlerts(RecordingAlerts):
        failures_left = 2

        def send(self, alert: Alert) -> None:
            if self.failures_left:
                self.failures_left -= 1
                raise OSError("telegram unreachable")
            super().send(alert)

    clock, source, alerts = FakeClock(), ScriptedOffsetSource(), FlakyAlerts()
    source.next_estimate = OffsetEstimate(offset_ms=0, uncertainty_ms=999)
    sync = ClockSync(
        offset_interval_s=600, max_offset_uncertainty_ms=100, max_estimate_age_s=1800, clock=clock, source=source, alerts=alerts
    )
    for _ in range(5):
        sync.tick()
    assert len(alerts.sent) == 1


def test_F1_AC6_an_unusable_estimate_from_the_source_counts_as_a_failed_attempt() -> None:
    class BadSource:
        def estimate(self) -> OffsetEstimate:
            return OffsetEstimate(offset_ms=0, uncertainty_ms=-1)

    sync = ClockSync(
        offset_interval_s=600,
        max_offset_uncertainty_ms=100,
        max_estimate_age_s=1800,
        clock=FakeClock(),
        source=BadSource(),
        alerts=RecordingAlerts(),
    )
    sync.tick()
    assert sync.refusal_reason(ActionKind.ADD) == "clock_unsynced"


@pytest.mark.parametrize("kwargs", [{"offset_interval_s": 0}, {"max_offset_uncertainty_ms": -1}, {"max_estimate_age_s": True}])
def test_F1_AC6_nonsense_thresholds_are_rejected_at_construction(kwargs: dict[str, int]) -> None:
    params = {
        "offset_interval_s": 600,
        "max_offset_uncertainty_ms": 100,
        "max_estimate_age_s": 1800,
        "clock": FakeClock(),
        "source": ScriptedOffsetSource(),
        "alerts": RecordingAlerts(),
    } | kwargs
    with pytest.raises(ValueError):
        ClockSync(**params)  # type: ignore[arg-type]


def test_F1_AC6_offset_estimate_and_timestamp_reject_wrong_types() -> None:
    with pytest.raises(TypeError):
        OffsetEstimate(offset_ms=1.5, uncertainty_ms=1)  # type: ignore[arg-type]
    assert Timestamp(ms=T0, source=TimeSource.LOCAL).to_datetime().year == 2026
