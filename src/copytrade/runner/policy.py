"""The entry-policy stand-in (F9 is stage 2): allow every entry at volatility multiplier 1, but never against the
runner's own fail-closed refusals."""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

from copytrade.core.domain import ActionKind
from copytrade.hl.access import AccessMonitor
from copytrade.hl.ws import HlWsFeed
from copytrade.recorder.service import Recorder
from copytrade.selection.manager import FollowManager
from copytrade.signals.models import Signal

_log = logging.getLogger(__name__)


class RunnerEntryPolicy:
    """``positions.types.EntryPolicy``. ``vol_mult(signal)`` is ``None`` (veto) when ANY of these says no for an OPEN
    by ``signal.wallet``: the runner is stopping; ``FollowManager.refusal_reason``; ``HlWsFeed.refusal_reason`` (stale
    feed); ``Recorder.refusal_reason`` (recording stopped at the disk floor); ``AccessMonitor`` degraded. Otherwise
    ``Decimal(1)``. A refusal source that raises counts as a veto (A2)."""

    def __init__(
        self,
        *,
        follow: FollowManager,
        feed: HlWsFeed,
        recorder: Recorder,
        access: AccessMonitor,
        is_stopping: Callable[[], bool],
    ) -> None:
        self._follow = follow
        self._feed = feed
        self._recorder = recorder
        self._access = access
        self._is_stopping = is_stopping

    def vol_mult(self, signal: Signal) -> Decimal | None:
        try:
            refusals = (
                self._is_stopping(),
                self._follow.refusal_reason(signal.wallet, ActionKind.OPEN),
                self._feed.refusal_reason(signal.wallet, ActionKind.OPEN),
                self._recorder.refusal_reason(ActionKind.OPEN),
                self._access.refusal_reason(ActionKind.OPEN),
            )
        except Exception:
            _log.exception("the entry policy could not ask a refusal source; vetoing", extra={"event": "policy_failed"})
            return None
        return None if any(refusals) else Decimal(1)
