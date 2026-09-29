"""EXPLORATORY - SYNTHETIC - NOT VALIDATION.

Monte Carlo estimate of how many *taken* copy trades a 30-day paper run produces
with 5-10 followed Hyperliquid traders, after the deterministic filter, signal-age
and slippage skips, conflict skips, Hyperliquid's $10 minimum order value, the
concurrency cap, and the daily/weekly loss halts. It also reports:
  * the share of mirrored partial exits that would fall below $10 on a $300 wallet
  * the probability of touching the 15% drawdown FAIL line at a given true mean R

Every input is an ASSUMPTION (no Hyperliquid data was reachable from the research
environment on 2026-09-29: the egress proxy refused api.hyperliquid.xyz). The
numbers show sensitivity, not facts. Replace the priors with measured values
from hl_sample.py or the 24h dry run before relying on them.

Stdlib only. Deterministic: fixed seed. Floats are fine here (research code, not
the money path).

Usage: python3 feasibility_mc.py [--runs 2000] [--seed 7]
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass, replace

MIN_ORDER_USD = 10.0          # Hyperliquid minimum order value (docs, inclusive)
WALLET_USD = 300.0            # PO decision
RISK_PER_TRADE = 0.01         # PO decision: <=1% of wallet at risk
DAILY_LOSS = 0.02             # PO decision
WEEKLY_LOSS = 0.05            # PO decision
MAX_DD = 0.15                 # PO decision: FAIL line
MAX_CONCURRENT = 10           # PO decision
DAYS = 30


@dataclass(frozen=True)
class Scenario:
    name: str
    n_followed: int
    opens_per_day_median: float   # new positions per trader per day
    opens_sigma: float            # lognormal dispersion across traders
    hold_hours_median: float
    frac_median: float            # leader position notional / leader account value at the open
    frac_sigma: float
    scale_in_prob: float          # P(leader's first fill is only a tranche of the final size)
    stop_pct_median: float        # our ATR-based stop distance as a fraction of price
    p_filter_pass: float          # deterministic filter (trend, vol, spread, funding, events)
    p_age_ok: float               # signal age <= 5s
    p_slip_ok: float              # slippage vs leader px within 0.3% / 0.8%
    p_no_conflict: float          # no opposite-direction open by another followed trader
    p_other_caps_ok: float        # BTC-beta bucket, per-trader cap, per-symbol cap
    partials_per_trade: float     # Poisson mean of leader partial reduces per position
    true_mean_r: float            # net of costs
    r_sd_target: float            # approx SD of per-trade R
    risk_per_trade: float = RISK_PER_TRADE


BASE = Scenario(
    name="base",
    n_followed=8,
    opens_per_day_median=3.0,
    opens_sigma=0.8,
    hold_hours_median=4.0,
    frac_median=0.5,
    frac_sigma=1.2,
    scale_in_prob=0.5,
    stop_pct_median=0.025,
    p_filter_pass=0.65,
    p_age_ok=0.90,
    p_slip_ok=0.95,
    p_no_conflict=0.97,
    p_other_caps_ok=0.92,
    partials_per_trade=0.8,
    true_mean_r=0.0,
    r_sd_target=1.2,
)

SCENARIOS = [
    replace(BASE, name="pessimistic", n_followed=5, opens_per_day_median=1.5,
            hold_hours_median=8.0, frac_median=0.15, p_filter_pass=0.5, p_age_ok=0.75,
            p_slip_ok=0.9),
    BASE,
    replace(BASE, name="optimistic", n_followed=10, opens_per_day_median=6.0,
            hold_hours_median=2.0, frac_median=1.5, p_filter_pass=0.8, p_age_ok=0.97,
            p_slip_ok=0.97),
    replace(BASE, name="base_risk_0.5pct", risk_per_trade=0.005),
]


def lognormal(rng: random.Random, median: float, sigma: float) -> float:
    return median * math.exp(rng.gauss(0.0, sigma))


def draw_r(rng: random.Random, loc: float, sd: float) -> float:
    """Bounded per-trade R: stop at about -1R (plus slippage), a take-profit/trail
    cap at +3R, leader exits in between."""
    return min(max(rng.gauss(loc, sd), -1.05), 3.0)


def calibrate_loc(target_mean: float, sd: float, rng: random.Random, n: int = 200_000) -> float:
    """Find the pre-clip location so that E[clipped R] == target_mean (bisection)."""
    zs = [rng.gauss(0.0, 1.0) for _ in range(n)]
    lo, hi = -2.0, 2.0
    for _ in range(40):
        mid = (lo + hi) / 2
        m = sum(min(max(mid + sd * z, -1.05), 3.0) for z in zs) / n
        if m < target_mean:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def run_once(sc: Scenario, rng: random.Random, r_loc: float, r_sd: float) -> dict:
    # 1. candidate opens: (time_hours, trader)
    events = []
    for trader in range(sc.n_followed):
        # eligibility gate: >=150 round trips in 180d  =>  >= 0.83/day
        lam = min(max(lognormal(rng, sc.opens_per_day_median, sc.opens_sigma), 0.83), 20.0)
        t = 0.0
        while True:
            t += rng.expovariate(lam / 24.0)
            if t >= DAYS * 24:
                break
            events.append((t, trader))
    events.sort()

    reasons = {"raw": len(events), "filter": 0, "age": 0, "slippage": 0, "conflict": 0,
               "caps": 0, "min_size": 0, "concurrency": 0, "loss_halt": 0, "dd_fail_stop": 0}
    dd_failed = False
    taken_before_dd_fail = 0
    open_positions: list[tuple[float, float, float]] = []   # (close_time, r, risk_frac)
    equity, peak, max_dd = 1.0, 1.0, 0.0
    day_loss: dict[int, float] = {}
    week_loss: dict[int, float] = {}
    taken = 0
    partials_total = 0
    partials_unexec = 0

    def settle_until(now: float) -> None:
        nonlocal equity, peak, max_dd
        still = []
        for pos in sorted(open_positions):
            close_t, r, risk = pos
            if close_t <= now:
                pnl = r * risk
                equity += pnl
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak)
                # loss limits act on NET realised P&L of the UTC day / week
                d = int(close_t // 24)
                day_loss[d] = day_loss.get(d, 0.0) - pnl
                week_loss[d // 7] = week_loss.get(d // 7, 0.0) - pnl
            else:
                still.append(pos)
        open_positions[:] = still

    for t, _trader in events:
        settle_until(t)
        if max_dd >= MAX_DD:
            # PO rule: 15% drawdown pauses the bot and the paper run is a FAIL
            if not dd_failed:
                dd_failed = True
                taken_before_dd_fail = taken
            reasons["dd_fail_stop"] += 1
            continue
        if rng.random() > sc.p_filter_pass:
            reasons["filter"] += 1
            continue
        if rng.random() > sc.p_age_ok:
            reasons["age"] += 1
            continue
        if rng.random() > sc.p_slip_ok:
            reasons["slippage"] += 1
            continue
        if rng.random() > sc.p_no_conflict:
            reasons["conflict"] += 1
            continue
        if rng.random() > sc.p_other_caps_ok:
            reasons["caps"] += 1
            continue
        d = int(t // 24)
        if day_loss.get(d, 0.0) >= DAILY_LOSS or week_loss.get(d // 7, 0.0) >= WEEKLY_LOSS:
            reasons["loss_halt"] += 1
            continue
        if len(open_positions) >= MAX_CONCURRENT:
            reasons["concurrency"] += 1
            continue
        # 2. sizing: mirror the leader's fraction, then cap by risk (cap always wins)
        frac = lognormal(rng, sc.frac_median, sc.frac_sigma)
        if rng.random() < sc.scale_in_prob:
            frac *= rng.uniform(0.2, 1.0)        # first tranche only
        stop_pct = lognormal(rng, sc.stop_pct_median, 0.4)
        notional = frac * WALLET_USD
        notional = min(notional, sc.risk_per_trade * WALLET_USD / stop_pct)
        notional = min(notional, 3.0 * WALLET_USD)   # 3x default leverage ceiling on one position
        if notional < MIN_ORDER_USD:
            reasons["min_size"] += 1
            continue
        risk_frac = notional * stop_pct / WALLET_USD   # fraction of wallet at risk
        # 3. partial exits mirrored by percentage
        k = 0
        lam_p = sc.partials_per_trade
        # Poisson draw (Knuth), fine for small lambda
        L, p = math.exp(-lam_p), 1.0
        while True:
            p *= rng.random()
            if p <= L:
                break
            k += 1
        remaining = notional
        for _ in range(k):
            cut = remaining * rng.uniform(0.2, 0.6)
            partials_total += 1
            if cut < MIN_ORDER_USD:
                partials_unexec += 1
            else:
                remaining -= cut
        hold = lognormal(rng, sc.hold_hours_median, 1.0)
        r = draw_r(rng, r_loc, r_sd)
        open_positions.append((t + hold, r, risk_frac))
        taken += 1
    settle_until(float("inf"))
    if max_dd >= MAX_DD and not dd_failed:
        dd_failed = True
        taken_before_dd_fail = taken
    return {"taken": taken, "dd_failed": dd_failed,
            "reached_300_clean": taken >= 300 and (not dd_failed or taken_before_dd_fail >= 300),
            "reasons": reasons, "max_dd": max_dd, "final_equity": equity,
            "partials_total": partials_total, "partials_unexec": partials_unexec}


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    print("EXPLORATORY / SYNTHETIC priors, not Hyperliquid data. 30-day run, $300 wallet.\n")
    for sc in SCENARIOS:
        for mean_r in (0.0, 0.1):
            loc_rng = random.Random(args.seed + 1)
            r_loc = calibrate_loc(mean_r, sc.r_sd_target, loc_rng)
            res = [run_once(sc, rng, r_loc, sc.r_sd_target) for _ in range(args.runs)]
            taken = [x["taken"] for x in res]
            dd = [x["max_dd"] for x in res]
            raw = sum(x["reasons"]["raw"] for x in res) / len(res)
            print(f"[{sc.name}] true mean R={mean_r:+.2f}  followed={sc.n_followed} "
                  f"opens/trader/day~{sc.opens_per_day_median}")
            print(f"  raw leader opens / 30d: mean {raw:.0f}")
            print(f"  taken trades / 30d: p10 {pct(taken, .1):.0f}  p50 {pct(taken, .5):.0f}  "
                  f"p90 {pct(taken, .9):.0f}   P(>=300) = {sum(t >= 300 for t in taken) / len(taken):.2f}")
            agg = {k: sum(x["reasons"][k] for x in res) / len(res) for k in res[0]["reasons"]}
            print("  mean rejections: " + ", ".join(f"{k} {v:.0f}" for k, v in agg.items() if k != "raw"))
            pt = sum(x["partials_total"] for x in res)
            pu = sum(x["partials_unexec"] for x in res)
            print(f"  mirrored partial exits below $10: {pu / pt:.0%} of {pt / len(res):.0f}/run")
            print(f"  max drawdown: p50 {pct(dd, .5):.1%}  p90 {pct(dd, .9):.1%}  "
                  f"P(DD>=15%) = {sum(x['dd_failed'] for x in res) / len(res):.3f}")
            print(f"  P(300 trades reached before any 15% DD) = "
                  f"{sum(x['reached_300_clean'] for x in res) / len(res):.2f}\n")


if __name__ == "__main__":
    main()
