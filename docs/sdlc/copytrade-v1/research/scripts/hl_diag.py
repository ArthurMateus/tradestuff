# Throwaway diagnostic, public read-only. Run OUTSIDE the repo: uv run python hl_diag.py
import json, time, urllib.request, urllib.error
INFO = "https://api.hyperliquid.xyz/info"
LB = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

def call(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, raw, time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300], time.time() - t
    except Exception as e:
        return repr(e), b"", time.time() - t

st, raw, dt = call(LB)
print("leaderboard:", st, len(raw), "bytes", round(dt, 1), "s")
rows = json.loads(raw)["leaderboardRows"] if st == 200 else []
print("rows:", len(rows)); 
if rows: print("row keys:", list(rows[0].keys()))
wallets = [r["ethAddress"] for r in rows[:3]]
now = int(time.time() * 1000)
for w in wallets:
    for label, start in (("last 24h", now - 86400000), ("last 30d", now - 30 * 86400000)):
        st, raw, dt = call(INFO, {"type": "userFillsByTime", "user": w, "startTime": start, "endTime": now})
        if st == 200:
            fills = json.loads(raw)
            ts = [f["time"] for f in fills]
            print(w[:10], label, "HTTP", st, len(raw), "bytes", len(fills), "fills",
                  (min(ts), max(ts)) if ts else None, round(dt, 1), "s",
                  "keys:", sorted(fills[0].keys()) if fills else None)
        else:
            print(w[:10], label, "HTTP", st, raw[:200], round(dt, 1), "s")
        time.sleep(1)
