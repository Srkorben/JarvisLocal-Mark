from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import socket
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .runtime import ControlCenterError, ProcessManager
from .presence import PRESENCE_FIELDS, VoicePresenceStore
from .system_status import SystemStatusMonitor
from .text_chat import ChatTranscript, TextChatError, TextChatRequestStore
from .voice_import import VoiceImportError
from .web import render_dashboard


LOGGER = logging.getLogger("jarvis_local.control_center")
MAX_BODY_BYTES = 4096
MAX_VOICE_IMPORT_BODY_BYTES = 34 * 1024 * 1024
# Procesos que publican la presencia de Mark y atienden el chat escrito.
_CONVERSATION_RUNTIMES = frozenset({"voice", "chat_runtime"})


class ControlCenterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # En Windows ``HTTPServer`` permite reutilizar una dirección. Dos árboles
    # de trabajo podrían quedar escuchando el mismo puerto y recibir peticiones
    # de forma no determinista. El panel necesita propiedad exclusiva del bind.
    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(
        self,
        address: tuple[str, int],
        manager: ProcessManager,
        *,
        auth_token: str,
        csrf_token: str,
        icon_path: Path,
        presence: VoicePresenceStore | None = None,
        text_chat: TextChatRequestStore | None = None,
        system_monitor: SystemStatusMonitor | None = None,
        module_snapshot: Callable[[], dict[str, Any]] | None = None,
        voice_importer: Callable[..., dict[str, object]] | None = None,
        version: str = "local",
    ) -> None:
        self.manager = manager
        self.auth_token = auth_token
        self.csrf_token = csrf_token
        self.icon_path = icon_path
        self.presence = presence or VoicePresenceStore()
        self.text_chat = text_chat or TextChatRequestStore()
        self.chat_history = ChatTranscript()
        self.system_monitor = system_monitor
        self.module_snapshot = module_snapshot
        self.voice_importer = voice_importer
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
        log = LOGGER.debug if urlsplit(self.path).path == "/api/chat/next" else LOGGER.info
        log(
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
            self._json(HTTPStatus.OK, {"status": "ok", "service": "Mark Scout Control Center"})
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
        api_bearer = parsed.path in {
            "/api/voice/presence",
            "/api/modules",
            "/api/chat/next",
        } and self._bearer_authenticated()
        if not self._authenticated() and not api_bearer:
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
        if parsed.path == "/api/system":
            if self.server.system_monitor is None:
                self._json_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "system_status_unavailable",
                    "El monitor local no está configurado.",
                )
                return
            try:
                snapshot = self.server.system_monitor.snapshot(
                    self.server.presence.snapshot()
                )
            except Exception:
                LOGGER.exception("No se pudo construir el estado seguro del núcleo.")
                self._json_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "system_status_failed",
                    "No se pudo leer el estado local del núcleo.",
                )
                return
            self._json(HTTPStatus.OK, {"system": snapshot})
            return
        if parsed.path == "/api/voice/presence":
            self._json(HTTPStatus.OK, {"presence": self.server.presence.snapshot()})
            return
        if parsed.path == "/api/chat/history":
            self._json(HTTPStatus.OK, {"turns": self.server.chat_history.snapshot()})
            return
        if parsed.path == "/api/chat/next":
            try:
                raw_wait = parse_qs(parsed.query).get("wait", ["5"])[0]
                wait_seconds = max(0.0, min(float(raw_wait), 10.0))
            except (TypeError, ValueError):
                self._json_error(HTTPStatus.BAD_REQUEST, "invalid_wait", "Espera inválida.")
                return
            self._json(
                HTTPStatus.OK,
                {"request": self.server.text_chat.take(wait_seconds=wait_seconds)},
            )
            return
        if parsed.path == "/api/modules":
            if self.server.module_snapshot is None:
                self._json_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "modules_unavailable",
                    "La vista de módulos no está disponible.",
                )
                return
            try:
                snapshot = self.server.module_snapshot()
            except Exception:
                LOGGER.exception("No se pudo construir la vista segura de módulos.")
                self._json_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "modules_failed",
                    "No se pudo leer la configuración local.",
                )
                return
            self._json(HTTPStatus.OK, snapshot)
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
        if parsed.path == "/api/voice/presence":
            if not self._bearer_authenticated():
                self._json_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "Token interno inválido.")
                return
            try:
                payload = self._read_json(
                    allowed_fields=PRESENCE_FIELDS, max_body_bytes=32_768
                )
                presence = self.server.presence.update(payload)
            except ValueError as exc:
                self._json_error(HTTPStatus.BAD_REQUEST, "invalid_presence", str(exc))
                return
            self.server.chat_history.observe(presence)
            self._json(HTTPStatus.OK, {"presence": presence})
            return
        if not self._authenticated():
            self._json_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "Autenticación requerida.")
            return
        if not self._valid_origin() or not hmac.compare_digest(
            self.headers.get("X-CSRF-Token", ""), self.server.csrf_token
        ):
            self._json_error(HTTPStatus.FORBIDDEN, "csrf_rejected", "Solicitud local no confiable.")
            return
        if parsed.path == "/api/chat":
            try:
                payload = self._read_json(
                    allowed_fields=frozenset({"text", "speak"}),
                    max_body_bytes=16_384,
                )
                text = payload.get("text")
                speak = payload.get("speak", True)
                request = self.server.text_chat.submit(text, speak)
                try:
                    runtime = self._ensure_chat_runtime()
                except Exception:
                    self.server.text_chat.discard(request["id"])
                    raise
                self.server.chat_history.start(request)
                self.server.presence.update(
                    {
                        "state": "queued",
                        "transcript": request["text"],
                        "response": "",
                        "error": "",
                    }
                )
            except TextChatError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": exc.as_dict()})
                return
            except ControlCenterError as exc:
                self._json(exc.http_status, {"error": exc.as_dict()})
                return
            except ValueError as exc:
                self._json_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
                return
            self._json(
                HTTPStatus.ACCEPTED,
                {
                    "result": {
                        "outcome": "queued",
                        "request_id": request["id"],
                        "runtime": runtime["outcome"],
                    }
                },
            )
            return
        if parsed.path == "/api/chat/cancel":
            try:
                self._read_json(allowed_fields=frozenset())
                result = self.server.text_chat.cancel()
                self.server.chat_history.mark_cancel()
            except TextChatError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": exc.as_dict()})
                return
            except ValueError as exc:
                self._json_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
                return
            self._json(HTTPStatus.OK, {"result": result})
            return
        if parsed.path == "/api/chat/history/clear":
            try:
                self._read_json(allowed_fields=frozenset())
            except ValueError as exc:
                self._json_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
                return
            removed = self.server.chat_history.clear()
            self._json(HTTPStatus.OK, {"result": {"outcome": "cleared", "removed": removed}})
            return
        if parsed.path == "/api/voice/reference/import":
            if self.server.voice_importer is None:
                self._json_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "voice_import_unavailable",
                    "La importación local de voz no está configurada.",
                )
                return
            if any(
                item["id"] in {"voice", "enroll_voice"}
                and item["status"] == "running"
                for item in self.server.manager.list_status()
            ):
                self._json_error(
                    HTTPStatus.CONFLICT,
                    "voice_runtime_active",
                    "Detén la conversación o grabación de voz antes de cambiar la referencia.",
                )
                return
            try:
                payload = self._read_json(
                    allowed_fields=frozenset(
                        {
                            "filename",
                            "audio_base64",
                            "authorization_confirmed",
                            "replace_existing",
                        }
                    ),
                    max_body_bytes=MAX_VOICE_IMPORT_BODY_BYTES,
                )
                if not isinstance(payload.get("filename"), str) or not isinstance(
                    payload.get("audio_base64"), str
                ):
                    raise ValueError("filename y audio_base64 deben ser texto.")
                if not isinstance(
                    payload.get("authorization_confirmed"), bool
                ) or not isinstance(payload.get("replace_existing"), bool):
                    raise ValueError("Las confirmaciones de importación deben ser booleanas.")
                result = self.server.voice_importer(**payload)
            except VoiceImportError as exc:
                self._json(exc.http_status, {"error": exc.as_dict()})
                return
            except ValueError as exc:
                self._json_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
                return
            except Exception:
                LOGGER.exception("Falló la importación local de referencia de voz.")
                self._json_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "voice_import_failed",
                    "No se pudo importar la referencia de voz.",
                )
                return
            self._json(HTTPStatus.OK, {"result": result})
            return
        try:
            payload = self._read_json(allowed_fields=frozenset({"confirmed"}))
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
                if tool_id == "voice" and self._tool_running("chat_runtime"):
                    # La voz atiende también el chat escrito: el runtime de
                    # texto cede el LLM para no cargar dos copias del modelo.
                    self.server.manager.stop("chat_runtime")
                    # Un turno escrito en curso se pierde con el runtime de texto.
                    self.server.chat_history.observe({"state": "offline"})
                result = self.server.manager.start(
                    tool_id, confirmed=payload.get("confirmed") is True
                )
                if tool_id in _CONVERSATION_RUNTIMES:
                    self.server.presence.update(
                        {"state": "loading", "transcript": "", "response": "", "error": ""}
                    )
            else:
                result = self.server.manager.stop(tool_id)
                if tool_id in _CONVERSATION_RUNTIMES:
                    self.server.chat_history.observe(
                        self.server.presence.update(
                            {"state": "offline", "transcript": "", "response": "", "error": ""}
                        )
                    )
        except ControlCenterError as exc:
            self._json(exc.http_status, {"error": exc.as_dict()})
            return
        self._json(HTTPStatus.OK, {"result": result})

    def _tool_running(self, tool_id: str) -> bool:
        return any(
            item["id"] == tool_id and item["status"] == "running"
            for item in self.server.manager.list_status()
        )

    def _ensure_chat_runtime(self) -> dict[str, object]:
        """Elige quién responde al chat escrito sin cargar audio innecesario.

        Si la conversación por voz ya está activa, ella consume la cola. Si no,
        se inicia el runtime de texto, que solo carga el LLM.
        """

        if self._tool_running("voice"):
            return {"outcome": "already_running", "tool_id": "voice"}
        return self.server.manager.start("chat_runtime")

    def _read_json(
        self,
        *,
        allowed_fields: frozenset[str],
        max_body_bytes: int = MAX_BODY_BYTES,
    ) -> dict[str, object]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length inválido.") from exc
        if length < 0 or length > max_body_bytes:
            raise ValueError("Cuerpo HTTP demasiado grande.")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("JSON inválido.") from exc
        if not isinstance(value, dict) or set(value).difference(allowed_fields):
            raise ValueError("La solicitud contiene campos no permitidos.")
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
            "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
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
