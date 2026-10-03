# EXPLORATORY throwaway check (public, read-only, paper-safe). NOT validation. Run OUTSIDE the bot, with the bot stopped:
#   uv run python docs\sdlc\copytrade-v1\research\scripts\candidate_rank_check.py
#   (options: --top 20  --window-days 180  --options A,D  (or A,B,C,D: twice as slow)  --file saved.json.gz  --selftest)
# What it does (see docs/sdlc/copytrade-v1/research/candidate-ranking.md, rules P1-P8 and the rank key):
#   1. downloads the leaderboard ONCE, saves it (gzip) under research/data/candidate_ranking/ (gitignored),
#   2. prints how many rows survive each prefilter rule, and the distribution of the row fields,
#   3. for the top N wallets of option D (recommended) and of option A (served order, today's bot) it asks Hyperliquid
#      for the FIRST page of fills of the scoring window (one call per wallet, as the bot's backfill starts), one wallet
#      every 6 s (a full page costs ~120 of the 1,200 weight/min per IP), and prints a verdict per wallet:
#        empty       = 0 fills in the window (EX2)
#        too_active  = a full first page (2,000 fills) spanning less than 1 day (EX1)
#        truncated?  = a full first page whose first fill is more than 1 day after the window start (10k-fill cap hit)
#        ok          = anything else (copyable-looking at first sight; the bot's gates still decide)
#   4. prints the pre-registered verdict of the prefilter (PASS / PARTIAL / KILL).
import argparse, gzip, json, math, re, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

LB = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO = "https://api.hyperliquid.xyz/info"
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"
DAY_MS = 86_400_000
PAGE = 2000
# Pre-registered prefilter parameters (candidate-ranking.md). Do not tune them on this run's output.
MIN_AV = 10_000.0          # P3 = gate.min_account_value_usd (G11)
MIN_TURN_M = 2.0           # P4 month volume >= 2 x account value (derived from G2 + G12)
MAX_TURN_M = 500.0         # P5 month volume <= 500 x account value (OF)
MAX_TURN_D = 50.0          # P5 day volume <= 50 x account value (OF)
MIN_BPS = 10.0             # P7 edge per traded dollar, month and before (bps)
MAX_RET_M = 1.0            # P8 month pnl / account value <= 1.0
EDGE_CAP_BPS = 50.0        # rank key cap
ADDR = re.compile(r"^0x[0-9a-f]{40}$")
WINDOWS = ("day", "week", "month", "allTime")


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def parse(row):
    """Row -> flat dict of floats (None when missing/unreadable)."""
    wp = {}
    for item in row.get("windowPerformances") or []:
        if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], dict):
            wp[item[0]] = item[1]
    r = {"addr": str(row.get("ethAddress", "")).lower(), "av": num(row.get("accountValue"))}
    for w in WINDOWS:
        for f in ("pnl", "roi", "vlm"):
            r[f"{f}_{w}"] = num((wp.get(w) or {}).get(f))
    return r


def derived(r):
    av, vm, va = r["av"], r["vlm_month"], r["vlm_allTime"]
    r["turn_m"] = vm / av if av and vm is not None else None
    r["turn_d"] = r["vlm_day"] / av if av and r["vlm_day"] is not None else None
    r["bps_m"] = 1e4 * r["pnl_month"] / vm if vm else None
    prior_v = va - vm if va is not None and vm is not None else None
    r["pnl_prior"] = r["pnl_allTime"] - r["pnl_month"] if r["pnl_allTime"] is not None and r["pnl_month"] is not None else None
    r["bps_p"] = 1e4 * r["pnl_prior"] / prior_v if prior_v and prior_v > 0 and r["pnl_prior"] is not None else None
    r["ret_m"] = r["pnl_month"] / av if av and r["pnl_month"] is not None else None
    return r


NEEDED = ("av", "pnl_day", "vlm_day", "pnl_week", "vlm_week", "pnl_month", "vlm_month", "pnl_allTime", "vlm_allTime")
RULES = [  # (id, description, predicate) applied in this order; a row must pass all of them
    ("P1", "readable row (address, accountValue, pnl and vlm of all 4 windows)",
     lambda r: bool(ADDR.match(r["addr"])) and all(r[k] is not None for k in NEEDED)),
    ("P2", "not an excluded address (HLP)", lambda r: r["addr"] != HLP),
    ("P3", f"accountValue >= {MIN_AV:,.0f} (G11)", lambda r: r["av"] >= MIN_AV),
    ("P4", f"active: week vlm > 0 and month vlm >= {MIN_TURN_M} x AV", lambda r: r["vlm_week"] > 0 and r["turn_m"] >= MIN_TURN_M),
    ("P5", f"not hyperactive: month vlm <= {MAX_TURN_M:.0f} x AV and day vlm <= {MAX_TURN_D:.0f} x AV",
     lambda r: r["turn_m"] <= MAX_TURN_M and r["turn_d"] <= MAX_TURN_D),
    ("P6", "profitable now and before: month pnl > 0 and (allTime - month) pnl > 0",
     lambda r: r["pnl_month"] > 0 and r["pnl_prior"] > 0),
    ("P7", f"edge per traded dollar >= {MIN_BPS:.0f} bps in the month AND before it",
     lambda r: r["bps_m"] is not None and r["bps_p"] is not None and r["bps_m"] >= MIN_BPS and r["bps_p"] >= MIN_BPS),
    ("P8", f"sanity: month pnl / AV <= {MAX_RET_M}", lambda r: r["ret_m"] <= MAX_RET_M),
]


def edge_key(r):
    return min(r["bps_m"], r["bps_p"], EDGE_CAP_BPS)


def rank_d(rows):
    """Option D: rows passing P1-P8, by min(bps month, bps before, 50) desc, then allTime pnl desc, then address."""
    ok = [r for r in rows if all(p(r) for _, _, p in RULES)]
    return sorted(ok, key=lambda r: (-edge_key(r), -r["pnl_allTime"], r["addr"]))


def base(rows):  # what today's bot uses: valid address, not excluded, AV not below the floor (missing AV kept)
    return [r for r in rows if ADDR.match(r["addr"]) and r["addr"] != HLP and not (r["av"] is not None and r["av"] < MIN_AV)]


def options(rows):
    b = base(rows)
    return {
        "A": b,                                                                                   # served order
        "B": sorted([r for r in b if r["pnl_allTime"] is not None], key=lambda r: (-r["pnl_allTime"], r["addr"])),
        "C": sorted([r for r in b if r["roi_month"] is not None], key=lambda r: (-r["roi_month"], r["addr"])),
        "D": rank_d(rows),
    }


def q(xs, p):
    s = sorted(xs)
    if not s:
        return None
    i = p * (len(s) - 1)
    lo = int(i)
    return s[lo] + (s[min(lo + 1, len(s) - 1)] - s[lo]) * (i - lo)


def dist(name, xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return f"  {name:<22} n=0"
    f = lambda v: f"{v:.4g}"  # noqa: E731
    return (f"  {name:<22} n={len(xs):<6} min={f(min(xs))} p10={f(q(xs, .1))} p25={f(q(xs, .25))} med={f(q(xs, .5))} "
            f"p75={f(q(xs, .75))} p90={f(q(xs, .9))} max={f(max(xs))} zero={sum(1 for x in xs if x == 0)}")


def summarise(rows):
    print(f"rows: {len(rows)}")
    alive = rows
    for rid, desc, pred in RULES:
        alone = sum(1 for r in rows if _safe(pred, r)) if rid != "P1" else sum(1 for r in rows if pred(r))
        alive = [r for r in alive if pred(r)]
        print(f"  {rid} {desc}\n       pass alone: {alone:>6}   survive P1..{rid}: {len(alive):>6}")
    for label, sub in (("ALL readable rows", [r for r in rows if RULES[0][2](r)]), ("SURVIVORS of P1-P8", alive)):
        print(f"distribution, {label}:")
        for k in ("av", "vlm_month", "turn_m", "turn_d", "pnl_month", "pnl_allTime", "roi_month", "roi_allTime", "bps_m", "bps_p", "ret_m"):
            print(dist(k, [r[k] for r in sub]))
    if alive:
        capped = sum(1 for r in alive if edge_key(r) >= EDGE_CAP_BPS)
        print(f"rank key at the {EDGE_CAP_BPS:.0f} bps cap (ties broken by allTime pnl): {capped} of {len(alive)}")
    return alive


def _safe(pred, r):
    try:
        return RULES[0][2](r) and pred(r)
    except TypeError:
        return False


def call(url, body=None, tries=5):
    data = json.dumps(body).encode() if body is not None else None
    for a in range(tries):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "tradestuff-research/rank-check"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and a < tries - 1:
                time.sleep(10 * 2 ** a)
                continue
            return e.code, None
        except Exception as e:  # noqa: BLE001 - throwaway research tool
            if a < tries - 1:
                time.sleep(10 * 2 ** a)
                continue
            return repr(e)[:120], None
    return "gave up", None


def classify(fills, start_ms):
    """Verdict on the FIRST page of userFillsByTime (ascending from start_ms), as the bot's backfill sees it."""
    if not fills:
        return "empty", {}
    ts = [int(f["time"]) for f in fills]
    span_d = (max(ts) - min(ts)) / DAY_MS
    notional = sum(float(f["sz"]) * float(f["px"]) for f in fills)
    maker = sum(float(f["sz"]) * float(f["px"]) for f in fills if f.get("crossed") is False)
    core = sum(1 for f in fills if not (str(f["coin"]).startswith("@") or "/" in str(f["coin"]) or ":" in str(f["coin"])))
    info = {"fills": len(fills), "span_d": round(span_d, 2), "first": datetime.fromtimestamp(min(ts) / 1000, timezone.utc).strftime("%Y-%m-%d"),
            "maker_share": round(maker / notional, 2) if notional > 0 else None, "core_perp_share": round(core / len(fills), 2)}
    if len(fills) >= PAGE and span_d < 1.0:
        return "too_active", info
    if len(fills) >= PAGE and min(ts) > start_ms + DAY_MS:
        return "truncated?", info
    return "ok", info


def check_fills(label, wallets, window_days, pause_s, fetch=None):
    fetch = fetch or (lambda body: call(INFO, body))
    start = int(time.time() * 1000) - window_days * DAY_MS
    counts = {"ok": 0, "empty": 0, "too_active": 0, "truncated?": 0, "failed": 0}
    print(f"\nfirst-page fill check, option {label}, {len(wallets)} wallets, window {window_days} d:")
    for i, r in enumerate(wallets):
        st, fills = fetch({"type": "userFillsByTime", "user": r["addr"], "startTime": start, "aggregateByTime": True})
        if st != 200 or not isinstance(fills, list):
            verdict, info = "failed", {"http": st}
        else:
            verdict, info = classify(fills, start)
        counts[verdict] += 1
        row = f"av={r['av']:.0f} turn_m={r['turn_m']:.1f} bps_m={r['bps_m']:.1f}" if r.get("turn_m") is not None and r.get("bps_m") is not None else ""
        print(f"  {i + 1:>2} {r['addr'][:12]} {verdict:<11} {info} {row}")
        if i + 1 < len(wallets):
            time.sleep(pause_s)
    print(f"  option {label}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return counts


def verdict(d, a, n):
    """Pre-registered (candidate-ranking.md): scaled to n wallets, 14/20 ok and +6 over served order."""
    need, margin, kill = math.ceil(0.70 * n), math.ceil(0.30 * n), math.ceil(0.50 * n)
    if d["ok"] >= need and (a is None or d["ok"] >= a["ok"] + margin):
        return "PASS"
    if d["ok"] < kill:
        return "KILL (redesign the prefilter; row fields do not separate copyable wallets)"
    return "PARTIAL (log it; at most one pre-registered variant may be tried)"


def repo_root():
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "docs" / "sdlc" / "copytrade-v1").is_dir():
            return p
    return Path.cwd()


def selftest():
    def row(addr, av, d, w, m, a):
        return {"ethAddress": addr, "accountValue": str(av), "displayName": None, "prize": 0,
                "windowPerformances": [[k, {"pnl": str(v[0]), "roi": str(v[0] / av), "vlm": str(v[1])}]
                                       for k, v in zip(WINDOWS, (d, w, m, a), strict=True)]}
    h = lambda i: "0x" + f"{i:040x}"  # noqa: E731
    rows = [parse(x) for x in [
        row(h(1), 50_000, (0, 0), (0, 0), (0, 0), (5_000, 1e6)),                     # empty now: fails P4
        row(h(2), 2_000_000, (1e3, 5e8), (5e3, 3e9), (2e4, 1e10), (1e6, 1e11)),     # HFT: fails P5
        row(h(3), 100_000, (500, 2e5), (2e3, 1e6), (8e3, 4e6), (5e4, 3e7)),          # good: bps_m 20, bps_p ~16
        row(h(4), 5_000, (10, 1e4), (50, 5e4), (200, 2e5), (900, 1e6)),              # small: fails P3
        row(h(5), 30_000, (0, 1e3), (100, 2e4), (3e4, 9e4), (3.5e4, 2e5)),           # month ret 1.0 -> passes P8 at edge
        row(h(6), 30_000, (0, 1e3), (100, 2e4), (4e4, 9e4), (4.5e4, 2e5)),           # month ret 1.33: fails P8
        row(h(7), 80_000, (100, 1e5), (500, 5e5), (4e3, 2e6), (-1e4, 2e7)),          # prior pnl negative: fails P6
        row(HLP, 1e8, (1, 1e6), (1, 1e7), (1, 1e8), (1, 1e9)),                       # HLP: fails P2
        {"ethAddress": "0xbad", "accountValue": "x"},                                   # unreadable: fails P1
    ]]
    for r in rows:
        derived(r)
    d = rank_d(rows)
    assert [r["addr"] for r in d] == [h(5), h(3)], [r["addr"] for r in d]   # h5: min(3333, 1000, cap 50) = 50 > h3 ~16
    assert abs(rows[2]["bps_m"] - 20.0) < 1e-9 and abs(rows[2]["bps_p"] - 1e4 * 42_000 / 26_000_000) < 1e-9
    assert [r["addr"] for r in options(rows)["A"]][:3] == [h(1), h(2), h(3)]
    t0 = 1_000 * DAY_MS
    assert classify([], t0)[0] == "empty"
    assert classify([{"time": t0 + i, "sz": "1", "px": "1", "coin": "BTC"} for i in range(PAGE)], t0)[0] == "too_active"
    assert classify([{"time": t0 + 2 * DAY_MS + i * 3_600_000, "sz": "1", "px": "1", "coin": "BTC"} for i in range(PAGE)], t0)[0] == "truncated?"
    assert classify([{"time": t0 + i * 3_600_000, "sz": "1", "px": "1", "coin": "BTC"} for i in range(50)], t0)[0] == "ok"
    fake = lambda body: (200, [])  # noqa: E731
    c = check_fills("D", d, 180, 0, fetch=fake)
    assert c["empty"] == 2 and verdict({"ok": 14}, {"ok": 8}, 20) == "PASS" and verdict({"ok": 14}, {"ok": 9}, 20).startswith("PARTIAL")
    assert verdict({"ok": 9}, None, 20).startswith("KILL")
    summarise(rows)
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--window-days", type=int, default=180)
    ap.add_argument("--options", default="A,D", help="which rankings get the fill check, e.g. A,D or A,B,C,D")
    ap.add_argument("--file", help="use a saved leaderboard (.json or .json.gz) instead of downloading")
    ap.add_argument("--pause", type=float, default=6.0, help="seconds between fill calls")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.file:
        opener = gzip.open if a.file.endswith(".gz") else open
        with opener(a.file, "rt", encoding="utf-8") as fh:
            doc = json.load(fh)
    else:
        st, doc = call(LB)
        print("leaderboard HTTP:", st)
        if st != 200:
            sys.exit(1)
        out = repo_root() / "research" / "data" / "candidate_ranking"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"leaderboard_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(doc, fh)
        print("saved:", path)
    rows = [derived(parse(r)) for r in doc["leaderboardRows"] if isinstance(r, dict)]
    print("EXPLORATORY. Today's leaderboard only (survivorship-biased); row fields are self-reported. Not validation.")
    summarise(rows)
    opts = options(rows)
    k = 50
    topd = {r["addr"] for r in opts["D"][:k]}
    for name in "ABC":
        top = opts[name][:k]
        fails = sum(1 for r in top if not (RULES[0][2](r) and RULES[3][2](r) and RULES[4][2](r)))
        print(f"option {name}: of its first {k}, {len(topd & {r['addr'] for r in top})} are in D's first {k}; "
              f"{fails} fail D's readability/activity/hyperactivity rules (P1, P4, P5)")
    print(f"option D first {k}: " + " ".join(r["addr"][:10] for r in opts["D"][:k]))
    res = {}
    for name in [x.strip().upper() for x in a.options.split(",") if x.strip()]:
        res[name] = check_fills(name, opts[name][: a.top], a.window_days, a.pause)
    if "D" in res:
        print(f"\nPRE-REGISTERED VERDICT (n={a.top}): {verdict(res['D'], res.get('A'), a.top)}")
    print("Send this whole output to the CTO.")


if __name__ == "__main__":
    main()
