from __future__ import annotations

import http.client
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VOICE_STATES = frozenset(
    {
        "offline",
        "loading",
        "queued",
        "idle",
        "recording",
        "transcribing",
        "processing",
        "speaking",
        "cancelling",
        "error",
    }
)
PRESENCE_FIELDS = frozenset({"state", "transcript", "response", "error"})


class VoicePresenceStore:
    """Estado efímero para la interfaz; nunca persiste conversación ni audio."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._revision = 0
        self._value: dict[str, Any] = {
            "state": "offline",
            "transcript": "",
            "response": "",
            "error": "",
            "revision": 0,
            "updated_at": _utc_now(),
        }

    def update(self, payload: dict[str, object]) -> dict[str, Any]:
        extra = set(payload).difference(PRESENCE_FIELDS)
        if extra:
            raise ValueError("Campos de presencia no permitidos: " + ", ".join(sorted(extra)))
        state = payload.get("state")
        if not isinstance(state, str) or state not in VOICE_STATES:
            raise ValueError("Estado de voz inválido.")
        normalized: dict[str, str] = {"state": state}
        for field, limit in (("transcript", 4096), ("response", 16_384), ("error", 2048)):
            value = payload.get(field, "")
            if not isinstance(value, str):
                raise ValueError(f"'{field}' debe ser texto.")
            normalized[field] = value[:limit]
        with self._lock:
            self._revision += 1
            self._value = {
                **normalized,
                "revision": self._revision,
                "updated_at": _utc_now(),
            }
            return dict(self._value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._value)


class VoicePresenceClient:
    """Publica telemetría visual al panel local autenticado.

    Es opcional y falla abierto respecto a la conversación: si la UI no está
    disponible, la voz continúa funcionando. No transmite PCM ni escribe estado
    conversacional en disco.
    """

    def __init__(self, *, port: int, token: str, timeout_seconds: float = 0.35) -> None:
        self.port = port
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.state = "idle"
        self.transcript = ""
        self.response = ""
        self.error = ""
        self._last_delta_publish = 0.0
        # La publicación es telemetría visual: se delega a un hilo para que una
        # UI lenta nunca bloquee el bucle de voz (hotkeys, cancelación, TTS).
        # Solo importa el estado más reciente, así que los intermedios se
        # sustituyen en lugar de encolarse.
        self._outbox: bytes | None = None
        self._outbox_condition = threading.Condition()
        self._sender: threading.Thread | None = None
        self._closing = False
        self._queued = 0
        self._delivered = 0

    @classmethod
    def discover(cls, project_root: Path) -> "VoicePresenceClient | None":
        path = project_root / "data" / "control_center" / "endpoint.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        port = value.get("port") if isinstance(value, dict) else None
        token = value.get("token") if isinstance(value, dict) else None
        bind = value.get("bind") if isinstance(value, dict) else None
        if (
            not isinstance(port, int)
            or not 1 <= port <= 65535
            or not isinstance(token, str)
            or len(token) < 24
            or bind != "127.0.0.1"
        ):
            return None
        return cls(port=port, token=token)

    def begin_turn(self) -> None:
        self.transcript = ""
        self.response = ""
        self.error = ""
        self.set_state("recording")

    def set_state(self, state: str) -> None:
        if state not in VOICE_STATES:
            return
        if state == "recording" and self.state != "recording":
            self.transcript = ""
            self.response = ""
            self.error = ""
        self.state = state
        self._publish()

    def set_transcript(self, text: str) -> None:
        self.transcript = text[:4096]
        self._publish()

    def append_response(self, delta: str) -> None:
        self.response = (self.response + delta)[-16_384:]
        now = time.monotonic()
        if now - self._last_delta_publish >= 0.15:
            self._last_delta_publish = now
            self._publish()

    def set_error(self, message: str) -> None:
        self.error = message[:2048]
        self._publish()

    def close(self, *, flush_timeout: float = 1.0) -> None:
        self.state = "offline"
        self._publish()
        with self._outbox_condition:
            self._closing = True
            self._outbox_condition.notify_all()
            sender = self._sender
        if sender is not None:
            sender.join(timeout=flush_timeout)

    def fetch_text_request(self, *, wait_seconds: float = 5.0) -> dict[str, Any] | None:
        """Obtiene una solicitud escrita efímera desde el panel autenticado."""

        connection = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=max(1.0, wait_seconds + 1.0)
        )
        try:
            connection.request(
                "GET",
                f"/api/chat/next?wait={max(0.0, min(wait_seconds, 10.0)):g}",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            request = payload.get("request") if response.status == 200 else None
            if not isinstance(request, dict):
                return None
            request_id = request.get("id")
            text = request.get("text")
            speak = request.get("speak")
            if (
                not isinstance(request_id, str)
                or not isinstance(text, str)
                or not text.strip()
                or not isinstance(speak, bool)
            ):
                return None
            submitted_at = request.get("submitted_at")
            result: dict[str, Any] = {"id": request_id, "text": text, "speak": speak}
            if isinstance(submitted_at, str):
                result["submitted_at"] = submitted_at
            return result
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        finally:
            connection.close()

    def _publish(self) -> None:
        payload = self._payload()
        # Los estados terminales se publican justo antes de que el proceso
        # termine: se espera su entrega (acotada) para que la UI no los pierda.
        terminal = self.state in {"error", "offline"}
        with self._outbox_condition:
            if self._closing and self._sender is None:
                return
            self._outbox = payload
            self._queued += 1
            generation = self._queued
            if self._sender is None:
                self._sender = threading.Thread(
                    target=self._send_loop, name="mark-presence-publisher", daemon=True
                )
                self._sender.start()
            self._outbox_condition.notify_all()
            if terminal:
                self._outbox_condition.wait_for(
                    lambda: self._delivered >= generation,
                    timeout=self.timeout_seconds + 0.5,
                )

    def _send_loop(self) -> None:
        while True:
            with self._outbox_condition:
                while self._outbox is None and not self._closing:
                    self._outbox_condition.wait()
                payload = self._outbox
                self._outbox = None
                generation = self._queued
                if payload is None:
                    return
            self._send(payload)
            with self._outbox_condition:
                self._delivered = generation
                self._outbox_condition.notify_all()

    def _payload(self) -> bytes:
        return json.dumps(
            {
                "state": self.state,
                "transcript": self.transcript,
                "response": self.response,
                "error": self.error,
            },
            ensure_ascii=False,
        ).encode("utf-8")

    def _send(self, payload: bytes) -> None:
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=self.timeout_seconds
        )
        try:
            connection.request(
                "POST",
                "/api/voice/presence",
                body=payload,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json; charset=utf-8",
                    "Content-Length": str(len(payload)),
                },
            )
            response = connection.getresponse()
            response.read()
        except OSError:
            return
        finally:
            connection.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
