"""Startup reload (the minimal slice of F13): rebuild state from the ledger and flag anything uncertain."""

from __future__ import annotations

from dataclasses import dataclass

# Uncertain-state codes (``Uncertainty.code``). Each one raises a Telegram alert of kind ``startup_uncertain`` and
# pauses new entries (``RiskGate.pause``, persisted) until the PO acknowledges with ``/resume``.
POSITION_WITHOUT_SHARE = "position_without_share"
SHARE_WITHOUT_POSITION = "share_without_position"
UNKNOWN_COIN = "unknown_coin"
EXIT_STATE_UNPROVEN = "exit_state_unproven"
MISSING_RISK_STATE_FILE = "missing_risk_state_file"
CHECKPOINT_BEHIND_LEDGER = "checkpoint_behind_ledger"
ALERT_STARTUP_UNCERTAIN = "startup_uncertain"
KIND_CHECKPOINT = "runner_checkpoint"
KIND_RUNNER_START = "runner_start"
KIND_RUNNER_STOP = "runner_stop"


@dataclass(frozen=True)
class Uncertainty:
    """One thing the reload could not prove. ``detail`` names the coin / share id / client order id, never a secret."""

    code: str
    detail: str


@dataclass(frozen=True)
class Requeued:
    """A pending exit re-queued under a NEW client order id (the old id stays in the ledger, so reusing it would be
    refused ``duplicate_client_order_id``)."""

    old_client_order_id: str
    new_client_order_id: str
    share_id: str
