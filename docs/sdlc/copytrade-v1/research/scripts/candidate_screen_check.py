# EXPLORATORY throwaway check (public, read-only, paper-safe). NOT validation. Run OUTSIDE the bot, with the bot stopped:
#   uv run python docs\sdlc\copytrade-v1\research\scripts\candidate_screen_check.py
#   (options: --ranks 21-40  --window-days 180  --file saved.json.gz  --fresh  --baseline  --pause 3  --selftest)
# Variant 2 of the candidate prefilter (candidate-ranking.md section 9, rules V1-V8 and S1-S9, pre-registered BEFORE any
# variant-2 data). Stdlib only.
#   stage 1 = option D on the leaderboard row, unchanged (imported from candidate_rank_check.py, same folder);
#   stage 2 = a screen computed ONLY from the FIRST page of fills (one userFillsByTime call per wallet, exactly the
#             backfill's page 1), on D ranks 21-40 (ranks 1-20 were seen in run 1: no tuning on seen data).
# Leaderboard: by default the OLDEST saved snapshot in research/data/candidate_ranking/ (= run 1's), so ranks 21-40
# are the 20 wallets right after the 20 already seen. --fresh downloads a new one (may then overlap run 1's wallets).
# Pacing: at least --pause s between calls, longer after a heavy page so the run stays under 1,200 weight/min per IP.
# Prints each wallet's page features and PASS/FAIL per rule, the pre-registered verdict and a SUMMARY block to paste back.
import argparse, gzip, json, math, sys, time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidate_rank_check as crc  # noqa: E402  stage 1 (P1-P8, K1), HTTP call with retries, leaderboard parsing

DAY_MS = crc.DAY_MS
MIN_MS = 60_000
PAGE = crc.PAGE                 # 2,000 rows per userFillsByTime page (API fact)
HL_FILLS_LIMIT = 10_000         # API fact; same constant as src/copytrade/selection/backfill.py (R1)
WEIGHT_PER_MIN = 1_200          # Hyperliquid REST weight per IP per minute
# REUSED gate/config defaults (04-spec section 3.4, config/*.toml). Not tuned here.
MAX_MAKER_SHARE = 0.70          # gate.max_maker_share (G13, M13 formula)
MIN_FILL_SPAN_D = 60.0          # gate.min_fill_span_days (G3)
MIN_HOLD_MIN = 15.0             # gate.min_median_hold_min (G8 floor)
MIN_EXEC_SHARE = 0.50           # gate.min_executable_share (G12, M16 flavour)
MIN_ROUND_TRIPS = 150           # gate.min_round_trips (G2)
WALLET_USD = 300.0              # paper.wallet_usd
MIN_ORDER_USD = 10.0            # sizing.min_order_usd
# NEW screen parameters (pre-registered in candidate-ranking.md section 9)
MIN_CORE_SHARE = 0.50           # prefilter.min_core_perp_share
MIN_TRIPS = 30                  # prefilter.screen_min_trips (S7/S8 not evaluable below this)
# NEW verdict-only numbers (validation run only, never config)
PASS_TENTHS, KILL_TENTHS, MIN_VALID = 5, 3, 16  # PASS >= 50% of n, KILL < 30% of n
C1_EVAL, C2_HOLD_MIN, C3_MAKER, C4_EXEC = 0.80, 30.0, 0.50, 0.70
RULE_IDS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")


class SchemaError(ValueError):
    pass


def is_core_perp(coin):  # same as src/copytrade/scoring/reconstruct.py::is_core_perp
    return not (coin.startswith("@") or "/" in coin or ":" in coin)


def dec(x, name):
    try:
        v = Decimal(str(x))
    except (InvalidOperation, ValueError):
        raise SchemaError(f"bad {name}: {x!r}") from None
    if not v.is_finite():
        raise SchemaError(f"bad {name}: {x!r}")
    return v


def norm(f):
    if not isinstance(f, dict) or not isinstance(f.get("crossed"), bool) or f.get("side") not in ("A", "B"):
        raise SchemaError(f"bad fill: {str(f)[:80]}")
    try:
        t = int(f["time"])
    except (KeyError, TypeError, ValueError):
        raise SchemaError("bad time") from None
    return {"time": t, "tid": f.get("tid"), "coin": str(f.get("coin", "")), "sz": dec(f.get("sz"), "sz"),
            "px": dec(f.get("px"), "px"), "side": f["side"], "start": dec(f.get("startPosition"), "startPosition"),
            "crossed": f["crossed"]}


def dedupe(fills):
    """F5's dedupe: sorted by (time, tid), repeats of (tid, time, coin, sz) removed."""
    seen, out = set(), []
    for f in sorted(fills, key=lambda f: (f["time"], f["tid"] if isinstance(f["tid"], int) else -1)):
        key = (f["tid"], f["time"], f["coin"], f["sz"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def trips(core):
    """Port of F5's reconstruct (position logic only): a position open at a coin's first fill is ignored until flat;
    a flip closes and opens. Returns (closed, still_open) as lists of dicts with open_ms, close_ms, open_sz, open_px."""
    live, ignoring, closed = {}, {}, []
    for f in core:
        coin, start = f["coin"], f["start"]
        end = start + (f["sz"] if f["side"] == "B" else -f["sz"])
        if coin not in live and coin not in ignoring:
            ignoring[coin] = start != 0
        if ignoring.get(coin, False):
            if end == 0 or (start != 0 and (end > 0) != (start > 0)):
                ignoring[coin] = False
                if end != 0:
                    live[coin] = {"dir": 1 if end > 0 else -1, "open_ms": f["time"], "open_sz": abs(end), "open_px": f["px"]}
            continue
        rt = live.get(coin)
        if rt is None:
            if end != 0:
                live[coin] = {"dir": 1 if end > 0 else -1, "open_ms": f["time"], "open_sz": abs(end), "open_px": f["px"]}
            continue
        if end != 0 and (end > 0) == (rt["dir"] > 0):
            continue  # add or reduce: same trip
        rt["close_ms"] = f["time"]
        closed.append(rt)
        del live[coin]
        if end != 0:
            live[coin] = {"dir": 1 if end > 0 else -1, "open_ms": f["time"], "open_sz": abs(end), "open_px": f["px"]}
    return closed, list(live.values())


def median(xs):
    s = sorted(xs)
    if not s:
        return None
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def features(raw, av):
    """Everything the screen may use, computed ONLY from the first page (raw = the API's list)."""
    ft = {"rows": len(raw), "full": len(raw) >= PAGE}
    fills = dedupe([norm(f) for f in raw])
    if not fills:
        return ft
    ts = [f["time"] for f in fills]
    core = [f for f in fills if is_core_perp(f["coin"])]
    notional = sum((f["sz"] * f["px"] for f in fills), Decimal(0))
    core_not = sum((f["sz"] * f["px"] for f in core), Decimal(0))
    span_d = (max(ts) - min(ts)) / DAY_MS
    ft.update(first_ms=min(ts), last_ms=max(ts), span_d=span_d, core_fills=len(core),
              fills_per_day=len(raw) / span_d if span_d > 0 else math.inf,
              core_share=float(core_not / notional) if notional > 0 else None,
              maker_share=float(sum((f["sz"] * f["px"] for f in core if not f["crossed"]), Decimal(0)) / core_not)
              if core_not > 0 else None,
              first_core_ms=min((f["time"] for f in core), default=None))
    ft["rate"] = (PAGE / span_d if span_d > 0 else math.inf) if ft["full"] else None
    closed, still_open = trips(core)
    holds = [(t["close_ms"] - t["open_ms"]) / MIN_MS for t in closed] + [math.inf] * len(still_open)  # censored: +inf
    every = closed + still_open
    ft.update(n_rt=len(closed), n_censored=len(still_open), n_trips=len(every), hold_med=median(holds))
    ft["exec_share"] = (sum(1 for t in every if float(t["open_sz"] * t["open_px"]) / av * WALLET_USD >= MIN_ORDER_USD)
                        / len(every)) if every and av and av > 0 else None
    ft["small_fill_share"] = (sum(1 for f in core if float(f["sz"] * f["px"]) / av * WALLET_USD < MIN_ORDER_USD)
                              / len(core)) if core and av and av > 0 else None  # info only (fills, not opens)
    return ft


def rules(ft, now_ms, window_days):
    """S1-S9: True = pass, False = fail, None = not evaluable / not applicable (never a failure)."""
    r = dict.fromkeys(RULE_IDS)
    r["S1"] = ft["rows"] >= 1
    if not r["S1"]:
        return r
    r["S2"] = not (ft["full"] and ft["span_d"] < 1.0)
    r["S3"] = ft["core_share"] is not None and ft["core_share"] >= MIN_CORE_SHARE
    r["S4"] = ft["maker_share"] is not None and ft["maker_share"] <= MAX_MAKER_SHARE
    r["S5"] = ft["first_core_ms"] is not None and (now_ms - ft["first_core_ms"]) / DAY_MS >= MIN_FILL_SPAN_D
    r["S6"] = (ft["rate"] * window_days < HL_FILLS_LIMIT) if ft["full"] else None
    r["S7"] = (ft["hold_med"] >= MIN_HOLD_MIN) if ft["n_trips"] >= MIN_TRIPS else None
    r["S8"] = (ft["exec_share"] is not None and ft["exec_share"] >= MIN_EXEC_SHARE) if ft["n_trips"] >= MIN_TRIPS else None
    r["S9"] = None if ft["full"] else ft["n_rt"] >= MIN_ROUND_TRIPS
    return r


def outcome(r):
    if r["S1"] is False:
        return "empty (EX2, 168 h)"
    if r["S2"] is False:
        return "too_active_first_page (EX1, 24 h)"
    bad = [k for k in RULE_IDS if r[k] is False]
    return f"screen_rejected {'+'.join(bad)} (72 h)" if bad else "OK"


def passed(r):
    return r["S1"] is True and all(v is not False for v in r.values())


def fmt(x, nd=2):
    if x is None:
        return "-"
    if isinstance(x, float) and math.isinf(x):
        return "inf"
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def line(res):
    ft, r = res.get("ft") or {}, res.get("rules")
    head = f"{res['rank']:>3} {res['addr'][:10]}"
    if r is None:
        return f"{head} FETCH/SCHEMA FAILED ({res['error']}) - excluded from n"
    marks = " ".join(f"{k}{'+' if r[k] else ('-' if r[k] is False else '.')}" for k in RULE_IDS)
    return (f"{head} rows={ft['rows']}{'F' if ft['full'] else ''} span_d={fmt(ft.get('span_d'), 1)} "
            f"fpd={fmt(ft.get('fills_per_day'), 0)} core={fmt(ft.get('core_share'))} maker={fmt(ft.get('maker_share'))} "
            f"hold_med={fmt(ft.get('hold_med'), 0)} trips={ft.get('n_trips', '-')}(rt={ft.get('n_rt', '-')},open={ft.get('n_censored', '-')}) "
            f"exec={fmt(ft.get('exec_share'))} small_fills={fmt(ft.get('small_fill_share'))} | {marks} | "
            f"{'PASS' if passed(r) else 'FAIL'} {outcome(r)}")


def screen_wallets(wallets, ranks, window_days, pause_s, fetch=None, now=None, sleep=time.sleep):
    fetch = fetch or (lambda body: crc.call(crc.INFO, body))
    now = now or (lambda: int(time.time() * 1000))
    out = []
    for i, (rank, row) in enumerate(zip(ranks, wallets, strict=True)):
        t = now()
        st, page = fetch({"type": "userFillsByTime", "user": row["addr"], "startTime": t - window_days * DAY_MS,
                          "aggregateByTime": True})
        res = {"rank": rank, "addr": row["addr"], "rules": None, "error": None}
        if st != 200 or not isinstance(page, list):
            res["error"] = f"http {st}"
        else:
            try:
                res["ft"] = features(page, row["av"])
                res["rules"] = rules(res["ft"], t, window_days)
            except SchemaError as e:
                res["error"] = f"schema: {e}"
        out.append(res)
        print("  " + line(res), flush=True)
        if i + 1 < len(wallets):
            rows = len(page) if isinstance(page, list) else 0
            sleep(max(pause_s, (20 + math.ceil(rows / 20)) * 60 / WEIGHT_PER_MIN))
    return out


def verdict(results):
    """Pre-registered (candidate-ranking.md section 9). Returns (verdict, details)."""
    valid = [x for x in results if x["rules"] is not None]
    n = len(valid)
    surv = [x for x in valid if passed(x["rules"])]
    d = {"n": n, "pass": len(surv), "need": math.ceil(n * PASS_TENTHS / 10), "kill_below": math.ceil(n * KILL_TENTHS / 10)}
    if n < MIN_VALID:
        return f"INCONCLUSIVE (only {n} valid fetches, need {MIN_VALID}: rerun)", d
    ev = [x for x in surv if x["rules"]["S7"] is not None and x["rules"]["S8"] is not None]
    med = lambda k: median([x["ft"][k] for x in surv if x["ft"].get(k) is not None])  # noqa: E731
    d.update(c1=len(ev) / len(surv) if surv else None, c2=med("hold_med"), c3=med("maker_share"), c4=med("exec_share"))
    copyable = (bool(surv) and d["c1"] >= C1_EVAL and d["c2"] is not None and d["c2"] >= C2_HOLD_MIN
                and d["c3"] is not None and d["c3"] <= C3_MAKER and d["c4"] is not None and d["c4"] >= C4_EXEC)
    d["copyable"] = copyable
    if len(surv) >= d["need"] and copyable:
        return "PASS (stage 2 screen adopted; route: PM amendment F6 -> test-designer)", d
    if len(surv) < d["kill_below"]:
        return "KILL (at most one more pre-registered variant; else keep served order + EX1/EX2)", d
    return "PARTIAL (log it; at most one more pre-registered variant)", d


def summary(label, results, v, d):
    fails = {k: sum(1 for x in results if x["rules"] and x["rules"][k] is False) for k in RULE_IDS}
    ne = {k: sum(1 for x in results if x["rules"] and x["rules"][k] is None) for k in RULE_IDS}
    print(f"{label}: valid={d['n']} pass={d['pass']} (PASS needs >= {d['need']}, KILL below {d['kill_below']})")
    print("  fails by rule: " + " ".join(f"{k}={fails[k]}" for k in RULE_IDS))
    print("  not evaluable/applicable: " + " ".join(f"{k}={ne[k]}" for k in RULE_IDS))
    if "c1" in d:
        print(f"  copyable: c1 evaluated share={fmt(d['c1'])} (>= {C1_EVAL}) c2 median hold_med={fmt(d['c2'], 0)} min "
              f"(>= {C2_HOLD_MIN:.0f}) c3 median maker={fmt(d['c3'])} (<= {C3_MAKER}) c4 median exec={fmt(d['c4'])} "
              f"(>= {C4_EXEC}) -> {'copyable' if d['copyable'] else 'NOT copyable'}")
    print(f"  VERDICT {label}: {v}")


def load_leaderboard(args):
    out = crc.repo_root() / "research" / "data" / "candidate_ranking"
    path = Path(args.file) if args.file else None
    if path is None and not args.fresh:
        saved = sorted(out.glob("leaderboard_*.json.gz"))  # names carry a UTC timestamp: the first is the oldest (run 1)
        path = saved[0] if saved else None
        if path is None:
            print("no saved leaderboard found: downloading a fresh one (ranks 21-40 may then include run-1 wallets)")
    if path is not None:
        with (gzip.open if str(path).endswith(".gz") else open)(path, "rt", encoding="utf-8") as fh:
            return json.load(fh), str(path.name)
    st, doc = crc.call(crc.LB)
    print("leaderboard HTTP:", st)
    if st != 200:
        sys.exit(1)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"leaderboard_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh)
    print("saved:", path, "(fresh snapshot: ranks 21-40 may overlap the wallets seen in run 1)")
    return doc, path.name


def selftest():  # noqa: PLR0915 - throwaway
    t0 = 1_000 * DAY_MS
    now = t0 + 180 * DAY_MS
    tid = iter(range(1, 10**9))

    def f(t, coin, side, sz, start, px=100, crossed=True):
        return {"time": t, "tid": next(tid), "coin": coin, "side": side, "sz": str(sz), "px": str(px),
                "startPosition": str(start), "crossed": crossed}

    def page(n_trips, first, step_ms, hold_ms, coin="BTC", sz=1, crossed=True, open_at_end=0):
        out = []
        for i in range(n_trips):
            t = first + i * step_ms
            out += [f(t, coin, "B", sz, 0, crossed=crossed), f(t + hold_ms, coin, "A", sz, sz, crossed=crossed)]
        for j in range(open_at_end):  # each on its own coin, opened and never closed on the page
            out.append(f(first + n_trips * step_ms + j, f"C{j}", "B", sz, 0, crossed=crossed))
        return out

    av = 100_000.0  # 1 BTC at 100 = 100 USD open -> 100/100k*300 = 0.3 USD mirrored; sz 50 -> 15 USD
    run = lambda p, a=av: (lambda ft: (ft, rules(ft, now, 180)))(features(p, a))  # noqa: E731
    swing = page(200, now - 170 * DAY_MS, 12 * 3_600_000, 2 * 3_600_000, sz=50)
    ft, r = run(swing)
    assert passed(r) and r["S6"] is None and r["S9"] is True and ft["n_rt"] == 200 and ft["hold_med"] == 120, (ft, r)
    assert abs(ft["exec_share"] - 1.0) < 1e-12 and ft["maker_share"] == 0.0 and ft["core_share"] == 1.0
    assert outcome(run([])[1]).startswith("empty") and not passed(run([])[1])
    ft, r = run(page(1000, now - 100 * DAY_MS, 30_000, 10_000, sz=50))           # 2,000 rows in 0.35 d
    assert r["S2"] is False and outcome(r).startswith("too_active_first_page"), r
    assert run(page(200, now - 170 * DAY_MS, 12 * 3_600_000, 7_200_000, sz=50, crossed=False))[1]["S4"] is False
    spot = swing + [f(now - 160 * DAY_MS + i, "@107", "B", 10_000, 0) for i in range(10)]  # 10 x 1M USD spot vs 2M core
    assert run(spot)[1]["S3"] is False and run(spot)[1]["S4"] is True
    assert run(page(200, now - 30 * DAY_MS, 3_600_000, 1_800_000, sz=50))[1]["S5"] is False   # young: G3 impossible
    ft, r = run(page(1000, now - 170 * DAY_MS, 20 * DAY_MS // 1000, 600_000, sz=50))         # full, ~20 d: 100/day
    assert ft["full"] and r["S6"] is False and r["S9"] is None, (ft["rate"], r)
    ft, r = run(page(1000, now - 170 * DAY_MS, 40 * DAY_MS // 1000, 600_000, sz=50))         # full, ~40 d: 50/day
    assert r["S6"] is True, ft["rate"]
    assert run(page(200, now - 170 * DAY_MS, DAY_MS // 2, 120_000, sz=50))[1]["S7"] is False  # 2-min scalper
    assert run(swing, 10_000_000.0)[1]["S8"] is False                                          # opens tiny vs AV
    assert run(page(100, now - 170 * DAY_MS, DAY_MS, 3_600_000, sz=50))[1]["S9"] is False     # 100 rt < 150
    ft, r = run(page(20, now - 170 * DAY_MS, DAY_MS, 60_000, sz=50))                          # 20 trips: n/e
    assert r["S7"] is None and r["S8"] is None and r["S9"] is False
    ft, r = run(page(25, now - 170 * DAY_MS, DAY_MS, 60_000, sz=50, open_at_end=10))          # 25 short + 10 censored
    assert ft["n_trips"] == 35 and r["S7"] is False, ft
    ft, r = run(page(15, now - 170 * DAY_MS, DAY_MS, 60_000, sz=50, open_at_end=20))          # censored majority: +inf
    assert ft["hold_med"] == math.inf and r["S7"] is True, ft
    # reconstruct: an initially open position is ignored until flat; a flip closes and opens; a repeat counts once
    p = [f(t0, "ETH", "A", 1, 2), f(t0 + 1, "ETH", "A", 1, 1),                       # ignored, then flat
         f(t0 + 2, "ETH", "B", 2, 0), f(t0 + 3, "ETH", "A", 5, 2), f(t0 + 9, "ETH", "B", 3, -3)]
    p.append(dict(p[-1]))
    closed, still = trips(dedupe([norm(x) for x in p]))
    assert [(c["open_ms"], c["close_ms"]) for c in closed] == [(t0 + 2, t0 + 3), (t0 + 3, t0 + 9)] and not still
    assert closed[1]["open_sz"] == 3 and closed[1]["dir"] == -1
    try:
        features([{"time": 1, "coin": "BTC"}], av)
        raise AssertionError("schema error expected")
    except SchemaError:
        pass
    # verdict thresholds (n = 20: PASS >= 10 and copyable, KILL < 6, INCONCLUSIVE < 16 valid)
    good = {"rank": 0, "addr": "0x", "error": None, "ft": run(swing)[0], "rules": run(swing)[1]}
    bad = {"rank": 0, "addr": "0x", "error": None, "ft": run([])[0], "rules": run([])[1]}
    failed = {"rank": 0, "addr": "0x", "error": "http 500", "rules": None}
    assert verdict([good] * 10 + [bad] * 10)[0].startswith("PASS")
    assert verdict([good] * 9 + [bad] * 11)[0].startswith("PARTIAL")
    assert verdict([good] * 6 + [bad] * 14)[0].startswith("PARTIAL") and verdict([good] * 5 + [bad] * 15)[0].startswith("KILL")
    assert verdict([good] * 10 + [bad] * 5 + [failed] * 5)[0].startswith("INCONCLUSIVE")
    meh_ft, meh_r = run(page(200, now - 170 * DAY_MS, 12 * 3_600_000, 20 * MIN_MS, sz=50))   # 20-min holds: passes S7
    meh = {"rank": 0, "addr": "0x", "error": None, "ft": meh_ft, "rules": meh_r}
    assert passed(meh_r) and verdict([meh] * 12 + [bad] * 8)[0].startswith("PARTIAL")      # c2: 20 < 30 min
    # end to end: 45 good synthetic rows -> D ranks 21-40 -> fake fetch -> 20 screened
    def row(i):
        a = 100_000 + i
        return {"ethAddress": "0x" + f"{i:040x}", "accountValue": str(a), "windowPerformances": [
            [k, {"pnl": str(v[0]), "roi": "0", "vlm": str(v[1])}]
            for k, v in zip(crc.WINDOWS, ((500, 2e5), (2e3, 1e6), (8e3, 4e6), (5e4 + i, 3e7)), strict=True)]}
    rows = [crc.derived(crc.parse(row(i))) for i in range(1, 46)]
    d = crc.rank_d(rows)
    assert len(d) == 45
    seen = []
    fake = lambda body: (seen.append(body) or (200, swing))  # noqa: E731
    res = screen_wallets(d[20:40], range(21, 41), 180, 0, fetch=fake, now=lambda: now, sleep=lambda s: None)
    assert len(res) == 20 and all(passed(x["rules"]) for x in res) and seen[0]["startTime"] == now - 180 * DAY_MS
    assert seen[0]["aggregateByTime"] is True and seen[0]["user"] == d[20]["addr"]
    summary("selftest", res, *verdict(res))
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranks", default="21-40", help="D ranks to screen (pre-registered: 21-40)")
    ap.add_argument("--window-days", type=int, default=180)
    ap.add_argument("--file", help="leaderboard .json/.json.gz (default: the oldest saved snapshot = run 1's)")
    ap.add_argument("--fresh", action="store_true", help="download a new leaderboard instead of the saved one")
    ap.add_argument("--baseline", action="store_true", help="also screen served-order rows at the same ranks (info only)")
    ap.add_argument("--pause", type=float, default=3.0, help="minimum seconds between fill calls")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    lo, hi = (int(x) for x in a.ranks.split("-"))
    doc, name = load_leaderboard(a)
    rows = [crc.derived(crc.parse(r)) for r in doc["leaderboardRows"] if isinstance(r, dict)]
    print("EXPLORATORY. Today's leaderboard only (survivorship-biased); row fields self-reported. Not validation.")
    alive, steps = rows, []
    for rid, _, pred in crc.RULES:
        alive = [r for r in alive if pred(r)]
        steps.append(f"{rid}:{len(alive)}")
    d = crc.rank_d(rows)
    print(f"leaderboard {name}: rows={len(rows)} stage 1 survivors after " + " ".join(steps) + f" -> D={len(d)}")
    target = d[lo - 1: hi]
    print(f"\nstage 2 first-page screen, D ranks {lo}-{lo + len(target) - 1}, window {a.window_days} d "
          f"(+ pass, - fail, . not evaluable/applicable):")
    res = screen_wallets(target, range(lo, lo + len(target)), a.window_days, a.pause)
    base = None
    if a.baseline:
        b = crc.base(rows)[lo - 1: hi]
        print(f"\nBASELINE (info only, not in the verdict): served-order rows {lo}-{lo + len(b) - 1}, same screen:")
        base = screen_wallets(b, range(lo, lo + len(b)), a.window_days, a.pause)
    v, det = verdict(res)
    print("\n=== SUMMARY (paste everything from here to the end back to the CTO) ===")
    print(f"variant 2 screen | leaderboard={name} rows={len(rows)} D={len(d)} ranks={a.ranks} window={a.window_days}d "
          f"run={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}")
    for x in res:
        print(line(x))
    summary("D", res, v, det)
    if base is not None:
        summary("baseline A (info only)", base, *verdict(base))
    print(f"PRE-REGISTERED VERDICT (variant 2 of max 3): {v}")


if __name__ == "__main__":
    main()
