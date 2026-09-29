"""EXPLORATORY - SURVIVORSHIP-BIASED (today's leaderboard) - NOT VALIDATION.

hl_sample.py v2 (2026-09-29). Rewritten after the backtest audit (BT-1, BT-2, BT-3, BT-16).

Pulls a small sample from Hyperliquid's PUBLIC info endpoints (no keys, read-only, no
orders) and estimates, per wallet AND as a cross-wallet dispersion (not only pooled):
  * opens per day over the OBSERVATION WINDOW (BT-1). If the 10,000-fill history cap
    may have truncated the window, the window starts at the first available fill and
    the wallet is flagged; otherwise the full requested window is the denominator.
  * holding time with right-censoring handled: Kaplan-Meier median, closed-only
    median, and the count of positions still open at the end (censored).
  * leader position size as a fraction of the leader's account value at the open,
    and the share of opens whose mirrored size on a $300 wallet is below the $10
    minimum: raw, and after the 0.5% risk cap (2 x ATR(1h, 14) stop) and the 3x cap.
  * mirrored ADDS (executed / below $10 / blocked by the cap) and mirrored PARTIAL
    EXITS under the PO rule of 2026-09-29: if the remainder would fall below $10,
    close it all; else if the cut is below $10, skip it and log it (BT-16).
  * price drift after the leader's opening fill at +1, +2, +5, +15 min
    (1-minute candles: coarse, +/- 1 minute; per-second decay needs our own
    recorded trade stream).

Look-ahead controls:
  * SELECT, THEN MEASURE FORWARD (BT-2). Wallets are selected with data available at
    t_sel = end - measure_days: the candidate pool uses the leaderboard's P&L earned
    BEFORE the last 30 days (allTime pnl - month pnl), and the gates use portfolio
    points and fills with time <= t_sel. Every reported statistic is measured only on
    positions OPENED in [t_sel, end]. Leader win rate and P&L are therefore
    forward, post-selection numbers; they are still survivorship-biased (see below).
  * The leader's account value at a past open is the latest portfolio point at or
    before that open (BT-3). There is NO fallback to the current account value.
    Opens with no earlier point are excluded from size statistics and counted.
  * Cheap product gates applied at t_sel (BT-16): not HLP, not a vault/agent account,
    account value >= $10k, account age >= 180 d, positive P&L in the selection
    window, maker share <= 0.70, median hold >= 15 min, >= 25 closed round trips in
    the 30-day selection window (the product's 150 per 180 d, pro-rated), no
    liquidation fill.

Remaining biases (also written into the output):
  * The candidate pool is TODAY's leaderboard: wallets that vanished are missing
    (survivorship). Numbers are indicative only, never evidence of an edge.
  * The product ranks by the section-10 score; this sampler ranks by selection-window
    P&L (coarse allTime pnlHistory points), so "top" wallets only approximate what the
    product would follow. Half the sample is drawn at random from the gate-passing
    pool to show dispersion.
  * The position cap on adds uses notional at the add price; the product caps risk.
  * HIP-3 (builder dex, "dex:COIN") and spot fills are skipped: v1 trades core
    crypto perps only (PO 2026-09-29).

Usage (from the repository root):
  python docs/sdlc/copytrade-v1/research/scripts/hl_sample.py --selftest
  python docs/sdlc/copytrade-v1/research/scripts/hl_sample.py
Output: research/data/hl_sample/run_<UTC timestamp>/summary.json (+ raw/*.json.gz).
research/data/ is gitignored. See README.md in this folder.
Stdlib only. Python >= 3.10.
"""

from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
import platform
import random
import shutil
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SCRIPT_VERSION = "2.0.0"
INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
HLP_VAULT = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"

DAY_MS = 86_400_000
MIN_MS = 60_000
FILL_CAP = 10_000             # only the 10,000 most recent fills exist per wallet
TRUNC_FLAG_FILLS = 9_000      # >= this many fills returned: history may be cut by the cap
MIN_ORDER_USD = 10.0          # Hyperliquid minimum order value
WALLET_USD = 300.0            # PO: paper wallet
RISK = 0.005                  # PO 2026-09-29: 0.5% risk per trade
LEV_CAP = 3.0                 # default leverage ceiling on one position (x wallet)
STOP_ATR_MULT = 2.0           # V0 stop: 2 x ATR
ATR_N = 14                    # ATR period on 1h candles closed before the entry
FALLBACK_STOP_PCT = 0.025     # only when candles are unavailable; flagged per open
DRIFT_DAYS = 3                # 1m candles reach back ~3.5 days (5,000 bars)
DRIFT_MINUTES = (1, 2, 5, 15)
EPS = 1e-12

LABEL = ("EXPLORATORY, SURVIVORSHIP-BIASED (candidate pool = today's leaderboard), "
         "small n. Indicative only, never evidence of an edge. Selection uses data up to "
         "t_sel; all statistics are measured on positions opened after t_sel.")

def _repo_root() -> Path:
    """The repository root if the script sits at its usual place, else the current folder."""
    try:
        root = Path(__file__).resolve().parents[5]
    except IndexError:
        return Path.cwd()
    return root if (root / "docs" / "sdlc" / "copytrade-v1").is_dir() else Path.cwd()


DEFAULT_OUT = _repo_root() / "research" / "data" / "hl_sample"


# ================================================================ rate budget (B4)
class WeightBudget:
    """Rolling 60-second request-weight budget. Hyperliquid allows 1,200 weight per
    minute per IP; the default here uses 800 so other tools keep headroom."""

    def __init__(self, per_min: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.per_min = per_min
        self.clock = clock
        self.sleep = sleep
        self.log: deque[tuple[float, float]] = deque()
        self.total = 0.0

    def _expire(self) -> float:
        now = self.clock()
        while self.log and now - self.log[0][0] >= 60.0:
            self.log.popleft()
        return now

    def spend(self, w: float) -> None:
        while True:
            now = self._expire()
            used = sum(x[1] for x in self.log)
            if used + w <= self.per_min or not self.log:
                break
            self.sleep(max(0.05, 60.0 - (now - self.log[0][0])))
        self.log.append((self.clock(), w))
        self.total += w

    def charge(self, w: float) -> None:
        """Weight that is only known after the response (items returned)."""
        if w > 0:
            self.log.append((self.clock(), w))
            self.total += w


# ================================================================ HTTP client (public)
class HttpClient:
    """Read-only client for public endpoints. No keys, no signing, no orders."""

    def __init__(self, weight_per_min: float = 800.0, verbose: bool = True) -> None:
        self.budget = WeightBudget(weight_per_min)
        self.requests = 0
        self.retries = 0
        self.verbose = verbose
        self._jitter = random.SystemRandom()

    def _fetch(self, url: str, payload: bytes | None) -> object:
        for attempt in range(7):
            try:
                req = urllib.request.Request(
                    url, data=payload,
                    headers={"Content-Type": "application/json",
                             "User-Agent": f"tradestuff-research/{SCRIPT_VERSION}"})
                self.requests += 1
                with urllib.request.urlopen(req, timeout=90) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (418, 429, 500, 502, 503, 504) and attempt < 6:
                    self._backoff(attempt, f"HTTP {e.code}")
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < 6:
                    self._backoff(attempt, type(e).__name__)
                    continue
                raise
        raise RuntimeError("unreachable")

    def _backoff(self, attempt: int, why: str) -> None:
        self.retries += 1
        wait = min(120.0, 5.0 * 2 ** attempt) * (0.5 + self._jitter.random())
        if self.verbose:
            print(f"  {why}; retrying in {wait:.0f} s", flush=True)
        time.sleep(wait)

    def _info(self, body: dict, base_weight: float, per_items: int | None = None) -> object:
        self.budget.spend(base_weight)
        data = self._fetch(INFO_URL, json.dumps(body).encode())
        if per_items and isinstance(data, list):
            self.budget.charge(len(data) // per_items)
        return data

    # --- interface used by run_sample() (the self-test uses a fake with the same methods)
    def leaderboard(self) -> list[dict]:
        return self._fetch(LEADERBOARD_URL, None)["leaderboardRows"]

    def portfolio(self, user: str) -> dict:
        return dict(self._info({"type": "portfolio", "user": user}, 20))

    def user_role(self, user: str) -> str:
        try:
            r = self._info({"type": "userRole", "user": user}, 60)
            return str(r.get("role", "unknown")) if isinstance(r, dict) else "unknown"
        except urllib.error.HTTPError:
            return "unknown"

    def fills(self, user: str, start_ms: int, end_ms: int) -> tuple[list[dict], int]:
        """Paginate forward; <= 2,000 fills per call; only the 10,000 most recent exist.
        Returns (deduplicated fills sorted by time, raw count returned by the API)."""
        out: list[dict] = []
        cursor = start_ms
        while True:
            batch = self._info({"type": "userFillsByTime", "user": user, "startTime": cursor,
                                "endTime": end_ms, "aggregateByTime": True}, 20, per_items=20)
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 2000:
                break
            nxt = max(int(f["time"]) for f in batch) + 1
            if nxt <= cursor:
                break
            cursor = nxt
        return dedupe_fills(out), len(out)

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
        data = self._info({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms}},
            20, per_items=60)
        return sorted(data or [], key=lambda c: int(c["t"]))


def dedupe_fills(fills: list[dict]) -> list[dict]:
    seen, uniq = set(), []
    for f in sorted(fills, key=lambda f: (int(f["time"]), f.get("tid", 0))):
        k = (f.get("tid"), f.get("hash"), f["time"], f["coin"], f["sz"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


# ================================================================ reconstruction
@dataclass
class Event:
    t: int
    kind: str                      # "add" | "reduce"
    px: float
    sz_before: float               # |leader position| before the fill
    sz_after: float                # |leader position| after the fill


@dataclass
class RoundTrip:
    coin: str
    direction: int                 # +1 long, -1 short
    open_ms: int
    open_px: float
    open_sz: float
    close_ms: int | None = None
    max_abs_sz: float = 0.0
    adds: int = 0
    adds_while_losing: int = 0
    reduces: list[float] = field(default_factory=list)   # fraction of position cut
    events: list[Event] = field(default_factory=list)
    net_pnl: float = 0.0
    avg_px: float = 0.0
    liquidated: bool = False


def is_core_perp(coin: str) -> bool:
    """Spot ('@123', 'PURR/USDC') and HIP-3 builder-dex perps ('dex:COIN') are skipped."""
    return not (coin.startswith("@") or "/" in coin or ":" in coin)


def is_liquidation(f: dict) -> bool:
    return bool(f.get("liquidation")) or "iquidat" in str(f.get("dir", ""))


def reconstruct(fills: list[dict]) -> tuple[list[RoundTrip], list[RoundTrip]]:
    """Returns (closed round trips, still-open round trips). A flip is split into a
    close and a new open. Positions already open at the first fill are skipped until
    flat (the product's rule: ignore positions held before we started)."""
    closed: list[RoundTrip] = []
    live: dict[str, RoundTrip] = {}
    skip_coin: dict[str, bool] = {}
    for f in sorted(fills, key=lambda f: (int(f["time"]), f.get("tid", 0))):
        coin = f["coin"]
        if not is_core_perp(coin):
            continue
        t = int(f["time"])
        start = float(f["startPosition"])
        sz = float(f["sz"])
        px = float(f["px"])
        delta = sz if f["side"] == "B" else -sz
        end = start + delta
        pnl = float(f.get("closedPnl", 0.0)) - float(f.get("fee", 0.0))
        liq = is_liquidation(f)
        if coin not in live and coin not in skip_coin:
            skip_coin[coin] = abs(start) > EPS          # pre-existing position: ignore until flat
        if skip_coin.get(coin):
            if abs(end) < EPS or (start != 0 and math.copysign(1, end) != math.copysign(1, start)):
                skip_coin[coin] = False
                if abs(end) > EPS:                       # flip out of an ignored position = fresh open
                    live[coin] = RoundTrip(coin, 1 if end > 0 else -1, t, px, abs(end),
                                           max_abs_sz=abs(end), avg_px=px)
            continue
        rt = live.get(coin)
        if rt is None:
            if abs(end) < EPS:
                continue
            live[coin] = RoundTrip(coin, 1 if end > 0 else -1, t, px, abs(end),
                                   max_abs_sz=abs(end), avg_px=px, net_pnl=pnl, liquidated=liq)
            continue
        same_side = abs(end) > EPS and math.copysign(1, end) == rt.direction
        rt.net_pnl += pnl
        rt.liquidated = rt.liquidated or liq
        if same_side and abs(end) > abs(start):                       # add
            rt.adds += 1
            if (px - rt.avg_px) * rt.direction < 0:
                rt.adds_while_losing += 1
            rt.avg_px = (rt.avg_px * abs(start) + px * (abs(end) - abs(start))) / abs(end)
            rt.max_abs_sz = max(rt.max_abs_sz, abs(end))
            rt.events.append(Event(t, "add", px, abs(start), abs(end)))
        elif same_side:                                               # partial reduce
            rt.reduces.append((abs(start) - abs(end)) / abs(start))
            rt.events.append(Event(t, "reduce", px, abs(start), abs(end)))
        else:                                                         # close or flip
            rt.close_ms = t
            closed.append(rt)
            del live[coin]
            if abs(end) > EPS:
                live[coin] = RoundTrip(coin, 1 if end > 0 else -1, t, px, abs(end),
                                       max_abs_sz=abs(end), avg_px=px)
    return closed, list(live.values())


# ================================================================ point-in-time helpers
def value_at(points: list[tuple[int, float]], t_ms: int) -> float | None:
    """Latest point with timestamp <= t_ms, or None. Never a later value (BT-3)."""
    i = bisect.bisect_right([p[0] for p in points], t_ms)
    return points[i - 1][1] if i else None


def _windows(port: dict, names: tuple[str, ...]) -> list[dict]:
    return [port[n] for n in names if isinstance(port.get(n), dict)]


def account_value_points(port: dict) -> list[tuple[int, float]]:
    """Account value is absolute, so points from all windows can be merged."""
    pts: dict[int, float] = {}
    wins = _windows(port, ("perpAllTime", "perpMonth", "perpWeek", "perpDay")) or \
        _windows(port, ("allTime", "month", "week", "day"))
    for w in wins:
        for ts, v in w.get("accountValueHistory") or []:
            pts[int(ts)] = float(v)
    return sorted(pts.items())


def alltime_pnl_points(port: dict) -> list[tuple[int, float]]:
    """Cumulative P&L. Only the all-time window is used: shorter windows restart at 0."""
    w = port.get("perpAllTime") or port.get("allTime") or {}
    return sorted((int(ts), float(v)) for ts, v in (w.get("pnlHistory") or []))


def atr_stop_pct(candles_1h: list[dict], t_ms: int, px: float) -> float | None:
    """STOP_ATR_MULT x ATR(ATR_N) / px on 1h bars CLOSED before t_ms (no look-ahead)."""
    bars = [c for c in candles_1h if int(c["T"]) < t_ms]
    if len(bars) < ATR_N + 1 or px <= 0:
        return None
    bars = bars[-(ATR_N + 1):]
    trs = []
    for prev, cur in zip(bars, bars[1:]):
        h, lo, pc = float(cur["h"]), float(cur["l"]), float(prev["c"])
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return STOP_ATR_MULT * (sum(trs) / len(trs)) / px


# ================================================================ statistics helpers
def quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def dispersion(values: list[float | None], nd: int = 4) -> dict:
    xs = [float(x) for x in values if x is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": round(min(xs), nd), "p25": round(quantile(xs, .25), nd),
            "median": round(quantile(xs, .5), nd), "p75": round(quantile(xs, .75), nd),
            "max": round(max(xs), nd)}


def km_median(durations: list[tuple[float, bool]]) -> float | None:
    """Kaplan-Meier median of right-censored durations [(value, observed)].
    None if the survival curve never drops to 0.5 (too much censoring)."""
    if not durations:
        return None
    data = sorted(durations, key=lambda x: (x[0], not x[1]))
    at_risk = len(data)
    s = 1.0
    i = 0
    while i < len(data):
        t = data[i][0]
        d = c = 0
        while i < len(data) and data[i][0] == t:
            if data[i][1]:
                d += 1
            else:
                c += 1
            i += 1
        if d:
            s *= 1.0 - d / at_risk
            if s <= 0.5 + 1e-12:
                return t
        at_risk -= d + c
    return None


def _share(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


# ================================================================ mirroring (BT-16, PO $10 rule)
@dataclass
class MirrorResult:
    status: str                    # "no_prior_av" | "open_below_min" | "taken"
    frac: float | None = None      # leader open notional / leader AV at the open
    mirror_usd: float | None = None
    capped_usd: float | None = None
    stop_pct: float | None = None
    adds_total: int = 0
    adds_exec: int = 0
    adds_below_min: int = 0
    adds_capped: int = 0
    adds_no_av: int = 0
    partials_total: int = 0
    partials_exec: int = 0
    partials_skipped_below_min: int = 0
    partials_closed_all: int = 0


def mirror_trip(rt: RoundTrip, av_points: list[tuple[int, float]], stop_pct: float) -> MirrorResult:
    """Mirror one leader round trip on a $300 wallet.
    Open: (leader notional / leader AV at the open) x $300, capped by the risk cap
    (RISK x $300 / stop_pct) and the leverage cap (LEV_CAP x $300).
    Adds: mirrored the same way at the add's own AV point; the total position stays
    within the cap; an add below $10 (after the cap) is not executable.
    Partial exits (PO 2026-09-29): if the remainder would fall below $10, close all;
    else if the cut is below $10, skip it and log it; else cut the same fraction."""
    av0 = value_at(av_points, rt.open_ms)
    if av0 is None or av0 <= 0:
        return MirrorResult("no_prior_av", stop_pct=stop_pct)
    frac = rt.open_sz * rt.open_px / av0
    mirror = frac * WALLET_USD
    cap = min(RISK * WALLET_USD / stop_pct, LEV_CAP * WALLET_USD)
    capped = min(mirror, cap)
    res = MirrorResult("taken", frac=frac, mirror_usd=mirror, capped_usd=capped, stop_pct=stop_pct)
    if capped < MIN_ORDER_USD:
        res.status = "open_below_min"
        return res
    qty = capped / rt.open_px
    for ev in rt.events:
        if ev.kind == "add":
            res.adds_total += 1
            av = value_at(av_points, ev.t)
            if av is None or av <= 0:
                res.adds_no_av += 1
                continue
            want = (ev.sz_after - ev.sz_before) * ev.px / av * WALLET_USD
            room = max(0.0, cap - qty * ev.px)
            add = min(want, room)
            if add < MIN_ORDER_USD:
                if want >= MIN_ORDER_USD:
                    res.adds_capped += 1
                else:
                    res.adds_below_min += 1
                continue
            qty += add / ev.px
            res.adds_exec += 1
        else:
            res.partials_total += 1
            cut_frac = (ev.sz_before - ev.sz_after) / ev.sz_before
            pos_usd = qty * ev.px
            cut_usd = pos_usd * cut_frac
            if pos_usd - cut_usd < MIN_ORDER_USD:
                res.partials_closed_all += 1        # reduce-only full close is exempt from $10
                break
            if cut_usd < MIN_ORDER_USD:
                res.partials_skipped_below_min += 1
                continue
            qty -= cut_usd / ev.px
            res.partials_exec += 1
    return res


# ================================================================ selection (point-in-time)
@dataclass(frozen=True)
class Gates:
    min_av_usd: float = 10_000.0
    min_age_days: float = 180.0
    max_maker_share: float = 0.70
    min_median_hold_min: float = 15.0
    min_round_trips: int = 25          # product G2: 150 per 180 d, pro-rated to 30 d
    exclude_roles: tuple[str, ...] = ("vault", "agent", "missing")


def stage_a(addr: str, port: dict, sel_start: int, t_sel: int, g: Gates) -> dict:
    """Portfolio-only gates, evaluated with points at or before t_sel."""
    av = account_value_points(port)
    pnl = alltime_pnl_points(port)
    av_sel = value_at(av, t_sel)
    age = (t_sel - av[0][0]) / DAY_MS if av else None
    p1 = value_at(pnl, t_sel)
    p0 = value_at(pnl, sel_start)
    sel_pnl = None if p1 is None else p1 - (p0 if p0 is not None else 0.0)
    fails = []
    if addr.lower() == HLP_VAULT:
        fails.append("hlp")
    if av_sel is None:
        fails.append("no_account_value_at_t_sel")
    elif av_sel < g.min_av_usd:
        fails.append("account_value_below_min_at_t_sel")
    if age is None or age < g.min_age_days:
        fails.append("account_too_young_at_t_sel")
    if sel_pnl is None:
        fails.append("no_pnl_at_t_sel")
    elif sel_pnl <= 0:
        fails.append("selection_window_pnl_not_positive")
    return {"address": addr, "fails": fails, "av_at_t_sel": av_sel,
            "age_days_at_t_sel": None if age is None else round(age, 1),
            "selection_pnl_usd": None if sel_pnl is None else round(sel_pnl, 2),
            "pnl_points_in_selection_window": sum(1 for ts, _ in pnl if sel_start < ts <= t_sel)}


def selection_stats(fills: list[dict], n_raw: int, sel_start: int, t_sel: int) -> dict:
    """Uses only fills with time <= t_sel (what the product could see at t_sel)."""
    known = [f for f in fills if int(f["time"]) <= t_sel]
    closed, _ = reconstruct(known)
    trips = [r for r in closed if r.open_ms >= sel_start]
    holds = [(r.close_ms - r.open_ms) / MIN_MS for r in trips]
    win = [f for f in known if int(f["time"]) >= sel_start and is_core_perp(f["coin"])]
    notional = sum(float(f["sz"]) * float(f["px"]) for f in win)
    maker = sum(float(f["sz"]) * float(f["px"]) for f in win if f.get("crossed") is False)
    first = min(int(f["time"]) for f in fills) if fills else None
    return {"n_round_trips": len(trips),
            "median_hold_min": round(statistics.median(holds), 1) if holds else None,
            "maker_share": round(maker / notional, 4) if notional > 0 else None,
            "liquidation": any(is_liquidation(f) for f in win),
            "realised_pnl_usd": round(sum(r.net_pnl for r in trips), 2),
            "history_possibly_truncated": n_raw >= TRUNC_FLAG_FILLS,
            "selection_window_truncated": bool(n_raw >= TRUNC_FLAG_FILLS and first is not None
                                               and first > sel_start)}


def stage_b_fails(role: str, sel: dict, g: Gates) -> list[str]:
    fails = []
    if role in g.exclude_roles:
        fails.append(f"role_{role}")
    if sel["n_round_trips"] < g.min_round_trips:
        fails.append("too_few_round_trips")
    if sel["maker_share"] is None or sel["maker_share"] > g.max_maker_share:
        fails.append("maker_share_above_max")
    if sel["median_hold_min"] is None or sel["median_hold_min"] < g.min_median_hold_min:
        fails.append("median_hold_below_min")
    if sel["liquidation"]:
        fails.append("liquidation_in_selection_window")
    return fails


# ================================================================ forward measurement
def measure_wallet(fills: list[dict], n_raw: int, av_points: list[tuple[int, float]],
                   meas_start: int, end: int,
                   stop_for: Callable[[str, int, float], tuple[float, str]]) -> dict:
    """All statistics use positions OPENED in [observation start, end).
    Observation start = meas_start, unless the fill cap may have truncated history
    after meas_start, in which case it is the first available fill (flagged; BT-1)."""
    closed, live = reconstruct(fills)
    first = min(int(f["time"]) for f in fills) if fills else None
    possibly_trunc = n_raw >= TRUNC_FLAG_FILLS
    obs_start = meas_start
    meas_trunc = False
    if possibly_trunc and first is not None and first > meas_start:
        obs_start, meas_trunc = first, True
    obs_days = max((end - obs_start) / DAY_MS, 1e-9)
    trips = sorted((r for r in closed + live if obs_start <= r.open_ms < end), key=lambda r: r.open_ms)

    durations = []
    for r in trips:
        if r.close_ms is not None and r.close_ms <= end:
            durations.append(((r.close_ms - r.open_ms) / MIN_MS, True))
        else:
            durations.append(((end - r.open_ms) / MIN_MS, False))
    closed_holds = [d for d, obs in durations if obs]

    mr: list[MirrorResult] = []
    stop_sources: Counter = Counter()
    for r in trips:
        sp, src = stop_for(r.coin, r.open_ms, r.open_px)
        stop_sources[src] += 1
        mr.append(mirror_trip(r, av_points, sp))
    with_av = [m for m in mr if m.status != "no_prior_av"]
    taken = [m for m in mr if m.status == "taken"]
    fracs = [m.frac for m in with_av if m.frac and m.frac > 0]
    closed_in = [r for r in trips if r.close_ms is not None and r.close_ms <= end]
    sum_ = lambda k: sum(getattr(m, k) for m in taken)          # noqa: E731
    pt = sum_("partials_total")
    at = sum_("adds_total")
    return {
        "observation_days": round(obs_days, 3),
        "history_possibly_truncated": possibly_trunc,
        "measurement_window_truncated": meas_trunc,
        "opens": len(trips),
        "opens_per_day": round(len(trips) / obs_days, 4),
        "closed_in_window": len(closed_in),
        "censored_open_at_end": len(trips) - len(closed_in),
        "median_hold_min_km": None if km_median(durations) is None else round(km_median(durations), 1),
        "median_hold_min_closed_only": round(statistics.median(closed_holds), 1) if closed_holds else None,
        "opens_no_prior_account_value": sum(m.status == "no_prior_av" for m in mr),
        "frac_median": round(statistics.median(fracs), 4) if fracs else None,
        "log_frac_sd": round(statistics.stdev([math.log(x) for x in fracs]), 3) if len(fracs) > 1 else None,
        "stop_pct_median": round(statistics.median([m.stop_pct for m in mr]), 4) if mr else None,
        "stop_source_counts": dict(stop_sources),
        "share_open_below_min_raw": _share(sum(m.mirror_usd < MIN_ORDER_USD for m in with_av), len(with_av)),
        "share_open_below_min_after_cap": _share(sum(m.status == "open_below_min" for m in with_av), len(with_av)),
        "adds_per_taken_trip": round(at / len(taken), 3) if taken else None,
        "adds_total": at,
        "share_adds_executed": _share(sum_("adds_exec"), at),
        "share_adds_below_min": _share(sum_("adds_below_min"), at),
        "share_adds_capped": _share(sum_("adds_capped"), at),
        "adds_no_prior_account_value": sum_("adds_no_av"),
        "partials_per_taken_trip": round(pt / len(taken), 3) if taken else None,
        "partials_total": pt,
        "share_partials_executed": _share(sum_("partials_exec"), pt),
        "share_partials_skipped_below_min": _share(sum_("partials_skipped_below_min"), pt),
        "share_partials_closed_all_remainder_below_min": _share(sum_("partials_closed_all"), pt),
        "adds_while_losing_share": _share(sum(r.adds_while_losing for r in trips), sum(r.adds for r in trips)),
        "fwd_leader_win_rate_closed": _share(sum(r.net_pnl > 0 for r in closed_in), len(closed_in)),
        "fwd_leader_net_pnl_closed_usd": round(sum(r.net_pnl for r in closed_in), 2),
        "fwd_leader_liquidations": sum(r.liquidated for r in trips),
    }


def drift_after_open(rts: list[RoundTrip], candles: dict[str, list[dict]]) -> dict[int, list[float]]:
    """Drift in bps at +k minutes (close of the 1-minute candle containing t+k).
    Positive = price moved in the leader's favour, i.e. what a copier arriving k
    minutes late pays. Coarse (+/- 1 minute)."""
    out: dict[int, list[float]] = {k: [] for k in DRIFT_MINUTES}
    for r in rts:
        cs = candles.get(r.coin)
        if not cs:
            continue
        starts = [int(c["t"]) for c in cs]
        for k in out:
            target = r.open_ms + k * MIN_MS
            i = bisect.bisect_right(starts, target) - 1
            if i >= 0 and target <= int(cs[i]["T"]):
                out[k].append(r.direction * (float(cs[i]["c"]) - r.open_px) / r.open_px * 1e4)
    return out


def _drift_summary(d: dict[int, list[float]]) -> dict:
    return {f"+{k}min": {"n": len(v),
                         "median_bps": round(statistics.median(v), 2) if v else None,
                         "mean_bps": round(statistics.fmean(v), 2) if v else None}
            for k, v in d.items()}


# ================================================================ orchestration
def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save_gz(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh)


def _pre_selection_pnl(row: dict) -> float:
    """Leaderboard P&L earned before the last 30 days = allTime - month. With
    measure_days <= 30 this uses no information after t_sel."""
    wp = dict(row.get("windowPerformances") or [])
    return float((wp.get("allTime") or {}).get("pnl", 0) or 0) - float((wp.get("month") or {}).get("pnl", 0) or 0)


def script_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unknown"


def run_sample(client, a: argparse.Namespace, now_ms: int, out_dir: Path, log=print) -> dict:
    g = Gates(min_round_trips=a.min_round_trips)
    end = now_ms
    t_sel = end - a.measure_days * DAY_MS
    sel_start = t_sel - a.select_days * DAY_MS
    raw = out_dir / "raw"
    started = time.time()

    log(f"[1/5] leaderboard (selection time t_sel = {_iso(t_sel)})")
    rows = client.leaderboard()
    _save_gz(raw / "leaderboard.json.gz", rows)
    pool_rows = [r for r in rows if str(r.get("ethAddress", "")).lower() != HLP_VAULT
                 and _pre_selection_pnl(r) > 0]
    pool_rows.sort(key=lambda r: (-_pre_selection_pnl(r), str(r["ethAddress"]).lower()))
    pool = [str(r["ethAddress"]) for r in pool_rows[: a.pool]]

    log(f"[2/5] portfolio gates at t_sel for {len(pool)} candidates")
    errors: list[dict] = []
    a_recs: dict[str, dict] = {}
    av_by_addr: dict[str, list[tuple[int, float]]] = {}
    for i, addr in enumerate(pool, 1):
        try:
            port = client.portfolio(addr)
        except Exception as e:                       # noqa: BLE001 - research tool, log and go on
            errors.append({"address": addr, "step": "portfolio", "error": repr(e)[:300]})
            continue
        _save_gz(raw / f"portfolio_{addr}.json.gz", port)
        av_by_addr[addr] = account_value_points(port)
        a_recs[addr] = stage_a(addr, port, sel_start, t_sel, g)
        if i % 20 == 0:
            log(f"      {i}/{len(pool)}")
    survivors = sorted((r for r in a_recs.values() if not r["fails"]),
                       key=lambda r: (-r["selection_pnl_usd"], r["address"].lower()))

    log(f"[3/5] fills and activity gates ({len(survivors)} passed the portfolio gates)")
    n_top = a.wallets // 2
    n_rand = a.wallets - n_top
    fetched = 0
    examined: dict[str, dict] = {}
    selected: list[tuple[str, str]] = []                 # (address, group)
    fills_by_addr: dict[str, tuple[list[dict], int]] = {}

    def examine(addr: str) -> bool:
        nonlocal fetched
        fetched += 1
        try:
            role = client.user_role(addr)
            fills, n_raw = client.fills(addr, sel_start, end)
        except Exception as e:                       # noqa: BLE001
            errors.append({"address": addr, "step": "fills", "error": repr(e)[:300]})
            examined[addr] = {"role": "error", "fails": ["fetch_error"]}
            return False
        _save_gz(raw / f"fills_{addr}.json.gz", fills)
        sel = selection_stats(fills, n_raw, sel_start, t_sel)
        fails = stage_b_fails(role, sel, g)
        examined[addr] = {"role": role, "selection": sel, "fails": fails, "raw_fill_count": n_raw}
        if not fails:
            fills_by_addr[addr] = (fills, n_raw)
        log(f"      {addr} role={role} rt={sel['n_round_trips']} "
            f"maker={sel['maker_share']} hold={sel['median_hold_min']} -> "
            f"{'PASS' if not fails else ','.join(fails)}")
        return not fails

    for rec in survivors:
        if sum(1 for _, gr in selected if gr == "top_by_selection_pnl") >= n_top or fetched >= a.max_fetch:
            break
        if examine(rec["address"]):
            selected.append((rec["address"], "top_by_selection_pnl"))
    rest = [r["address"] for r in survivors if r["address"] not in examined]
    random.Random(a.seed).shuffle(rest)
    for addr in rest:
        if sum(1 for _, gr in selected if gr == "random_from_gate_passers") >= n_rand or fetched >= a.max_fetch:
            break
        if examine(addr):
            selected.append((addr, "random_from_gate_passers"))

    log(f"[4/5] 1h candles for ATR stops ({len(selected)} wallets selected)")
    trips_by_addr: dict[str, list[RoundTrip]] = {}
    for addr, _ in selected:
        closed, live = reconstruct(fills_by_addr[addr][0])
        trips_by_addr[addr] = [r for r in closed + live if t_sel <= r.open_ms < end]
    coins = sorted({r.coin for rs in trips_by_addr.values() for r in rs})
    c1h: dict[str, list[dict]] = {}
    for coin in coins:
        try:
            c1h[coin] = client.candles(coin, "1h", t_sel - 3 * DAY_MS, end)
        except Exception as e:                       # noqa: BLE001
            errors.append({"coin": coin, "step": "candles_1h", "error": repr(e)[:300]})
    _save_gz(raw / "candles_1h.json.gz", c1h)

    def stop_for(coin: str, t_ms: int, px: float) -> tuple[float, str]:
        sp = atr_stop_pct(c1h.get(coin, []), t_ms, px)
        return (sp, "atr_1h") if sp else (FALLBACK_STOP_PCT, "fallback_2.5pct")

    wallets_out: dict[str, dict] = {}
    for addr, group in selected:
        fills, n_raw = fills_by_addr[addr]
        m = measure_wallet(fills, n_raw, av_by_addr[addr], t_sel, end, stop_for)
        wallets_out[addr] = {"group": group, "portfolio_gates": a_recs[addr],
                             "activity_gates": examined[addr], "forward": m}

    log("[5/5] 1m candles for post-open drift")
    drift_from = max(t_sel, end - DRIFT_DAYS * DAY_MS)
    drift_trips = {addr: [r for r in rs if r.open_ms >= drift_from] for addr, rs in trips_by_addr.items()}
    c1m: dict[str, list[dict]] = {}
    for coin in sorted({r.coin for rs in drift_trips.values() for r in rs}):
        try:
            c1m[coin] = client.candles(coin, "1m", drift_from, end)
        except Exception as e:                       # noqa: BLE001
            errors.append({"coin": coin, "step": "candles_1m", "error": repr(e)[:300]})
    pooled_drift = drift_after_open([r for rs in drift_trips.values() for r in rs], c1m)
    for addr in wallets_out:
        d = drift_after_open(drift_trips.get(addr, []), c1m)
        wallets_out[addr]["forward"]["drift"] = _drift_summary(d)

    fw = [w["forward"] for w in wallets_out.values()]
    disp_keys = ["opens_per_day", "median_hold_min_km", "median_hold_min_closed_only", "frac_median",
                 "log_frac_sd", "stop_pct_median", "share_open_below_min_raw",
                 "share_open_below_min_after_cap", "adds_per_taken_trip", "share_adds_executed",
                 "partials_per_taken_trip", "share_partials_skipped_below_min",
                 "share_partials_closed_all_remainder_below_min", "fwd_leader_win_rate_closed"]
    total_opens = sum(x["opens"] for x in fw)
    total_days = sum(x["observation_days"] for x in fw)
    fail_a = Counter(f for r in a_recs.values() for f in r["fails"])
    fail_b = Counter(f for r in examined.values() for f in r["fails"])
    summary = {
        "label": LABEL,
        "script": {"file": "docs/sdlc/copytrade-v1/research/scripts/hl_sample.py",
                   "version": SCRIPT_VERSION, "sha256": script_sha256()},
        "run": {"python": sys.version.split()[0], "platform": platform.system() + " " + platform.release(),
                "started_unix": round(started), "finished_utc": _iso(int(time.time() * 1000)),
                "args": vars(a), "requests": getattr(client, "requests", None),
                "retries": getattr(client, "retries", None),
                "weight_spent": getattr(getattr(client, "budget", None), "total", None)},
        "windows": {"selection_start_utc": _iso(sel_start), "t_sel_utc": _iso(t_sel), "end_utc": _iso(end),
                    "select_days": a.select_days, "measure_days": a.measure_days},
        "assumptions": {"wallet_usd": WALLET_USD, "risk_per_trade": RISK, "leverage_cap_x": LEV_CAP,
                        "stop": f"{STOP_ATR_MULT} x ATR({ATR_N}) on 1h bars closed before the open; "
                                f"fallback {FALLBACK_STOP_PCT}",
                        "min_order_usd": MIN_ORDER_USD,
                        "partial_rule": "remainder < $10 -> close all; else cut < $10 -> skip and log",
                        "truncation_flag_fills": TRUNC_FLAG_FILLS, "gates": vars(g) if hasattr(g, "__dict__") else str(g)},
        "pool": {"leaderboard_rows": len(rows), "pool_size": len(pool),
                 "portfolio_gate_pass": len(survivors), "portfolio_gate_fail_reasons": dict(fail_a),
                 "examined_with_fills": len(examined), "activity_gate_fail_reasons": dict(fail_b),
                 "role_unknown": sum(1 for r in examined.values() if r.get("role") == "unknown"),
                 "selected": len(selected), "selected_top": sum(1 for _, gr in selected if gr.startswith("top")),
                 "selected_random": sum(1 for _, gr in selected if gr.startswith("random"))},
        "dispersion_across_wallets": {k: dispersion([x.get(k) for x in fw]) for k in disp_keys},
        "pooled": {"opens": total_opens, "wallet_observation_days": round(total_days, 2),
                   "opens_per_wallet_day": round(total_opens / total_days, 4) if total_days else None,
                   "wallets_measure_window_truncated": sum(x["measurement_window_truncated"] for x in fw),
                   "opens_no_prior_account_value": sum(x["opens_no_prior_account_value"] for x in fw),
                   "censored_open_at_end": sum(x["censored_open_at_end"] for x in fw)},
        "drift_pooled": _drift_summary(pooled_drift),
        "wallets": wallets_out,
        "errors": errors,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


# ================================================================ self-test (offline)
def _fill(t, coin, side, sz, px, start, pnl=0.0, fee=0.0, crossed=True, liq=False):
    d = {"time": t, "coin": coin, "side": side, "sz": str(sz), "px": str(px),
         "startPosition": str(start), "closedPnl": str(pnl), "fee": str(fee), "tid": t,
         "hash": f"h{t}", "crossed": crossed}
    if liq:
        d["liquidation"] = {"markPx": str(px)}
    return d


def _rt(t0, hold_ms, coin="BTC", sz=1.0, px=100.0, crossed=True, win=True):
    exit_px = px * (1.01 if win else 0.99)
    return [_fill(t0, coin, "B", sz, px, 0.0, crossed=crossed),
            _fill(t0 + hold_ms, coin, "A", sz, exit_px, sz, pnl=sz * (exit_px - px), crossed=crossed)]


class _FakeClient:
    """Offline stand-in for HttpClient with canned, synthetic data."""

    def __init__(self, rows, ports, roles, fills, candles):
        self.rows, self.ports, self.roles, self.f, self.c = rows, ports, roles, fills, candles
        self.requests = 0

    def leaderboard(self):
        return self.rows

    def portfolio(self, user):
        self.requests += 1
        return self.ports[user]

    def user_role(self, user):
        self.requests += 1
        return self.roles.get(user, "unknown")

    def fills(self, user, s, e):
        self.requests += 1
        fs = [f for f in self.f.get(user, []) if s <= f["time"] <= e]
        return dedupe_fills(fs), len(fs)

    def candles(self, coin, interval, s, e):
        self.requests += 1
        return [c for c in self.c.get((coin, interval), []) if s <= c["t"] <= e]


def selftest() -> None:
    m, d = MIN_MS, DAY_MS

    # 1. reconstruction: pre-existing skipped, add while losing, partial, flip split, open left
    fills = [
        _fill(0, "ETH", "B", 1.0, 100, 1.0),                   # pre-existing long: ignored
        _fill(1 * m, "ETH", "A", 2.0, 101, 2.0, pnl=2.0),      # closes pre-existing -> flat
        _fill(2 * m, "BTC", "B", 1.0, 100, 0.0),               # open long 1
        _fill(3 * m, "BTC", "B", 1.0, 98, 1.0),                # add while losing
        _fill(4 * m, "BTC", "A", 0.8, 102, 2.0, pnl=3.2),      # reduce 40%
        _fill(10 * m, "BTC", "A", 3.2, 103, 1.2, pnl=3.6),     # flip: close 1.2, open short 2.0
        _fill(20 * m, "BTC", "B", 2.0, 104, -2.0, pnl=-2.0),   # close short
        _fill(30 * m, "SOL", "A", 5.0, 20, 0.0),               # open short, still open
        _fill(31 * m, "xyz:TSLA", "B", 1.0, 300, 0.0),         # HIP-3: skipped (core perps only)
        _fill(32 * m, "@107", "B", 1.0, 30, 0.0),              # spot: skipped
    ]
    closed, live = reconstruct(fills)
    assert [(r.coin, r.direction) for r in closed] == [("BTC", 1), ("BTC", -1)], closed
    assert closed[0].adds == 1 and closed[0].adds_while_losing == 1
    assert abs(closed[0].reduces[0] - 0.4) < 1e-9
    assert [e.kind for e in closed[0].events] == ["add", "reduce"]
    assert closed[0].close_ms == 10 * m and closed[1].open_ms == 10 * m
    assert abs(closed[0].net_pnl - 6.8) < 1e-9 and abs(closed[1].net_pnl + 2.0) < 1e-9
    assert [(r.coin, r.direction) for r in live] == [("SOL", -1)]

    const_stop = lambda coin, t, px: (0.025, "test")          # noqa: E731
    av = [(0, 1000.0)]

    # 2. BT-1: a sparse wallet. One 60-minute round trip in a 30-day window = 1/30 per day,
    #    not 24 per day (the v1 bug divided by the first-to-last-fill span).
    ms0 = 100 * d
    sparse = _rt(ms0 + 5 * d, 60 * m)
    s = measure_wallet(sparse, len(sparse), av, ms0, ms0 + 30 * d, const_stop)
    assert s["opens"] == 1 and abs(s["opens_per_day"] - round(1 / 30, 4)) < 1e-9, s
    assert s["observation_days"] == 30.0 and not s["measurement_window_truncated"]

    # 3. BT-1: truncation by the fill cap is detected and flagged, then first fill -> end
    busy = _rt(ms0 + 20 * d, 60 * m) + _rt(ms0 + 25 * d, 60 * m)
    t = measure_wallet(busy, FILL_CAP, av, ms0, ms0 + 30 * d, const_stop)
    assert t["history_possibly_truncated"] and t["measurement_window_truncated"]
    assert t["observation_days"] == 10.0 and abs(t["opens_per_day"] - 0.2) < 1e-9, t
    nt = measure_wallet(busy, len(busy), av, ms0, ms0 + 30 * d, const_stop)
    assert not nt["measurement_window_truncated"] and abs(nt["opens_per_day"] - round(2 / 30, 4)) < 1e-9

    # 4. BT-3: no account-value point before the open -> excluded and counted, and a
    #    LATER (larger) value is never used for a past open.
    late_av = [(ms0 + 6 * d, 1_000_000.0)]
    u = measure_wallet(sparse, len(sparse), late_av, ms0, ms0 + 30 * d, const_stop)
    assert u["opens_no_prior_account_value"] == 1 and u["share_open_below_min_raw"] is None, u
    assert value_at([(10, 1.0), (20, 2.0)], 15) == 1.0 and value_at([(10, 1.0)], 5) is None
    two_av = [(0, 1000.0), (ms0 + 6 * d, 1_000_000.0)]         # huge value arrives after the open
    v = measure_wallet(sparse, len(sparse), two_av, ms0, ms0 + 30 * d, const_stop)
    assert v["frac_median"] == 0.1, v                          # 1 x 100 / 1000, not / 1,000,000

    # 5. BT-2: selection sees only fills <= t_sel; measurement counts only opens >= t_sel
    t_sel = ms0
    straddle = [_fill(t_sel - 2 * d, "BTC", "B", 1.0, 100, 0.0),
                _fill(t_sel + 1 * d, "BTC", "A", 1.0, 101, 1.0, pnl=1.0)]
    sel = selection_stats(straddle + _rt(t_sel - 10 * d, 30 * m, coin="ETH"), 3, t_sel - 30 * d, t_sel)
    assert sel["n_round_trips"] == 1 and sel["median_hold_min"] == 30.0, sel   # straddler not closed at t_sel
    fwd = measure_wallet(straddle, 2, av, t_sel, t_sel + 30 * d, const_stop)
    assert fwd["opens"] == 0, fwd                                                  # opened before t_sel

    # 6. BT-16: adds are mirrored; partial sizing uses the position after adds.
    #    AV 1000, leader 1 BTC @100 -> $30 mirror; cap = 0.005*300/0.025 = $60.
    adds = [_fill(ms0 + 1 * d, "BTC", "B", 1.0, 100, 0.0),
            _fill(ms0 + 1 * d + m, "BTC", "B", 1.0, 100, 1.0),        # add $30 -> $60 (at cap)
            _fill(ms0 + 1 * d + 2 * m, "BTC", "B", 1.0, 100, 2.0),    # add wanted $30, room $0 -> capped
            _fill(ms0 + 1 * d + 3 * m, "BTC", "B", 0.2, 100, 3.0),    # add wanted $6 -> below min
            _fill(ms0 + 1 * d + 4 * m, "BTC", "A", 1.6, 100, 3.2),    # leader cuts 50% -> we cut $30
            _fill(ms0 + 1 * d + 9 * m, "BTC", "A", 1.6, 100, 1.6)]    # close
    rt = reconstruct(adds)[0][0]
    mr = mirror_trip(rt, av, 0.025)
    assert (mr.adds_total, mr.adds_exec, mr.adds_capped, mr.adds_below_min) == (4 - 1, 1, 1, 1), mr
    assert mr.partials_exec == 1 and mr.partials_skipped_below_min == 0, mr

    # 7. PO $10 partial rule
    def one(cuts, open_sz=1.0):
        fs = [_fill(ms0, "BTC", "B", open_sz, 100, 0.0)]
        pos, tt = open_sz, ms0
        for c in cuts:
            tt += m
            fs.append(_fill(tt, "BTC", "A", pos * c, 100, pos))
            pos -= pos * c
        fs.append(_fill(tt + m, "BTC", "A", pos, 100, pos))
        return mirror_trip(reconstruct(fs)[0][0], av, 0.025)
    r1 = one([0.2])            # $30 position: cut $6 < $10, remainder $24 >= $10 -> skip and log
    assert (r1.partials_skipped_below_min, r1.partials_closed_all, r1.partials_exec) == (1, 0, 0), r1
    r2 = one([0.7])            # cut $21, remainder $9 < $10 -> close all
    assert (r2.partials_closed_all, r2.partials_exec) == (1, 0), r2
    r3 = one([0.5], open_sz=0.5)   # $15 position: cut $7.5 and remainder $7.5 -> close all
    assert r3.partials_closed_all == 1 and r3.partials_skipped_below_min == 0, r3
    r4 = one([0.4])            # cut $12, remainder $18 -> executed
    assert r4.partials_exec == 1, r4
    tiny = mirror_trip(reconstruct(_rt(ms0, m))[0][0], [(0, 100_000.0)], 0.025)
    assert tiny.status == "open_below_min" and abs(tiny.mirror_usd - 0.3) < 1e-9

    # 8. cheap gates
    g = Gates()
    ok = {"n_round_trips": 30, "median_hold_min": 60.0, "maker_share": 0.1, "liquidation": False}
    assert stage_b_fails("user", ok, g) == []
    assert stage_b_fails("vault", ok, g) == ["role_vault"]
    assert stage_b_fails("user", {**ok, "maker_share": 0.8}, g) == ["maker_share_above_max"]
    assert stage_b_fails("user", {**ok, "median_hold_min": 10.0}, g) == ["median_hold_below_min"]
    assert stage_b_fails("user", {**ok, "n_round_trips": 20}, g) == ["too_few_round_trips"]
    assert stage_b_fails("user", {**ok, "liquidation": True}, g) == ["liquidation_in_selection_window"]
    assert "hlp" in stage_a(HLP_VAULT, {}, 0, d, g)["fails"]

    # 9. Kaplan-Meier median and dispersion
    assert km_median([(10, True), (20, False), (30, True), (40, True)]) == 30
    assert km_median([(10, False), (20, False)]) is None
    dd = dispersion([5, 1, 3, 2, 4])
    assert (dd["min"], dd["p25"], dd["median"], dd["p75"], dd["max"]) == (1, 2, 3, 4, 5)

    # 10. ATR stop uses only bars closed before the entry
    bars = [{"t": i * 3_600_000, "T": (i + 1) * 3_600_000 - 1, "o": "100", "h": "101", "l": "99",
             "c": "100"} for i in range(20)]
    sp = atr_stop_pct(bars, 20 * 3_600_000, 100.0)
    assert sp is not None and abs(sp - 0.04) < 1e-12, sp
    bars_future = bars + [{"t": 20 * 3_600_000, "T": 21 * 3_600_000 - 1, "o": "100", "h": "200",
                           "l": "50", "c": "100"}]
    assert atr_stop_pct(bars_future, 20 * 3_600_000, 100.0) == sp
    assert atr_stop_pct(bars[:5], 5 * 3_600_000, 100.0) is None

    # 11. drift sign
    cs = {"BTC": [{"t": 2 * m + i * m, "T": 3 * m + i * m - 1, "c": str(100 + i)} for i in range(20)]}
    dr = drift_after_open(closed[:1], cs)
    assert abs(dr[1][0] - 100.0) < 1e-6        # +1 min: close 101 vs 100 long -> +100 bps

    # 12. rate budget waits instead of exceeding the weight per minute
    clock = [0.0]
    slept: list[float] = []
    b = WeightBudget(100, clock=lambda: clock[0], sleep=lambda s_: (slept.append(s_), clock.__setitem__(0, clock[0] + s_)))
    b.spend(60)
    b.spend(60)
    assert slept and abs(clock[0] - 60.0) < 1e-9 and b.total == 120

    # 13. end to end with a fake client: point-in-time selection, gates, forward measurement
    end = 400 * d
    t_sel2, sel0 = end - 30 * d, end - 60 * d

    def lb_row(addr, av_now, pre_pnl):
        return {"ethAddress": addr, "accountValue": str(av_now),
                "windowPerformances": [["day", {"pnl": "0"}], ["week", {"pnl": "0"}],
                                       ["month", {"pnl": "1000"}], ["allTime", {"pnl": str(pre_pnl + 1000)}]]}

    def port(av_pts, pnl_pts):
        return {"perpAllTime": {"accountValueHistory": [[t_, str(v_)] for t_, v_ in av_pts],
                                "pnlHistory": [[t_, str(v_)] for t_, v_ in pnl_pts]}}

    good_av = [(0, 50_000.0)]
    good_pnl = [(0, 0.0), (sel0, 100.0), (t_sel2, 5_100.0)]

    def active(start, n, hold=60 * m, crossed=True):
        out = []
        for k in range(n):
            out += _rt(start + k * d // 2, hold, crossed=crossed)
        return out
    A, B, C, D_, E, F, G = (f"0x{c * 40}" for c in "abcdef1")
    rows = [lb_row(A, 60_000, 9_000), lb_row(B, 60_000, 8_000), lb_row(C, 60_000, 7_000),
            lb_row(D_, 5_000_000, 6_000), lb_row(E, 60_000, 5_000), lb_row(F, 60_000, 4_000),
            lb_row(G, 60_000, 3_000), lb_row(HLP_VAULT, 1e8, 1e7)]
    # B and C rank above A on selection P&L, so the top phase examines B (vault), C (maker)
    # and then A; the random phase is left with G only (deterministic, seed-independent).
    ports = {A: port(good_av, [(0, 0.0), (sel0, 0.0), (t_sel2, 9_000.0)]),
             B: port(good_av, [(0, 0.0), (sel0, 0.0), (t_sel2, 20_000.0)]),
             C: port(good_av, [(0, 0.0), (sel0, 0.0), (t_sel2, 15_000.0)]),
             D_: port([(0, 5_000.0), (end - d, 5_000_000.0)], good_pnl),      # big NOW, small at t_sel
             E: port([(end - 100 * d, 50_000.0)], [(end - 100 * d, 0.0), (t_sel2, 5_000.0)]),  # young
             F: port(good_av, [(0, 0.0), (sel0, 5_000.0), (t_sel2, 4_000.0)]),                # lost in window
             G: port(good_av, [(0, 0.0), (sel0, 0.0), (t_sel2, 2_000.0)])}
    roles = {A: "user", B: "vault", C: "user", G: "user"}
    fl = {A: active(sel0, 30) + _rt(t_sel2 + 2 * d, 60 * m) + _rt(end - d, 30 * m),
          B: active(sel0, 30), C: active(sel0, 30, crossed=False), G: active(sel0, 30) + _rt(t_sel2 + d, 90 * m)}
    c1h = [{"t": t_sel2 - 3 * d + i * 3_600_000, "T": t_sel2 - 3 * d + (i + 1) * 3_600_000 - 1,
            "o": "100", "h": "101", "l": "99", "c": "100"} for i in range(34 * 24)]
    c1m = [{"t": end - 3 * d + i * m, "T": end - 3 * d + (i + 1) * m - 1, "c": "100.5"} for i in range(3 * 1440)]
    fake = _FakeClient(rows, ports, roles, fl, {("BTC", "1h"): c1h, ("BTC", "1m"): c1m})
    ns = argparse.Namespace(wallets=2, pool=20, max_fetch=10, seed=3, select_days=30, measure_days=30,
                            min_round_trips=25)
    tmp = Path(tempfile.mkdtemp(prefix="hl_selftest_"))
    try:
        summ = run_sample(fake, ns, end, tmp, log=lambda *_: None)
        assert (tmp / "summary.json").exists() and (tmp / "raw" / "leaderboard.json.gz").exists()
        sel_addrs = {x: w["group"] for x, w in summ["wallets"].items()}
        assert sel_addrs == {A: "top_by_selection_pnl", G: "random_from_gate_passers"}, sel_addrs
        fa, fb = summ["pool"]["portfolio_gate_fail_reasons"], summ["pool"]["activity_gate_fail_reasons"]
        assert fa.get("account_value_below_min_at_t_sel") == 1        # D: current AV is never used
        assert fa.get("account_too_young_at_t_sel") == 1              # E
        assert fa.get("selection_window_pnl_not_positive") == 1       # F
        assert fb.get("role_vault") == 1 and fb.get("maker_share_above_max") == 1   # B, C
        wa = summ["wallets"][A]["forward"]
        assert wa["opens"] == 2 and abs(wa["opens_per_day"] - round(2 / 30, 4)) < 1e-9, wa
        assert wa["stop_source_counts"] == {"atr_1h": 2} and abs(wa["stop_pct_median"] - 0.04) < 1e-9
        assert wa["drift"]["+1min"]["n"] == 1 and abs(wa["drift"]["+1min"]["median_bps"] - 50.0) < 1e-6
        assert summ["dispersion_across_wallets"]["opens_per_day"]["n"] == 2
        assert HLP_VAULT not in summ["wallets"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest OK (13 checks)")


# ================================================================ main
def main() -> None:
    ap = argparse.ArgumentParser(description="Exploratory Hyperliquid sampler (public data, no keys).")
    ap.add_argument("--selftest", action="store_true", help="offline checks only, no network")
    ap.add_argument("--wallets", type=int, default=16, help="wallets to measure (half top, half random)")
    ap.add_argument("--pool", type=int, default=100, help="leaderboard candidates checked at t_sel")
    ap.add_argument("--max-fetch", type=int, default=48, help="cap on wallets whose fills are downloaded")
    ap.add_argument("--select-days", type=int, default=30)
    ap.add_argument("--measure-days", type=int, default=30, help="<= 30 (see pre-selection P&L)")
    ap.add_argument("--min-round-trips", type=int, default=25)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--weight-per-min", type=float, default=800.0)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    if not 3 <= a.measure_days <= 30:
        ap.error("--measure-days must be between 3 and 30 (the pool uses allTime - month P&L)")
    if a.wallets < 2:
        ap.error("--wallets must be >= 2")
    now_ms = int(time.time() * 1000)
    out_dir = Path(a.out) / ("run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    print(f"hl_sample {SCRIPT_VERSION}: public read-only data, no keys. Output: {out_dir}", flush=True)
    client = HttpClient(a.weight_per_min)
    log = lambda *x: print(*x, flush=True)                     # noqa: E731
    summ = run_sample(client, a, now_ms, out_dir, log=log)
    p = summ["pool"]
    print(f"\nDone. {p['selected']} wallets measured ({p['selected_top']} top, {p['selected_random']} random); "
          f"{len(summ['errors'])} errors; {summ['run']['requests']} requests.")
    print(f"Send back this file: {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
