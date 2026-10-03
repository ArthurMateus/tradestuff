"""F1.AC2: hard ceilings and floors are constants in code; config can never raise them.

For every §3 key with a Max: the Max loads and one step above is rejected. For every key with a Min:
the Min loads and one step below is rejected. "fixed" keys accept only their value. Steps: +/-1 for
integer keys; +/-0.0001 for decimal keys, unless the spec's required case gives the step.

Spec: 04-spec.md F1.AC2 (Amendment 1), §3 tables, invariant A3.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from copytrade.core import ceilings
from copytrade.core.ceilings import ceiling_for
from copytrade.core.config import load_config
from copytrade.core.errors import ConfigError
from copytrade.core.startup import startup
from tests.core.helpers import REPO_ROOT, ConfigTree, fixture_leaves, make_root, same_kind

pytestmark = pytest.mark.unit

D = Decimal
LEAVES = fixture_leaves()

# (key, value at the Max that loads, value one step above that is rejected, companion overrides)
MAX_CASES: list[tuple[str, Any, Any, dict[str, Any]]] = [
    ("storage.upload_delay_min", 120, 121, {}),
    ("storage.upload_deadline_h", 24, 25, {}),
    ("storage.local_retention_days", 30, 31, {}),
    ("storage.max_unarchived_days", 7, 8, {}),
    ("storage.cache_max_gb", 50, 51, {}),
    ("storage.read_retry_max_min", 240, 241, {}),
    ("storage.retry_interval_min", 120, 121, {}),
    ("storage.alert_interval_h", 24, 25, {}),
    ("storage.monthly_budget_usd", "5", "5.0001", {}),
    ("storage.budget_alert_fraction", "1.0", "1.0001", {}),
    ("clock.offset_interval_s", 3600, 3601, {}),
    ("clock.max_offset_uncertainty_ms", 500, 501, {}),
    ("clock.max_estimate_age_s", 3600, 3601, {}),
    ("ledger.heartbeat_interval_s", 60, 61, {}),
    ("supervisor.restart_delay_s", 120, 121, {}),
    ("supervisor.max_restarts_per_hour", 10, 11, {}),
    ("hl.rest_weight_budget_per_min", 1100, 1101, {}),
    ("hl.scoring_weight_share", "0.8", "0.8001", {}),
    ("hl.rest_timeout_s", 30, 31, {}),
    ("hl.retry_max", 8, 9, {}),
    ("hl.backoff_base_s", 10, 11, {}),
    ("hl.backoff_max_s", 300, 301, {}),
    ("hl.ws_max_unique_users", 10, 11, {}),
    ("hl.ws_max_new_conns_per_min", 30, 31, {}),
    ("hl.ws_ping_interval_s", 50, 51, {}),
    ("hl.ws_reconnect_backoff_max_s", 120, 121, {}),
    ("feed.stale_after_s", 60, 61, {}),
    ("access.degraded_error_count", 20, 21, {}),
    ("access.degraded_window_min", 30, 31, {}),
    ("access.degraded_min_success_rate", "0.9", "0.9001", {}),
    ("access.recover_min", 60, 61, {}),
    ("follow.clearinghouse_poll_s", 300, 301, {}),
    ("follow.max_leader_av_age_s", 900, 901, {}),
    ("recording.max_coins", 400, 401, {}),
    ("recording.universe_lookback_days", 90, 91, {}),
    ("recording.l2_levels", 20, 21, {}),
    ("recording.l2_interval_ms", 4000, 4001, {}),
    ("recording.asset_ctx_interval_s", 300, 301, {}),
    ("recording.leaderboard_interval_min", 60, 61, {}),
    ("recording.disk_check_interval_s", 300, 301, {}),
    ("recording.disk_resume_margin_gb", 20, 21, {}),
    ("recording.max_gb_per_day", "5", "5.0001", {}),
    ("scoring.candidates_k", 500, 501, {}),
    ("scoring.interval_min", 1440, 1441, {}),
    ("scoring.window_days", 365, 366, {}),
    ("scoring.stale_input_mult", 4, 5, {}),
    ("gate.min_positive_blocks", 6, 7, {}),  # Max = gate.n_blocks (6)
    ("gate.n_blocks", 12, 13, {}),
    ("gate.block_days", 90, 91, {}),
    ("gate.max_drawdown", "0.50", "0.5001", {}),
    ("gate.min_dsr_prob", "0.99", "0.9901", {}),
    ("gate.max_top_trade_share", "1.0", "1.0001", {}),
    ("gate.max_top_asset_share", "1.0", "1.0001", {}),
    ("gate.min_executable_share", "1.0", "1.0001", {}),
    ("gate.max_maker_share", "1.0", "1.0001", {}),
    ("gate.max_current_drawdown", "0.50", "0.5001", {}),
    ("blowup.max_adds_while_losing_share", "1", "1.0001", {}),
    ("blowup.skew_win_rate", "1", "1.0001", {}),
    ("blowup.hidden_dd_floor", "1", "1.0001", {}),
    ("blowup.max_median_eff_leverage", 50, 51, {}),
    ("blowup.max_open_unrealized_loss", "1.0", "1.0001", {}),
    ("select.join_confirm_cycles", 6, 7, {}),
    ("select.drop_confirm_cycles", 6, 7, {}),
    ("select.min_followed", 9, 10, {}),  # Max = select.max_followed (9)
    ("select.max_followed", 9, 10, {}),
    ("select.backfill_max_hours", 48, 49, {}),
    ("select.swap_margin", "1", "1.0001", {}),
    ("select.max_swaps_per_cycle", 1, 2, {}),
    ("select.max_cycle_duration_min", 60, 61, {}),  # Max = scoring.interval_min (60)
    ("leader_pause.max_copy_dd", "0.50", "0.5001", {}),
    ("leader_pause.max_consec_losses", 20, 21, {}),
    ("risk.leader_allocation_fraction", "0.50", "0.5001", {}),
    ("copyreplay.delay_ms", 5000, 5001, {}),
    ("tiers.lookback_days", 30, 31, {}),
    ("tiers.recompute_interval_h", 168, 169, {}),
    ("tiers.max_age_h", 336, 337, {}),
    ("tiers.depth_band_pct", "2.0", "2.0001", {}),
    ("tiers.min_coverage_fraction", "1.0", "1.0001", {}),
    ("filter.max_signal_age_ms", 5000, 5001, {}),
    ("filter.max_slippage_pct_tier1", "0.30", "0.3001", {}),
    ("filter.max_slippage_pct_tier2", "0.80", "0.8001", {}),
    ("filter.max_spread_pct_tier1", "0.30", "0.3001", {}),
    ("filter.max_spread_pct_tier2", "0.80", "0.8001", {}),
    ("filter.max_depth_share", "0.05", "0.0501", {}),
    ("filter.depth_band_pct", "2.0", "2.0001", {}),
    ("filter.max_price_age_ms", 5000, 5001, {}),
    ("filter.vol_window_h", 72, 73, {}),
    ("filter.vol_lookback_days", 200, 201, {}),
    ("filter.vol_halving_percentile", 99, 100, {}),
    ("filter.vol_size_mult", "1.0", "1.0001", {}),
    ("filter.trend.ema_period_h", 200, 201, {}),
    ("filter.trend.min_aligned_atr", D("5"), D("5.0001"), {}),
    ("filter.funding.max_adverse_rate_per_h", D("0.04"), D("0.0401"), {}),
    ("filter.oi_drop.max_drop_pct_24h", D("90"), D("90.0001"), {}),
    ("filter.premium.max_abs_pct", D("10"), D("10.0001"), {}),
    ("calendar.window_fomc_min.before", 240, 241, {}),
    ("calendar.window_fomc_min.after", 240, 241, {}),
    ("calendar.window_tier1_min.before", 240, 241, {}),
    ("calendar.window_tier1_min.after", 240, 241, {}),
    ("calendar.min_coverage_days", 120, 121, {}),
    ("risk.per_trade_fraction", "0.01", "0.0101", {}),
    ("risk.max_share_risk_fraction", "0.02", "0.0201", {}),
    ("risk.max_total_open_risk_fraction", "0.10", "0.1001", {}),
    ("risk.max_symbol_open_risk_fraction", "0.03", "0.0301", {}),
    ("risk.max_btc_bucket_open_risk_fraction", "0.05", "0.0501", {}),
    ("risk.btc_bucket_corr_threshold", "0.9", "0.9001", {}),
    ("risk.btc_bucket_corr_window_days", 90, 91, {}),
    ("risk.max_leader_open_risk_fraction", "0.03", "0.0301", {}),
    ("risk.max_open_positions", 10, 11, {}),
    ("risk.max_position_notional_equity_mult", "3.0", "3.0001", {}),
    ("risk.leverage_min", 3, 4, {}),
    ("risk.max_leverage_alt", 5, 6, {}),
    ("risk.max_leverage_high_tier", 10, 11, {}),
    ("risk.daily_loss_limit", "0.05", "0.0501", {}),
    ("risk.weekly_loss_limit", "0.10", "0.1001", {}),
    ("risk.max_orders_per_min", 60, 61, {}),
    ("exits.stop_atr_mult", "4.0", "4.0001", {}),
    ("exits.atr_period", 50, 51, {}),
    ("exits.tp1_r", "10", "10.0001", {}),
    ("exits.tp1_fraction", "1.0", "1.0001", {}),
    ("exits.trail_start_r", "5", "5.0001", {}),
    ("exits.trail_atr_mult", "5", "5.0001", {}),
    ("exits.retry_interval_s", 5, 6, {}),
    ("exits.alert_after_s", 60, 61, {}),
    ("reconcile.interval_s", 600, 601, {}),
    ("cost.taker_fee_bps", "20", "20.0001", {}),
    ("cost.maker_fee_bps", "20", "20.0001", {}),
    ("paper.ack_delay_ms", 5000, 5001, {}),
    ("paper.max_book_age_ms", 5000, 5001, {}),
    ("paper.meta_refresh_min", 1440, 1441, {}),
    ("restart.max_reconstruct_gap_h", 84, 85, {}),
    ("telegram.min_edit_interval_s", 60, 61, {}),
    ("telegram.max_msgs_per_min_per_chat", 20, 21, {}),
    ("telegram.queue_max_messages", 10000, 10001, {}),
    ("telegram.queue_max_age_h", 72, 73, {}),
    ("telegram.pin_max_attempts", 5, 6, {}),
    ("telegram.pin_lockout_min", 1440, 1441, {}),
    ("telegram.unauthorized_alert_interval_min", 60, 61, {}),
    ("llm.monthly_budget_usd", "20", "20.0001", {}),
    ("llm.timeout_s", 30, 31, {}),
    ("llm.max_output_chars", 1500, 1501, {}),
]

# (key, value at the Min that loads, value one step below that is rejected, companion overrides)
MIN_CASES: list[tuple[str, Any, Any, dict[str, Any]]] = [
    ("storage.upload_delay_min", 5, 4, {}),
    ("storage.upload_deadline_h", 1, 0, {}),
    ("storage.local_retention_days", 2, 1, {}),
    ("storage.max_unarchived_days", 1, 0, {}),
    ("storage.cache_max_gb", 2, 1, {}),
    ("storage.read_retry_max_min", 1, 0, {}),
    ("storage.retry_interval_min", 1, 0, {}),
    ("storage.alert_interval_h", 1, 0, {}),
    ("storage.monthly_budget_usd", "0", "-0.0001", {}),
    ("storage.budget_alert_fraction", "0.1", "0.0999", {}),
    ("storage.price_usd_per_gb_month", "0.0001", "0", {}),  # Min is "> 0" (exclusive)
    ("storage.price_usd_per_10k_ops", "0", "-0.0001", {}),
    ("clock.offset_interval_s", 60, 59, {}),
    ("clock.max_offset_uncertainty_ms", 10, 9, {}),
    ("clock.max_estimate_age_s", 600, 599, {}),
    ("ledger.heartbeat_interval_s", 1, 0, {}),
    ("supervisor.restart_delay_s", 5, 4, {}),
    ("supervisor.max_restarts_per_hour", 1, 0, {}),
    ("hl.rest_weight_budget_per_min", 100, 99, {}),
    ("hl.scoring_weight_share", "0.1", "0.0999", {}),
    ("hl.weight_userRole", 20, 19, {}),
    ("hl.weight_portfolio", 20, 19, {}),
    ("hl.rest_timeout_s", 2, 1, {}),
    ("hl.retry_max", 0, -1, {}),
    ("hl.backoff_base_s", 1, 0, {}),
    ("hl.backoff_max_s", 10, 9, {}),
    ("hl.ws_max_unique_users", 1, 0, {}),
    ("hl.ws_max_new_conns_per_min", 1, 0, {}),
    ("hl.ws_ping_interval_s", 5, 4, {}),
    ("hl.ws_reconnect_backoff_max_s", 5, 4, {}),
    ("feed.stale_after_s", 5, 4, {}),
    ("access.degraded_error_count", 1, 0, {}),
    ("access.degraded_window_min", 1, 0, {}),
    ("access.degraded_min_success_rate", "0.1", "0.0999", {}),
    ("access.recover_min", 1, 0, {}),
    ("follow.clearinghouse_poll_s", 10, 9, {}),
    ("follow.max_leader_av_age_s", 60, 59, {}),
    ("recording.max_coins", 10, 9, {}),
    ("recording.universe_lookback_days", 7, 6, {}),
    ("recording.l2_levels", 5, 4, {}),
    ("recording.l2_interval_ms", 500, 499, {}),
    ("recording.asset_ctx_interval_s", 10, 9, {}),
    ("recording.leaderboard_interval_min", 15, 14, {}),
    ("recording.disk_check_interval_s", 10, 9, {}),
    ("recording.disk_alert_free_gb", 6, 5, {"recording.disk_floor_free_gb": 5}),  # must also exceed the floor
    ("recording.disk_floor_free_gb", 5, 4, {}),
    ("recording.disk_resume_margin_gb", 1, 0, {}),
    ("recording.max_gb_per_day", "0.1", "0.0999", {}),
    ("scoring.candidates_k", 50, 49, {}),
    ("scoring.interval_min", 15, 14, {"select.max_cycle_duration_min": 14}),  # keep max_cycle <= interval
    ("scoring.window_days", 90, 89, {}),
    ("scoring.dsr_min_daily_days", 30, 29, {}),
    ("scoring.stale_input_mult", 1, 0, {}),
    ("gate.min_account_age_days", 90, 89, {}),
    ("gate.min_round_trips", 50, 49, {}),
    ("gate.min_fill_span_days", 30, 29, {}),
    ("gate.min_positive_blocks", 1, 0, {}),
    ("gate.n_blocks", 2, 1, {"gate.min_positive_blocks": 1}),
    ("gate.block_days", 7, 6, {}),
    ("gate.max_drawdown", "0.05", "0.0499", {}),
    ("gate.min_profit_factor", "1.0", "0.9999", {}),
    ("gate.min_dsr_prob", "0.50", "0.4999", {}),
    ("gate.dsr_n_trials", 200, 199, {}),  # Min = scoring.candidates_k (200)
    ("gate.min_median_hold_min", 5, 4, {}),
    ("gate.hold_latency_mult", 5, 4, {}),
    ("gate.max_top_trade_share", "0.05", "0.0499", {}),
    ("gate.max_top_asset_share", "0.10", "0.0999", {}),
    ("gate.min_copy_edge_ratio", "1.0", "0.9999", {}),
    ("gate.min_account_value_usd", "1000", "999", {}),
    ("gate.min_executable_share", "0.10", "0.0999", {}),
    ("gate.max_maker_share", "0.10", "0.0999", {}),
    ("gate.max_current_drawdown", "0.05", "0.0499", {}),
    ("blowup.max_adds_while_losing_share", "0", "-0.0001", {}),
    ("blowup.min_adds", 1, 0, {}),
    ("blowup.max_size_after_loss_ratio", "1.0", "0.9999", {}),
    ("blowup.min_each", 5, 4, {}),
    ("blowup.skew_win_rate", "0.5", "0.4999", {}),
    ("blowup.skew_loss_mult", "1", "0.9999", {}),
    ("blowup.max_worst_to_median_loss", "2", "1.9999", {}),
    ("blowup.min_losses", 3, 2, {}),
    ("blowup.hidden_dd_mult", "1", "0.9999", {}),
    ("blowup.hidden_dd_floor", "0", "-0.0001", {}),
    ("blowup.max_median_eff_leverage", 1, 0, {}),
    ("blowup.max_open_unrealized_loss", "0.01", "0.0099", {}),
    ("score.shrink_k_trades", 0, -1, {}),
    ("score.shrink_k_days_recent", 0, -1, {}),
    ("select.join_rank", 1, 0, {}),
    ("select.drop_rank", 9, 8, {}),  # Min = select.join_rank + 1 (9)
    ("select.join_confirm_cycles", 1, 0, {}),
    ("select.drop_confirm_cycles", 1, 0, {}),
    ("select.min_follow_hours", 1, 0, {}),
    ("select.min_followed", 1, 0, {}),
    ("select.max_followed", 1, 0, {"select.min_followed": 1}),
    ("select.backfill_max_hours", 1, 0, {}),
    ("select.swap_margin", "0", "-0.0001", {}),
    ("select.max_swaps_per_cycle", 0, -1, {}),
    ("select.max_cycle_duration_min", 10, 9, {}),
    ("leader_pause.max_copy_dd", "0.02", "0.0199", {}),
    ("leader_pause.max_consec_losses", 2, 1, {}),
    ("risk.leader_allocation_fraction", "0.05", "0.0499", {}),
    ("copyreplay.delay_ms", 250, 249, {}),
    ("copyreplay.half_spread_bps.major", "2", "1.9999", {}),
    ("copyreplay.half_spread_bps.alt", "8", "7.9999", {}),
    ("tiers.lookback_days", 3, 2, {}),
    ("tiers.recompute_interval_h", 1, 0, {}),
    ("tiers.max_age_h", 2, 1, {}),
    ("tiers.depth_band_pct", "0.1", "0.0999", {}),
    ("tiers.tier1_min_depth_usd", "50000", "49999", {}),  # Min = tiers.floor_min_depth_usd
    ("tiers.tier1_min_volume_usd", "10000000", "9999999", {}),  # Min = tiers.floor_min_volume_usd
    ("tiers.floor_min_depth_usd", "20000", "19999", {}),
    ("tiers.floor_min_volume_usd", "2000000", "1999999", {}),
    ("tiers.min_coverage_fraction", "0.5", "0.4999", {}),
    ("filter.max_signal_age_ms", 500, 499, {}),
    ("filter.max_slippage_pct_tier1", "0.05", "0.0499", {}),
    ("filter.max_slippage_pct_tier2", "0.10", "0.0999", {}),
    ("filter.max_spread_pct_tier1", "0.01", "0.0099", {}),
    ("filter.max_spread_pct_tier2", "0.02", "0.0199", {}),
    ("filter.max_depth_share", "0.001", "0.0009", {}),
    ("filter.depth_band_pct", "0.1", "0.0999", {}),
    ("filter.max_price_age_ms", 250, 249, {}),
    ("filter.vol_window_h", 4, 3, {}),
    ("filter.vol_lookback_days", 30, 29, {}),
    ("filter.vol_halving_percentile", 50, 49, {}),
    ("filter.vol_size_mult", "0.1", "0.0999", {}),
    ("filter.trend.ema_period_h", 10, 9, {}),
    ("filter.trend.min_aligned_atr", D("-5"), D("-5.0001"), {}),
    ("filter.funding.max_adverse_rate_per_h", D("0"), D("-0.0001"), {}),
    ("filter.oi_drop.max_drop_pct_24h", D("5"), D("4.9999"), {}),
    ("filter.premium.max_abs_pct", D("0.05"), D("0.0499"), {}),
    ("calendar.window_fomc_min.before", 0, -1, {}),
    ("calendar.window_fomc_min.after", 0, -1, {}),
    ("calendar.window_tier1_min.before", 0, -1, {}),
    ("calendar.window_tier1_min.after", 0, -1, {}),
    ("calendar.min_coverage_days", 67, 66, {}),
    ("risk.per_trade_fraction", "0.001", "0.0009", {}),
    ("risk.max_share_risk_fraction", "0.005", "0.0049", {}),
    ("risk.max_total_open_risk_fraction", "0.005", "0.0049", {}),
    ("risk.max_symbol_open_risk_fraction", "0.005", "0.0049", {}),
    ("risk.max_btc_bucket_open_risk_fraction", "0.005", "0.0049", {}),
    ("risk.btc_bucket_corr_threshold", "0.3", "0.2999", {}),
    ("risk.btc_bucket_corr_window_days", 7, 6, {}),
    ("risk.max_leader_open_risk_fraction", "0.005", "0.0049", {}),
    ("risk.max_open_positions", 1, 0, {}),
    ("risk.max_position_notional_equity_mult", "0.1", "0.0999", {}),
    ("risk.leverage_min", 1, 0, {}),
    ("risk.max_leverage_alt", 1, 0, {}),
    ("risk.max_leverage_high_tier", 1, 0, {}),
    ("risk.min_liq_distance_stop_mult", "3", "2.9999", {}),
    ("risk.daily_loss_limit", "0.005", "0.0049", {}),
    ("risk.weekly_loss_limit", "0.01", "0.0099", {}),
    ("risk.max_orders_per_min", 1, 0, {}),
    ("sizing.min_order_usd", "10", "9.9999", {}),
    ("live.min_wallet_usd", "300", "299.9999", {}),
    ("exits.stop_atr_mult", "1.0", "0.9999", {}),
    ("exits.atr_period", 5, 4, {}),
    ("exits.tp1_r", "0.5", "0.4999", {}),
    ("exits.tp1_fraction", "0.1", "0.0999", {}),
    ("exits.trail_start_r", "0.25", "0.2499", {}),
    ("exits.trail_atr_mult", "0.5", "0.4999", {}),
    ("exits.retry_interval_s", 1, 0, {}),
    ("exits.alert_after_s", 5, 4, {}),
    ("reconcile.interval_s", 60, 59, {}),
    ("cost.taker_fee_bps", "4.5", "4.4999", {}),
    ("cost.maker_fee_bps", "1.5", "1.4999", {}),
    ("paper.ack_delay_ms", 500, 499, {}),
    ("paper.max_book_age_ms", 1000, 999, {}),
    ("paper.meta_refresh_min", 5, 4, {}),
    ("cost.fallback_half_spread_bps.major", "2", "1.9999", {}),
    ("cost.fallback_half_spread_bps.alt", "8", "7.9999", {}),
    ("cost.fallback_half_spread_mult", "1.5", "1.4999", {}),
    ("cost.fallback_delay_slippage_bps.major", "5", "4.9999", {}),
    ("cost.fallback_delay_slippage_bps.alt", "15", "14.9999", {}),
    ("restart.max_reconstruct_gap_h", 1, 0, {}),
    ("telegram.min_edit_interval_s", 3, 2, {}),
    ("telegram.max_msgs_per_min_per_chat", 1, 0, {}),
    ("telegram.queue_max_messages", 10, 9, {}),
    ("telegram.queue_max_age_h", 1, 0, {}),
    ("telegram.pin_max_attempts", 1, 0, {}),
    ("telegram.pin_lockout_min", 5, 4, {}),
    ("telegram.unauthorized_alert_interval_min", 1, 0, {}),
    ("llm.monthly_budget_usd", "0", "-0.0001", {}),
    ("llm.timeout_s", 1, 0, {}),
    ("llm.max_output_chars", 100, 99, {}),
    ("llm.price_usd_per_1k_tokens.input", "0.0001", "0", {}),  # "> 0"
    ("llm.price_usd_per_1k_tokens.output", "0.0001", "0", {}),  # "> 0"
    ("latency.measure_hours", 24, 23, {}),
    ("latency.min_signals", 50, 49, {}),
]

# "fixed" keys (Min = Max = Default): the fixture value loads (every other test proves it); these are rejected.
FIXED_REJECTS: list[tuple[str, Any]] = [
    ("recording.segment_hash_minutes", 4),
    ("recording.segment_hash_minutes", 6),
    ("recording.candle_store", "hourly_1m"),
    ("markets.allowed_dexes", ["core", "xyz"]),
    ("markets.allowed_dexes", []),
    ("calendar.timezone", "UTC"),
    ("sizing.partial_below_min_action", "close_all"),
    ("sizing.close_all_if_remainder_below_min", False),
    ("paper.wallet_usd", D("301.0")),
    ("paper.wallet_usd", D("299.9999")),
    ("exits.missed_exit_max_lag_s", 61),
    ("exits.missed_exit_max_lag_s", 59),
    ("cost.funding_accrual", "none"),
    ("cost.fallback_tier_rule", "untiered_is_major"),
    ("restart.candle_interval", "5m"),
    ("report.weekly_block_days", 8),
    ("replay.max_variants", 9),
    ("eval.sample_basis", "closed"),
    ("eval.n_trades", 299),
    ("eval.n_trades", 301),
    ("eval.calendar_cap_days", 31),
    ("eval.extension_days", 31),
    ("eval.closeout_max_days", 8),
    ("eval.ci_level_run1", D("0.95")),
    ("eval.ci_level_run2", D("0.98")),
    ("eval.max_runs", 3),
    ("eval.ci_method", "iid_t"),
    ("eval.cluster_key", "trade_day"),
    ("eval.min_day_clusters", 4),
    ("eval.bootstrap_b", 9999),
    ("eval.bootstrap_seed", "00" * 32),  # a hand-set seed would defeat the CSPRNG draw at run start
    ("eval.bootstrap_statistic", "median"),
    ("eval.rng", "mt19937"),
    ("eval.percentile_index", "nearest_rank"),
    ("eval.gate_round_dp", 5),
    ("eval.flatten_gate_rule", "realised"),
    ("eval.require_clean_engine_tree", False),
    ("eval.engine_path_manifest", "other-manifest.txt"),
    ("eval.run_worktree_pinned", False),
    ("eval.run_record_env_hashes", ["packages"]),
    ("eval.deploy_policy", "continue"),
    ("eval.require_usd_pnl_positive", False),
    ("eval.baseline_gate", "none"),
    ("eval.max_dd", D("0.16")),
    ("eval.mark_interval_s", 61),
    ("eval.max_downtime_fraction", D("0.03")),
    ("eval.show_interim_stats", "full"),
    ("eval.missed_exit_max_count", 4),
    ("eval.missed_exit_max_cost_r", D("1.1")),
    ("eval.missed_exit_gate_rule", "actual_only"),
    ("eval.missed_exit_gap_rule", "tp_first"),
    ("eval.missed_exit_cost_rule", "trade_only"),
    ("eval.p4_breach_time", "latest"),
    ("eval.settled_gap_rule", "ignore"),
    ("eval.fill_audit_interval_h", 48),
    ("eval.missing_data_retry_max_h", 96),
    ("eval.recording_integrity", "unverified"),
    ("baseline.dm_exclude_downtime", False),
    ("baseline.dm_discretionary_pause_rule", "exclude_pause"),
    ("baseline.dm_costs", "with_decay"),
    ("baseline.dm_min_admissible_hours", 12),
    ("baseline.dm_max_missing_share", D("0.20")),
    ("baseline.dm_missing_rule", "drop"),
    ("baseline.dm_max_book_gap_s", 6),
    ("baseline.dm_max_mid_gap_s", 61),
    ("baseline.dm_reps", 999),
    ("baseline.random_reps", 999),
    ("baseline.top_roi_n", 10),
    ("fragility.top_k_trades", 4),
    ("fragility.drop_best_day_clusters", 2),
    ("fragility.cost_stress_mult", D("1.5")),
    ("data.paid_s3", True),
    ("d6.min_decision_agreement", D("0.80")),
    ("d6.max_median_abs_r_diff", D("0.06")),
    ("d6.max_mean_r_diff", D("0.20")),
    ("d6.max_median_fill_dev_bps", 4),
    ("d6.max_p90_fill_dev_bps", 11),
    ("d6.max_trade_count_dev", D("0.20")),
    ("kill.k1_min_trades", 99),
    ("kill.k2_min_trades", 149),
    ("kill.k6_decay_share", D("0.60")),
    ("kill.k7_min_eligible", 4),
    ("kill.k7_cycle_share", D("0.60")),
    ("kill.k8_unexecutable_share", D("0.60")),
]

# The spec's named cases (F1.AC2), verbatim.
REQUIRED_CEILING_REJECTS = [
    ("risk.per_trade_fraction", D("0.0101")),
    ("risk.max_leverage_alt", 6),
    ("risk.max_leverage_high_tier", 11),
    ("select.max_followed", 10),
    ("filter.max_signal_age_ms", 5001),
]
REQUIRED_FLOOR_REJECTS = [
    ("cost.taker_fee_bps", D("4.4")),
    ("risk.min_liq_distance_stop_mult", D("2.9")),
    ("recording.disk_floor_free_gb", 4),
    ("tiers.floor_min_depth_usd", D("19999")),
]

for _key, *_ in MAX_CASES + MIN_CASES:
    assert _key in LEAVES, f"bounds table names a key missing from the fixture: {_key}"
for _key, _ in FIXED_REJECTS:
    assert _key in LEAVES, f"fixed table names a key missing from the fixture: {_key}"


def _apply(tree: ConfigTree, key: str, value: Any, companions: dict[str, Any]) -> ConfigTree:
    for k, v in companions.items():
        tree.set(k, same_kind(LEAVES[k], v))
    return tree.set(key, same_kind(LEAVES[key], value))


def _assert_loads(config_dir: Path, key: str, value: Any) -> None:
    config = load_config(config_dir)
    assert config[key] == value


def _assert_rejected(config_dir: Path, key: str, *also: str) -> None:
    with pytest.raises(ConfigError) as info:
        load_config(config_dir)
    assert info.value.key in (key, *also), f"error names {info.value.key!r}, expected {key!r}"
    assert info.value.key in str(info.value)


def _case_id(case: tuple[str, Any, Any, dict[str, Any]]) -> str:
    return case[0]


@pytest.mark.parametrize("case", MAX_CASES, ids=_case_id)
def test_F1_AC2_value_equal_to_max_loads(tmp_path: Path, case: tuple[str, Any, Any, dict[str, Any]]) -> None:
    key, at, _, companions = case
    tree = _apply(ConfigTree(), key, at, companions)
    _assert_loads(tree.write(tmp_path / "config"), key, same_kind(LEAVES[key], at))


@pytest.mark.parametrize("case", MAX_CASES, ids=_case_id)
def test_F1_AC2_value_one_step_above_max_is_rejected(tmp_path: Path, case: tuple[str, Any, Any, dict[str, Any]]) -> None:
    key, _, above, companions = case
    tree = _apply(ConfigTree(), key, above, companions)
    _assert_rejected(tree.write(tmp_path / "config"), key, *companions)


@pytest.mark.parametrize("case", MIN_CASES, ids=_case_id)
def test_F1_AC2_value_equal_to_min_loads(tmp_path: Path, case: tuple[str, Any, Any, dict[str, Any]]) -> None:
    key, at, _, companions = case
    tree = _apply(ConfigTree(), key, at, companions)
    _assert_loads(tree.write(tmp_path / "config"), key, same_kind(LEAVES[key], at))


@pytest.mark.parametrize("case", MIN_CASES, ids=_case_id)
def test_F1_AC2_value_one_step_below_min_is_rejected(tmp_path: Path, case: tuple[str, Any, Any, dict[str, Any]]) -> None:
    key, _, below, companions = case
    tree = _apply(ConfigTree(), key, below, companions)
    _assert_rejected(tree.write(tmp_path / "config"), key, *companions)


@pytest.mark.parametrize(("key", "value"), REQUIRED_CEILING_REJECTS, ids=[k for k, _ in REQUIRED_CEILING_REJECTS])
def test_F1_AC2_required_ceiling_cases_are_rejected(tmp_path: Path, key: str, value: Any) -> None:
    _assert_rejected(ConfigTree().set(key, value).write(tmp_path / "config"), key)


@pytest.mark.parametrize(("key", "value"), REQUIRED_FLOOR_REJECTS, ids=[k for k, _ in REQUIRED_FLOOR_REJECTS])
def test_F1_AC2_required_floor_cases_are_rejected(tmp_path: Path, key: str, value: Any) -> None:
    tree = ConfigTree().set(key, same_kind(LEAVES[key], value))
    _assert_rejected(tree.write(tmp_path / "config"), key)


@pytest.mark.parametrize(("key", "value"), FIXED_REJECTS, ids=[f"{k}={v!r}" for k, v in FIXED_REJECTS])
def test_F1_AC2_fixed_key_rejects_any_other_value(tmp_path: Path, key: str, value: Any) -> None:
    _assert_rejected(ConfigTree().set(key, value).write(tmp_path / "config"), key)


# --- the compiled high-leverage coin set ------------------------------------------------------------

@pytest.mark.parametrize("coins", [[], ["BTC"], ["ETH"], ["SOL"], ["ETH", "SOL"], ["SOL", "BTC", "ETH"]], ids=repr)
def test_F1_AC2_high_leverage_coins_accepts_any_subset_of_btc_eth_sol(tmp_path: Path, coins: list[str]) -> None:
    config = load_config(ConfigTree().set("risk.high_leverage_coins", coins).write(tmp_path / "config"))
    assert sorted(config["risk.high_leverage_coins"]) == sorted(coins)


@pytest.mark.parametrize(
    "coins",
    [
        ["DOGE"],
        ["BTC", "DOGE"],
        ["BTC", "ETH", "SOL", "WIF"],
        ["btc"],  # coin names are case-sensitive on Hyperliquid
        ["ВТС"],  # Cyrillic look-alike of "BTC"
        ["BTC "],
        ["kPEPE"],
    ],
    ids=repr,
)
def test_F1_AC2_high_leverage_coins_with_any_other_coin_is_rejected(tmp_path: Path, coins: list[str]) -> None:
    _assert_rejected(ConfigTree().set("risk.high_leverage_coins", coins).write(tmp_path / "config"), "risk.high_leverage_coins")


def test_F1_AC2_high_leverage_coin_universe_is_a_compiled_constant() -> None:
    assert getattr(ceilings, "HIGH_LEVERAGE_COIN_UNIVERSE", None) == frozenset({"BTC", "ETH", "SOL"})


# --- ceilings are code constants that config cannot raise -------------------------------------------

@pytest.mark.parametrize(
    ("key", "side", "expected"),
    [
        ("risk.per_trade_fraction", "max", D("0.01")),
        ("risk.max_leverage_alt", "max", 5),
        ("risk.max_leverage_high_tier", "max", 10),
        ("select.max_followed", "max", 9),
        ("filter.max_signal_age_ms", "max", 5000),
        ("cost.taker_fee_bps", "min", D("4.5")),
        ("risk.min_liq_distance_stop_mult", "min", 3),
        ("recording.disk_floor_free_gb", "min", 5),
        ("tiers.floor_min_depth_usd", "min", 20000),
        ("tiers.floor_min_volume_usd", "min", 2000000),
        ("risk.daily_loss_limit", "max", D("0.05")),
        ("risk.max_open_positions", "max", 10),
        ("risk.max_orders_per_min", "max", 60),
        ("risk.max_position_notional_equity_mult", "max", 3),
    ],
)
def test_F1_AC2_ceiling_constants_match_the_spec(key: str, side: str, expected: Any) -> None:
    bounds = ceiling_for(key)
    assert getattr(bounds, side) == expected


def test_F1_AC2_price_floor_is_exclusive() -> None:
    bounds = ceiling_for("storage.price_usd_per_gb_month")
    assert bounds.min == 0 and bounds.min_exclusive is True


@pytest.mark.parametrize(
    "extra",
    [
        {"risk.per_trade_fraction_max": D("0.05")},
        {"ceilings.risk.per_trade_fraction": D("0.05")},
        {"risk.max.per_trade_fraction": D("0.05")},
    ],
    ids=["suffix", "ceilings-table", "nested"],
)
def test_F1_AC2_config_cannot_raise_a_ceiling(tmp_path: Path, extra: dict[str, Any]) -> None:
    tree = ConfigTree().set("risk.per_trade_fraction", D("0.02"))
    for k, v in extra.items():
        tree.set(k, v, file="attempted_override.toml")
    # Whether unknown keys are tolerated is not specified; either way the load must fail.
    _assert_rejected(tree.write(tmp_path / "config"), "risk.per_trade_fraction", *extra)


def test_F1_AC2_environment_cannot_raise_a_ceiling(tmp_path: Path, canary_secrets: dict[str, str]) -> None:
    fake = make_root(tmp_path, ConfigTree().set("risk.max_leverage_alt", 8))
    env = {**canary_secrets, "COPYTRADE_RISK_MAX_LEVERAGE_ALT_MAX": "10", "COPYTRADE_CEILINGS": "off"}
    with pytest.raises(ConfigError) as info:
        startup(fake.root, env, code_root=REPO_ROOT, engine_module_files=[])
    assert info.value.key == "risk.max_leverage_alt"


# --- cross-key bounds --------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("overrides", "keys", "ok"),
    [
        ({"select.max_followed": 5, "select.min_followed": 5}, (), True),
        ({"select.max_followed": 5, "select.min_followed": 6}, ("select.min_followed", "select.max_followed"), False),
        ({"select.join_rank": 8, "select.drop_rank": 8}, ("select.drop_rank", "select.join_rank"), False),
        ({"select.join_rank": 3, "select.drop_rank": 4}, (), True),
        ({"gate.n_blocks": 4, "gate.min_positive_blocks": 5}, ("gate.min_positive_blocks", "gate.n_blocks"), False),
        ({"scoring.candidates_k": 500, "gate.dsr_n_trials": 499}, ("gate.dsr_n_trials", "scoring.candidates_k"), False),
        ({"scoring.candidates_k": 500, "gate.dsr_n_trials": 500}, (), True),
        ({"scoring.interval_min": 30, "select.max_cycle_duration_min": 31}, ("select.max_cycle_duration_min", "scoring.interval_min"), False),
        ({"recording.disk_floor_free_gb": 10, "recording.disk_alert_free_gb": 10}, ("recording.disk_alert_free_gb", "recording.disk_floor_free_gb"), False),
        ({"recording.disk_floor_free_gb": 10, "recording.disk_alert_free_gb": 11}, (), True),
        ({"tiers.floor_min_depth_usd": "60000", "tiers.tier1_min_depth_usd": "59999"}, ("tiers.tier1_min_depth_usd", "tiers.floor_min_depth_usd"), False),
        ({"tiers.floor_min_volume_usd": "20000000", "tiers.tier1_min_volume_usd": "19999999"}, ("tiers.tier1_min_volume_usd", "tiers.floor_min_volume_usd"), False),
    ],
)
def test_F1_AC2_cross_key_bounds(tmp_path: Path, overrides: dict[str, Any], keys: tuple[str, ...], ok: bool) -> None:
    tree = ConfigTree()
    for k, v in overrides.items():
        tree.set(k, same_kind(LEAVES[k], v))
    config_dir = tree.write(tmp_path / "config")
    if ok:
        load_config(config_dir)
    else:
        _assert_rejected(config_dir, *keys)


# --- score weights and anchors -----------------------------------------------------------------------

WEIGHTS = ["dsr_excess", "copy_mean_r", "pos_blocks", "max_dd", "recent_sr", "executable"]


def _weights_tree(values: list[str]) -> ConfigTree:
    tree = ConfigTree()
    for name, v in zip(WEIGHTS, values, strict=True):
        tree.set(f"score.weights.{name}", D(v))
    return tree


def test_F1_AC2_score_weights_summing_to_one_load(tmp_path: Path) -> None:
    load_config(_weights_tree(["0.5", "0.5", "0", "0", "0", "0"]).write(tmp_path / "config"))


@pytest.mark.parametrize(
    "values",
    [
        ["0.31", "0.25", "0.15", "0.15", "0.10", "0.05"],  # sum 1.01
        ["0.29", "0.25", "0.15", "0.15", "0.10", "0.05"],  # sum 0.99
        ["1.05", "-0.05", "0", "0", "0", "0"],  # sum 1, but one weight > 1 and one < 0
    ],
    ids=["sum-above-1", "sum-below-1", "outside-0-1"],
)
def test_F1_AC2_score_weights_outside_rules_are_rejected(tmp_path: Path, values: list[str]) -> None:
    with pytest.raises(ConfigError) as info:
        load_config(_weights_tree(values).write(tmp_path / "config"))
    assert info.value.key is not None and info.value.key.startswith("score.weights")


def test_F1_AC2_score_anchor_with_equal_lo_and_hi_is_rejected(tmp_path: Path) -> None:
    tree = ConfigTree().set("score.anchors.dsr_excess.lo", D("0.15")).set("score.anchors.dsr_excess.hi", D("0.15"))
    with pytest.raises(ConfigError) as info:
        load_config(tree.write(tmp_path / "config"))
    assert info.value.key is not None and info.value.key.startswith("score.anchors.dsr_excess")
