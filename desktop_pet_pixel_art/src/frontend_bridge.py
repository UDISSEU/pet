"""Authenticated loopback bridge between the web panel and the Tk core."""

import http.server
import json
import logging
import mimetypes
import queue
import secrets
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

RPC_OPERATIONS = frozenset({
    "state.get",
    "chat.send",
    "app.confirm",
    "focus.start",
    "focus.stop",
    "history.delete",
    "history.clear",
    "reminder.add",
    "reminder.complete",
    "reminder.delete",
})
MAX_REQUEST_BYTES = 16_384


@dataclass
class RpcCall:
    request_id: str
    operation: str
    payload: dict
    completed: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    error: dict | None = None
    cancelled: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def complete(self, result=None, error=None):
        with self._lock:
            if self.completed.is_set():
                return False
            self.result = result
            self.error = error
            self.completed.set()
            return True


def validate_rpc_message(data):
    if not isinstance(data, dict) or set(data) != {"version", "id", "op", "payload"}:
        raise ValueError("Formato de requisição inválido.")
    if data["version"] != 1:
        raise ValueError("Versão do protocolo não suportada.")
    request_id = data["id"]
    if not isinstance(request_id, str) or len(request_id) != 36:
        raise ValueError("Identificador de requisição inválido.")
    try:
        if str(uuid.UUID(request_id)) != request_id:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError("Identificador de requisição inválido.") from exc
    operation = data["op"]
    if not isinstance(operation, str) or operation not in RPC_OPERATIONS:
        raise ValueError("Operação não permitida.")
    payload = data["payload"]
    if not isinstance(payload, dict):
        raise ValueError("Os argumentos precisam ser um objeto JSON.")
    return RpcCall(request_id, operation, payload)


class _LoopbackServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, server_address, handler, client_timeout=10, max_clients=16):
        self.client_timeout = client_timeout
        self._client_slots = threading.BoundedSemaphore(max_clients)
        super().__init__(server_address, handler)

    def get_request(self):
        request, client_address = super().get_request()
        try:
            request.settimeout(self.client_timeout)
        except OSError:
            request.close()
            raise
        return request, client_address

    def process_request(self, request, client_address):
        if not self._client_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._client_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._client_slots.release()


class FrontendBridge:
    """Serve bundled UI files and dispatch a small RPC allowlist to Tk."""

    def __init__(self, frontend_dir, icon_path, rpc_timeout=60, client_timeout=10, max_clients=16):
        self.frontend_dir = Path(frontend_dir).resolve()
        self.icon_path = Path(icon_path).resolve()
        self.rpc_timeout = rpc_timeout
        self.requests = queue.Queue(maxsize=32)
        self._bootstrap_token = secrets.token_urlsafe(32)
        self._session_token = secrets.token_urlsafe(32)
        self._bootstrap_used = False
        self._session_lock = threading.Lock()
        self._seen_ids = set()
        self._seen_id_order = deque()
        self._seen_lock = threading.Lock()
        self._thread = None
        self.server = _LoopbackServer(
            ("127.0.0.1", 0), self._make_handler(),
            client_timeout=client_timeout, max_clients=max_clients,
        )
        port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{port}"
        self.server.bridge = self
        self.server.origin = self.origin
        self.server.bootstrap_token = self._bootstrap_token
        self.server.session_token = self._session_token
        self.server.session_lock = self._session_lock
        self.server.bootstrap_used = False
        self.server.rpc_timeout = rpc_timeout
        self.server.requests = self.requests
        self.server.seen_ids = self._seen_ids
        self.server.seen_id_order = self._seen_id_order
        self.server.seen_lock = self._seen_lock
        self.server.frontend_dir = self.frontend_dir
        self.server.icon_path = self.icon_path

    @property
    def launch_url(self):
        # URL fragments are not sent in HTTP requests or Referer headers.
        return f"{self.origin}/#{self._bootstrap_token}"

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self.server.serve_forever,
            name="nova-frontend-http",
            daemon=True,
        )
        self._thread.start()

    def drain_requests(self, limit=16):
        calls = []
        for _ in range(limit):
            try:
                call = self.requests.get_nowait()
            except queue.Empty:
                break
            if not call.cancelled:
                calls.append(call)
        return calls

    def close(self):
        if self._thread is not None:
            self.server.shutdown()
            self.server.server_close()
            self._thread.join(timeout=2)
            self._thread = None

    def _make_handler(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "NovaLocal/1"
            sys_version = ""

            def log_message(self, _format, *_args):
                # Request bodies, URLs, and user messages never enter access logs.
                return

            def _respond(self, status, body=b"", content_type="application/json; charset=utf-8", headers=None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; media-src 'self'; connect-src 'self'; "
                    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                )
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                if body:
                    try:
                        self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def _json(self, status, data, headers=None):
                body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._respond(status, body, headers=headers)

            def _valid_host(self):
                return self.headers.get("Host", "").casefold() == self.server.origin.removeprefix("http://").casefold()

            def _same_origin(self):
                return self.headers.get("Origin") == self.server.origin

            def _read_json(self, limit=MAX_REQUEST_BYTES):
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Transfer-Encoding não é aceito.")
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    raise ValueError("Content-Type deve ser application/json.")
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError as exc:
                    raise ValueError("Content-Length inválido.") from exc
                if length < 0 or length > limit:
                    raise ValueError("Requisição maior que o limite permitido.")
                try:
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("JSON inválido.") from exc

            def _session_authorized(self):
                if not self._same_origin():
                    return False
                cookie = self.headers.get("Cookie", "")
                target = "nova_session="
                for part in cookie.split(";"):
                    part = part.strip()
                    if part.startswith(target):
                        return secrets.compare_digest(
                            part[len(target):], self.server.session_token,
                        )
                return False

            def do_GET(self):
                if not self._valid_host():
                    self._respond(400)
                    return
                if self.path == "/api/v1/health":
                    self._json(200, {"ready": True, "version": 1})
                    return
                static_files = {
                    "/": self.server.frontend_dir / "index.html",
                    "/app.css": self.server.frontend_dir / "app.css",
                    "/app.js": self.server.frontend_dir / "app.js",
                    "/nova-icon.png": self.server.icon_path,
                }
                path = static_files.get(self.path)
                if path is None:
                    self._respond(404)
                    return
                try:
                    body = path.read_bytes()
                except OSError:
                    self._respond(404)
                    return
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                if content_type.startswith(("text/", "application/javascript")):
                    content_type += "; charset=utf-8"
                self._respond(200, body, content_type=content_type)

            def do_POST(self):
                if not self._valid_host() or not self._same_origin():
                    self._json(403, {"ok": False, "error": {"code": "origin", "message": "Origem não autorizada."}})
                    return
                if self.path == "/api/v1/session":
                    self._exchange_session()
                    return
                if self.path != "/api/v1/rpc" or not self._session_authorized():
                    self._json(403, {"ok": False, "error": {"code": "auth", "message": "Sessão local não autorizada."}})
                    return
                self._dispatch_rpc()

            def _exchange_session(self):
                if self.headers.get("Transfer-Encoding"):
                    self._json(400, {"ok": False, "error": {"code": "invalid_request", "message": "Corpo inesperado."}})
                    return
                try:
                    body_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    body_length = -1
                if body_length != 0:
                    self._json(400, {"ok": False, "error": {"code": "invalid_request", "message": "Corpo inesperado."}})
                    return
                authorization = self.headers.get("Authorization", "")
                supplied = authorization.removeprefix("Bearer ")
                with self.server.session_lock:
                    if (
                        self.server.bootstrap_used
                        or not secrets.compare_digest(supplied, self.server.bootstrap_token)
                    ):
                        self._json(403, {"ok": False, "error": {"code": "bootstrap", "message": "Credencial inicial inválida."}})
                        return
                    self.server.bootstrap_used = True
                self._json(200, {"ok": True, "version": 1}, headers={
                    "Set-Cookie": (
                        f"nova_session={self.server.session_token}; Path=/api/v1; "
                        "HttpOnly; SameSite=Strict; Max-Age=86400"
                    ),
                })

            def _dispatch_rpc(self):
                try:
                    call = validate_rpc_message(self._read_json())
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": {"code": "invalid_request", "message": str(exc)}})
                    return
                with self.server.seen_lock:
                    if call.request_id in self.server.seen_ids:
                        self._json(409, {"id": call.request_id, "ok": False, "error": {
                            "code": "duplicate_id", "message": "Esse identificador já foi utilizado.",
                        }})
                        return
                    self.server.seen_ids.add(call.request_id)
                    self.server.seen_id_order.append(call.request_id)
                    while len(self.server.seen_id_order) > 512:
                        self.server.seen_ids.discard(self.server.seen_id_order.popleft())
                try:
                    self.server.requests.put(call, timeout=0.1)
                except queue.Full:
                    self._json(429, {"id": call.request_id, "ok": False, "error": {
                        "code": "busy", "message": "A Nova está ocupada. Tente novamente em instantes.",
                    }})
                    return
                if not call.completed.wait(self.server.rpc_timeout):
                    call.cancelled = True
                    self._json(504, {"id": call.request_id, "ok": False, "error": {
                        "code": "timeout", "message": "A operação demorou mais que o esperado. Confira o estado antes de reenviar.",
                    }})
                    return
                if call.error:
                    self._json(400, {"id": call.request_id, "ok": False, "error": call.error})
                    return
                self._json(200, {"id": call.request_id, "ok": True, "result": call.result})

        return Handler

