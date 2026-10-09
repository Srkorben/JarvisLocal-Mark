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

    def close(self) -> None:
        self.state = "offline"
        self._publish()

    def _publish(self) -> None:
        payload = json.dumps(
            {
                "state": self.state,
                "transcript": self.transcript,
                "response": self.response,
                "error": self.error,
            },
            ensure_ascii=False,
        ).encode("utf-8")
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
