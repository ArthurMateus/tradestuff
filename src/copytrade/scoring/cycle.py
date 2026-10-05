"""One scoring cycle: score every wallet, rank the eligible, persist (F5.AC3, AC5, AC6, AC7).

Persistence is a boundary (``ScoreStore``): a cycle is appended exactly once, and a store failure propagates. The
leaderboard row (``pnl``, ``roi``, ``accountValue``) is self-reported and is never read here (C1, F5.AC6).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass, replace
from decimal import Decimal
from typing import Any

from copytrade.core.config import Config
from copytrade.scoring.blowup import detect_blowups
from copytrade.scoring.gates import evaluate_gates
from copytrade.scoring.metrics import compute_metrics, daily_returns, latest_snapshot, trip_records
from copytrade.scoring.models import (
    MINUTE_MS,
    CostModel,
    CycleResult,
    RankEntry,
    ScoreStore,
    WalletInputs,
    WalletScore,
)
from copytrade.scoring.reconstruct import dedupe_fills, is_core_perp
from copytrade.scoring.score import rank_entries, score_components

STALE_REASON = "stale_input"


def _canonical(obj: Any) -> Any:
    """A JSON-ready form: Decimals as plain normalised text, dataclasses and mappings as sorted objects."""
    if isinstance(obj, Decimal):
        return format(obj.normalize(), "f")
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _canonical(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Mapping):
        return {str(k): _canonical(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    return obj


def _digest(obj: Any) -> str:
    text = json.dumps(_canonical(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def input_hashes(inputs: WalletInputs, *, t_ms: int) -> Mapping[str, str]:
    """sha256 hex per input kind (``fills``, ``funding``, ``portfolio``, ``clearinghouse``, ``own_snapshots``,
    ``candles``) over the canonical bytes of the point-in-time inputs actually used (10.1). The leaderboard row is
    not hashed. Stable across processes and input order: items are sorted, repeats removed, and anything after
    ``t_ms`` (a fill, a snapshot fetched later, a bar that closes later) is left out.
    """
    fills = sorted(  # the venue's tid is only for de-duplication: the record covers what was traded, not its id
        (
            _canonical({k: v for k, v in vars(f).items() if k != "tid"})
            for f in dedupe_fills(f for f in inputs.fills if is_core_perp(f.coin) and f.time <= t_ms)
        ),
        key=lambda c: json.dumps(c, sort_keys=True),
    )
    funding = sorted(
        (p for p in inputs.funding if is_core_perp(p.coin) and p.time <= t_ms), key=lambda p: (p.time, p.coin, p.paid)
    )
    own = sorted((o for o in inputs.own_snapshots if o.ms <= t_ms), key=lambda o: o.ms)
    candles = {
        coin: sorted((b for b in bars if b.close_ms <= t_ms), key=lambda b: (b.open_ms, b.close_ms))
        for coin, bars in inputs.candles_1h.items()
    }
    return {
        "fills": _digest(fills),
        "funding": _digest(funding),
        "portfolio": _digest(latest_snapshot(inputs.portfolios, t_ms)),
        "clearinghouse": _digest(latest_snapshot(inputs.clearinghouse, t_ms)),
        "own_snapshots": _digest(own),
        "candles": _digest(candles),
    }


def _is_stale(inputs: WalletInputs, *, cfg: Config, t_ms: int) -> bool:
    """A required input is missing, fetched after the cycle time, or older than
    ``scoring.stale_input_mult * scoring.interval_min`` minutes (fail closed, A2)."""
    limit_ms = cfg["scoring.stale_input_mult"] * cfg["scoring.interval_min"] * MINUTE_MS
    portfolio = latest_snapshot(inputs.portfolios, t_ms)
    clearinghouse = latest_snapshot(inputs.clearinghouse, t_ms)
    fetched = (
        inputs.fills_fetched_ms,
        inputs.candles_fetched_ms,
        None if portfolio is None else portfolio.fetched_ms,
        None if clearinghouse is None else clearinghouse.fetched_ms,
    )
    return any(ms is None or ms > t_ms or t_ms - ms > limit_ms for ms in fetched)


def score_wallet(
    inputs: WalletInputs, *, cfg: Config, t_ms: int, costs: CostModel, p95_latency_s: Decimal | None
) -> WalletScore:
    """Metrics, blow-up flags, gates and (if eligible) components and S for one wallet, with ``rank`` None.

    A missing input, or the latest input older than ``scoring.stale_input_mult * scoring.interval_min`` minutes,
    gives ``eligible=False`` with the reason ``stale_input`` (listed before the gate reasons) and no score. The
    metrics are still computed, so the audit record and the blow-up flags exist. Depends on this wallet's data only.
    """
    address = inputs.address.lower()
    metrics = compute_metrics(inputs, cfg=cfg, t_ms=t_ms, costs=costs)
    flags = detect_blowups(trip_records(inputs, cfg=cfg, t_ms=t_ms), metrics, cfg=cfg)
    failed = evaluate_gates(
        metrics, cfg=cfg, address=address, role=inputs.role, p95_latency_s=p95_latency_s, blowup_flags=flags
    )
    reasons = (STALE_REASON, *failed) if _is_stale(inputs, cfg=cfg, t_ms=t_ms) else failed
    components = None
    if not reasons:
        # No gate covers the recent Sharpe: a wallet with no measurable recent variance gets u = 0 (the worst outcome)
        # on that component, set explicitly and not by feeding a value in as input. The stored metric keeps the None.
        components = score_components(metrics, cfg=cfg, recent_sr_unmeasurable_is_worst=True)
    _, resolution = daily_returns(inputs, cfg=cfg, t_ms=t_ms)
    return WalletScore(
        address=address,
        eligible=not reasons,
        reasons=reasons,
        blowup_flags=flags,
        metrics=metrics,
        components=components,
        score=None if components is None else components.score,
        rank=None,
        input_hashes=input_hashes(inputs, t_ms=t_ms),
        dsr_resolution=resolution,
    )


def score_cycle(
    wallets: Sequence[WalletInputs], *, cfg: Config, t_ms: int, costs: CostModel, p95_latency_s: Decimal | None
) -> CycleResult:
    """Score all wallets and rank the eligible ones (rank 1 = best) with the deterministic tie-break.

    Eligible wallets come first in rank order, then the ineligible ones by address.
    """
    scored = [score_wallet(w, cfg=cfg, t_ms=t_ms, costs=costs, p95_latency_s=p95_latency_s) for w in wallets]
    owner: dict[int, WalletScore] = {}
    entries: list[RankEntry] = []
    for s in scored:
        if s.eligible and s.score is not None and s.metrics is not None:
            entry = RankEntry(s.address, s.score, s.metrics.n_rt)
            owner[id(entry)] = s
            entries.append(entry)
    ordered = [replace(owner[id(e)], rank=i) for i, e in enumerate(rank_entries(entries), start=1)]
    ineligible = sorted((s for s in scored if not s.eligible), key=lambda s: s.address)
    return CycleResult(t_ms=t_ms, scores=(*ordered, *ineligible))


def run_cycle(  # noqa: PLR0913
    store: ScoreStore,
    wallets: Sequence[WalletInputs],
    *,
    cfg: Config,
    t_ms: int,
    costs: CostModel,
    p95_latency_s: Decimal | None,
) -> CycleResult:
    """``score_cycle`` then ``store.append_cycle`` exactly once. A store failure propagates (nothing is swallowed)."""
    result = score_cycle(wallets, cfg=cfg, t_ms=t_ms, costs=costs, p95_latency_s=p95_latency_s)
    store.append_cycle(result)
    return result
