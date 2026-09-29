"""EXPLORATORY - SURVIVORSHIP-BIASED (today's leaderboard) - NOT VALIDATION.

Pull a small sample from Hyperliquid's PUBLIC endpoints (no keys, read-only) and
estimate, per wallet:
  * position opens per day, median holding time, round-trip count and fill span
  * share of opens whose mirrored size on a $300 wallet is below the $10 minimum
    (before and after the 1%-risk cap), and share of mirrored partial reduces < $10
  * adverse price drift after the leader's opening fill at +1, +2, +5, +15 min
    (1-minute candles only; per-second decay needs our own recorded trade stream)

STATUS 2026-09-29: NOT RUN against the live API. The research sandbox's egress
proxy refused api.hyperliquid.xyz and stats-data.hyperliquid.xyz. Only the
offline --selftest (synthetic fills) was executed. The endpoint shapes follow the
public docs and third-party mirrors (Chainstack, QuickNode) and must be checked on
first run.

Usage:
  python3 hl_sample.py --selftest
  python3 hl_sample.py --wallets 10 --days 30 --out ../../../../../research/data/hl_sample
Raw JSON goes under research/data/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
MIN_ORDER_USD = 10.0
WALLET_USD = 300.0
RISK = 0.01
ASSUMED_STOP_PCT = 0.025      # replace with ATR-based stop per coin when available
REQUEST_GAP_S = 1.5           # stays far below the 1200 weight/min IP budget


# ---------------------------------------------------------------- HTTP (public)
def post_info(body: dict) -> object:
    req = urllib.request.Request(INFO_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    time.sleep(REQUEST_GAP_S)
    return data


def get_leaderboard() -> list[dict]:
    with urllib.request.urlopen(LEADERBOARD_URL, timeout=60) as r:
        return json.loads(r.read())["leaderboardRows"]


def fills_by_time(user: str, start_ms: int, end_ms: int) -> list[dict]:
    """Paginate forward; the API returns <=2000 fills per call and only the
    10,000 most recent fills exist."""
    out: list[dict] = []
    cursor = start_ms
    while True:
        batch = post_info({"type": "userFillsByTime", "user": user, "startTime": cursor,
                           "endTime": end_ms, "aggregateByTime": True})
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 2000:
            break
        cursor = max(f["time"] for f in batch) + 1
    seen, uniq = set(), []
    for f in sorted(out, key=lambda f: (f["time"], f.get("tid", 0))):
        k = (f.get("tid"), f.get("hash"), f["time"], f["coin"], f["sz"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


# ---------------------------------------------------------------- reconstruction
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
    net_pnl: float = 0.0
    avg_px: float = 0.0


def reconstruct(fills: list[dict]) -> tuple[list[RoundTrip], list[RoundTrip]]:
    """Returns (closed round trips, still-open round trips). A flip is split into a
    close and a new open. Positions already open at the first fill are skipped
    (same rule as the product: ignore positions held before we started)."""
    closed: list[RoundTrip] = []
    live: dict[str, RoundTrip] = {}
    skip_coin: dict[str, bool] = {}
    for f in sorted(fills, key=lambda f: (f["time"], f.get("tid", 0))):
        coin = f["coin"]
        if coin.startswith("@") or "/" in coin:      # spot
            continue
        start = float(f["startPosition"])
        sz = float(f["sz"])
        px = float(f["px"])
        delta = sz if f["side"] == "B" else -sz
        end = start + delta
        pnl = float(f.get("closedPnl", 0.0)) - float(f.get("fee", 0.0))
        if coin not in live and coin not in skip_coin:
            skip_coin[coin] = abs(start) > 1e-12     # pre-existing position: ignore until flat
        if skip_coin.get(coin):
            if abs(end) < 1e-12 or (start != 0 and math.copysign(1, end) != math.copysign(1, start)):
                skip_coin[coin] = False
                if abs(end) > 1e-12:                 # flip out of an ignored position = fresh open
                    live[coin] = RoundTrip(coin, 1 if end > 0 else -1, f["time"], px, abs(end),
                                           max_abs_sz=abs(end), avg_px=px)
            continue
        rt = live.get(coin)
        if rt is None:
            if abs(end) < 1e-12:
                continue
            live[coin] = RoundTrip(coin, 1 if end > 0 else -1, f["time"], px, abs(end),
                                   max_abs_sz=abs(end), avg_px=px, net_pnl=pnl)
            continue
        same_side = abs(end) > 1e-12 and math.copysign(1, end) == rt.direction
        rt.net_pnl += pnl
        if same_side and abs(end) > abs(start):                       # add
            rt.adds += 1
            if (px - rt.avg_px) * rt.direction < 0:
                rt.adds_while_losing += 1
            rt.avg_px = (rt.avg_px * abs(start) + px * (abs(end) - abs(start))) / abs(end)
            rt.max_abs_sz = max(rt.max_abs_sz, abs(end))
        elif same_side:                                               # partial reduce
            rt.reduces.append((abs(start) - abs(end)) / abs(start))
        else:                                                         # close or flip
            rt.close_ms = f["time"]
            closed.append(rt)
            del live[coin]
            if abs(end) > 1e-12:
                live[coin] = RoundTrip(coin, 1 if end > 0 else -1, f["time"], px, abs(end),
                                       max_abs_sz=abs(end), avg_px=px)
    return closed, list(live.values())


# ---------------------------------------------------------------- per-wallet stats
def account_value_at(history: list[list], t_ms: int, fallback: float) -> float:
    best = None
    for ts, v in history:
        if ts <= t_ms:
            best = float(v)
    return best if best and best > 0 else fallback


def wallet_stats(fills: list[dict], acct_hist: list[list], acct_now: float) -> dict:
    closed, open_ = reconstruct(fills)
    rts = closed + open_
    if not fills or not rts:
        return {"round_trips": 0}
    span_d = max(1e-9, (fills[-1]["time"] - fills[0]["time"]) / 86_400_000)
    holds = [(r.close_ms - r.open_ms) / 60_000 for r in closed]
    below_raw = below_capped = 0
    partial_total = partial_below = 0
    for r in rts:
        av = account_value_at(acct_hist, r.open_ms, acct_now)
        frac = r.open_sz * r.open_px / av
        mirror = frac * WALLET_USD
        capped = min(mirror, RISK * WALLET_USD / ASSUMED_STOP_PCT)
        below_raw += mirror < MIN_ORDER_USD
        below_capped += capped < MIN_ORDER_USD
        pos = capped
        for cut in r.reduces:
            partial_total += 1
            if pos * cut < MIN_ORDER_USD:
                partial_below += 1
            else:
                pos *= (1 - cut)
    adds = sum(r.adds for r in rts)
    return {
        "fills": len(fills), "fill_span_days": round(span_d, 2),
        "round_trips": len(closed), "open_positions": len(open_),
        "opens_per_day": round(len(rts) / span_d, 2),
        "median_hold_min": round(statistics.median(holds), 1) if holds else None,
        "share_open_below_min_raw": round(below_raw / len(rts), 3),
        "share_open_below_min_after_cap": round(below_capped / len(rts), 3),
        "share_partials_below_min": round(partial_below / partial_total, 3) if partial_total else None,
        "adds_while_losing_share": round(sum(r.adds_while_losing for r in rts) / adds, 3) if adds else None,
        "win_rate": round(sum(r.net_pnl > 0 for r in closed) / len(closed), 3) if closed else None,
        "net_pnl_closed": round(sum(r.net_pnl for r in closed), 2),
    }


def drift_after_open(rts: list[RoundTrip], candles: dict[str, list[dict]]) -> dict[int, list[float]]:
    """Adverse drift in bps at +k minutes: positive = price moved in the leader's
    favour, i.e. what a copier arriving k minutes late pays."""
    out: dict[int, list[float]] = {1: [], 2: [], 5: [], 15: []}
    for r in rts:
        cs = candles.get(r.coin)
        if not cs:
            continue
        for k in out:
            target = r.open_ms + k * 60_000
            c = next((c for c in cs if c["t"] <= target < c["T"] + 1), None)
            if c:
                out[k].append(r.direction * (float(c["c"]) - r.open_px) / r.open_px * 1e4)
    return out


# ---------------------------------------------------------------- self-test
def selftest() -> None:
    def f(t, coin, side, sz, px, start, pnl=0.0, fee=0.0):
        return {"time": t, "coin": coin, "side": side, "sz": str(sz), "px": str(px),
                "startPosition": str(start), "closedPnl": str(pnl), "fee": str(fee), "tid": t}
    m = 60_000
    fills = [
        f(0, "ETH", "B", 1.0, 100, 1.0),                     # pre-existing long: ignored
        f(1 * m, "ETH", "A", 2.0, 101, 2.0, pnl=2.0),        # closes pre-existing -> flat
        f(2 * m, "BTC", "B", 1.0, 100, 0.0),                 # open long 1
        f(3 * m, "BTC", "B", 1.0, 98, 1.0),                  # add while losing
        f(4 * m, "BTC", "A", 0.8, 102, 2.0, pnl=3.2),        # reduce 40%
        f(10 * m, "BTC", "A", 3.2, 103, 1.2, pnl=3.6),       # flip: close 1.2, open short 2.0
        f(20 * m, "BTC", "B", 2.0, 104, -2.0, pnl=-2.0),     # close short
        f(30 * m, "SOL", "A", 5.0, 20, 0.0),                 # open short, still open
    ]
    closed, live = reconstruct(fills)
    assert [(r.coin, r.direction) for r in closed] == [("BTC", 1), ("BTC", -1)], closed
    assert closed[0].adds == 1 and closed[0].adds_while_losing == 1
    assert abs(closed[0].reduces[0] - 0.4) < 1e-9
    assert closed[0].close_ms == 10 * m and closed[1].open_ms == 10 * m
    assert abs(closed[0].net_pnl - 6.8) < 1e-9 and abs(closed[1].net_pnl + 2.0) < 1e-9
    assert [(r.coin, r.direction) for r in live] == [("SOL", -1)]
    s = wallet_stats(fills, [[0, "1000"]], 1000.0)
    # BTC open: 1*100/1000*300 = $30; after-flip short: 2*103/1000*300 = $61.8; SOL: $30
    assert s["share_open_below_min_raw"] == 0.0
    # BTC long: $30 position, 40% cut = $12 -> executable
    assert s["share_partials_below_min"] == 0.0
    tiny = wallet_stats(fills, [[0, "100000"]], 100000.0)   # 100x bigger account -> $0.30 opens
    assert tiny["share_open_below_min_raw"] == 1.0
    cs = {"BTC": [{"t": 2 * m + i * m, "T": 3 * m + i * m - 1, "c": str(100 + i)} for i in range(20)]}
    d = drift_after_open(closed[:1], cs)
    assert abs(d[1][0] - 100.0) < 1e-6        # +1 min: close 101 vs 100 long -> +100 bps
    print("selftest OK")


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--wallets", type=int, default=10)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--out", default="research/data/hl_sample")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = get_leaderboard()
    (out / f"leaderboard_{int(time.time())}.json").write_text(json.dumps(rows))

    def month(r: dict) -> dict:
        return dict(r["windowPerformances"]).get("month", {})

    cands = [r for r in rows if float(r["accountValue"]) >= 10_000]
    cands.sort(key=lambda r: float(month(r).get("pnl", 0)), reverse=True)
    top = cands[:200]
    rng = random.Random(a.seed)
    by_roi = sorted(top, key=lambda r: float(month(r).get("roi", 0)), reverse=True)
    sample = by_roi[: a.wallets // 2] + rng.sample(by_roi[a.wallets // 2:], a.wallets - a.wallets // 2)
    end = int(time.time() * 1000)
    start = end - a.days * 86_400_000
    results, all_rts = {}, []
    for r in sample:
        addr = r["ethAddress"]
        fills = fills_by_time(addr, start, end)
        port = dict(post_info({"type": "portfolio", "user": addr}))
        hist = port.get("perpMonth", port.get("month", {})).get("accountValueHistory", [])
        (out / f"fills_{addr}.json").write_text(json.dumps(fills))
        (out / f"portfolio_{addr}.json").write_text(json.dumps(port))
        st = wallet_stats(fills, hist, float(r["accountValue"]))
        st["account_value_now"] = float(r["accountValue"])
        results[addr] = st
        closed, live = reconstruct(fills)
        all_rts += [x for x in closed + live if x.open_ms >= end - 3 * 86_400_000]
        print(addr, st, flush=True)
    candles: dict[str, list[dict]] = {}
    for coin in sorted({x.coin for x in all_rts}):
        candles[coin] = post_info({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": "1m", "startTime": end - 3 * 86_400_000, "endTime": end}})
    drift = drift_after_open(all_rts, candles)
    summary = {"label": "EXPLORATORY, survivorship-biased (current leaderboard)",
               "wallets": results,
               "drift_bps_median": {k: (statistics.median(v) if v else None) for k, v in drift.items()},
               "drift_n": {k: len(v) for k, v in drift.items()}}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary["drift_bps_median"]), file=sys.stderr)


if __name__ == "__main__":
    main()
