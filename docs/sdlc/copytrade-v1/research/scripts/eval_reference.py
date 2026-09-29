"""EXPLORATORY - REFERENCE IMPLEMENTATION OF THE FROZEN EVALUATION KEYS - NOT PRODUCTION CODE (E13).

edge-hypothesis.md addendum A1 (BT2-3) pins every choice the verdict depends on. This file
implements exactly that text so that the test designer, the developer and the backtest-auditor
can check an implementation against fixed test vectors. If this file and the addendum text
disagree, the addendum text wins and this file is a bug.

  * rng_uint(): SHA-256 counter RNG with rejection sampling (no modulo bias), language-independent
  * cluster bootstrap: resample G day clusters with replacement; statistic = pooled trade mean
    (sum of picked cluster sums / sum of picked cluster sizes); percentile index in integers
  * iid t, cluster-robust t (G-1 df), LB_r = min, UB_r = max, compared after rounding to 1e-6
  * merged positions: connected components (transitive) of same-coin same-direction trades with
    overlapping closed intervals [entry, min(close, T_eval)]; day cluster = UTC day of the
    component's first entry
  * B0d start-time draw over an admissible set of half-open ms intervals
  * the /flatten gate rule: min(realised R, shadow R under the frozen exits)
  * verdict precedence
Usage (from this folder): python3 eval_reference.py > ../../../../../research/data/eval_reference_vectors.txt
Stdlib only. Imports the Student-t quantile from gate_power.py.
"""
from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from gate_power import t_ppf

DAY_MS = 86_400_000
TAG_BOOT_R, TAG_BOOT_D, TAG_B0D = "bootR", "bootD", "b0d"


# ------------------------------------------------------------------ RNG (A1.3 c)
def rng_uint(seed: bytes, tag: str, counters: tuple[int, ...], n: int) -> int:
    """Uniform integer in [0, n). Block k = SHA-256(seed || tag || 0x00 || counters as uint32
    big-endian || k as uint32 big-endian); x = first 8 bytes as uint64 big-endian; accept when
    x < floor(2^64 / n) * n and return x mod n, else k += 1."""
    if not 0 < n < 2 ** 64:
        raise ValueError("n out of range")
    limit = (2 ** 64 // n) * n
    prefix = seed + tag.encode("ascii") + b"\x00" + b"".join(c.to_bytes(4, "big") for c in counters)
    k = 0
    while True:
        x = int.from_bytes(hashlib.sha256(prefix + k.to_bytes(4, "big")).digest()[:8], "big")
        if x < limit:
            return x % n
        k += 1


# ------------------------------------------------------------------ intervals (A1.3 a, b)
def upper_q(level_pct: int) -> float:
    return 1.0 - (100 - level_pct) / 200.0


def pct_index(b: int, level_pct: int) -> int:
    """0-based index of the lower percentile in the ascending sort; the upper is b - 1 - index."""
    return (b * (100 - level_pct)) // 200


def cluster_sums(xs: list[float], keys: list[int]) -> tuple[list[int], list[float], list[int]]:
    ks = sorted(set(keys))
    s = {k: 0.0 for k in ks}
    c = {k: 0 for k in ks}
    for x, k in zip(xs, keys):
        s[k] += x
        c[k] += 1
    return ks, [s[k] for k in ks], [c[k] for k in ks]


def boot_ci(xs: list[float], keys: list[int], seed: bytes, tag: str, b: int, level_pct: int) -> tuple[float, float]:
    _ks, sums, cnts = cluster_sums(xs, keys)
    g = len(sums)
    means = []
    for r in range(b):
        tot = 0.0
        n = 0
        for j in range(g):
            p = rng_uint(seed, tag, (r, j), g)
            tot += sums[p]
            n += cnts[p]
        means.append(tot / n)
    means.sort()
    i = pct_index(b, level_pct)
    return means[i], means[b - 1 - i]


def t_ci(xs: list[float], level_pct: int) -> tuple[float, float]:
    n = len(xs)
    m = statistics.fmean(xs)
    h = t_ppf(upper_q(level_pct), n - 1) * statistics.stdev(xs) / math.sqrt(n)
    return m - h, m + h


def crt_ci(xs: list[float], keys: list[int], level_pct: int) -> tuple[float, float]:
    n = len(xs)
    m = statistics.fmean(xs)
    acc: dict[int, float] = {}
    for x, k in zip(xs, keys):
        acc[k] = acc.get(k, 0.0) + (x - m)
    g = len(acc)
    if g < 2:
        return -math.inf, math.inf
    v = g / (g - 1) * sum(s * s for s in acc.values()) / (n * n)
    h = t_ppf(upper_q(level_pct), g - 1) * math.sqrt(v)
    return m - h, m + h


def r6(x: float) -> Decimal:
    """Gate comparisons use values rounded half-even to 1e-6 R (A1.3 a)."""
    if math.isinf(x):
        return Decimal("-Infinity") if x < 0 else Decimal("Infinity")
    return Decimal(repr(x)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)


def lb_ub(xs: list[float], keys: list[int], seed: bytes, tag: str, b: int, level_pct: int) -> dict:
    t = t_ci(xs, level_pct)
    bt = boot_ci(xs, keys, seed, tag, b, level_pct)
    cr = crt_ci(xs, keys, level_pct)
    return {"t": t, "boot": bt, "crt": cr, "LB": r6(min(t[0], bt[0], cr[0])), "UB": r6(max(t[1], bt[1], cr[1]))}


# ------------------------------------------------------------------ merged positions (A1.3 d)
@dataclass
class Trade:
    tid: str
    coin: str
    direction: int
    entry_ms: int
    close_ms: int | None          # None = still open at T_eval (marked)


def day_clusters(trades: list[Trade], t_eval: int) -> dict[str, int]:
    """trade id -> UTC day number of its merged position's first entry. Components of the
    interval-overlap graph within (coin, direction); closed intervals, so touching counts."""
    out: dict[str, int] = {}
    groups: dict[tuple[str, int], list[Trade]] = {}
    for tr in trades:
        groups.setdefault((tr.coin, tr.direction), []).append(tr)
    for grp in groups.values():
        grp.sort(key=lambda x: (x.entry_ms, x.tid))
        comp: list[Trade] = []
        reach = None
        for tr in grp:
            end = t_eval if tr.close_ms is None else min(tr.close_ms, t_eval)
            if comp and tr.entry_ms <= reach:
                comp.append(tr)
                reach = max(reach, end)
                continue
            for x in comp:
                out[x.tid] = comp[0].entry_ms // DAY_MS
            comp, reach = [tr], end
        for x in comp:
            out[x.tid] = comp[0].entry_ms // DAY_MS
    return out


# ------------------------------------------------------------------ B0d start time (A1.1, A1.3 g)
def b0d_start(seed: bytes, trade_index: int, rep: int, admissible: list[tuple[int, int]]) -> int | None:
    """Uniform ms start time over sorted, disjoint half-open intervals [a, b); None if empty."""
    total = sum(b - a for a, b in admissible)
    if total <= 0:
        return None
    u = rng_uint(seed, TAG_B0D, (trade_index, rep), total)
    for a, b in admissible:
        if u < b - a:
            return a + u
        u -= b - a
    raise AssertionError("unreachable")


def d_value(r: float, reps: list[float] | None) -> float:
    """D_i = R_i - mean of the replications; with no admissible window, min(R_i, 0) (A1.3 g)."""
    return min(r, 0.0) if not reps else r - statistics.fmean(reps)


def gate_r_flattened(realised_r: float, shadow_r: float) -> float:
    """A trade closed by /flatten counts with the worse of its realised R and the R the frozen
    exits would have produced on the recorded data (A1.3 f)."""
    return min(realised_r, shadow_r)


# ------------------------------------------------------------------ verdict precedence (A1.3)
def verdict(*, aborted: bool, f1: bool, f2: bool, n_opened: int, g: int,
            lb_r: Decimal, ub_r: Decimal, usd_pnl_positive: bool, lb_d: Decimal,
            baseline_missing_share: float, p5: bool, p6: bool) -> str:
    """aborted: an ABORTED event ended the run before any F1/F2 and before T_eval, or the
    backtest-auditor voided the run (that ruling overrides FAIL; it can never produce PASS).
    f1 / f2: the breach happened before T_eval and before any ABORTED event (the run ended there)."""
    if aborted:
        return "ABORTED"
    if f1 or f2:
        return "FAIL"
    if n_opened < 300:
        return "INCONCLUSIVE"
    if g < 5:
        return "INCONCLUSIVE"
    if ub_r <= 0:
        return "FAIL"
    p2c = lb_d > 0 and baseline_missing_share <= 0.10
    if lb_r > 0 and usd_pnl_positive and p2c and p5 and p6:
        return "PASS"
    return "INCONCLUSIVE"


# ------------------------------------------------------------------ self-test and test vectors
def main() -> None:
    seed = hashlib.sha256(b"tradestuff copytrade-v1 A1 test vector").digest()
    lines = ["EXPLORATORY reference implementation of the frozen evaluation keys (addendum A1). Test vectors.",
             f"seed (hex) = {seed.hex()}"]

    # RNG
    first = [rng_uint(seed, TAG_BOOT_R, (0, j), 6) for j in range(10)]
    lines.append(f"rng_uint(seed, 'bootR', (0, j), 6) for j = 0..9: {first}")
    assert first == [rng_uint(seed, TAG_BOOT_R, (0, j), 6) for j in range(10)]          # deterministic
    assert rng_uint(seed, TAG_BOOT_D, (0, 0), 6) is not None
    assert all(0 <= rng_uint(seed, "x", (i,), 7) < 7 for i in range(200))

    # percentile index
    assert (pct_index(10_000, 96), pct_index(10_000, 99)) == (200, 50)
    assert pct_index(1_000, 96) == 20 and pct_index(1_000, 99) == 5
    lines.append("pct_index(B=10000): 96% -> lower 200, upper 9799; 99% -> lower 50, upper 9949")

    # merged positions, transitivity, marked trade
    h = 3_600_000
    d0 = 20_000 * DAY_MS
    tr = [Trade("A", "BTC", 1, d0 + 22 * h, d0 + 25 * h),          # day d0, ends next day 01:00
          Trade("B", "BTC", 1, d0 + 24 * h + 30 * 60_000, d0 + 30 * h),   # overlaps A (next day)
          Trade("C", "BTC", 1, d0 + 29 * h, d0 + 31 * h),          # overlaps B, not A -> same component
          Trade("D", "BTC", -1, d0 + 29 * h, d0 + 31 * h),         # other direction -> own component
          Trade("E", "BTC", 1, d0 + 31 * h, None),                 # touches C at 31h -> same component
          Trade("F", "ETH", 1, d0 + 26 * h, d0 + 27 * h)]
    dc = day_clusters(tr, t_eval=d0 + 40 * h)
    assert dc["A"] == dc["B"] == dc["C"] == dc["E"] == 20_000, dc
    assert dc["D"] == 20_001 and dc["F"] == 20_001, dc
    lines.append(f"day_clusters example (A..F): {dc}")

    # CI on a toy sample: 30 trades on 6 days
    xs = [0.8, -1.0, 0.3, 1.9, -1.0, 0.1, -0.4, 2.5, -1.0, 0.6, 0.2, -1.0, 1.1, -0.2, 0.9,
          -1.0, 0.4, 3.0, -0.7, -1.0, 0.5, 1.4, -1.0, 0.0, -0.3, 2.2, -1.0, 0.7, -0.6, 1.0]
    keys = [k // 5 for k in range(30)]
    for lv in (96, 99):
        res = lb_ub(xs, keys, seed, TAG_BOOT_R, 10_000, lv)
        fmt = lambda p: f"({p[0]:.6f}, {p[1]:.6f})"          # noqa: E731
        lines.append(f"toy sample, level {lv}%: t {fmt(res['t'])}  boot {fmt(res['boot'])}  "
                     f"crt {fmt(res['crt'])}  LB_r {res['LB']}  UB_r {res['UB']}")
        assert res["LB"] == min(r6(res["t"][0]), r6(res["boot"][0]), r6(res["crt"][0]))
        again = lb_ub(xs, keys, seed, TAG_BOOT_R, 10_000, lv)
        assert again["LB"] == res["LB"] and again["UB"] == res["UB"]                    # deterministic

    # B0d draw
    adm = [(1_000, 1_010), (5_000, 5_005)]
    draws = [b0d_start(seed, 7, rep, adm) for rep in range(8)]
    assert all(1_000 <= x < 1_010 or 5_000 <= x < 5_005 for x in draws)
    assert b0d_start(seed, 7, 0, []) is None
    lines.append(f"b0d_start(seed, trade 7, rep 0..7, [[1000,1010),[5000,5005)]): {draws}")
    assert d_value(0.5, None) == 0.0 and d_value(-0.4, []) == -0.4 and d_value(0.5, [0.1, 0.3]) == 0.3
    assert gate_r_flattened(1.2, 0.4) == 0.4 and gate_r_flattened(-0.5, 0.3) == -0.5

    # verdict precedence
    base = dict(aborted=False, f1=False, f2=False, n_opened=300, g=12,
                lb_r=Decimal("0.01"), ub_r=Decimal("0.3"), usd_pnl_positive=True, lb_d=Decimal("0.02"),
                baseline_missing_share=0.0, p5=True, p6=True)
    v = lambda **k: verdict(**{**base, **k})                 # noqa: E731
    assert v() == "PASS"
    assert v(aborted=True, f1=True) == "ABORTED"
    assert v(f1=True) == "FAIL" and v(f2=True, n_opened=120) == "FAIL"
    assert v(n_opened=299, ub_r=Decimal("-1")) == "INCONCLUSIVE"
    assert v(g=4, ub_r=Decimal("-0.5")) == "INCONCLUSIVE"                  # G < 5 before F3
    assert v(ub_r=Decimal("0")) == "FAIL" and v(ub_r=Decimal("0.000000")) == "FAIL"
    assert v(lb_r=Decimal("0.000000")) == "INCONCLUSIVE"                 # rounded 0 is not > 0
    assert v(lb_d=Decimal("-0.01")) == "INCONCLUSIVE"
    assert v(baseline_missing_share=0.11) == "INCONCLUSIVE"
    assert v(usd_pnl_positive=False) == "INCONCLUSIVE" and v(p5=False) == "INCONCLUSIVE" and v(p6=False) == "INCONCLUSIVE"
    lines.append("verdict precedence: ABORTED > F1/F2 > P1 incomplete > G < 5 > F3 > PASS > INCONCLUSIVE (asserted)")
    lines.append("selftest OK")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
