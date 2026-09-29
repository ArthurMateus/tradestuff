"""EXPLORATORY - SYNTHETIC - NOT VALIDATION.

feasibility_mc.py v2 (2026-09-29). Revised after the backtest audit (BT-6, BT-8, BT-9, BT-10)
and the PO decisions of 2026-09-29.

Monte Carlo of a paper run under the FROZEN rules: 0.5% risk per trade, at most 9 followed
wallets, sample = the first 300 OPENED trades, evaluated once all have closed (close-out cap 7 days
after the 300th open), 30 days extended to 60 days if fewer than 300 were opened by day 30. It
reports:
  * taken trades by day 30 and by day 60; P(300 opened by day 30 / by day 60)
  * drawdown: realised closes only (a LOWER bound on the mark-to-market drawdown the gate uses) and a
    pessimistic mark-to-market bound (every open position at its worst excursion at once; an UPPER
    bound) (BT-8)
  * JOINT P(PASS): 300 opened by day 60, no 15% drawdown before evaluation, net USD P&L > 0, and
    LB > 0 where LB = min(iid t, UTC-day cluster-robust t) at the run-1 level of 96%. The day-cluster
    bootstrap part of the frozen rule is omitted for speed, so this slightly OVERSTATES P(PASS). The
    baseline test P2c is not modelled: there is no market in this model (BT-6)
  * rejection shares with explicit denominators (BT-9)
  * mirrored partial exits under the PO rule (remainder < $10 -> close all; else cut < $10 -> skip)
Scenarios include 3-5 followed traders with no activity floor (BT-10), and a daily market factor
times direction with a long bias (correlated R, BT-8).

Every input is an ASSUMPTION (no Hyperliquid data reachable from the research environment on
2026-09-29). Replace the priors with measured values from hl_sample.py or the 24h dry run before
relying on them. Per-trade R is i.i.d. clipped normal unless rho_day > 0; the partial exits do not
change R here.

Stdlib only. Deterministic: fixed seed. Floats are fine here (research code, not the money path).
Usage: python3 feasibility_mc.py [--runs 2000] [--seed 17]
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass, replace

from gate_power import crt_lb, lb_t

MIN_ORDER_USD = 10.0          # Hyperliquid minimum order value (docs, inclusive)
WALLET_USD = 300.0            # PO decision
DAILY_LOSS = 0.02             # PO decision
WEEKLY_LOSS = 0.05            # PO decision
MAX_DD = 0.15                 # PO decision: FAIL line
MAX_CONCURRENT = 10           # PO decision
N_SAMPLE = 300                # PO: first 300 opened trades
DAYS_BASE, DAYS_MAX = 30, 60  # PO: extend to 60 days if < 300 opened by day 30
CLOSEOUT_H = 7 * 24           # QR: evaluation no later than 7 days after the 300th open
LEVEL_RUN1 = 0.96             # alpha split: run 1 at 96%


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
    r_sd_target: float            # approx SD of per-trade R
    risk_per_trade: float = 0.005             # PO 2026-09-29
    n_followed_range: tuple[int, int] | None = None   # draw n per run (inclusive)
    open_rate_floor: float | None = 0.83      # G2: >= 150 round trips in 180 d
    rho_day: float = 0.0                      # daily market factor x direction
    p_long: float = 0.5


BASE = Scenario(
    name="base", n_followed=8, opens_per_day_median=3.0, opens_sigma=0.8, hold_hours_median=4.0,
    frac_median=0.5, frac_sigma=1.2, scale_in_prob=0.5, stop_pct_median=0.025,
    p_filter_pass=0.65, p_age_ok=0.90, p_slip_ok=0.95, p_no_conflict=0.97, p_other_caps_ok=0.92,
    partials_per_trade=0.8, r_sd_target=1.2,
)

SCENARIOS = [
    replace(BASE, name="pessimistic", n_followed=5, opens_per_day_median=1.5, hold_hours_median=8.0,
            frac_median=0.15, p_filter_pass=0.5, p_age_ok=0.75, p_slip_ok=0.9),
    replace(BASE, name="few_3to5_nofloor", n_followed_range=(3, 5), opens_per_day_median=2.0,
            open_rate_floor=None),
    BASE,
    replace(BASE, name="optimistic", n_followed=9, opens_per_day_median=6.0, hold_hours_median=2.0,
            frac_median=1.5, p_filter_pass=0.8, p_age_ok=0.97, p_slip_ok=0.97),
    replace(BASE, name="base_corr_rho0.2_long70", rho_day=0.2, p_long=0.7),
    replace(BASE, name="base_risk_1pct_reference", risk_per_trade=0.01),
]


def lognormal(rng: random.Random, median: float, sigma: float) -> float:
    return median * math.exp(rng.gauss(0.0, sigma))


def clip_r(x: float) -> float:
    """Bounded per-trade R: stop at about -1R (plus slippage), a TP/trail cap at +3R."""
    return min(max(x, -1.05), 3.0)


def calibrate_loc(target_mean: float, sd: float, rng: random.Random, n: int = 200_000) -> float:
    """Pre-clip location so that E[clipped R] == target_mean (bisection)."""
    zs = [rng.gauss(0.0, 1.0) for _ in range(n)]
    lo, hi = -2.0, 2.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if sum(clip_r(mid + sd * z) for z in zs) / n < target_mean:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def poisson(rng: random.Random, lam: float) -> int:
    k, p, lim = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= lim:
            return k
        k += 1


def run_once(sc: Scenario, rng: random.Random, r_loc: float, r_sd: float) -> dict:
    n_f = rng.randint(*sc.n_followed_range) if sc.n_followed_range else sc.n_followed
    events = []
    for trader in range(n_f):
        lam = lognormal(rng, sc.opens_per_day_median, sc.opens_sigma)
        if sc.open_rate_floor is not None:
            lam = max(lam, sc.open_rate_floor)
        lam = min(lam, 20.0)
        t = 0.0
        while True:
            t += rng.expovariate(lam / 24.0)
            if t >= DAYS_MAX * 24:
                break
            events.append((t, trader))
    events.sort()
    day_factor = [rng.gauss(0.0, 1.0) for _ in range(DAYS_MAX + 1)]
    a_d, a_e = math.sqrt(sc.rho_day), math.sqrt(1.0 - sc.rho_day)

    reasons = {"raw": len(events), "filter": 0, "age": 0, "slippage": 0, "conflict": 0, "caps": 0,
               "loss_halt": 0, "concurrency": 0, "min_size": 0, "dd_fail_stop": 0}
    st = {"equity": 1.0, "peak": 1.0, "max_dd": 0.0, "dd_fail_t": None, "pess_dd": 0.0, "pess_fail_t": None}
    open_pos: list[tuple[float, float, float, float]] = []    # (close_t, r, risk_frac, mae_r)
    day_loss: dict[int, float] = {}
    week_loss: dict[int, float] = {}
    taken: list[tuple[float, float, float, float]] = []        # (open_t, r, risk_frac, close_t)
    partials = {"total": 0, "skipped": 0, "closed_all": 0}
    t_eval = None

    def settle_until(now: float) -> None:
        still = []
        for pos in sorted(open_pos):
            close_t, r, risk, _ = pos
            if close_t <= now:
                pnl = r * risk
                st["equity"] += pnl
                st["peak"] = max(st["peak"], st["equity"])
                dd = (st["peak"] - st["equity"]) / st["peak"]
                st["max_dd"] = max(st["max_dd"], dd)
                if dd >= MAX_DD and st["dd_fail_t"] is None:
                    st["dd_fail_t"] = close_t
                d = int(close_t // 24)                 # loss limits act on NET realised P&L
                day_loss[d] = day_loss.get(d, 0.0) - pnl
                week_loss[d // 7] = week_loss.get(d // 7, 0.0) - pnl
            else:
                still.append(pos)
        open_pos[:] = still

    def mark_pessimistic(now: float) -> None:
        worst = st["equity"] + sum(risk * mae for _, _, risk, mae in open_pos)
        dd = (st["peak"] - worst) / st["peak"]
        st["pess_dd"] = max(st["pess_dd"], dd)
        if dd >= MAX_DD and st["pess_fail_t"] is None:
            st["pess_fail_t"] = now

    for t, _trader in events:
        if t_eval is not None and t > t_eval:
            break
        settle_until(t)
        mark_pessimistic(t)
        if st["dd_fail_t"] is not None:
            reasons["dd_fail_stop"] += 1               # PO: 15% drawdown pauses the bot; run FAILS
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
        if len(open_pos) >= MAX_CONCURRENT:
            reasons["concurrency"] += 1
            continue
        frac = lognormal(rng, sc.frac_median, sc.frac_sigma)
        if rng.random() < sc.scale_in_prob:
            frac *= rng.uniform(0.2, 1.0)              # first tranche only
        stop_pct = lognormal(rng, sc.stop_pct_median, 0.4)
        notional = min(frac * WALLET_USD, sc.risk_per_trade * WALLET_USD / stop_pct, 3.0 * WALLET_USD)
        if notional < MIN_ORDER_USD:
            reasons["min_size"] += 1
            continue
        risk_frac = notional * stop_pct / WALLET_USD
        remaining = notional                           # PO $10 rule for mirrored partial exits
        for _ in range(poisson(rng, sc.partials_per_trade)):
            cut = remaining * rng.uniform(0.2, 0.6)
            partials["total"] += 1
            if remaining - cut < MIN_ORDER_USD:
                partials["closed_all"] += 1
                break
            if cut < MIN_ORDER_USD:
                partials["skipped"] += 1
                continue
            remaining -= cut
        hold = lognormal(rng, sc.hold_hours_median, 1.0)
        s = 1.0 if rng.random() < sc.p_long else -1.0
        r = clip_r(r_loc + r_sd * (a_d * s * day_factor[d] + a_e * rng.gauss(0.0, 1.0)))
        mae = r if r < 0 else -rng.uniform(0.0, 0.8)   # worst excursion before the close (assumption)
        open_pos.append((t + hold, r, risk_frac, mae))
        taken.append((t, r, risk_frac, t + hold))
        if len(taken) == N_SAMPLE:                     # all 300 closed, capped at 7 days after the 300th open
            t_eval = min(max(c for _, _, _, c in taken), t + CLOSEOUT_H)
    settle_until(t_eval if t_eval is not None else float("inf"))
    if t_eval is not None:
        mark_pessimistic(t_eval)

    n30 = sum(1 for ot, _, _, _ in taken if ot < DAYS_BASE * 24)
    reached = len(taken) >= N_SAMPLE
    horizon = t_eval if reached else float("inf")
    dd_fail = st["dd_fail_t"] is not None and st["dd_fail_t"] <= horizon
    pess_fail = dd_fail or (st["pess_fail_t"] is not None and st["pess_fail_t"] <= horizon)
    passed = False
    if reached and not dd_fail:
        smp = taken[:N_SAMPLE]
        rs = [x[1] for x in smp]
        days = [int(x[0] // 24) for x in smp]
        usd = sum(r * risk for _, r, risk, _ in smp)
        passed = usd > 0 and min(lb_t(rs, LEVEL_RUN1), crt_lb(rs, days, LEVEL_RUN1)) > 0
    return {"n_followed": n_f, "taken30": n30, "taken60": len(taken), "reached30": n30 >= N_SAMPLE,
            "reached60": reached, "dd_fail": dd_fail, "pess_fail": pess_fail, "max_dd": st["max_dd"],
            "pess_dd": st["pess_dd"], "pass": passed, "pass_pess": passed and not pess_fail,
            "pass_by30": passed and n30 >= N_SAMPLE, "reasons": reasons, "partials": partials}


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]


def share(k: float, n: float) -> str:
    return f"{k / n:.1%} ({k:.0f}/{n:.0f})" if n else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    print("EXPLORATORY / SYNTHETIC priors, not Hyperliquid data. $300 wallet, 0.5% risk unless stated,\n"
          "first 300 opened trades, 30 days extended to 60. Rates are over all runs of a cell.\n")
    for sc in SCENARIOS:
        for mean_r in (0.0, 0.1):
            r_loc = calibrate_loc(mean_r, sc.r_sd_target, random.Random(args.seed + 1))
            res = [run_once(sc, rng, r_loc, sc.r_sd_target) for _ in range(args.runs)]
            n = len(res)
            agg = {k: sum(x["reasons"][k] for x in res) for k in res[0]["reasons"]}
            taken60 = sum(x["taken60"] for x in res)
            size_den = agg["min_size"] + taken60
            halt_den = agg["loss_halt"] + agg["concurrency"] + size_den
            pt = sum(x["partials"]["total"] for x in res)
            ps = sum(x["partials"]["skipped"] for x in res)
            pc = sum(x["partials"]["closed_all"] for x in res)
            f = sc.n_followed_range or (sc.n_followed, sc.n_followed)
            print(f"[{sc.name}] true mean R={mean_r:+.2f}  followed={f[0]}-{f[1]}  "
                  f"opens/trader/day~{sc.opens_per_day_median} floor={sc.open_rate_floor}  "
                  f"risk={sc.risk_per_trade:.1%}  rho_day={sc.rho_day} long={sc.p_long:.0%}")
            t30 = [x["taken30"] for x in res]
            t60 = [x["taken60"] for x in res]
            print(f"  taken by day 30: p10 {pct(t30, .1):.0f}  p50 {pct(t30, .5):.0f}  p90 {pct(t30, .9):.0f}   "
                  f"by day 60 (or stop): p10 {pct(t60, .1):.0f}  p50 {pct(t60, .5):.0f}  p90 {pct(t60, .9):.0f}")
            print(f"  P(300 opened by day 30) = {sum(x['reached30'] for x in res) / n:.2f}   "
                  f"P(300 opened by day 60) = {sum(x['reached60'] for x in res) / n:.2f}")
            print(f"  P(DD >= 15% before evaluation): realised-only LOWER bound {sum(x['dd_fail'] for x in res) / n:.3f}; "
                  f"pessimistic MTM UPPER bound {sum(x['pess_fail'] for x in res) / n:.3f}")
            print(f"  JOINT P(PASS), run 1 (96%): {sum(x['pass'] for x in res) / n:.3f} "
                  f"(evaluated within 30 days: {sum(x['pass_by30'] for x in res) / n:.3f}; "
                  f"with the pessimistic drawdown: {sum(x['pass_pess'] for x in res) / n:.3f})")
            print(f"  opens below $10 after the cap: {share(agg['min_size'], size_den)} of entries reaching the size check")
            print(f"  loss-halt blocks: {share(agg['loss_halt'], halt_den)} of entries reaching the halt check; "
                  f"concurrency blocks: {share(agg['concurrency'], halt_den)}")
            print(f"  mirrored partial exits: skipped (cut < $10) {share(ps, pt)}; closed all "
                  f"(remainder < $10) {share(pc, pt)}; {pt / n:.0f} partials/run\n")


if __name__ == "__main__":
    main()
