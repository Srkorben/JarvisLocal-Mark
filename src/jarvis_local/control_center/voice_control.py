from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


VOICE_CONTROL_ACTIONS = frozenset(
    {
        "start_call",
        "end_call",
        "mute",
        "unmute",
        "start_recording",
        "finish_recording",
        "cancel",
    }
)


class VoiceControlError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class VoiceControlStore:
    """Canal efímero y tipado entre la UI confiable y el runtime de voz.

    Solo transporta gestos de control. No contiene texto, argumentos de
    herramientas, confirmaciones ni autoridad, y nunca se persiste.
    """

    def __init__(self, *, capacity: int = 16) -> None:
        self._condition = threading.Condition()
        self._pending: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._closed = False

    def submit(self, action: object) -> dict[str, Any]:
        if not isinstance(action, str) or action not in VOICE_CONTROL_ACTIONS:
            raise VoiceControlError(
                "invalid_voice_action", "Acción de micrófono no permitida."
            )
        command = {
            "id": str(uuid4()),
            "action": action,
            "submitted_at": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
        }
        with self._condition:
            if self._closed:
                raise VoiceControlError(
                    "voice_control_closed", "El control de voz está detenido."
                )
            if self._pending and self._pending[-1]["action"] == action:
                return dict(self._pending[-1])
            if len(self._pending) == self._pending.maxlen:
                raise VoiceControlError(
                    "voice_control_busy", "Hay demasiadas órdenes de micrófono pendientes."
                )
            self._pending.append(command)
            self._condition.notify_all()
        return dict(command)

    def take(self, *, wait_seconds: float = 0.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.0, min(wait_seconds, 10.0))
        with self._condition:
            while not self._pending and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            if not self._pending:
                return None
            return dict(self._pending.popleft())

    def clear(self) -> None:
        with self._condition:
            self._pending.clear()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()
