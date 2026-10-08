from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .runtime import ControlCenterError, ProcessManager
from .web import render_dashboard


LOGGER = logging.getLogger("jarvis_local.control_center")
MAX_BODY_BYTES = 4096


class ControlCenterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        manager: ProcessManager,
        *,
        auth_token: str,
        csrf_token: str,
        icon_path: Path,
        version: str = "local",
    ) -> None:
        self.manager = manager
        self.auth_token = auth_token
        self.csrf_token = csrf_token
        self.icon_path = icon_path
        self.version = version
        super().__init__(address, ControlCenterRequestHandler)

    @property
    def origin(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


class ControlCenterRequestHandler(BaseHTTPRequestHandler):
    server: ControlCenterHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # BaseHTTPRequestHandler incluye la query completa en su log por defecto.
        # La primera navegación transporta un token de un solo origen, por lo que
        # registramos únicamente método y ruta normalizada, nunca query/cookies.
        LOGGER.info(
            "http client=%s method=%s path=%s",
            self.client_address[0],
            self.command,
            urlsplit(self.path).path,
        )

    def do_GET(self) -> None:  # noqa: N802
        if not self._valid_host():
            self._json_error(HTTPStatus.BAD_REQUEST, "invalid_host", "Host no permitido.")
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "service": "JarvisLocal Control Center"})
            return
        if parsed.path == "/favicon.ico":
            self._favicon()
            return
        query = parse_qs(parsed.query, keep_blank_values=True)
        supplied = query.get("token", [""])[0]
        if supplied and hmac.compare_digest(supplied, self.server.auth_token):
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"jarvis_cc={self.server.auth_token}; HttpOnly; SameSite=Strict; Path=/",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._authenticated():
            self._json_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "Abre el panel desde el acceso directo local.")
            return
        if parsed.path == "/":
            nonce = secrets.token_urlsafe(18)
            body = render_dashboard(
                csrf_token=self.server.csrf_token,
                nonce=nonce,
                version=self.server.version,
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self._security_headers(nonce=nonce)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/tools":
            self._json(HTTPStatus.OK, {"tools": self.server.manager.list_status()})
            return
        self._json_error(HTTPStatus.NOT_FOUND, "not_found", "Ruta no encontrada.")

    def do_POST(self) -> None:  # noqa: N802
        if not self._valid_host():
            self._json_error(HTTPStatus.BAD_REQUEST, "invalid_host", "Host no permitido.")
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/api/server/stop" and self._bearer_authenticated():
            self._json(HTTPStatus.OK, {"result": {"outcome": "stopping"}})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if not self._authenticated():
            self._json_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "Autenticación requerida.")
            return
        if not self._valid_origin() or not hmac.compare_digest(
            self.headers.get("X-CSRF-Token", ""), self.server.csrf_token
        ):
            self._json_error(HTTPStatus.FORBIDDEN, "csrf_rejected", "Solicitud local no confiable.")
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
            return
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 4 or parts[:2] != ["api", "tools"] or parts[3] not in {"start", "stop"}:
            self._json_error(HTTPStatus.NOT_FOUND, "not_found", "Acción no encontrada.")
            return
        tool_id, action = parts[2], parts[3]
        try:
            if action == "start":
                result = self.server.manager.start(
                    tool_id, confirmed=payload.get("confirmed") is True
                )
            else:
                result = self.server.manager.stop(tool_id)
        except ControlCenterError as exc:
            self._json(exc.http_status, {"error": exc.as_dict()})
            return
        self._json(HTTPStatus.OK, {"result": result})

    def _read_json(self) -> dict[str, object]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length inválido.") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("Cuerpo HTTP demasiado grande.")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("JSON inválido.") from exc
        if not isinstance(value, dict) or set(value).difference({"confirmed"}):
            raise ValueError("Solo se acepta el campo tipado 'confirmed'.")
        if "confirmed" in value and not isinstance(value["confirmed"], bool):
            raise ValueError("'confirmed' debe ser booleano.")
        return value

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _valid_origin(self) -> bool:
        origin = self.headers.get("Origin", "")
        return origin in {self.server.origin, self.server.origin.replace("127.0.0.1", "localhost")}

    def _authenticated(self) -> bool:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return False
        item = cookie.get("jarvis_cc")
        return bool(item and hmac.compare_digest(item.value, self.server.auth_token))

    def _bearer_authenticated(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.auth_token}"
        return hmac.compare_digest(supplied, expected)

    def _security_headers(self, *, nonce: str | None = None) -> None:
        script = f"'nonce-{nonce}'" if nonce else "'none'"
        style = f"'nonce-{nonce}'" if nonce else "'none'"
        self.send_header(
            "Content-Security-Policy",
            f"default-src 'none'; script-src {script}; style-src {style}; "
            "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _json(self, status: int, value: dict[str, object]) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: int, code: str, message: str) -> None:
        self._json(status, {"error": {"code": code, "message": message}})

    def _favicon(self) -> None:
        try:
            body = self.server.icon_path.read_bytes()
        except OSError:
            self._json_error(HTTPStatus.NOT_FOUND, "icon_missing", "Icono no disponible.")
            return
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", "image/x-icon")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
