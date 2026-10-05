"""EXPLORATORY - REFERENCE IMPLEMENTATION OF THE FROZEN EVALUATION KEYS - NOT PRODUCTION CODE (E16).

v4 (2026-09-29, addendum A4; supersedes the E15 version). edge-hypothesis.md addenda A1 (BT2-3),
A2 (BT3-1, BT3-3, BT3-7), A3 (PO spec-review decision A4, missed exits) and A4 (BT4-1 to BT4-10)
pin every choice the verdict depends on. This file implements
exactly that text so that the test designer, the developer and the backtest-auditor can check an
implementation against fixed test vectors. If this file and the addendum text disagree, the
addendum text wins and this file is a bug. Section labels below cite edge-hypothesis.md 5.3 / 6.2
and the addendum item that fixed each rule.

v3 adds (A3.1): a missed-exit trade counts in the gate at min(actual R, mirrored R), with the
mirror's ambiguous 1h bars resolved stop-first ("lo"); its cost versus mirroring uses the TP-first
mirror ("hi"); P4 / F2 = more than 3 missed exits, or any cost > 1R after rounding to 1e-6; the
evaluation close of a missed-exit trade is the later of its real close and its mirror exit. Every
v2 golden literal is unchanged.

v4 adds (A4): the cost of each missed exit is incremental (mirror M_j fixes missed exits 1..j) and
is tested next to the per-trade total, with actual R = realised R (A4.3); an uncomputable mirror
costs more than 1R and has mirrored lo R = actual R (A4.2); a mirror fill without a recorded book
uses the 1m candle, else the 1h candle, at its worst price + 8 bps (lo) and best price + 2 bps (hi),
and an SL/TP inside a gap fills at its trigger or at a gapped-through open (A4.2); the P4 breach time
is the leader event time of the 4th missed exit or the moment a cost is established, capped at
T_eval, and decides precedence against ABORTED (A4.4); an exit event is classified on time, late,
orphan, settled after a restart, settled after a data gap (resync + 60 s) or reconstruction failed
(A4.1, A4.5); a discretionary pause gives B-bar = max(including, excluding the paused starts)
(A4.6). verdict() is unchanged. Every v3 golden literal is unchanged.

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
  * the missed-exit rules (A3.1): gate R, cost versus the mirror, P4 / F2, evaluation close
  * A4: incremental costs, uncomputable mirrors, gap fills, P4 breach time, run end, exit classes,
    B-bar under discretionary pauses
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
    missed_exit: bool = False     # has at least one ledgered missed exit (A3.1)
    mirror_close_ms: int | None = None   # missed-exit only: mirror exit; None = mirror still open


def eval_close_ms(tr: Trade) -> int | None:
    """The close used for T_eval, hold_i, merged positions, B0d and P3 (A2.1, A3.1): the shadow
    exit for a flattened trade, the real full close otherwise; for a trade with a missed exit, the
    later of that and its mirror exit (A3.1). None = still open."""
    base = tr.shadow_close_ms if tr.flattened else tr.close_ms
    if not tr.missed_exit:
        return base
    if base is None or tr.mirror_close_ms is None:
        return None
    return max(base, tr.mirror_close_ms)


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


# ------------------------------------------------------------------ missed exits (5.3 P4 / F2, A3.1)
MISSED_EXIT_MAX_COUNT = 3               # eval.missed_exit_max_count: FAIL at the 4th
MISSED_EXIT_MAX_COST_R = Decimal("1")   # eval.missed_exit_max_cost_r: FAIL when cost > 1R


def gate_r(realised_r: float, shadow_r: float | None = None, mirror_lo_r: float | None = None) -> float:
    """Gate R of a trade in S (A1.3 d, A3.1): the minimum of its realised R, its /flatten shadow R
    (if flattened) and its stop-first mirrored R (if it has a missed exit). Never above realised."""
    return min(x for x in (realised_r, shadow_r, mirror_lo_r) if x is not None)


def missed_exit_cost(actual_r: float, mirror_lo_r: float, mirror_hi_r: float) -> Decimal:
    """Cost of a missed-exit trade versus mirroring on time, in that trade's R (A3.1): the TP-first
    mirrored R ("hi") minus the actual R, rounded half-even to 1e-6 like every gate comparison.
    The stop-first mirror ("lo") feeds the gate R only; it never enters the cost (the two are equal
    when no ambiguous 1h bar is used)."""
    if mirror_hi_r < mirror_lo_r:
        raise ValueError("the TP-first mirror can't be below the stop-first mirror")
    return r6(mirror_hi_r - actual_r)


def p4_breach(missed_count: int, costs: list[Decimal]) -> bool:
    """P4 fails (F2) when more than 3 missed exits fall in the evaluation window, or any
    missed-exit trade cost more than 1R versus its mirror (A3.1). costs are missed_exit_cost values."""
    return missed_count > MISSED_EXIT_MAX_COUNT or any(c > MISSED_EXIT_MAX_COST_R for c in costs)


# ------------------------------------------------------------------ A4 (E16): costs, gaps, breach time, classes, pauses
UNCOMPUTABLE = Decimal("Infinity")      # cost of an uncomputable mirror: above any threshold (A4.2)
LAG_MS = 60_000                         # exits.missed_exit_max_lag_s = 60 (A3.1)
BPS = Decimal("0.0001")
ALT_HALF_SPREAD_BPS = Decimal("8")      # cost.fallback_half_spread_bps, alt (6.3)
MAJOR_HALF_SPREAD_BPS = Decimal("2")    # cost.fallback_half_spread_bps, major (6.3)


def missed_exit_costs(actual_r: float, mirror_hi_chain: list[float | None]) -> list[Decimal]:
    """Costs of one share's missed exits 1..k in leader-event order (A4.3). mirror_hi_chain[j-1] is
    the TP-first ("hi") R of mirror M_j: missed exits 1..j and every other leader event mirrored on
    time, missed exits j+1..k handled as the engine actually handled them. M_k is the full A3.1
    mirror. Returns [c_1, ..., c_k, trade cost]: c_j = hi(M_j) - hi(M_(j-1)) with hi(M_0) = actual R,
    and trade cost = hi(M_k) - actual R, each rounded half-even to 1e-6. actual R is the realised R
    (a /flatten close included, never the shadow; the marked R for a trade still open at the cap).
    A None in the chain is an uncomputable mirror: every cost of the share is UNCOMPUTABLE (A4.2)."""
    if not mirror_hi_chain:
        raise ValueError("a share with a missed exit has at least one mirror")
    if any(x is None for x in mirror_hi_chain):
        return [UNCOMPUTABLE] * (len(mirror_hi_chain) + 1)
    out, prev = [], actual_r
    for hi in mirror_hi_chain:
        out.append(r6(hi - prev))
        prev = hi
    out.append(r6(mirror_hi_chain[-1] - actual_r))
    return out


def mirror_lo_for_gate(actual_r: float, mirror_lo_r: float | None) -> float:
    """Mirrored lo R used by gate_r (A4.2): an uncomputable mirror (None) has lo = actual R."""
    return actual_r if mirror_lo_r is None else mirror_lo_r


def gap_candle(fill_ms: int, candles_1m: set[int], candles_1h: set[int]) -> tuple[str, int] | None:
    """The candle a mirrored leader action fills on when no book is recorded within 5 s of its fill
    time (A4.2): the 1m candle containing fill_ms if it is in the hashed candle store, else the 1h
    candle, else None (uncomputable). The sets hold candle open times in ms."""
    m1 = fill_ms - fill_ms % 60_000
    if m1 in candles_1m:
        return ("1m", m1)
    h1 = fill_ms - fill_ms % 3_600_000
    if h1 in candles_1h:
        return ("1h", h1)
    return None


def _against(px: Decimal, side: int, bps: Decimal) -> Decimal:
    """Move px against us by bps: up for a buy (side +1), down for a sell (side -1)."""
    if side not in (1, -1):
        raise ValueError("side is +1 (buy) or -1 (sell)")
    return px * (1 + side * bps * BPS)


def gap_fill_px(side: int, candle: tuple[Decimal, Decimal, Decimal, Decimal]) -> tuple[Decimal, Decimal]:
    """(lo, hi) fill prices of a mirrored leader action over the gap candle (o, h, l, c) (A4.2).
    lo: the candle's worst price for our side (high for a buy, low for a sell) moved against us by
    the alt half-spread (8 bps). hi: its best price (low for a buy, high for a sell) moved against us
    by the major half-spread (2 bps). The open and close are never used; no delay term; taker fees
    are charged separately, as for every fill."""
    _o, h, l, _c = candle
    worst, best = (h, l) if side == 1 else (l, h)
    return _against(worst, side, ALT_HALF_SPREAD_BPS), _against(best, side, MAJOR_HALF_SPREAD_BPS)


def gap_trigger_px(side: int, kind: str, trigger: Decimal, bar_open: Decimal) -> tuple[Decimal, Decimal]:
    """(lo, hi) fill prices of a mirror's or shadow's SL or TP triggered inside a recording gap
    (A4.2). side is our closing order's side (-1 closes a long, +1 closes a short); kind is "sl" or
    "tp". The fill is at the trigger, or at the bar's open when the bar opened beyond the trigger
    (gap-through), moved against us by 8 bps (lo) or 2 bps (hi)."""
    if kind not in ("sl", "tp"):
        raise ValueError("kind is sl or tp")
    falls = (side == -1) == (kind == "sl")           # a long's stop and a short's TP trigger on a fall
    beyond = bar_open < trigger if falls else bar_open > trigger
    base = bar_open if beyond else trigger
    return _against(base, side, ALT_HALF_SPREAD_BPS), _against(base, side, MAJOR_HALF_SPREAD_BPS)


@dataclass
class MissedExit:
    mid: str                        # missed-exit ID
    event_ms: int                   # the leader event's exchange timestamp
    ledgered_ms: int                # when the missed_exit record was written (live, audit or final audit)
    costs: tuple[Decimal, ...]      # its incremental cost; the share's last one also carries the trade cost
    established_ms: int             # later of real close and mirror exits; the event time if uncomputable


def p4_breach_time(missed: list[MissedExit], t0: int, t_eval: int, audit_gap_ms: int | None = None) -> int | None:
    """Breach time of P4 / F2 (A4.4), or None. Only missed exits with a leader event in [t0, T_eval]
    count, whenever they were found. Count: the leader event time of the 4th in event-time order
    (ties by ID), never the order of ledgering. Cost: the moment a cost above 1R is established,
    capped at T_eval (a side still open there is marked). An incomplete fill audit (A4.1) breaches at
    audit_gap_ms. The earliest applies; it always lies in [t0, T_eval]."""
    inw = sorted((m for m in missed if t0 <= m.event_ms <= t_eval), key=lambda m: (m.event_ms, m.mid))
    times = []
    if len(inw) > MISSED_EXIT_MAX_COUNT:
        times.append(inw[MISSED_EXIT_MAX_COUNT].event_ms)
    times += [min(m.established_ms, t_eval) for m in inw if any(c > MISSED_EXIT_MAX_COST_R for c in m.costs)]
    if audit_gap_ms is not None:
        times.append(audit_gap_ms)
    return min(times) if times else None


def run_end(*, voided: bool, aborted_ms: int | None, f1_ms: int | None, f2_ms: int | None) -> str | None:
    """Precedence items 1 and 2 with times (A4.4). aborted_ms: the first ABORTED event before
    T_eval; f1_ms / f2_ms: breach times (both lie in [t0, T_eval]). A voiding ruling always gives
    ABORTED. Otherwise ABORTED wins only when strictly earlier than every breach; on a tie, FAIL.
    None: the run reached T_eval without an early end."""
    if voided:
        return "ABORTED"
    breach = min((x for x in (f1_ms, f2_ms) if x is not None), default=None)
    if aborted_ms is not None and (breach is None or aborted_ms < breach):
        return "ABORTED"
    return "FAIL" if breach is not None else None


MISSED_CLASSES = ("late", "orphan", "reconstruction_failed")


def exit_class(event_ms: int, handled_ms: int | None, found_by: str,
               process_down: list[tuple[int, int]], data_gaps: list[tuple[int, int]],
               reconstruction_settled: bool = False) -> str:
    """Class of a leader exit event on a share we hold (A3.1, A4.1, A4.5). handled_ms: the first
    ledger time of a mirroring action, a rule-based non-mirror record or the share's full close for
    it (None: never). found_by: "live", "reconciliation" or "audit". Downtime intervals are
    half-open [start, end), with end = the restart or the resync. Missed exits are MISSED_CLASSES;
    "settled_gap" is not a missed exit but counts at min(actual, mirrored lo) (A4.5)."""
    for a, b in process_down:
        if a <= event_ms < b:
            return "settled_restart" if reconstruction_settled else "reconstruction_failed"
    for a, b in data_gaps:
        if a <= event_ms < b:
            return "settled_gap" if handled_ms is not None and handled_ms <= b + LAG_MS else "reconstruction_failed"
    if handled_ms is not None and handled_ms <= event_ms + LAG_MS:
        return "on_time"
    return "late" if found_by == "live" else "orphan"


def b_bar_discretionary(starts: list[int], reps_r: list[float], paused: list[tuple[int, int]]) -> float:
    """B-bar_i under discretionary pauses (A4.6). The replications are drawn (tag b0d) from the
    admissible set with the discretionary pause intervals NOT excluded. B-bar = max(mean over all,
    mean over the replications starting outside every discretionary pause); the mean over all when
    no replication starts inside, or none outside. Without a discretionary pause in the draw range
    this equals the A3.2 b draw."""
    everything = statistics.fmean(reps_r)
    outside = [r for s, r in zip(starts, reps_r) if not any(a <= s < b for a, b in paused)]
    if not outside or len(outside) == len(reps_r):
        return everything
    return max(everything, statistics.fmean(outside))


# ------------------------------------------------------------------ verdict precedence (5.3, A1.3 a)
def verdict(*, aborted: bool, f1: bool, f2: bool, n_opened: int, g: int,
            lb_r: Decimal, ub_r: Decimal, usd_pnl_positive: bool, lb_d: Decimal,
            baseline_missing_share: float, p5: bool, p6: bool) -> str:
    """aborted: run_end(...) == "ABORTED": an ABORTED event before T_eval and strictly before every
    F1/F2 breach time, or the backtest-auditor voided the run (that ruling overrides FAIL; it can
    never produce PASS). f1 / f2: run_end(...) == "FAIL" with that breach. f2 is true for any P4
    breach by missed exits with a leader event in [t0, T_eval], whenever it is found before the
    verdict (A4.4; p4_breach / p4_breach_time): more than 3 missed exits, an incremental or trade
    cost > 1R, an uncomputable mirror, or an incomplete fill audit."""
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
# A3.1 (E15). Costs are Decimal strings after rounding; -2.003 / -1.003 is a pair of 1e-6 R values
# whose binary64 difference is 1.0000000000000002, so only the rounded comparison says "not > 1R".
GOLDEN_MISSED = {"gate R actual 0.8, mirror_lo 0.3": 0.3, "gate R actual -1.4, mirror_lo -0.2": -1.4,
                 "gate R realised 0.5, shadow 0.2, mirror_lo 0.4": 0.2,
                 "cost actual -1.3, mirror_hi -0.2 (mirror_lo -0.5)": "1.100000",
                 "cost actual -2.003, mirror_hi -1.003": "1.000000",
                 "P4 3 missed, costs 0.200000/1.000000/0.000000": False, "P4 4 missed, costs 0": True,
                 "P4 1 missed, cost 1.100000": True, "P4 1 missed, cost 1.000000 (-2.003 vs -1.003)": False,
                 "P4 0 missed": False}
GOLDEN_MISSED_CLOSE = {"T_eval mirror closed (h from d0)": 40, "T_eval mirror open (h from d0)": 198,
                       "hold M (h)": 39, "M marked (mirror open)": True, "M marked (mirror closed)": False,
                       "clusters M/N/O": [0, 0, 1]}
# A4 (E16). Hand-computed before the first run; the run reproduced every value.
GOLDEN_A4_COST = {"costs actual 0.2, hi chain [1.5, 1.0]": ["1.300000", "-0.500000", "0.800000"],
                  "costs actual -1.3, hi chain [-0.2]": ["1.100000", "1.100000"],
                  "costs actual -0.5, hi chain [0.3, uncomputable]": ["Infinity", "Infinity", "Infinity"],
                  "P4 2 missed, costs of [1.5, 1.0] from 0.2": True, "P4 on the netted trade cost only": False,
                  "P4 1 missed, uncomputable": True, "gate R uncomputable mirror, actual 0.7": 0.7}
GOLDEN_A4_GAP_CANDLE = {"1m and 1h stored": ("1m", 754), "1h only": ("1h", 720), "neither": None}
GOLDEN_A4_GAP_FILL = {"buy": ["101.0808", "99.0198"], "sell": ["98.9208", "100.9798"],
                      "long SL 95, open 96": ["94.9240", "94.9810"],
                      "long SL 95, open 94 (gap-through)": ["93.9248", "93.9812"],
                      "long TP 110, open 111 (gap-through)": ["110.9112", "110.9778"],
                      "short SL 105, open 106 (gap-through)": ["106.0848", "106.0212"],
                      "short TP 90, open 91": ["90.0720", "90.0180"]}
GOLDEN_A4_BREACH = {"4 in window, found by the audit at 24 h (h from d0)": 9, "3 in window, 4th event after T_eval": None,
                    "cost 1.2R established after T_eval": 25, "incomplete audit from 11 h": 11}
GOLDEN_A4_RUN_END = {"aborted 8 h, F2 9 h": "ABORTED", "aborted 9 h, F2 9 h (tie)": "FAIL",
                     "aborted 10 h, F2 9 h (found later)": "FAIL", "voided, F1 5 h": "ABORTED",
                     "F1 5 h, aborted 7 h, F2 9 h": "FAIL", "none": None}
GOLDEN_A4_CLASS = {"handled +60 s": "on_time", "handled +61 s, live": "late",
                   "handled +61 s, reconciliation": "orphan", "never handled, audit": "orphan",
                   "process down, settled": "settled_restart", "process down, not settled": "reconstruction_failed",
                   "data gap, handled at resync + 60 s": "settled_gap",
                   "data gap, handled at resync + 61 s": "reconstruction_failed",
                   "data gap, never handled": "reconstruction_failed", "at resync, handled +61 s": "late"}
GOLDEN_A4_BBAR = {"paused starts high": 0.275, "paused starts low": -0.04, "no pause": 0.275}


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
    lines = ["EXPLORATORY reference implementation of the frozen evaluation keys (addenda A1 to A4). Test vectors.",
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

    # missed exits (A3.1): gate R, cost versus the mirror, P4 / F2, evaluation close
    cost_a = missed_exit_cost(-1.3, -0.5, -0.2)
    cost_b = missed_exit_cost(-2.003, -1.003, -1.003)
    assert -1.003 - -2.003 > 1.0                  # the unrounded binary64 difference exceeds 1R
    me = {"gate R actual 0.8, mirror_lo 0.3": gate_r(0.8, mirror_lo_r=0.3),
          "gate R actual -1.4, mirror_lo -0.2": gate_r(-1.4, mirror_lo_r=-0.2),
          "gate R realised 0.5, shadow 0.2, mirror_lo 0.4": gate_r(0.5, 0.2, 0.4),
          "cost actual -1.3, mirror_hi -0.2 (mirror_lo -0.5)": str(cost_a),
          "cost actual -2.003, mirror_hi -1.003": str(cost_b),
          "P4 3 missed, costs 0.200000/1.000000/0.000000":
              p4_breach(3, [missed_exit_cost(-0.4, -0.2, -0.2), missed_exit_cost(-1.2, -0.2, -0.2), missed_exit_cost(0.1, 0.1, 0.1)]),
          "P4 4 missed, costs 0": p4_breach(4, [Decimal("0")] * 4),
          "P4 1 missed, cost 1.100000": p4_breach(1, [cost_a]),
          "P4 1 missed, cost 1.000000 (-2.003 vs -1.003)": p4_breach(1, [cost_b]),
          "P4 0 missed": p4_breach(0, [])}
    lines.append("missed exits (A3.1): " + "; ".join(f"{k} -> {v}" for k, v in me.items()))
    assert me == GOLDEN_MISSED, me
    for a_ in (-2.0, -0.7, 0.0, 0.4, 1.9):          # the gate R never exceeds actual or mirror
        for m_ in (-1.5, -0.1, 0.0, 0.6, 3.0):
            assert gate_r(a_, mirror_lo_r=m_) <= a_ and gate_r(a_, mirror_lo_r=m_) <= m_
    assert gate_r(1.2) == 1.2 and gate_r(1.2, 0.4) == gate_r_flattened(1.2, 0.4)
    try:                                                    # hi below lo is a caller bug
        missed_exit_cost(-1.0, 0.2, 0.1)
        raise AssertionError("TP-first mirror below stop-first mirror accepted")
    except ValueError:
        pass
    t300m = d0 + 30 * h
    mt = [Trade("M", "SOL", 1, d0 + 1 * h, d0 + 2 * h, missed_exit=True, mirror_close_ms=d0 + 40 * h),
          Trade("N", "SOL", 1, d0 + 30 * h, d0 + 32 * h),       # overlaps M's mirror, not its real close
          Trade("O", "ETH", -1, d0 + 26 * h, d0 + 28 * h)]
    te_m = t_eval_ms(mt, t300m)
    mt_open = [Trade("M", "SOL", 1, d0 + 1 * h, d0 + 2 * h, missed_exit=True, mirror_close_ms=None), *mt[1:]]
    te_mo = t_eval_ms(mt_open, t300m)
    dcm = day_clusters(mt, te_m)
    mc = {"T_eval mirror closed (h from d0)": (te_m - d0) // h,
          "T_eval mirror open (h from d0)": (te_mo - d0) // h,
          "hold M (h)": hold_ms(mt[0], te_m) // h,
          "M marked (mirror open)": is_marked(mt_open[0], te_mo),
          "M marked (mirror closed)": is_marked(mt[0], te_m),
          "clusters M/N/O": [dcm[x] - 20_000 for x in "MNO"]}
    lines.append("missed-exit evaluation close (A3.1): " + "; ".join(f"{k} = {v}" for k, v in mc.items()))
    assert mc == GOLDEN_MISSED_CLOSE, mc
    late_real = Trade("M", "SOL", 1, d0 + 1 * h, d0 + 45 * h, missed_exit=True, mirror_close_ms=d0 + 40 * h)
    assert eval_close_ms(late_real) == d0 + 45 * h                        # the later of the two closes

    # A4.3 incremental and per-trade costs; A4.2 uncomputable mirror
    ca = missed_exit_costs(0.2, [1.5, 1.0])        # BT4-3: +1.3R then -0.5R; the trade nets 0.8R
    cb = missed_exit_costs(-1.3, [-0.2])
    cc = missed_exit_costs(-0.5, [0.3, None])
    a4c = {"costs actual 0.2, hi chain [1.5, 1.0]": [str(x) for x in ca],
           "costs actual -1.3, hi chain [-0.2]": [str(x) for x in cb],
           "costs actual -0.5, hi chain [0.3, uncomputable]": [str(x) for x in cc],
           "P4 2 missed, costs of [1.5, 1.0] from 0.2": p4_breach(2, ca),
           "P4 on the netted trade cost only": p4_breach(2, ca[-1:]),
           "P4 1 missed, uncomputable": p4_breach(1, missed_exit_costs(0.4, [None])),
           "gate R uncomputable mirror, actual 0.7": gate_r(0.7, mirror_lo_r=mirror_lo_for_gate(0.7, None))}
    lines.append("missed-exit costs (A4.3, A4.2): " + "; ".join(f"{k} -> {v}" for k, v in a4c.items()))
    assert a4c == GOLDEN_A4_COST, a4c
    assert cb[0] == missed_exit_cost(-1.3, -0.5, -0.2) and cb[-1] == cb[0]      # k = 1: the A3.1 cost
    for act in (-1.7, -0.3, 0.0, 0.9):                                          # increments telescope
        for chain in ([0.5], [1.1, -0.4], [-2.0, 0.3, 0.8]):
            cs = missed_exit_costs(act, chain)
            assert abs(sum(cs[:-1]) - cs[-1]) <= Decimal("0.000001") * len(chain)
    try:
        missed_exit_costs(0.1, [])
        raise AssertionError("a share with a missed exit and no mirror accepted")
    except ValueError:
        pass

    # A4.2 fills without a recorded book: candle choice, candle extremes, SL/TP gap-through
    fill = d0 + 12 * h + 34 * 60_000 + 56_789
    m1, h1 = fill - fill % 60_000, fill - fill % h
    cndl = (Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100.5"))
    gc = {"1m and 1h stored": gap_candle(fill, {m1}, {h1}), "1h only": gap_candle(fill, set(), {h1}),
          "neither": gap_candle(fill, {m1 - 60_000}, set())}
    gcr = {k: (None if v is None else (v[0], (v[1] - d0) // 60_000)) for k, v in gc.items()}
    gf = {"buy": [str(x) for x in gap_fill_px(1, cndl)], "sell": [str(x) for x in gap_fill_px(-1, cndl)],
          "long SL 95, open 96": [str(x) for x in gap_trigger_px(-1, "sl", Decimal("95"), Decimal("96"))],
          "long SL 95, open 94 (gap-through)": [str(x) for x in gap_trigger_px(-1, "sl", Decimal("95"), Decimal("94"))],
          "long TP 110, open 111 (gap-through)": [str(x) for x in gap_trigger_px(-1, "tp", Decimal("110"), Decimal("111"))],
          "short SL 105, open 106 (gap-through)": [str(x) for x in gap_trigger_px(1, "sl", Decimal("105"), Decimal("106"))],
          "short TP 90, open 91": [str(x) for x in gap_trigger_px(1, "tp", Decimal("90"), Decimal("91"))]}
    lines.append("gap fills (A4.2): candle (minutes from d0) " + "; ".join(f"{k} -> {v}" for k, v in gcr.items())
                 + "; (lo, hi) " + "; ".join(f"{k} -> {v}" for k, v in gf.items()))
    assert gcr == GOLDEN_A4_GAP_CANDLE, gcr
    assert gf == GOLDEN_A4_GAP_FILL, gf
    for s_ in (1, -1):                          # lo is never better than hi for our side
        lo_, hi_ = gap_fill_px(s_, cndl)
        assert (lo_ - hi_) * s_ >= 0

    # A4.4 breach time and run end
    t0b, teb = d0, d0 + 25 * h
    me4 = [MissedExit("A", d0 + 2 * h, d0 + 24 * h, (Decimal("0.1"),), d0 + 3 * h),
           MissedExit("B", d0 + 5 * h, d0 + 24 * h, (Decimal("0.2"),), d0 + 6 * h),
           MissedExit("C", d0 + 7 * h, d0 + 24 * h, (Decimal("0"),), d0 + 8 * h),
           MissedExit("D", d0 + 9 * h, d0 + 9 * h + 60_000, (Decimal("0.3"),), d0 + 10 * h),
           MissedExit("E", d0 + 26 * h, d0 + 26 * h, (Decimal("0"),), d0 + 27 * h)]
    cost_late = [MissedExit("F", d0 + 20 * h, d0 + 20 * h, (Decimal("1.200000"),), d0 + 30 * h)]
    bt = {"4 in window, found by the audit at 24 h (h from d0)": p4_breach_time(me4, t0b, teb),
          "3 in window, 4th event after T_eval": p4_breach_time([me4[0], me4[1], me4[3], me4[4]], t0b, teb),
          "cost 1.2R established after T_eval": p4_breach_time(cost_late, t0b, teb),
          "incomplete audit from 11 h": p4_breach_time(me4[:2], t0b, teb, d0 + 11 * h)}
    btr = {k: (None if v is None else (v - d0) // h) for k, v in bt.items()}
    re_ = {"aborted 8 h, F2 9 h": run_end(voided=False, aborted_ms=d0 + 8 * h, f1_ms=None, f2_ms=d0 + 9 * h),
           "aborted 9 h, F2 9 h (tie)": run_end(voided=False, aborted_ms=d0 + 9 * h, f1_ms=None, f2_ms=d0 + 9 * h),
           "aborted 10 h, F2 9 h (found later)": run_end(voided=False, aborted_ms=d0 + 10 * h, f1_ms=None, f2_ms=d0 + 9 * h),
           "voided, F1 5 h": run_end(voided=True, aborted_ms=None, f1_ms=d0 + 5 * h, f2_ms=None),
           "F1 5 h, aborted 7 h, F2 9 h": run_end(voided=False, aborted_ms=d0 + 7 * h, f1_ms=d0 + 5 * h, f2_ms=d0 + 9 * h),
           "none": run_end(voided=False, aborted_ms=None, f1_ms=None, f2_ms=None)}
    lines.append("P4 breach time (A4.4, h from d0; T_eval 25 h): " + "; ".join(f"{k} -> {v}" for k, v in btr.items())
                 + "; run end: " + "; ".join(f"{k} -> {v}" for k, v in re_.items()))
    assert btr == GOLDEN_A4_BREACH, btr
    assert re_ == GOLDEN_A4_RUN_END, re_
    for sub in (me4, me4[:3], cost_late, me4[:3] + cost_late):   # breach time exists iff p4_breach
        inw = [m for m in sub if t0b <= m.event_ms <= teb]
        assert (p4_breach_time(sub, t0b, teb) is not None) == p4_breach(len(inw), [c for m in inw for c in m.costs])

    # A4.1 / A4.5 exit classes (seconds; data gap [3000 s, 3010 s) resyncs at 3010 s)
    s = 1_000
    pd, dg = [(1_000 * s, 2_000 * s)], [(3_000 * s, 3_010 * s)]
    ec = {"handled +60 s": exit_class(100 * s, 160 * s, "live", pd, dg),
          "handled +61 s, live": exit_class(100 * s, 161 * s, "live", pd, dg),
          "handled +61 s, reconciliation": exit_class(100 * s, 161 * s, "reconciliation", pd, dg),
          "never handled, audit": exit_class(100 * s, None, "audit", pd, dg),
          "process down, settled": exit_class(1_500 * s, None, "live", pd, dg, reconstruction_settled=True),
          "process down, not settled": exit_class(1_500 * s, None, "live", pd, dg),
          "data gap, handled at resync + 60 s": exit_class(3_005 * s, 3_070 * s, "live", pd, dg),
          "data gap, handled at resync + 61 s": exit_class(3_005 * s, 3_071 * s, "live", pd, dg),
          "data gap, never handled": exit_class(3_005 * s, None, "audit", pd, dg),
          "at resync, handled +61 s": exit_class(3_010 * s, 3_071 * s, "live", pd, dg)}
    lines.append("exit classes (A4.1, A4.5): " + "; ".join(f"{k} -> {v}" for k, v in ec.items()))
    assert ec == GOLDEN_A4_CLASS, ec

    # A4.6 B-bar under a discretionary pause: draws over [1000, 1010) and [5000, 5005), /pause = [5000, 5005)
    starts = [b0d_start(seed, 7, rep, adm) for rep in range(8)]
    up = [0.9, -0.2, 0.1, 0.8, -0.4, 0.3, 0.7, 0.0]      # paused starts did well: including them is higher
    down = [-0.9, -0.2, 0.1, -0.8, -0.4, 0.3, -0.7, 0.0]  # paused starts did badly: excluding them is higher
    bb = {"paused starts high": b_bar_discretionary(starts, up, [(5_000, 5_005)]),
          "paused starts low": b_bar_discretionary(starts, down, [(5_000, 5_005)]),
          "no pause": b_bar_discretionary(starts, up, [])}
    lines.append("B-bar under /pause (A4.6): " + "; ".join(f"{k} -> {v:.6f}" for k, v in bb.items()))
    assert {k: round(v, 6) for k, v in bb.items()} == GOLDEN_A4_BBAR, bb
    for rs in (up, down):
        assert b_bar_discretionary(starts, rs, [(5_000, 5_005)]) >= statistics.fmean(rs)

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
    assert v(f2=p4_breach(3, [cost_b, cost_b, cost_b])) == "PASS"         # 3 missed exits, each <= 1R (A3.1)
    assert v(f2=p4_breach(4, [])) == "FAIL" and v(f2=p4_breach(1, [cost_a])) == "FAIL"
    assert v(aborted=True, f2=p4_breach(4, [])) == "ABORTED" and v(f2=p4_breach(4, []), g=3) == "FAIL"
    # A4.4: a breach found after T_eval (final audit) is F2; an abort after the breach time is FAIL
    end = run_end(voided=False, aborted_ms=d0 + 10 * h, f1_ms=None, f2_ms=p4_breach_time(me4, t0b, teb))
    assert v(aborted=end == "ABORTED", f2=end == "FAIL") == "FAIL"
    assert v(f2=p4_breach(1, missed_exit_costs(0.4, [None]))) == "FAIL"      # uncomputable mirror (A4.2)
    assert v(f2=p4_breach(2, ca)) == "FAIL"                                   # incremental cost 1.3R (A4.3)
    lines.append("verdict precedence: ABORTED > F1/F2 > P1 incomplete > G < 5 > F3 > PASS > INCONCLUSIVE (asserted)")
    lines.append("selftest OK (golden vectors asserted)")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
