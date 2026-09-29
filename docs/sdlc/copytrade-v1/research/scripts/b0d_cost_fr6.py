"""EXPLORATORY - SYNTHETIC - NOT VALIDATION (E11, round-2 audit BT2-1 and BT2-8).

Part 1 (BT2-1). Zero NET timing value in a trending month: the copy's R and the direction-matched
random-time baseline (B0d) have the same expected factor exposure and the same fee+spread cost, so
under the corrected cost specification (addendum A1.1: B0d never pays post-signal decay) the
expected D_i is 0. Under the superseded v2 wording, B0d was also charged the copy's delay cost
d (in R), which shifts D_i up by d. Rows: P(frozen P2 at 96%) and P(P2 and P2c at 96%) for
d = 0 (corrected), 0.05R and 0.10R (superseded wording).

Part 2 (BT2-8). FR6 = mean R over S without the best UTC-day cluster (largest sum of R) <= 0.
Rows: given a frozen-P2 pass at 96%, the share of runs in which FR6 fires, for 300 trades on
8 / 21 / 30 UTC days, at true mean R +0.10 and +0.15, no beta and day-factor corr 0.3 with 80% long.

Trade model: gate_power.py section D2 (merged positions, day factor x direction), except that in
part 1 the daily factor has mean `trend` (a trending month). All assumption, not data.
Usage (from this folder): python3 b0d_cost_fr6.py > ../../../../../research/data/b0d_cost_fr6_seed41.txt
Stdlib only; seed 41 fixed inside; 2 processes; results do not depend on the process count.
"""
from __future__ import annotations

import math
import random
import statistics
from multiprocessing import Pool

import gate_power as g

SEED = 41
SIMS = 2000
BOOT = 1000
SHIFTS = (0.0, 0.05, 0.10)


def gen_trend(rng: random.Random, loc: float, sd: float, rho_d: float, p_long: float, trend: float,
              days: int = 30, mean_extra: float = 0.5, rho_p: float = 0.5):
    """gate_power.gen_trades with a daily factor F_day ~ Normal(trend, 1)."""
    f = [rng.gauss(trend, 1) for _ in range(days)]
    a_d, a_p, a_e = math.sqrt(rho_d), math.sqrt(rho_p * (1 - rho_d)), math.sqrt((1 - rho_p) * (1 - rho_d))
    rs, ds, ss = [], [], []
    while len(rs) < g.N_TRADES:
        day = rng.randrange(days)
        s = 1 if rng.random() < p_long else -1
        size = 1 + (rng.random() < mean_extra / (1 + mean_extra)) * (1 + int(rng.expovariate(1.0)))
        size = min(size, g.N_TRADES - len(rs))
        p = rng.gauss(0, 1)
        for _ in range(size):
            rs.append(g.clip(loc + sd * (a_d * s * f[day] + a_p * p + a_e * rng.gauss(0, 1))))
            ds.append(day)
            ss.append(s)
    return rs, ds, ss, f


def cell_p2c(args: tuple) -> str:
    rho_d, p_long, trend, seed = args
    rng = random.Random(seed)
    loc0 = g.calibrate(0.0, 1.2)
    p2 = 0
    both = dict.fromkeys(SHIFTS, 0)
    means = []
    for _ in range(SIMS):
        rs, ds, ss, f = gen_trend(rng, loc0, 1.2, rho_d, p_long, trend)
        means.append(statistics.fmean(rs))
        if g.frozen_lb(rs, ds, rng, BOOT, g.LEVEL_RUN1) > 0:
            p2 += 1
            base = g.baseline_means(rng, loc0, 1.2, rho_d, ss, f)
            for d in SHIFTS:
                dd = [r - (x - d) for r, x in zip(rs, base)]
                both[d] += g.frozen_lb(dd, ds, rng, BOOT, g.LEVEL_RUN1) > 0
    cols = "  ".join(f"P2+P2c, B0d charged {d:.2f}R {'(corrected)' if d == 0 else '(superseded)'} "
                     f"{g.wilson(v, SIMS)}" for d, v in both.items())
    return (f"   corr {rho_d:.1f}, long {p_long:.0%}, factor trend {trend:+.2f} (mean copy R "
            f"{statistics.fmean(means):+.3f}; zero net timing value): P2 {g.wilson(p2, SIMS)}\n      {cols}")


def fr6(rs: list[float], ds: list[int]) -> bool:
    tot: dict[int, float] = {}
    for r, d in zip(rs, ds):
        tot[d] = tot.get(d, 0.0) + r
    best = max(tot, key=lambda d: (tot[d], -d))
    rest = [r for r, d in zip(rs, ds) if d != best]
    return (not rest) or statistics.fmean(rest) <= 0


def cell_fr6(args: tuple) -> str:
    days, rho_d, p_long, mu, seed = args
    rng = random.Random(seed)
    loc = g.calibrate(mu, 1.2)
    passes = fires = 0
    for _ in range(SIMS):
        rs, ds, _ps, _ss, _f = g.gen_trades(rng, loc, 1.2, rho_d, p_long, 0.5, 0.5, days)
        if g.frozen_lb(rs, ds, rng, BOOT, g.LEVEL_RUN1) > 0:
            passes += 1
            fires += fr6(rs, ds)
    return (f"   {days:>2} days, corr {rho_d:.1f}, long {p_long:.0%}, mu {mu:+.2f}: P2 pass "
            f"{g.wilson(passes, SIMS)}; FR6 fires given a pass {g.wilson(fires, passes)}")


def run(task: tuple) -> str:
    kind, args = task
    return cell_p2c(args) if kind == "p2c" else cell_fr6(args)


if __name__ == "__main__":
    tasks, i = [], 0
    for rho_d, p_long in ((0.3, 0.8), (0.5, 0.8)):
        for trend in (0.0, 0.25, 0.5):
            i += 1
            tasks.append(("p2c", (rho_d, p_long, trend, SEED * 100_003 + i)))
    for mu in (0.10, 0.15):
        for rho_d, p_long in ((0.0, 0.5), (0.3, 0.8)):
            for days in (8, 21, 30):
                i += 1
                tasks.append(("fr6", (days, rho_d, p_long, mu, SEED * 100_003 + i)))
    with Pool(2) as pool:
        out = pool.map(run, tasks, chunksize=1)
    print(f"EXPLORATORY / SYNTHETIC (E11). sims per cell {SIMS}, bootstrap resamples {BOOT}, seed {SEED}. "
          "Brackets: Wilson 95% Monte Carlo interval.\n")
    print("1. BT2-1: zero net timing value, trending month. P(PASS on P2 and P2c), run-1 level 96%")
    print("\n".join(o for (k, _), o in zip(tasks, out) if k == "p2c"))
    print("\n2. BT2-8: FR6 (mean R without the best UTC-day cluster <= 0), given a frozen-P2 pass at 96%")
    print("\n".join(o for (k, _), o in zip(tasks, out) if k == "fr6"))
