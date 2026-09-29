"""EXPLORATORY - REFERENCE IMPLEMENTATION OF THE FROZEN EVALUATION KEYS - NOT PRODUCTION CODE (E14).

v2 (2026-09-29, addendum A2; supersedes the E13 version). edge-hypothesis.md addenda A1 (BT2-3)
and A2 (BT3-1, BT3-3, BT3-7) pin every choice the verdict depends on. This file implements
exactly that text so that the test designer, the developer and the backtest-auditor can check an
implementation against fixed test vectors. If this file and the addendum text disagree, the
addendum text wins and this file is a bug. Section labels below cite edge-hypothesis.md 5.3 / 6.2
and the addendum item that fixed each rule.

  * rng_uint(): SHA-256 counter RNG with rejection sampling (no modulo bias), language-independent.
    The seed is the 32 RAW bytes decoded from the run record's hex string, never the hex text.
  * cluster bootstrap: resample G day clusters with replacement; statistic = pooled trade mean
    (sum of picked cluster sums / sum of picked cluster sizes); percentile index in integers
  * iid t, cluster-robust t (G-1 df), LB_r = min, UB_r = max, compared after rounding to 1e-6
  * merged positions: connected components (transitive) of same-coin same-direction trades with
    overlapping closed intervals [entry, min(close, T_eval)]; day cluster = UTC day of the
    component's first entry. For a /flatten-ed trade, "close" is its SHADOW exit (A2.1).
  * T_eval = min(last evaluation close in S, t300 + 7 d), with shadow exits for flattened trades;
    hold_i = min(evaluation close, T_eval) - entry (A2.1)
  * B0d start-time draw over an admissible set of half-open ms intervals
  * D_i: R_i - mean(B0d reps); without an admissible window min(R_i, 0, R_i - B_partial) (A2.3 a)
  * the /flatten gate rule: min(realised R, shadow R under the frozen exits)
  * verdict precedence
  * golden asserts: every printed vector is asserted against its expected literal value (A2.7)
Usage (from this folder): python3 eval_reference.py > ../../../../../research/data/eval_reference_vectors.txt
Stdlib only. Imports the Student-t quantile from gate_power.py. Runs in about 5 s.
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


# ------------------------------------------------------------------ RNG (5.3 "Bootstrap, exact", A1.3 b; A2.7)
def rng_uint(seed: bytes, tag: str, counters: tuple[int, ...], n: int) -> int:
    """Uniform integer in [0, n). Block k = SHA-256(seed || tag || 0x00 || counters as uint32
    big-endian || k as uint32 big-endian); x = first 8 bytes as uint64 big-endian; accept when
    x < floor(2^64 / n) * n and return x mod n, else k += 1. seed = 32 raw bytes (A2.7)."""
    if len(seed) != 32:
        raise ValueError("seed must be the 32 raw bytes, not the hex text")
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


# ------------------------------------------------------------------ intervals (5.3 LB_r / UB_r; bootstrap A1.3 b)
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
    """Gate comparisons use values rounded half-even to 1e-6 R (A1.3 b)."""
    if math.isinf(x):
        return Decimal("-Infinity") if x < 0 else Decimal("Infinity")
    return Decimal(repr(x)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)


def lb_ub(xs: list[float], keys: list[int], seed: bytes, tag: str, b: int, level_pct: int) -> dict:
    t = t_ci(xs, level_pct)
    bt = boot_ci(xs, keys, seed, tag, b, level_pct)
    cr = crt_ci(xs, keys, level_pct)
    return {"t": t, "boot": bt, "crt": cr, "LB": r6(min(t[0], bt[0], cr[0])), "UB": r6(max(t[1], bt[1], cr[1]))}


# ------------------------------------------------------------------ merged positions (A1.3 c), T_eval and hold (A1.3 f, A2.1)
@dataclass
class Trade:
    tid: str
    coin: str
    direction: int
    entry_ms: int
    close_ms: int | None          # None = still open (marked if still open at t300 + 7 d)
    flattened: bool = False       # closed by /flatten (A1.3 d)
    shadow_close_ms: int | None = None   # flattened only: shadow exit; None = shadow still open


def eval_close_ms(tr: Trade) -> int | None:
    """The close used for T_eval, hold_i, merged positions, B0d and P3 (A2.1): the shadow exit
    for a flattened trade, the real full close otherwise. None = still open."""
    return tr.shadow_close_ms if tr.flattened else tr.close_ms


def t_eval_ms(trades_in_s: list[Trade], t300_ms: int) -> int:
    """T_eval = min(last evaluation close in S, t300 + 7 days) (5.3, A2.1)."""
    cap = t300_ms + 7 * DAY_MS
    closes = [eval_close_ms(tr) for tr in trades_in_s]
    if any(c is None for c in closes):
        return cap
    return min(max(closes), cap)


def hold_ms(tr: Trade, t_eval: int) -> int:
    """hold_i = min(evaluation close, T_eval) - entry fill; a marked trade (or marked shadow)
    holds to T_eval (A1.3 f, A2.1)."""
    c = eval_close_ms(tr)
    return (t_eval if c is None else min(c, t_eval)) - tr.entry_ms


def is_marked(tr: Trade, t_eval: int) -> bool:
    """Marked for the gate: its evaluation close (shadow exit if flattened) is after T_eval."""
    c = eval_close_ms(tr)
    return c is None or c > t_eval


def day_clusters(trades: list[Trade], t_eval: int) -> dict[str, int]:
    """trade id -> UTC day number of its merged position's first entry. Components of the
    interval-overlap graph within (coin, direction); closed intervals, so touching counts.
    Interval = [entry, min(evaluation close, T_eval)] (shadow exit if flattened, A2.1)."""
    out: dict[str, int] = {}
    groups: dict[tuple[str, int], list[Trade]] = {}
    for tr in trades:
        groups.setdefault((tr.coin, tr.direction), []).append(tr)
    for grp in groups.values():
        grp.sort(key=lambda x: (x.entry_ms, x.tid))
        comp: list[Trade] = []
        reach = None
        for tr in grp:
            c = eval_close_ms(tr)
            end = t_eval if c is None else min(c, t_eval)
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


# ------------------------------------------------------------------ B0d (6.2; A1.3 g; A2.3 a)
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


def b_partial_last_resort(same_direction_bbar: list[float]) -> float:
    """Step 3 of the B_partial chain (A2.3 a): when trade i has neither a partial nor a relaxed
    window, B_partial = the largest B-bar of any trade in S with the same direction (full or
    partial), floored at 0; 0 if there is none."""
    return max([0.0, *same_direction_bbar])


def d_value(r: float, reps: list[float] | None, b_partial: float | None = None) -> float:
    """D_i = R_i - mean of the replications when trade i has an admissible window (>= 24 h).
    Without one: D_i = min(R_i, 0, R_i - B_partial) (A2.3 a; replaces A1.3 g's min(R_i, 0)).
    B_partial always exists (the 6.2 chain ends in b_partial_last_resort)."""
    if reps:
        return r - statistics.fmean(reps)
    if b_partial is None:
        raise ValueError("no admissible window: B_partial is required (6.2 chain)")
    return min(r, 0.0, r - b_partial)


def gate_r_flattened(realised_r: float, shadow_r: float) -> float:
    """A trade closed by /flatten counts with the worse of its realised R and the R the frozen
    exits would have produced on the recorded data (A1.3 d); a shadow still open at t300 + 7 d
    is marked, and shadow_r is then the marked R (A2.1)."""
    return min(realised_r, shadow_r)


# ------------------------------------------------------------------ verdict precedence (5.3, A1.3 a)
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
# Golden values (A2.7). Every printed vector is asserted against these literals, so a change in
# the RNG, the percentile index, the interval formulas or the merged-position rule fails the
# self-test instead of silently changing the printed file. The E13 literals were reproduced
# independently by the backtest-auditor from the addendum text (backtest-audit-r3.md).
GOLDEN_SEED_HEX = "0b233e788f6ca597fa1c5fea107f616e67489bc904773ef922b571a7d64a7cce"
GOLDEN_RNG = [3, 0, 4, 3, 3, 4, 2, 1, 3, 0]
GOLDEN_DC = {"A": 20000, "B": 20000, "C": 20000, "E": 20000, "D": 20001, "F": 20001}
GOLDEN_TOY = {
    96: "t (-0.202942, 0.696275)  boot (0.153333, 0.356667)  crt (0.095575, 0.397759)  LB_r -0.202942  UB_r 0.696275",
    99: "t (-0.329662, 0.822995)  boot (0.143333, 0.383333)  crt (0.025654, 0.467680)  LB_r -0.329662  UB_r 0.822995",
}
GOLDEN_REJ = [3438783679287873193, 3731590252986640208, 1270572960040841644, 6381682936847185917,
              1885042538497917448, 1431558458600256952]      # blocks rejected: i = 0 (2), i = 4 (1)
GOLDEN_UNEQUAL = "t (-0.202942, 0.696275)  boot (-0.050000, 0.378788)  crt (-0.029682, 0.523016)  LB_r -0.202942  UB_r 0.696275"
GOLDEN_B0D = [5004, 1003, 1008, 5001, 1001, 1005, 5001, 1009]
GOLDEN_DISTINCT = {
    96: ("lower k-1/k/k+1 0.041700/0.041875/0.041925  upper 0.334050/0.334125/0.334250  "
         "t (0.031863, 0.343137)  boot (0.041875, 0.334125)  crt (0.031863, 0.343137)  LB_r 0.031863  UB_r 0.343137"),
    99: ("lower k-1/k/k+1 0.005175/0.005300/0.006425  upper 0.368050/0.369350/0.372625  "
         "t (-0.010855, 0.385855)  boot (0.005300, 0.369350)  crt (-0.010855, 0.385855)  LB_r -0.010855  UB_r 0.385855"),
}
GOLDEN_FLATTEN = {"T_eval shadow open (h from d0)": 198, "T_eval all shadows closed (h from d0)": 70,
                  "hold Q (h)": 47, "hold S shadow open (h)": 168, "S marked (shadow open)": True,
                  "Q marked": False, "clusters P/Q/R/S": [0, 0, 0, 1],
                  "gate R Q (realised 1.2, shadow 0.4)": 0.4}
GOLDEN_D = {"full window R 0.5, reps [0.1, 0.3]": 0.3, "missing, R 0.5, B_partial 1.0": -0.5,
            "missing, R 0.5, B_partial 0.2": 0.0, "missing, R -0.4, B_partial -0.3": -0.4,
            "missing, R -0.4, B_partial 0.3": -0.7, "last resort B_partial of [0.4, -0.2, 0.9]": 0.9,
            "last resort B_partial of []": 0.0}


def fmt_pair(p: tuple[float, float]) -> str:
    return f"({p[0]:.6f}, {p[1]:.6f})"


def fmt_ci(res: dict) -> str:
    return (f"t {fmt_pair(res['t'])}  boot {fmt_pair(res['boot'])}  crt {fmt_pair(res['crt'])}  "
            f"LB_r {res['LB']}  UB_r {res['UB']}")


def main() -> None:
    # The seed is 32 raw bytes (A2.7). The run record stores it as 64 hex characters; an
    # implementation decodes the hex and feeds the raw bytes to SHA-256, never the hex text.
    seed = hashlib.sha256(b"tradestuff copytrade-v1 A1 test vector").digest()
    assert len(seed) == 32 and seed.hex() == GOLDEN_SEED_HEX
    assert bytes.fromhex(GOLDEN_SEED_HEX) == seed
    lines = ["EXPLORATORY reference implementation of the frozen evaluation keys (addenda A1 and A2). Test vectors.",
             f"seed (hex of the 32 raw bytes the RNG consumes) = {seed.hex()}"]

    # RNG
    first = [rng_uint(seed, TAG_BOOT_R, (0, j), 6) for j in range(10)]
    lines.append(f"rng_uint(seed, 'bootR', (0, j), 6) for j = 0..9: {first}")
    assert first == GOLDEN_RNG, first
    try:                                                    # the hex text is not a valid seed
        rng_uint(seed.hex().encode("ascii"), TAG_BOOT_R, (0, 0), 6)
        raise AssertionError("hex-text seed accepted")
    except ValueError:
        pass
    assert rng_uint(seed, TAG_BOOT_D, (0, 0), 6) is not None
    assert all(0 <= rng_uint(seed, "x", (i,), 7) < 7 for i in range(200))
    # Rejection vector (A2.7): with n = 2^63 + 1 about half of the SHA-256 blocks are rejected,
    # so an implementation without rejection sampling (x mod n) fails this vector.
    big = 2 ** 63 + 1
    rej = [rng_uint(seed, "rej", (i,), big) for i in range(6)]
    lines.append(f"rng_uint(seed, 'rej', (i,), 2^63 + 1) for i = 0..5: {rej}")
    assert rej == GOLDEN_REJ, rej

    # percentile index
    assert (pct_index(10_000, 96), pct_index(10_000, 99)) == (200, 50)
    assert pct_index(1_000, 96) == 20 and pct_index(1_000, 99) == 5
    assert pct_index(999, 96) == 19 and pct_index(10_001, 99) == 50        # floor, not round (A2.7)
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
    assert dc == GOLDEN_DC, dc
    lines.append(f"day_clusters example (A..F): {dc}")

    # CI on a toy sample: 30 trades on 6 days
    xs = [0.8, -1.0, 0.3, 1.9, -1.0, 0.1, -0.4, 2.5, -1.0, 0.6, 0.2, -1.0, 1.1, -0.2, 0.9,
          -1.0, 0.4, 3.0, -0.7, -1.0, 0.5, 1.4, -1.0, 0.0, -0.3, 2.2, -1.0, 0.7, -0.6, 1.0]
    keys = [k // 5 for k in range(30)]
    for lv in (96, 99):
        res = lb_ub(xs, keys, seed, TAG_BOOT_R, 10_000, lv)
        lines.append(f"toy sample, level {lv}%: {fmt_ci(res)}")
        assert fmt_ci(res) == GOLDEN_TOY[lv], (lv, fmt_ci(res))
        assert res["LB"] == min(r6(res["t"][0]), r6(res["boot"][0]), r6(res["crt"][0]))
        again = lb_ub(xs, keys, seed, TAG_BOOT_R, 10_000, lv)
        assert again["LB"] == res["LB"] and again["UB"] == res["UB"]                    # deterministic
        rev = lb_ub(list(reversed(xs)), list(reversed(keys)), seed, TAG_BOOT_R, 10_000, lv)
        assert fmt_ci(rev) == fmt_ci(res)                                               # cluster order

    # Unequal cluster sizes (A2.7): the statistic is the pooled trade mean, which differs from the
    # mean of cluster means only when cluster sizes differ (the toy sample has 5 trades per day).
    keys_u = [0] * 2 + [1] * 9 + [2] * 4 + [3] * 7 + [4] * 3 + [5] * 5
    res_u = lb_ub(xs, keys_u, seed, TAG_BOOT_R, 10_000, 96)
    lines.append(f"toy sample, unequal days (2/9/4/7/3/5 trades), level 96%: {fmt_ci(res_u)}")
    assert fmt_ci(res_u) == GOLDEN_UNEQUAL, fmt_ci(res_u)

    # Percentile off-by-one guard (A2.7): 40 single-trade day clusters with distinct values, so
    # neighbouring order statistics of the 10,000 bootstrap means differ. The printed neighbours
    # show that element k (not k - 1 or k + 1) is the bound.
    xs2 = [round(0.037 * i - 0.61 + (0.29 if i % 3 == 0 else 0.0) - (0.17 if i % 7 == 0 else 0.0), 6)
           for i in range(40)]
    keys2 = list(range(40))
    _ks, sums2, cnts2 = cluster_sums(xs2, keys2)
    distinct = {}
    for lv in (96, 99):
        means = []
        for r in range(10_000):
            tot, n = 0.0, 0
            for j in range(40):
                p = rng_uint(seed, TAG_BOOT_D, (r, j), 40)
                tot += sums2[p]
                n += cnts2[p]
            means.append(tot / n)
        means.sort()
        i = pct_index(10_000, lv)
        bt = boot_ci(xs2, keys2, seed, TAG_BOOT_D, 10_000, lv)
        assert bt == (means[i], means[10_000 - 1 - i])
        assert means[i - 1] < means[i] < means[i + 1] and means[-i - 2] < means[-i - 1] < means[-i]
        distinct[lv] = (f"lower k-1/k/k+1 {means[i - 1]:.6f}/{means[i]:.6f}/{means[i + 1]:.6f}  "
                        f"upper {means[-i - 2]:.6f}/{means[-i - 1]:.6f}/{means[-i]:.6f}  "
                        f"{fmt_ci(lb_ub(xs2, keys2, seed, TAG_BOOT_D, 10_000, lv))}")
        lines.append(f"distinct 40-cluster sample, tag bootD, level {lv}%: {distinct[lv]}")
    assert distinct == GOLDEN_DISTINCT, distinct

    # B0d draw
    adm = [(1_000, 1_010), (5_000, 5_005)]
    draws = [b0d_start(seed, 7, rep, adm) for rep in range(8)]
    assert all(1_000 <= x < 1_010 or 5_000 <= x < 5_005 for x in draws)
    assert draws == GOLDEN_B0D, draws
    assert b0d_start(seed, 7, 0, []) is None
    lines.append(f"b0d_start(seed, trade 7, rep 0..7, [[1000,1010),[5000,5005)]): {draws}")

    # D_i (A2.3 a): full window; missing window with B_partial; the beta-leak case B > max(R, 0)
    dv = {
        "full window R 0.5, reps [0.1, 0.3]": d_value(0.5, [0.1, 0.3]),
        "missing, R 0.5, B_partial 1.0": d_value(0.5, None, 1.0),
        "missing, R 0.5, B_partial 0.2": d_value(0.5, None, 0.2),
        "missing, R -0.4, B_partial -0.3": d_value(-0.4, [], -0.3),
        "missing, R -0.4, B_partial 0.3": d_value(-0.4, [], 0.3),
        "last resort B_partial of [0.4, -0.2, 0.9]": b_partial_last_resort([0.4, -0.2, 0.9]),
        "last resort B_partial of []": b_partial_last_resort([]),
    }
    lines.append("D_i (A2.3 a): " + "; ".join(f"{k} -> {v:.6f}" for k, v in dv.items()))
    assert {k: round(v, 6) for k, v in dv.items()} == GOLDEN_D, dv
    for r_ in (-1.0, -0.2, 0.0, 0.3, 1.5):
        for b_ in (-0.5, 0.0, 0.4, 2.0):
            assert d_value(r_, None, b_) <= min(r_, 0.0) and d_value(r_, None, b_) <= r_ - b_
    try:
        d_value(0.5, None)
        raise AssertionError("missing window without B_partial accepted")
    except ValueError:
        pass

    # /flatten (A1.3 d, A2.1): T_eval, hold and merged intervals use the SHADOW exit
    t300 = d0 + 30 * h
    fl = [Trade("P", "SOL", 1, d0 + 1 * h, d0 + 2 * h),
          Trade("Q", "SOL", 1, d0 + 3 * h, d0 + 4 * h, flattened=True, shadow_close_ms=d0 + 50 * h),
          Trade("R", "SOL", 1, d0 + 49 * h, d0 + 52 * h),          # overlaps Q's shadow, not its real close
          Trade("S", "ETH", -1, t300, d0 + 60 * h, flattened=True, shadow_close_ms=None)]  # shadow open
    te1 = t_eval_ms(fl, t300)
    fl_closed = fl[:3] + [Trade("S", "ETH", -1, t300, d0 + 60 * h, flattened=True, shadow_close_ms=d0 + 70 * h)]
    te2 = t_eval_ms(fl_closed, t300)
    dcf = day_clusters(fl_closed, te2)
    flat = {"T_eval shadow open (h from d0)": (te1 - d0) // h,
            "T_eval all shadows closed (h from d0)": (te2 - d0) // h,
            "hold Q (h)": hold_ms(fl_closed[1], te2) // h,
            "hold S shadow open (h)": hold_ms(fl[3], te1) // h,
            "S marked (shadow open)": is_marked(fl[3], te1),
            "Q marked": is_marked(fl_closed[1], te2),
            "clusters P/Q/R/S": [dcf[x] - 20_000 for x in "PQRS"],
            "gate R Q (realised 1.2, shadow 0.4)": gate_r_flattened(1.2, 0.4)}
    lines.append("flatten (A2.1): " + "; ".join(f"{k} = {v}" for k, v in flat.items()))
    assert flat == GOLDEN_FLATTEN, flat
    # the real close of a flattened trade never moves T_eval: flatten earlier or later, same T_eval
    for real_close in (d0 + 5 * h, d0 + 20 * h, d0 + 45 * h):
        alt = [fl_closed[0], Trade("Q", "SOL", 1, d0 + 3 * h, real_close, True, d0 + 50 * h), *fl_closed[2:]]
        assert t_eval_ms(alt, t300) == te2 and day_clusters(alt, te2) == dcf
    assert gate_r_flattened(-0.5, 0.3) == -0.5

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
    assert v(baseline_missing_share=0.10) == "PASS"                       # 30 of 300 is allowed
    assert v(usd_pnl_positive=False) == "INCONCLUSIVE" and v(p5=False) == "INCONCLUSIVE" and v(p6=False) == "INCONCLUSIVE"
    lines.append("verdict precedence: ABORTED > F1/F2 > P1 incomplete > G < 5 > F3 > PASS > INCONCLUSIVE (asserted)")
    lines.append("selftest OK (golden vectors asserted)")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
