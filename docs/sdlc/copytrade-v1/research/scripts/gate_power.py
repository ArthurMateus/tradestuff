"""EXPLORATORY - SYNTHETIC - NOT VALIDATION.

gate_power.py v2 (2026-09-29). Revised after the backtest audit (BT-4, BT-5, BT-6, BT-7,
BT-11, BT-12).

Statistical properties of the FROZEN go-live gate (edge-hypothesis.md section 5.3):
  P2   lower bound (LB) of the two-sided CI of mean trade R > 0 over the first 300 OPENED trades,
       LB = min( iid t-interval,
                 UTC-day cluster percentile bootstrap,
                 UTC-day cluster-robust t-interval with G-1 degrees of freedom )
       where a trade's day is the UTC day of the first open of its merged position, so every
       share of a merged position is in one day cluster (day clusters nest position clusters).
       CI level: 96% in paper run 1, 99% in paper run 2 (alpha split; at most 2 runs).
  P2c  the same LB, computed on D_i = R_i - mean R of trade i's direction-matched random-time
       baseline replications, > 0.

Sections
  A. CI half-width and minimum detectable mean R at the 95% (reference), 96% and 99% levels.
  B. Power, single look at n=300, independent trades.
  C. Peeking at true mean R = 0 (unchanged model).
  D. Position clustering only: the v1 model, in which only the shares of one merged position are
     correlated. The v1 P2 rule was min(t, position-cluster bootstrap).
  D2. Cross-position correlation: a daily market factor times the trade direction (beta), with a
     long bias. It compares the v1 rule, each frozen-rule component, the frozen rule, and the
     frozen rule plus the baseline test P2c (BT-4, BT-7).
  E. Luck (unchanged).
  F. Mean R vs USD toy (unchanged).
  G. Alpha split across at most 2 paper runs (BT-5).
  H. Heavy tails, and the pre-registered fragility checks (BT-12).
Every simulated rate carries a Wilson 95% Monte Carlo interval in brackets (BT-11).

Correction to v1 (BT-4): the v1 docstring said section D covered "same-hour BTC-beta trades".
It did not. v1 correlated only the shares of one merged position, so its cluster-bootstrap
false-PASS figures (1.6-2.4%) do not cover beta or same-day correlation. Section D2 does.

Per-trade R model: Normal(loc, sd) clipped to [-1.05, +3.0] unless stated (H uses a heavy-tailed
mixture). All of this is assumption, not data. Stdlib only, fixed seed; results do not depend on --jobs.
Usage: python3 gate_power.py [--sims 4000] [--boot 1000] [--seed 23] [--jobs 4]
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
from functools import lru_cache
from multiprocessing import Pool
from statistics import NormalDist

LO, HI = -1.05, 3.0
N_TRADES = 300
LEVEL_RUN1, LEVEL_RUN2 = 0.96, 0.99
ND = NormalDist()


# ------------------------------------------------------------------ distributions
def clip(x: float) -> float:
    return min(max(x, LO), HI)


def clipped(rng: random.Random, loc: float, sd: float) -> float:
    return clip(rng.gauss(loc, sd))


@lru_cache(maxsize=None)
def calibrate(target: float, sd: float, seed: int = 1, n: int = 100_000) -> float:
    rng = random.Random(seed)
    zs = [rng.gauss(0, 1) for _ in range(n)]
    lo, hi = -2.0, 2.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if sum(clip(mid + sd * z) for z in zs) / n < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def realised_sd(loc: float, sd: float, seed: int = 2, n: int = 100_000) -> float:
    rng = random.Random(seed)
    return statistics.pstdev([clipped(rng, loc, sd) for _ in range(n)])


# ------------------------------------------------------------------ Student t (stdlib)
def _nz(v: float) -> float:
    return v if abs(v) > 1e-300 else 1e-300


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 / _nz(1.0 - qab * x / qap)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 / _nz(1.0 + aa * d)
        c = _nz(1.0 + aa / c)
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 / _nz(1.0 + aa * d)
        c = _nz(1.0 + aa / c)
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-14:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, nu: float) -> float:
    p = 0.5 * _betai(nu / 2.0, 0.5, nu / (nu + t * t))
    return 1.0 - p if t > 0 else p


@lru_cache(maxsize=None)
def t_ppf(q: float, nu: int) -> float:
    """Quantile of Student t for q > 0.5 (bisection on the CDF)."""
    lo, hi = 0.0, 1000.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_cdf(mid, nu) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def upper_q(level: float) -> float:
    return 1.0 - (1.0 - level) / 2.0


# ------------------------------------------------------------------ interval estimators
def lb_t(xs: list[float], level: float) -> float:
    n = len(xs)
    return statistics.fmean(xs) - t_ppf(upper_q(level), n - 1) * statistics.stdev(xs) / math.sqrt(n)


def cluster_sums(xs: list[float], keys: list[int]) -> tuple[list[float], list[int]]:
    s: dict[int, float] = {}
    c: dict[int, int] = {}
    for x, k in zip(xs, keys):
        s[k] = s.get(k, 0.0) + x
        c[k] = c.get(k, 0) + 1
    ks = sorted(s)
    return [s[k] for k in ks], [c[k] for k in ks]


def boot_lbs(sums: list[float], cnts: list[int], rng: random.Random, b: int,
             levels: tuple[float, ...]) -> dict[float, float]:
    """Percentile cluster bootstrap: resample whole clusters with replacement."""
    k = len(sums)
    r = range(k)
    gs, gc = sums.__getitem__, cnts.__getitem__
    means = []
    for _ in range(b):
        picks = rng.choices(r, k=k)
        means.append(sum(map(gs, picks)) / sum(map(gc, picks)))
    means.sort()
    return {lv: means[min(b - 1, int((1.0 - upper_q(lv)) * b))] for lv in levels}


def crt_lb(xs: list[float], keys: list[int], level: float) -> float:
    """Cluster-robust (CR1-type) t-interval with G-1 degrees of freedom."""
    n = len(xs)
    m = statistics.fmean(xs)
    acc: dict[int, float] = {}
    for x, k in zip(xs, keys):
        acc[k] = acc.get(k, 0.0) + (x - m)
    g = len(acc)
    if g < 2:
        return -math.inf
    v = g / (g - 1) * sum(s * s for s in acc.values()) / (n * n)
    return m - t_ppf(upper_q(level), g - 1) * math.sqrt(v)


def frozen_lb(xs: list[float], days: list[int], rng: random.Random, b: int, level: float) -> float:
    s, c = cluster_sums(xs, days)
    return min(lb_t(xs, level), boot_lbs(s, c, rng, b, (level,))[level], crt_lb(xs, days, level))


def wilson(k: int, n: int, z: float = 1.959964) -> str:
    if n == 0:
        return "n/a"
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return f"{p:.3f} [{max(0.0, centre - half):.3f}, {min(1.0, centre + half):.3f}]"


# ------------------------------------------------------------------ A
def section_a() -> list[str]:
    out = ["A. CI half-width of mean R at n=300 (normal approx) and minimum mean R for 80% power"]
    for lv in (0.95, LEVEL_RUN1, LEVEL_RUN2):
        z = ND.inv_cdf(upper_q(lv))
        hw = ", ".join(f"SD {sd}: +/-{z * sd / math.sqrt(N_TRADES):.3f}R" for sd in (1.0, 1.2, 1.5))
        mde = ", ".join(f"SD {sd}: {(z + ND.inv_cdf(0.8)) * sd / math.sqrt(N_TRADES):.3f}R"
                        for sd in (1.0, 1.2, 1.5))
        out.append(f"   level {lv:.0%}: half-width {hw}")
        out.append(f"              80%-power mean R {mde}")
    return out + [""]


# ------------------------------------------------------------------ B
def cell_b(args: tuple) -> str:
    sd_pre, mu, sims, seed = args
    rng = random.Random(seed)
    loc = calibrate(mu, sd_pre)
    k = {0.95: 0, LEVEL_RUN1: 0, LEVEL_RUN2: 0}
    for _ in range(sims):
        xs = [clipped(rng, loc, sd_pre) for _ in range(N_TRADES)]
        for lv in k:
            k[lv] += lb_t(xs, lv) > 0
    return (f"   pre-clip SD {sd_pre} mu={mu:+.2f}: 95% {wilson(k[0.95], sims)}  "
            f"96% {wilson(k[LEVEL_RUN1], sims)}  99% {wilson(k[LEVEL_RUN2], sims)}")


# ------------------------------------------------------------------ C
def cell_c(args: tuple) -> str:
    sims, seed = args
    rng = random.Random(seed)
    loc = calibrate(0.0, 1.2)
    z = ND.inv_cdf(0.975)
    single = peek_300 = peek_to_600 = 0
    for _ in range(sims):
        s1 = s2 = 0.0
        lb = {}
        for i in range(1, 601):
            x = clipped(rng, loc, 1.2)
            s1 += x
            s2 += x * x
            if i >= 30 and i % 10 == 0:
                m = s1 / i
                var = (s2 - i * m * m) / (i - 1)
                lb[i] = m - z * math.sqrt(max(var, 0.0) / i)
        single += lb[300] > 0
        peek_300 += any(lb[n] > 0 for n in range(30, 301, 10))
        peek_to_600 += any(lb[n] > 0 for n in range(300, 601, 10))
    return (f"   single look at n=300           : {wilson(single, sims)}\n"
            f"   look every 10 trades, 30..300  : {wilson(peek_300, sims)}\n"
            f"   look every 10 trades, 300..600 : {wilson(peek_to_600, sims)}")


# ------------------------------------------------------------------ trade generator (D, D2, G)
def gen_trades(rng: random.Random, loc: float, sd: float, rho_d: float, p_long: float,
               mean_extra: float, rho_p: float, days: int) -> tuple[list[float], list[int], list[int], list[int], list[float]]:
    """Merged positions of 1+ trader shares. Each position has a UTC day, a direction s and a
    position factor P; each day has a market factor F. Share R = loc + sd * z, clipped, with
    z = sqrt(rho_d) s F_day + sqrt(rho_p (1-rho_d)) P + sqrt((1-rho_p)(1-rho_d)) e, so Var z = 1."""
    f = [rng.gauss(0, 1) for _ in range(days)]
    a_d = math.sqrt(rho_d)
    a_p = math.sqrt(rho_p * (1 - rho_d))
    a_e = math.sqrt((1 - rho_p) * (1 - rho_d))
    rs, ds, ps, ss = [], [], [], []
    pid = 0
    while len(rs) < N_TRADES:
        day = rng.randrange(days)
        s = 1 if rng.random() < p_long else -1
        size = 1 + (rng.random() < mean_extra / (1 + mean_extra)) * (1 + int(rng.expovariate(1.0)))
        size = min(size, N_TRADES - len(rs))
        p = rng.gauss(0, 1)
        for _ in range(size):
            z = a_d * s * f[day] + a_p * p + a_e * rng.gauss(0, 1)
            rs.append(clip(loc + sd * z))
            ds.append(day)
            ps.append(pid)
            ss.append(s)
        pid += 1
    return rs, ds, ps, ss, f


def baseline_means(rng: random.Random, loc0: float, sd: float, rho_d: float, ss: list[int],
                   f: list[float], k: int = 20) -> list[float]:
    """Direction-matched, random-time baseline: same direction, a uniformly random day of the
    evaluation window, zero skill (loc0). Mean of k replications per trade."""
    a_d, a_e = math.sqrt(rho_d), math.sqrt(1 - rho_d)
    days = len(f)
    out = []
    for s in ss:
        acc = 0.0
        for _ in range(k):
            acc += clip(loc0 + sd * (a_d * s * f[rng.randrange(days)] + a_e * rng.gauss(0, 1)))
        out.append(acc / k)
    return out


# ------------------------------------------------------------------ D (v1 model)
def cell_d(args: tuple) -> str:
    mean_extra, rho, sims, b, seed = args
    rng = random.Random(seed)
    loc = calibrate(0.0, 1.2)
    naive = boot = 0
    sizes = []
    for _ in range(sims):
        rs, _ds, ps, _ss, _f = gen_trades(rng, loc, 1.2, 0.0, 0.5, mean_extra, rho, 30)
        naive += lb_t(rs, 0.95) > 0
        s, c = cluster_sums(rs, ps)
        boot += min(lb_t(rs, 0.95), boot_lbs(s, c, rng, b, (0.95,))[0.95]) > 0
        sizes.append(N_TRADES / len(s))
    return (f"   extra shares~{mean_extra:.1f}, within-position corr {rho:.1f}, mean cluster size "
            f"{statistics.fmean(sizes):.2f}: naive t {wilson(naive, sims)}; v1 rule min(t, position "
            f"bootstrap) {wilson(boot, sims)}")


# ------------------------------------------------------------------ D2 (day factor / beta)
def cell_d2(args: tuple) -> str:
    rho_d, p_long, mu, sims, b, seed = args
    rng = random.Random(seed)
    loc0, loc = calibrate(0.0, 1.2), calibrate(mu, 1.2)
    k = dict.fromkeys(["naive95", "v1_rule95", "day_boot96", "day_crt96", "frozen96", "frozen99",
                       "frozen96_and_baseline"], 0)
    g_sizes = []
    for _ in range(sims):
        rs, ds, ps, ss, f = gen_trades(rng, loc, 1.2, rho_d, p_long, 0.5, 0.5, 30)
        t95 = lb_t(rs, 0.95)
        k["naive95"] += t95 > 0
        s, c = cluster_sums(rs, ps)
        k["v1_rule95"] += min(t95, boot_lbs(s, c, rng, b, (0.95,))[0.95]) > 0
        s, c = cluster_sums(rs, ds)
        g_sizes.append(len(s))
        bl = boot_lbs(s, c, rng, b, (LEVEL_RUN1, LEVEL_RUN2))
        c96, c99 = crt_lb(rs, ds, LEVEL_RUN1), crt_lb(rs, ds, LEVEL_RUN2)
        k["day_boot96"] += bl[LEVEL_RUN1] > 0
        k["day_crt96"] += c96 > 0
        f96 = min(lb_t(rs, LEVEL_RUN1), bl[LEVEL_RUN1], c96) > 0
        k["frozen96"] += f96
        k["frozen99"] += min(lb_t(rs, LEVEL_RUN2), bl[LEVEL_RUN2], c99) > 0
        if f96:
            base = baseline_means(rng, loc0, 1.2, rho_d, ss, f)
            dd = [r - x for r, x in zip(rs, base)]
            k["frozen96_and_baseline"] += frozen_lb(dd, ds, rng, b, LEVEL_RUN1) > 0
    head = (f"   day-factor corr {rho_d:.1f}, long share {p_long:.0%}, true mean R {mu:+.2f} "
            f"(~{statistics.fmean(g_sizes):.0f} day clusters):")
    body = "\n".join(f"      {name:<24} {wilson(v, sims)}" for name, v in k.items())
    return head + "\n" + body


# ------------------------------------------------------------------ G (alpha split)
def cell_g(args: tuple) -> str:
    mu, sims, seed = args
    rng = random.Random(seed)
    loc = calibrate(mu, 1.2)
    r1 = both = no_split = 0
    for _ in range(sims):
        x1 = [clipped(rng, loc, 1.2) for _ in range(N_TRADES)]
        x2 = [clipped(rng, loc, 1.2) for _ in range(N_TRADES)]
        p1 = lb_t(x1, LEVEL_RUN1) > 0
        r1 += p1
        both += p1 or lb_t(x2, LEVEL_RUN2) > 0
        no_split += lb_t(x1, 0.95) > 0 or lb_t(x2, 0.95) > 0
    return (f"   true mean R {mu:+.2f}: PASS in run 1 (96%) {wilson(r1, sims)}; PASS within 2 runs "
            f"(96% then 99%) {wilson(both, sims)}; for contrast, 2 runs at 95% each {wilson(no_split, sims)}")


# ------------------------------------------------------------------ H (heavy tails, fragility)
TAIL_LOSS_P, TAIL_WIN_P = 0.06, 0.06


def heavy_draw(rng: random.Random, loc: float) -> float:
    """Mixture: 88% clipped Normal(loc, 1.0); 6% gap-through or add-inflated losses
    U(-2.5, -1.05)R; 6% add-inflated or untaken-TP wins 3 x Pareto(1.8), capped at 12R."""
    u = rng.random()
    if u < TAIL_LOSS_P:
        return rng.uniform(-2.5, LO)
    if u < TAIL_LOSS_P + TAIL_WIN_P:
        return min(3.0 * rng.paretovariate(1.8), 12.0)
    return clip(rng.gauss(loc, 1.0))


@lru_cache(maxsize=None)
def heavy_loc(target: float) -> float:
    rng = random.Random(5)
    n = 200_000
    tail = sum(min(3.0 * rng.paretovariate(1.8), 12.0) for _ in range(n)) / n * TAIL_WIN_P \
        + (-2.5 + LO) / 2 * TAIL_LOSS_P
    core_target = (target - tail) / (1 - TAIL_LOSS_P - TAIL_WIN_P)
    return calibrate(core_target, 1.0)


def fragility_flags(xs: list[float], leaders: list[int]) -> tuple[bool, bool]:
    top5 = sorted(xs)[:-5]
    tot: dict[int, float] = {}
    for x, ld in zip(xs, leaders):
        tot[ld] = tot.get(ld, 0.0) + x
    best = max(tot, key=lambda ld: (tot[ld], -ld))
    rest = [x for x, ld in zip(xs, leaders) if ld != best]
    return statistics.fmean(top5) <= 0, (not rest) or statistics.fmean(rest) <= 0


ZIPF9 = [1 / k for k in range(1, 10)]


def cell_h(args: tuple) -> str:
    model, mu, sims, seed = args
    rng = random.Random(seed)
    if model == "concentrated":
        w1 = ZIPF9[0] / sum(ZIPF9)
        loc_star, loc_rest = heavy_loc(mu / w1), heavy_loc(0.0)
    else:
        loc_star = loc_rest = heavy_loc(mu) if model == "heavy" else calibrate(mu, 1.0)
    passes = flag_top5 = flag_leader = flag_any = 0
    sds = []
    for _ in range(sims):
        leaders = rng.choices(range(9), weights=ZIPF9, k=N_TRADES)
        if model == "normal":
            xs = [clipped(rng, loc_rest, 1.0) for _ in leaders]
        else:
            xs = [heavy_draw(rng, loc_star if ld == 0 else loc_rest) for ld in leaders]
        sds.append(statistics.stdev(xs))
        if lb_t(xs, LEVEL_RUN1) > 0:
            passes += 1
            a, bb = fragility_flags(xs, leaders)
            flag_top5 += a
            flag_leader += bb
            flag_any += a or bb
    return (f"   {model:<12} mu={mu:+.2f} (realised SD ~{statistics.fmean(sds):.2f}R): P(LB96 > 0) "
            f"{wilson(passes, sims)}; given a pass, fragile without top-5 trades {wilson(flag_top5, passes)}, "
            f"without best leader {wilson(flag_leader, passes)}, either {wilson(flag_any, passes)}")


# ------------------------------------------------------------------ E, F (deterministic)
def expected_max_z(n: int) -> float:
    g = 0.5772156649
    return (1 - g) * ND.inv_cdf(1 - 1 / n) + g * ND.inv_cdf(1 - 1 / (n * math.e))


def section_e() -> list[str]:
    out = ["E. Luck: expected best z among N zero-skill traders (Bailey & Lopez de Prado SR0 multiplier)"]
    for n in (10, 200, 2_000, 30_000):
        out.append(f"   N={n:>6}: E[max z] ~ {expected_max_z(n):.2f}  (sqrt(2 ln N) = {math.sqrt(2 * math.log(n)):.2f})")
    for n in (200, 30_000):
        for t in (30, 180):
            sr0 = expected_max_z(n) / math.sqrt(t)
            out.append(f"   N={n}, T={t} daily obs: SR0 ~ {sr0:.3f}/day ({sr0 * math.sqrt(365):.2f} annualised)")
    return out + [""]


def section_f() -> list[str]:
    trades = [(+0.5, 1.0)] * 6 + [(-1.0, 9.0)] * 1
    mean_r = statistics.fmean(r for r, _ in trades)
    pnl = sum(r * risk for r, risk in trades)
    rw = pnl / sum(risk for _, risk in trades)
    return ["F. Mean R vs USD P&L with mirrored sizing (toy, deterministic)",
            "   6 small winners +0.5R on $1 risk, 1 large loser -1R on $9 risk:",
            f"   mean R = {mean_r:+.3f}R, USD P&L = {pnl:+.2f}, risk-weighted mean R = {rw:+.3f}R", ""]


# ------------------------------------------------------------------ driver
def run_cell(task: tuple) -> str:
    fn, args = task
    return {"b": cell_b, "c": cell_c, "d": cell_d, "d2": cell_d2, "g": cell_g, "h": cell_h}[fn](args)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=4000)
    ap.add_argument("--boot", type=int, default=1000, help="bootstrap resamples inside each simulated run")
    ap.add_argument("--seed", type=int, default=23)
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    sims, b = a.sims, a.boot
    seq = iter(range(1, 10_000))

    def sd(i: int) -> int:                    # deterministic per-cell seed
        return a.seed * 100_003 + i

    tasks: list[tuple[str, list[tuple]]] = []
    tasks.append(("B. Power, single look at n=300 (independent trades), P(LB > 0) at the 95% / 96% / 99% levels",
                  [("b", (sp, mu, sims, sd(next(seq)))) for sp in (1.0, 1.4)
                   for mu in (0.0, 0.05, 0.10, 0.15, 0.20)]))
    tasks.append(("C. Peeking at true mean R = 0 (95% t-interval; false PASS, nominal one-sided 2.5%)",
                  [("c", (sims, sd(next(seq))))]))
    tasks.append(("D. v1 model: only shares of one merged position correlated; true mean R = 0 (false PASS)",
                  [("d", (me, rho, sims // 2, b, sd(next(seq))))
                   for me, rho in ((0.0, 0.0), (0.5, 0.7), (1.0, 0.7), (1.0, 0.9))]))
    tasks.append(("D2. Daily market factor x direction (beta) + merged positions (extra shares ~0.5, "
                  "within-position corr 0.5), 30 days. Rows: share of runs with LB > 0",
                  [("d2", (rd, pl, mu, sims, b, sd(next(seq))))
                   for mu in (0.0, 0.10)
                   for rd, pl in ((0.0, 0.5), (0.2, 0.7), (0.3, 0.8), (0.5, 0.8))]))
    tasks.append(("G. Alpha split across at most 2 paper runs (independent trades, pre-clip SD 1.2)",
                  [("g", (mu, sims, sd(next(seq)))) for mu in (0.0, 0.05, 0.10, 0.15)]))
    tasks.append(("H. Heavy tails and fragility checks (9 leaders, Zipf trade shares; LB = iid t at 96%)",
                  [("h", (model, mu, sims, sd(next(seq))))
                   for model, mu in (("normal", 0.0), ("normal", 0.10), ("heavy", 0.0), ("heavy", 0.05),
                                     ("heavy", 0.10), ("heavy", 0.15), ("concentrated", 0.10))]))
    flat = [t for _, cells in tasks for t in cells]
    if a.jobs > 1:
        with Pool(a.jobs) as pool:
            results = pool.map(run_cell, flat, chunksize=1)
    else:
        results = [run_cell(t) for t in flat]

    print("EXPLORATORY / SYNTHETIC. R model: clipped normal unless stated, not Hyperliquid data.")
    print(f"sims per cell {sims} (D: {sims // 2}), bootstrap resamples {b}, seed {a.seed}. "
          "Brackets: Wilson 95% Monte Carlo interval.\n")
    print("\n".join(section_a()))
    i = 0
    for title, cells in tasks:
        print(title)
        for _ in cells:
            print(results[i])
            i += 1
        print()
    print("\n".join(section_e()))
    print("\n".join(section_f()))


if __name__ == "__main__":
    main()
