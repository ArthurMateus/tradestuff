# Throwaway diagnostic (public, read-only, paper-safe). For the three wallets whose backfill keeps failing with
# `candleSnapshot: HTTP 500`, list the coins they traded (first page of fills) and ask for each coin's 180 d of 1h bars.
#   uv run python docs\sdlc\copytrade-v1\research\scripts\hl_wallet_coins_check.py
# Prints for every perp-like coin (no '@', '/' or ':'): HTTP status and bar count. A coin that answers 500 (often a
# delisted or renamed perp) is the cause. Also prints whether the coin is in Hyperliquid's CURRENT perp universe (meta).
import json, sys, time, urllib.request, urllib.error
INFO = "https://api.hyperliquid.xyz/info"
WALLETS = sys.argv[1:] or [
    "0xd21d931890d27b6e7e2e668f27931e17698e90f1",
    "0x266b5569ed3017e74dd48059c6db804e016eefcb",
    "0xbe3f79ae0ab3294aaa3230c1155e912c05b6a55b",
]
now = int(time.time() * 1000)

def call(body):
    req = urllib.request.Request(INFO, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]
    except Exception as e:
        return repr(e), None

st, meta = call({"type": "meta"})
universe = {u["name"] for u in meta["universe"]} if st == 200 else set()
print("current perp universe:", len(universe), "coins")
seen = {}
for w in WALLETS:
    st, fills = call({"type": "userFillsByTime", "user": w, "startTime": now - 180 * 86400000, "aggregateByTime": True})
    time.sleep(2)
    if st != 200:
        print(w[:12], "fills HTTP", st); continue
    coins = sorted({f["coin"] for f in fills if not (f["coin"].startswith("@") or "/" in f["coin"] or ":" in f["coin"])})
    print(w[:12], "fills:", len(fills), "coins:", coins)
    for c in coins:
        seen.setdefault(c, []).append(w[:8])
for c in sorted(seen):
    st, bars = call({"type": "candleSnapshot", "req": {"coin": c, "interval": "1h", "startTime": now - 180 * 86400000, "endTime": now}})
    n = len(bars) if st == 200 and isinstance(bars, list) else "-"
    print(f"{c:10} HTTP {st} bars={n} in_current_universe={c in universe}")
    time.sleep(1)
