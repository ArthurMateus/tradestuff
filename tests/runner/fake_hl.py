"""A LOCAL loopback fake of Hyperliquid (real sockets, 127.0.0.1 only): the info endpoint (HTTP POST /info), the stats
host (HTTP GET /leaderboard) and the info WebSocket (reusing tests/hl/ws_server.FakeWsServer). The only thing faked
besides Telegram, the clock and the disk probe in the R0 tests.

Payload shapes follow tests/fixtures/exchange/hl (which are synthetic until the PO's hl_sample.py recordings replace
them) and the public Hyperliquid documentation for ``meta``, ``metaAndAssetCtxs`` and ``fundingHistory``.
Every request is recorded; ``bad_paths`` collects any POST path other than ``/info`` (the order endpoint must never be
touched).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tests.hl.ws_server import FakeWsServer, ServerSide

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "exchange" / "hl"
HOUR_MS = 3_600_000
MIN_MS = 60_000


def fill_json(
    tid: int,
    *,
    coin: str,
    side: str,
    sz: str,
    px: str,
    direction: str,
    time_ms: int,
    start_position: str = "0.0",
    closed_pnl: str = "0.0",
) -> dict[str, Any]:
    """One leader fill in the exchange's JSON shape (``side`` B = buy, A = sell)."""
    return {
        "coin": coin,
        "px": px,
        "sz": sz,
        "side": side,
        "time": time_ms,
        "startPosition": start_position,
        "dir": direction,
        "closedPnl": closed_pnl,
        "hash": "0x" + f"{tid:064x}",
        "oid": 900_000 + tid,
        "crossed": True,
        "fee": "0.0123",
        "tid": tid,
        "feeToken": "USDC",
    }


@dataclass
class FakeHl:
    exchange_ms: Callable[[], int]
    http_requests: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    bad_paths: list[str] = field(default_factory=list)
    mids: dict[str, str] = field(default_factory=lambda: {"SOL": "100.0", "BTC": "67000.0", "ETH": "3400.0"})
    universe: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"name": "BTC", "szDecimals": 5, "maxLeverage": 40},
            {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
            {"name": "SOL", "szDecimals": 2, "maxLeverage": 20},
        ]
    )
    leader_av: dict[str, str] = field(default_factory=dict)
    leader_positions: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)  # wallet -> [(coin, szi, entry)]
    leader_fills: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    candle_range: tuple[str, str] = ("100.375", "99.625")  # high, low of every flat bar: true range 0.75
    funding_rate: str = "0.0000125"
    fail_types: set[str] = field(default_factory=set)  # info request types answered with HTTP 500
    hang_types: set[str] = field(default_factory=set)  # info request types never answered until release()
    leaderboard_status: int = 200
    leaderboard_body: bytes = b""
    leaderboard_delay_s: float = 0.0
    hook: Callable[[], None] | None = None  # called at the start of every info request (e.g. to advance a fake clock)
    _release: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _httpd: ThreadingHTTPServer | None = None
    _ws: FakeWsServer | None = None
    info_url: str = ""
    leaderboard_url: str = ""
    ws_url: str = ""

    # ------------------------------------------------------------------------------------------------ lifecycle
    def start(self) -> FakeHl:
        outer = self
        self.leaderboard_body = (FIXTURES / "leaderboard.json").read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def do_POST(self) -> None:  # noqa: N802
                outer._post(self)

            def do_GET(self) -> None:  # noqa: N802
                outer._get(self)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        port = self._httpd.server_address[1]
        self.info_url = f"http://127.0.0.1:{port}/info"
        self.leaderboard_url = f"http://127.0.0.1:{port}/leaderboard"
        self._ws = FakeWsServer(auto_pong=True)
        self.ws_url = self._ws.url
        return self

    def stop(self) -> None:
        self._release.set()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._ws is not None:
            self._ws.stop()

    def release(self) -> None:
        self._release.set()

    # ------------------------------------------------------------------------------------------------ http
    @staticmethod
    def _reply(h: BaseHTTPRequestHandler, status: int, body: bytes) -> None:
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        try:
            h.wfile.write(body)
        except OSError:
            pass

    def _post(self, h: BaseHTTPRequestHandler) -> None:
        length = int(h.headers.get("Content-Length") or 0)
        raw = h.rfile.read(length) if length else b"{}"
        if h.path != "/info":
            with self._lock:
                self.bad_paths.append(h.path)
            self._reply(h, 404, b"{}")
            return
        req = json.loads(raw or b"{}")
        rtype = str(req.get("type"))
        if self.hook is not None:
            self.hook()
        with self._lock:
            self.http_requests.append((rtype, req))
        if rtype in self.hang_types:
            self._release.wait(30)
        if rtype in self.fail_types:
            self._reply(h, 500, b"{}")
            return
        self._reply(h, 200, json.dumps(self._answer(rtype, req)).encode())

    def _get(self, h: BaseHTTPRequestHandler) -> None:
        with self._lock:
            self.http_requests.append(("GET " + h.path, {}))
        if h.path != "/leaderboard":
            self._reply(h, 404, b"{}")
            return
        if self.leaderboard_delay_s:
            self._release.wait(self.leaderboard_delay_s)
        self._reply(h, self.leaderboard_status, self.leaderboard_body)

    def requests_of(self, rtype: str) -> list[dict[str, Any]]:
        with self._lock:
            return [req for t, req in self.http_requests if t == rtype]

    # ------------------------------------------------------------------------------------------------ answers
    def book_levels(self, coin: str) -> list[list[dict[str, Any]]]:
        mid = Decimal(self.mids.get(coin, "100.0"))
        bids = [{"px": str(mid - Decimal("0.1") - i), "sz": "500.0", "n": 3} for i in range(5)]
        asks = [{"px": str(mid + Decimal("0.1") + i), "sz": "500.0", "n": 3} for i in range(5)]
        return [bids, asks]

    def _answer(self, rtype: str, req: dict[str, Any]) -> Any:  # noqa: PLR0911, PLR0912
        if rtype == "allMids":
            return self.mids
        if rtype == "l2Book":
            return {"coin": req["coin"], "time": self.exchange_ms(), "levels": self.book_levels(req["coin"])}
        if rtype == "meta":
            return {"universe": self.universe}
        if rtype == "metaAndAssetCtxs":
            ctxs = [
                {
                    "funding": self.funding_rate,
                    "openInterest": "1000.0",
                    "prevDayPx": self.mids.get(u["name"], "100.0"),
                    "dayNtlVlm": "50000000.0",
                    "premium": "0.0001",
                    "oraclePx": self.mids.get(u["name"], "100.0"),
                    "markPx": self.mids.get(u["name"], "100.0"),
                    "midPx": self.mids.get(u["name"], "100.0"),
                    "impactPxs": [self.mids.get(u["name"], "100.0")] * 2,
                }
                for u in self.universe
            ]
            return [{"universe": self.universe}, ctxs]
        if rtype == "fundingHistory":
            start = int(req["startTime"])
            first = start - start % HOUR_MS
            now = self.exchange_ms()
            points = []
            t = first if first >= start else first + HOUR_MS
            while t <= now:
                points.append({"coin": req["coin"], "fundingRate": self.funding_rate, "premium": "0.0001", "time": t})
                t += HOUR_MS
            return points
        if rtype == "clearinghouseState":
            wallet = str(req["user"]).lower()
            return self._clearinghouse(wallet)
        if rtype in ("userFillsByTime", "userFills"):
            wallet = str(req["user"]).lower()
            lo = int(req.get("startTime", 0))
            hi = int(req.get("endTime", 1 << 62))
            return [f for f in self.leader_fills.get(wallet, []) if lo <= f["time"] <= hi]
        if rtype == "candleSnapshot":
            return self._candles(req["req"])
        if rtype == "userRole":
            return {"role": "user"}
        if rtype == "portfolio":
            return json.loads((FIXTURES / "portfolio.json").read_text(encoding="utf-8"))
        return {}

    def _clearinghouse(self, wallet: str) -> dict[str, Any]:
        value = self.leader_av.get(wallet, "1000.0")
        positions = [
            {
                "type": "oneWay",
                "position": {
                    "coin": coin,
                    "szi": szi,
                    "entryPx": entry,
                    "positionValue": "1000.0",
                    "unrealizedPnl": "0.0",
                    "returnOnEquity": "0.0",
                    "liquidationPx": None,
                    "leverage": {"type": "cross", "value": 5},
                    "marginUsed": "200.0",
                    "maxLeverage": 20,
                    "cumFunding": {"allTime": "0.0", "sinceOpen": "0.0", "sinceChange": "0.0"},
                },
            }
            for coin, szi, entry in self.leader_positions.get(wallet, [])
        ]
        summary = {"accountValue": value, "totalNtlPos": "0.0", "totalRawUsd": value, "totalMarginUsed": "0.0"}
        return {
            "marginSummary": summary,
            "crossMarginSummary": summary,
            "crossMaintenanceMarginUsed": "0.0",
            "withdrawable": value,
            "assetPositions": positions,
            "time": self.exchange_ms(),
        }

    def _candles(self, req: dict[str, Any]) -> list[dict[str, Any]]:
        step = HOUR_MS if req["interval"] == "1h" else MIN_MS
        start, end = int(req["startTime"]), int(req["endTime"])
        now = self.exchange_ms()
        open_ms = start if start % step == 0 else start - start % step + step
        out = []
        while open_ms + step - 1 <= min(end, now):
            out.append(
                {
                    "t": open_ms,
                    "T": open_ms + step - 1,
                    "s": req["coin"],
                    "i": req["interval"],
                    "o": "100.0",
                    "c": "100.0",
                    "h": self.candle_range[0],
                    "l": self.candle_range[1],
                    "v": "10.0",
                    "n": 10,
                }
            )
            open_ms += step
        return out

    # ------------------------------------------------------------------------------------------------ websocket
    def connections(self) -> list[ServerSide]:
        assert self._ws is not None
        return list(self._ws.connections)

    @staticmethod
    def _subscriptions(side: ServerSide) -> list[dict[str, Any]]:
        out = []
        for text in list(side.received):
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if msg.get("method") == "subscribe":
                out.append(msg["subscription"])
        return out

    def subscribed(self, sub_type: str) -> list[dict[str, Any]]:
        """Every subscription of ``sub_type`` seen on any connection (``{"type": ..., "user"/"coin": ...}``)."""
        return [s for side in self.connections() for s in self._subscriptions(side) if s.get("type") == sub_type]

    def user_subscribed(self, wallet: str) -> bool:
        return any(s.get("user", "").lower() == wallet.lower() for s in self.subscribed("userFills"))

    def _send_to(self, predicate: Callable[[dict[str, Any]], bool], message: dict[str, Any]) -> int:
        sent = 0
        for side in self.connections():
            if side.closed.is_set():
                continue
            if any(predicate(s) for s in self._subscriptions(side)):
                side.send(json.dumps(message))
                sent += 1
        return sent

    def push_user_fills(self, wallet: str, fills: list[dict[str, Any]], *, snapshot: bool = False) -> int:
        """Send a ``userFills`` frame to the connection(s) subscribed to ``wallet``; returns how many got it."""
        self.leader_fills.setdefault(wallet.lower(), []).extend(fills)
        message = {"channel": "userFills", "data": {"isSnapshot": snapshot, "user": wallet, "fills": fills}}
        return self._send_to(lambda s: s.get("type") == "userFills" and s.get("user", "").lower() == wallet.lower(), message)

    def push_l2(self, coin: str, time_ms: int | None = None) -> int:
        message = {
            "channel": "l2Book",
            "data": {"coin": coin, "time": self.exchange_ms() if time_ms is None else time_ms, "levels": self.book_levels(coin)},
        }
        return self._send_to(lambda s: s.get("type") == "l2Book" and s.get("coin") == coin, message)

    def push_mids(self) -> int:
        message = {"channel": "allMids", "data": {"mids": dict(self.mids)}}
        return self._send_to(lambda s: s.get("type") == "allMids", message)

    def push_raw_to_market(self, text: str) -> None:
        for side in self.connections():
            if any(s.get("type") in ("l2Book", "allMids") for s in self._subscriptions(side)):
                side.send(text)

    def drop_market_connections(self) -> None:
        for side in self.connections():
            if any(s.get("type") in ("l2Book", "allMids") for s in self._subscriptions(side)):
                side.abort()
