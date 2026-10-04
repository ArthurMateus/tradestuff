# Throwaway diagnostic (public, read-only, paper-safe): which candleSnapshot requests does Hyperliquid answer with HTTP 500?
#   uv run python docs\sdlc\copytrade-v1\research\scripts\hl_candle_check.py
# For a list of coins it asks for 1h bars over 7, 30, 90 and 180 days (the bot asks for the scoring window, 180 d by default)
# and prints HTTP status, bar count and the first/last bar time. One request per second. Send the whole output to the CTO.
import json, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
INFO = "https://api.hyperliquid.xyz/info"
COINS = sys.argv[1:] or ["BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "SUI", "AVAX", "LINK", "BNB"]
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

for coin in COINS:
    for days in (7, 30, 90, 180):
        start = now - days * 86400000
        st, data = call({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": start, "endTime": now}})
        if st == 200 and isinstance(data, list) and data:
            f = lambda c: datetime.fromtimestamp(c["t"] / 1000, timezone.utc).strftime("%Y-%m-%d")
            print(f"{coin:6} {days:3} d HTTP 200 bars={len(data)} first={f(data[0])} last={f(data[-1])}")
        else:
            print(f"{coin:6} {days:3} d HTTP {st} body={str(data)[:120]}")
        time.sleep(1)
