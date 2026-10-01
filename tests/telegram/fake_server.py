"""A LOCAL loopback fake of the Telegram Bot API (real sockets, 127.0.0.1 only). The only thing faked in the F14 tests.

Shapes follow the public Bot API documentation (no recorded real payload exists in tests/fixtures yet): every reply is
``{"ok": true, "result": ...}``; an error is ``{"ok": false, "error_code": n, "description": "...",
"parameters": {"retry_after": s}}``. Routes: ``POST /bot<token>/<method>`` with a JSON body.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Req:
    method: str
    payload: dict[str, Any]
    path: str
    delivered: bool = False  # True only when the server answered with a 2xx (a real delivery)


@dataclass
class FakeTelegram:
    token: str
    mode: str = "ok"  # ok | down (connection dropped) | http500 | hang
    script: list[tuple[int, dict[str, Any]]] = field(default_factory=list)  # forced replies, consumed first
    requests: list[Req] = field(default_factory=list)
    updates: list[dict[str, Any]] = field(default_factory=list)
    _next_message_id: int = 100
    _next_update_id: int = 1
    _release: threading.Event = field(default_factory=threading.Event)
    _httpd: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---------------------------------------------------------------------------------------------- lifecycle
    def start(self) -> str:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base signature
                return

            def do_POST(self) -> None:  # noqa: N802 - the base class API
                outer._handle(self)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def stop(self) -> None:
        self._release.set()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # ---------------------------------------------------------------------------------------------- handler
    def _handle(self, h: BaseHTTPRequestHandler) -> None:
        length = int(h.headers.get("Content-Length") or 0)
        raw = h.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        parts = h.path.strip("/").split("/")
        method = parts[-1] if parts else ""
        with self._lock:
            req = Req(method, payload, h.path)
            self.requests.append(req)
            mode, forced = self.mode, (self.script.pop(0) if self.script else None)
        if parts[0] != f"bot{self.token}":
            self._reply(h, 401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
            return
        if forced is not None:
            req.delivered = 200 <= forced[0] < 300
            self._reply(h, forced[0], forced[1])
            return
        if mode == "down":
            h.close_connection = True
            h.connection.close()
            return
        if mode == "hang":
            self._release.wait(timeout=2.0)
            h.close_connection = True
            return
        if mode == "http500":
            self._reply(h, 500, {"ok": False, "error_code": 500, "description": "Internal Server Error"})
            return
        req.delivered = True
        self._reply(h, 200, {"ok": True, "result": self._result(method, payload)})

    def _result(self, method: str, payload: dict[str, Any]) -> Any:
        with self._lock:
            if method == "sendMessage":
                self._next_message_id += 1
                return {"message_id": self._next_message_id, "chat": {"id": payload.get("chat_id")}}
            if method == "getUpdates":
                offset = int(payload.get("offset") or 0)
                self.updates = [u for u in self.updates if u["update_id"] >= offset]
                return list(self.updates)
            return True

    @staticmethod
    def _reply(h: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)

    # ---------------------------------------------------------------------------------------------- scripting
    def push_text(
        self, text: str | None, *, user_id: int = 111111111, chat_id: int = 111111111, update_id: int | None = None
    ) -> int:
        with self._lock:
            uid = self._next_update_id if update_id is None else update_id
            self._next_update_id = max(self._next_update_id, uid) + 1
            message: dict[str, Any] = {
                "message_id": 5000 + uid, "from": {"id": user_id, "is_bot": False}, "chat": {"id": chat_id},
                "date": 1_700_000_000,
            }
            if text is not None:
                message["text"] = text
            self.updates.append({"update_id": uid, "message": message})
            return 5000 + uid

    def push_raw(self, update: dict[str, Any]) -> None:
        with self._lock:
            self.updates.append(update)

    # ---------------------------------------------------------------------------------------------- reads
    def calls(self, method: str) -> list[dict[str, Any]]:
        """Every request received for `method`, including attempts that failed (down/5xx/4xx)."""
        with self._lock:
            return [r.payload for r in self.requests if r.method == method]

    def delivered_calls(self, method: str) -> list[dict[str, Any]]:
        """Only requests the server accepted (2xx): what the chat actually received."""
        with self._lock:
            return [r.payload for r in self.requests if r.method == method and r.delivered]

    def sent(self, chat_id: int | None = None) -> list[str]:
        return [str(p["text"]) for p in self.delivered_calls("sendMessage") if chat_id is None or p.get("chat_id") == chat_id]

    def edits(self) -> list[dict[str, Any]]:
        return self.calls("editMessageText")

    def deletes(self) -> list[dict[str, Any]]:
        return self.calls("deleteMessage")

    def all_outgoing_text(self) -> str:
        return "\n".join(str(p.get("text", "")) for r in self.requests for p in [r.payload])

    def request_count(self) -> int:
        with self._lock:
            return len(self.requests)
