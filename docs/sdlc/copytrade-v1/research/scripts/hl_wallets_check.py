# Throwaway diagnostic (public, read-only, paper-safe). Run OUTSIDE the bot, with the bot stopped:
#   uv run python docs\sdlc\copytrade-v1\research\scripts\hl_wallets_check.py
# For the top N leaderboard wallets it asks Hyperliquid for the fills of the last 90 days (as the bot does),
# one wallet every 3 s, and prints: fill count, first/last fill time, how many days it spans, and a verdict:
#   ok            = a normal, copyable-looking history
#   too active    = 10,000 fills (Hyperliquid's cap) all inside a short span: a high-frequency account
#   empty/failed  = nothing returned, or the HTTP error
import json, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
N = int(sys.argv[1]) if len(sys.argv) > 1 else 15
INFO = "https://api.hyperliquid.xyz/info"
LB = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

def call(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return repr(e), None

st, lb = call(LB)
print("leaderboard:", st)
rows = lb["leaderboardRows"] if st == 200 else []
print("rows:", len(rows))
now = int(time.time() * 1000)
start = now - 90 * 86400000
ok = 0
for row in rows[:N]:
    w = row["ethAddress"]
    st, fills = call(INFO, {"type": "userFillsByTime", "user": w, "startTime": start, "aggregateByTime": True})
    if st != 200 or fills is None:
        print(w[:12], "HTTP", st, "-> empty/failed")
    elif not fills:
        print(w[:12], "0 fills -> empty")
    else:
        ts = [f["time"] for f in fills]
        span = (max(ts) - min(ts)) / 86400000
        first = datetime.fromtimestamp(min(ts) / 1000, timezone.utc).strftime("%Y-%m-%d")
        verdict = "too active" if len(fills) >= 2000 and span < 5 else "ok"
        ok += verdict == "ok"
        print(w[:12], len(fills), "fills (first page)", "from", first, f"span {span:.1f} d ->", verdict)
    time.sleep(3)
print("copyable-looking:", ok, "of", min(N, len(rows)))
