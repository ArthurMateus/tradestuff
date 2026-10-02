"""Hard ceilings and floors compiled into code (F1.AC2, invariant A3).

Every numeric §3 key has its bounds here as constants; config can never raise a Max or lower a Min.
"fixed" keys have Min = Max. Bounds that are another key's value (e.g. ``select.min_followed`` <=
``select.max_followed``) are cross-key rules, checked by the loader (``copytrade.core.config``); the
constants below carry only the part that follows statically from the other key's own bounds.

The module also exposes ``HIGH_LEVERAGE_COIN_UNIVERSE: frozenset[str]``, the compiled set that
``risk.high_leverage_coins`` must be a subset of ({BTC, ETH, SOL}, spec §3.6), and ``FIXED_VALUES``,
the compiled value of every non-numeric "fixed" key.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class Bounds:
    """Compiled bounds of one §3 key. ``None`` means unbounded on that side.

    ``min_exclusive`` is True where the spec says "> x" (e.g. ``storage.price_usd_per_gb_month`` > 0).
    """

    min: int | Decimal | None
    max: int | Decimal | None
    min_exclusive: bool


class NumberKind(Enum):
    """Whether a numeric key is a whole number or a Decimal."""

    INT = "int"
    DECIMAL = "decimal"


@dataclass(frozen=True)
class NumericSpec:
    """A numeric §3 key: its kind and its compiled bounds."""

    kind: NumberKind
    bounds: Bounds


HIGH_LEVERAGE_COIN_UNIVERSE: frozenset[str] = frozenset({"BTC", "ETH", "SOL"})

# The six score components (EH §10.4): each has a weight (0..1, all summing to 1) and lo/hi anchors (lo != hi).
SCORE_COMPONENTS: tuple[str, ...] = ("dsr_excess", "copy_mean_r", "pos_blocks", "max_dd", "recent_sr", "executable")

_INT = NumberKind.INT
_DEC = NumberKind.DECIMAL
_NUMERIC: dict[str, NumericSpec] = {}


def _bound(kind: NumberKind, value: int | str | None) -> int | Decimal | None:
    if value is None:
        return None
    return int(value) if kind is _INT else Decimal(value)


def _num(
    key: str,
    kind: NumberKind,
    lo: int | str | None = None,
    hi: int | str | None = None,
    *,
    lo_exclusive: bool = False,
) -> None:
    """Declare one numeric key. Bounds are written as ints or decimal strings so no float is involved."""
    if key in _NUMERIC:
        raise ValueError(f"duplicate ceiling declaration for {key}")
    _NUMERIC[key] = NumericSpec(kind, Bounds(_bound(kind, lo), _bound(kind, hi), lo_exclusive))


def _int(key: str, lo: int | None = None, hi: int | None = None) -> None:
    _num(key, _INT, lo, hi)


def _dec(key: str, lo: str | None = None, hi: str | None = None, *, lo_exclusive: bool = False) -> None:
    _num(key, _DEC, lo, hi, lo_exclusive=lo_exclusive)


def _fixed_int(key: str, value: int) -> None:
    _num(key, _INT, value, value)


def _fixed_dec(key: str, value: str) -> None:
    _num(key, _DEC, value, value)


# --- 3.1 Platform, storage, supervisor --------------------------------------------------------------
_int("storage.upload_delay_min", 5, 120)
_int("storage.upload_deadline_h", 1, 24)
_int("storage.local_retention_days", 2, 30)
_int("storage.max_unarchived_days", 1, 7)
_int("storage.cache_max_gb", 2, 50)
_int("storage.read_retry_max_min", 1, 240)
_int("storage.retry_interval_min", 1, 120)
_int("storage.alert_interval_h", 1, 24)
_dec("storage.monthly_budget_usd", "0", "5")
_dec("storage.budget_alert_fraction", "0.1", "1.0")
_dec("storage.price_usd_per_gb_month", "0", lo_exclusive=True)
_dec("storage.price_usd_per_10k_ops", "0")
_int("clock.offset_interval_s", 60, 3600)
_int("clock.max_offset_uncertainty_ms", 10, 500)
_int("clock.max_estimate_age_s", 600, 3600)
_int("ledger.heartbeat_interval_s", 1, 60)
_int("supervisor.restart_delay_s", 5, 120)
_int("supervisor.max_restarts_per_hour", 1, 10)

# --- 3.2 Hyperliquid client and feeds ---------------------------------------------------------------
_int("hl.rest_weight_budget_per_min", 100, 1100)
_dec("hl.scoring_weight_share", "0.1", "0.8")
_int("hl.weight_userRole", 20)
_int("hl.weight_portfolio", 20)
_int("hl.rest_timeout_s", 2, 30)
_int("hl.retry_max", 0, 8)
_int("hl.backoff_base_s", 1, 10)
_int("hl.backoff_max_s", 10, 300)
_int("hl.ws_max_unique_users", 1, 10)
_int("hl.ws_max_new_conns_per_min", 1, 30)
_int("hl.ws_ping_interval_s", 5, 50)
_int("hl.ws_reconnect_backoff_max_s", 5, 120)
_int("hl.ws_connect_timeout_s", 2, 30)
_int("hl.ws_max_message_bytes", 65_536, 16_777_216)
_int("feed.stale_after_s", 5, 60)
_int("access.degraded_error_count", 1, 20)
_int("access.degraded_window_min", 1, 30)
_dec("access.degraded_min_success_rate", "0.1", "0.9")
_int("access.recover_min", 1, 60)
_int("follow.clearinghouse_poll_s", 10, 300)
_int("follow.max_leader_av_age_s", 60, 900)

# --- 3.3 Recorder -----------------------------------------------------------------------------------
_int("recording.max_coins", 10, 400)
_int("recording.universe_lookback_days", 7, 90)
_int("recording.l2_levels", 5, 20)
_int("recording.l2_interval_ms", 500, 4000)
_int("recording.asset_ctx_interval_s", 10, 300)
_int("recording.leaderboard_interval_min", 15, 60)
_int("recording.disk_check_interval_s", 10, 300)
_int("recording.disk_alert_free_gb", 6)  # and above disk_floor_free_gb (cross-key)
_int("recording.disk_floor_free_gb", 5)
_int("recording.disk_resume_margin_gb", 1, 20)
_dec("recording.max_gb_per_day", "0.1", "5")
_fixed_int("recording.segment_hash_minutes", 5)

# --- 3.4 Scoring and selection ----------------------------------------------------------------------
_int("scoring.candidates_k", 50, 500)
_int("scoring.interval_min", 15, 1440)
_int("scoring.window_days", 90, 365)
_int("scoring.dsr_min_daily_days", 30)
_int("scoring.stale_input_mult", 1, 4)
_int("gate.min_account_age_days", 90)
_int("gate.min_round_trips", 50)
_int("gate.min_fill_span_days", 30)
_int("gate.min_positive_blocks", 1, 12)  # and at most gate.n_blocks (cross-key)
_int("gate.n_blocks", 2, 12)
_int("gate.block_days", 7, 90)
_dec("gate.max_drawdown", "0.05", "0.50")
_dec("gate.min_profit_factor", "1.0")
_dec("gate.min_dsr_prob", "0.50", "0.99")
_int("gate.dsr_n_trials", 50)  # and at least scoring.candidates_k (cross-key)
_int("gate.min_median_hold_min", 5)
_int("gate.hold_latency_mult", 5)
_dec("gate.max_top_trade_share", "0.05", "1.0")
_dec("gate.max_top_asset_share", "0.10", "1.0")
_dec("gate.min_copy_edge_ratio", "1.0")
_dec("gate.min_account_value_usd", "1000")
_dec("gate.min_executable_share", "0.10", "1.0")
_dec("gate.max_maker_share", "0.10", "1.0")
_dec("gate.max_current_drawdown", "0.05", "0.50")
_dec("blowup.max_adds_while_losing_share", "0", "1")
_int("blowup.min_adds", 1)
_dec("blowup.max_size_after_loss_ratio", "1.0")
_int("blowup.min_each", 5)
_dec("blowup.skew_win_rate", "0.5", "1")
_dec("blowup.skew_loss_mult", "1")
_dec("blowup.max_worst_to_median_loss", "2")
_int("blowup.min_losses", 3)
_dec("blowup.hidden_dd_mult", "1")
_dec("blowup.hidden_dd_floor", "0", "1")
_int("blowup.max_median_eff_leverage", 1, 50)
_dec("blowup.max_open_unrealized_loss", "0.01", "1.0")
for _component in SCORE_COMPONENTS:
    _dec(f"score.weights.{_component}", "0", "1")  # all six sum to 1 (cross-key)
    _dec(f"score.anchors.{_component}.lo")  # lo != hi (cross-key)
    _dec(f"score.anchors.{_component}.hi")
_int("score.shrink_k_trades", 0)
_int("score.shrink_k_days_recent", 0)
_int("select.join_rank", 1)
_int("select.drop_rank", 2)  # and above select.join_rank (cross-key)
_int("select.join_confirm_cycles", 1, 6)
_int("select.drop_confirm_cycles", 1, 6)
_int("select.min_follow_hours", 1)
_int("select.min_followed", 1, 9)  # and at most select.max_followed (cross-key)
_int("select.max_followed", 1, 9)
_int("select.backfill_max_hours", 1, 48)
_dec("select.swap_margin", "0", "1")
_int("select.max_swaps_per_cycle", 0, 1)
_int("select.max_cycle_duration_min", 10, 1440)  # and at most scoring.interval_min (cross-key)
_dec("leader_pause.max_copy_dd", "0.02", "0.50")
_int("leader_pause.max_consec_losses", 2, 20)
_dec("risk.leader_allocation_fraction", "0.05", "0.50")
_int("copyreplay.delay_ms", 250, 5000)
_dec("copyreplay.half_spread_bps.major", "2")
_dec("copyreplay.half_spread_bps.alt", "8")

# --- 3.5 Markets, filter, calendar ------------------------------------------------------------------
_int("tiers.lookback_days", 3, 30)
_int("tiers.recompute_interval_h", 1, 168)
_int("tiers.max_age_h", 2, 336)
_dec("tiers.depth_band_pct", "0.1", "2.0")
_dec("tiers.tier1_min_depth_usd", "20000")  # and at least floor_min_depth_usd (cross-key)
_dec("tiers.tier1_min_volume_usd", "2000000")  # and at least floor_min_volume_usd (cross-key)
_dec("tiers.floor_min_depth_usd", "20000")
_dec("tiers.floor_min_volume_usd", "2000000")
_dec("tiers.min_coverage_fraction", "0.5", "1.0")
_int("filter.max_signal_age_ms", 500, 5000)
_dec("filter.max_slippage_pct_tier1", "0.05", "0.30")
_dec("filter.max_slippage_pct_tier2", "0.10", "0.80")
_dec("filter.max_spread_pct_tier1", "0.01", "0.30")
_dec("filter.max_spread_pct_tier2", "0.02", "0.80")
_dec("filter.max_depth_share", "0.001", "0.05")
_dec("filter.depth_band_pct", "0.1", "2.0")
_int("filter.max_price_age_ms", 250, 5000)
_int("filter.vol_window_h", 4, 72)
_int("filter.vol_lookback_days", 30, 200)
_int("filter.vol_halving_percentile", 50, 99)
_dec("filter.vol_size_mult", "0.1", "1.0")  # never raises size
_int("filter.trend.ema_period_h", 10, 200)
_dec("filter.trend.min_aligned_atr", "-5", "5")
_dec("filter.funding.max_adverse_rate_per_h", "0", "0.04")
_dec("filter.oi_drop.max_drop_pct_24h", "5", "90")
_dec("filter.premium.max_abs_pct", "0.05", "10")
_int("calendar.window_fomc_min.before", 0, 240)
_int("calendar.window_fomc_min.after", 0, 240)
_int("calendar.window_tier1_min.before", 0, 240)
_int("calendar.window_tier1_min.after", 0, 240)
_int("calendar.min_coverage_days", 67, 120)

# --- 3.6 Risk, sizing, exits ------------------------------------------------------------------------
_dec("risk.per_trade_fraction", "0.001", "0.01")
_dec("risk.max_share_risk_fraction", "0.005", "0.02")
_dec("risk.max_total_open_risk_fraction", "0.005", "0.10")
_dec("risk.max_symbol_open_risk_fraction", "0.005", "0.03")
_dec("risk.max_btc_bucket_open_risk_fraction", "0.005", "0.05")
_dec("risk.btc_bucket_corr_threshold", "0.3", "0.9")
_int("risk.btc_bucket_corr_window_days", 7, 90)
_dec("risk.max_leader_open_risk_fraction", "0.005", "0.03")
_int("risk.max_open_positions", 1, 10)
_dec("risk.max_position_notional_equity_mult", "0.1", "3.0")
_int("risk.leverage_min", 1, 3)
_int("risk.max_leverage_alt", 1, 5)
_int("risk.max_leverage_high_tier", 1, 10)
_dec("risk.min_liq_distance_stop_mult", "3")
_dec("risk.daily_loss_limit", "0.005", "0.05")
_dec("risk.weekly_loss_limit", "0.01", "0.10")
_int("risk.max_orders_per_min", 1, 60)
_dec("sizing.min_order_usd", "10")
_fixed_dec("paper.wallet_usd", "300")
_dec("live.min_wallet_usd", "300")
_dec("exits.stop_atr_mult", "1.0", "4.0")
_int("exits.atr_period", 5, 50)
_dec("exits.tp1_r", "0.5", "10")
_dec("exits.tp1_fraction", "0.1", "1.0")
_dec("exits.trail_start_r", "0.25", "5")
_dec("exits.trail_atr_mult", "0.5", "5")
_fixed_int("exits.missed_exit_max_lag_s", 60)
_int("exits.retry_interval_s", 1, 5)
_int("exits.alert_after_s", 5, 60)
_int("reconcile.interval_s", 60, 600)

# --- 3.7 Paper costs and restart --------------------------------------------------------------------
_dec("cost.taker_fee_bps", "4.5", "20")
_dec("cost.maker_fee_bps", "1.5", "20")
_int("paper.ack_delay_ms", 500, 5000)
_int("paper.max_book_age_ms", 1000, 5000)
_int("paper.meta_refresh_min", 5, 1440)
_dec("cost.fallback_half_spread_bps.major", "2")
_dec("cost.fallback_half_spread_bps.alt", "8")
_dec("cost.fallback_half_spread_mult", "1.5")
_dec("cost.fallback_delay_slippage_bps.major", "5")
_dec("cost.fallback_delay_slippage_bps.alt", "15")
_int("restart.max_reconstruct_gap_h", 1, 84)

# --- 3.8 Telegram, reports, LLM, latency ------------------------------------------------------------
_int("telegram.allowed_user_id")
_int("telegram.control_chat_id")
_int("telegram.alerts_chat_id")  # group and channel IDs are negative
_int("telegram.min_edit_interval_s", 3, 60)
_int("telegram.max_msgs_per_min_per_chat", 1, 20)
_int("telegram.queue_max_messages", 10, 10000)
_int("telegram.queue_max_age_h", 1, 72)
_int("telegram.pin_max_attempts", 1, 5)
_int("telegram.pin_lockout_min", 5, 1440)
_int("telegram.unauthorized_alert_interval_min", 1, 60)
_fixed_int("report.weekly_block_days", 7)
_dec("llm.monthly_budget_usd", "0", "20")
_int("llm.timeout_s", 1, 30)
_int("llm.max_output_chars", 100, 1500)
_dec("llm.price_usd_per_1k_tokens.input", "0", lo_exclusive=True)
_dec("llm.price_usd_per_1k_tokens.output", "0", lo_exclusive=True)
_int("latency.measure_hours", 24)
_int("latency.min_signals", 50)

# --- 3.9 Replay, run and evaluation (pre-registered, fixed) -----------------------------------------
_fixed_int("replay.max_variants", 8)
_fixed_int("eval.n_trades", 300)
_fixed_int("eval.calendar_cap_days", 30)
_fixed_int("eval.extension_days", 30)
_fixed_int("eval.closeout_max_days", 7)
_fixed_dec("eval.ci_level_run1", "0.96")
_fixed_dec("eval.ci_level_run2", "0.99")
_fixed_int("eval.max_runs", 2)
_fixed_int("eval.min_day_clusters", 5)
_fixed_int("eval.bootstrap_b", 10000)
_fixed_int("eval.gate_round_dp", 6)
_fixed_dec("eval.max_dd", "0.15")
_fixed_int("eval.mark_interval_s", 60)
_fixed_dec("eval.max_downtime_fraction", "0.02")
_fixed_int("eval.missed_exit_max_count", 3)
_fixed_dec("eval.missed_exit_max_cost_r", "1.0")
_fixed_int("eval.fill_audit_interval_h", 24)
_fixed_int("eval.missing_data_retry_max_h", 72)
_fixed_int("baseline.dm_min_admissible_hours", 24)
_fixed_dec("baseline.dm_max_missing_share", "0.10")
_fixed_int("baseline.dm_max_book_gap_s", 5)
_fixed_int("baseline.dm_max_mid_gap_s", 60)
_fixed_int("baseline.dm_reps", 1000)
_fixed_int("baseline.random_reps", 1000)
_fixed_int("baseline.top_roi_n", 9)
_fixed_int("fragility.top_k_trades", 5)
_fixed_int("fragility.drop_best_day_clusters", 1)
_fixed_dec("fragility.cost_stress_mult", "2.0")
_fixed_dec("d6.min_decision_agreement", "0.90")
_fixed_dec("d6.max_median_abs_r_diff", "0.05")
_fixed_dec("d6.max_mean_r_diff", "0.10")
_fixed_int("d6.max_median_fill_dev_bps", 3)
_fixed_int("d6.max_p90_fill_dev_bps", 10)
_fixed_dec("d6.max_trade_count_dev", "0.10")
_fixed_int("kill.k1_min_trades", 100)
_fixed_int("kill.k2_min_trades", 150)
_fixed_dec("kill.k6_decay_share", "0.50")
_fixed_int("kill.k7_min_eligible", 5)
_fixed_dec("kill.k7_cycle_share", "0.50")
_fixed_dec("kill.k8_unexecutable_share", "0.50")

NUMERIC_KEYS: Mapping[str, NumericSpec] = _NUMERIC

FIXED_VALUES: Mapping[str, str | bool | tuple[str, ...]] = {
    "recording.candle_store": "hourly_1m_1h_hashed",
    "markets.allowed_dexes": ("core",),
    "calendar.timezone": "America/New_York",
    "sizing.partial_below_min_action": "skip_and_log",
    "sizing.close_all_if_remainder_below_min": True,
    "cost.funding_accrual": "hourly_actual",
    "cost.fallback_tier_rule": "tightest_tier_conservative",
    "restart.candle_interval": "1m",
    "eval.sample_basis": "opened",
    "eval.ci_method": "min3",
    "eval.cluster_key": "merged_first_entry_day",
    "eval.bootstrap_seed": "generated",
    "eval.bootstrap_statistic": "pooled_mean",
    "eval.rng": "sha256_counter_rejection",
    "eval.percentile_index": "floor_index",
    "eval.flatten_gate_rule": "min_realised_shadow",
    "eval.require_clean_engine_tree": True,
    "eval.engine_path_manifest": "engine-path-set.txt",
    "eval.run_worktree_pinned": True,
    "eval.run_record_env_hashes": ("packages", "data_inputs"),
    "eval.deploy_policy": "auditor_ruling_required",
    "eval.require_usd_pnl_positive": True,
    "eval.baseline_gate": "direction_matched_random_time",
    "eval.show_interim_stats": "descriptive_only",
    "eval.missed_exit_gate_rule": "min_actual_mirrored",
    "eval.missed_exit_gap_rule": "candle_lo_stop_first_hi_tp_first",
    "eval.missed_exit_cost_rule": "incremental_and_trade_hi",
    "eval.p4_breach_time": "earliest_event_order",
    "eval.settled_gap_rule": "settled_min_lo",
    "eval.recording_integrity": "lossless_hashed_verified",
    "baseline.dm_exclude_downtime": True,
    "baseline.dm_discretionary_pause_rule": "max_all_outside_pause",
    "baseline.dm_costs": "own_time_no_decay",
    "baseline.dm_missing_rule": "min_r_0_partial",
    "data.paid_s3": False,
}


def ceiling_for(key: str) -> Bounds:
    """Return the compiled bounds of a numeric §3 key.

    Raises:
        KeyError: ``key`` is not a numeric §3 key.
    """
    return _NUMERIC[key].bounds
