"""The risk gate (F10): the single chokepoint for every order (A1) and the only holder of the ``GateAuthority``.

Design in one paragraph: ``check`` decides, ``submit`` and ``place_stop`` decide and then send. A decision is built by
running an ordered list of checks over one snapshot of the world (equity, open shares, coin rules, persisted state,
exchange time); the first failed check refuses and names its reason, every check that ran is recorded, and exactly one
``risk_decision`` record is appended to the ledger per decision (B5). Only an approved decision reaches
``GateAuthority.issue`` (a fresh token bound to exactly that intent) and the broker. Entries fail closed on any doubt;
exits and stops are never refused for caps, limits, pauses, blackouts, margin or missing data (F10.AC7).

Not thread-safe except for the persisted state, which ``pause``/``resume``/``mark_equity`` update under a lock so the
kill switch can be pulled from another thread; call the rest from the supervisor's loop.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn, TypeGuard

from copytrade.core.config import Config
from copytrade.core.domain import ActionKind
from copytrade.core.errors import ClockUnsyncedError
from copytrade.core.events import Alert, AlertSink
from copytrade.core.money import MAX_SZ_DECIMALS, Price, Qty
from copytrade.ledger.errors import LedgerWriteError
from copytrade.ledger.records import RiskCheckResult
from copytrade.ledger.store import Ledger
from copytrade.paper.broker import PaperBroker
from copytrade.paper.gate import GateAuthority, intent_digest
from copytrade.paper.ports import MetaSource
from copytrade.paper.settings import MONEY_CONTEXT, PaperSettings
from copytrade.paper.types import BrokerEvent, CoinMeta, OrderIntent, PositionView, StopIntent
from copytrade.risk.caps import BTC_BUCKET_RISK, Cap, entry_caps
from copytrade.risk.correlation import pearson
from copytrade.risk.errors import RiskStateError
from copytrade.risk.ids import client_order_id
from copytrade.risk.leverage import LeveragePlan, leverage_ceiling, plan_leverage
from copytrade.risk.limits import DAILY_LOSS, DRAWDOWN, WEEKLY_LOSS, Halt, apply_mark
from copytrade.risk.ports import AccountView, EntryCalendar, ExchangeTime, ReturnsSource, ShareBook
from copytrade.risk.settings import RiskSettings
from copytrade.risk.sizing import (
    add_qty,
    lot_qty_down,
    mirror_notional_usd,
    risk_notional_usd,
    stop_distance_fraction,
)
from copytrade.risk.state import RiskState, load_state, save_state
from copytrade.risk.types import (
    AddRequest,
    Decision,
    ExitRequest,
    OpenRequest,
    Outcome,
    Request,
    ShareExposure,
    StopRequest,
)

_log = logging.getLogger(__name__)

STATE_FILENAME = "risk_state.json"
RATE_WINDOW_MS = 60_000  # "orders per minute": the unit of ``risk.max_orders_per_min``, not a tunable
MS_PER_SECOND = 1000
_ZERO = Decimal(0)
_BTC = "BTC"
_STOP_KINDS = ("sl", "tp")
_ENTRY_TYPES = (OpenRequest, AddRequest)
_HALT_ALERTS = {DAILY_LOSS: "daily_loss_halt", WEEKLY_LOSS: "weekly_loss_halt", DRAWDOWN: "drawdown_pause"}


class _Refusal(Exception):  # noqa: N818 - control flow inside one decision, it never leaves this module
    """Raised by ``_Draft.fail`` to stop a decision at its first failed check."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _Draft:
    """One decision under construction: the checks that ran and the figures reached so far."""

    checks: list[RiskCheckResult] = field(default_factory=list)
    client_order_id: str | None = None
    action: ActionKind | None = None
    equity_usd: Decimal | None = None
    mirror_notional_usd: Decimal | None = None
    risk_notional_usd: Decimal | None = None
    final_notional_usd: Decimal | None = None
    qty: Qty | None = None
    initial_risk_usd: Decimal | None = None
    leverage: int | None = None
    leverage_ceiling: int | None = None
    posted_margin_usd: Decimal | None = None
    liquidation_px: Price | None = None
    order: OrderIntent | None = None
    stop: StopIntent | None = None

    def ok(self, check: str, detail: str = "") -> None:
        self.checks.append(RiskCheckResult(check, True, detail))

    def fail(self, reason: str, detail: str = "") -> NoReturn:
        self.checks.append(RiskCheckResult(reason, False, detail))
        raise _Refusal(reason)

    def decision(self, reason: str | None) -> Decision:
        return Decision(
            approved=reason is None,
            reason=reason,
            action=self.action,
            client_order_id=self.client_order_id,
            mirror_notional_usd=self.mirror_notional_usd,
            risk_notional_usd=self.risk_notional_usd,
            final_notional_usd=self.final_notional_usd,
            qty=self.qty,
            initial_risk_usd=self.initial_risk_usd,
            leverage=self.leverage,
            leverage_ceiling=self.leverage_ceiling,
            posted_margin_usd=self.posted_margin_usd,
            liquidation_px=self.liquidation_px,
            checks=tuple(self.checks),
        )


@dataclass(frozen=True)
class _Verdict:
    """A finished decision and, when approved, the one intent it approved."""

    decision: Decision
    order: OrderIntent | None = None
    stop: StopIntent | None = None


@dataclass(frozen=True)
class _Entry:
    """What every check of one entry reads: the request's common fields and one snapshot of the world."""

    coin: str
    leader: str
    is_long: bool
    share_id: str
    decision_px: Price
    now_ms: int
    equity_usd: Decimal
    shares: tuple[ShareExposure, ...]
    meta: CoinMeta
    position: PositionView | None
    ceiling: int

    @property
    def side(self) -> str:
        return "long" if self.is_long else "short"


class RiskGate:
    """Sizes entries from our risk budget, enforces every hard limit and sends approved orders to the broker.

    State that must survive a restart (pause flag, daily and weekly opening equity and halts, peak equity and the
    drawdown pause) lives in ``state_dir / STATE_FILENAME``; an unreadable state file refuses entries.

    Refusal reasons (``Decision.reason``): ``paused``, ``drawdown_pause``, ``daily_loss_halt``, ``weekly_loss_halt``,
    ``calendar_blackout``, ``clock_unsynced``, ``equity_unknown``, ``risk_state_unknown``, ``ledger_failed``,
    ``meta_unavailable``, ``unknown_coin``, ``check_error``, ``no_leader_av``, ``opposite_side_entry``,
    ``max_open_positions``, ``rate_limit``, ``unexecutable``, ``insufficient_margin``, ``liq_too_close``,
    ``stop_widening``, ``add_below_min``, and for exits ``exceeds_share``. Also: ``add_leverage_unsafe`` (an entry on a
    coin that already holds a position is gated at that position's leverage and the rule, the margin or the ceiling
    fails there), ``duplicate_order`` (this client order ID was already sent), ``invalid_request`` / ``invalid_stop`` /
    ``invalid_qty`` (malformed input), ``unknown_share`` / ``position_unknown`` (an add whose share or position is
    not there) and ``broker_failed`` (the broker could not advance for an entry).
    """

    def __init__(  # noqa: PLR0913 - the boundaries are injected
        self,
        *,
        config: Config,
        broker: PaperBroker,
        meta: MetaSource,
        account: AccountView,
        shares: ShareBook,
        returns: ReturnsSource,
        exchange_time: ExchangeTime,
        calendar: EntryCalendar,
        ledger: Ledger,
        alerts: AlertSink,
        authority: GateAuthority,
        state_dir: Path,
    ) -> None:
        self._settings = RiskSettings.from_config(config)
        self._meta_ttl_ms = PaperSettings.from_config(config).meta_refresh_ms
        self._broker = broker
        self._meta_source = meta
        self._account = account
        self._shares = shares
        self._returns = returns
        self._exchange_time = exchange_time
        self._calendar = calendar
        self._ledger = ledger
        self._alerts = alerts
        self._authority = authority
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._state_path = state_dir / STATE_FILENAME
        self._state_lock = threading.Lock()
        self._state_unreadable = False
        self._persist_failed = False
        self._state = self._initial_state()
        self._last_exchange_ms = 0
        self._sent_ms: deque[int] = deque()
        self._meta: Mapping[str, CoinMeta] | None = None
        self._meta_fetched_ms = 0

    # ------------------------------------------------------------------------------------------ decisions

    def check(self, request: Request) -> Decision:
        """Decide without sending. Writes one ``risk_decision`` ledger record (B5). Never raises for an entry: any
        exception inside a check is a ``check_error`` refusal. Exits are never refused for caps, limits, pauses,
        calendar, equity or state problems."""
        return self._decide(request, now_ms=self._read_exchange_ms()).decision

    def submit(self, request: Request) -> Outcome:
        """``broker.advance_to(exchange_now)``, stamp ``decided_at_ms`` with that exchange time, ``check``, and when
        approved issue a FRESH token for exactly the intent and call the broker. A refused request reaches neither
        ``GateAuthority.issue`` nor the broker.

        An entry is refused ``broker_failed`` when the broker cannot advance. Every other exception from the broker
        or the ledger (a latched broker, a failed ledger write) is a system failure and propagates, for an exit as
        well, so the supervisor sees it. An exit with no synced clock is stamped with the last exchange time seen."""
        if isinstance(request, StopRequest):
            return self.place_stop(request)
        now_ms = self._read_exchange_ms()
        events: tuple[BrokerEvent, ...] = ()
        if now_ms is not None:
            try:
                events = tuple(self._broker.advance_to(now_ms))
            except Exception:
                if not isinstance(request, _ENTRY_TYPES):
                    raise
                _log.exception("the broker could not advance", extra={"event": "risk_broker_failed"})
                refused = self._refusal(request, "broker_failed", "the broker could not advance to exchange time")
                return Outcome(self._record(request, refused, now_ms).decision, None)
        verdict = self._decide(request, now_ms=now_ms)
        if verdict.order is None:
            return Outcome(verdict.decision, None, events)
        self._note_order_sent(verdict.order.decided_at_ms)
        token = self._authority.issue(verdict.order)
        return Outcome(verdict.decision, self._broker.submit(verdict.order, token), events)

    def place_stop(self, request: StopRequest) -> Outcome:
        """Approve a stop (exit-like, never refused for pauses or limits) and register it with the broker."""
        verdict = self._decide(request, now_ms=self._read_exchange_ms())
        if verdict.stop is None:
            return Outcome(verdict.decision, None)
        token = self._authority.issue(verdict.stop)
        return Outcome(verdict.decision, self._broker.place_stop(verdict.stop, token))

    def flatten(self, *, run_id: str) -> Sequence[Outcome]:
        """Close every open share in the share book through the gate (full ``CLOSE``, reason ``flatten``, at the
        share's mark), whatever the pause, halt or equity state. Re-running it sends no second order for a share.
        Nothing is caught: when the share book itself cannot be read there is nothing to flatten from, and a broker or
        ledger failure is a system failure the caller must see.

        The client order ID of a flatten close is fixed by ``run_id``, the share and the action, so a second call in
        the same run finds it already sent and refuses it ``duplicate_order``; a fresh ``run_id`` flattens again."""
        return tuple(
            self.submit(
                ExitRequest(
                    run_id=run_id,
                    signal_id=f"flatten:{share.share_id}",
                    leader=share.leader,
                    coin=share.coin,
                    is_long=share.is_long,
                    tids=(),
                    trade_id=share.trade_id,
                    share_id=share.share_id,
                    qty=share.qty,
                    close=True,
                    decision_px=share.mark_px,
                    reason="flatten",
                )
            )
            for share in self._shares.open_shares()
        )

    def _decide(self, request: Request, *, now_ms: int | None) -> _Verdict:
        """Run the checks for ``request`` and record the decision."""
        draft = _Draft()
        try:
            if isinstance(request, _ENTRY_TYPES):
                self._decide_entry(request, draft, now_ms)
            elif isinstance(request, ExitRequest):
                self._decide_exit(request, draft, now_ms if now_ms is not None else self._last_exchange_ms)
            else:
                self._decide_stop(request, draft)
        except _Refusal as refusal:
            verdict = _Verdict(draft.decision(refusal.reason))
        except Exception as exc:  # A2: an exception inside a check refuses an entry and leaves an exit unsendable
            _log.exception("a risk check raised", extra={"event": "risk_check_error", "error_type": type(exc).__name__})
            draft.checks.append(RiskCheckResult("check_error", False, f"{type(exc).__name__} inside a check"))
            verdict = _Verdict(draft.decision("check_error"))
        else:
            verdict = _Verdict(draft.decision(None), draft.order, draft.stop)
        return self._record(request, verdict, now_ms, draft.equity_usd)

    def _record(
        self, request: Request, verdict: _Verdict, now_ms: int | None, equity_usd: Decimal | None = None
    ) -> _Verdict:
        """Append the ``risk_decision`` record and log a refusal. An approved entry whose record cannot be written
        is refused instead (no audit, no order); an exit or stop is sent regardless (it is never blocked)."""
        decision = verdict.decision
        try:
            self._ledger.append("risk_decision", self._audit_payload(request, decision, now_ms, equity_usd))
        except Exception as exc:
            _log.exception("the risk decision could not be recorded", extra={"event": "risk_audit_failed"})
            if decision.approved and isinstance(request, _ENTRY_TYPES):
                reason = "ledger_failed" if isinstance(exc, LedgerWriteError) else "check_error"
                failed = RiskCheckResult(reason, False, "the decision could not be recorded")
                decision = replace(decision, approved=False, reason=reason, checks=(*decision.checks, failed))
                verdict = _Verdict(decision)
        if not decision.approved:
            _log.info(
                "risk refusal: %s",
                decision.reason,
                extra={"event": "risk_refusal", "reason": decision.reason, "signal_id": request.signal_id},
            )
        return verdict

    @staticmethod
    def _refusal(request: Request, reason: str, detail: str) -> _Verdict:
        """A refusal made outside the check pipeline (the caller records it)."""
        draft = _Draft()
        draft.checks.append(RiskCheckResult(reason, False, detail))
        if isinstance(request, _ENTRY_TYPES):
            draft.action = ActionKind.ADD if isinstance(request, AddRequest) else ActionKind.OPEN
        return _Verdict(draft.decision(reason))

    # --------------------------------------------------------------------------------------- entries

    def _decide_entry(self, request: OpenRequest | AddRequest, draft: _Draft, now_ms: int | None) -> None:
        is_add = isinstance(request, AddRequest)
        action = ActionKind.ADD if is_add else ActionKind.OPEN
        cid = client_order_id(
            run_id=request.run_id,
            leader=request.leader,
            coin=request.coin,
            tids=request.tids,
            action=action.value,
            share_id=request.share_id,
        )
        draft.action, draft.client_order_id = action, cid
        now = self._entry_gates(draft, now_ms)
        if self._ledger.has_client_order_id(cid):
            draft.fail("duplicate_order", "this client order ID was already sent")
        draft.ok("idempotency", "the client order ID is new")
        _validate_entry(request, draft)
        entry = self._snapshot(request, now, draft)
        draft.leverage_ceiling = entry.ceiling
        self._check_direction(entry, draft)
        self._check_position_count(entry, draft)
        self._check_order_rate(entry, draft)
        stop_fraction = stop_distance_fraction(decision_px=entry.decision_px, stop_px=request.stop_px)
        if isinstance(request, AddRequest):
            desired_usd, share_used_usd = self._size_add(request, entry, draft)
            # the added share's stop after the add is the current one; the other shares keep theirs
            liquidation_stops = [
                s.stop_px for s in entry.shares if s.coin == entry.coin and s.share_id != entry.share_id
            ]
            liquidation_stops.append(request.current_stop_px)
        else:
            desired_usd, share_used_usd = self._size_open(request, entry, stop_fraction, draft), _ZERO
            liquidation_stops = [s.stop_px for s in entry.shares if s.coin == entry.coin]
            liquidation_stops.append(request.stop_px)
        qty = self._apply_caps(entry, desired_usd, request.stop_px, share_used_usd, is_add=is_add, draft=draft)
        leverage = self._plan_leverage(entry, qty, liquidation_stops, draft)
        order = OrderIntent(
            client_order_id=cid,
            coin=entry.coin,
            side="buy" if entry.is_long else "sell",
            qty=qty,
            action=action,
            decided_at_ms=now,
            decision_px=entry.decision_px,
            trade_id=request.trade_id,
            share_id=request.share_id,
            leverage=leverage,
            exit_reason=None,
        )
        intent_digest(order)  # a dry run: an intent that cannot be bound to a token is refused here, not at issue
        draft.order = order

    def _entry_gates(self, draft: _Draft, now_ms: int | None) -> int:
        """The state-wide gates every entry passes first. Returns exchange time (an entry needs a synced clock)."""
        if self._ledger.failed:
            draft.fail("ledger_failed", "the ledger failed to append earlier")
        draft.ok("ledger", "the ledger is healthy")
        if self._state_unreadable or self._persist_failed:
            draft.fail("risk_state_unknown", "the persisted risk state is unreadable or could not be saved")
        state = self._state
        if state.manual_pause:
            draft.fail("paused", "the kill switch is on")
        if state.drawdown_pause:
            draft.fail("drawdown_pause", "paused by the drawdown limit until /resume")
        draft.ok("pause", "not paused")
        if now_ms is None:
            draft.fail("clock_unsynced", "no synced exchange time")
        draft.ok("clock", "exchange time is synced")
        blackout = self._calendar.blocks_entries(now_ms)
        if blackout is not None:
            draft.fail("calendar_blackout", blackout)
        draft.ok("calendar", "no blackout")
        if state.daily_halt_active(now_ms):
            draft.fail("daily_loss_halt", f"halted until {state.daily_halt_until_ms} ms")
        if state.weekly_halt_active(now_ms):
            draft.fail("weekly_loss_halt", f"halted until {state.weekly_halt_until_ms} ms")
        draft.ok("loss_halts", "no daily or weekly halt")
        return now_ms

    def _snapshot(self, request: OpenRequest | AddRequest, now_ms: int, draft: _Draft) -> _Entry:
        """Equity, open shares, the coin's rules and the broker's position, read once for the whole decision."""
        equity = self._account.equity_usd()
        if not isinstance(equity, Decimal) or not equity.is_finite() or equity <= 0:
            draft.fail("equity_unknown", "equity is unknown or not positive")
        draft.equity_usd = equity
        draft.ok("equity", f"equity {equity}")
        shares = tuple(self._shares.open_shares())
        meta = self._coin_meta(request.coin, now_ms, draft)
        return _Entry(
            coin=request.coin,
            leader=request.leader,
            is_long=request.is_long,
            share_id=request.share_id,
            decision_px=request.decision_px,
            now_ms=now_ms,
            equity_usd=equity,
            shares=shares,
            meta=meta,
            position=self._broker.position(request.coin),
            ceiling=leverage_ceiling(
                coin=request.coin,
                high_leverage_coins=self._settings.high_leverage_coins,
                max_leverage_high_tier=self._settings.max_leverage_high_tier,
                max_leverage_alt=self._settings.max_leverage_alt,
                exchange_max_leverage=meta.max_leverage,
            ),
        )

    def _coin_meta(self, coin: str, now_ms: int, draft: _Draft) -> CoinMeta:
        """The coin's exchange rules from a snapshot at most ``paper.meta_refresh_min`` old. A failed refresh leaves no
        snapshot (B1: no stale rules for an entry) and is retried on the next decision."""
        if self._meta is None or not 0 <= now_ms - self._meta_fetched_ms < self._meta_ttl_ms:
            self._meta = None
            try:
                self._meta = dict(self._meta_source.fetch())
                self._meta_fetched_ms = now_ms
            except Exception:
                _log.warning("meta refresh failed", extra={"event": "risk_meta_failed"}, exc_info=True)
        if self._meta is None:
            draft.fail("meta_unavailable", "the exchange rules could not be fetched")
        rules = self._meta.get(coin)
        if not _usable(rules):
            draft.fail("unknown_coin", f"no usable exchange rules for {coin}")
        draft.ok("meta", f"{coin}: {rules.sz_decimals} size decimals, max leverage {rules.max_leverage}")
        return rules

    @staticmethod
    def _check_direction(entry: _Entry, draft: _Draft) -> None:
        """Never send an opposite-side entry (F11 contract): a flip is a CLOSE, then an OPEN after the fill."""
        held_opposite = entry.position is not None and (entry.position.qty > 0) != entry.is_long
        booked_opposite = any(s.is_long != entry.is_long for s in entry.shares if s.coin == entry.coin)
        if held_opposite or booked_opposite:
            draft.fail("opposite_side_entry", f"{entry.coin} already holds the other direction")
        draft.ok("direction", f"{entry.side} on {entry.coin}")

    def _check_position_count(self, entry: _Entry, draft: _Draft) -> None:
        coins = {s.coin for s in entry.shares}
        limit = self._settings.max_open_positions
        if entry.coin not in coins and len(coins) >= limit:
            draft.fail("max_open_positions", f"{len(coins)} merged positions are open, limit {limit}")
        draft.ok("max_open_positions", f"{len(coins)} open, limit {limit}")

    def _check_order_rate(self, entry: _Entry, draft: _Draft) -> None:
        """Orders sent in (now - 60 s, now], exits included: an order is an order to the exchange."""
        recent = sum(1 for sent in self._sent_ms if sent > entry.now_ms - RATE_WINDOW_MS)
        limit = self._settings.max_orders_per_min
        if recent >= limit:
            draft.fail("rate_limit", f"{recent} orders in the last minute, limit {limit}")
        draft.ok("rate_limit", f"{recent} orders in the last minute, limit {limit}")

    def _size_open(self, request: OpenRequest, entry: _Entry, stop_fraction: Decimal, draft: _Draft) -> Decimal:
        """``min(mirror, risk)`` for a new share (F10.AC2, C2). The leader's account value must be known and fresh."""
        value, stamped = request.leader_account_value_usd, request.leader_av_time_ms
        if value is None or stamped is None or not value.is_finite() or value <= 0:
            draft.fail("no_leader_av", "the leader's account value is missing or not positive")
        age_ms = entry.now_ms - stamped
        limit_ms = self._settings.max_leader_av_age_s * MS_PER_SECOND
        if abs(age_ms) > limit_ms:
            draft.fail("no_leader_av", f"the leader's account value is {age_ms} ms old, limit {limit_ms} ms")
        draft.ok("leader_av", f"{age_ms} ms old, limit {limit_ms} ms")
        mirror = mirror_notional_usd(
            leader_position_notional_usd=request.leader_position_notional_usd,
            leader_account_value_usd=value,
            equity_usd=entry.equity_usd,
        )
        risk = risk_notional_usd(
            equity_usd=entry.equity_usd,
            per_trade_fraction=self._settings.per_trade_fraction,
            vol_mult=request.vol_mult,
            stop_distance_fraction=stop_fraction,
        )
        draft.mirror_notional_usd, draft.risk_notional_usd = mirror, risk
        draft.ok("sizing", f"mirror {mirror}, risk {risk}")
        return min(mirror, risk)

    @staticmethod
    def _size_add(request: AddRequest, entry: _Entry, draft: _Draft) -> tuple[Decimal, Decimal]:
        """The add's notional (our share x the leader's add fraction, F10.AC9) and the open risk the share already
        carries. An add whose stop would widen the share's stop is skipped."""
        widening = (
            request.stop_px < request.current_stop_px if request.is_long else request.stop_px > request.current_stop_px
        )
        if widening:
            draft.fail("stop_widening", f"the add's stop {request.stop_px} is beyond the current stop")
        draft.ok("stop_widening", "the add's stop does not widen the share's stop")
        share = next((s for s in entry.shares if s.share_id == request.share_id and s.coin == request.coin), None)
        if share is None:
            draft.fail("unknown_share", "the share being added to is not in the share book")
        if entry.position is None:
            draft.fail("position_unknown", "the broker holds no position on the coin")
        qty = add_qty(
            our_share_qty=request.our_share_qty,
            leader_add_size=request.leader_add_size,
            leader_pre_add_position=request.leader_pre_add_position,
        )
        draft.ok("sizing", f"add quantity {qty}")
        return MONEY_CONTEXT.multiply(qty, request.decision_px), share.open_risk_usd

    def _apply_caps(  # noqa: PLR0913
        self,
        entry: _Entry,
        desired_usd: Decimal,
        stop_px: Price,
        share_used_usd: Decimal,
        *,
        is_add: bool,
        draft: _Draft,
    ) -> Qty:
        """Reduce to the largest size every cap allows, round down to the lot and re-apply the minimum order. The
        order's initial risk is its quantity times the distance to its stop (exact, not via the rounded fraction)."""
        stop_fraction = stop_distance_fraction(decision_px=entry.decision_px, stop_px=stop_px)
        caps = entry_caps(
            settings=self._settings,
            equity_usd=entry.equity_usd,
            shares=entry.shares,
            coin=entry.coin,
            leader=entry.leader,
            share_used_usd=share_used_usd,
            existing_qty=Qty(abs(entry.position.qty)) if entry.position is not None else Qty(0),
            decision_px=entry.decision_px,
            bucket_used_usd=self._bucket_used_usd(entry, draft),
        )
        allowed_usd = desired_usd
        for cap in caps:
            limit_usd = cap.max_notional_usd(stop_fraction)
            allowed_usd = min(allowed_usd, limit_usd)
            draft.checks.append(_cap_check(cap, limit_usd))
        qty = lot_qty_down(notional_usd=allowed_usd, px=entry.decision_px, sz_decimals=entry.meta.sz_decimals)
        final_usd = MONEY_CONTEXT.multiply(qty, entry.decision_px)
        draft.qty, draft.final_notional_usd = qty, final_usd
        draft.initial_risk_usd = MONEY_CONTEXT.multiply(qty, abs(MONEY_CONTEXT.subtract(entry.decision_px, stop_px)))
        minimum = self._settings.min_order_usd
        if final_usd < minimum:
            draft.fail("add_below_min" if is_add else "unexecutable", f"final notional {final_usd} is below {minimum}")
        draft.ok("min_order", f"final notional {final_usd}, minimum {minimum}")
        return qty

    def _bucket_used_usd(self, entry: _Entry, draft: _Draft) -> Decimal | None:
        """Same-direction open risk of the BTC bucket, or ``None`` when the coin is not in the bucket. A coin whose
        correlation is unknown (no candles, too few, a constant series) counts as in the bucket, never out of it."""
        days = self._settings.btc_bucket_corr_window_days
        members: dict[str, bool] = {_BTC: True}
        btc_returns: list[Sequence[Decimal] | None] = []

        def in_bucket(coin: str) -> bool:
            if coin not in members:
                if not btc_returns:
                    btc_returns.append(self._returns.hourly_returns(_BTC, days))
                members[coin] = self._correlated(btc_returns[0], self._returns.hourly_returns(coin, days))
            return members[coin]

        if not in_bucket(entry.coin):
            draft.ok(BTC_BUCKET_RISK, f"{entry.coin} is not in the BTC bucket")
            return None
        used = _ZERO
        for share in entry.shares:
            if share.is_long == entry.is_long and in_bucket(share.coin):
                used = MONEY_CONTEXT.add(used, share.open_risk_usd)
        return used

    def _correlated(self, btc: Sequence[Decimal] | None, series: Sequence[Decimal] | None) -> bool:
        if btc is None or series is None:
            return True
        try:
            correlation = pearson(btc, series)
        except ValueError:
            return True
        return correlation is None or correlation >= self._settings.btc_bucket_corr_threshold

    def _plan_leverage(self, entry: _Entry, qty: Qty, liquidation_stops: Sequence[Price], draft: _Draft) -> int:
        """Choose leverage and apply the margin and liquidation rules (F10.AC4, AC10). An entry on a coin that already
        holds a position is gated at that position's leverage (F11 keeps the first entry's), never a fresh one; only
        an OPEN on a coin with no position takes the lowest leverage that fits."""
        position = entry.position
        free_usd = MONEY_CONTEXT.subtract(entry.equity_usd, self._total_margin(entry))
        plan = plan_leverage(
            side=entry.side,
            coin_ceiling=entry.ceiling if position is None else min(entry.ceiling, position.leverage),
            leverage_min=self._settings.leverage_min if position is None else position.leverage,
            exchange_max_leverage=entry.meta.max_leverage,
            sz_decimals=entry.meta.sz_decimals,
            decision_px=entry.decision_px,
            order_qty=qty,
            existing_qty=Qty(0) if position is None else Qty(abs(position.qty)),
            existing_avg_entry_px=None if position is None else position.avg_entry_px,
            posted_margin_usd=_ZERO if position is None else position.margin_usd,
            free_equity_usd=free_usd,
            share_stop_pxs=tuple(liquidation_stops),
            min_liq_distance_stop_mult=self._settings.min_liq_distance_stop_mult,
        )
        draft.posted_margin_usd = plan.posted_margin_usd
        draft.leverage = plan.leverage if position is None else position.leverage
        draft.liquidation_px = plan.liquidation_px
        if not plan.accepted or plan.leverage is None:
            reason = "add_leverage_unsafe" if position is not None else (plan.reason or "insufficient_margin")
            draft.fail(reason, _plan_detail(plan, entry.ceiling))
        draft.ok("leverage", _plan_detail(plan, entry.ceiling))
        return plan.leverage

    def _total_margin(self, entry: _Entry) -> Decimal:
        """Posted isolated margin over every position the book knows and the coin being entered."""
        total = _ZERO
        for coin in sorted({s.coin for s in entry.shares} | {entry.coin}):
            position = entry.position if coin == entry.coin else self._broker.position(coin)
            if position is not None:
                total = MONEY_CONTEXT.add(total, position.margin_usd)
        return total

    # ---------------------------------------------------------------------------------- exits and stops

    def _decide_exit(self, request: ExitRequest, draft: _Draft, decided_at_ms: int) -> None:
        """An exit is only checked for being well formed, reduce-only, at most the share and new (F10.AC7)."""
        action = ActionKind.CLOSE if request.close else ActionKind.REDUCE
        cid = client_order_id(
            run_id=request.run_id,
            leader=request.leader,
            coin=request.coin,
            tids=request.tids,
            action=action.value,
            share_id=request.share_id,
        )
        draft.action, draft.client_order_id = action, cid
        if not request.qty.is_finite() or request.qty <= 0 or not request.reason.strip():
            draft.fail("invalid_qty", "an exit needs a positive quantity and a reason")
        self._check_share_quantity(request, draft)
        if self._ledger.has_client_order_id(cid):
            draft.fail("duplicate_order", "this client order ID was already sent")
        draft.ok("idempotency", "the client order ID is new")
        draft.qty = request.qty
        order = OrderIntent(
            client_order_id=cid,
            coin=request.coin,
            side="sell" if request.is_long else "buy",
            qty=request.qty,
            action=action,
            decided_at_ms=decided_at_ms,
            decision_px=request.decision_px,
            trade_id=request.trade_id,
            share_id=request.share_id,
            leverage=None,
            exit_reason=request.reason,
        )
        intent_digest(order)
        draft.order = order

    def _check_share_quantity(self, request: ExitRequest, draft: _Draft) -> None:
        """Reduce-only: at most the share's quantity. The share book is a convenience here: when it is down or does
        not list the share, the broker enforces the same limit (``exceeds_position``) and the exit goes on."""
        try:
            books = tuple(self._shares.open_shares())
        except Exception:
            _log.warning("share book unavailable for an exit", extra={"event": "risk_exit_book_down"}, exc_info=True)
            draft.ok("reduce_only", "the share book is unavailable; the broker enforces the share quantity")
            return
        share = next((s for s in books if s.share_id == request.share_id and s.coin == request.coin), None)
        if share is None:
            draft.ok("reduce_only", "the share is not in the book; the broker enforces the share quantity")
            return
        if request.qty > share.qty:
            draft.fail("exceeds_share", f"{request.qty} is more than the share's {share.qty}")
        draft.ok("reduce_only", f"{request.qty} of the share's {share.qty}")

    def _decide_stop(self, request: StopRequest, draft: _Draft) -> None:
        """A stop is exit-like: only its shape and idempotency are checked. The ID carries the signal, so a replaced
        (trailed) stop on the same share is a new order while a replay of the same signal is a duplicate."""
        cid = client_order_id(
            run_id=request.run_id,
            leader=request.leader,
            coin=request.coin,
            tids=(),
            action=f"{request.kind}:{request.signal_id}",
            share_id=request.share_id,
        )
        draft.client_order_id = cid
        if (
            request.kind not in _STOP_KINDS
            or not request.qty.is_finite()
            or request.qty <= 0
            or request.trigger_px <= 0
        ):
            draft.fail("invalid_stop", "a stop needs kind sl or tp, a positive quantity and a positive trigger")
        if self._ledger.has_client_order_id(cid):
            draft.fail("duplicate_order", "this client order ID was already sent")
        draft.ok("idempotency", "the client order ID is new")
        draft.qty = request.qty
        stop = StopIntent(
            client_order_id=cid,
            coin=request.coin,
            kind=request.kind,
            side="sell" if request.is_long else "buy",
            qty=request.qty,
            trigger_px=request.trigger_px,
            trade_id=request.trade_id,
            share_id=request.share_id,
        )
        intent_digest(stop)
        draft.stop = stop

    # ------------------------------------------------------------------------------ audit, time, rate

    @staticmethod
    def _audit_payload(
        request: Request, decision: Decision, now_ms: int | None, equity_usd: Decimal | None
    ) -> dict[str, Any]:
        return {
            "signal_id": request.signal_id,
            "run_id": request.run_id,
            "leader": request.leader,
            "coin": request.coin,
            "share_id": request.share_id,
            "action": None if decision.action is None else decision.action.value,
            "approved": decision.approved,
            "reason": decision.reason,
            "client_order_id": decision.client_order_id,
            "exchange_now_ms": now_ms,
            "equity_usd": equity_usd,
            "price_used": request.trigger_px if isinstance(request, StopRequest) else request.decision_px,
            "mirror_notional_usd": decision.mirror_notional_usd,
            "risk_notional_usd": decision.risk_notional_usd,
            "final_notional_usd": decision.final_notional_usd,
            "qty": decision.qty,
            "initial_risk_usd": decision.initial_risk_usd,
            "leverage": decision.leverage,
            "leverage_ceiling": decision.leverage_ceiling,
            "posted_margin_usd": decision.posted_margin_usd,
            "liquidation_px": decision.liquidation_px,
            "checks": [{"check": c.check, "passed": c.passed, "detail": c.detail} for c in decision.checks],
        }

    def _read_exchange_ms(self) -> int | None:
        """Exchange time in ms, or ``None`` while the clock is unsynced (entries are then refused, exits go on)."""
        try:
            now_ms = self._exchange_time.exchange_now().ms
        except ClockUnsyncedError:
            return None
        except Exception:
            _log.warning("exchange time unavailable", extra={"event": "risk_clock_failed"}, exc_info=True)
            return None
        self._last_exchange_ms = max(self._last_exchange_ms, now_ms)
        return now_ms

    def _note_order_sent(self, at_ms: int) -> None:
        while self._sent_ms and self._sent_ms[0] <= at_ms - RATE_WINDOW_MS:
            self._sent_ms.popleft()
        self._sent_ms.append(at_ms)

    # ------------------------------------------------------------------------------- state and kill switch

    @property
    def paused(self) -> bool:
        """Whether entries are refused by the kill switch or the drawdown pause (also while the state is unknown)."""
        return self._state.paused or self._state_unreadable

    def pause(self) -> None:
        """Kill switch: refuse new opens and adds at once. Persisted.

        Raises:
            RiskStateError: the pause could not be saved. It is in force in memory anyway and entries stay refused."""
        with self._state_lock:
            self._state = replace(self._state, manual_pause=True)
            if self._state_unreadable:
                _log.error("paused in memory only: the state file is unreadable", extra={"event": "risk_pause_unsaved"})
                return
            self._persist()

    def resume(self) -> None:
        """Clear the pause (manual and drawdown). Persisted.

        Raises:
            RiskStateError: the state file is unreadable (repair or delete it and restart) or the new state could not
                be saved (the gate stays paused in that case)."""
        with self._state_lock:
            if self._state_unreadable:
                raise RiskStateError("the risk state file is unreadable; repair or delete it and restart")
            previous = self._state
            self._state = replace(previous, manual_pause=False, drawdown_pause=False)
            try:
                self._persist()
            except RiskStateError:
                self._state = previous
                raise

    def mark_equity(self, now_ms: int) -> None:
        """Mark-to-market the account (called every ``eval.mark_interval_s``): updates opening equity, the daily and
        weekly halts and the drawdown pause. An unknown equity changes nothing. Never raises for a bad equity source."""
        if self._state_unreadable:
            _log.error("equity mark skipped: the state file is unreadable", extra={"event": "risk_mark_skipped"})
            return
        try:
            equity = self._account.equity_usd()
        except Exception:
            _log.warning("equity unavailable for a mark", extra={"event": "risk_mark_failed"}, exc_info=True)
            return
        if not isinstance(equity, Decimal) or not equity.is_finite() or equity <= 0:
            _log.warning("equity unknown at a mark", extra={"event": "risk_mark_unknown"})
            return
        with self._state_lock:
            before = self._state
            after, halts = apply_mark(
                before,
                now_ms=now_ms,
                equity_usd=equity,
                settings=self._settings,
            )
            self._state = after
            if after != before or self._persist_failed:
                try:
                    self._persist()
                except RiskStateError:
                    _log.exception("the risk state could not be saved", extra={"event": "risk_state_unsaved"})
        for halt in halts:
            self._announce(halt, now_ms)

    def _announce(self, halt: Halt, now_ms: int) -> None:
        """Record a halt in the ledger and alert. The alert goes out even when the ledger write fails."""
        payload: dict[str, Any] = {
            "reason": halt.reason,
            "equity_usd": halt.equity_usd,
            "reference_equity_usd": halt.reference_equity_usd,
            "limit": halt.limit,
            "halted_until_ms": halt.until_ms,
            "at_ms": now_ms,
        }
        try:
            self._ledger.append("risk_halt", payload)
        finally:
            self._send_alert(_HALT_ALERTS[halt.reason], f"{halt.reason} limit hit at equity {halt.equity_usd}")

    def _send_alert(self, kind: str, message: str) -> None:
        try:
            self._alerts.send(Alert(kind=kind, message=message))
        except Exception:
            _log.exception("a risk alert could not be delivered", extra={"event": "risk_alert_failed", "kind": kind})

    def _initial_state(self) -> RiskState:
        try:
            return load_state(self._state_path)
        except RiskStateError:
            _log.exception("the risk state is unreadable; entries are refused", extra={"event": "risk_state_bad"})
            self._state_unreadable = True
            return RiskState()

    def _persist(self) -> None:
        """Save the state; a failed save refuses entries until one succeeds (A2). The caller holds the lock."""
        try:
            save_state(self._state_path, self._state)
        except RiskStateError:
            self._persist_failed = True
            raise
        self._persist_failed = False


def _usable(rules: object) -> TypeGuard[CoinMeta]:
    """Whether a coin's fetched rules can be used (the same test the broker applies)."""
    return (
        isinstance(rules, CoinMeta)
        and type(rules.sz_decimals) is int
        and 0 <= rules.sz_decimals <= MAX_SZ_DECIMALS
        and type(rules.max_leverage) is int
        and rules.max_leverage >= 1
    )


def _validate_entry(request: OpenRequest | AddRequest, draft: _Draft) -> None:
    """Malformed input is refused, never computed with (a NaN multiplier, a stop on the wrong side of the price)."""
    if request.decision_px <= 0:
        draft.fail("invalid_request", "the decision price must be positive")
    stops = (request.stop_px, request.current_stop_px) if isinstance(request, AddRequest) else (request.stop_px,)
    for stop in stops:
        protective = stop < request.decision_px if request.is_long else stop > request.decision_px
        if stop <= 0 or not protective:
            draft.fail("invalid_stop", "the stop must sit on the protective side of the decision price")
    if isinstance(request, AddRequest):
        quantities = (request.our_share_qty, request.leader_add_size, request.leader_pre_add_position)
        if any(q <= 0 for q in quantities):
            draft.fail("invalid_request", "an add needs positive quantities")
    else:
        if not request.vol_mult.is_finite() or request.vol_mult <= 0:
            draft.fail("invalid_request", "vol_mult must be finite and positive")
        if not request.leader_position_notional_usd.is_finite() or request.leader_position_notional_usd < 0:
            draft.fail("invalid_request", "the leader's position notional must be finite and not negative")
    draft.ok("request", "well formed")


def _cap_check(cap: Cap, limit_notional_usd: Decimal) -> RiskCheckResult:
    return RiskCheckResult(
        cap.name,
        cap.room_usd > 0,
        f"limit {cap.limit_usd}, used {cap.used_usd}, room {cap.room_usd}, largest notional {limit_notional_usd}",
    )


def _plan_detail(plan: LeveragePlan, ceiling: int) -> str:
    return f"{plan.reason or 'fits'}: leverage {plan.leverage}, ceiling {ceiling}, liquidation {plan.liquidation_px}"
