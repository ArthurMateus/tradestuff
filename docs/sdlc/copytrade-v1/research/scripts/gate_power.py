"""EXPLORATORY - SYNTHETIC - NOT VALIDATION.

Statistical properties of the PO's go-live gate:
  "lower bound of the 95% CI of mean trade R > 0 over ~300 trades"

Sections
  A. CI half-width at n=300 for plausible per-trade R dispersion.
  B. Power: P(gate PASS | true mean R) with a single look at n=300.
  C. Peeking: false-PASS rate at true mean R = 0 when the report is checked
     repeatedly (after every 10 trades) instead of once at n=300.
  D. Clustering: false-PASS rate at true mean R = 0 when several trader shares of one
     merged position (and same-hour BTC-beta trades) are counted as independent
     trades, naive t-CI vs a cluster bootstrap CI.
  E. Luck: expected best Sharpe z-score among N zero-skill traders and the
     Deflated Sharpe benchmark SR0 (Bailey & Lopez de Prado 2014).
  F. Mean R vs USD P&L under mirrored (variable-risk) sizing, toy example.

Per-trade R model: Normal(loc, sd) clipped to [-1.05, +3.0] (stop about -1R plus
slippage, take-profit/trail cap). Assumption, not data.

Stdlib only, fixed seed. Usage: python3 gate_power.py [--sims 4000] [--seed 11]
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
from statistics import NormalDist

Z975 = NormalDist().inv_cdf(0.975)
LO, HI = -1.05, 3.0


def clipped(rng: random.Random, loc: float, sd: float) -> float:
    return min(max(rng.gauss(loc, sd), LO), HI)


def calibrate(target: float, sd: float, seed: int = 1, n: int = 100_000) -> float:
    rng = random.Random(seed)
    zs = [rng.gauss(0, 1) for _ in range(n)]
    lo, hi = -2.0, 2.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if sum(min(max(mid + sd * z, LO), HI) for z in zs) / n < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def realised_sd(loc: float, sd: float, seed: int = 2, n: int = 100_000) -> float:
    rng = random.Random(seed)
    return statistics.pstdev([clipped(rng, loc, sd) for _ in range(n)])


def lower_bound(xs: list[float]) -> float:
    n = len(xs)
    return statistics.fmean(xs) - Z975 * statistics.stdev(xs) / math.sqrt(n)


def section_a() -> None:
    print("A. 95% CI half-width of mean R (normal approx) at n trades")
    for sd in (0.8, 1.0, 1.2, 1.5):
        row = ", ".join(f"n={n}: +/-{Z975 * sd / math.sqrt(n):.3f}R" for n in (100, 300, 600, 1000))
        print(f"   SD {sd:.1f}R -> {row}")
    for sd in (1.0, 1.2, 1.5):
        mde = (Z975 + NormalDist().inv_cdf(0.8)) * sd / math.sqrt(300)
        print(f"   minimum true mean R for 80% power at n=300, SD {sd}: {mde:.3f}R")
    print()


def section_b(rng: random.Random, sims: int) -> None:
    print("B. Power, single look at n=300 (independent trades), P(lower bound > 0)")
    for sd_pre in (1.0, 1.4):
        cells = []
        for mu in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30):
            loc = calibrate(mu, sd_pre)
            wins = sum(lower_bound([clipped(rng, loc, sd_pre) for _ in range(300)]) > 0
                       for _ in range(sims))
            cells.append(f"mu={mu:.2f}: {wins / sims:.3f}")
        print(f"   pre-clip SD {sd_pre} (realised SD ~{realised_sd(calibrate(0.0, sd_pre), sd_pre):.2f}R): "
              + ", ".join(cells))
    print()


def section_c(rng: random.Random, sims: int) -> None:
    print("C. Peeking at true mean R = 0 (false PASS rate; nominal one-sided 2.5%)")
    loc = calibrate(0.0, 1.2)
    single = peek_300 = peek_to_600 = 0
    for _ in range(sims):
        xs = [clipped(rng, loc, 1.2) for _ in range(600)]
        s1 = s2 = 0.0
        lb = {}
        for i, x in enumerate(xs, 1):
            s1 += x
            s2 += x * x
            if i >= 30 and i % 10 == 0:
                m = s1 / i
                var = (s2 - i * m * m) / (i - 1)
                lb[i] = m - Z975 * math.sqrt(max(var, 0.0) / i)
        if lb[300] > 0:
            single += 1
        # checks after every 10 trades from 30 to 300, PASS declared at the first LB>0
        if any(lb[n] > 0 for n in range(30, 301, 10)):
            peek_300 += 1
        # "INCONCLUSIVE, keep running": checks every 10 trades from 300 to 600
        if any(lb[n] > 0 for n in range(300, 601, 10)):
            peek_to_600 += 1
    print(f"   single look at n=300           : {single / sims:.3f}")
    print(f"   look every 10 trades, 30..300  : {peek_300 / sims:.3f}")
    print(f"   look every 10 trades, 300..600 : {peek_to_600 / sims:.3f}\n")


def cluster_bootstrap_lb(clusters: list[list[float]], rng: random.Random, b: int = 400) -> float:
    k = len(clusters)
    means = []
    for _ in range(b):
        tot = cnt = 0.0
        for _ in range(k):
            c = clusters[rng.randrange(k)]
            tot += sum(c)
            cnt += len(c)
        means.append(tot / cnt)
    means.sort()
    return means[int(0.025 * b)]


def section_d(rng: random.Random, sims: int) -> None:
    print("D. Clustering at true mean R = 0: n=300 trader-share trades in merged clusters")
    loc = calibrate(0.0, 1.2)
    for mean_extra, rho in ((0.0, 0.0), (0.5, 0.7), (1.0, 0.7), (1.0, 0.9)):
        naive = boot = 0
        runs = max(200, sims // 8)
        deff = []
        for _ in range(runs):
            clusters: list[list[float]] = []
            total = 0
            while total < 300:
                size = 1 + (rng.random() < mean_extra / (1 + mean_extra)) * (1 + int(rng.expovariate(1.0)))
                size = min(size, 300 - total)
                common = rng.gauss(0, 1)
                c = []
                for _ in range(size):
                    z = math.sqrt(rho) * common + math.sqrt(1 - rho) * rng.gauss(0, 1)
                    c.append(min(max(loc + 1.2 * z, LO), HI))
                clusters.append(c)
                total += size
            flat = [x for c in clusters for x in c]
            if lower_bound(flat) > 0:
                naive += 1
            if cluster_bootstrap_lb(clusters, rng) > 0:
                boot += 1
            deff.append(300 / len(clusters))
        print(f"   avg extra shares/cluster~{mean_extra:.1f}, within-cluster corr {rho:.1f}, "
              f"mean cluster size {statistics.fmean(deff):.2f}: naive false PASS {naive / runs:.3f}, "
              f"cluster-bootstrap false PASS {boot / runs:.3f}")
    print()


def expected_max_z(n: int) -> float:
    g = 0.5772156649
    nd = NormalDist()
    return (1 - g) * nd.inv_cdf(1 - 1 / n) + g * nd.inv_cdf(1 - 1 / (n * math.e))


def section_e() -> None:
    print("E. Luck: expected best z among N zero-skill traders (Bailey & Lopez de Prado SR0 multiplier)")
    for n in (10, 200, 2_000, 30_000):
        print(f"   N={n:>6}: E[max z] ~ {expected_max_z(n):.2f}  (sqrt(2 ln N) = {math.sqrt(2 * math.log(n)):.2f})")
    # what a 180-day daily Sharpe has to exceed
    t = 180
    for n in (200, 30_000):
        sr0 = expected_max_z(n) / math.sqrt(t)   # V[SR_hat] ~ 1/T under the null
        print(f"   N={n}, T={t} daily obs: SR0 ~ {sr0:.3f}/day ({sr0 * math.sqrt(365):.2f} annualised)")
    print()


def section_f() -> None:
    print("F. Mean R vs USD P&L with mirrored sizing (toy, deterministic)")
    trades = [(+0.5, 1.0)] * 6 + [(-1.0, 9.0)] * 1     # (R, initial risk in USD)
    mean_r = statistics.fmean(r for r, _ in trades)
    pnl = sum(r * risk for r, risk in trades)
    rw = pnl / sum(risk for _, risk in trades)
    print(f"   6 small winners +0.5R on $1 risk, 1 large loser -1R on $9 risk:")
    print(f"   mean R = {mean_r:+.3f}R, USD P&L = {pnl:+.2f}, risk-weighted mean R = {rw:+.3f}R\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    print("EXPLORATORY / SYNTHETIC. R model: clipped normal, not Hyperliquid data.\n")
    section_a()
    section_b(rng, a.sims)
    section_c(rng, a.sims)
    section_d(rng, a.sims)
    section_e()
    section_f()


if __name__ == "__main__":
    main()
